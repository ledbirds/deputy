# ADR 0003: The audit log is append-only and merges by union

**Status:** accepted

## Context

Several agents run on schedules and commit to the same repository. Two
finishing inside the same minute is normal, not exceptional. The log of what
they did is the only evidence of what happened while nobody was watching, so
losing half of it to a merge resolution is not an acceptable failure.

## Decision

The log is JSONL, one self-contained record per line, registered in
`.gitattributes` as `*.jsonl merge=union`. A merge concatenates both sides
instead of raising a conflict.

Union merge has a real cost, and it is handled rather than wished away.

**It can duplicate lines.** The same entry arriving down two branches appears
twice. Every entry therefore carries a content-derived id, and the reader
de-duplicates on it, so a duplicated line is idempotent rather than a double
count. This matters directly: rate limits are computed by counting entries,
and a double-counted action would tighten a cap that should not have moved.

**The id excludes the sequence number.** The same logical event replayed on
two branches gets numbered differently on each, and including `seq` in the
identity would make the two look like distinct events, which is exactly the
double count the id exists to prevent.

**Ordering is per-writer, not global.** Entries carry a timestamp and a
sequence and the reader sorts, but two writers on separate branches share no
clock. The log does not pretend otherwise. Anything that needs a total order
across writers needs something this design does not provide.

## Durability

Appends flush and `fsync`. A crash between an agent taking an action and the
log recording it produces a log that reports less than what happened while
looking complete, which is worse than no log, because it will be trusted.

Writes to the vault happen before the corresponding audit entry, for the same
reason: if the process dies between the two, the log under-reports rather than
claiming a write that did not land. The git diff is the backstop.

## Damage tolerance

A corrupt line, from an interrupted write or a hand-edit that left conflict
markers, is skipped and counted rather than fatal. `read_with_damage` returns
the count so a caller can alarm on it. A single bad line should not make the
entire history unreadable.

Unknown fields from a newer writer are carried into `detail` rather than
dropped, so a record survives a round trip through an older reader.

## Alternatives considered

**A real merge driver.** Correct and more work, and it only pays once entries
need to be reconciled rather than concatenated. Not there.

**One log file per agent.** Removes the conflict entirely and replaces it with
the problem of reading eight files in timestamp order to answer one question,
plus the same lack of a shared clock. Rejected as a lateral move.

**A database for the log specifically.** Would give ordering and uniqueness for
free. Rejected because it reintroduces a server for the one part of the system
whose entire value is being readable and repairable with the tools already on
the machine.

## Consequences

Good: concurrent agents cannot silently drop each other's history, and the log
is greppable.

Bad: the file only grows. There is no compaction, and nothing here addresses
what happens at a million entries. Reading the log is O(n) and rate-limit
checks read it on every decision, which is the first thing that will need
fixing.
