# ADR 0005: No agent framework, and no dependencies in the core

**Status:** accepted

## Context

There are good agent frameworks. Using one would have supplied the loop, tool
schemas, provider adapters, and streaming, and saved real time.

## Decision

The core package has zero dependencies. The agent loop is about 130 lines.
Provider SDKs are kept out entirely, behind a four-line protocol and a
`CallableModel` adapter that translates a provider's exceptions into the two
typed errors the runtime understands.

## Why

The thing this repo is arguing about is authority, provenance, and
measurement. All three sit at the boundary between the loop and the outside
world, which is the exact layer a framework owns. Building on one would mean
either fighting its abstractions or accepting its answers, and its answers are
the subject.

Two secondary reasons that turned out to matter more than expected.

**Reviewability.** The whole system can be read in an afternoon. For a repo
whose purpose is to show how something was reasoned about, a reader who has to
first learn a framework's model of the world has been charged a tax before
reaching the argument.

**Testability.** Because there is no provider SDK in the way, `ScriptedModel`
and `RecordedModel` are trivial, and the suite runs offline in under a second
with no keys and no network. That property came from the dependency decision
rather than from anything clever, and it is the single reason the tests are
worth having.

## What is given up

Streaming. Parallel tool calls. Provider-native tool-calling APIs, so tool
selection goes through JSON in the completion text and needs the tolerant
extractor in `model.py` to survive fences and preamble. Retries and rate
limiting that a mature SDK would provide. Token counting is a
four-characters-per-token estimate, used only where a provider does not report
real usage.

Each of those is a real cost and none of them changes the argument.

## When this would be the wrong call

If this were a product rather than an argument. Provider-native tool calling is
meaningfully more reliable than parsing JSON out of prose, and reimplementing
it is not a good use of anyone's time. The right structure then is to keep
`policy`, `store`, and `evals` exactly as they are, since none of them know
what a model is, and replace `runtime` with the framework's loop. The seams
are already in the right place for that: `runtime` is the only package that
imports a model, and `policy` and `store` have no knowledge of it at all.
