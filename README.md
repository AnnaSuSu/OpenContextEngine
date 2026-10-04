<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/logo-lockup-dark.svg">
    <img src="assets/brand/logo-lockup.svg" alt="OpenContextEngine" width="660">
  </picture>
  <p><strong>Precise code context for AI coding agents.</strong></p>
  <p>Find related code across files. Follow its connections. Give your agent the evidence it needs.</p>
  <p>
    <a href="docs/BENCHMARKS.md#seven-method-comparison"><img src="https://img.shields.io/badge/dev_evidence_coverage-94.79%25-23875b?style=flat-square" alt="Development evidence coverage: 94.79%"></a>
    <a href="docs/BENCHMARKS.md#seven-method-comparison"><img src="https://img.shields.io/badge/median_retrieval-1.73_s-23875b?style=flat-square" alt="Median retrieval: 1.73 seconds"></a>
    <a href="docs/BENCHMARKS.md#engineering-validation"><img src="https://img.shields.io/badge/verified_tests-107-23875b?style=flat-square" alt="107 verified tests"></a>
    <a href="docs/QUICKSTART.md"><img src="https://img.shields.io/badge/MCP-stdio-193c34?style=flat-square" alt="MCP over stdio"></a>
  </p>
  <p><a href="#quick-start">Quick start</a> · <a href="docs/BENCHMARKS.md">Benchmarks</a> · <a href="docs/QUICKSTART.md">MCP setup</a></p>
</div>

OpenContextEngine is a **self-hostable code context engine for AI coding agents**. Connect it to your agent through MCP to help it explore an unfamiliar codebase, locate implementations, and find the related code needed for a fix or feature.

It indexes your working directory and follows saved changes. Given a natural-language task, it combines semantic and keyword search, code relationships, and reranking to return relevant source snippets with file paths and line numbers, within a fixed context budget.

## Why OpenContextEngine

- **Search beyond exact words.** Describe a behavior; retrieve its implementation and connected code across files.
- **Understand code structure.** Python, TypeScript, JavaScript, and Go adapters, plus text fallback for other languages, configuration, and scripts.
- **Stay current as you edit.** Saved changes, file deletions, and branch switches sync automatically. Unchanged embeddings are reused; incomplete updates never replace a complete index.
- **Work across projects through MCP.** Your agent supplies the project path; indexes start on demand and are reused. `search_code` retrieves evidence; `index_status` reports synchronization.

## Measured results

![Required evidence coverage and observed query time](assets/benchmarks/method-comparison.svg)

**94.79% required evidence coverage · 1.73 s median retrieval · 69/80 queries with complete evidence.** Seven engines, four repositories, the same 4,000-token output budget. OpenContextEngine retained the most required evidence in this internal development evaluation.

Measured with the optional batch rerank API. 40 source-derived tasks, each asked in Chinese and English. Coverage measures source evidence, not coding-agent success. Timings reflect native retrieval for open tools and SDK client calls for ACE. [Full comparison, configurations, and per-query results →](docs/eval/METHOD_COMPARISON.md)

## Quick start

Requires **macOS or Linux**, Node.js 22.14+, Python 3.10+, Git, and configured embedding/reranking services. Go repositories also need Go 1.22+.

**Preparing the first npm release; not yet published.** Get the installation archive from the maintainer, then expand your client's guide. Model settings are shared across clients on the same machine.

<details>
<summary><strong>Codex — install, connect, and search</strong></summary>

**1. Install the CLI**

With Codex CLI already installed, run:

```sh
npm install -g /path/to/open-context-engine-0.1.0.tgz
```

**2. Configure your models**

```sh
open-context-engine setup
```

Enter your embedding and reranking base URLs, API keys, model names, and embedding dimensions. Setup installs isolated Python dependencies and saves your settings. The default reranker uses the ordinary `/rerank` API. [Endpoint examples →](docs/QUICKSTART.md#2-shared-model-configuration)

**3. Add the MCP server**

```sh
codex mcp add open-context-engine -- open-context-engine mcp
codex mcp get open-context-engine
```

The second command checks the saved configuration. These commands assume `open-context-engine` is on the client's `PATH`. For the desktop app or source installations, use the [absolute-path configuration](docs/QUICKSTART.md#client-setup-notes). Restart an already-running Codex client after adding the server.

**4. Search your project**

```sh
cd /path/to/your-project
codex
```

Ask:

> Use open-context-engine's search_code tool to explain this project's main functionality. Include the entry points and relevant file paths and line numbers.

Codex supplies the project's absolute path as `directory_path`. The first request starts indexing; if it is still building, ask Codex to check `index_status` and retry when ready. Later searches reuse the index, and saved changes update automatically.

[Codex MCP reference](https://developers.openai.com/codex/mcp)

</details>

<details>
<summary><strong>Claude Code — install, connect, and search</strong></summary>

**1. Install the CLI**

With Claude Code already installed, run:

```sh
npm install -g /path/to/open-context-engine-0.1.0.tgz
```

**2. Configure your models**

```sh
open-context-engine setup
```

Enter your embedding and reranking base URLs, API keys, model names, and embedding dimensions. Setup installs isolated Python dependencies and saves your settings. If you already completed setup for Codex, reuse those settings and skip this step. [Endpoint examples →](docs/QUICKSTART.md#2-shared-model-configuration)

**3. Add the MCP server**

```sh
claude mcp add --transport stdio --scope user open-context-engine -- open-context-engine mcp
```

User scope makes the server available across your projects. For a shared project configuration, run the command from that project and replace `--scope user` with `--scope project`. These commands assume `open-context-engine` is on the client's `PATH`; see [client setup notes](docs/QUICKSTART.md#client-setup-notes) for absolute paths. Restart an already-running Claude Code session after adding the server.

**4. Search your project**

```sh
cd /path/to/your-project
claude
```

Run `/mcp` to check the connection, then ask:

> Use open-context-engine's search_code tool to explain this project's main functionality. Include the entry points and relevant file paths and line numbers.

Claude supplies the project's absolute path as `directory_path`. The first request starts indexing; if it is still building, ask Claude to check `index_status` and retry when ready. Later searches reuse the index, and saved changes update automatically.

[Claude Code MCP reference](https://code.claude.com/docs/en/mcp)

</details>

<details>
<summary>Other MCP clients</summary>

[Install and run setup](docs/QUICKSTART.md#1-install), then use the configuration printed by `open-context-engine mcp-config` in your client's supported format. For clients that accept `mcpServers` JSON and can find the installed command on `PATH`:

```json
{
  "mcpServers": {
    "open-context-engine": {
      "command": "open-context-engine",
      "args": ["mcp"]
    }
  }
}
```

Your agent supplies the current project's absolute path as `directory_path`. To pin one project, add `"--root", "/absolute/path/to/your-repository"` to `args`.

</details>

<details>
<summary>Run from source or build an internal package</summary>

```sh
git clone https://github.com/AnnaSuSu/OpenContextEngine.git
cd OpenContextEngine
npm ci
node bin/opencontextengine.mjs setup
# Build an installable archive for internal testers:
npm pack
```

Use the absolute Node and CLI paths printed by setup. [Client-specific configuration →](docs/QUICKSTART.md#client-setup-notes)

</details>

[Model configuration, troubleshooting, and update behavior →](docs/QUICKSTART.md)

Once published, install with `npm install -g open-context-engine`. Until then, use the archive above. [Release checklist](docs/RELEASING.md).

## Explore

[Benchmark report](docs/BENCHMARKS.md) · [Raw evaluations](docs/eval/results) · [Retrieval engine](src/retrieval) · [Logo assets](assets/brand)

## License

[MIT](LICENSE) © 2026 AnnaSuSu.
