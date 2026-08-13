# Postmortem 0004: Nine defects a green test suite did not catch

**Severity:** high. Three of them broke safety mechanisms this README advertises.
**Found by:** two independent adversarial reviews, run against the repo after
it was finished and passing.

## Context

At the point of review the repo had 105 passing tests, 87% line coverage, a
worked example that ran, and evals that reproduced byte for byte. It looked
done.

Two reviewers were pointed at it: one reading it as a hiring manager checking
whether the code does what the prose claims, one auditing for exploitable
correctness bugs with instructions to write scripts and confirm by execution
rather than by reading.

Between them they found nine real defects. Three of those broke mechanisms the
README specifically draws attention to.

## The three that mattered

**The budget ceiling was checked after the call, not before.** `Budget.check`
took an `estimated_cost` parameter, the README explained at length why
checking before matters, and nothing in the agent loop ever passed it. A
single long-context call overshot a ceiling by roughly thirty times. The
parameter existed, was correct, and was dead code.

**Rate limits silently did not exist when more than one rule matched.**
Consumption was booked against `decision.matched[0]`, the first rule in file
order, while the limiter counted usage by exact rule name. Put any uncapped
rule above a capped one and the cap accumulated nothing. The policy file in
this repo states that rule order carries no meaning; for rate limits it
quietly decided everything.

**One approval granted permanent authority.** `grant()` set a flag that
`authorize()` read and never cleared. Clicking approve once on a single action
converted the gate into a standing allow for that action forever. Worse in
combination: because a breached rate limit downgrades to REQUIRE_APPROVAL
rather than DENY, a standing approval also converted a capped rule into an
uncapped one.

## The rest

- An agent could write to `.deputy/audit.jsonl` and `.git/hooks/`. The path
  guard correctly refused everything outside the vault root and both of those
  are inside it. Truncating the audit log erases the trail and resets every
  rate-limit window; a writable hooks directory is code execution on the next
  commit.
- `when_amount: 5000` stayed the string `"5000"` and never equalled the
  integer, so any DENY rule with a non-boolean predicate matched nothing while
  reading correctly in the file. Identical in class to postmortem 0003, which
  had been fixed for its one symptom rather than for the class.
- `limit_per_day: 0` was falsy and read as "no cap set", so the strictest
  thing a person can write in a policy file meant unlimited.
- Approval keys were `f"{name}:{subject}"`, which is not injective. `("post",
  "issue:42")` and `("post:issue", "42")` collide, and subjects come from
  model output.
- A line of valid JSON that was not an object raised `AttributeError` past the
  damage handler, making the whole log unreadable and taking the policy engine
  down with it, since the engine reads the log on every rate-limit check.
- `dumps(loads(x)) != x` for several inputs: values already wrapped in quotes
  lost them, escaped quotes accumulated backslashes, and a key containing a
  colon produced a document that silently parsed back as something else.

## Why the tests did not catch any of it

They tested the implementation. Each unit did what its author believed it did,
and the tests asserted that belief back.

Nothing tested the *seams*: that the agent passes what `Budget.check`
expects, that what `record_performed` writes is what `_rate_limited` reads,
that a grant is consumed by the thing that honours it. Every one of these bugs
lives between two components that were individually correct.

One test was actively harmful. `test_same_event_from_two_branches_dedupes_
despite_different_seq` asserted that two entries differing only in sequence
number share an identity, with a docstring explaining why that was desirable.
It was wrong, it locked the bug in, and it made the behaviour look considered.
A confident docstring on a wrong test is worse than no test.

## What changed

Every defect is fixed and every one has a regression test named after the
symptom rather than the function.

Two structural changes beyond the individual fixes. Monotonicity is now
asserted over three hundred randomly generated rulesets instead of one
hand-picked example, which is what a property claim requires; the hand-picked
version happened to compare `REQUIRE_APPROVAL` against itself and asserted
`1 >= 1`. And the README's claim was narrowed to what actually holds, because
the property is true within the matched set and false across the fail-closed
default, and the first draft claimed both.

## The transferable lesson

A green suite over an implementation is evidence about the implementation, not
about the claims. The claims in a README are a specification, and the useful
question is not "do the tests pass" but "which sentence in this document has
no test behind it". Every one of the three serious findings was a sentence in
this README with nothing checking it.

The cheapest fix available was not more tests. It was handing the repo to
someone whose instructions were to disbelieve it.
