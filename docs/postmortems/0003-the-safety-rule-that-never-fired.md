# Postmortem 0003: A catch-all safety rule that matched nothing

**Severity:** high. Irreversible actions were being allowed through.
**Found by:** running the worked example and reading the output

## What happened

The triage policy contained this rule, intended as the backstop that gates
anything an agent cannot undo:

```markdown
## anything-irreversible-needs-a-human

match: "*"
when_reversible: false
verdict: require_approval
```

The policy body parser split each line on the first colon and stored the
remainder verbatim. So `match` was stored as the five-character string `"*"`,
with the quote characters, and `fnmatch("post_comment", '"*"')` is false.

The rule matched nothing. Every action fell past it to the ruleset default. In
the worked example the default was `deny`, so `post_comment` came out DENIED
rather than HELD, and the run looked stricter than intended rather than looser.

That is luck. With a default of `allow`, which is what a permissive
development configuration would have, the same bug means every irreversible
action executes with no gate at all, and the policy file still reads as though
it is protected.

## How it was found

Not by a test. By running the example and reading the five lines of output
against what the policy said should happen. `post_comment` was denied when it
should have been held for approval, and the stated reason was "no rule granted
this capability", which is the engine saying plainly that the rule was not
seen. The output was already explaining the bug; it just needed reading.

## Fix

`_unquote` strips one layer of surrounding quotes from every value in the
policy body. Quoting has to be supported, because a bare `match: *` is
ambiguous to read and invites a YAML-shaped mistake, so the fix is to accept
the quotes and remove them rather than to forbid them.

The regression test is named `test_quoted_glob_actually_matches` and its
docstring states the symptom, because the failure mode is what someone reading
it later needs to recognise.

## Why this class of bug is the worst one available

A policy engine has one job. When it fails open, nothing announces it. There is
no exception, no error, no missing output. The policy file still contains the
rule, code review still sees the rule, and anyone asking "are irreversible
actions gated" reads the file and correctly answers yes.

The only evidence is behaviour, and behaviour is only evidence if someone is
comparing it against intent.

## What changed beyond the fix

**Decisions carry a trace.** Every `Decision` lists the rules that matched.
When a rule is expected to fire and does not, its absence is visible in the
output rather than requiring inference.

**The CLI can interrogate a policy.** `deputy policy check <file> <action>
--irreversible` answers what would happen for one action, and `deputy policy
explain <file>` prints the parsed ruleset. A parse bug shows up as a rule whose
match string looks wrong, which is exactly what would have caught this in
seconds.

**The worked example runs in CI.** Its output is the artifact that exposed
this. Producing it on every commit means a future version of this bug is caught
the same way, without depending on someone remembering to look.

## What is still missing

Nothing validates that a rule in a policy file can match anything at all. A
rule whose glob is malformed, or whose `when_` predicate names an attribute no
action ever carries, is silently inert. A linter that warns on rules unreachable
against the registered toolbox would have caught this at load time rather than
at run time, and it is not built.
