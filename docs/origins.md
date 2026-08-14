# Where this came from

`deputy` is not a greenfield demo. It is the extractable third of a system that
has been running unattended on my own machine, on schedules, for months.

I could not open that system. It reads a personal inbox and a calendar, so
publishing it would expose other people's messages as well as mine. So I
rebuilt the part that has something to say, from scratch, with no private data
in it. This document is what the original is, so that the design decisions in
this repo read as things that were paid for rather than things that were
imagined.

---

## What the original is

A personal operating system: a git-backed vault of markdown files, a set of
autonomous routines on independent schedules, and a chat thread on my phone as
the only interface. No dashboard, no web app, no login.

Nine routines currently run. A morning brief. Inbox triage. A queue where I
drop a task from my phone and find the output done later. Weekly synthesis that
catches loops I have let go quiet. A job-search agent, described below. Each
has its own cadence, its own authority, and its own constitution file.

### The constraint that shaped everything

The scheduler available to me could not fire more often than hourly.

A reminder system that cannot fire at 3:15 is not a reminder system. That one
limitation forced the whole architecture: the system is split across two
execution environments, and every capability had to be assigned to one side or
the other.

```
phone  ──►  message bridge  ──►  agent runtime
              (edge worker)        (scheduled)
                   │                     │
                   │  5-min tick         │  hourly+ cadence
                   ▼                     ▼
              time-critical         everything durable
               reminders                  │
                                          ▼
                                    markdown vault
                                   (git, versioned)
```

Sub-hour work lives at the edge. Everything durable lives in plain text under
version control. Deciding which side each capability belonged on was most of
the design work, and it is the reason ADR 0002 in this repo is about a state
layer rather than about a feature.

### Authority is a file, and it was a file there first

Each workspace in the vault carries a `CLAUDE.md`: a scoped constitution that
says what the agent operating in that directory may and may not do. The vault
root has its own, and the scoped one adds to it rather than replacing it.

The hard rules are short and they are absolute:

- No financial actions without approval. Never spend, move, or commit money.
- No communicating with other humans without approval. Drafting is fine.
  Sending is not.
- No fabrication. Never invent a role, a date, a team size, or a metric.

`deputy`'s policy engine is that idea with the reasoning made mechanical. The
constitution is prose a model is asked to follow; the policy engine is a gate
the model cannot talk its way past. Moving from one to the other is the single
biggest thing I learned building the original, and it is why this repo argues
that the model proposes and the policy engine disposes.

### The job-search agent

The most complete routine, and the one that produced most of the operational
scars. It is exactly what it sounds like: I am looking for a job, and I built
an agent to do the parts of that which are mechanical.

It sweeps public applicant-tracking APIs, scores every posting against a
written profile on a six-dimension rubric, drafts a tailored resume and cover
letter for anything that clears the bar, and stops at a human gate before
anything is sent.

Its first production run swept 23 endpoints and roughly 5,000 postings, gated
them down to 82, and surfaced 6 worth a decision, each with a written
justification for its score including what it thought I would fail on.

The rubric and a real scored role are in [`artifacts/`](artifacts/), with
identifying detail removed. They are the best evidence I have that the scoring
design in this repo is not theoretical.

---

## What it taught, in the order the lessons hurt

### The pipeline whose last stage could never run

Documented in full as [postmortem 0001](postmortems/0001-the-pipeline-that-could-never-run.md).
That is not a hypothetical written for this repo. It happened, it reported
success nightly for days while submitting nothing, and I diagnosed it wrongly
twice before finding it.

The final stage needed a live browser session. The scheduled environment had no
browser and could never have one. The stage did not error, because from its own
point of view it had nothing to do, and nothing to do is not a failure.

I had designed the pipeline end to end and mapped it onto the execution
environment afterwards. That ordering buries an assumption about the
environment inside a design that already exists, where nobody thinks to
question it, and it fails in the one direction that looks like success.

### A packaged application for a role that did not exist

Discovery scored a role at 80, generated a tailored resume and cover letter for
it, and queued it. The role was not on the company's board. Every actual
opening at that company was in cities I had filtered out.

The posting had come from an aggregator and was stale. Discovery never
re-verified that a posting was still live before packaging it, so the pipeline
spent real model budget producing a deliverable for something that was not
there. Nothing in the system was wrong except an assumption nobody had written
down.

### Form automation that silently dropped data

Filling an application form through browser automation, four required dropdowns
reported as set and displayed "Select..." afterwards. Setting a value in the
DOM is not the same as a framework registering it. An unattended run would have
submitted a form with blank work-authorisation answers while recording success.

This is the same class as the two above and it is the reason `deputy` treats
"the action was taken" and "the action was recorded as taken" as separate
things that have to be reconciled, rather than assuming one implies the other.

### An outage I invented

I once reported that the whole fleet had been dark for 45 hours. It had not.
`git fetch` from one particular execution context fails silently against an SSH
remote, so the branch I was reading had been frozen while the system ran
normally the entire time. My own briefings, which I was receiving on my phone,
disproved it.

I include this one because it is the least flattering and the most useful. The
monitoring was reading a stale ref and reporting confidently on it, which is
exactly the failure the audit log in this repo is shaped to prevent: a record
is only evidence if you know when it was last written.

---

## How the original maps onto this repo

| In the original | In `deputy` |
|---|---|
| `CLAUDE.md` constitutions, prose a model is asked to follow | `policy/`: a gate the model cannot talk past |
| Markdown vault in git, hand-editable | `store/vault.py`, same tradeoff, [ADR 0002](adr/0002-plaintext-state.md) |
| Append-only ops log, union merge driver | `store/audit.py`, [ADR 0003](adr/0003-append-only-audit.md) |
| Approval prompts over chat, answered on a phone | `policy/approvals.py`: durable, expiring, single-use |
| Six-dimension fit rubric, never calibrated | `evals/`: where the calibration finally happens |
| Nine routines, hourly floor, two execution tiers | Deliberately absent. See below. |

### What is deliberately not here

The scheduling layer, the message bridge, the multi-agent fleet. All real, all
working, and none of them argue anything this repo is about. Including them
would have added surface area and infrastructure without testing the position.

The one that stings to leave out is calibration on real data. The original has
a rubric that has scored a few dozen roles and has never been checked against
outcomes, because the outcomes take months to arrive and there are not enough
of them yet. That is precisely the gap `evals/` exists to close, and closing it
properly is the next thing I would build, not something I can claim.

---

## What is honest to claim from this

Plainly, because the distinction matters and I would rather draw it myself.

**This is production in every meaningful sense.** It runs unattended, on
schedules, without me. It has uptime, it has failure modes I have debugged at
2am, and it has a change history going back months. The failures above are real
incidents with real consequences, not exercises.

**It is not professional engineering experience.** No team, no code review, no
on-call rotation, no users other than me, and no consequence to anyone else
when it breaks. A system with one user is missing most of what makes production
hard.

Both of those are true at once. When this comes up in an interview I say the
first and I do not imply the second, and the same rule is written into the
agent's own constitution: claim the former, never imply the latter.
