"""Command line entry point.

    deputy policy check examples/triage/policy.md post_comment --irreversible --external
    deputy policy explain examples/triage/policy.md
    deputy audit tail path/to/vault

The `policy check` subcommand exists because the question "what would the
system do if an agent tried this" should be answerable in one line, by
someone who is not going to read the engine, before the agent is trusted with
the capability.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from deputy.policy.engine import PolicyEngine
from deputy.policy.rules import Action, load_rules
from deputy.store.audit import AuditLog


def _check(args: argparse.Namespace) -> int:
    engine = PolicyEngine(rules=load_rules(args.policy))
    action = Action(
        name=args.action,
        subject=args.subject or "",
        reversible=not args.irreversible,
        external=args.external,
        attrs=dict(pair.split("=", 1) for pair in args.attr),
    )
    decision = engine.check(action)
    print(decision.explain())
    return 0 if not decision.denied else 1


def _explain(args: argparse.Namespace) -> int:
    rules = load_rules(args.policy)
    print(f"default: {rules.default.name}  ({rules.default_because})")
    print(f"{len(rules)} rules\n")
    for rule in rules:
        conditions = ", ".join(f"{k}={v}" for k, v in rule.when.items())
        caps = []
        if rule.limit_per_day:
            caps.append(f"{rule.limit_per_day}/day")
        if rule.limit_per_week:
            caps.append(f"{rule.limit_per_week}/week")
        print(f"  {rule.name}")
        print(f"    match   {rule.match}" + (f"  where {conditions}" if conditions else ""))
        print(f"    verdict {rule.verdict.name}" + (f"  limit {', '.join(caps)}" if caps else ""))
        if rule.because:
            print(f"    because {rule.because}")
        print()
    return 0


def _tail(args: argparse.Namespace) -> int:
    path = Path(args.vault)
    log = AuditLog(path if path.suffix == ".jsonl" else path / ".deputy" / "audit.jsonl")
    entries, damaged = log.read_with_damage()
    for entry in entries[-args.n :]:
        print(f"{entry.actor:<16} {entry.action:<10} {entry.subject:<28} {entry.outcome}")
    if damaged:
        print(f"\n{damaged} unreadable line(s) skipped", file=sys.stderr)
    return 0


def _approvals(args: argparse.Namespace) -> int:
    from deputy.policy.approvals import ApprovalStore
    from deputy.store.vault import Vault

    store = ApprovalStore(Vault(args.vault, git=False))

    if args.cmd == "pending":
        rows = store.pending()
        if not rows:
            print("nothing waiting")
            return 0
        for a in rows:
            print(f"{a.key}\n  {a.action} on {a.subject or '(none)'}\n  {a.because}\n")
        return 0

    if args.cmd == "grant":
        a = store.grant(args.key, by=args.by, uses=args.uses)
        print(f"granted {a.key} to {a.decided_by}, {a.uses_left} use(s), expires {a.expires_at}")
        return 0

    if args.cmd == "deny":
        a = store.deny(args.key, by=args.by)
        print(f"denied {a.key}")
        return 0

    closed = store.sweep()
    print(f"{closed} expired grant(s) closed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deputy", description=__doc__)
    sub = parser.add_subparsers(dest="group", required=True)

    policy = sub.add_parser("policy", help="inspect and test a policy file")
    policy_sub = policy.add_subparsers(dest="cmd", required=True)

    check = policy_sub.add_parser("check", help="ask what the policy would decide")
    check.add_argument("policy")
    check.add_argument("action")
    check.add_argument("--subject", default="")
    check.add_argument("--irreversible", action="store_true")
    check.add_argument("--external", action="store_true")
    check.add_argument("--attr", action="append", default=[], metavar="KEY=VALUE")
    check.set_defaults(fn=_check)

    explain = policy_sub.add_parser("explain", help="print the ruleset in full")
    explain.add_argument("policy")
    explain.set_defaults(fn=_explain)

    audit = sub.add_parser("audit", help="inspect an audit log")
    audit_sub = audit.add_subparsers(dest="cmd", required=True)
    tail = audit_sub.add_parser("tail", help="show recent entries")
    tail.add_argument("vault")
    tail.add_argument("-n", type=int, default=20)
    tail.set_defaults(fn=_tail)

    approvals = sub.add_parser("approvals", help="inspect and decide pending approvals")
    approvals_sub = approvals.add_subparsers(dest="cmd", required=True)
    for name, help_text in (
        ("pending", "list what the system is waiting on"),
        ("grant", "approve one action"),
        ("deny", "refuse one action"),
        ("sweep", "close grants that have expired"),
    ):
        sp = approvals_sub.add_parser(name, help=help_text)
        sp.add_argument("vault")
        if name in ("grant", "deny"):
            sp.add_argument("key")
            sp.add_argument("--by", default="human")
        if name == "grant":
            sp.add_argument("--uses", type=int, default=1)
        sp.set_defaults(fn=_approvals)

    args = parser.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
