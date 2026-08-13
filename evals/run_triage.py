"""Run the triage suite and write a result file.

    python evals/run_triage.py

Two reports come out of one run, because they answer different questions.

  Quality      Does the rubric put issues in the right band? Measured with a
               scorer that gives partial credit for being one band off, since
               a "soon" that should have been "urgent" is a different failure
               from a "low" that should have been "urgent".

  Calibration  When the rubric says 0.8, does the thing happen 80% of the
               time? This is the one that can invalidate the rubric even when
               quality looks fine, and it is the one almost nobody runs.

The result JSON is committed. A metric nobody can reproduce is a claim, and
this repo is meant to be checkable rather than believed.
"""

from __future__ import annotations

import json
import sys

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from deputy.evals import calibration  # noqa: E402
from deputy.evals.harness import load_cases, run_suite  # noqa: E402
from examples.triage.rubric import score  # noqa: E402

CASES = ROOT / "evals" / "cases" / "triage.json"
RESULTS = ROOT / "evals" / "results"

BANDS = ["low", "backlog", "soon", "urgent"]


def band_distance(got: Any, want: Any) -> tuple[float, str]:
    """Partial credit by how many bands off the call was.

    Exact is 1.0, one band away is 0.5, further is 0. A flat exact-match
    scorer treats "called it soon instead of urgent" the same as "called it
    low instead of urgent", and those are not the same mistake.
    """
    try:
        gi, wi = BANDS.index(str(got)), BANDS.index(str(want))
    except ValueError:
        return 0.0, f"unknown band: got {got!r}, want {want!r}"
    gap = abs(gi - wi)
    if gap == 0:
        return 1.0, "exact band"
    if gap == 1:
        direction = "high" if gi > wi else "low"
        return 0.5, f"one band too {direction} ({got} vs {want})"
    return 0.0, f"{gap} bands off ({got} vs {want})"


def main() -> int:
    cases = load_cases(CASES)

    def run(inputs: dict[str, Any]) -> Any:
        return score(inputs["signals"])

    report = run_suite(
        "triage-rubric",
        cases,
        run,
        scorer=band_distance,
        extract=lambda j: (j.band, j.probability, 0.0),
    )

    predictions, outcomes = report.calibration_inputs()
    cal = calibration.assess(predictions, outcomes, bins=5, min_samples=25)

    print(report.render())
    print()
    print("=" * 60)
    print("CALIBRATION: are the probabilities worth anything?")
    print("=" * 60)
    print(cal.render())
    print()
    if cal.informative:
        print(f"The rubric beats the base rate. Skill {cal.skill:+.3f}.")
    else:
        print("The rubric does NOT beat always guessing the base rate.")

    RESULTS.mkdir(parents=True, exist_ok=True)

    # The committed artifact is deliberately deterministic: no wall-clock
    # timestamp, no latency figures. Both change on every run and on every
    # machine, and if the file churns then `git diff --exit-code` in CI stops
    # being a reproducibility check and becomes noise people learn to ignore.
    # Timing is real and worth knowing, so it is printed above; it just does
    # not belong in an artifact whose job is to be byte-identical.
    quality = report.as_dict()
    for volatile in ("p50_latency_s", "p95_latency_s", "duration_s"):
        quality.pop(volatile, None)
    for case in quality["results"]:
        case.pop("elapsed_s", None)

    # Rounded to 6 decimals, and the reason is not cosmetic.
    #
    # Python 3.12 changed `sum()` to use Neumaier compensated summation for
    # floats, so a sum of the same values in the same order differs in its
    # last bits between 3.11 and 3.12. Committing 17 significant digits made
    # the reproducibility gate fail on 3.12 while passing on 3.10 and 3.11,
    # reporting a version difference as a regression.
    #
    # Six decimals is also the honest precision. A Brier score whose 95%
    # interval spans 0.118 to 0.269 does not have seventeen meaningful digits,
    # and a real regression moves it by far more than 1e-15. The gate stays
    # strict where strictness means something.
    def r6(x):
        return None if x is None else round(x, 6)

    payload = {
        "suite_version": "2",
        "cases_file": str(CASES.relative_to(ROOT)),
        "quality": quality,
        "calibration": {
            "n": cal.n,
            "brier": r6(cal.brier),
            "brier_ci_95": [r6(v) for v in cal.brier_ci] if cal.brier_ci else None,
            "baseline_brier": r6(cal.baseline_brier),
            "skill": r6(cal.skill),
            "ece": r6(cal.ece),
            "informative": cal.informative,
            "caveat": cal.caveat,
            "bins": [
                {
                    "range": [b.lower, b.upper],
                    "n": b.count,
                    "mean_confidence": round(b.mean_confidence, 4),
                    "observed_rate": round(b.observed_rate, 4),
                    "gap": round(b.gap, 4),
                }
                for b in cal.bins
            ],
        },
    }
    out = RESULTS / "triage.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
