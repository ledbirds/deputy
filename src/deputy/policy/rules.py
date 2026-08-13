"""Declarative authority rules.

A rule is a match plus a verdict. Rules are data, not code, so the set of
things an agent may do can be reviewed in a diff by someone who does not
read Python, and changed without a deploy.

Matching is intentionally boring: exact string or glob on the action name,
plus optional equality predicates on the action's attributes. There is no
expression language. An expression language in a policy file is a way of
writing code in a place that does not get tested, and the first genuinely
subtle predicate someone writes in it will be the one that grants authority
nobody intended.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Iterable

from deputy.store.frontmatter import loads


class Verdict(IntEnum):
    """Ordered by restrictiveness. Higher is more restrictive.

    The ordering is load-bearing: when several rules match, the engine takes
    the maximum. That makes rule composition monotone, so adding a rule can
    tighten authority but can never widen it. A first-match-wins engine has
    the opposite property, and the failure is silent.
    """

    ALLOW = 0
    REQUIRE_APPROVAL = 1
    DENY = 2

    @classmethod
    def parse(cls, raw: str) -> "Verdict":
        key = raw.strip().upper().replace("-", "_")
        try:
            return cls[key]
        except KeyError as exc:
            valid = ", ".join(v.name.lower() for v in cls)
            raise ValueError(f"unknown verdict {raw!r}; expected one of: {valid}") from exc


@dataclass(frozen=True)
class Action:
    """Something an agent proposes to do.

    `reversible` and `external` are not decoration. They are the two axes
    that decide how much a mistake costs. An irreversible external action
    (a sent email) cannot be walked back and is visible to someone else; a
    reversible internal one (a draft) costs nothing to get wrong.
    """

    name: str
    subject: str = ""
    reversible: bool = True
    external: bool = False
    attrs: dict[str, Any] = field(default_factory=dict)

    def attribute(self, key: str) -> Any:
        if key == "reversible":
            return self.reversible
        if key == "external":
            return self.external
        if key == "name":
            return self.name
        if key == "subject":
            return self.subject
        return self.attrs.get(key)


@dataclass(frozen=True)
class Rule:
    name: str
    match: str
    verdict: Verdict
    because: str = ""
    when: dict[str, Any] = field(default_factory=dict)
    limit_per_day: int | None = None
    limit_per_week: int | None = None

    def matches(self, action: Action) -> bool:
        if not fnmatch.fnmatch(action.name, self.match):
            return False
        return all(action.attribute(key) == value for key, value in self.when.items())


@dataclass
class RuleSet:
    rules: list[Rule] = field(default_factory=list)
    default: Verdict = Verdict.DENY
    default_because: str = "no rule matched and the engine fails closed"

    def matching(self, action: Action) -> list[Rule]:
        return [rule for rule in self.rules if rule.matches(action)]

    def __len__(self) -> int:
        return len(self.rules)

    def __iter__(self) -> Iterable[Rule]:
        return iter(self.rules)


def _unquote(value: str) -> str:
    """Strip one layer of surrounding quotes.

    Glob patterns like "*" have to be quotable, because a bare `match: *` is
    ambiguous to read and invites a YAML-shaped mistake. Without this, the
    pattern is stored with its quote characters intact and silently matches
    nothing, which presents as a catch-all rule that never fires: the most
    dangerous way for a policy file to be wrong.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _coerce(raw: str) -> Any:
    """Type a `when_` predicate value the way the action attribute will be typed.

    Predicates are compared with `==` against attributes that carry real
    Python types, so a value left as a string can never match an int or a
    bool. The failure is silent and it fails open: `when_amount: 5000` stayed
    the string "5000", never equalled the integer 5000, and the DENY rule it
    guarded matched nothing while reading correctly in the file. Same class
    as the quoted-glob bug in postmortem 0003, so it is fixed for the class
    rather than for the one symptom.

    Quoting is the escape hatch and it is honoured: `when_flag: "false"` is
    the four-character string, not the boolean.
    """
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("null", "none", "~"):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def load_rules(path: str | Path) -> RuleSet:
    """Load a ruleset from a markdown policy file.

    The format is a markdown document whose frontmatter holds the default
    verdict, and whose body holds one `## rule-name` section per rule with
    flat `key: value` lines beneath it. Keeping the policy in the same
    format as the rest of the state means it lives in the same repo, shows
    up in the same diffs, and can carry prose explaining itself.
    """
    text = Path(path).read_text(encoding="utf-8")
    meta, body = loads(text)

    default = Verdict.parse(str(meta.get("default", "deny")))
    ruleset = RuleSet(default=default)
    if meta.get("default_because"):
        ruleset.default_because = str(meta["default_because"])

    current: dict[str, Any] | None = None
    name: str = ""

    def flush() -> None:
        nonlocal current, name
        if current is None:
            return
        if "match" not in current:
            raise ValueError(f"rule {name!r} has no 'match'")
        if "verdict" not in current:
            raise ValueError(f"rule {name!r} has no 'verdict'")
        when = {k[5:]: _coerce(str(v)) for k, v in current.items() if k.startswith("when_")}
        ruleset.rules.append(
            Rule(
                name=name,
                match=_unquote(str(current["match"])),
                verdict=Verdict.parse(_unquote(str(current["verdict"]))),
                because=_unquote(str(current.get("because", ""))),
                when=when,
                limit_per_day=_int_or_none(current.get("limit_per_day")),
                limit_per_week=_int_or_none(current.get("limit_per_week")),
            )
        )
        current = None

    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## "):
            flush()
            name = stripped[3:].strip()
            current = {}
            continue
        if current is None or not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            current[key.strip()] = value.strip()

    flush()
    return ruleset


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)
