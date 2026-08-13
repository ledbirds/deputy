"""Calibration: treating an agent's judgments as predictions and checking them."""

from deputy.evals.calibration import (
    CalibrationReport,
    Reliability,
    bootstrap_ci,
    brier_score,
    expected_calibration_error,
    reliability_bins,
)
from deputy.evals.harness import Case, CaseResult, EvalReport, run_suite
from deputy.evals.scorers import exact, numeric_within, set_f1, verdict_match

__all__ = [
    "CalibrationReport",
    "Case",
    "CaseResult",
    "EvalReport",
    "Reliability",
    "bootstrap_ci",
    "brier_score",
    "exact",
    "expected_calibration_error",
    "numeric_within",
    "reliability_bins",
    "run_suite",
    "set_f1",
    "verdict_match",
]
