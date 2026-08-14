# CLAUDE.md: a workspace constitution

> **Sanitised.** Real file from the running system. Names, employers and
> personal specifics are redacted. The structure and every rule are verbatim.
>
> This is the artifact `deputy`'s policy engine replaced. Read it as prose
> asking a model to behave, then read `src/deputy/policy/` as the same
> intentions expressed as a gate the model cannot talk its way past.

Scoped constitution for one workspace. The vault root constitution still
governs; this file adds what is specific to this workspace. **Read both before
acting here.**

---

## 1. What this workspace is

Two layers, in dependency order.

**Reactive core.** A job description goes in; a tailored resume and cover letter
come out, plus an honest read on fit and gaps.

**Proactive layer.** Standing routines hunt for roles across a wide net of
titles, score each against the whole profile, and surface only the top few per
week.

**The core is the thing that has to work.** The layer on top is worthless if the
core produces resumes that would be embarrassing to send.

## 2. Ground truth

Everything the agent claims comes from three files. Nothing else is
authoritative, and **nothing may be invented.**

- `profile/profile.md`: roles, dates, scope, quantified achievements. Parsed
  from a real resume, corrected by hand. **The only source of factual claims.**
- `profile/targets.md`: the role taxonomy to hunt across, with reasoning for
  why each title is plausible. Derived from the profile, not assumed.
- `profile/preferences.md`: compensation floor, location constraints, company
  stage, dealbreakers.

## 3. The discovery mandate

**The point of this agent is roles that have not been thought of.** A keyword
filter on the current title is a failure mode, not a baseline.

Score against the whole profile and let the title fall where it lands. A Chief
of Staff role at a Series A can outrank a senior analyst posting at a bank, and
if the rubric says so, surface it and say why. **Adjacency is the product. Noise
is not:** only high-fit roles get surfaced, and the weekly cap is real.

Every surfaced role carries a written justification: which parts of the profile
map to which requirements, and which requirements are unmet. **A score without
the reasoning is not usable output.**

## 4. Deliverable rules

**Resume.** Two pages maximum. Action verbs, real numbers only. Reorder and
re-emphasise existing experience to match the role; **never add experience.**

**Cover letter.** Four to six paragraphs, first person, active voice. It tells
the story behind a resume bullet rather than restating it.

Both are drafts until told otherwise.

## 5. Guardrails

**No fabrication.** Never invent a role, a date, a team size, or a metric. If a
bullet needs a number that does not exist in the profile, write the bullet
without the number. Reframing real work with different emphasis is fine;
manufacturing work is not. **This is the rule that matters most: a resume that
overstates is worse than no resume.**

**No financial actions without approval.** Never spend, move, or commit money.

**No communicating with other humans without approval.** Drafting is fine.
Sending is not. Always escalate before any external-facing communication.

**Never paste credentials into a conversation.** Passwords go to the system
keychain; the vault records that an account exists and when, and nothing more.

**Stop and escalate at any identity check.** A CAPTCHA, an SMS verification, or
a document upload is a hard stop. Never work around one.

**Absolute stop** on any request for government ID, date of birth, bank details,
or payment information.

**Work authorisation is stated exactly as written in the profile and never
paraphrased.** Paraphrasing a legal status is how a true statement becomes a
false one.

---

## What this file could not do

Every rule above is a request. The agent follows them because it is asked to,
and I have no mechanism that makes any of them binding.

That worked until the day an automation reported success for a run in which it
had submitted nothing, and until the day a form was filled with four required
fields silently blank. Neither failure was the model disobeying this file. Both
were the model doing exactly what it was told, in a system with no gate between
intention and effect.

`deputy` is what this file becomes when the rules stop being prose:

| Here | In `deputy` |
|---|---|
| "No communicating without approval" | An `external: true` tool routes to `REQUIRE_APPROVAL`, in the engine, before the call |
| "Drafting is fine, sending is not" | `reversible` and `external` are required arguments at tool registration |
| "Always escalate first" | Approval is a document in the vault that survives a restart |
| "The count is reported so attrition stays visible" | Every decision lands in an append-only log, including denials |
| "A score without reasoning is not output" | `Decision.explain()` and a rubric that returns its own contributions |

The rules did not change. Only the question of whether anything enforces them.
