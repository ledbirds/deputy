"""Store tests: frontmatter round trips, audit durability, path safety."""

from __future__ import annotations

import json

import pytest

from deputy.store.audit import AuditLog, Entry
from deputy.store.frontmatter import FrontmatterError, dumps, loads
from deputy.store.vault import Vault, VaultError


class TestFrontmatter:
    def test_round_trip_preserves_types_and_order(self):
        meta = {"state": "applied", "score": 89, "ratio": 0.75, "live": True, "tags": ["a", "b"]}
        parsed, body = loads(dumps(meta, "# Title\n\nbody\n"))
        assert parsed == meta
        assert list(parsed) == list(meta), "key order must survive, or every write diffs"
        assert body.startswith("# Title")

    @pytest.mark.parametrize(
        "value", ["true", "false", "null", "2026-08-13", "007", "3.14", "yes: no"]
    )
    def test_ambiguous_strings_survive_a_round_trip(self, value):
        """The failure this prevents: `state: on` silently becoming a boolean."""
        parsed, _ = loads(dumps({"k": value}))
        assert parsed["k"] == value
        assert isinstance(parsed["k"], str)

    def test_iso_dates_stay_strings(self):
        parsed, _ = loads("---\napplied: 2026-08-13\n---\n")
        assert parsed["applied"] == "2026-08-13"

    def test_document_without_frontmatter_is_not_an_error(self):
        meta, body = loads("just a note\n")
        assert meta == {}
        assert body == "just a note\n"

    def test_unclosed_block_raises(self):
        with pytest.raises(FrontmatterError, match="never closed"):
            loads("---\nkey: value\n\nbody")

    def test_nested_mapping_raises_rather_than_guessing(self):
        with pytest.raises(FrontmatterError, match="nested"):
            loads("---\nouter:\n  inner: 1\n---\n")

    def test_duplicate_key_raises(self):
        with pytest.raises(FrontmatterError, match="duplicate"):
            loads("---\nk: 1\nk: 2\n---\n")

    def test_error_reports_the_offending_line(self):
        with pytest.raises(FrontmatterError) as exc:
            loads("---\ngood: 1\nthis line has no colon\n---\n")
        assert "line 3" in str(exc.value)

    def test_block_lists(self):
        meta, _ = loads("---\ntags:\n  - one\n  - two\n---\n")
        assert meta["tags"] == ["one", "two"]

    def test_inline_lists(self):
        meta, _ = loads("---\ntags: [one, two]\n---\n")
        assert meta["tags"] == ["one", "two"]


class TestAuditLog:
    def test_append_and_read(self, tmp_path):
        log = AuditLog(tmp_path / "a.jsonl")
        log.append(actor="x", action="write", subject="s", outcome="ok")
        entries = log.read()
        assert len(entries) == 1
        assert entries[0].actor == "x"

    def test_union_merge_duplicates_collapse(self, tmp_path):
        """git merge=union can duplicate a line. It must not double count."""
        path = tmp_path / "a.jsonl"
        log = AuditLog(path)
        entry = log.append(actor="x", action="act", subject="s", outcome="performed")

        with open(path, "a", encoding="utf-8") as handle:
            handle.write(entry.to_line() + "\n")  # the duplicate a union merge leaves

        assert len(log.read()) == 1

    def test_identical_events_under_a_frozen_clock_stay_distinct(self, tmp_path):
        """Dedup must not collapse genuinely separate events.

        An earlier version hashed content and excluded seq, so five identical
        actions performed at the same clock value read back as one. Since rate
        limits are computed by counting entries, that was a cap bypass under
        exactly the frozen clock the tests inject. There was a test asserting
        the old behaviour, which is how it survived review.
        """
        log = AuditLog(tmp_path / "a.jsonl")
        for _ in range(5):
            log.append(
                actor="a", action="act", subject="s", outcome="performed", at=1_000_000.0
            )
        assert len(log.read()) == 5

    def test_a_line_duplicated_by_union_merge_still_collapses(self, tmp_path):
        """The property dedup actually exists for."""
        path = tmp_path / "a.jsonl"
        log = AuditLog(path)
        entry = log.append(actor="x", action="act", subject="s", outcome="performed")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(entry.to_line() + "\n")
        assert len(log.read()) == 1

    def test_two_writers_do_not_collide_on_seq(self, tmp_path):
        path = tmp_path / "a.jsonl"
        one, two = AuditLog(path, writer="aaa"), AuditLog(path, writer="bbb")
        one.append(actor="x", action="act", subject="s", outcome="performed", at=1.0)
        two.append(actor="y", action="act", subject="s", outcome="performed", at=1.0)
        assert len(one.read()) == 2

    @pytest.mark.parametrize("line", ["5", '"hello"', "null", "true", "[1,2]"])
    def test_valid_json_that_is_not_an_object_is_damage(self, tmp_path, line):
        """These raised AttributeError, which escaped read()'s handler.

        One such line made the whole history unreadable, and because the
        policy engine reads the log on every rate-limit check, it took the
        engine down too.
        """
        path = tmp_path / "a.jsonl"
        log = AuditLog(path)
        log.append(actor="x", action="write", subject="s", outcome="ok")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")

        entries, damaged = log.read_with_damage()
        assert len(entries) == 1 and damaged == 1

    def test_non_dict_detail_is_damage(self, tmp_path):
        path = tmp_path / "a.jsonl"
        log = AuditLog(path)
        log.append(actor="x", action="write", subject="s", outcome="ok")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"actor": "x", "action": "a", "subject": "s",
                                     "outcome": "ok", "at": 1.0, "detail": "oops"}) + "\n")
        entries, damaged = log.read_with_damage()
        assert len(entries) == 1 and damaged == 1

    def test_corrupt_line_is_skipped_not_fatal(self, tmp_path):
        path = tmp_path / "a.jsonl"
        log = AuditLog(path)
        log.append(actor="x", action="write", subject="s", outcome="ok")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("{ this is not json\n")
        log.append(actor="y", action="write", subject="t", outcome="ok")

        entries, damaged = log.read_with_damage()
        assert len(entries) == 2
        assert damaged == 1

    def test_conflict_markers_are_damage_not_data(self, tmp_path):
        path = tmp_path / "a.jsonl"
        log = AuditLog(path)
        log.append(actor="x", action="write", subject="s", outcome="ok")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("<<<<<<< HEAD\n=======\n>>>>>>> other\n")

        entries, damaged = log.read_with_damage()
        assert len(entries) == 1
        assert damaged == 3

    def test_entries_sort_by_time(self, tmp_path):
        log = AuditLog(tmp_path / "a.jsonl")
        log.append(actor="x", action="a", subject="s", outcome="ok", at=300.0)
        log.append(actor="x", action="b", subject="s", outcome="ok", at=100.0)
        assert [e.action for e in log.read()] == ["b", "a"]

    def test_unknown_fields_from_a_newer_writer_are_carried_not_dropped(self, tmp_path):
        path = tmp_path / "a.jsonl"
        raw = {
            "actor": "x",
            "action": "a",
            "subject": "s",
            "outcome": "ok",
            "at": 1.0,
            "detail": {},
            "seq": 0,
            "future_field": "keep me",
        }
        path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
        entry = AuditLog(path).read()[0]
        assert entry.detail["future_field"] == "keep me"


class TestVault:
    def test_write_then_read(self, tmp_path):
        vault = Vault(tmp_path / "v", git=False)
        vault.write("notes/a.md", {"state": "open"}, "body", actor="t")
        doc = vault.read("notes/a.md")
        assert doc.meta["state"] == "open"
        assert doc.body.strip() == "body"

    def test_write_is_audited(self, tmp_path):
        vault = Vault(tmp_path / "v", git=False)
        vault.write("a.md", {"k": 1}, actor="agent-7", reason="because")
        entry = vault.audit.read()[-1]
        assert entry.actor == "agent-7"
        assert entry.outcome == "created"
        assert entry.detail["reason"] == "because"

    def test_identical_rewrite_is_not_logged(self, tmp_path):
        vault = Vault(tmp_path / "v", git=False)
        vault.write("a.md", {"k": 1}, "b", actor="t")
        before = len(vault.audit.read())
        vault.write("a.md", {"k": 1}, "b", actor="t")
        assert len(vault.audit.read()) == before, "a no-op write is not an event"

    @pytest.mark.parametrize(
        "path", ["../escape.md", "../../etc/passwd", "notes/../../out.md"]
    )
    def test_path_traversal_is_refused(self, tmp_path, path):
        """Agents choose these paths, sometimes straight from model output."""
        vault = Vault(tmp_path / "v", git=False)
        with pytest.raises(VaultError, match="escapes vault root"):
            vault.write(path, {}, "x")

    def test_query_by_frontmatter(self, tmp_path):
        vault = Vault(tmp_path / "v", git=False)
        vault.write("a.md", {"state": "open"}, actor="t")
        vault.write("b.md", {"state": "closed"}, actor="t")
        vault.write("c.md", {"state": "open"}, actor="t")
        assert len(vault.query(state="open")) == 2

    def test_malformed_note_does_not_halt_a_sweep(self, tmp_path):
        vault = Vault(tmp_path / "v", git=False)
        vault.write("good.md", {"state": "open"}, actor="t")
        (vault.root / "bad.md").write_text("---\nunclosed\n", encoding="utf-8")
        assert [d.path for d in vault.glob()] == ["good.md"]

    @pytest.mark.parametrize(
        "path", [".git/hooks/post-commit", ".deputy/audit.jsonl", ".git/config"]
    )
    def test_writes_into_control_directories_are_refused(self, tmp_path, path):
        """These live inside root, so the traversal check does not cover them.

        A writable .git/hooks is arbitrary code execution on the next commit.
        A writable .deputy/audit.jsonl lets an agent erase its own trail and
        reset every rate-limit window in one call.
        """
        vault = Vault(tmp_path / "v", git=False)
        with pytest.raises(VaultError, match="control state"):
            vault.write(path, {}, "x", actor="agent")

    def test_writing_to_the_root_itself_is_refused(self, tmp_path):
        vault = Vault(tmp_path / "v", git=False)
        for bad in ("", ".", "   "):
            with pytest.raises(VaultError):
                vault.write(bad, {}, "x")

    def test_git_repo_gets_the_union_merge_driver(self, tmp_path):
        vault = Vault(tmp_path / "v", git=True)
        if not (vault.root / ".git").exists():
            pytest.skip("git unavailable")
        assert "merge=union" in (vault.root / ".gitattributes").read_text(encoding="utf-8")
