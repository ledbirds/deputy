"""A runnable triage agent wired to the policy engine.

Run it:

    python -m examples.triage.triage

No API key and no network. The model is a ScriptedModel, so the whole loop is
deterministic and a reader can follow exactly what happened.

What this demonstrates, in order of what a reviewer probably cares about:

  1. An irreversible external action (posting a public comment) is parked for
     approval rather than taken, without stalling the rest of the run.
  2. A denied action stays denied, and the agent is told so and moves on.
  3. Every step lands in an append-only log with a reason attached.
  4. Cost and latency are accounted per run, not estimated afterwards.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from deputy.policy.engine import PolicyEngine  # noqa: E402
from deputy.policy.rules import load_rules  # noqa: E402
from deputy.runtime.agent import Agent  # noqa: E402
from deputy.runtime.budget import Budget  # noqa: E402
from deputy.runtime.model import ScriptedModel  # noqa: E402
from deputy.runtime.tools import Toolbox  # noqa: E402
from deputy.store.vault import Vault  # noqa: E402
from examples.triage.rubric import score  # noqa: E402

HERE = Path(__file__).resolve().parent

ISSUES: dict[str, dict[str, Any]] = {
    "1041": {
        "title": "Batch import drops rows silently when a column is missing",
        "body": (
            "Importing a CSV where one column is absent completes with a success "
            "message but writes only some of the rows. No error, no warning. "
            "Reproduced on 3.2.1 and 3.2.2 with the attached file. We lost about "
            "1,200 records before anyone noticed."
        ),
        "signals": {
            "data_loss": True,
            "reproducible": True,
            "regression": False,
            "many_affected": True,
            "has_workaround": False,
            "question_not_bug": False,
            "stale_version": False,
            "no_detail": False,
            "security": False,
            "blocks_release": False,
        },
    },
    "1042": {
        "title": "How do I change the timezone?",
        "body": "Sorry if this is documented somewhere, I could not find it.",
        "signals": {
            "data_loss": False,
            "reproducible": False,
            "regression": False,
            "many_affected": False,
            "has_workaround": True,
            "question_not_bug": True,
            "stale_version": False,
            "no_detail": False,
            "security": False,
            "blocks_release": False,
        },
    },
}


def build(vault_root: Path) -> tuple[Agent, PolicyEngine, Vault]:
    vault = Vault(vault_root, git=False)
    policy = PolicyEngine(rules=load_rules(HERE / "policy.md"), audit=vault.audit)
    tools = Toolbox()

    def read_issue(subject: str = "", **_: Any) -> dict[str, Any]:
        issue = ISSUES.get(subject)
        if issue is None:
            raise KeyError(f"no issue {subject!r}")
        return {"title": issue["title"], "body": issue["body"]}

    def score_issue(subject: str = "", **_: Any) -> dict[str, Any]:
        issue = ISSUES.get(subject)
        if issue is None:
            raise KeyError(f"no issue {subject!r}")
        judgment = score(issue["signals"])
        vault.write(
            f"triage/{subject}.md",
            {
                "issue": subject,
                "band": judgment.band,
                "probability": round(judgment.probability, 4),
                "confident": judgment.confident,
            },
            body=f"# {issue['title']}\n\n{judgment.explain()}\n",
            actor="triage-agent",
            reason="scored against the triage rubric",
        )
        return judgment.as_dict()

    def draft_reply(subject: str = "", text: str = "", **_: Any) -> dict[str, Any]:
        vault.write(
            f"drafts/{subject}.md",
            {"issue": subject, "state": "draft"},
            body=text,
            actor="triage-agent",
            reason="drafted a reply for review",
        )
        return {"drafted": True, "chars": len(text)}

    def post_comment(subject: str = "", text: str = "", **_: Any) -> dict[str, Any]:
        # Never reached in this example: policy parks it for approval first.
        return {"posted": True, "issue": subject, "chars": len(text)}

    def apply_label(subject: str = "", label: str = "", **_: Any) -> dict[str, Any]:
        return {"labelled": label, "issue": subject}

    def close_issue(subject: str = "", **_: Any) -> dict[str, Any]:
        return {"closed": subject}

    tools.register(
        "read_issue", "Fetch an issue's title and body.", read_issue,
        reversible=True, external=False,
    )
    tools.register(
        "score_issue", "Score an issue against the triage rubric.", score_issue,
        reversible=True, external=False,
    )
    tools.register(
        "draft_reply", "Write a reply to the vault for a human to review.", draft_reply,
        reversible=True, external=False,
    )
    tools.register(
        "apply_label", "Apply a label to the issue.", apply_label,
        reversible=True, external=True,
    )
    tools.register(
        "post_comment", "Post a public comment on the issue.", post_comment,
        reversible=False, external=True,
    )
    tools.register(
        "close_issue", "Close the issue.", close_issue,
        reversible=False, external=True,
    )

    # Scripted so the run is deterministic and free. Swap for CallableModel
    # wrapping a real provider and nothing else changes.
    model = ScriptedModel(
        replies=[
            json.dumps({"tool": "read_issue", "args": {"subject": "1041"}, "why": "get context"}),
            json.dumps({"tool": "score_issue", "args": {"subject": "1041"}, "why": "triage it"}),
            json.dumps(
                {
                    "tool": "draft_reply",
                    "args": {
                        "subject": "1041",
                        "text": (
                            "Thanks for the detailed report, and sorry about the lost "
                            "records. Silent partial writes on a missing column is a "
                            "data-loss bug and we are treating it as one. Could you "
                            "confirm whether the import ran through the CLI or the web "
                            "uploader?"
                        ),
                    },
                    "why": "acknowledge and ask the one question that unblocks a fix",
                }
            ),
            json.dumps(
                {
                    "tool": "post_comment",
                    "args": {"subject": "1041", "text": "posting the draft above"},
                    "why": "the reporter is waiting",
                }
            ),
            json.dumps(
                {
                    "tool": "close_issue",
                    "args": {"subject": "1042"},
                    "why": "it is only a question",
                }
            ),
            json.dumps(
                {
                    "tool": "finish",
                    "args": {
                        "answer": (
                            "1041 scored urgent on data loss; reply drafted and waiting "
                            "for approval to post. 1042 is a support question and closing "
                            "it is not mine to do."
                        )
                    },
                    "why": "done",
                }
            ),
        ]
    )

    agent = Agent(
        model=model,
        tools=tools,
        policy=policy,
        budget=Budget(ceiling_usd=0.25, max_calls=20),
        audit=vault.audit,
        name="triage-agent",
    )
    return agent, policy, vault


def main() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        agent, policy, vault = build(Path(tmp) / "vault")
        result = agent.run("Triage the open issues in the queue.", subject="1041")

        print("=" * 68)
        print("STEPS")
        print("=" * 68)
        for step in result.steps:
            mark = {
                "performed": "  ok  ",
                "pending_approval": " HELD ",
                "denied": "DENIED",
                "failed": " FAIL ",
            }.get(step.outcome, "  ?   ")
            print(f"[{mark}] {step.tool}({_render_args(step.args)})")
            print(f"         {step.because}")

        print()
        print("=" * 68)
        print("OUTCOME")
        print("=" * 68)
        print(result.answer or "(no answer)")
        print()
        print(f"stopped because : {result.stopped_because}")
        print(f"performed       : {len(result.performed)}")
        print(f"held for a human: {len(result.pending_approval)}")
        print(f"denied          : {sum(1 for s in result.steps if s.outcome == 'denied')}")

        print()
        print("=" * 68)
        print("SPEND")
        print("=" * 68)
        print(json.dumps(result.budget, indent=2))

        print()
        print("=" * 68)
        print("AUDIT LOG")
        print("=" * 68)
        for entry in vault.audit.read():
            print(f"  {entry.actor:<14} {entry.action:<8} {entry.subject:<22} {entry.outcome}")

        print()
        print("=" * 68)
        print("APPROVING THE HELD ACTION")
        print("=" * 68)
        if result.pending_approval:
            held = result.pending_approval[0]
            key = f"{held.tool}:{held.args.get('subject', '')}"
            print(f"granting: {key}")
            policy.grant(key)
            from deputy.policy.rules import Action

            tool = agent.tools.get(held.tool)
            again = policy.authorize(tool.action_for(str(held.args.get("subject", ""))))
            print(again.explain())
        else:
            print("nothing was held")

    return 0


def _render_args(args: dict[str, Any]) -> str:
    parts = []
    for key, value in args.items():
        text = str(value)
        if len(text) > 28:
            text = text[:28] + "..."
        parts.append(f"{key}={text!r}")
    return ", ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
