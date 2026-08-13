"""Retry with exponential backoff and full jitter.

Two decisions worth stating, because both are commonly got wrong:

Only transient failures are retried. A schema violation or a refusal is
deterministic; retrying it three times produces the same answer three times,
three times the cost, and three times the latency before the same failure
surfaces. The type of the exception carries that distinction, which is why
the model layer bothers to raise two different ones.

Jitter is full, not equal. Without jitter, a fleet of agents that all hit a
rate limit at the same moment retry at the same moment, and the retry storm
reproduces the condition that caused it. Full jitter (sleep uniformly in
[0, backoff]) spreads them; the slightly higher mean delay is a good trade
against a synchronised second failure.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

from deputy.runtime.model import TransientModelError

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    retry_on: tuple[type[BaseException], ...] = (TransientModelError,)

    def backoff(self, attempt: int, rand: Callable[[], float] = random.random) -> float:
        """Full jitter: uniform in [0, min(max, base * 2**attempt)]."""
        ceiling = min(self.max_delay, self.base_delay * (2**attempt))
        return rand() * ceiling


def retry(
    fn: Callable[[], T],
    policy: RetryPolicy | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[], float] = random.random,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> T:
    """Call fn, retrying only the exception types the policy names.

    `sleep` and `rand` are injected so tests can run the real backoff logic
    without real delays and without flakiness.
    """
    policy = policy or RetryPolicy()
    last: BaseException | None = None

    for attempt in range(policy.attempts):
        try:
            return fn()
        except policy.retry_on as exc:
            last = exc
            if attempt == policy.attempts - 1:
                break
            delay = policy.backoff(attempt, rand)
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            sleep(delay)

    assert last is not None
    raise last
