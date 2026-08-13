"""A git-backed store of markdown documents.

The state layer is a directory of markdown files in a git repository. Agents
read and write the same files a human reads and writes, with a text editor,
at the same time.

The obvious alternative is a database. A database would be faster to query
and would give real transactions. The reason not to use one here is that the
failure mode this system actually has is not a slow query, it is an agent
writing something wrong while nobody is watching. Plain files in git mean
every autonomous change has a diff, a blame, and a revert, and a human can
repair the state with the tool already open on their screen. That tradeoff
is only correct at this scale, and the point at which it stops being correct
is written down in docs/adr/0002-plaintext-state.md.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from deputy.store.audit import GITATTRIBUTES_RULE, AuditLog
from deputy.store.frontmatter import dumps, loads


class VaultError(RuntimeError):
    pass


@dataclass
class Document:
    """A markdown file with frontmatter, addressed by vault-relative path."""

    path: str
    meta: dict[str, Any]
    body: str

    def render(self) -> str:
        return dumps(self.meta, self.body)


class Vault:
    """A directory of markdown documents, optionally under git."""

    def __init__(self, root: str | Path, *, git: bool = True):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.audit = AuditLog(self.root / ".deputy" / "audit.jsonl")
        self._git = git and self._git_available()
        if self._git:
            self._ensure_repo()

    # ---------------------------------------------------------------- paths

    #: Directories inside the vault that agents must never write to. `.git`
    #: because a writable hooks directory is arbitrary code execution on the
    #: next commit; `.deputy` because it holds the audit log, and an agent
    #: able to truncate the log can erase its own trail and reset every
    #: rate-limit window at the same time. Both live under root, so the
    #: traversal check alone does not cover them.
    PROTECTED = (".git", ".deputy")

    def _resolve(self, path: str, *, write: bool = False) -> Path:
        """Resolve a vault-relative path, refusing escapes and control dirs.

        Agents choose these paths, sometimes straight from model output. A
        path like `../../.ssh/authorized_keys` is not a hypothetical, it is
        the first thing that happens when a document key is interpolated into
        a filename without checking.
        """
        if not str(path).strip():
            raise VaultError("empty path")

        candidate = (self.root / path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise VaultError(f"path escapes vault root: {path!r}")
        if candidate == self.root:
            raise VaultError("path resolves to the vault root itself")

        if write:
            parts = candidate.relative_to(self.root).parts
            if parts and parts[0] in self.PROTECTED:
                raise VaultError(
                    f"refusing to write inside {parts[0]}/: it is control state, not content"
                )
        return candidate

    # ------------------------------------------------------------------ io

    def read(self, path: str) -> Document:
        target = self._resolve(path)
        if not target.exists():
            raise FileNotFoundError(path)
        meta, body = loads(target.read_text(encoding="utf-8"))
        return Document(path=path, meta=meta, body=body)

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def write(
        self,
        path: str,
        meta: dict[str, Any],
        body: str = "",
        *,
        actor: str = "unknown",
        reason: str = "",
    ) -> Document:
        """Write a document and record the write in the audit log.

        The audit entry is written after the file, not before. If the process
        dies between the two, the log under-reports rather than claiming a
        write that did not land, and the git diff is the backstop. The
        opposite ordering produces a log that is confidently wrong.
        """
        target = self._resolve(path, write=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        doc = Document(path=path, meta=meta, body=body)

        existed = target.exists()
        previous = target.read_text(encoding="utf-8") if existed else None
        rendered = doc.render()
        if previous == rendered:
            return doc  # no-op writes do not deserve a log line

        target.write_text(rendered, encoding="utf-8")
        self.audit.append(
            actor=actor,
            action="write",
            subject=path,
            outcome="updated" if existed else "created",
            detail={"reason": reason, "bytes": len(rendered)},
        )
        return doc

    def update_meta(
        self, path: str, changes: dict[str, Any], *, actor: str = "unknown", reason: str = ""
    ) -> Document:
        doc = self.read(path)
        merged = dict(doc.meta)
        merged.update(changes)
        return self.write(path, merged, doc.body, actor=actor, reason=reason)

    def glob(self, pattern: str = "**/*.md") -> Iterator[Document]:
        for target in sorted(self.root.glob(pattern)):
            if not target.is_file():
                continue
            if ".deputy" in target.parts or ".git" in target.parts:
                continue
            rel = str(target.relative_to(self.root))
            try:
                yield self.read(rel)
            except Exception:  # noqa: BLE001 - a malformed note must not halt a sweep
                continue

    def query(self, **equals: Any) -> list[Document]:
        """Documents whose frontmatter matches every given key."""
        return [d for d in self.glob() if all(d.meta.get(k) == v for k, v in equals.items())]

    # ----------------------------------------------------------------- git

    @staticmethod
    def _git_available() -> bool:
        try:
            subprocess.run(["git", "--version"], capture_output=True, check=True, timeout=5)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _run_git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=check,
            timeout=30,
        )

    def _ensure_repo(self) -> None:
        if (self.root / ".git").exists():
            self._ensure_merge_driver()
            return
        self._run_git("init", "-q")
        self._run_git("config", "user.email", "deputy@localhost")
        self._run_git("config", "user.name", "deputy")
        self._ensure_merge_driver()

    def _ensure_merge_driver(self) -> None:
        """Register the union merge strategy for the audit log.

        Without this, two agents committing on separate branches produce a
        conflict on every shared run, and the usual resolution is to take one
        side, which silently discards the other agent's history.
        """
        attributes = self.root / ".gitattributes"
        existing = attributes.read_text(encoding="utf-8") if attributes.exists() else ""
        if "merge=union" not in existing:
            attributes.write_text(existing + GITATTRIBUTES_RULE, encoding="utf-8")

    def commit(self, message: str) -> str | None:
        """Commit the current state. Returns the short sha, or None if clean."""
        if not self._git:
            return None
        self._run_git("add", "-A")
        status = self._run_git("status", "--porcelain")
        if not status.stdout.strip():
            return None
        self._run_git("commit", "-q", "-m", message)
        return self._run_git("rev-parse", "--short", "HEAD").stdout.strip()
