"""Token and cost accounting with a hard ceiling.

An agent that can loop can spend without bound. Treating budget as a
first-class runtime object rather than a dashboard you check afterwards is
the difference between a run that stops at the limit and a bill that arrives
at the end of the month.

The ceiling is enforced before the call, not after. Checking after means the
call that breaks the budget still happens, which on a long-context request is
exactly the expensive one.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class BudgetExceeded(RuntimeError):
    """Raised when a call would take the run past its ceiling."""

    def __init__(self, spent: float, ceiling: float, *, unit: str = "USD"):
        self.spent = spent
        self.ceiling = ceiling
        super().__init__(f"budget exhausted: {spent:.4f} of {ceiling:.4f} {unit} spent")


@dataclass(frozen=True)
class Price:
    """Cost per million tokens, split by direction."""

    input_per_m: float
    output_per_m: float

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens * self.input_per_m / 1_000_000
            + completion_tokens * self.output_per_m / 1_000_000
        )


# Illustrative rates. Real prices change; this table exists so the accounting
# is exercised, not so it is authoritative. Override per deployment.
PRICES: dict[str, Price] = {
    "scripted": Price(0.0, 0.0),
    "small": Price(0.25, 1.25),
    "large": Price(3.00, 15.00),
}


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    latency_s: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def merge(self, other: "Usage") -> None:
        self.calls += other.calls
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.cost += other.cost
        self.latency_s += other.latency_s

    def as_dict(self) -> dict[str, float | int]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost, 6),
            "latency_s": round(self.latency_s, 3),
        }


@dataclass
class Budget:
    """A spending ceiling for one run, with per-model accounting."""

    ceiling_usd: float = 1.0
    max_calls: int | None = None
    usage: Usage = field(default_factory=Usage)
    per_model: dict[str, Usage] = field(default_factory=dict)

    def remaining(self) -> float:
        return max(0.0, self.ceiling_usd - self.usage.cost)

    def check(self, *, estimated_cost: float = 0.0) -> None:
        """Raise if the run is already over, or would be after this call."""
        if self.max_calls is not None and self.usage.calls >= self.max_calls:
            raise BudgetExceeded(self.usage.calls, self.max_calls, unit="calls")
        if self.usage.cost + estimated_cost > self.ceiling_usd:
            raise BudgetExceeded(self.usage.cost + estimated_cost, self.ceiling_usd)

    def charge(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_s: float = 0.0,
    ) -> float:
        price = PRICES.get(model, PRICES["small"])
        cost = price.cost(prompt_tokens, completion_tokens)
        delta = Usage(
            calls=1,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost,
            latency_s=latency_s,
        )
        self.usage.merge(delta)
        bucket = self.per_model.setdefault(model, Usage())
        bucket.merge(delta)
        return cost

    def report(self) -> dict[str, object]:
        return {
            "ceiling_usd": self.ceiling_usd,
            "total": self.usage.as_dict(),
            "by_model": {name: u.as_dict() for name, u in sorted(self.per_model.items())},
        }


def estimate_cost(model: object, prompt: str, system: str = "", max_output: int = 1024) -> float:
    """Price a call before making it.

    Deliberately pessimistic on the output side: it assumes the completion
    runs to `max_output`. A ceiling enforced on an optimistic estimate is not
    a ceiling, and the direction to be wrong in is refusing a call that would
    have fit rather than making one that does not.
    """
    from deputy.runtime.model import estimate_tokens

    name = getattr(model, "name", "small")
    price = PRICES.get(name, PRICES["small"])
    return price.cost(estimate_tokens(system + prompt), max_output)
