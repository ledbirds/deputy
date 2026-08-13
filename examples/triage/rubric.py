"""The triage rubric: a scoring function that states its own uncertainty.

The rubric answers one question: will this inbound issue need a maintainer's
attention within a day. It returns a probability, not a grade out of a
hundred, because a probability is a claim that can be checked against what
actually happened, and a grade out of a hundred quietly cannot.

Everything here is a hand-set weight. That is a prior, not a measurement, and
the header of every report says so. The weights were chosen by reasoning about
which signals matter, then measured; `evals/results/` holds what the
measurement actually said, including where the reasoning was wrong.

Deliberately deterministic and model-free. A rubric that calls an LLM cannot
be evaluated separately from the LLM, so a calibration regression becomes
impossible to attribute. The model's job in this system is extraction, which
is what models are good at. The judgment stays in code that can be diffed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# Signal -> (weight, why). Weights are log-odds contributions, so evidence
# composes additively and the result stays in [0, 1] without clamping.
SIGNALS: dict[str, tuple[float, str]] = {
    "data_loss": (2.2, "an issue that destroys user data outranks everything else"),
    "security": (2.0, "even unconfirmed, a security report is triaged fast or not at all"),
    "regression": (1.3, "something that worked last release is a promise broken"),
    "reproducible": (0.9, "a report a maintainer can reproduce is one they can act on"),
    "blocks_release": (1.5, "a blocker is urgent by definition"),
    "many_affected": (1.0, "breadth turns a bug into a priority"),
    "has_workaround": (-1.1, "a workaround buys time, which is what urgency spends"),
    "question_not_bug": (-1.8, "a support question is real work but not maintainer-urgent"),
    "stale_version": (-1.2, "a report against an old release is usually already fixed"),
    "no_detail": (-1.5, "a report with nothing in it cannot be acted on today"),
}

BASE_LOG_ODDS = -1.1  # most inbound issues are not same-day urgent


def _sigmoid(x: float) -> float:
    """Numerically stable logistic. Both branches avoid overflowing exp."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


@dataclass
class Judgment:
    """A score, the reasoning behind it, and what would change it."""

    probability: float
    band: str
    contributions: list[tuple[str, float, str]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def confident(self) -> bool:
        """Whether the score is far enough from the fence to route on alone."""
        return self.probability <= CONFIDENT_BELOW or self.probability >= CONFIDENT_ABOVE

    def explain(self) -> str:
        lines = [f"{self.probability:.2f} ({self.band})"]
        for name, weight, why in self.contributions:
            lines.append(f"  {weight:+.1f}  {name}: {why}")
        if self.missing:
            lines.append(f"  unknown: {', '.join(self.missing)}")
        if not self.confident:
            lines.append("  near the threshold; route to a human rather than acting on this")
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return {
            "probability": round(self.probability, 4),
            "band": self.band,
            "confident": self.confident,
            "contributions": [
                {"signal": n, "weight": w, "why": y} for n, w, y in self.contributions
            ],
            "missing": self.missing,
        }


#: The only place bands are defined. `evals/build_cases.py` imports this
#: rather than restating it: the generator and the system under test used to
#: carry byte-identical copies of the thresholds, which is a silent drift
#: waiting to happen and makes the eval look more independent than it is.
BANDS: tuple[tuple[float, str], ...] = (
    (0.75, "urgent"),
    (0.45, "soon"),
    (0.20, "backlog"),
    (0.00, "low"),
)

#: Below the lowest or above the highest of these, the score is far enough
#: from a band edge to route on. Tied to BANDS on purpose: these were 0.25
#: and 0.7 while the bands used 0.20 and 0.75, an undocumented drift that
#: made `confident` mean something slightly different from what it looked
#: like it meant.
CONFIDENT_BELOW = BANDS[2][0]
CONFIDENT_ABOVE = BANDS[0][0]


def band_for(p: float) -> str:
    for threshold, name in BANDS:
        if p >= threshold:
            return name
    return BANDS[-1][1]


def score(signals: dict[str, Any]) -> Judgment:
    """Score an issue from extracted boolean signals.

    Unknown signals are recorded as missing rather than assumed false.
    Treating an absent signal as a negative is how a thin report ends up
    scored as confidently unimportant, which is the exact case where the
    system should be least sure of itself.
    """
    total = BASE_LOG_ODDS
    contributions: list[tuple[str, float, str]] = []
    missing: list[str] = []

    for name, (weight, why) in SIGNALS.items():
        if name not in signals or signals[name] is None:
            missing.append(name)
            continue
        if signals[name]:
            total += weight
            contributions.append((name, weight, why))

    unknown = [k for k in signals if k not in SIGNALS]
    if unknown:
        raise ValueError(f"unknown signals: {sorted(unknown)}")

    probability = _sigmoid(total)
    return Judgment(
        probability=probability,
        band=band_for(probability),
        contributions=sorted(contributions, key=lambda c: -abs(c[1])),
        missing=missing,
    )
