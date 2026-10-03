# Connect OpenContextEngine to your agent

OpenContextEngine runs a local repository index and calls configured model services for embeddings and reranking. Its MCP interface uses stdio. Currently supported hosts: **macOS and Linux**.

## 1. Install

Requires Node.js 22.14+, Python 3.10+, and Git. Go source analysis also needs Go 1.22+ on `PATH`, or an explicit `REPONERVE_GO_BINARY`.

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
REPONERVE_EMBEDDING_DIMENSIONS=1024

RERANK_BASE_URL=https://your-reranker-service.example/v1
RERANK_API_KEY=your-reranker-key
RERANK_MODEL=Qwen3-Reranker-4B
```

The embedding service must implement `POST /v1/embeddings`. The reranker must implement OpenContextEngine's `POST /v1/rerank-batch` contract; a generic `/rerank` endpoint alone is insufficient. The [included reranker server](../deploy/reranker/server.py) implements it. Qwen3-Embedding-4B / Qwen3-Reranker-4B are the evaluated models.

The launcher requires HTTPS model endpoints, with explicit SSH/direct-worker transport options available in [the transport configuration](../src/eval/remote-models.mjs). It does not install or load model weights on the client. Repository fragments and queries are sent to the model endpoints you configure.

## 3. Add the MCP server

For clients that use `mcpServers`, add:

```json
{
  "mcpServers": {
    "opencontextengine": {
      "command": "node",
      "args": [
        "/absolute/path/to/OpenContextEngine/scripts/mcp-reponerve.mjs",
        "--root", "/absolute/path/to/your-repository"
      ],
      "env": {
        "REPONERVE_PYTHON": "/absolute/path/to/OpenContextEngine/.venv/bin/python"
      }
    }
  }
}
```

Use absolute paths and your client's equivalent configuration format. The MCP process reads `.env` from the OpenContextEngine checkout; process environment values take precedence. Existing `reponerve` filenames and `REPONERVE_*` variables remain the supported interface.

The server starts its repository worker automatically and stops it when the client disconnects. First-time indexing runs in the background.

| Tool | Purpose |
| --- | --- |
| `search_code` | Describe the behavior you need. Returns source paths, line numbers, and relevant code; default budget: 4,000 tokens. |
| `index_status` | Inspect indexing progress, active generation, vector reuse, and the latest update error. |

## Updates & storage

Saved files are checked every second by default, with a 300 ms debounce. New files, deletions, renames, and branch changes update the index automatically. Embeddings are reused by model identity and actual input content. Structural analysis conservatively refreshes the affected language group to update references in unchanged files.

Search actively checks source hashes before retrieval and again before returning. It waits up to 30 seconds for synchronization (`freshnessWaitMs`, maximum 120 seconds). Failed updates, timeouts, or edits during retrieval produce explicit errors. Unsaved editor buffers are not indexed.

State is stored in `~/.cache/reponerve/<repository-path-hash>/`. Override it with `--state /outside/repository/index`. One worker may write to a state directory at a time. Stop that worker and remove the directory to delete stored source and embeddings.

When model weights change under the same name, increment `REPONERVE_EMBEDDING_REVISION`. A different provider, model name, or dimension count also invalidates vector reuse. Other models need separate compatibility and quality validation.

## Share one worker across clients

Set a `REPONERVE_API_KEY` of at least 24 characters in `.env`, then run:

```sh
npm run serve-retrieval -- --root /absolute/path/to/your-repository --port 23505
```

Configure each MCP client to run `scripts/mcp-reponerve.mjs --connect`, with `REPONERVE_BASE_URL=http://127.0.0.1:23505` and the same `REPONERVE_API_KEY`. Closing a client leaves the shared worker running.

[Benchmark & test report](BENCHMARKS.md) · [Detailed update design](LIVE_INDEX.md) · [MCP implementation](../src/mcp.mjs)
