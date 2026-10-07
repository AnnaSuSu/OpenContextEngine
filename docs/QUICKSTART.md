# Connect OpenContextEngine to your agent

OpenContextEngine runs a local repository index and calls configured model services for embeddings and reranking. Its MCP interface uses stdio. Supported hosts: **macOS, Linux, and Windows**. Native Windows support requires version **0.1.3** or later.

## 1. Install

Requires Node.js 22.14+, Python 3.10+, and Git. Go source analysis also needs Go 1.22+ on `PATH`, or an explicit `OCE_GO_BINARY`.

Install the package from npm:

```sh
npm install -g open-context-engine
open-context-engine setup
```

`setup` asks for your embedding and reranking endpoints, keys, model names, and embedding dimensions. It creates a dedicated Python virtual environment, installs NumPy and tiktoken, and preloads tokenizer data. No model weights are installed. API key input is not echoed. Use `--python /absolute/path/to/python3` to select a base interpreter.

You can also run the same setup from source:

```sh
git clone https://github.com/AnnaSuSu/OpenContextEngine.git
cd OpenContextEngine
npm ci
node bin/opencontextengine.mjs setup
```

On Windows, run the npm installation commands in PowerShell with `node`, `npm`, `python`, and `git` on `PATH`; WSL is not required. Setup defaults to `python` and uses `Scripts/python.exe` inside its virtual environment. To select a particular interpreter, run:

```powershell
open-context-engine setup --python "C:\Program Files\Python312\python.exe"
```

Use native absolute project paths such as `C:\Users\you\project` in MCP calls. Generated MCP JSON escapes backslashes automatically.

For internal builds, maintainers can create an archive with `npm pack` and install it with `npm install -g /path/to/open-context-engine-0.1.7.tgz`. See the [release checklist](https://github.com/AnnaSuSu/OpenContextEngine/blob/main/docs/RELEASING.md).

The CLI and package are named `open-context-engine`. The previous `opencontextengine` command remains an alias. Existing configuration and cache directories keep their paths, so saved keys and indexes are reused.

## 2. Shared model configuration

Setup saves `.config/opencontextengine/config.json` under your home directory. Files use owner-only permissions on macOS/Linux; Windows uses the directory's inherited access permissions. All MCP clients running under the same user share these settings. Python environments live in the adjacent `runtimes/` directory. Use `OCE_CONFIG_HOME` to select a separate configuration directory; setup includes that override in its generated MCP configuration.

Configuration precedence is **process environment → saved user settings → source checkout `.env` defaults**. The `.env` of the project being searched is never loaded. Existing source installations using `.env` and `OCE_PYTHON` continue to work.

For automation, set the following environment variables and run `open-context-engine setup --non-interactive`:

```dotenv
EMBEDDING_BASE_URL=https://your-embedding-service.example/v1
EMBEDDING_API_KEY=your-embedding-key
EMBEDDING_MODEL=Qwen3-Embedding-4B
# Match the actual output size of your embedding endpoint.
OCE_EMBEDDING_DIMENSIONS=2560

RERANK_BASE_URL=https://your-reranker-service.example/v1
RERANK_API_KEY=your-reranker-key
RERANK_MODEL=Qwen3-Reranker-4B
```

The setup prompt initially suggests `1024` dimensions; replace it with your endpoint's actual output size. The example above uses `2560`.

The embedding service must implement `POST /v1/embeddings`. By default, the reranker uses the ordinary `/rerank` API: requests contain `model`, `query`, `documents`, and `top_n`; responses must return every requested document in `results`, with its original `index` and a finite `relevance_score` between 0 and 1. Results may arrive in relevance order. Set the reranker base URL to the part before `/rerank`: for example, `https://provider.example/v1`, `/v2`, or `https://provider.example` for an unversioned endpoint.

For Alibaba Cloud Model Studio, use its OpenAI-compatible embedding endpoint and select the DashScope rerank format:

```dotenv
EMBEDDING_BASE_URL=https://YOUR_WORKSPACE.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=qwen3.7-text-embedding
OCE_EMBEDDING_DIMENSIONS=1024
OCE_EMBEDDING_BATCH_SIZE=20
RERANK_BASE_URL=https://YOUR_WORKSPACE.cn-beijing.maas.aliyuncs.com/api/v1
RERANK_MODEL=qwen3.7-text-rerank
OCE_RERANK_API=dashscope
```

Supply your API key through `EMBEDDING_API_KEY` and `RERANK_API_KEY`, then run setup to save these settings. DashScope mode calls `/services/rerank/text-rerank/text-rerank`, nests the request under `input` and `parameters`, and reads `output.results`. The embedding model defaults to 1024 dimensions and accepts up to 20 texts per request; `OCE_EMBEDDING_BATCH_SIZE` limits index-building batches (default 64, range 1–64). Query embedding uses at most five texts per MCP search. Clear any previous SSH transport overrides when switching to direct HTTPS endpoints. Changing the embedding provider or model rebuilds the index; existing embeddings are retained for reuse with their original configuration.

Index-building request concurrency is controlled by `OCE_EMBEDDING_CONCURRENCY` (default 1, range 1–8, per workspace). Start with 2 for a remote endpoint to overlap computation and response transfer. This is separate from `OCE_EMBEDDING_BATCH_SIZE` and the server's GPU inference batch size; increase it only within your provider's request and resource limits. The client keeps at most the configured number of batches in flight, validates and caches each completed batch even if responses arrive out of order, and counts committed documents in progress. After a request fails, it stops submitting new batches and preserves successful in-flight results for the next retry. Changing batch size or concurrency does not invalidate cached vectors. Save these settings through setup or the `env` object in the user configuration file, then restart the MCP client after existing indexing work finishes.

HTTPS is the default. For an explicitly trusted remote HTTP deployment, set `OCE_ALLOW_HTTP=1` before running `open-context-engine setup`; setup saves this choice in the shared configuration. HTTP transmits API keys and source text without encryption. Local model endpoints remain prohibited. Set `OCE_EMBEDDING_DIMENSIONS` to the service's actual output size (for example, `2560`); changing the provider or dimensions creates a new index generation and does not mix incompatible cached vectors.

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
RERANK_SSH_TUNNEL_URL=http://127.0.0.1:43078/v1
RERANK_SSH_REMOTE=operator@model-host.example:22
```

The rerank tunnel must preserve the configured base URL's path prefix. The example above matches `RERANK_BASE_URL=https://your-reranker-service.example/v1`; if your provider uses an unversioned `/rerank` endpoint, omit `/v1` from both base URLs. Keep the SSH process running while using MCP. The CLI does not create SSH sessions or store SSH passwords, and a disconnected tunnel surfaces an error instead of falling back to public HTTP. Models continue to run on the remote server.

## 3. Add the MCP server

Paste the MCP configuration printed by setup into your client, or print it again with `open-context-engine mcp-config`. It uses absolute Node and CLI paths so desktop clients do not need to find npm's global binary directory.

If your client already has `open-context-engine` on `PATH`, this shorter equivalent works:

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

Use your client's equivalent configuration format. Configuration and dependency errors go to stderr; MCP stdout is reserved for protocol messages.

Without `--root`, the server uses **automatic workspace mode**. Your agent supplies the absolute project directory in `directory_path` on each tool call. No indexing starts until a project is requested; first access starts a repository worker and background indexing. Later calls reuse it, including calls from other MCP processes under the same local user. One MCP session can search multiple projects, each with an independent worker and persistent index.

Version **0.1.4** and later automatically share one worker per index directory across compatible clients. Closing a client releases only its lease; a worker exits after all leases expire or are released, no searches remain in flight, and it has been idle for 30 seconds. Clients renew their leases automatically, and reconnect if the worker exits.

The server does not infer your editor's project from its own launch directory. Its tool instructions tell the agent to use the project path supplied by the host, or inspect the current project directory. Missing, relative, or invalid paths return an error. Symbolic links to the same directory share a worker. Supply the same project root consistently, rather than a different subdirectory on each call.

Example tool arguments (sent by your agent):

```json
{"directory_path":"/absolute/path/to/your-repository","query":"Where are user sessions validated?"}
```

To pin the server to one project instead, append `"--root", "/absolute/path/to/your-repository"` to `args`. In this mode `directory_path` may be omitted; a different project path is rejected. Existing fixed-project configurations continue to work.

| Tool | Purpose |
| --- | --- |
| `search_code` | Pass `directory_path` and describe the behavior in `query`. Returns source paths, line numbers, and relevant code; default budget: 8,000 tokens. Pass `budget: 4000` for a smaller response. |
| `index_status` | Pass `directory_path` to inspect indexing progress, active generation, vector reuse, and the latest update error. First access also starts that project's index. |

### Client setup notes

Start with the expandable **Codex** or **Claude Code** guide in the [README](../README.md#quick-start). The CLI registration commands there assume the installed executable is on the client's `PATH`.

For desktop clients or source installations, run `open-context-engine mcp-config` (or `node bin/opencontextengine.mjs mcp-config` from the checkout). Use the absolute `command` and `args` values it prints. Codex uses TOML rather than the printed `mcpServers` JSON; add or update this entry in `~/.codex/config.toml`, replacing the example paths:

```toml
[mcp_servers.open-context-engine]
command = "/absolute/path/to/node"
args = ["/absolute/path/to/bin/opencontextengine.mjs", "mcp"]
startup_timeout_sec = 30
tool_timeout_sec = 180
```

For Claude Code, use those same paths with its registration command:

```sh
claude mcp add --transport stdio --scope user open-context-engine -- /absolute/path/to/node /absolute/path/to/bin/opencontextengine.mjs mcp
```

Quote paths that contain spaces. If the generated configuration includes `env` (for example, a custom `OCE_CONFIG_HOME`), preserve it: use `[mcp_servers.open-context-engine.env]` in Codex or `--env OCE_CONFIG_HOME=/absolute/config/path` before `--transport stdio` in the Claude command. Keep your model keys in the shared OpenContextEngine settings saved by setup. Restart the client after changing its configuration.

- **Command not found:** use the absolute paths above and confirm the Node executable still exists after a Node upgrade.
- **Tools missing:** check `codex mcp get open-context-engine` for the saved Codex entry, or `/mcp` inside Claude Code for connection status; restart the client after configuration changes.
- **Search reports "Index is updating":** synchronization is still running in the background; the search has not run yet. MCP retries a pending update once, then returns a normal `status: "updating"` response with `retryable: true` if more time is needed. This is not an empty search result. Ask the agent to call `index_status` for the same project and retry `search_code` once ready. Progress shows the current stage and, during embedding, completed/total documents requiring new vectors for this update (cached vectors are excluded). Large repositories can take longer than a single tool call's timeout. If status reports an error, resolve that error before retrying.
- **Model configuration or authentication errors:** rerun `open-context-engine setup`. `open-context-engine doctor` checks local configuration and dependencies; an actual search checks access to the model APIs. If using SSH forwarding, keep the tunnel running.

Client references: [Codex MCP](https://developers.openai.com/codex/mcp) · [Claude Code MCP](https://code.claude.com/docs/en/mcp).

## Updates & storage

Saved files are checked every second by default (`OCE_POLL_SECONDS=1`), with a 300 ms debounce (`OCE_DEBOUNCE_SECONDS=0.3`). New files, deletions, renames, and branch changes update the index automatically. Embeddings are reused by model identity and actual input content. Structural analysis conservatively refreshes the affected language group to update references in unchanged files.

Search actively checks source hashes before retrieval and again before returning. Each HTTP search waits up to 30 seconds for synchronization by default (`freshnessWaitMs`, maximum 120 seconds). MCP retries `INDEX_UPDATING` once with an additional wait of `min(freshnessWaitMs, 10000)` milliseconds, giving a default synchronization wait of up to 40 seconds across both attempts; `freshnessWaitMs: 0` disables waiting and retry. HTTP pending responses remain 503 and include `code: "INDEX_UPDATING"`, `retryable: true`, and index progress. MCP presents this specific condition as a normal updating status. Failed updates and edits during retrieval still produce explicit errors. Unsaved editor buffers are not indexed.

Python, JavaScript, TypeScript, and Go files with syntax errors (including unfilled templates) are indexed as plain text with their original paths and line numbers. Healthy files keep their structural analysis; no structural relations are inferred for degraded files. The index remains `ready`, while `index_status` reports `generation.degradedFiles` and `generation.parseDiagnostics` (path, language, error type, line, column, and fallback mode). Search responses include a degraded-file count and MCP displays a short notice. Diagnostics persist across restarts and disappear when the file is repaired or deleted. Model, toolchain, storage, and source-integrity failures still fail explicitly; stale source is never substituted.

State is stored in `~/.cache/opencontextengine/<repository-path-hash>/`. Override it with `--state /outside/repository/index`: automatic mode creates a separate path-hash subdirectory for each project; fixed `--root` mode uses that exact state directory. Existing installations automatically reuse their previous cache location. One worker may write to a state directory at a time. Stop the worker and remove the directory to delete stored source and embeddings.

Automatic mode discovers the writer through an authenticated loopback handshake; concurrent starts keep the existing writer lock intact. Its `worker.json` connection record contains a local access token and is restricted to the current user (POSIX file permissions or a Windows file ACL). Do not share this file.

Configuration and runtime compatibility include model credentials, endpoints, language options, and worker source. Incompatible clients receive an explicit error instead of silently adopting another configuration; close the existing clients before changing settings, or select a separate `--state` directory. An older or manually started worker cannot be adopted automatically: use `--connect` or stop its owning clients before switching to automatic sharing.

Searches are serialized with a bounded queue of 16 active/waiting requests and a 30-second queue wait; saturation returns a retryable busy error.

When model weights change under the same name, increment `OCE_EMBEDDING_REVISION`. A different provider, model name, or dimension count also invalidates vector reuse. Other models need separate compatibility and quality validation.

Optional Go type analysis can be enabled with `OCE_LANGUAGE_OPTIONS='{"go":{"mode":"types"}}'`; the default uses syntax-based analysis. `OCE_PYTHON` selects an existing Python environment with the required dependencies; normal CLI installations use the runtime created by setup.

## Share one worker across clients

This optional source-installation workflow shares a running worker, in addition to the shared model configuration available to all CLI installations. Set an `OCE_API_KEY` of at least 24 characters in the environment, then run from the checkout:

```sh
npm run serve-retrieval -- --root /absolute/path/to/your-repository --port 23505
```

Configure each MCP client to run `open-context-engine mcp --connect` (or `node scripts/mcp-opencontextengine.mjs --connect` from source), with `OCE_BASE_URL=http://127.0.0.1:23505` and the same `OCE_API_KEY`. This mode always uses the shared worker's configured project: omit `directory_path`. Closing a client leaves the shared worker running.

## Check and upgrade

Run `open-context-engine doctor` to check model configuration, Python dependencies, tokenizer data, and Git. This does not send code to model providers; endpoint authentication is checked during actual search.

If upgrading from the old package named `opencontextengine`, first run `npm uninstall -g opencontextengine` to avoid a command-name conflict. This leaves your saved model settings and indexes intact.

To upgrade from npm and reuse your saved settings:

```sh
npm install -g open-context-engine@latest
open-context-engine setup
```

Press Enter to retain saved settings. Setup reuses a healthy managed Python runtime when its dependency requirements match; otherwise it builds a new environment before changing the saved configuration. Failed dependency installation preserves the previous settings and runtime. Old runtimes remain available for rollback. When migrating from the old package name, replace the client entry with the configuration printed by setup: its absolute installation path has changed. Restart the MCP client after an upgrade. Project indexes remain outside the package directory and continue to reuse compatible embeddings.

First-time setup requires network access to npm/PyPI and tokenizer data. If Python is missing or lacks `venv`/`pip`, install Python 3.10+ with those components, then rerun setup. The CLI does not install system Node, Python, Git, or Go.

## Installation verification

1. Install from npm (or an internal tarball) on macOS, Linux, or Windows and run setup with your model endpoints.
2. Paste the generated MCP configuration into your client, restart it, and search a small project.
3. Save an edit, add a file, and delete a file; verify search returns current source.
4. Switch to another project and back; verify the results belong to the requested project.
5. Restart the client and reinstall the package; verify model settings and compatible indexes are retained.

For issues, include the CLI version, operating system, client name, and the error message. Keep API keys and private source code out of reports.

[Benchmark & test report](BENCHMARKS.md) · [Detailed update design](LIVE_INDEX.md) · [MCP implementation](../src/mcp.mjs)
