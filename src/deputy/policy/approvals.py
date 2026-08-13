"""Approvals that survive a restart.

A runtime whose central claim is that approval parks rather than blocks needs
the parked thing to be durable. Holding pending approvals in a dict means the
queue dies with the process: an agent asks at 02:00, the scheduler restarts at
03:00, and the request is gone with nothing recording that a human was ever
waiting on it. Worse, it is gone silently, so the next run asks again and the
human sees a duplicate rather than a resumption.

So approvals live in the vault, in the same markdown format as everything
else, with the same diff and the same audit trail. A request is a document. A
grant is an edit to that document. Both are visible in `git log`.

Three properties the in-memory version did not have:

  Durable    A pending request outlives the process that made it.
  Expiring   A grant has a deadline. An approval nobody used within its
             window lapses instead of sitting there indefinitely waiting to
             authorise something whose context has moved on.
  Attributable  Who granted it and when is recorded, because "the system was
             approved to do that" is not an answer anyone can act on.

See docs/adr/0006-durable-approvals.md.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from deputy.store.vault import Vault

#: Grants lapse after this long by default. Short on purpose: an approval is a
#: judgment made against a situation, and situations move. Renewing is cheap;
#: discovering that a week-old yes authorised something surprising is not.
DEFAULT_TTL_S = 24 * 3600

PENDING = "pending"
GRANTED = "granted"
SPENT = "spent"
DENIED = "denied"
LAPSED = "lapsed"


@dataclass
class Approval:
    """One request for a human decision, and its life cycle."""

    key: str
    action: str
    subject: str
    state: str
    because: str = ""
    requested_at: float = 0.0
    decided_at: float | None = None
    decided_by: str = ""
    expires_at: float | None = None
    uses_left: int = 0
    note: str = ""

    def is_usable(self, now: float) -> bool:
        if self.state != GRANTED or self.uses_left <= 0:
            return False
        return not (self.expires_at is not None and now >= self.expires_at)

    def as_meta(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "action": self.action,
            "subject": self.subject,
            "state": self.state,
            "because": self.because,
            "requested_at": round(self.requested_at, 3),
            "decided_at": round(self.decided_at, 3) if self.decided_at else "",
            "decided_by": self.decided_by,
            "expires_at": round(self.expires_at, 3) if self.expires_at else "",
            "uses_left": self.uses_left,
        }

    @classmethod
    def from_meta(cls, meta: dict[str, Any], body: str = "") -> "Approval":
        def num(value: Any) -> float | None:
            if value in ("", None):
                return None
            return float(value)

        return cls(
            key=str(meta.get("key", "")),
            action=str(meta.get("action", "")),
            subject=str(meta.get("subject", "")),
            state=str(meta.get("state", PENDING)),
            because=str(meta.get("because", "")),
            requested_at=num(meta.get("requested_at")) or 0.0,
            decided_at=num(meta.get("decided_at")),
            decided_by=str(meta.get("decided_by", "")),
            expires_at=num(meta.get("expires_at")),
            uses_left=int(meta.get("uses_left", 0) or 0),
            note=body.strip(),
        )


def _slug(key: str) -> str:
    """A filename-safe, collision-free name for an approval key.

    Hashed rather than sanitised. Sanitising is where two different keys
    become the same filename, and for a file that carries authority that is
    the same class of bug as the ambiguous approval key this replaced.
    """
    import hashlib

    digest = hashlib.sha256(key.encode()).hexdigest()[:12]
    readable = "".join(c if c.isalnum() or c in "-_" else "-" for c in key)[:48]
    return f"{readable}-{digest}"


class ApprovalStore:
    """Approvals as documents in a vault."""

    DIR = "approvals"

    def __init__(
        self,
        vault: Vault,
        *,
        clock: Callable[[], float] = time.time,
        default_ttl_s: float = DEFAULT_TTL_S,
    ):
        self.vault = vault
        self.clock = clock
        self.default_ttl_s = default_ttl_s

    # ------------------------------------------------------------- paths

    def _path(self, key: str) -> str:
        return f"{self.DIR}/{_slug(key)}.md"

    # ------------------------------------------------------------- write

    def request(self, key: str, action: str, subject: str, because: str) -> Approval:
        """Record that an agent wants to do something and needs a human.

        Idempotent on key. An agent that re-proposes the same action on the
        next run must not produce a second request, or a human who has not yet
        answered watches the queue grow with copies of one question.
        """
        existing = self.get(key)
        if existing is not None and existing.state in (PENDING, GRANTED):
            return existing

        approval = Approval(
            key=key,
            action=action,
            subject=subject,
            state=PENDING,
            because=because,
            requested_at=self.clock(),
        )
        self._save(approval, reason="approval requested")
        return approval

    def grant(
        self,
        key: str,
        *,
        by: str = "human",
        uses: int = 1,
        ttl_s: float | None = None,
        note: str = "",
    ) -> Approval:
        approval = self.get(key)
        if approval is None:
            raise KeyError(f"no approval request for {key!r}")
        if uses < 1:
            raise ValueError("uses must be at least 1")

        now = self.clock()
        approval.state = GRANTED
        approval.decided_at = now
        approval.decided_by = by
        approval.uses_left = uses
        approval.expires_at = now + (self.default_ttl_s if ttl_s is None else ttl_s)
        approval.note = note or approval.note
        self._save(approval, reason=f"granted by {by}")
        return approval

    def deny(self, key: str, *, by: str = "human", note: str = "") -> Approval:
        approval = self.get(key)
        if approval is None:
            raise KeyError(f"no approval request for {key!r}")
        approval.state = DENIED
        approval.decided_at = self.clock()
        approval.decided_by = by
        approval.uses_left = 0
        approval.note = note or approval.note
        self._save(approval, reason=f"denied by {by}")
        return approval

    def consume(self, key: str) -> bool:
        """Spend one use. Returns whether the action may proceed.

        Expiry is evaluated here, at the point of use, rather than by a sweep.
        A grant that lapsed an hour ago must not authorise anything even if
        nothing has run since to notice, and a system that depends on a
        cleanup job having run is one that fails open when the job does not.
        """
        approval = self.get(key)
        if approval is None:
            return False

        now = self.clock()
        if approval.state == GRANTED and not approval.is_usable(now):
            if approval.expires_at is not None and now >= approval.expires_at:
                approval.state = LAPSED
                approval.uses_left = 0
                self._save(approval, reason="grant expired before it was used")
            return False

        if not approval.is_usable(now):
            return False

        approval.uses_left -= 1
        if approval.uses_left <= 0:
            approval.state = SPENT
        self._save(approval, reason="approval consumed")
        return True

    # -------------------------------------------------------------- read

    def get(self, key: str) -> Approval | None:
        path = self._path(key)
        if not self.vault.exists(path):
            return None
        doc = self.vault.read(path)
        return Approval.from_meta(doc.meta, doc.body)

    def pending(self) -> list[Approval]:
        return self._in_state(PENDING)

    def granted(self) -> list[Approval]:
        now = self.clock()
        return [a for a in self._in_state(GRANTED) if a.is_usable(now)]

    def _in_state(self, state: str) -> list[Approval]:
        found: list[Approval] = []
        for doc in self.vault.glob(f"{self.DIR}/*.md"):
            approval = Approval.from_meta(doc.meta, doc.body)
            if approval.state == state:
                found.append(approval)
        return sorted(found, key=lambda a: a.requested_at)

    def sweep(self) -> int:
        """Mark expired grants as lapsed. Returns how many were closed.

        Purely cosmetic: `consume` already refuses an expired grant. This
        exists so the pending queue a human looks at is not full of grants
        that would not work if used, not as a correctness mechanism.
        """
        now = self.clock()
        closed = 0
        for approval in self._in_state(GRANTED):
            if not approval.is_usable(now):
                approval.state = LAPSED
                approval.uses_left = 0
                self._save(approval, reason="grant expired")
                closed += 1
        return closed

    # ------------------------------------------------------------ intern

    def _save(self, approval: Approval, *, reason: str) -> None:
        body = approval.note or (
            f"{approval.action} on {approval.subject or '(no subject)'}\n\n"
            f"{approval.because}\n"
        )
        self.vault.write(
            self._path(approval.key),
            approval.as_meta(),
            body,
            actor="approvals",
            reason=reason,
        )
