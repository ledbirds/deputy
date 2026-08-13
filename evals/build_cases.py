"""Generate the triage golden set.

The cases are synthetic, and the README says so plainly. What they are not is
arbitrary: each archetype is a shape of inbound issue that a maintainer would
recognise, and each carries a ground-truth `outcome` meaning "did a maintainer
actually have to deal with this within a day".

The important detail is the noise. Roughly one case in seven has an outcome
that contradicts what its signals suggest, because that is the world: the
dramatic data-loss report that turns out to be a duplicate already fixed on
main, the one-line question from the person who happens to be integrating for
a customer shipping on Friday. A golden set without those produces a
calibration report that looks excellent and has measured nothing except its
own construction.

Regenerate with:  python evals/build_cases.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.triage.rubric import band_for  # noqa: E402

OUT = Path(__file__).resolve().parent / "cases" / "triage.json"

ALL_SIGNALS = [
    "data_loss",
    "security",
    "regression",
    "reproducible",
    "blocks_release",
    "many_affected",
    "has_workaround",
    "question_not_bug",
    "stale_version",
    "no_detail",
]

# (label, signals-that-are-true, base probability the outcome is genuinely urgent)
ARCHETYPES: list[tuple[str, list[str], float]] = [
    ("silent-data-loss", ["data_loss", "reproducible", "many_affected"], 0.95),
    ("data-loss-thin", ["data_loss", "no_detail"], 0.70),
    ("security-report", ["security", "reproducible"], 0.90),
    ("security-vague", ["security", "no_detail"], 0.55),
    ("release-blocker", ["blocks_release", "reproducible", "regression"], 0.92),
    ("regression-with-workaround", ["regression", "reproducible", "has_workaround"], 0.45),
    ("regression-broad", ["regression", "many_affected", "reproducible"], 0.80),
    ("support-question", ["question_not_bug", "has_workaround"], 0.05),
    ("support-question-thin", ["question_not_bug", "no_detail"], 0.03),
    ("stale-version-report", ["stale_version", "reproducible"], 0.10),
    ("stale-and-thin", ["stale_version", "no_detail"], 0.04),
    ("plain-bug-reproducible", ["reproducible"], 0.30),
    ("plain-bug-thin", ["no_detail"], 0.08),
    ("broad-annoyance", ["many_affected", "has_workaround", "reproducible"], 0.35),
]

TITLES = {
    "silent-data-loss": "Rows dropped without error during bulk import",
    "data-loss-thin": "lost my data",
    "security-report": "Session token accepted after logout",
    "security-vague": "possible security problem, contact me privately",
    "release-blocker": "Build fails on the release branch after upgrade",
    "regression-with-workaround": "Sort order flipped in 4.1, can pin to 4.0",
    "regression-broad": "Every scheduled job fires an hour late since DST change",
    "support-question": "How do I configure a proxy?",
    "support-question-thin": "does this work with postgres",
    "stale-version-report": "Crash on startup (running 2.9)",
    "stale-and-thin": "broken",
    "plain-bug-reproducible": "Tooltip renders behind the modal",
    "plain-bug-thin": "layout weird on mobile",
    "broad-annoyance": "Export button needs a double click the first time",
}


def build(seed: int = 20260813, per_archetype: int = 3) -> list[dict]:
    rng = random.Random(seed)
    cases: list[dict] = []
    n = 0

    for name, true_signals, base in ARCHETYPES:
        for variant in range(per_archetype):
            n += 1
            signals = {s: (s in true_signals) for s in ALL_SIGNALS}

            # A third of cases have one signal the extractor could not
            # determine. The rubric must handle unknown, not assume false.
            if variant == 2:
                unknown = rng.choice([s for s in ALL_SIGNALS if s not in true_signals])
                signals[unknown] = None

            outcome = rng.random() < base

            cases.append(
                {
                    "id": f"tri-{n:03d}",
                    "inputs": {"signals": signals},
                    "expect": band_for(base),
                    "outcome": outcome,
                    "tags": [name, "urgent" if outcome else "not-urgent"],
                    "note": TITLES[name],
                }
            )
    return cases





if __name__ == "__main__":
    cases = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    urgent = sum(1 for c in cases if c["outcome"])
    print(f"wrote {len(cases)} cases to {OUT}")
    print(f"base rate: {urgent}/{len(cases)} = {urgent / len(cases):.3f} genuinely urgent")
