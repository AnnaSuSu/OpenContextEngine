# Evidence-oriented retrieval

The live worker uses `EvidenceEngine` (`evidence-v1`). Historical engines remain
available for reproducing evaluations pinned to their recorded revisions.
Published benchmark results have not been relabeled as results for this engine.

## Selection behavior

- Keep the top 40 positive dense and lexical candidates per question independently,
  instead of discarding single-channel discoveries through an early fused cutoff.
- Score the full request and its behavior facets. Each facet includes the original
  request, so conditions and pronouns retain context. At most five queries are used.
- Expand bounded static calls, source-value references, and same-symbol links;
  score discovered evidence and affordable function continuations before selection.
- Prefer the requested source role. Ordinary behavior queries start with
  implementation evidence; explicit test, documentation, and interface queries
  retain their respective intent. These are heuristics, not semantic guarantees.
- Combine relevance with within-role rank to separate saturated scores. A short
  snippet does not earn an inverse-token-cost bonus. Repeated parts of the same
  symbol receive diminishing priority.
- Reserve space for direct dependencies, function continuations, and requested
  regression tests. Short helpers explicitly referenced by an implementation can
  accompany it. The caller's token budget remains a hard limit.
- Merge contiguous returned source spans without inventing intervening lines.
  A large function may still be partial when it cannot fit the budget.

Python links resolve lexical imports inside functions and unambiguous module
suffixes across source roots. Parameters, local assignments, conditional imports,
and ambiguous modules are treated conservatively. A function used through a
wrapper attribute is a value reference, not a proven call. Dynamic dispatch and
runtime rebinding are not fully modeled. Adapter identities include the resolver;
source text and embedding inputs remain unchanged by relation-only upgrades.

## Validation and diagnostics

`debug` reports candidate counts, scoring waves, model request counts, selected
units and bundles, and selection phases. Model pairs are reused within one search;
there is no cross-search answer cache in the live worker. Real latency therefore
includes model calls and source-freshness verification.

For a quality comparison, freeze the source revision, queries, required evidence
spans, models, and output budget before running. Save raw contexts and exact source
line checks alongside stage diagnostics. Measure complete required evidence as
well as whether any relevant result was returned. Score selectors must never enter
the retrieval request. Keep diagnostic development cases separate from new
regression cases, and report remaining omissions rather than treating a narrow
local set as a general benchmark.

Offline experiment response caching is useful for comparing selection rules with
identical model responses. Mark such timings as cached; measure live latency
separately. Reuse existing third-party comparison outputs unless a changed source,
query, or protocol requires a new paid request.
