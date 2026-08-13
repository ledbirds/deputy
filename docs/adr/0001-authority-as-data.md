# ADR 0001: Authority is data, and composition is monotone

**Status:** accepted

## Context

An agent that can call tools needs some answer to "is it allowed to do this".
The usual answer is a check inside the tool, or a wrapper the caller is
expected to remember, or a system prompt that asks the model nicely.

All three fail the same way. The rule about what the agent may do lives in a
place where it cannot be reviewed as a whole, so nobody can answer "what is
this agent allowed to do" without reading every call site, and the answer
changes when someone adds a tool and forgets the wrapper.

## Decision

Authority is a declarative ruleset in a markdown file, evaluated by one engine
that every action passes through.

Three properties are enforced by the engine rather than left to whoever writes
the rules.

**Fail closed.** An action matched by no rule is denied. The default is a
field on the ruleset so it is explicit, and it defaults to deny.

**Monotone composition.** Verdicts are ordered `ALLOW < REQUIRE_APPROVAL <
DENY`, and when several rules match the maximum is taken. Adding a rule can
therefore tighten authority and can never widen it.

**Classification at definition.** Every tool declares `reversible` and
`external` when it is registered. Both are required arguments, so a capability
cannot be added without someone deciding what a mistake with it costs.

## Alternatives considered

**First-match-wins, ordered rules.** This is what firewalls do and what most
people reach for. Rejected because it makes rule order load-bearing, which
means a permissive rule accidentally placed above a restrictive one silently
grants authority, and the file still looks correct. The failure is invisible
in review, which is the worst property a policy file can have.

**An expression language in the policy file.** Tempting, and it would handle
the cases the `when_*` predicates cannot. Rejected because an expression
language in a policy file is code written in a place that does not get tested,
and the first genuinely subtle predicate someone writes in it will be the one
that grants authority nobody intended. When the predicates are not enough, the
right move is a new attribute on the action, set in Python where it can be
tested.

**Policy in the system prompt.** Rejected because it is a request, not a
control. The model complies until it does not, and there is no artifact to
review or diff.

## Consequences

Good: the full authority of an agent is one file, readable by someone who does
not read Python, diffable in a pull request, changeable without a deploy. The
CLI can answer "what would this do" in one line, before the capability is
trusted.

Bad: expressiveness is genuinely limited. Rules are a glob plus equality
predicates and nothing else, so anything conditional on the *content* of an
action has to be lifted into an attribute first. This has already been mildly
annoying once and is the right trade anyway.

Bad: two rules can both match and both be intended as the deciding one, and
the engine takes the stricter without telling you the other was shadowed. The
decision trace lists every matching rule, which makes this visible but does
not prevent it.

## How this could be wrong

If the ruleset grows past roughly a few dozen rules, "every rule is evaluated
and the strictest wins" stops being something a human can hold in their head,
and the absence of ordering goes from a safety property to an obstacle. At
that point the answer is probably rule namespacing per agent rather than
ordering, but this has not been hit and is not designed for.
