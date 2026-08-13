# Postmortem 0001: A pipeline whose last stage could never execute

**Severity:** high. The system reported success for days while doing nothing.

## What happened

An earlier system this design descends from had a scheduled pipeline: discover
candidate items, score them, package the output, and submit. It ran nightly.
It reported success nightly. Nothing was ever submitted.

The final stage needed a live browser session. The scheduled environment had
no browser and could not have one: the capability was bound to an interactive
session on a desktop machine, not to the environment the schedule ran in. The
stage did not error, because from its own point of view it had nothing to do
and nothing to do is not a failure.

The cause was diagnosed twice as something else before the real one was found.
Both times the wrong diagnosis was acted on, and both times the fix was
plausible enough that its failure to change anything read as bad luck.

## Why it took so long to see

The pipeline was designed end to end and then mapped onto the execution
environment afterwards. That order makes the question "can this stage
physically reach what it needs" one that nobody asks, because by the time the
environment is being configured, the design is already a thing that exists and
the assumption is buried inside it.

A stage doing nothing looks identical to a stage with nothing to do. There was
no assertion anywhere that a run which produced zero submissions was suspicious
rather than quiet.

## What changed in this design

**Capabilities are declared, and the declaration is checked at registration.**
A tool must state `reversible` and `external`. Both are required arguments and
omitting either is a `TypeError` at import, not a surprise at runtime. This
does not by itself catch an unreachable capability, but it forces the moment
where someone writes down what a capability is and what it touches.

**Nothing succeeds silently.** Every step lands in the audit log with an
outcome, including `denied` and `pending_approval`. A run that performed
nothing produces a log that says so, in a form that can be counted.

**Approval parks rather than blocks, and pending work is a first-class
result.** `AgentResult.pending_approval` is a list, separate from `performed`
and `failed`. A caller that never looks at it is making a choice, rather than
being told everything is fine.

**The worked example is run in CI.** The README shows output. If the repo
stops being able to produce that output, CI fails. A demonstration that only
ran once, on the author's machine, on the day it was written, is the same
class of thing as a pipeline that reports success.

## What is still not solved

Nothing here detects that a capability is unreachable in a given environment
before it is invoked. A tool whose backing service is unreachable will still
register happily and fail at call time, and if it fails by doing nothing rather
than by raising, the outcome will be `performed`.

The honest version of this fix is a preflight per capability: a cheap probe run
at startup that asserts the tool can actually reach what it needs, with the
result recorded. That is the right design and it is not built. Writing it down
here is the second-best thing.

## The transferable lesson

Confirm what each stage can physically reach before designing what it does.
The order matters, because a design produced in the other order encodes an
assumption about the environment that nobody will think to question, and that
assumption fails in the one direction that looks like success.
