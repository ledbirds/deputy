"""Model interface, plus the two implementations that make this testable.

The provider protocol is four lines. Everything else in this module exists
to solve one problem: an LLM-backed system whose tests call a real model is a
system with no tests. It is slow, it costs money, it fails in CI for reasons
unrelated to the change, and it is non-deterministic, so a passing run proves
very little.

Two implementations address that:

  ScriptedModel  Returns canned completions in order, or keyed by a hash of
                 the prompt. Used in unit tests. Deterministic by design.

  RecordedModel  Wraps a real provider. On a cache miss it calls through and
                 writes the exchange to disk; on a hit it replays. Record
                 once against the real API, then run the suite offline
                 forever. The cassette is committed, so a reviewer can read
                 exactly what the model was asked and what it said.

Both raise the same typed errors as a live provider would, so retry and
budget logic is exercised by the tests rather than only in production.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence


class ModelError(RuntimeError):
    """A model call failed in a way that will not be fixed by retrying."""


class TransientModelError(ModelError):
    """A model call failed in a way that might succeed on retry.

    Rate limits, timeouts, 5xx. Kept distinct from ModelError because
    retrying a genuine schema violation or a refusal just burns budget and
    arrives at the same place slower.
    """


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float = 0.0
    cached: bool = False


class Model(Protocol):
    name: str

    def complete(self, prompt: str, *, system: str = "", temperature: float = 0.0) -> Completion:
        ...


def estimate_tokens(text: str) -> int:
    """A cheap token estimate.

    Roughly four characters per token for English prose. This is not a
    tokenizer and does not claim to be; it exists so that budget accounting
    has a number to work with when a provider does not return usage, and so
    the offline models produce plausible figures. Where a provider reports
    real usage, that is used instead and this is never consulted.
    """
    return max(1, len(text) // 4)


@dataclass
class ScriptedModel:
    """Deterministic model for tests.

    Either a queue of replies consumed in order, or a mapping from a prompt
    substring to a reply. Unmatched prompts raise rather than returning
    something plausible, because a test that silently gets the wrong canned
    answer is worse than one that fails.
    """

    replies: list[str] = field(default_factory=list)
    keyed: dict[str, str] = field(default_factory=dict)
    name: str = "scripted"
    fail_times: int = 0
    _calls: int = field(default=0, init=False)
    _failures: int = field(default=0, init=False)
    seen: list[str] = field(default_factory=list, init=False)

    def complete(self, prompt: str, *, system: str = "", temperature: float = 0.0) -> Completion:
        self.seen.append(prompt)

        if self._failures < self.fail_times:
            self._failures += 1
            raise TransientModelError("scripted transient failure")

        text: str | None = None
        for needle, reply in self.keyed.items():
            if needle in prompt:
                text = reply
                break

        if text is None:
            if self._calls < len(self.replies):
                text = self.replies[self._calls]
            else:
                raise ModelError(
                    "ScriptedModel has no reply for this prompt; "
                    f"call #{self._calls}, {len(self.replies)} queued, "
                    f"{len(self.keyed)} keyed"
                )

        self._calls += 1
        return Completion(
            text=text,
            model=self.name,
            prompt_tokens=estimate_tokens(system + prompt),
            completion_tokens=estimate_tokens(text),
            latency_s=0.0,
        )


@dataclass
class RecordedModel:
    """Record-and-replay wrapper around any Model.

    The cassette is a directory of JSON files, one per distinct request,
    named by a hash of (model, system, prompt, temperature). Committing it
    makes the test suite hermetic and makes the model's actual behaviour
    reviewable in a pull request.
    """

    inner: Model | None
    cassette: Path
    name: str = "recorded"
    allow_record: bool = True
    hits: int = field(default=0, init=False)
    misses: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.cassette = Path(self.cassette)
        self.cassette.mkdir(parents=True, exist_ok=True)

    def _key(self, prompt: str, system: str, temperature: float) -> str:
        """Key on the request only, never on the wrapper's own identity.

        This deliberately excludes the model name. An earlier version folded
        it in, and because the recorder took its name from the inner model
        while the replayer (which has no inner model) kept its default, every
        cassette written by a recorder missed on replay. The recording path
        and the replay path are by construction configured differently, so
        anything derived from that configuration must stay out of the key.
        Use one cassette directory per model instead.
        """
        payload = json.dumps(
            {"system": system, "prompt": prompt, "temperature": temperature},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:24]

    def complete(self, prompt: str, *, system: str = "", temperature: float = 0.0) -> Completion:
        key = self._key(prompt, system, temperature)
        track = self.cassette / f"{key}.json"

        if track.exists():
            self.hits += 1
            raw = json.loads(track.read_text(encoding="utf-8"))
            return Completion(
                text=raw["response"]["text"],
                model=raw["response"].get("model", self.name),
                prompt_tokens=raw["response"]["prompt_tokens"],
                completion_tokens=raw["response"]["completion_tokens"],
                latency_s=raw["response"].get("latency_s", 0.0),
                cached=True,
            )

        self.misses += 1
        if self.inner is None or not self.allow_record:
            raise ModelError(
                f"no recording for this request ({key}) and recording is disabled. "
                "Run with a live provider and DEPUTY_RECORD=1 to capture it."
            )

        started = time.monotonic()
        completion = self.inner.complete(prompt, system=system, temperature=temperature)
        elapsed = time.monotonic() - started

        track.write_text(
            json.dumps(
                {
                    "request": {
                        "model": self.name,
                        "system": system,
                        "prompt": prompt,
                        "temperature": temperature,
                    },
                    "response": {
                        "text": completion.text,
                        "model": completion.model,
                        "prompt_tokens": completion.prompt_tokens,
                        "completion_tokens": completion.completion_tokens,
                        "latency_s": round(elapsed, 4),
                    },
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return completion


@dataclass
class CallableModel:
    """Adapter for wiring in a real provider without importing its SDK here.

    Keeping provider SDKs out of the core is what lets this package have no
    dependencies. Pass a function that takes (prompt, system, temperature)
    and returns text, and translate that provider's exceptions into
    TransientModelError or ModelError at the boundary.
    """

    fn: Callable[[str, str, float], str]
    name: str = "small"
    transient_exceptions: Sequence[type[BaseException]] = ()

    def complete(self, prompt: str, *, system: str = "", temperature: float = 0.0) -> Completion:
        started = time.monotonic()
        try:
            text = self.fn(prompt, system, temperature)
        except BaseException as exc:  # noqa: BLE001 - re-raised as a typed error
            if any(isinstance(exc, kind) for kind in self.transient_exceptions):
                raise TransientModelError(str(exc)) from exc
            raise ModelError(str(exc)) from exc
        elapsed = time.monotonic() - started
        return Completion(
            text=text,
            model=self.name,
            prompt_tokens=estimate_tokens(system + prompt),
            completion_tokens=estimate_tokens(text),
            latency_s=elapsed,
        )


def parse_json_object(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a completion.

    Models wrap JSON in prose and fences no matter how firmly the prompt asks
    them not to. Rather than tightening the prompt forever, extract the object
    and validate it. Raises ModelError, not TransientModelError: asking the
    same model the same question again usually produces the same shape.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```")[1] if "```" in stripped[3:] else stripped[3:]
        if stripped.lstrip().startswith("json"):
            stripped = stripped.lstrip()[4:]

    start = stripped.find("{")
    if start == -1:
        raise ModelError(f"no JSON object in completion: {text[:200]!r}")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(stripped)):
        char = stripped[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(stripped[start : index + 1])
                except json.JSONDecodeError as exc:
                    raise ModelError(f"malformed JSON object: {exc}") from exc

    raise ModelError("unterminated JSON object in completion")
