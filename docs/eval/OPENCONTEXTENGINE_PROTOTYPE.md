# OpenContextEngine first structural-retrieval prototype

This page retains the original historical results. The default subsequently changed to two batch-scoring waves and a persistent service, preserving coverage on the same tasks at 4,000 tokens. Three Mac-client rounds have a median of 3.27 seconds and P95 of 4.79 seconds; see the [speed refactor and usage](OPENCONTEXTENGINE_SPEED.md).

2026-10-03. This development exploration reuses the existing 10 Django tasks and 20 Chinese/English queries without adding baselines. Models are limited to Qwen3-Embedding-4B and Qwen3-Reranker-4B on the user-authorized server; the client loads no models.

## Implemented behavior

The core is `src/retrieval/engine.py`, without Django-specific paths, task IDs, answers, or symbol rules.

1. Extract module, class-body, and function source spans with Python AST, retaining paths, qualified names, and original line numbers. Split long spans preferentially at statement boundaries, with at most 65 lines per unit; exceptionally long statements may be split by line. Class headers and function bodies are represented separately, with links between spans of the same function.
2. Build static candidate relationships from module import aliases, same-module functions, `self`/`cls` method names, and class inheritance. Do not guess dynamic receivers. Edges are retrieval clues, not guaranteed runtime call-graph accuracy.
3. Run 1,024-dimensional vector retrieval and BM25 lexical retrieval per query clause, combining them with reciprocal rank fusion. Model inputs include paths, symbols, and code.
4. Rerank each clause's candidates, expand a few high-scoring seeds' static neighbors, then rerank merged candidates against the whole query and its clauses.
5. Select original spans using overall relevance, marginal clause coverage, and unit token cost, counting paths and line numbers within 4,000 tokens.

Completeness applies to selected spans, not every long function or an entire behavior chain. Embedding text is capped at 2,200 characters, with the service also applying its 1,024-token input cap. Reranking text is capped at 5,000 characters. Splitting and truncation can lose information.

## Query planning for this run

The GPT planning endpoint became unavailable after a few requests. Therefore, **all 20 final queries use their original wording and generic clause splitting**, without mixing in generated plans, translations, or answer hints. `scripts/literal-retrieval-plans.mjs` splits only on punctuation and common conjunctions, producing at most four clauses.

`scripts/plan-retrieval.mjs` is a separate optional experiment using the project's configured remote GPT endpoint to generate plans. It is excluded from these final scores. That generative path is not fully self-hosted and should be distinguished from the prototype's open-weight model path.

## Execution

The runner `scripts/run-opencontextengine.mjs` starts an HTTP-only embedding gateway and Python worker, recording original questions, plans, returned source, candidate/selection diagnostics, and a copy of execution code. The worker reads only frozen source, queries, and plans. Reference answers are attached after retrieval for local offline scoring.

Core Python dependencies are `numpy` and `tiktoken`. The cloud runner reuses the existing client-only environment `.pilot-state/baselines/cocoindex-venv/bin/python`; it is neither a portable installer nor a completed MCP product at this stage.

```sh
node scripts/literal-retrieval-plans.mjs
node scripts/run-opencontextengine.mjs
# Score locally where frozen reference answers are available:
node scripts/score-django.mjs RUN_DIRECTORY answers.v2.json
```

The first index covers 736 nonempty files out of 883 inputs, yielding 12,333 source spans and 40,205 static relationships, including span continuation and parent-class body links. Blank files create no retrieval spans.

## Results

Run directory: `runs/reponerve-django-2026-10-03T12-53-21.093Z`. All 20/20 queries completed. With reference answers v2 at 4,000 tokens:

| Method | Chinese coverage | English coverage | Complete tasks (Chinese / English) | Median query time |
| --- | --- | --- | --- | --- |
| ACE / DirectContext | 86.5% | 84.0% | 5/10, 5/10 | 2.82 s |
| CocoIndex Code | 24.0% | 33.5% | 0/10, 0/10 | 0.15 s |
| ContextWeaver + Qwen3 reranking | 26.0% | 17.67% | 1/10, 0/10 | 2.88 s |
| OpenContextEngine AST prototype + Qwen3 reranking | 86.33% | 84.67% | 5/10, 5/10 | 15.23 s |

OpenContextEngine is 0.17 percentage points below ACE in Chinese and 0.67 above in English. These exploratory results are broadly similar and do not establish a lead. Deployment, serialization, and pipeline differences affect timing. Without statistical tests or ablations, gains cannot be attributed solely to AST or graph expansion.

Prototype indexing took 346.2 seconds. The 20 queries totaled 431.4 seconds, with a median of 15.23 seconds and range of 5.00–72.30 seconds. The full run took 871.6 seconds, including about 94 seconds for engine initialization and other overhead. Embedding used 1,562 requests and 12,396 inputs, with 0 cache hits, 0 failures, and 0 retries, including indexing and queries. GPT-availability probes are excluded from these query timings.

At 2,000 tokens, coverage is 67.33% in Chinese and 73.67% in English. The 8,000-token scores equal the 4,000-token scores because the engine selects at most 4,000 tokens; this is not a fresh retrieval run with an 8,000-token budget.

### Per-task coverage at 4,000 tokens

| Task | ACE Chinese / English | OpenContextEngine Chinese / English |
| --- | --- | --- |
| Login | 80% / 80% | 80% / 80% |
| Routing | 100% / 50% | 75% / 100% |
| Middleware | 75% / 75% | 100% / 50% |
| Transactions | 75% / 100% | 100% / 100% |
| CSRF | 60% / 60% | 100% / 100% |
| Page caching | 100% / 100% | 100% / 100% |
| Settings | 100% / 100% | 66.67% / 100% |
| File uploads | 100% / 100% | 75% / 75% |
| Signals | 75% / 75% | 100% / 75% |
| View permissions | 100% / 100% | 66.67% / 66.67% |

### Remaining bottlenecks

Of 5 incompletely covered Chinese reference units, 4 are partially returned and 1 absent. For English, 5 are partial and 1 absent. Priorities are evidence completeness after span selection and selection stability across language variants, rather than simply increasing candidate count. Budgeted selection still leaves gaps in key methods or adjacent spans.

Latency is the second bottleneck: repeated clause-specific reranking produces quality near ACE with a high call count. Subsequent work should first test generic joint selection of related spans and reranking-call consolidation/pruning, then other projects. Do not encode these tasks, paths, or answer symbols into retrieval rules.

See the [machine-readable comparison](results/django-comparison-20261003.json). Original queries, returned text, per-request diagnostics, execution-source snapshots, and both score versions remain in the run directory above. Downloaded archive SHA256: `cf6eb9d065d6537290c17ae6591a76243b0bac8759355c4b392f952e433b7dea`.

Validation: existing Node tests passed 20/20; added Python structure tests passed 2/2, covering source-span reconstruction, long-function splitting, import/method links, and unresolved dynamic receivers. All 20 actual responses passed source-evidence checks and token scoring. These results guide structural improvements and do not establish generalization to unseen projects.
