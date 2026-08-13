"""Scorers: how a case result is compared to its expectation.

Each scorer returns a float in [0, 1] and a short reason. The reason is not
decoration. When an eval regresses, the first question is which cases moved
and why, and a bare 0.82 answers neither.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

Scorer = Callable[[Any, Any], tuple[float, str]]


def exact(got: Any, want: Any) -> tuple[float, str]:
    if got == want:
        return 1.0, "exact match"
    return 0.0, f"got {got!r}, want {want!r}"


def case_insensitive(got: Any, want: Any) -> tuple[float, str]:
    if str(got).strip().lower() == str(want).strip().lower():
        return 1.0, "match ignoring case and surrounding space"
    return 0.0, f"got {got!r}, want {want!r}"


def numeric_within(tolerance: float) -> Scorer:
    """Score 1 when |got - want| <= tolerance, degrading linearly to 0 at 2x."""

    def scorer(got: Any, want: Any) -> tuple[float, str]:
        try:
            g, w = float(got), float(want)
        except (TypeError, ValueError):
            return 0.0, f"not numeric: got {got!r}, want {want!r}"
        delta = abs(g - w)
        if delta <= tolerance:
            return 1.0, f"within {tolerance} (off by {delta:.3f})"
        if delta >= 2 * tolerance:
            return 0.0, f"off by {delta:.3f}, tolerance {tolerance}"
        partial = 1.0 - (delta - tolerance) / tolerance
        return partial, f"off by {delta:.3f}, partial credit {partial:.2f}"

    return scorer


def set_f1(got: Any, want: Any) -> tuple[float, str]:
    """F1 over two collections treated as sets."""
    g = set(got if isinstance(got, Iterable) and not isinstance(got, str) else [got])
    w = set(want if isinstance(want, Iterable) and not isinstance(want, str) else [want])
    if not g and not w:
        return 1.0, "both empty"
    overlap = len(g & w)
    if overlap == 0:
        return 0.0, f"no overlap; missing {sorted(w - g)}, spurious {sorted(g - w)}"
    precision = overlap / len(g)
    recall = overlap / len(w)
    f1 = 2 * precision * recall / (precision + recall)
    return f1, f"P {precision:.2f} R {recall:.2f}; missing {sorted(w - g)}, spurious {sorted(g - w)}"


def verdict_match(got: Any, want: Any) -> tuple[float, str]:
    """Compare policy verdicts, with asymmetric partial credit.

    Being too restrictive and being too permissive are not equally wrong. A
    system that asks for approval when it could have proceeded wastes a
    human's attention. A system that proceeds when it should have asked has
    already done the thing. Half credit for erring toward caution, zero for
    erring toward action, so an eval average cannot be improved by loosening.
    """
    order = {"allow": 0, "require_approval": 1, "deny": 2}
    g = str(got).strip().lower()
    w = str(want).strip().lower()

    if g == w:
        return 1.0, "verdict matches"
    if g not in order or w not in order:
        return 0.0, f"unknown verdict: got {got!r}, want {want!r}"
    if order[g] > order[w]:
        return 0.5, f"over-restrictive: got {g}, want {w}"
    return 0.0, f"UNDER-restrictive: got {g}, want {w}"


def contains_all(got: Any, want: Any) -> tuple[float, str]:
    """Fraction of required substrings present in the output."""
    haystack = str(got).lower()
    needles = list(want) if isinstance(want, (list, tuple)) else [want]
    if not needles:
        return 1.0, "nothing required"
    present = [n for n in needles if str(n).lower() in haystack]
    score = len(present) / len(needles)
    missing = [n for n in needles if n not in present]
    return score, ("all present" if not missing else f"missing {missing}")
