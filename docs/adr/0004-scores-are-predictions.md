# ADR 0004: A rubric score is a prediction, and predictions get scored

**Status:** accepted

## Context

Agents that rank things produce numbers: a fit score, a severity, a priority.
Those numbers get used to route work. Almost nobody checks whether they mean
anything, because the usual eval is accuracy against a label, and accuracy
does not test the number.

A system that outputs 0.87 for everything and is right 87% of the time scores
well on accuracy and is useless for ranking, because the number carries no
information about which items are the good ones.

## Decision

The rubric outputs a probability, not a grade out of a hundred, and the eval
harness measures it as a probability.

Three measures, each answering something the others do not:

- **Brier score.** Mean squared error of the probabilities. Rewards being both
  right and appropriately confident.
- **Base rate Brier.** The score of always predicting the base rate. This is
  reported alongside as *the number to beat*, because a Brier score printed on
  its own looks informative whether or not it is.
- **ECE and reliability bins.** The gap between stated confidence and observed
  rate, bucketed, so a systematic bias at one end is visible rather than
  averaged away. Reporting ECE without the bins hides the shape, and the shape
  is the actionable part.

Confidence intervals are bootstrapped and seeded, so a committed result is
reproducible. On a small sample the interval is embarrassingly wide, which is
the point.

## The rubric does not call a model

The scoring function is deterministic and model-free. A rubric that calls an
LLM cannot be evaluated separately from the LLM, so a calibration regression
becomes impossible to attribute: the weights, the prompt, and the model
version all moved.

The model's job in this system is extraction, turning prose into booleans,
which is what models are good at. The judgment stays in code that can be
diffed, unit-tested, and reasoned about.

## Unknown is not false

A signal the extractor could not determine is recorded as missing, not as
absent. Treating an unknown as a negative is how a thin report gets scored as
confidently unimportant, which is precisely the case where the system should
be least sure of itself.

## The harness refuses small samples

`assess()` takes a `min_samples` floor and, below it, computes the numbers but
attaches a caveat saying they must not be used to retune anything.

This is a guardrail against the specific failure of looking at a
plausible-shaped metric over a dozen cases and adjusting weights until it
improves. That is fitting the noise, and it feels exactly like doing the work.
The weights in this repo are a stated prior, and the README says where the
measurement disagreed with them and why they have not been changed anyway.

## Consequences

Good: the claim "this score is worth something" is checkable, and in this repo
it is checked and comes out as a qualified yes with a named weakness.

Bad: it needs ground truth, which is the expensive part and which synthetic
cases cannot supply honestly. The golden set here is generated, the generator
documents its own noise model, and the README is explicit that 42 synthetic
cases establish the machinery works and are not evidence about the domain.

Bad: there is no held-out split, because with 42 cases a split would leave
neither half meaningful. That is the correct call at this size and the wrong
one at any size where it becomes possible.
