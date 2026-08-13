"""An append-only log that survives concurrent writers.

Two agents finishing inside the same second must not lose each other's
history. The log is JSONL, one self-contained record per line, and the file
is registered with git as `merge=union` so a merge concatenates both sides
instead of raising a conflict.

Union merge has a real cost: it can produce duplicate lines when the same
entry arrives down two branches. That is handled here rather than wished
away. Every entry carries a content-derived id, and `read` de-duplicates on
it, so a duplicated line is idempotent rather than a double count. The
ordering guarantee is per-writer, not global; entries carry a sequence and a
timestamp and the reader sorts, but two writers on separate branches have no
shared clock and the log does not pretend otherwise.

See docs/adr/0003-append-only-audit.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

GITATTRIBUTES_RULE = "*.jsonl merge=union\n"


@dataclass(frozen=True)
class Entry:
    """One recorded event. Immutable by construction."""

    actor: str
    action: str
    subject: str
    outcome: str
    at: float
    detail: dict[str, Any] = field(default_factory=dict)
    seq: int = 0
    writer: str = ""

    @property
    def id(self) -> str:
        """Identity of the *event*, not of the line.

        This is (writer, seq) rather than a hash of the content, and the
        distinction is load-bearing.

        A content hash cannot tell a merge duplicate apart from a genuine
        repeat. Five identical actions performed under a frozen clock hash to
        one value, so they read back as one entry, and since rate limits are
        computed by counting entries that is a cap bypass. An earlier version
        of this file did exactly that and had a test asserting the behaviour,
        which is how it survived.

        (writer, seq) has the property actually wanted. Each AuditLog instance
        gets a writer id at construction, so a line duplicated by `merge=union`
        carries the same pair and collapses, while two distinct events from the
        same writer always differ in `seq` and both survive. Content is
        included only as a tiebreak for the pathological case of two writers
        colliding on an id.
        """
        payload = json.dumps(
            {
                "writer": self.writer,
                "seq": self.seq,
                "actor": self.actor,
                "action": self.action,
                "subject": self.subject,
                "outcome": self.outcome,
                "at": round(self.at, 6),
                "detail": self.detail,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_line(self) -> str:
        payload = asdict(self)
        payload["id"] = self.id
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_line(cls, line: str) -> "Entry":
        raw = json.loads(line)
        # A line that is valid JSON but not an object is damage, not a record.
        # Without this, `5` or `"hello"` on its own line raised AttributeError
        # from the .pop() below, which escaped read()'s handler and made the
        # entire history unreadable. Since the policy engine reads the log on
        # every rate-limit check, one such line took the engine down with it.
        if not isinstance(raw, dict):
            raise ValueError(f"audit line is {type(raw).__name__}, not an object")
        raw.pop("id", None)
        if "detail" in raw and not isinstance(raw["detail"], dict):
            raise ValueError("audit entry 'detail' is not an object")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(raw) - known
        if unknown:
            # Forward compatibility: a newer writer added fields. Keep them
            # in detail rather than dropping them, so the record survives a
            # round trip through an older reader.
            carried = {k: raw.pop(k) for k in unknown}
            raw.setdefault("detail", {}).update(carried)
        return cls(**raw)


class AuditLog:
    """Append-only JSONL log with union-merge-safe reads."""

    def __init__(self, path: str | Path, *, writer: str | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One id per log instance. Two agents in separate processes get
        # different ids, which is what lets (writer, seq) separate their
        # entries without a shared clock or a coordination point.
        self.writer = writer or uuid.uuid4().hex[:12]
        self._seq = self._scan_seq()

    def append(
        self,
        *,
        actor: str,
        action: str,
        subject: str,
        outcome: str,
        detail: dict[str, Any] | None = None,
        at: float | None = None,
    ) -> Entry:
        entry = Entry(
            actor=actor,
            action=action,
            subject=subject,
            outcome=outcome,
            at=at if at is not None else time.time(),
            detail=detail or {},
            seq=self._next_seq(),
            writer=self.writer,
        )
        # Append with an explicit flush + fsync. A crash between the agent
        # taking an action and the log recording it is the one failure that
        # makes the log worse than useless, because it reports less than what
        # happened while looking complete.
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(entry.to_line() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return entry

    def _scan_seq(self) -> int:
        """Highest seq already on disk for this writer, plus one.

        Read once at construction rather than on every append. The previous
        version re-read the whole file per write, which made a run that logged
        n events O(n^2), and counted damaged and duplicate lines so sequence
        numbers skipped.
        """
        if not self.path.exists():
            return 0
        highest = -1
        with open(self.path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                    if isinstance(raw, dict) and raw.get("writer") == self.writer:
                        highest = max(highest, int(raw.get("seq", -1)))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
        return highest + 1

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq += 1
        return seq

    def read(self) -> list[Entry]:
        """All entries, de-duplicated by content id, ordered by timestamp.

        Corrupt lines are skipped rather than fatal. A single bad line from an
        interrupted write should not make the entire history unreadable, and
        the count of skipped lines is available via `read_with_damage`.
        """
        entries, _ = self.read_with_damage()
        return entries

    def read_with_damage(self) -> tuple[list[Entry], int]:
        if not self.path.exists():
            return [], 0

        seen: set[str] = set()
        entries: list[Entry] = []
        damaged = 0

        with open(self.path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                # Union merge leaves conflict markers only if the file was
                # also edited by hand. Treat them as damage, not as data.
                if line.startswith(("<<<<<<<", "=======", ">>>>>>>")):
                    damaged += 1
                    continue
                try:
                    entry = Entry.from_line(line)
                except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
                    damaged += 1
                    continue
                if entry.id in seen:
                    continue
                seen.add(entry.id)
                entries.append(entry)

        entries.sort(key=lambda e: (e.at, e.seq))
        return entries, damaged

    def by_subject(self, subject: str) -> list[Entry]:
        return [e for e in self.read() if e.subject == subject]

    def __iter__(self) -> Iterator[Entry]:
        return iter(self.read())

    def __len__(self) -> int:
        return len(self.read())
