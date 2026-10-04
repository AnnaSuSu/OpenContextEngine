# Script guide

## Product entry points

- `mcp-opencontextengine.mjs`: stdio MCP server, including automatic workspace selection.
- `serve-opencontextengine.mjs`: managed HTTP retrieval worker.
- `search-opencontextengine.mjs`: command-line retrieval client.
- `retrieval-server.py`: Python retrieval worker started by the service launcher.
- `smoke-mcp.mjs`: opt-in end-to-end checks against configured model services.

The corresponding `*-reponerve.mjs` entry points preserve existing integrations.

## Public evaluation tools

These scripts support the reports linked from [Benchmarks](../docs/BENCHMARKS.md). They are research runners with documented environment requirements, not part of normal MCP startup.

| Location | Purpose |
| --- | --- |
| `benchmarks/` | Seven-method execution, scoring, audits, charts, and the optional benchmark reranker |
| `expanded/` | Frozen Click, HTTPX, and Zod comparisons and regressions |
| `roadmap/` | JavaScript and Go structural/retrieval checks |
| `text-fallback/` | Unsupported-language and configuration-file checks |
| `diagnostics/` | Stage-level evidence for published retrieval diagnostics |
| `prepare-django.mjs`, `ace-django.mjs`, `score-django.mjs` | Frozen Django dataset and ACE comparison |
| `run-baseline.mjs`, `run-opencontextengine.mjs`, `compare-django.mjs` | Earlier published retrieval comparisons |
| `benchmark-service.mjs`, `summarize-speed.py` | Client/service latency measurements and summaries |

Other helpers in this directory prepare source snapshots, normalize native results, build retrieval plans, or bridge model APIs for those runners. Frozen data lives in `eval/`; reports and published JSON live in `docs/eval/`. Local runs, provider experiments, personal deployment notes, and retired experiments are not public benchmark dependencies.
