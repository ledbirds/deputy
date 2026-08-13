"""Run a golden set through a system and report what happened.

Cases live as JSON on disk, not in test code, so the set can grow when a bug
is found without touching the runner, and so a non-engineer can add one.

Two things this harness does that a bare loop does not:

  It records cost and latency per case. An eval that only reports quality
  will happily bless a change that doubles accuracy and decuples spend.

  It separates a case that scored badly from a case that blew up. Those get
  averaged together constantly, and they mean completely different things:
  one is a quality regression, the other is a bug.
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from deputy.evals.scorers import Scorer, exact


@dataclass(frozen=True)
class Case:
    id: str
    inputs: dict[str, Any]
    expect: Any
    tags: tuple[str, ...] = ()
    # Optional ground truth for calibration: did the good outcome occur?
    outcome: bool | None = None
    note: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Case":
        return cls(
            id=str(raw["id"]),
            inputs=raw.get("inputs", {}),
            expect=raw.get("expect"),
            tags=tuple(raw.get("tags", ())),
            outcome=raw.get("outcome"),
            note=raw.get("note", ""),
        )


@dataclass
class CaseResult:
    case: Case
    score: float = 0.0
    reason: str = ""
    got: Any = None
    confidence: float | None = None
    error: str | None = None
    elapsed_s: float = 0.0
    cost_usd: float = 0.0

    @property
    def errored(self) -> bool:
        return self.error is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.case.id,
            "score": round(self.score, 4),
            "reason": self.reason,
            "confidence": self.confidence,
            "outcome": self.case.outcome,
            "error": self.error,
            "elapsed_s": round(self.elapsed_s, 3),
            "cost_usd": round(self.cost_usd, 6),
            "tags": list(self.case.tags),
        }


@dataclass
class EvalReport:
    suite: str
    results: list[CaseResult] = field(default_factory=list)
    started_at: float = 0.0
    duration_s: float = 0.0

    @property
    def scored(self) -> list[CaseResult]:
        return [r for r in self.results if not r.errored]

    @property
    def errors(self) -> list[CaseResult]:
        return [r for r in self.results if r.errored]

    @property
    def mean_score(self) -> float:
        """Mean over cases that ran. Errors are reported separately, never as zero.

        Folding an exception in as a zero makes a crash look like a quality
        problem and lets a fix for the crash masquerade as a quality gain.
        """
        if not self.scored:
            return 0.0
        return statistics.mean(r.score for r in self.scored)

    @property
    def pass_rate(self) -> float:
        if not self.scored:
            return 0.0
        return sum(1 for r in self.scored if r.score >= 0.999) / len(self.scored)

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.results)

    @property
    def p50_latency(self) -> float:
        times = sorted(r.elapsed_s for r in self.results)
        return statistics.median(times) if times else 0.0

    @property
    def p95_latency(self) -> float:
        times = sorted(r.elapsed_s for r in self.results)
        if not times:
            return 0.0
        return times[min(len(times) - 1, int(0.95 * len(times)))]

    def by_tag(self) -> dict[str, float]:
        buckets: dict[str, list[float]] = {}
        for r in self.scored:
            for tag in r.case.tags:
                buckets.setdefault(tag, []).append(r.score)
        return {tag: statistics.mean(scores) for tag, scores in sorted(buckets.items())}

    def calibration_inputs(self) -> tuple[list[float], list[bool]]:
        pairs = [
            (r.confidence, r.case.outcome)
            for r in self.results
            if r.confidence is not None and r.case.outcome is not None
        ]
        return [p for p, _ in pairs], [o for _, o in pairs]

    def worst(self, k: int = 5) -> list[CaseResult]:
        return sorted(self.scored, key=lambda r: r.score)[:k]

    def as_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "n": len(self.results),
            "errors": len(self.errors),
            "mean_score": round(self.mean_score, 4),
            "pass_rate": round(self.pass_rate, 4),
            "cost_usd": round(self.total_cost, 6),
            "p50_latency_s": round(self.p50_latency, 3),
            "p95_latency_s": round(self.p95_latency, 3),
            "duration_s": round(self.duration_s, 3),
            "by_tag": {k: round(v, 4) for k, v in self.by_tag().items()},
            "results": [r.as_dict() for r in self.results],
        }

    def render(self) -> str:
        lines = [
            f"suite: {self.suite}",
            f"cases: {len(self.results)}   errored: {len(self.errors)}",
            f"mean score: {self.mean_score:.3f}   pass rate: {self.pass_rate:.1%}",
            f"cost: ${self.total_cost:.4f}   p50 {self.p50_latency:.3f}s   "
            f"p95 {self.p95_latency:.3f}s",
        ]
        tags = self.by_tag()
        if tags:
            lines.append("")
            lines.append("by tag:")
            lines.extend(f"  {tag:<20} {score:.3f}" for tag, score in tags.items())
        weak = [r for r in self.worst() if r.score < 0.999]
        if weak:
            lines.append("")
            lines.append("weakest cases:")
            lines.extend(f"  {r.case.id:<24} {r.score:.2f}  {r.reason}" for r in weak)
        if self.errors:
            lines.append("")
            lines.append("errors:")
            lines.extend(f"  {r.case.id:<24} {r.error}" for r in self.errors)
        return "\n".join(lines)


def load_cases(path: str | Path) -> list[Case]:
    """Load cases from a .json array or a .jsonl file."""
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if target.suffix == ".jsonl":
        return [Case.from_dict(json.loads(line)) for line in text.splitlines() if line.strip()]
    return [Case.from_dict(raw) for raw in json.loads(text)]


def run_suite(
    name: str,
    cases: list[Case],
    fn: Callable[[dict[str, Any]], Any],
    *,
    scorer: Scorer = exact,
    extract: Callable[[Any], tuple[Any, float | None, float]] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> EvalReport:
    """Run every case through `fn` and score the output.

    `extract` pulls (value, confidence, cost) out of whatever `fn` returns,
    so the harness stays agnostic about the shape of the system under test.
    """
    report = EvalReport(suite=name, started_at=time.time())
    suite_started = clock()

    for case in cases:
        result = CaseResult(case=case)
        started = clock()
        try:
            raw = fn(case.inputs)
            if extract is not None:
                value, confidence, cost = extract(raw)
            else:
                value, confidence, cost = raw, None, 0.0
            result.got = value
            result.confidence = confidence
            result.cost_usd = cost
            result.score, result.reason = scorer(value, case.expect)
        except Exception as exc:  # noqa: BLE001 - one bad case must not end the suite
            result.error = f"{type(exc).__name__}: {exc}"
        result.elapsed_s = clock() - started
        report.results.append(result)

    report.duration_s = clock() - suite_started
    return report
