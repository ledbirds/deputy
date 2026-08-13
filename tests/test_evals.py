"""Eval and calibration tests.

The measurement layer needs tests more than most code does. A bug in a scorer
does not crash; it quietly reports the wrong number, and the wrong number then
gets used to justify a change.
"""

from __future__ import annotations

import pytest

from deputy.evals.calibration import (
    NotEnoughData,
    assess,
    base_rate_brier,
    bootstrap_ci,
    brier_score,
    expected_calibration_error,
    reliability_bins,
)
from deputy.evals.harness import Case, run_suite
from deputy.evals.scorers import contains_all, exact, numeric_within, set_f1, verdict_match


class TestScorers:
    def test_exact(self):
        assert exact("a", "a")[0] == 1.0
        assert exact("a", "b")[0] == 0.0

    def test_numeric_tolerance_gives_partial_credit(self):
        scorer = numeric_within(1.0)
        assert scorer(10.0, 10.0)[0] == 1.0
        assert scorer(10.5, 10.0)[0] == 1.0
        assert scorer(11.5, 10.0)[0] == pytest.approx(0.5)
        assert scorer(12.5, 10.0)[0] == 0.0

    def test_set_f1(self):
        assert set_f1({"a", "b"}, {"a", "b"})[0] == 1.0
        assert set_f1({"a"}, {"a", "b"})[0] == pytest.approx(2 / 3)
        assert set_f1({"z"}, {"a"})[0] == 0.0

    def test_set_f1_names_what_is_missing(self):
        _, reason = set_f1({"a"}, {"a", "b"})
        assert "missing ['b']" in reason

    def test_verdict_match_is_asymmetric(self):
        """Erring toward caution is half credit; erring toward action is zero.

        Without this, an eval average can be improved by loosening the policy,
        which is exactly backwards.
        """
        assert verdict_match("deny", "deny")[0] == 1.0
        assert verdict_match("deny", "allow")[0] == 0.5
        assert verdict_match("allow", "deny")[0] == 0.0
        assert "UNDER-restrictive" in verdict_match("allow", "require_approval")[1]

    def test_contains_all(self):
        assert contains_all("the quick brown fox", ["quick", "fox"])[0] == 1.0
        assert contains_all("the quick brown fox", ["quick", "zebra"])[0] == 0.5


class TestHarness:
    def test_errors_are_separated_from_low_scores(self):
        """A crash must not be averaged in as a zero.

        Doing so makes a bug look like a quality regression, and makes fixing
        the bug look like a quality improvement.
        """
        cases = [
            Case(id="ok", inputs={"x": 1}, expect=1),
            Case(id="wrong", inputs={"x": 2}, expect=99),
            Case(id="boom", inputs={"x": "explode"}, expect=1),
        ]

        def fn(inputs):
            if inputs["x"] == "explode":
                raise RuntimeError("kaboom")
            return inputs["x"]

        report = run_suite("t", cases, fn)
        assert len(report.errors) == 1
        assert len(report.scored) == 2
        assert report.mean_score == pytest.approx(0.5)

    def test_one_bad_case_does_not_end_the_suite(self):
        cases = [Case(id=str(i), inputs={"i": i}, expect=i) for i in range(5)]

        def fn(inputs):
            if inputs["i"] == 2:
                raise RuntimeError("bad")
            return inputs["i"]

        report = run_suite("t", cases, fn)
        assert len(report.results) == 5

    def test_scores_break_down_by_tag(self):
        cases = [
            Case(id="a", inputs={"v": 1}, expect=1, tags=("easy",)),
            Case(id="b", inputs={"v": 2}, expect=99, tags=("hard",)),
        ]
        report = run_suite("t", cases, lambda i: i["v"])
        assert report.by_tag() == {"easy": 1.0, "hard": 0.0}

    def test_cost_and_latency_are_captured(self):
        cases = [Case(id="a", inputs={}, expect=1)]
        report = run_suite(
            "t", cases, lambda i: (1, 0.5, 0.01), extract=lambda r: (r[0], r[1], r[2])
        )
        assert report.total_cost == pytest.approx(0.01)


class TestCalibration:
    def test_brier_is_zero_for_perfect_confident_predictions(self):
        assert brier_score([1.0, 0.0], [True, False]) == 0.0

    def test_brier_is_one_for_confidently_wrong(self):
        assert brier_score([1.0, 0.0], [False, True]) == 1.0

    def test_base_rate_is_the_number_to_beat(self):
        outcomes = [True] * 7 + [False] * 3
        baseline = base_rate_brier(outcomes)
        useless = brier_score([0.7] * 10, outcomes)
        assert baseline == pytest.approx(useless)

    def test_a_constant_predictor_shows_zero_skill(self):
        outcomes = [True] * 6 + [False] * 4
        report = assess([0.6] * 10, outcomes, min_samples=1)
        assert report.skill == pytest.approx(0.0, abs=1e-9)
        assert not report.informative

    def test_an_informative_predictor_beats_the_base_rate(self):
        preds = [0.9] * 5 + [0.1] * 5
        outcomes = [True] * 5 + [False] * 5
        report = assess(preds, outcomes, min_samples=1)
        assert report.informative
        assert report.skill > 0.5

    def test_reliability_bins_omit_empty_buckets(self):
        bins = reliability_bins([0.05, 0.95], [False, True], bins=5)
        assert len(bins) == 2, "an empty bucket is missing evidence, not a data point"

    def test_reliability_top_bin_includes_one(self):
        bins = reliability_bins([1.0], [True], bins=5)
        assert len(bins) == 1 and bins[0].count == 1

    def test_ece_is_zero_when_perfectly_calibrated(self):
        preds = [0.5] * 10
        outcomes = [True] * 5 + [False] * 5
        assert expected_calibration_error(preds, outcomes, bins=2) == pytest.approx(0.0)

    def test_ece_catches_overconfidence(self):
        preds = [0.9] * 10
        outcomes = [True] * 5 + [False] * 5
        assert expected_calibration_error(preds, outcomes, bins=5) == pytest.approx(0.4)

    def test_small_sample_gets_a_refusal_not_a_headline(self):
        report = assess([0.9, 0.1], [True, False], min_samples=25)
        assert "below the 25-case floor" in report.caveat

    def test_single_class_outcomes_are_reported_as_undefined(self):
        report = assess([0.5] * 30, [True] * 30, min_samples=1)
        assert report.brier is None
        assert "identical" in report.caveat

    def test_bootstrap_is_seeded_and_reproducible(self):
        preds = [0.9] * 10 + [0.2] * 10
        outcomes = [True] * 10 + [False] * 10
        a = bootstrap_ci(preds, outcomes, resamples=200, seed=7)
        b = bootstrap_ci(preds, outcomes, resamples=200, seed=7)
        assert a == b

    def test_bootstrap_interval_brackets_the_estimate(self):
        preds = [0.9] * 10 + [0.2] * 10
        outcomes = [True] * 9 + [False] + [False] * 9 + [True]
        lo, hi = bootstrap_ci(preds, outcomes, resamples=500, seed=1)
        assert lo <= brier_score(preds, outcomes) <= hi

    def test_empty_input_raises_rather_than_returning_zero(self):
        with pytest.raises(NotEnoughData):
            brier_score([], [])

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError):
            brier_score([0.5], [True, False])
