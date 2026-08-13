# Postmortem 0002: Rate limit windows that never expired

**Severity:** medium. Caught by a test before it ran anywhere.
**Found by:** `test_rate_limit_window_expires`

## What happened

`PolicyEngine` takes an injectable `clock` so that time-dependent behaviour can
be tested without sleeping. The rate limiter read `self.clock()` to get "now",
then compared it against the `at` timestamp on each audit entry.

`record_performed` wrote those entries without passing `at`, so `AuditLog`
filled it in with its own default: `time.time()`.

Under the real clock the two agree and everything works, which is why this
survived being written. Under any injected clock they do not. The test set the
engine's clock to 1,000,000 while entries were stamped at roughly 1.7 billion,
so `now - entry.at` came out around negative 1.7 billion, which is comfortably
less than a day, so every entry ever written counted as "within the window",
forever. Advancing the fake clock by a day changed nothing.

## Why it is worth writing up

The symptom in production would have been a cap that tripped once and never
released. Someone would have noticed eventually, since the agent would stop
doing a thing it used to do, and the investigation would have started at the
policy file, which was correct, rather than at a default argument two modules
away.

The deeper issue is that the engine and the log were reading time from two
different sources while doing arithmetic that only makes sense if they share
one. That is not a bug in either component. It is a bug in the seam, and it is
invisible in any test that does not move the clock.

## Fix

`record_performed` passes `at=self.clock()`. The engine's clock is now the
single source of time for anything the engine later does arithmetic on, and
the reason is written at the call site rather than left to be rediscovered.

## What made it findable

The test asserts the property rather than the implementation: perform an action
under a cap of one, confirm the next is gated, advance the clock past the
window, confirm it is allowed again. A test that only checked "the cap trips"
would have passed. The window expiring is the half of a rate limiter that is
easy to leave untested, because it is the half that needs time to pass.

## Generalisation

Any component that accepts an injectable clock has to pass that clock to
everything it later compares timestamps against. Injecting it in one place and
not the other is worse than not injecting it at all, because the resulting
system passes its tests under the real clock and is wrong under the fake one,
which is the opposite of what a seam for testing is meant to achieve.

Two places in this repo still take time from elsewhere and are worth watching:
`Vault.write` lets `AuditLog` stamp its own entries, and `run_suite` takes a
`clock` for durations only. Neither currently feeds arithmetic that depends on
agreeing with the engine. If either ever does, this bug comes back.
