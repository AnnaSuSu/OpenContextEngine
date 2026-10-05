# Workspace indexing and automatic updates

The persistent service supports saved files in any local repository. First access builds a complete index. Later updates detect changes by file-content hash, reuse embeddings for unchanged code units, build a new version in the background, and switch versions atomically. No prior Git commit is required.

## Run a separate service from source

Supported platforms are macOS / Linux / Windows, requiring Node.js 22.14+, Python 3.10+, and Git. Native Windows support requires version 0.1.3 or later. Repositories with Go files also require a Go compiler. Models run through configured remote embedding and reranking services, without local model loading. For ordinary MCP use, follow the [Quickstart](QUICKSTART.md) and run `open-context-engine setup`; a separate HTTP service is unnecessary.

```sh
npm ci
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# Set model endpoints and OCE_API_KEY (at least 24 characters) in .env.
npm run serve-retrieval -- --root /absolute/path/to/repository --port 23505
```

On Windows, create and install the source environment in PowerShell:

```powershell
npm ci
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Set model endpoints and OCE_API_KEY (at least 24 characters) in .env.
npm run serve-retrieval -- --root "C:\Users\you\project" --port 23505
```

npm installations use the Python environment created and saved by `setup`. Source installations can select an interpreter with `OCE_PYTHON`; otherwise, compatible locations such as the source directory's `.venv` are checked before falling back to `python3` on macOS/Linux or `python` on Windows. Virtual environments use `bin/python` on macOS/Linux and `Scripts/python.exe` on Windows. Select the Go compiler with `OCE_GO_BINARY`. Enable Go type analysis with `OCE_LANGUAGE_OPTIONS='{"go":{"mode":"types"}}'`; syntax-based structure analysis remains the default.

Indexes default to `~/.cache/opencontextengine/<repository-path-hash>/`; override this with `--state /outside/repository/index`. Existing installations automatically reuse their previous cache directory. Keep the state directory outside the source directory to avoid indexing its own output. Only one process may write to a state directory. After stopping the service, deleting the entire state directory removes source copies and vectors. Historical vectors are retained to reuse content when switching branches.

Without `--root`, the HTTP command `serve-retrieval` retains the original frozen-index mode for earlier evaluations and services.

Without `--root`, `npm run mcp` uses automatic-workspace mode. The agent passes an absolute `directory_path` to every `search_code` or `index_status` call. First access starts a separate project process and index; later calls reuse them. Processes for multiple projects remain running until the client disconnects. Paths are normalized to real directories, so symbolic links do not create duplicate processes; concurrent first access to the same project starts it only once. After a process exits, the next access restarts it and reads the persistent index. In automatic mode, `--state` is the cache base directory, with a separate path-hash subdirectory for each project.

MCP's `--root` fixes one project and rejects switches to other directories. `--connect` connects to an existing service and does not accept `directory_path`. Model configuration precedence is process environment variables → user settings saved by `setup` → `.env` in the OpenContextEngine source directory. The target project's `.env` is not read.

## Update rules

- By default, scan Git-tracked files and new unignored files every second. Non-Git directories use the same text-admission rules. Read saved disk content, not unsaved editor buffers.
- Debounce consecutive changes for 300 milliseconds before building. Adjust this with `OCE_POLL_SECONDS` and `OCE_DEBOUNCE_SECONDS`.
- Handle additions, edits, deletions, renames, `git switch`, and `git pull` through content differences. Deleted files' units and references do not enter the new version.
- Reuse text parsing per file. Python, JS/TS, and Go relationships can cross files, so a changed language group is conservatively reanalyzed in full; other groups are reused. JS/TS share a group, and Go module-path configuration changes also refresh parsing. Compiler-level minimal dependency invalidation is not implemented.
- Embedding cache keys include the provider, model name, dimensions, revision, and complete actual model input. Reuse vectors when only line numbers change. Re-embed when a rename changes the path in the input. Relationship changes do not require new embeddings if the model input stays the same.
- Changes to `EMBEDDING_MODEL`, `OCE_EMBEDDING_DIMENSIONS`, or the provider create a new vector-cache identity. When weights change under the same model name, increment `OCE_EMBEDDING_REVISION`. Historical evaluations used Qwen3-Embedding-4B / 1024 dimensions; configure the actual dimensions returned by your service rather than copying the benchmark value. Other models must support the current source-retrieval input format and be evaluated separately.
- Write index files into a separate version directory, then atomically replace the version pointer. Requests use a fixed in-memory version. Model failures or changes during a build do not overwrite the complete active version. Python syntax errors degrade only the affected files to text chunks; the new version includes current content and persistent parse diagnostics, without stale structural relations.

Synchronization uses automatic incremental polling rather than filesystem event watching. Scan and structural reanalysis costs on large repositories still require separate validation.

## Query consistency

`POST /search` accepts `query`, `budget`, `trace`, and optional `freshnessWaitMs` (default 30 seconds, maximum 120 seconds). Each query first scans current source and waits for its matching index; file hashes are verified again after retrieval. Successful results include `index.identity` and `freshness: verified-after-search`.

Source changes during retrieval, update failures, or wait timeouts return HTTP 503 with explicit index status, instead of presenting old source as current. Source can change again after a response, so agents should still read target files before editing.

`GET /status` uses the same Bearer authentication as search and returns `starting / updating / ready / failed`, the current version, changed-file counts, reuse counts, and the latest error type. Status reflects the most recent background observation; searches perform an additional active check. `GET /healthz` indicates process liveness, not index readiness.

Added regression coverage includes additions/edits/deletions/renames, vector reuse after line-number changes, branch-content restoration, persistent caches, cross-file reference refresh, empty repositories, edits during builds, failure recovery, Python syntax fallback and recovery without stale results, and the single-writer constraint.
