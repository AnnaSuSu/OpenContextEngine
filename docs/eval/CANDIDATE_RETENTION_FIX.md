# Candidate retention and complete short-function evidence

2026-10-04, engine `batched-dag-v6`. Changes address issues already exposed in the [expanded-v1 omission diagnosis](EXPANDED_DIAGNOSIS.md), then run 60 regression queries on the same 30 bilingual tasks. This is development regression, not a new held-out result. ACE was not queried again, and original reference answers and scoring code are unchanged.

## Results

At 4,000 tokens, using the original frozen `answers.v1.json` scoring:

| Metric | Before: v4 | After: v6 |
| --- | ---: | ---: |
| Overall required evidence coverage | 90.14% | 94.03% |
| Complete-evidence queries | 48/60 | 51/60 |
| Click coverage (language mean) | 98.75% | 98.75% |
| HTTPX coverage (language mean) | 85.00% | 85.00% |
| Zod coverage (language mean) | 86.67% | 98.33% |
| Median query time | 3.76 s | 4.51 s |
| Query P95 | 5.94 s | 6.98 s |
| Successful queries | 60/60 | 60/60 |

Per-query comparison shows 3 improvements, 57 unchanged, and 0 regressions: Zod `safe-parsing` rises from 0% to 100% in both languages, and Chinese `tagged-union` from 66.67% to 100%. One evidence unit in English `async-refinement` remains incomplete.

HTTPX's two blank-line scoring issues retain the original rules to avoid mixing a scoring change with algorithm gains. Uniformly ignoring missing blank lines in both groups produces diagnostic coverage of **91.81% → 95.69%** and complete retrieval of **50/60 → 53/60**. Both scoring variants are recorded without overwriting original results.

## Implementation

Changes are in `src/retrieval/batched.py`, retaining the shared Python/TypeScript structural interface and unchanged index and model configuration.

1. **Candidate slots add new units.** Retain the top 64 core candidates plus 16 distinct structural candidates. Fill remaining capacity from the original ranking, with at most 80 total. This fixes the case where all 16 additions overlap the top 64 and only 64 survive.
2. **Unscored structural candidates inherit evidence from their source.** Follow calls, same-symbol units, and function-containment relationships from core candidates, ranking additions by existing relevance, relationship confidence, and new-neighbor count. New units need not already have a first-wave score. Type references, imports, and class-level membership do not use this added priority route.
3. **Keep complete short-function context within bounds.** Group a short function's body and nested getters using source structure, optionally following callers for at most two levels. Each function group costs at most 256 tokens; common functions with more than 4 callers are not expanded; the full group is capped at 768 tokens. Final selection charges actual incremental token cost, deduplicates, and remains within 4,000 tokens. Larger functions retain the existing unit granularity.

The third change recovers the error getter alongside `handleResult` and the short parsing entry points. Additional units come from verified source and static relationships, without language, repository, or task-name special cases. Some are not reranked independently; diagnostics explicitly mark `contextOnly` and `selectionAnchor`, so they cannot count as independent model judgments.

Limits remain at most 80 second-wave units, one embedding request, and at most two reranking waves, without cross-query caching. Filling the slots increases actual scored pairs and latency by about 0.75 seconds (roughly 20% at the median). Both runs use the same Mac and remote models, with only one 60-query run each; no statistical-significance or concurrent-throughput claim is made.

## Validation and version records

- All 16 Python tests passed, covering duplicate slots, callers/nested units without first-wave scores, type-reference filtering, candidate filling, two-level context limits, common-function exclusion, and existing language/retrieval behavior.
- All 23 Node tests passed.
- Full regression checks original-output hashes, local and remote engine hashes, matching index identities, unchanged frozen inputs/answers, real source lines, no duplicate output units, the 4,000-token cap, the 80-unit reranking cap, and request-wave counts.
- With candidate retention alone in v5, targeted Zod scores were 33.33% in Chinese and 0% in English, insufficient for complete evidence. Records remain in `runs/reponerve-v5-probe-*` and are not final results. After adding bounded short-function context, both targeted and full v6 regressions restore the target task to 100% in both languages. No tuning followed the full regression results.
- A v6 startup health probe encountered one connection reset. It was retried after service readiness, before any query or result-directory creation. All 60 full-regression queries succeeded.
- Validation used a separate remote worker, retaining the original v4 evaluation service and records. Model deployment, language adapters, reference answers, scorer, and Git-history functionality are unchanged.

## Archives

- [Machine-readable regression and per-query changes](results/candidate-fix-20261004.json)
- Frozen engine: `eval/regression-v6/engine-freeze.json`; previous probe configuration: `eval/regression-v5/engine-freeze.json`.
- Runner: `scripts/expanded/regress.mjs`; service startup: `scripts/expanded/serve-fixed.mjs`; offline comparison and integrity checks: `scripts/expanded/compare-fix.py`.
- Full run directories:
  - `runs/reponerve-v6-regression-click-2026-10-03T16-12-34.807Z`
  - `runs/reponerve-v6-regression-httpx-2026-10-03T16-14-23.565Z`
  - `runs/reponerve-v6-regression-zod-2026-10-03T16-16-00.747Z`

Running `node scripts/expanded/regress.mjs click` (or `httpx`, `zod`) requires the corresponding authorized remote worker and SSH forward. Original v4 comparisons should keep using archived results without mixing in this development regression.
