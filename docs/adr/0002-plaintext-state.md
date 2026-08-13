# ADR 0002: State is markdown in git, not rows in a database

**Status:** accepted

## Context

The system needs durable state: what the agent found, what it decided, what it
is waiting on. The default answer is a database.

## Decision

State is markdown files with frontmatter, in a git repository. Agents read and
write the same files a human reads and writes, at the same time, with a text
editor.

## Why not a database

A database is faster to query, gives real transactions, and has a schema. All
three are genuine advantages and none of them addresses the failure this
system actually has.

The failure this system has is an agent writing something wrong while nobody
is watching. Against that failure, plain files in git give three things a
database does not:

- Every autonomous change has a diff, so "what did it do last night" is
  `git log -p`, not a query against a table that only records current state.
- Every change has a revert, and the revert is one command that a human can
  run at 2am without thinking about foreign keys.
- A human can repair the state with the tool already open on their screen.

The scale at which this is correct is small: one operator, thousands of
documents, no concurrent readers to speak of. The point at which it stops
being correct is when a query needs an index, which in practice means when a
sweep over every document to answer one question becomes slow enough to
notice. That is the tripwire; it has not been hit.

## The parser is deliberately restricted

Frontmatter is parsed by a hand-written parser that handles flat scalar keys,
block lists, and inline lists, and raises on anything else. It is not YAML.

Reaching for PyYAML and accepting whatever it returns is the obvious move and
it is wrong here, because this format is a contract between a human and
several autonomous writers. A parser that quietly coerces `state: on` into the
boolean `True`, or accepts a nested structure that half the writers cannot
round-trip, produces corruption that surfaces days later as strange agent
behaviour rather than immediately at the edit.

So: ISO dates stay strings, because a date that round-trips through a `date`
object comes back with a different textual form and shows up as a spurious
diff on every write, which makes the audit trail useless. Ambiguous scalars
are quoted on write so that `dumps` then `loads` is a genuine round trip.
Duplicate keys raise. Nested maps raise, with the line number and the line.

## Consequences

Good: the state layer has no dependencies, no migrations, and no server. A
reviewer can read the entire contents of the system with `cat`.

Bad: no transactions. A crash midway through a multi-document update leaves
the vault half-updated. This is mitigated by writing the file before the audit
entry, so the log under-reports rather than claiming a write that did not
land, and by the fact that git makes the inconsistency visible. It is not
solved.

Bad: queries are a linear scan. `Vault.query` walks every document. Fine at
this scale, and the first thing that will hurt.

Bad: a malformed document is skipped during a sweep rather than raising. This
keeps one bad note from halting a nightly run, and it means a note can silently
stop participating. The tradeoff was made toward availability and it is the
kind of thing that should have a metric on it.
