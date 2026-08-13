"""A deliberately small frontmatter parser.

This does not implement YAML. It implements the subset of YAML that a
human hand-editing a note in a text editor actually writes: flat scalar
keys, block lists of scalars, and inline lists. Anything else raises.

The temptation is to reach for PyYAML and accept whatever it gives back.
The reason not to is that this format is a contract between a human and a
set of autonomous writers. A parser that quietly coerces `state: on` into
the boolean `True`, or accepts a nested structure that half the writers do
not know how to round-trip, produces corruption that surfaces days later in
an agent's behaviour rather than immediately at the edit. Failing loudly at
parse time is worth more than being permissive.

See docs/adr/0002-plaintext-state.md.
"""

from __future__ import annotations

import re
from typing import Any

DELIMITER = "---"

_INT = re.compile(r"^-?\d+$")
_FLOAT = re.compile(r"^-?\d+\.\d+$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class FrontmatterError(ValueError):
    """Raised when a document's frontmatter is not in the supported subset."""

    def __init__(self, message: str, *, line_no: int | None = None, line: str | None = None):
        self.line_no = line_no
        self.line = line
        if line_no is not None:
            message = f"line {line_no}: {message}"
        if line is not None:
            message = f"{message}\n  |  {line}"
        super().__init__(message)


def _scalar(raw: str, line_no: int) -> Any:
    """Convert a scalar token, preserving anything ambiguous as a string."""
    value = raw.strip()
    if not value:
        return ""

    # Quoted values are always strings, verbatim. This is the escape hatch for
    # anything that would otherwise be coerced: "true", "2026-08-03", "007".
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        # Mirror the escaping done by _emit. Without this, a value containing
        # a quote came back with its backslashes still attached.
        return inner.replace('\\"', '"').replace("\\\\", "\\")

    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("null", "~"):
        return None
    if _INT.match(value):
        return int(value)
    if _FLOAT.match(value):
        return float(value)
    if _ISO_DATE.match(value):
        # Kept as a string on purpose. Dates that round-trip through a date
        # object come back with a different textual form, which shows up as a
        # spurious diff on every write and makes the audit log useless.
        return value
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_scalar(item, line_no) for item in inner.split(",")]
    if value.startswith("{"):
        raise FrontmatterError(
            "inline maps are not supported; use flat keys or a block list",
            line_no=line_no,
            line=raw,
        )
    return value


def loads(text: str) -> tuple[dict[str, Any], str]:
    """Split a document into (frontmatter, body).

    A document with no frontmatter block returns an empty dict and the whole
    text as the body. That is the common case for a note a human started
    without ceremony, and it is not an error.
    """
    if not text.startswith(DELIMITER):
        return {}, text

    lines = text.split("\n")
    closing = None
    for i in range(1, len(lines)):
        if lines[i].strip() == DELIMITER:
            closing = i
            break
    if closing is None:
        raise FrontmatterError("frontmatter block opened but never closed")

    meta: dict[str, Any] = {}
    pending_key: str | None = None

    for offset, line in enumerate(lines[1:closing], start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if line.startswith(("  - ", "- ", "\t- ")):
            if pending_key is None:
                raise FrontmatterError("list item with no key above it", line_no=offset, line=line)
            item = line.split("- ", 1)[1]
            existing = meta.get(pending_key)
            if isinstance(existing, list):
                existing.append(_scalar(item, offset))
            elif existing in ("", None):
                meta[pending_key] = [_scalar(item, offset)]
            else:
                # `k: value` followed by `- item` silently discarded `value`.
                # This module promises to fail loudly rather than guess.
                raise FrontmatterError(
                    f"list item under key {pending_key!r} which already has a scalar value",
                    line_no=offset,
                    line=line,
                )
            continue

        if line.startswith((" ", "\t")):
            raise FrontmatterError(
                "nested mappings are not supported; flatten the key", line_no=offset, line=line
            )

        if ":" not in line:
            raise FrontmatterError("expected 'key: value'", line_no=offset, line=line)

        key, _, raw = line.partition(":")
        key = key.strip()
        if not key:
            raise FrontmatterError("empty key", line_no=offset, line=line)
        if key in meta:
            raise FrontmatterError(f"duplicate key {key!r}", line_no=offset, line=line)

        if not raw.strip():
            # Either a block list follows, or the value is genuinely empty.
            # Recorded as empty; a following list item will overwrite it.
            meta[key] = ""
            pending_key = key
        else:
            meta[key] = _scalar(raw, offset)
            pending_key = key

    body = "\n".join(lines[closing + 1 :])
    return meta, body.lstrip("\n")


def _emit(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if "\n" in text:
        raise FrontmatterError(
            "multi-line values are not supported in frontmatter; put it in the body"
        )
    # Quote anything that would parse back as a different type, so that
    # dumps -> loads is a genuine round trip.
    already_quoted = len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'"
    needs_quotes = (
        text.strip() != text
        or text.lower() in ("true", "false", "null", "~")
        or _INT.match(text)
        or _FLOAT.match(text)
        or _ISO_DATE.match(text)
        or text.startswith(("[", "{", "#", "-"))
        or ":" in text
        or text == ""
        # A value that is itself wrapped in quote characters must be quoted,
        # or _scalar strips them on the way back in and the round trip loses
        # them silently. Found by property-testing dumps(loads(x)) == x.
        or already_quoted
        or "\\" in text
    )
    if needs_quotes:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def dumps(meta: dict[str, Any], body: str = "") -> str:
    """Serialise frontmatter and body back to a document.

    Key order is preserved rather than sorted. A stable order means the diff
    of an autonomous write shows only what actually changed, which is the
    whole point of keeping state in git.
    """
    if not meta:
        return body

    lines = [DELIMITER]
    for key, value in meta.items():
        # A key containing a colon or a newline produces a document that
        # parses back as something else entirely, silently. dumps used to
        # emit it happily; refusing is the only honest option, since there is
        # no quoting form for keys in this subset.
        if ":" in str(key) or "\n" in str(key):
            raise FrontmatterError(f"key may not contain ':' or a newline: {key!r}")
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                lines.extend(f"  - {_emit(item)}" for item in value)
        else:
            lines.append(f"{key}: {_emit(value)}")
    lines.append(DELIMITER)
    lines.append("")
    return "\n".join(lines) + body
