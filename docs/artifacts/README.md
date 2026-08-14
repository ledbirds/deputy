# Artifacts from the running system

These are real files from the system described in [../origins.md](../origins.md),
with identifying detail removed. They are here because the design claims in this
repo are easier to believe when you can see what the thing they came from
actually produces.

## What was removed and what was kept

**Removed.** My name, employers past and present, the companies whose roles were
scored, URLs, compensation figures, my location, and the specific details of
personal projects that would identify me. Anywhere a redaction changes the
shape of the document, it is marked rather than silently smoothed over.

**Kept.** The structure, the weights, the thresholds, the routing logic, and
the reasoning, unchanged in substance. Punctuation is normalised to this repo's
house style and nothing else was touched. The judgment is the part worth showing, and none
of it depends on knowing who I am.

Nothing here has been improved for publication. Where the reasoning is
hedged, or where a file admits it has not been checked against reality, that is
how it reads in the vault.

## The files

| File | What it is |
|---|---|
| [`scoring-rubric.md`](scoring-rubric.md) | The six-dimension fit rubric the discovery agent scores every role against |
| [`scored-opportunity.md`](scored-opportunity.md) | One role as the agent actually wrote it up, including what it thought would disqualify me |
| [`constitution.md`](constitution.md) | The scoped `CLAUDE.md` governing one workspace: ground truth, mandate, guardrails |

## How these became `deputy`

The rubric is why `evals/calibration.py` exists. Read its header: *"This rubric
is a prior, not a measurement."* That line has been sitting in my vault,
unresolved, for the entire life of the system. The rubric has scored a few dozen
roles and has never once been checked against whether its scores predicted
anything.

`deputy`'s calibration harness is the machinery for closing that gap, built
against synthetic data because the real outcomes take months to arrive and there
are not yet enough of them. The honesty about sample size in that module is not
a stylistic choice. It is the same discipline this rubric file has been
enforcing on itself by refusing to retune.

The constitution is why `policy/` exists. It is prose asking a model to behave.
The policy engine is a gate the model cannot talk its way past. Moving from one
to the other is the central lesson of the original system.
