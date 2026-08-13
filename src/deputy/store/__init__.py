"""Provenance: durable, human-editable, attributable state."""

from deputy.store.audit import AuditLog, Entry
from deputy.store.frontmatter import FrontmatterError, dumps, loads
from deputy.store.vault import Document, Vault

__all__ = [
    "AuditLog",
    "Document",
    "Entry",
    "FrontmatterError",
    "Vault",
    "dumps",
    "loads",
]
