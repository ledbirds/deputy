"""The agent loop.

One turn is: ask the model what to do, authorize it, do it or park it, record
what happened. The loop is small on purpose. Almost everything that makes an
agent trustworthy lives outside it, in policy, budget, and the log, and a
loop that stays legible is one whose behaviour can still be reasoned about
after the interesting parts are added.

What the loop guarantees:

  Nothing runs unauthorized.  Every tool call passes the policy engine first.
  Approval parks, never blocks.  An action needing a human is recorded as
      pending and the run continues with the rest. A loop that blocks on
      approval turns one unanswered question into a stalled queue.
  Budget is checked before the call, and the run stops cleanly when spent.
  Every step is recorded, including the ones that failed.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from deputy.policy.engine import Decision, PolicyEngine
from deputy.policy.rules import Verdict
from deputy.runtime.budget import Budget, BudgetExceeded, estimate_cost
from deputy.runtime.model import Model, ModelError, parse_json_object
from deputy.runtime.retry import RetryPolicy, retry
from deputy.runtime.tools import Toolbox, ToolError
from deputy.runtime.untrusted import Fence, Finding, sanitise
from deputy.store.audit import AuditLog

FINISH = "finish"


@dataclass
class Step:
    """One decision and its consequence."""

    n: int
    tool: str
    args: dict[str, Any]
    verdict: str
    because: str
    outcome: str
    result: Any = None
    error: str | None = None
    elapsed_s: float = 0.0
    #: Injection shapes seen in this step's output. Recorded, never blocking.
    suspicious: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "tool": self.tool,
            "args": self.args,
            "verdict": self.verdict,
            "because": self.because,
            "outcome": self.outcome,
            "error": self.error,
            "elapsed_s": round(self.elapsed_s, 3),
            "suspicious": list(self.suspicious),
        }


@dataclass
class AgentResult:
    steps: list[Step] = field(default_factory=list)
    pending_approval: list[Step] = field(default_factory=list)
    answer: str = ""
    stopped_because: str = "finished"
    budget: dict[str, Any] = field(default_factory=dict)

    @property
    def suspicious(self) -> list[str]:
        """Every injection shape seen across the run, for alerting."""
        return [note for step in self.steps for note in step.suspicious]

    @property
    def performed(self) -> list[Step]:
        return [s for s in self.steps if s.outcome == "performed"]

    @property
    def failed(self) -> list[Step]:
        return [s for s in self.steps if s.outcome == "failed"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "stopped_because": self.stopped_because,
            "steps": [s.as_dict() for s in self.steps],
            "pending_approval": [s.as_dict() for s in self.pending_approval],
            "budget": self.budget,
        }


PROMPT = """{task}

Tools available:
{tools}

Reply with a single JSON object and nothing else:
  {{"tool": "<name>", "args": {{...}}, "why": "<one line>"}}
To stop, use tool "finish" with args {{"answer": "<your answer>"}}.

{history}"""


@dataclass
class Agent:
    """A policy-gated tool-using agent."""

    model: Model
    tools: Toolbox
    policy: PolicyEngine
    budget: Budget = field(default_factory=Budget)
    audit: AuditLog | None = None
    name: str = "agent"
    system: str = "You are a careful operations agent. Prefer the smallest sufficient action."
    max_steps: int = 8
    #: Used only to price a call before making it, never to cap the provider.
    max_output_tokens: int = 1024
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    clock: Callable[[], float] = time.monotonic
    #: Regenerated per run, so an attacker cannot embed a closing marker.
    fence: Fence = field(default_factory=Fence)

    def run(self, task: str, *, subject: str = "") -> AgentResult:
        result = AgentResult()
        history: list[str] = []

        for n in range(1, self.max_steps + 1):
            try:
                self.budget.check()
            except BudgetExceeded as exc:
                result.stopped_because = str(exc)
                break

            try:
                proposal = self._propose(task, history)
            except BudgetExceeded as exc:
                result.stopped_because = str(exc)
                break
            except ModelError as exc:
                result.stopped_because = f"model failed: {exc}"
                break

            tool_name = str(proposal.get("tool", "")).strip()
            args = proposal.get("args") or {}
            if not isinstance(args, dict):
                args = {"value": args}

            if tool_name == FINISH:
                result.answer = str(args.get("answer", ""))
                result.stopped_because = "finished"
                break

            step = self._act(n, tool_name, args, subject=subject)
            result.steps.append(step)
            if step.outcome == "pending_approval":
                result.pending_approval.append(step)

            history.append(self._observation(step))
        else:
            result.stopped_because = f"hit max_steps ({self.max_steps})"

        result.budget = self.budget.report()
        return result

    # ------------------------------------------------------------ internals

    def _propose(self, task: str, history: list[str]) -> dict[str, Any]:
        prompt = PROMPT.format(
            task=task,
            tools=self.tools.describe() + f"\n- {FINISH}: stop and give the answer",
            history=("Previous steps:\n" + "\n".join(history)) if history else "",
        )

        def call() -> Any:
            # Estimate this call's cost and check the ceiling against it,
            # rather than checking whether the ceiling is already breached.
            # The parameter existed and was never passed, so a single
            # long-context call could overshoot a small ceiling by 30x before
            # anything noticed: the exact failure the docstring on
            # Budget.check claims to prevent.
            self.budget.check(
                estimated_cost=estimate_cost(
                    self.model, prompt, self.system, self.max_output_tokens
                )
            )
            started = self.clock()
            completion = self.model.complete(prompt, system=self.system, temperature=0.0)
            elapsed = self.clock() - started
            self.budget.charge(
                completion.model,
                completion.prompt_tokens,
                completion.completion_tokens,
                latency_s=completion.latency_s or elapsed,
            )
            return completion

        completion = retry(call, self.retry_policy)
        return parse_json_object(completion.text)

    def _act(self, n: int, tool_name: str, args: dict[str, Any], *, subject: str) -> Step:
        started = self.clock()

        try:
            tool = self.tools.get(tool_name)
        except ToolError as exc:
            return Step(
                n=n,
                tool=tool_name,
                args=args,
                verdict="n/a",
                because="unknown tool",
                outcome="failed",
                error=str(exc),
                elapsed_s=self.clock() - started,
            )

        target = str(args.get("subject") or subject or "")
        action = tool.action_for(target)
        decision: Decision = self.policy.authorize(action, actor=self.name)

        if decision.verdict is Verdict.DENY:
            return Step(
                n=n,
                tool=tool_name,
                args=args,
                verdict="deny",
                because=decision.because,
                outcome="denied",
                elapsed_s=self.clock() - started,
            )

        if decision.verdict is Verdict.REQUIRE_APPROVAL:
            # Park it where a human will still find it after a restart. A
            # pending request held only in process memory is a question nobody
            # was ever asked.
            self.policy.request_approval(action, decision)
            self._record(tool_name, target, "pending_approval", decision.because)
            return Step(
                n=n,
                tool=tool_name,
                args=args,
                verdict="require_approval",
                because=decision.because,
                outcome="pending_approval",
                elapsed_s=self.clock() - started,
            )

        try:
            value = tool(**args)
            findings = self._scan_result(value)
        except ToolError as exc:
            self._record(tool_name, target, "failed", str(exc))
            return Step(
                n=n,
                tool=tool_name,
                args=args,
                verdict="allow",
                because=decision.because,
                outcome="failed",
                error=str(exc),
                elapsed_s=self.clock() - started,
            )

        # Every rule that authorised this, not just the first. Booking
        # against one meant a capped rule sitting below an uncapped one in
        # the policy file never accumulated usage and its cap did not exist.
        self.policy.record_performed(
            action, list(decision.matched) or ["default"], actor=self.name
        )
        if findings and self.audit is not None:
            self.audit.append(
                actor=self.name,
                action="untrusted",
                subject=target or tool_name,
                outcome="flagged",
                detail={"tool": tool_name, "findings": [str(f) for f in findings]},
            )

        return Step(
            n=n,
            tool=tool_name,
            args=args,
            verdict="allow",
            because=decision.because,
            outcome="performed",
            result=value,
            elapsed_s=self.clock() - started,
            suspicious=[str(f) for f in findings],
        )

    def _scan_result(self, value: Any) -> list[Finding]:
        from deputy.runtime.untrusted import scan

        try:
            return scan(json.dumps(value, default=str))
        except (TypeError, ValueError):
            return []

    def _record(self, tool: str, subject: str, outcome: str, detail: str) -> None:
        if self.audit is None:
            return
        self.audit.append(
            actor=self.name,
            action="step",
            subject=subject or tool,
            outcome=outcome,
            detail={"tool": tool, "note": detail},
        )

    def _observation(self, step: Step) -> str:
        if step.outcome == "performed":
            rendered = json.dumps(step.result, default=str)
            if len(rendered) > 400:
                rendered = rendered[:400] + "...(truncated)"
            # Tool output is untrusted: it may contain an issue body, an email,
            # a scraped page. Fenced with a per-run nonce and labelled as data.
            # This raises the cost of an injection and makes attempts visible;
            # it is not what stops one. What stops one is that the policy
            # engine gates whatever the model proposes next.
            fenced = self.fence.wrap(rendered, source=step.tool)
            return f"{step.n}. {step.tool} returned:\n{fenced}"
        if step.outcome == "pending_approval":
            return (
                f"{step.n}. {step.tool} was not run: it needs human approval "
                f"({step.because}). Continue with other work."
            )
        if step.outcome == "denied":
            return f"{step.n}. {step.tool} was denied ({step.because}). Do not retry it."
        return f"{step.n}. {step.tool} failed: {step.error}"
