# Connect OpenContextEngine to your agent

OpenContextEngine runs a local repository index and calls configured model services for embeddings and reranking. Its MCP interface uses stdio. Currently supported hosts: **macOS and Linux**.

## 1. Install

Requires Node.js 22.14+, Python 3.10+, and Git. Go source analysis also needs Go 1.22+ on `PATH`, or an explicit `OCE_GO_BINARY`.

**Internal testing only; no npm registry publication.** Install the archive supplied by the maintainer:

```sh
npm install -g /path/to/opencontextengine-0.1.0.tgz
opencontextengine setup
```

`setup` asks for your embedding and reranking endpoints, keys, model names, and embedding dimensions. It creates a private Python virtual environment, installs NumPy and tiktoken, and preloads tokenizer data. No model weights are installed. API key input is not echoed. Use `--python /absolute/path/to/python3` to select a base interpreter.

You can also run the same setup from source:

```sh
git clone https://github.com/AnnaSuSu/OpenContextEngine.git
cd OpenContextEngine
npm ci
node bin/opencontextengine.mjs setup
```

Maintainers can build the archive with `npm pack`. The package is marked private to prevent accidental registry publication; this does not prevent local tarball installation.

## 2. Shared model configuration

Setup saves `~/.config/opencontextengine/config.json` with owner-only file permissions. All MCP clients running under the same user share these settings. Python environments live in the adjacent `runtimes/` directory. Use `OCE_CONFIG_HOME` to select a separate configuration directory; setup includes that override in its generated MCP configuration.

Configuration precedence is **process environment → saved user settings → source checkout `.env` defaults**. The `.env` of the project being searched is never loaded. Existing source installations using `.env` and `OCE_PYTHON` continue to work.

For automation, set the following environment variables and run `opencontextengine setup --non-interactive`:

```dotenv
EMBEDDING_BASE_URL=https://your-embedding-service.example/v1
EMBEDDING_API_KEY=your-embedding-key
EMBEDDING_MODEL=Qwen3-Embedding-4B
OCE_EMBEDDING_DIMENSIONS=1024

RERANK_BASE_URL=https://your-reranker-service.example/v1
RERANK_API_KEY=your-reranker-key
RERANK_MODEL=Qwen3-Reranker-4B
OCE_RERANK_API=rerank
```

The embedding service must implement `POST /v1/embeddings`. By default, the reranker uses the ordinary `/rerank` API: requests contain `model`, `query`, `documents`, and `top_n`; responses must return every requested document in `results`, with its original `index` and a finite `relevance_score` between 0 and 1. Results may arrive in relevance order. Set the reranker base URL to the part before `/rerank`: for example, `https://provider.example/v1`, `/v2`, or `https://provider.example` for an unversioned endpoint.

HTTPS is the default. For an explicitly trusted remote HTTP deployment, set `OCE_ALLOW_HTTP=1` before running `opencontextengine setup`; setup saves this choice in the shared configuration. HTTP transmits API keys and source text without encryption. Local model endpoints remain prohibited. Set `OCE_EMBEDDING_DIMENSIONS` to the service's actual output size (for example, `2560`); changing the provider or dimensions creates a new index generation and does not mix incompatible cached vectors.

OpenContextEngine groups the needed pairs by query, reuses scores within each search, and makes at most two concurrent rerank requests by default. Optional `OCE_RERANK_CONCURRENCY` (1–8, default 2) and `OCE_RERANK_MAX_DOCUMENTS` (1–1,024, default 128) control concurrency and documents per request. It requests all scores and rejects missing, duplicate, or invalid result indices; errors are surfaced without silently switching endpoints.

For the [optional benchmark reranker server](RERANKER_API.md), you can optionally set `OCE_RERANK_API=rerank-batch` to combine multiple queries into its custom `/rerank-batch` endpoint. The default `rerank` mode works with this server too. Qwen3-Embedding-4B / Qwen3-Reranker-4B are the evaluated models; the published seven-method benchmark used the custom batch mode. Other providers and models still need compatibility and quality validation, especially if they score documents jointly rather than independently. Changing document batch limits may then affect scores.

The launcher defaults to HTTPS model endpoints, with explicit HTTP opt-in and SSH/direct-worker transport options available in [the transport configuration](../src/eval/remote-models.mjs). It does not install or load model weights on the client. Repository fragments and queries are sent to the model endpoints you configure.

For internal testing, both model APIs can use an existing SSH connection. Keep the logical `EMBEDDING_BASE_URL` and `RERANK_BASE_URL` unchanged so the vector cache retains its provider identity. Start a loopback-only forward in a separate terminal (replace the example host and server ports):

```sh
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L 127.0.0.1:43079:127.0.0.1:8079 \
  -L 127.0.0.1:43078:127.0.0.1:8078 operator@model-host.example
```

Then start the CLI with these overrides, or save them with `setup --non-interactive`:

```dotenv
EMBEDDING_SSH_TUNNEL_URL=http://127.0.0.1:43079/v1
EMBEDDING_SSH_REMOTE=operator@model-host.example:22
RERANK_SSH_TUNNEL_URL=http://127.0.0.1:43078
RERANK_SSH_REMOTE=operator@model-host.example:22
```

The rerank tunnel must preserve the configured base URL's path prefix (for example, `/v1` if required). Keep the SSH process running while using MCP. The CLI does not create SSH sessions or store SSH passwords, and a disconnected tunnel surfaces an error instead of falling back to public HTTP. Models continue to run on the remote server.

## 3. Add the MCP server

Paste the MCP configuration printed by setup into your client, or print it again with `opencontextengine mcp-config`. It uses absolute Node and CLI paths so desktop clients do not need to find npm's global binary directory.

If your client already has `opencontextengine` on `PATH`, this shorter equivalent works:

```json
{
  "mcpServers": {
    "opencontextengine": {
      "command": "opencontextengine",
      "args": ["mcp"]
    }
  }
}
```

Use your client's equivalent configuration format. Configuration and dependency errors go to stderr; MCP stdout is reserved for protocol messages.

Without `--root`, the server uses **automatic workspace mode**. Your agent supplies the absolute project directory in `directory_path` on each tool call. No indexing starts until a project is requested; first access starts a repository worker and background indexing. Later calls reuse it. One MCP session can search multiple projects, each with an independent worker and persistent index. Workers stay active until the client disconnects, when all are stopped.

The server does not infer your editor's project from its own launch directory. Its tool instructions tell the agent to use the project path supplied by the host, or inspect the current project directory. Missing, relative, or invalid paths return an error. Symbolic links to the same directory share a worker. Supply the same project root consistently, rather than a different subdirectory on each call.

Example tool arguments (sent by your agent):

```json
{"directory_path":"/absolute/path/to/your-repository","query":"Where are user sessions validated?"}
```

To pin the server to one project instead, append `"--root", "/absolute/path/to/your-repository"` to `args`. In this mode `directory_path` may be omitted; a different project path is rejected. Existing fixed-project configurations continue to work.

| Tool | Purpose |
| --- | --- |
| `search_code` | Pass `directory_path` and describe the behavior in `query`. Returns source paths, line numbers, and relevant code; default budget: 4,000 tokens. |
| `index_status` | Pass `directory_path` to inspect indexing progress, active generation, vector reuse, and the latest update error. First access also starts that project's index. |

## Updates & storage

Saved files are checked every second by default, with a 300 ms debounce. New files, deletions, renames, and branch changes update the index automatically. Embeddings are reused by model identity and actual input content. Structural analysis conservatively refreshes the affected language group to update references in unchanged files.

Search actively checks source hashes before retrieval and again before returning. It waits up to 30 seconds for synchronization (`freshnessWaitMs`, maximum 120 seconds). Failed updates, timeouts, or edits during retrieval produce explicit errors. Unsaved editor buffers are not indexed.

State is stored in `~/.cache/opencontextengine/<repository-path-hash>/`. Override it with `--state /outside/repository/index`: automatic mode creates a separate path-hash subdirectory for each project; fixed `--root` mode uses that exact state directory. Existing installations automatically reuse their previous cache location. One worker may write to a state directory at a time. Stop that worker and remove the directory to delete stored source and embeddings.

When model weights change under the same name, increment `OCE_EMBEDDING_REVISION`. A different provider, model name, or dimension count also invalidates vector reuse. Other models need separate compatibility and quality validation.

## Share one worker across clients

This optional source-installation workflow shares a running worker, in addition to the shared model configuration available to all CLI installations. Set an `OCE_API_KEY` of at least 24 characters in the environment, then run from the checkout:

```sh
npm run serve-retrieval -- --root /absolute/path/to/your-repository --port 23505
```

Configure each MCP client to run `opencontextengine mcp --connect` (or `node scripts/mcp-opencontextengine.mjs --connect` from source), with `OCE_BASE_URL=http://127.0.0.1:23505` and the same `OCE_API_KEY`. This mode always uses the shared worker's configured project: omit `directory_path`. Closing a client leaves the shared worker running.

## Check and upgrade

Run `opencontextengine doctor` to check model configuration, Python dependencies, tokenizer data, and Git. This does not send code to model providers; endpoint authentication is checked during actual search.

For an internal upgrade, install the new archive and rerun setup:

```sh
npm install -g /path/to/new-opencontextengine.tgz
opencontextengine setup
```

Press Enter to retain saved settings. Setup reuses a healthy managed Python runtime when its dependency requirements match; otherwise it builds a new environment before changing the saved configuration. Failed dependency installation preserves the previous settings and runtime. Old runtimes remain available for rollback. Restart the MCP client after an upgrade. Project indexes remain outside the package directory and continue to reuse compatible embeddings.

First-time setup requires network access to npm/PyPI and tokenizer data. If Python is missing or lacks `venv`/`pip`, install Python 3.10+ with those components, then rerun setup. The CLI does not install system Node, Python, Git, or Go.

## Internal testing checklist

1. Install the supplied tarball on macOS or Linux and run setup with your model endpoints.
2. Paste the generated MCP configuration into your client, restart it, and search a small project.
3. Save an edit, add a file, and delete a file; verify search returns current source.
4. Switch to another project and back; verify the results belong to the requested project.
5. Restart the client and reinstall the archive; verify model settings and compatible indexes are retained.

For issues, include the CLI version, operating system, client name, and the error message. Keep API keys and private source code out of reports.

[Benchmark & test report](BENCHMARKS.md) · [Detailed update design](LIVE_INDEX.md) · [MCP implementation](../src/mcp.mjs)
