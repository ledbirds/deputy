"""Is the agent's confidence worth anything?

An agent that scores an item 87 out of 100 is making a claim. Accuracy alone
does not test that claim: a system that says 87 for everything and is right
87% of the time looks accurate and is useless for ranking, because the number
carries no information about which items are the good ones.

Calibration is the property that when the agent says 0.8, the thing happens
about 80% of the time. Three measures here, each answering something the
others do not:

  Brier score   Mean squared error of the probabilities. Lower is better.
                Rewards being both right and appropriately confident.
  ECE           Average gap between stated confidence and observed rate,
                bucketed. Says how far off the confidence is, in the units
                the confidence is expressed in.
  Reliability   The per-bucket numbers behind ECE, so a systematic bias
                (over-confident at the top end, say) is visible rather than
                averaged away.

The guard that matters most is `min_samples`. A Brier score over eleven cases
is noise wearing a decimal point. This module refuses to report a headline
number below a threshold and says why, because the failure it exists to
prevent is a plausible-looking metric being used to justify retuning a rubric
that nobody has actually measured yet.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

DEFAULT_MIN_SAMPLES = 25
DEFAULT_BINS = 5


class NotEnoughData(ValueError):
    """Raised when a sample is too small for the requested statistic."""


def brier_score(predictions: list[float], outcomes: list[bool]) -> float:
    """Mean squared error between stated probability and observed outcome."""
    if len(predictions) != len(outcomes):
        raise ValueError("predictions and outcomes differ in length")
    if not predictions:
        raise NotEnoughData("no predictions")
    return sum((p - (1.0 if o else 0.0)) ** 2 for p, o in zip(predictions, outcomes)) / len(
        predictions
    )


def base_rate_brier(outcomes: list[bool]) -> float:
    """Brier score of always predicting the base rate.

    This is the number to beat. A model that cannot beat it is adding cost
    and no information, and reporting its Brier score without this alongside
    makes it look informative when it is not.
    """
    if not outcomes:
        raise NotEnoughData("no outcomes")
    rate = sum(1 for o in outcomes if o) / len(outcomes)
    return sum((rate - (1.0 if o else 0.0)) ** 2 for o in outcomes) / len(outcomes)


@dataclass(frozen=True)
class Reliability:
    lower: float
    upper: float
    count: int
    mean_confidence: float
    observed_rate: float

    @property
    def gap(self) -> float:
        return abs(self.mean_confidence - self.observed_rate)


def reliability_bins(
    predictions: list[float], outcomes: list[bool], bins: int = DEFAULT_BINS
) -> list[Reliability]:
    """Bucket predictions and compare stated confidence to observed rate.

    Empty buckets are omitted rather than reported as zero. A bucket with no
    cases in it is missing evidence, and rendering it as a point at the origin
    on a reliability diagram invents a data point that does not exist.
    """
    if len(predictions) != len(outcomes):
        raise ValueError("predictions and outcomes differ in length")

    edges = [i / bins for i in range(bins + 1)]
    result: list[Reliability] = []

    for i in range(bins):
        lower, upper = edges[i], edges[i + 1]
        last = i == bins - 1
        members = [
            (p, o)
            for p, o in zip(predictions, outcomes)
            if (lower <= p <= upper if last else lower <= p < upper)
        ]
        if not members:
            continue
        confidences = [p for p, _ in members]
        hits = [o for _, o in members]
        result.append(
            Reliability(
                lower=lower,
                upper=upper,
                count=len(members),
                mean_confidence=sum(confidences) / len(confidences),
                observed_rate=sum(1 for o in hits if o) / len(hits),
            )
        )
    return result


def expected_calibration_error(
    predictions: list[float], outcomes: list[bool], bins: int = DEFAULT_BINS
) -> float:
    """Size-weighted mean gap between confidence and observed rate."""
    buckets = reliability_bins(predictions, outcomes, bins)
    if not buckets:
        raise NotEnoughData("no populated bins")
    total = sum(b.count for b in buckets)
    return sum(b.count * b.gap for b in buckets) / total


def bootstrap_ci(
    predictions: list[float],
    outcomes: list[bool],
    *,
    statistic=brier_score,
    resamples: int = 2000,
    confidence: float = 0.95,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap interval for a statistic.

    Seeded, so a committed eval result is reproducible. An interval on a
    small sample will be embarrassingly wide, which is the point: it makes
    the uncertainty visible instead of letting a point estimate imply
    precision the data does not support.
    """
    if not predictions:
        raise NotEnoughData("no predictions")

    rng = random.Random(seed)
    n = len(predictions)
    draws: list[float] = []

    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        try:
            draws.append(statistic([predictions[i] for i in idx], [outcomes[i] for i in idx]))
        except (NotEnoughData, ZeroDivisionError):
            continue

    if not draws:
        raise NotEnoughData("every resample was degenerate")

    draws.sort()
    tail = (1.0 - confidence) / 2.0
    lo = draws[max(0, math.floor(tail * len(draws)))]
    hi = draws[min(len(draws) - 1, math.ceil((1 - tail) * len(draws)) - 1)]
    return lo, hi


@dataclass
class CalibrationReport:
    n: int
    brier: float | None = None
    brier_ci: tuple[float, float] | None = None
    baseline_brier: float | None = None
    ece: float | None = None
    bins: list[Reliability] = field(default_factory=list)
    caveat: str = ""
    min_samples: int = DEFAULT_MIN_SAMPLES
    #: True when the sample was too small and figures were withheld entirely.
    withheld: bool = False

    @property
    def informative(self) -> bool:
        """True when the predictions beat always guessing the base rate."""
        if self.brier is None or self.baseline_brier is None:
            return False
        return self.brier < self.baseline_brier

    @property
    def skill(self) -> float | None:
        """Brier skill score: 1 is perfect, 0 is no better than the base rate."""
        if self.brier is None or not self.baseline_brier:
            return None
        return 1.0 - (self.brier / self.baseline_brier)

    def render(self) -> str:
        if self.brier is None:
            return f"n={self.n}. {self.caveat}"

        lines = [
            f"n = {self.n}",
            f"Brier            {self.brier:.4f}"
            + (
                f"   95% CI [{self.brier_ci[0]:.4f}, {self.brier_ci[1]:.4f}]"
                if self.brier_ci
                else ""
            ),
            f"Base rate Brier  {self.baseline_brier:.4f}   (the number to beat)",
        ]
        if self.skill is not None:
            lines.append(f"Skill            {self.skill:+.3f}")
        if self.ece is not None:
            lines.append(f"ECE              {self.ece:.4f}")
        if self.bins:
            lines.append("")
            lines.append("  bucket        n   stated   observed     gap")
            for b in self.bins:
                lines.append(
                    f"  {b.lower:.1f}-{b.upper:.1f}  {b.count:>5}   "
                    f"{b.mean_confidence:6.3f}   {b.observed_rate:8.3f}  {b.gap:6.3f}"
                )
        if self.caveat:
            lines.extend(["", self.caveat])
        return "\n".join(lines)


def assess(
    predictions: list[float],
    outcomes: list[bool],
    *,
    bins: int = DEFAULT_BINS,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    seed: int = 0,
) -> CalibrationReport:
    """Full calibration assessment, with an honest refusal on small samples."""
    if len(predictions) != len(outcomes):
        raise ValueError("predictions and outcomes differ in length")

    n = len(predictions)
    report = CalibrationReport(n=n, min_samples=min_samples)

    if n < min_samples:
        # Refuse, rather than disclaim. An earlier version set this caveat and
        # then computed and returned the figure anyway, so `render()` printed
        # a headline number under a paragraph saying not to trust it. In
        # practice the number is what gets quoted. Withholding it is the only
        # version of this guardrail that actually guards anything.
        report.withheld = True
        report.caveat = (
            f"Sample of {n} is below the {min_samples}-case floor, so no headline figure is "
            "reported. At this size the confidence interval is wider than any effect worth "
            "acting on. Pass min_samples explicitly to override, and say so when you quote it."
        )
        return report

    if n == 0:
        return report

    if len(set(outcomes)) < 2:
        report.caveat = (
            f"All {n} outcomes are identical, so calibration is undefined: there is no "
            "variation for the predictions to track. Collect cases from both classes."
        )
        return report

    report.brier = brier_score(predictions, outcomes)
    report.baseline_brier = base_rate_brier(outcomes)
    report.bins = reliability_bins(predictions, outcomes, bins)
    try:
        report.ece = expected_calibration_error(predictions, outcomes, bins)
    except NotEnoughData:
        report.ece = None
    try:
        report.brier_ci = bootstrap_ci(predictions, outcomes, seed=seed)
    except NotEnoughData:
        report.brier_ci = None

    return report
