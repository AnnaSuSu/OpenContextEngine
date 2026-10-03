<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/logo-lockup-dark.svg">
    <img src="assets/brand/logo-lockup.svg" alt="OpenContextEngine" width="660">
  </picture>
  <p><strong>Precise code context for AI coding agents.</strong></p>
  <p>Find related code across files. Follow its connections. Give your agent the evidence it needs.</p>
  <p>
    <a href="docs/BENCHMARKS.md#retrieval-speed"><img src="https://img.shields.io/badge/dev_evidence_coverage-91.67%25-23875b?style=flat-square" alt="Development evidence coverage: 91.67%"></a>
    <a href="docs/BENCHMARKS.md#retrieval-speed"><img src="https://img.shields.io/badge/median_retrieval-1.90_s-23875b?style=flat-square" alt="Median retrieval: 1.90 seconds"></a>
    <a href="docs/BENCHMARKS.md#engineering-validation"><img src="https://img.shields.io/badge/verified_tests-83-23875b?style=flat-square" alt="83 verified tests"></a>
    <a href="docs/QUICKSTART.md"><img src="https://img.shields.io/badge/MCP-stdio-193c34?style=flat-square" alt="MCP over stdio"></a>
  </p>
  <p><a href="#quick-start">Quick start</a> · <a href="docs/BENCHMARKS.md">Benchmarks</a> · <a href="docs/QUICKSTART.md">MCP setup</a></p>
</div>

OpenContextEngine is a **self-hostable code context engine** that turns natural-language tasks into relevant source code, with original file paths and line numbers. It combines semantic and keyword search, structural relationships, and neural reranking within a fixed context budget.

## Why OpenContextEngine

- **Search beyond exact words.** Describe a behavior; retrieve its implementation and connected code across files.
- **Understand code structure.** Python, TypeScript, JavaScript, and Go adapters, plus text fallback for other languages, configuration, and scripts.
- **Stay current as you edit.** Saved changes, file deletions, and branch switches sync automatically. Unchanged embeddings are reused; incomplete updates never replace a complete index.
- **Work through MCP.** `search_code` retrieves evidence; `index_status` reports synchronization. Run your own model services and keep the retrieval stack under your control.

## Measured results

**1.90 s median retrieval with 91.67% evidence coverage** across 76 development queries on Click, HTTPX, Zod, and esbuild, within a 4,000-token budget. The speed update reduced the median from 4.71 s, with no per-query coverage regressions. These are server-side timings with indexes and models already loaded.

An earlier frozen comparison used **30 tasks in Chinese and English**, with the same 4,000-token output budget for both engines:

| Metric | OpenContextEngine | Augment Context Engine¹ |
| --- | ---: | ---: |
| Required evidence coverage | **90.14%** | 85.69% |
| Queries returning all required evidence | **48 / 60** | 40 / 60 |
| Median client latency | 3.76 s | **2.15 s** |

¹ ACE was accessed through its official SDK. These internal, source-derived evaluations are not independent benchmarks; the later speed run did not rerun ACE. [Read the reports, methodology, and raw results →](docs/BENCHMARKS.md)

## Quick start

Requires **macOS or Linux**, Node.js 22.14+, Python 3.10+, Git, and configured embedding/reranking services. Go repositories also need Go 1.22+.

```sh
git clone https://github.com/AnnaSuSu/OpenContextEngine.git
cd OpenContextEngine
npm ci
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Set your model endpoints and keys in `.env`, then add this server to an MCP client:

```json
{
  "mcpServers": {
    "opencontextengine": {
      "command": "node",
      "args": [
        "/absolute/path/to/OpenContextEngine/scripts/mcp-reponerve.mjs",
        "--root", "/absolute/path/to/your-repository"
      ]
    }
  }
}
```

The MCP server starts the repository worker and maintains its index. **Save your code; the index follows.** [Model configuration, shared services, and update behavior →](docs/QUICKSTART.md)

## Explore

[Benchmark report](docs/BENCHMARKS.md) · [Raw evaluations](docs/eval/results) · [Retrieval engine](src/retrieval) · [Technical report](TECHNICAL_REPORT.md) · [Project goals](GOALS.md) · [Logo assets](assets/brand)

Historical reports and internal commands retain the project's former name, **RepoNerve**.
