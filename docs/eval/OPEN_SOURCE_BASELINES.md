# Open-source first-search comparison records (historical)

**This page retains the early exploration from October 3. A new seven-method, four-repository comparison completed on October 4, including ContextWeaver's two previously omitted large files. See the [seven-method report](METHOD_COMPARISON.md) for current results and charts.**

Integration began on 2026-10-03 using remote-model services. ACE, CocoIndex, and ContextWeaver each completed 20 queries as preliminary references for prototype development.

**At that stage, this was development exploration: no rerun for the two large-file indexing differences and no expansion of the baseline count. The OpenContextEngine prototype completed the same-task comparison with models running only on remote servers.**

First-search coverage with reference answers v2 at 4,000 tokens:

| Method | Chinese | English |
| --- | --- | --- |
| ACE / DirectContext | 86.5% | 84.0% |
| CocoIndex Code | 24.0% | 33.5% |
| ContextWeaver + Qwen3 reranking | 26.0% | 17.7% |
| OpenContextEngine AST prototype + Qwen3 reranking | 86.33% | 84.67% |

OpenContextEngine uses original questions and generic clause splitting throughout, without generative planning. Complete-task retrieval is 5/10 in both languages, matching ACE. Median query time is 15.23 seconds versus ACE's 2.82 seconds. Different deployments and pipelines prevent an isolated algorithm-speed comparison. See the [prototype record](OPENCONTEXTENGINE_PROTOTYPE.md) for structure, per-task results, and limitations. The subsequent default uses two batch-scoring waves and a persistent service, preserving same-task coverage with actual Mac-client median 3.27 seconds and P95 4.79 seconds; see the [speed refactor](OPENCONTEXTENGINE_SPEED.md). The table retains the first comparison.

ContextWeaver's default 100 KiB file limit skipped two large ORM files (881 / 883). This run remains a rough reference; the subsequent seven-method comparison includes those files. Responses typically contain only 266–1,373 tokens, with conservative file and snippet selection that does not fill the 4,000-token budget. These are one-run results on 10 development tasks and 20 bilingual queries, not a research-paper conclusion. See the [results](results/django-comparison-20261003.json) for machine-readable comparison and omission categories.

## Fixed comparison procedure

Use the [Django protocol](DJANGO_PROTOCOL_V1.md): 883 production Python files, 10 bilingual paired tasks, reference answers v2, and 2,000 / 4,000 / 8,000-token budgets. Tools receive only source and queries; references are used for offline scoring. Preserve each tool's own splitting, indexing, and retrieval implementation. Save native JSON before formatting text with paths and line numbers, without adding source beyond returned snippets or reranking.

ACE retains its original service text. Structured open-source results use a consistent compact text format, creating serialization-overhead differences that must be reported rather than attributed wholly to retrieval algorithms. All paths and line numbers count against the final token budget.

## Initial integration priorities

| Group | Pinned revision | Configuration | Status |
| --- | --- | --- | --- |
| CocoIndex Code | `8ec0ff3510be526e699028db5b64e10a0a8359b3` | Native recursive splitting and SQLite vector retrieval; at most 60 units per query, then uniform token-prefix truncation | Completed: 736 nonempty files, 8,002 units; indexing 245.7 seconds; all 20 queries passed |
| ContextWeaver | `42375d315e180da258ebb983215004dbbf98c00d` | Native retrieval defaults; Qwen3-Embedding-4B; remote Qwen3-Reranker-4B | Completed 20 queries; default file-size limit indexed 881 files |

Of CocoIndex's 883 input files, 147 are empty or whitespace-only and skipped by its native indexer, leaving 736 nonempty files. All input files were supplied; 736 is the post-indexing nonempty count. Default splitting uses 1,000 characters, minimum 250, and overlap 150; total unit text is 5,949,219 characters.

ContextWeaver's default retrieval requires a reranking service. This comparison uses remote APIs, with no model loading on the client.

Remote Qwen3-Reranker-4B replaces the upstream default BGE reranker; comparisons must retain this configuration distinction. See the [reranker API](../RERANKER_API.md) for the interface and generic implementation. Service connectivity checks are not ContextWeaver retrieval-quality results.

The shared embedding service is the existing Qwen3-Embedding-4B deployment, returning 1,024 dimensions with a 1,024-token input limit. ContextWeaver sets `EMBEDDINGS_MAX_CONTEXT_TOKENS=1024`, using upstream long-text splitting and vector merging. The service does not support the default 8,192-token window. Remote model-weight hashes were unavailable; caches are isolated by endpoint, model, dimensions, and deployment date.

## Integration and limits

`scripts/run-baseline.mjs` copies frozen source and verifies its revision, starts a bounded embedding-forwarding gateway, runs native tools, and stores original results and hashes. Gateway batches contain at most 8 inputs, accessing the same remote embedding service over HTTPS or explicitly configured SSH forwarding. Attempts are capped at 30 seconds, with at most 3 attempts for timeouts, connection failures, and specified transient HTTP errors; every attempt counts against limits. Authentication, parameter, and response-format errors are not retried, and inputs or models are not changed.

Each run permits at most 6,000 remote requests and 60 million input characters. ContextWeaver's splitting for the service input window exceeded the initial 2,000-request limit, so the shared runner cap increased before its query results were obtained. Completed CocoIndex used only 1,022 requests and never reached the old cap. Models, source, tool parameters, and scoring budgets are unchanged. Based on actual remote throughput, the indexing-and-first-query limit increased from 20 to 90 minutes; later queries remain capped at 2 minutes, and the full run at 100 minutes. Retrieval-quality questions, answers, and token budgets are unchanged. Save runner copies and hashes before execution; querying begins only after error-free indexing that includes all nonempty input files.

The embedding gateway only caches and forwards remote requests; it runs no models and retains the actual embedding key. Reranking requires an explicitly configured remote HTTPS address and rejects local, loopback, and local-domain addresses. Missing configuration stops execution without local-model fallback. ContextWeaver runs in a dedicated Node process with `os.homedir()` redirected to this project's isolated state directory, without changing global HOME or upstream retrieval source.

```sh
# Run only after installing remote-client dependencies and configuring remote models:
npm run baseline -- cocoindex
npm run baseline -- contextweaver
npm run score-django -- RUN_DIRECTORY answers.v2.json
```

The previous local environment was removed; current execution uses a dedicated cloud-server environment. The project does not automatically download or install local models.

`BASELINE_RESEARCH_ROOT` selects the pinned upstream checkout directory, and `BASELINE_EXECUTION_LOCATION` is recorded in reports. This remains a development-pilot runner rather than a portable installer. Remote embedding authentication, 1,024-dimensional vectors, and semantic ordering were verified. Sustained batch indexing encountered timeouts; both end-to-end retrieval groups subsequently completed.

## Cloud execution

The runner is on the authorized cloud server at `/root/reponerve-baselines/worker`, with unchanged upstream revisions and Node pinned to 22.14.0. Only frozen public Django source, queries, and runners are uploaded; reference answers remain local for offline scoring. The cloud host verified the manifest and SHA256 of all 883 files. Open-source execution and the ACE client run in different locations, so timing differences cannot be attributed entirely to retrieval algorithms.

ContextWeaver's optional ONNX component download failed with HTTP 302. Installation and compilation succeeded with its official `ONNXRUNTIME_NODE_INSTALL=skip` option. This run explicitly uses `EMBEDDINGS_PROVIDER=remote`, without local embedding models.

Public forwarding latency affected batch indexing, so the evaluation server switched to a direct SSH tunnel to the embedding server. In a preliminary comparison of the same 8 inputs, SSH took 306–393 ms versus public HTTPS at 3331–4106 ms. Subsequent inter-server SSH completed 10 consecutive batches of 8 inputs at 165–243 ms each. These are connectivity diagnostics, not formal performance scores. Evaluation restarted from a clean index after the transport fix; the table contains only corrected runs.

The caller establishes the SSH tunnel, binding only `127.0.0.1` and targeting the model server. SSH identities below use example values. Set `EMBEDDING_SSH_TUNNEL_URL=http://127.0.0.1:42002/v1` and `EMBEDDING_SSH_REMOTE=operator@model-host.example:22`. Logical `EMBEDDING_BASE_URL` retains the original service address; reports record transport and remote identity. This setup installs or loads no local models.

## Subsequent decisions

The three reference groups informed OpenContextEngine's first prototype comparison. At this stage, grepai, Claude Context, and OCE runs were deferred; Serena and codebase-memory-mcp remained references for later symbol/relationship capabilities.

The prototype implements complete function/class representations, compound-task splitting, semantic and lexical retrieval, symbol-relationship completion, and complementary evidence selection within budget. Do not encode these development tasks' answers, paths, or symbols into retrieval rules. Evaluate first on the existing development tasks without presenting them as unseen test-set results.
