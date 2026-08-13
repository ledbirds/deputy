---
default: deny
default_because: "no rule grants this capability, and the engine fails closed"
---

# Triage policy

The shape of this file is the point. Authority is data, reviewable in a diff
by someone who does not read Python, and changeable without a deploy.

Two properties make it safe to leave running. An action no rule mentions is
denied rather than allowed. And when several rules match, the most
restrictive one wins, so adding a rule can tighten authority but can never
widen it. See `docs/adr/0001-authority-as-data.md`.

The rules are ordered for a human reader, not for the engine. Order carries
no meaning: every matching rule is evaluated and the strictest verdict is
taken. That is deliberate, because a first-match-wins file rewards putting
your permissive rule at the top and the failure is invisible.

## read-anything

match: read_*
verdict: allow
because: reading is free and reversible, and starving an agent of context makes it guess

## score-anything

match: score_issue
verdict: allow
because: scoring produces a number and a justification, and writes nothing

## draft-freely

match: draft_*
verdict: allow
because: a draft costs nothing to get wrong and is the useful half of the work

## label-is-visible-but-cheap

match: apply_label
verdict: allow
limit_per_day: 40
because: a label is public but one click to undo, so it is capped rather than gated

## irreversible-needs-a-human

match: "*"
when_reversible: false
verdict: require_approval
because: a mistake that cannot be walked back is worth one round trip to a human

## public-and-permanent-needs-a-human

match: "*"
when_external: true
when_reversible: false
verdict: require_approval
because: another person sees it and it cannot be recalled, which is the worst pair

## never-close-on-behalf-of-a-human

match: close_issue
verdict: deny
because: closing someone's report is a judgment about their problem, not a task to delegate

## never-touch-embargoed-reports

match: "*"
when_sensitive: true
verdict: deny
because: an embargoed report routes to a human directly and never through an autonomous path
