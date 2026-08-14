---
version: 1
calibrated: never. v1 is a prior, not a measurement
---

> **Sanitised.** Real file from the running system. Personal details, employers,
> compensation figures and location are replaced with `[redacted]` or a generic
> equivalent. Structure, weights, thresholds and reasoning are verbatim.

# Fit rubric

Produces a 0-100 score and a written justification for every discovered role.
The score routes the role; the justification is what actually gets read. **A
score without reasoning is not output.**

**This rubric is a prior, not a measurement.** v1 weights are reasoned guesses.
They get corrected against outcomes, not before. Treat early scores as
provisional and say so.

## Gate: hard filters, run first

A role failing any of these is discarded without scoring, **and the count is
reported in the digest so silent attrition stays visible.**

Location outside the acceptable set · stated compensation topping out below the
floor · citizenship requirement · current employer or its merger counterparty ·
a non-target function · junior or mid level.

## Dimensions

Six dimensions, 100 points. Every dimension cites the specific profile evidence
it scored on.

### 1. Seam fit (30 points)

*Does this role need both halves of the profile, or only one?*

The heaviest dimension, deliberately. This is where the candidate wins.

- **25-30**: the posting explicitly requires both.
- **15-24**: one side is the core requirement, the other is a strong plus.
- **7-14**: single-discipline role where the other half is a quiet advantage
  but nobody is screening for it.
- **0-6**: pure specialist posting. The other half is dead weight and the
  candidate is competing on depth they do not have.

A high score everywhere else with a 0-6 here should not clear the surface
threshold. **That combination is the trap:** a role that looks close on title
and is a bad bet in practice.

### 2. Requirement coverage (25 points)

*Of the must-have requirements, how many are met with real evidence?*

Score `met / total × 25`, counting **only must-haves**. Nice-to-haves do not
count here. A requirement is met only if a specific line in the profile supports
it. Inference does not count, **and this is the dimension where fabrication
pressure is highest.**

List unmet must-haves explicitly in the justification. Three or more caps the
total at 60 regardless of everything else.

### 3. Seniority and scope match (15 points)

*Is the scope in the posting comparable to scope actually held?*

Roles asking for materially more score low and the justification says why.
**Roles asking for materially less are also a downgrade and also score low.**
The rubric penalises both directions, because taking a role beneath demonstrated
scope is a different failure, not a safe one.

Stated years-of-experience requirements lose points here rather than gating the
role out, because they are frequently soft.

### 4. Domain leverage (15 points)

*Does the specific domain background matter here, or is it unleveraged?*

Banded by how directly prior domain depth transfers, from a maximum where the
background is uncommon and directly relevant, down to zero where there is no
connection. **Not disqualifying at the bottom, just unleveraged.**

### 5. Trajectory (10 points)

*Does taking this move toward the stated goal, or sideways?*

Roles that build owned surface area or genuine autonomy score high. **Roles that
are the current job at a different employer score low even when the compensation
is good, especially when the compensation is good, because that is the trap that
ends the search without advancing anything.**

### 6. Practical signals (5 points)

Compensation stated and above floor · location unambiguous · posted within 14
days · a real application path rather than a dead portal · no sponsorship
language that wastes time · company not in a visible layoff cycle.

## Routing

| Score | Action |
|---|---|
| **85-100** | Auto-apply band. Package generated, submitted, notified after the fact with what was sent. |
| **70-84** | Full package sent with an `APPROVE` prompt. Nothing submitted until a human replies. |
| **55-69** | Written to `opportunities/` and rolled into the weekly digest. No package. |
| **< 55** | Logged and dropped. Counted in the digest, not detailed. |

### Two mandatory overrides on the auto-apply band

**No role auto-applies if it has any unmet must-have, or if seam fit scored
below 15, regardless of total.** Both route to `APPROVE` instead.

These exist because the failure modes of auto-apply are asymmetric: **a missed
opportunity costs a week, an application that overstates costs a relationship.**

## Calibration

The weights above are reasoned guesses with no outcome data behind them.

They are not to be retuned below roughly twenty scored results with known
outcomes. Adjusting them on a handful of data points is fitting noise, and it
feels exactly like doing the work.

---

## Note added when this was published

The `calibrated: never` in the frontmatter has been true for the entire life of
this file. The rubric has scored a few dozen roles and has never been checked
against whether its scores predicted anything, because the outcomes take months
and there are not enough yet.

`deputy`'s `evals/` package is the machinery for closing that gap. The
refusal-on-small-samples behaviour in `calibration.assess()` is this file's
discipline, made mechanical.
