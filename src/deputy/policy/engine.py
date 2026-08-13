"""The gate every action passes through.

The engine answers one question: may this agent do this thing right now.
It answers with a verdict and a trace of how it got there, because a policy
decision nobody can explain is one nobody will trust enough to leave running
unattended.

Three properties are enforced here rather than left to convention:

  fail closed        An action with no matching rule is denied, not allowed.
  monotone           When rules disagree, the most restrictive wins, so
                     adding a rule can never widen authority.
  rate limits count  Approvals and denials do not consume budget; only
                     actions that actually ran do.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from deputy.policy.rules import Action, Rule, RuleSet, Verdict
from deputy.store.audit import AuditLog

if TYPE_CHECKING:  # pragma: no cover
    from deputy.policy.approvals import ApprovalStore

DAY = 86_400.0
WEEK = 7 * DAY


def _rules_of(detail: dict) -> list[str]:
    """Rule names an audit entry was booked against.

    Tolerates the older single-`rule` shape so a log written before the fix
    still reads. Silently returning nothing for those would understate usage
    and quietly reopen a cap.
    """
    names = detail.get("rules")
    if isinstance(names, list):
        return [str(n) for n in names]
    single = detail.get("rule")
    return [str(single)] if single else []


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    action: Action
    because: str
    matched: tuple[str, ...] = ()
    trace: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW

    @property
    def needs_approval(self) -> bool:
        return self.verdict is Verdict.REQUIRE_APPROVAL

    @property
    def denied(self) -> bool:
        return self.verdict is Verdict.DENY

    def explain(self) -> str:
        lines = [f"{self.verdict.name} {self.action.name}", f"  because: {self.because}"]
        if self.matched:
            lines.append(f"  matched rules: {', '.join(self.matched)}")
        lines.extend(f"  {line}" for line in self.trace)
        return "\n".join(lines)


@dataclass
class PolicyEngine:
    """Evaluates actions against a ruleset, with rate limiting and audit."""

    rules: RuleSet
    audit: AuditLog | None = None
    clock: Callable[[], float] = time.time
    #: When set, approvals are durable and survive a restart. When None, they
    #: are held in memory for the life of the process, which is fine for a
    #: test and wrong for anything scheduled.
    approvals: "ApprovalStore | None" = None
    _memory: dict[str, int] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------- decide

    def check(self, action: Action) -> Decision:
        matched = self.rules.matching(action)

        if not matched:
            return Decision(
                verdict=self.rules.default,
                action=action,
                because=self.rules.default_because,
                trace=(f"no rule matched {action.name!r}",),
            )

        verdict = max(rule.verdict for rule in matched)
        deciding = [r for r in matched if r.verdict == verdict]
        trace = [
            f"{rule.name}: {rule.verdict.name}" + (f" ({rule.because})" if rule.because else "")
            for rule in matched
        ]

        # Rate limits only tighten. A rule that would have allowed the action
        # becomes an approval request once its budget for the window is spent,
        # rather than a hard denial, because the human is the release valve.
        if verdict is Verdict.ALLOW:
            breach = self._rate_limited(matched)
            if breach is not None:
                rule, window, used, cap = breach
                return Decision(
                    verdict=Verdict.REQUIRE_APPROVAL,
                    action=action,
                    because=f"{rule.name} is at its {window} limit ({used}/{cap})",
                    matched=tuple(r.name for r in matched),
                    trace=tuple(trace + [f"rate limit reached on {rule.name}"]),
                )

        because = next(
            (r.because for r in deciding if r.because),
            f"matched {deciding[0].name}",
        )
        return Decision(
            verdict=verdict,
            action=action,
            because=because,
            matched=tuple(r.name for r in matched),
            trace=tuple(trace),
        )

    def _rate_limited(self, rules: list[Rule]) -> tuple[Rule, str, int, int] | None:
        if self.audit is None:
            return None
        # `is not None`, not truthiness. `limit_per_day: 0` is a cap of zero,
        # which means "never", and the falsy check treated it as "no cap set"
        # and allowed everything. A zero written deliberately into a policy
        # file is the strictest thing a person can write there.
        capped = [
            r for r in rules if r.limit_per_day is not None or r.limit_per_week is not None
        ]
        if not capped:
            return None

        now = self.clock()
        performed = [
            e for e in self.audit.read() if e.action == "act" and e.outcome == "performed"
        ]

        for rule in capped:
            for window_name, span, cap in (
                ("daily", DAY, rule.limit_per_day),
                ("weekly", WEEK, rule.limit_per_week),
            ):
                if cap is None:
                    continue
                # Consumption is booked against every rule that authorised the
                # action, not just one, so `rules` here is checked against a
                # list. Recording a single rule name meant a capped rule that
                # happened to sit below an uncapped one in the file never
                # accumulated anything and its cap silently did not exist,
                # despite the policy file promising that order carries no
                # meaning.
                used = sum(
                    1
                    for e in performed
                    if rule.name in _rules_of(e.detail) and now - e.at < span
                )
                if used >= cap:
                    return rule, window_name, used, cap
        return None

    # ------------------------------------------------------------ approve

    def grant(self, action_key: str, *, uses: int = 1, by: str = "human", **kw) -> None:
        """Record a human approval, consumed on use.

        Single use by default, and the default is the whole point. An approval
        that persists is not an approval of an action, it is a permanent grant
        of a capability, obtained by clicking yes once. Worse, because a
        breached rate limit downgrades to REQUIRE_APPROVAL rather than DENY,
        a standing approval silently converts a capped rule into an uncapped
        one. Ask for `uses` above one only when the human was shown the count.
        """
        if uses < 1:
            raise ValueError("uses must be at least 1")
        if self.approvals is not None:
            if self.approvals.get(action_key) is None:
                name, _, subject = action_key.partition(":")
                self.approvals.request(action_key, name, subject, "granted directly")
            self.approvals.grant(action_key, uses=uses, by=by, **kw)
            return
        self._memory[action_key] = self._memory.get(action_key, 0) + uses

    def revoke(self, action_key: str) -> None:
        if self.approvals is not None:
            if self.approvals.get(action_key) is not None:
                self.approvals.deny(action_key, by="revoked")
            return
        self._memory.pop(action_key, None)

    def is_granted(self, action_key: str) -> bool:
        """Whether an unspent approval exists. Does not consume it."""
        if self.approvals is not None:
            approval = self.approvals.get(action_key)
            return approval is not None and approval.is_usable(self.clock())
        return self._memory.get(action_key, 0) > 0

    def _consume(self, action_key: str) -> bool:
        if self.approvals is not None:
            return self.approvals.consume(action_key)
        remaining = self._memory.get(action_key, 0)
        if remaining <= 0:
            return False
        remaining -= 1
        if remaining:
            self._memory[action_key] = remaining
        else:
            self._memory.pop(action_key, None)
        return True

    def request_approval(self, action: Action, decision: "Decision") -> None:
        """Kept for callers that park an action they did not route via authorize."""
        if self.approvals is None:
            return
        self.approvals.request(
            self.key(action), action.name, action.subject, decision.because
        )

    # -------------------------------------------------------------- guard

    def authorize(self, action: Action, *, actor: str = "agent") -> Decision:
        """Decide, record the decision, and return it.

        An approval granted earlier upgrades a REQUIRE_APPROVAL to ALLOW. It
        never upgrades a DENY. A denied action is denied because the system
        is not permitted to take it at all, and a human clicking approve in a
        chat window is not the right place to override that.
        """
        decision = self.check(action)

        if decision.needs_approval and self._consume(self.key(action)):
            decision = Decision(
                verdict=Verdict.ALLOW,
                action=action,
                because="approved by a human for this specific action",
                matched=decision.matched,
                trace=decision.trace + ("approval consumed",),
            )

        # Park the request here, in the engine, rather than relying on every
        # caller to remember. A pending approval that exists only when the
        # agent thought to record it is the same class of bug as a capability
        # check the caller is expected to remember to run.
        if decision.needs_approval and self.approvals is not None:
            self.approvals.request(
                self.key(action), action.name, action.subject, decision.because
            )

        if self.audit is not None:
            self.audit.append(
                actor=actor,
                action="policy",
                subject=action.name,
                outcome=decision.verdict.name.lower(),
                detail={
                    "because": decision.because,
                    "target": action.subject,
                    "matched": list(decision.matched),
                },
            )
        return decision

    @staticmethod
    def key(action: Action) -> str:
        """A collision-free approval key.

        Naive `f"{name}:{subject}"` is not injective: ("post", "issue:42") and
        ("post:issue", "42") both render as "post:issue:42", so approving one
        authorises the other. Subjects come from model output, so the
        colliding half is attacker-influenced. Length-prefixing removes the
        ambiguity.
        """
        return f"{len(action.name)}:{action.name}:{action.subject}"

    def record_performed(
        self, action: Action, rules: str | list[str] | tuple[str, ...], *, actor: str = "agent"
    ) -> None:
        """Mark an action as carried out, against every rule that allowed it."""
        if self.audit is None:
            return
        names = [rules] if isinstance(rules, str) else list(rules)
        # The timestamp comes from the engine's clock, not the log's default.
        # If the two disagree, every rate-limit window is measured against a
        # different time source than the one that wrote the entries, and the
        # cap either never trips or never releases. Found by a test that
        # advanced an injected clock and watched yesterday's actions keep
        # counting; see docs/postmortems/0002-clock-skew-in-rate-limits.md.
        self.audit.append(
            actor=actor,
            action="act",
            subject=action.subject or action.name,
            outcome="performed",
            detail={"rules": names, "action": action.name},
            at=self.clock(),
        )
