# ADR 0006: Approvals are documents in the vault

**Status:** accepted

## Context

The runtime's central claim is that approval parks rather than blocks. The
first implementation held pending approvals in a dict on the engine.

That makes the claim untrue in the case it matters. An agent asks at 02:00, the
scheduler restarts at 03:00, and the question is gone. Nothing recorded that a
human was ever waiting, so the next run asks again and the human sees a
duplicate rather than a resumption. A parked action that does not survive the
process was never parked; it was dropped politely.

## Decision

An approval is a markdown document in the vault, in the same format as
everything else, with the same diff and the same audit trail. A request is a
document. A grant is an edit to it. Both are in `git log`.

Four properties the dict did not have.

**Durable.** A pending request outlives the process. `deputy approvals pending`
answers "what is the system waiting on" without a running agent.

**Expiring.** A grant carries a deadline, 24 hours by default. An approval is a
judgment made against a situation, and situations move. Renewing is cheap;
discovering that a week-old yes authorised something surprising is not.

**Evaluated at use.** `consume` checks expiry at the moment of use, not by a
sweep. A system whose safety depends on a cleanup job having run is one that
fails open when the job does not. `sweep` exists, and it is cosmetic: it tidies
the queue a human looks at, and correctness does not rest on it.

**Attributable.** Who granted it and when is recorded, because "the system was
approved to do that" is not an answer anyone can act on.

## The request is made by the engine, not the caller

`authorize` parks the request itself whenever it returns REQUIRE_APPROVAL.

The first version had the agent call `request_approval` after seeing the
verdict, which is the same shape as a capability check the caller is expected
to remember to run. Any other code path reaching the engine directly, and there
are several, would gate correctly and silently fail to record that anyone was
waiting. Putting it inside `authorize` means there is no way to get a gated
verdict without the request existing.

## Idempotent on key

Re-requesting an existing pending or granted approval returns the existing one.
Without this, an agent that re-proposes the same action on every scheduled run
grows the queue with copies of one question, and the human's queue becomes
noise they stop reading, which defeats the mechanism more thoroughly than
losing a request would.

## Filenames are hashed, not sanitised

Sanitising a key into a filename is where two different keys become one file,
and for a file that carries authority that is the same class of bug as the
ambiguous approval key this system already had once. The name is a readable
prefix plus a hash of the full key.

## Consequences

Good: the pending queue is inspectable with `git log`, `cat`, and the CLI. A
human can grant, deny, or read the reasoning without the agent running.

Bad: an approval is now a write, so a vault with no disk space cannot park an
action. The failure is loud, which is the right direction, but it is a new
dependency for a path that previously could not fail.

Bad: there is no locking. Two processes consuming the same single-use approval
in the same instant could both succeed. The window is small and the fix is a
lock file or an atomic compare-and-swap on the document; neither is built, and
this is the most likely place a real deployment would need work first.

Bad: expiry is checked against the engine's clock, which after postmortem 0002
is at least the same clock the rate limiter uses. It is still wall time on one
machine, and two machines disagreeing about now will disagree about whether a
grant has lapsed.
