# Connect OpenContextEngine to your agent

OpenContextEngine runs a local repository index and calls configured model services for embeddings and reranking. Its MCP interface uses stdio. Currently supported hosts: **macOS and Linux**.

## 1. Install

Requires Node.js 22.14+, Python 3.10+, and Git. Go source analysis also needs Go 1.22+ on `PATH`, or an explicit `OCE_GO_BINARY`.

```sh
git clone https://github.com/AnnaSuSu/OpenContextEngine.git
cd OpenContextEngine
npm ci
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

## 2. Configure models

Replace the example endpoints with your own services in `.env`:

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

The embedding service must implement `POST /v1/embeddings`. By default, the reranker uses the ordinary `/rerank` API: requests contain `model`, `query`, `documents`, and `top_n`; responses must return every requested document in `results`, with its original `index` and a finite `relevance_score` between 0 and 1. Results may arrive in relevance order. Use the provider's versioned base URL (for example, `https://provider.example/v1` or `/v2`), without appending `/rerank` yourself.

OpenContextEngine groups the needed pairs by query, reuses scores within each search, and makes at most two concurrent rerank requests by default. Optional `OCE_RERANK_CONCURRENCY` (1–8, default 2) and `OCE_RERANK_MAX_DOCUMENTS` (1–1,024, default 128) control concurrency and documents per request. It requests all scores and rejects missing, duplicate, or invalid result indices; errors are surfaced without silently switching endpoints.

For the [included reranker server](../deploy/reranker/server.py), you can optionally set `OCE_RERANK_API=rerank-batch` to combine multiple queries into its custom `/rerank-batch` endpoint. The default `rerank` mode works with this server too. Qwen3-Embedding-4B / Qwen3-Reranker-4B are the evaluated models; the published seven-method benchmark used the custom batch mode. Other providers and models still need compatibility and quality validation, especially if they score documents jointly rather than independently. Changing document batch limits may then affect scores.

The launcher requires HTTPS model endpoints, with explicit SSH/direct-worker transport options available in [the transport configuration](../src/eval/remote-models.mjs). It does not install or load model weights on the client. Repository fragments and queries are sent to the model endpoints you configure.

## 3. Add the MCP server

For clients that use `mcpServers`, add:

```json
{
  "mcpServers": {
    "opencontextengine": {
      "command": "node",
      "args": [
        "/absolute/path/to/OpenContextEngine/scripts/mcp-opencontextengine.mjs"
      ],
      "env": {
        "OCE_PYTHON": "/absolute/path/to/OpenContextEngine/.venv/bin/python"
      }
    }
  }
}
```

Use absolute paths and your client's equivalent configuration format. The MCP process reads `.env` from the OpenContextEngine checkout; process environment values take precedence. Use the `OCE_*` configuration variables shown here.

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

Set a `OCE_API_KEY` of at least 24 characters in `.env`, then run:

```sh
npm run serve-retrieval -- --root /absolute/path/to/your-repository --port 23505
```

Configure each MCP client to run `scripts/mcp-opencontextengine.mjs --connect`, with `OCE_BASE_URL=http://127.0.0.1:23505` and the same `OCE_API_KEY`. This mode always uses the shared worker's configured project: omit `directory_path`. Closing a client leaves the shared worker running.

[Benchmark & test report](BENCHMARKS.md) · [Detailed update design](LIVE_INDEX.md) · [MCP implementation](../src/mcp.mjs)
