"""Policy engine tests.

These are the tests that matter most in the repo. Everything else failing
produces a wrong answer; this failing produces an agent that does something
it was not permitted to do.
"""

from __future__ import annotations

import pytest

from deputy.policy.engine import PolicyEngine
from deputy.policy.rules import Action, Rule, RuleSet, Verdict, load_rules
from deputy.store.audit import AuditLog


def ruleset(*rules: Rule, default: Verdict = Verdict.DENY) -> RuleSet:
    return RuleSet(rules=list(rules), default=default)


def test_unmatched_action_is_denied_not_allowed():
    engine = PolicyEngine(rules=ruleset())
    decision = engine.check(Action(name="send_email"))
    assert decision.denied
    assert "fails closed" in decision.because


def test_most_restrictive_verdict_wins_regardless_of_order():
    permissive = Rule(name="broad", match="*", verdict=Verdict.ALLOW)
    strict = Rule(name="narrow", match="delete_*", verdict=Verdict.DENY)

    forward = PolicyEngine(rules=ruleset(permissive, strict))
    reverse = PolicyEngine(rules=ruleset(strict, permissive))
    action = Action(name="delete_account")

    assert forward.check(action).denied
    assert reverse.check(action).denied


def test_adding_a_rule_can_never_widen_authority():
    """The monotonicity property, stated as a test so it cannot regress."""
    base = [Rule(name="a", match="post_*", verdict=Verdict.REQUIRE_APPROVAL)]
    action = Action(name="post_comment")

    before = PolicyEngine(rules=ruleset(*base)).check(action).verdict
    widened = base + [Rule(name="b", match="post_comment", verdict=Verdict.ALLOW)]
    after = PolicyEngine(rules=ruleset(*widened)).check(action).verdict

    assert after >= before


def test_attribute_predicates_gate_on_reversibility():
    rules = ruleset(
        Rule(name="allow-all", match="*", verdict=Verdict.ALLOW),
        Rule(
            name="gate-irreversible",
            match="*",
            verdict=Verdict.REQUIRE_APPROVAL,
            when={"reversible": False},
        ),
    )
    engine = PolicyEngine(rules=rules)

    assert engine.check(Action(name="draft", reversible=True)).allowed
    assert engine.check(Action(name="send", reversible=False)).needs_approval


def test_approval_upgrades_require_approval_but_never_a_deny():
    rules = ruleset(
        Rule(name="gate", match="post_*", verdict=Verdict.REQUIRE_APPROVAL),
        Rule(name="forbid", match="delete_*", verdict=Verdict.DENY),
    )
    engine = PolicyEngine(rules=rules)

    gated = Action(name="post_comment", subject="42")
    engine.grant(PolicyEngine.key(gated))
    assert engine.authorize(gated).allowed

    forbidden = Action(name="delete_repo", subject="42")
    engine.grant(PolicyEngine.key(forbidden))
    assert engine.authorize(forbidden).denied, "a human approval must not override a deny"


def test_approval_is_scoped_to_one_subject():
    engine = PolicyEngine(
        rules=ruleset(Rule(name="gate", match="post_*", verdict=Verdict.REQUIRE_APPROVAL))
    )
    engine.grant(PolicyEngine.key(Action(name="post_comment", subject="42")))

    assert engine.authorize(Action(name="post_comment", subject="42")).allowed
    assert engine.authorize(Action(name="post_comment", subject="99")).needs_approval


def test_approval_is_consumed_by_one_use():
    """A grant authorises an action, not a capability.

    Without consumption, clicking approve once converts the gate into a
    permanent allow. It also converts a capped rule into an uncapped one,
    because a breached cap downgrades to REQUIRE_APPROVAL rather than DENY.
    """
    engine = PolicyEngine(
        rules=ruleset(Rule(name="gate", match="send_*", verdict=Verdict.REQUIRE_APPROVAL))
    )
    action = Action(name="send_email", subject="ceo@example.com")
    engine.grant(PolicyEngine.key(action))

    assert engine.authorize(action).allowed
    assert engine.authorize(action).needs_approval, "the grant must not be standing"


def test_multiple_uses_can_be_granted_explicitly():
    engine = PolicyEngine(
        rules=ruleset(Rule(name="gate", match="send_*", verdict=Verdict.REQUIRE_APPROVAL))
    )
    action = Action(name="send_email", subject="a")
    engine.grant(PolicyEngine.key(action), uses=2)

    assert engine.authorize(action).allowed
    assert engine.authorize(action).allowed
    assert engine.authorize(action).needs_approval


def test_approval_keys_cannot_collide():
    """f"{name}:{subject}" is not injective, and subjects come from the model."""
    a = PolicyEngine.key(Action(name="post", subject="issue:42"))
    b = PolicyEngine.key(Action(name="post:issue", subject="42"))
    assert a != b


def test_a_cap_of_zero_means_never(tmp_path):
    """`limit_per_day: 0` was falsy and read as 'no cap set'."""
    audit = AuditLog(tmp_path / "audit.jsonl")
    engine = PolicyEngine(
        rules=ruleset(Rule(name="capped", match="label", verdict=Verdict.ALLOW, limit_per_day=0)),
        audit=audit,
    )
    assert engine.check(Action(name="label", subject="x")).needs_approval


def test_cap_is_enforced_even_when_an_uncapped_rule_also_matches(tmp_path):
    """Consumption is booked against every matching rule, not just the first.

    Booking against one meant a capped rule sitting below an uncapped one in
    the file accumulated nothing, so its cap silently did not exist. The
    policy file promises that rule order carries no meaning; this is the test
    that makes that true.
    """
    audit = AuditLog(tmp_path / "audit.jsonl")
    rules = ruleset(
        Rule(name="broad", match="*", verdict=Verdict.ALLOW),
        Rule(name="capped", match="label", verdict=Verdict.ALLOW, limit_per_day=2),
    )
    engine = PolicyEngine(rules=rules, audit=audit)
    action = Action(name="label", subject="x")

    for _ in range(2):
        assert engine.check(action).allowed
        engine.record_performed(action, ["broad", "capped"])

    assert engine.check(action).needs_approval


def test_rate_limit_downgrades_allow_to_approval(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    rules = ruleset(Rule(name="capped", match="label", verdict=Verdict.ALLOW, limit_per_day=2))
    engine = PolicyEngine(rules=rules, audit=audit)
    action = Action(name="label", subject="x")

    assert engine.check(action).allowed
    engine.record_performed(action, "capped")
    assert engine.check(action).allowed
    engine.record_performed(action, "capped")

    third = engine.check(action)
    assert third.needs_approval, "the cap should ask a human, not hard-deny"
    assert "daily limit" in third.because


def test_rate_limit_counts_only_actions_that_ran(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    rules = ruleset(Rule(name="capped", match="label", verdict=Verdict.ALLOW, limit_per_day=1))
    engine = PolicyEngine(rules=rules, audit=audit)
    action = Action(name="label", subject="x")

    for _ in range(5):
        engine.authorize(action)  # decisions logged, nothing performed

    assert engine.check(action).allowed, "checking must not consume budget"


def test_rate_limit_window_expires(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    rules = ruleset(Rule(name="capped", match="label", verdict=Verdict.ALLOW, limit_per_day=1))
    now = [1_000_000.0]
    engine = PolicyEngine(rules=rules, audit=audit, clock=lambda: now[0])
    action = Action(name="label", subject="x")

    engine.record_performed(action, "capped")
    assert engine.check(action).needs_approval

    now[0] += 86_401
    assert engine.check(action).allowed, "yesterday's actions must not count today"


def test_decision_explains_itself():
    rules = ruleset(
        Rule(
            name="gate",
            match="send_*",
            verdict=Verdict.REQUIRE_APPROVAL,
            because="email cannot be unsent",
        )
    )
    text = PolicyEngine(rules=rules).check(Action(name="send_email")).explain()
    assert "REQUIRE_APPROVAL" in text
    assert "email cannot be unsent" in text


class TestPolicyFile:
    def test_loads_the_shipped_triage_policy(self):
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "examples" / "triage" / "policy.md"
        rules = load_rules(path)
        assert len(rules) >= 6
        assert rules.default is Verdict.DENY

    def test_quoted_glob_actually_matches(self, tmp_path):
        """Regression: a quoted "*" was stored with its quotes and matched nothing.

        The symptom was the worst possible one, a catch-all safety rule that
        silently never fired, so irreversible actions fell through to the
        default instead of being gated.
        """
        policy = tmp_path / "p.md"
        policy.write_text(
            "---\ndefault: allow\n---\n\n"
            '## catch-all\n\nmatch: "*"\nwhen_reversible: false\nverdict: require_approval\n',
            encoding="utf-8",
        )
        engine = PolicyEngine(rules=load_rules(policy))
        assert engine.check(Action(name="anything", reversible=False)).needs_approval

    def test_bad_verdict_is_rejected_loudly(self, tmp_path):
        policy = tmp_path / "p.md"
        policy.write_text(
            "---\ndefault: deny\n---\n\n## r\n\nmatch: x\nverdict: maybe\n", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="unknown verdict"):
            load_rules(policy)

    def test_rule_without_verdict_is_rejected(self, tmp_path):
        policy = tmp_path / "p.md"
        policy.write_text("---\ndefault: deny\n---\n\n## r\n\nmatch: x\n", encoding="utf-8")
        with pytest.raises(ValueError, match="no 'verdict'"):
            load_rules(policy)


def test_when_predicates_are_typed_like_the_attributes_they_match(tmp_path):
    """Non-boolean predicates stayed strings and never matched anything.

    `when_amount: 5000` was the string "5000", which never equals the integer
    5000, so the DENY rule it guarded matched nothing while reading correctly
    in the file. Same failure class as the quoted-glob bug: fixed for the
    class, not the symptom.
    """
    policy = tmp_path / "p.md"
    policy.write_text(
        "---\ndefault: allow\n---\n\n"
        "## block-large-payments\n\nmatch: pay_*\nwhen_amount: 5000\nverdict: deny\n",
        encoding="utf-8",
    )
    engine = PolicyEngine(rules=load_rules(policy))
    assert engine.check(Action(name="pay_send", attrs={"amount": 5000})).denied


def test_quoting_a_predicate_keeps_it_a_string(tmp_path):
    policy = tmp_path / "p.md"
    policy.write_text(
        '---\ndefault: allow\n---\n\n## r\n\nmatch: "*"\nwhen_flag: "false"\nverdict: deny\n',
        encoding="utf-8",
    )
    engine = PolicyEngine(rules=load_rules(policy))
    assert engine.check(Action(name="x", attrs={"flag": "false"})).denied
    assert engine.check(Action(name="x", attrs={"flag": False})).allowed


def test_monotonicity_holds_over_generated_rulesets():
    """The property, checked over random rulesets rather than one example.

    Scoped to actions that already match at least one rule. Across the
    fail-closed default the property genuinely does not hold, because adding
    the first matching rule is how authority gets granted at all.
    """
    import random

    rng = random.Random(11)
    verdicts = list(Verdict)
    for _ in range(300):
        base = [
            Rule(name=f"r{i}", match=rng.choice(["a_*", "*", "a_go"]),
                 verdict=rng.choice(verdicts))
            for i in range(rng.randint(1, 4))
        ]
        action = Action(name="a_go", reversible=rng.choice([True, False]))
        engine = PolicyEngine(rules=ruleset(*base))
        if not engine.rules.matching(action):
            continue
        before = engine.check(action).verdict
        extra = Rule(name="extra", match=rng.choice(["a_*", "*", "a_go"]),
                     verdict=rng.choice(verdicts))
        after = PolicyEngine(rules=ruleset(*base, extra)).check(action).verdict
        assert after >= before, f"widened: {before.name} -> {after.name}"


class TestDurableApprovals:
    """Approvals must outlive the process that asked for them."""

    def _store(self, tmp_path, clock=None):
        from deputy.policy.approvals import ApprovalStore
        from deputy.store.vault import Vault

        vault = Vault(tmp_path / "vault", git=False)
        return ApprovalStore(vault, clock=clock or (lambda: 1_000_000.0))

    def test_a_pending_request_survives_a_new_process(self, tmp_path):
        """The whole point. An in-memory queue loses the question silently."""
        from deputy.policy.approvals import ApprovalStore
        from deputy.store.vault import Vault

        store = self._store(tmp_path)
        store.request("post:42", "post_comment", "42", "irreversible")

        reopened = ApprovalStore(Vault(tmp_path / "vault", git=False))
        assert [a.key for a in reopened.pending()] == ["post:42"]

    def test_engine_backed_by_a_store_honours_a_grant_after_restart(self, tmp_path):
        from deputy.policy.approvals import ApprovalStore
        from deputy.store.vault import Vault

        rules = ruleset(Rule(name="gate", match="post_*", verdict=Verdict.REQUIRE_APPROVAL))
        action = Action(name="post_comment", subject="42")
        clock = lambda: 1_000_000.0  # noqa: E731

        first = PolicyEngine(
            rules=rules, approvals=self._store(tmp_path, clock), clock=clock
        )
        assert first.authorize(action).needs_approval
        first.approvals.grant(PolicyEngine.key(action), by="junaid")

        second = PolicyEngine(
            rules=rules,
            approvals=ApprovalStore(Vault(tmp_path / "vault", git=False), clock=clock),
            clock=clock,
        )
        assert second.authorize(action).allowed, "the grant must survive the restart"
        assert second.authorize(action).needs_approval, "and still be single use"

    def test_a_grant_lapses_after_its_ttl(self, tmp_path):
        now = [1_000_000.0]
        store = self._store(tmp_path, lambda: now[0])
        store.request("k", "send", "x", "because")
        store.grant("k", ttl_s=3600)

        now[0] += 3599
        assert store.get("k").is_usable(now[0])
        now[0] += 2
        assert not store.consume("k"), "an expired grant must not authorise anything"
        assert store.get("k").state == "lapsed"

    def test_expiry_is_evaluated_at_use_not_by_a_sweep(self, tmp_path):
        """A system that needs a cleanup job to have run fails open when it has not."""
        now = [1_000_000.0]
        store = self._store(tmp_path, lambda: now[0])
        store.request("k", "send", "x", "b")
        store.grant("k", ttl_s=10)
        now[0] += 100
        assert not store.consume("k")

    def test_requesting_twice_does_not_duplicate_the_question(self, tmp_path):
        store = self._store(tmp_path)
        store.request("k", "send", "x", "b")
        store.request("k", "send", "x", "b")
        assert len(store.pending()) == 1

    def test_a_denial_is_recorded_and_blocks_use(self, tmp_path):
        store = self._store(tmp_path)
        store.request("k", "send", "x", "b")
        store.deny("k", by="junaid")
        assert not store.consume("k")
        assert store.get("k").decided_by == "junaid"

    def test_who_decided_and_when_is_recorded(self, tmp_path):
        store = self._store(tmp_path)
        store.request("k", "send", "x", "b")
        store.grant("k", by="junaid")
        approval = store.get("k")
        assert approval.decided_by == "junaid" and approval.decided_at == 1_000_000.0

    def test_keys_that_differ_get_different_files(self, tmp_path):
        store = self._store(tmp_path)
        store.request("post:issue:42", "post", "issue:42", "b")
        store.request("post:issue-42", "post", "issue-42", "b")
        assert len(store.pending()) == 2

    def test_the_agent_parks_a_gated_action_durably(self, tmp_path):
        from deputy.store.vault import Vault
        from deputy.runtime.agent import Agent
        from deputy.runtime.model import ScriptedModel
        from deputy.runtime.tools import Toolbox
        import json as _json

        vault = Vault(tmp_path / "v", git=False)
        store = self._store(tmp_path)
        policy = PolicyEngine(
            rules=ruleset(
                Rule(name="gate", match="*", verdict=Verdict.REQUIRE_APPROVAL,
                     when={"reversible": False})
            ),
            audit=vault.audit,
            approvals=store,
        )
        box = Toolbox()
        box.register("send_it", "Send.", lambda **k: None, reversible=False, external=True)
        Agent(
            model=ScriptedModel(
                replies=[
                    _json.dumps({"tool": "send_it", "args": {"subject": "a"}, "why": "x"}),
                    _json.dumps({"tool": "finish", "args": {"answer": "done"}, "why": "x"}),
                ]
            ),
            tools=box,
            policy=policy,
            audit=vault.audit,
        ).run("task")

        assert [a.action for a in store.pending()] == ["send_it"]
