# Faster retrieval with shared whole-query scores

2026-10-04. The persistent retrieval entry point defaults to `shared-intent-v4`. Whole-query candidate scores are reused within each search, while subquestions use existing vectors to calculate relative relevance. Score-based relationship expansion, candidate protection, and short-function context are retained. If the highest whole-query score is below 0.1, the second wave uses actual subquestion scoring to handle poor whole-query model scores. The output-selection threshold changes from 0.015 to 0.005, using remaining budget to retain low-scoring dependencies.

Each search still uses one embedding request, at most two reranking waves, at most 80 final reranking candidates, and 4,000 tokens, without cross-query caching. `BatchedEngine` remains the comparison implementation with full subquestion scoring. Service health reports the actual engine version.

## Comparison on the same source

Original indexes, questions, and reference answers are fixed, with remote Qwen3-Embedding-4B / Qwen3-Reranker-4B unchanged. The original and second variants run alternately; two observed regressions are then fixed before final validation on 76 queries. Latencies below are internal to the remote process. Original results come from the preceding comparison run, and final results from a separate post-fix run, both without concurrent indexing load.

| Repository | Queries | Original median | Final median | Original coverage | Final coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| esbuild | 16 | 6.368 s | 2.546 s | 81.25% | 81.25% |
| Click | 20 | 4.952 s | 2.001 s | 98.75% | 100% |
| HTTPX | 20 | 4.391 s | 1.801 s | 85% | 85% |
| Zod | 20 | 3.766 s | 1.551 s | 98.33% | 98.33% |

Per-query comparison shows 75 unchanged, 1 improved, and 0 regressed. All outputs pass original-source, line-number, response-hash, and budget checks. Tasks are used for development validation and do not establish independent-sample performance. ACE was not rerun.

The first approach, using only local subquestion scores, missed one esbuild task and was rejected. The second variant stopped selection too early on HTTPX and produced low whole-query scores on Zod. These were fixed with the budget-selection threshold and low-confidence scoring fallback respectively. Records remain locally in `runs/roadmap-routing-v1` through `v4`; final per-query data and source fingerprints are in the [machine-readable report](results/shared-intent-20261004.json).

`scripts/roadmap/compare.py` reads only questions and frozen indexes; `score.mjs` loads reference answers locally for scoring; `run.mjs` runs only on the configured remote evaluation host. Index builds and model startup are excluded from latency. This change updates the default code entry point; existing service processes must restart with the new code to use it.
