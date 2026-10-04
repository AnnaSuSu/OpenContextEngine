# MCP integration

OpenContextEngine uses the official TypeScript MCP SDK's stdio transport and provides two tools:

- `search_code(directory_path, query, budget=4000, freshnessWaitMs=30000)`: search the specified repository's current source and return file paths, original line numbers, evidence snippets, and the index version.
- `index_status(directory_path)`: check index readiness, changed-file counts, embedding reuse, and the most recent update error.

The implementation uses the [official SDK's stdio and tool registration interfaces](https://ts.sdk.modelcontextprotocol.io/server).

In the default automatic-workspace mode, the agent must pass the project's absolute path as `directory_path` to both tools. Model calls use the configured remote embedding and reranking services; no additional GPT endpoint is required.

## Use with one client

Follow the [Quickstart](QUICKSTART.md) to install and run `open-context-engine setup`. The example below is for clients that accept `mcpServers` JSON and can find the CLI on `PATH`. For Codex TOML and absolute-path configurations, see [client setup notes](QUICKSTART.md#client-setup-notes).

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

Configuration precedence is: process environment variables → user settings saved by `setup` → `.env` in the OpenContextEngine source directory. The searched project's `.env` is not read. The default index location is `~/.cache/opencontextengine/<repository-path-hash>/`; override it with `--state /outside/repository/index`.

The default mode is not tied to one project. On first access to a project path, the service starts a local HTTP worker with a dynamic port and authentication key. Later requests reuse its worker and index. One MCP session can search multiple projects. Initial indexing runs in the background, and searches wait for synchronization; use `index_status` to check progress first.

To use a fixed project, append `"--root", "/absolute/path/to/your-repository"` to `args`. Tool calls may then omit `directory_path`; if provided, it must refer to that same project.

Associated workers exit when the client closes, stdin reaches EOF, or a termination signal arrives. stdout carries only the MCP protocol; logs go to stderr.

## Share a repository across clients

This is an optional setup for source installations. An index directory permits only one writer. To let multiple clients search the same repository simultaneously, start a separate persistent service from the OpenContextEngine source directory:

```sh
# Set OCE_API_KEY in .env to at least 24 characters.
npm run serve-retrieval -- --root /absolute/path/to/your-repository --port 23505
```

Use the following command in each MCP client, with the same service key:

```json
{
  "command": "open-context-engine",
  "args": ["mcp", "--connect"],
  "env": {
    "OCE_BASE_URL": "http://127.0.0.1:23505",
    "OCE_API_KEY": "replace-with-at-least-24-random-characters"
  }
}
```

`--connect` only connects to the service. Omit `directory_path` from tool calls; closing MCP does not stop the shared service. Use HTTPS or an explicit local SSH forward when connecting to a remote worker. The MCP search tool requires a live index started with `--root`; it does not treat an old frozen evaluation index as the current workspace.

## Behavior while editing

Save files normally; no manual rebuild or Git commit is required. By default, changes are checked every second, with consecutive edits debounced for 300 milliseconds. Searches also actively check current file hashes:

1. Synchronized: search the complete version immediately.
2. Updating: wait within `freshnessWaitMs`, defaulting to 30 seconds and capped at 120 seconds. For large initial indexes, call `index_status` first.
3. Parsing or model failure, wait timeout, or source changes during retrieval: return `isError: true` with an explicit reason so the agent can check status or retry.

Only saved files are processed; the index cannot read unsaved code. See [automatic updates](LIVE_INDEX.md) for default exclusions, model changes, persistent-cache removal, and the scope of structural reanalysis.

## Validation

These commands are for source development and maintenance. Install development dependencies and the test Python environment first.

```sh
npm test
OCE_GO_BINARY=/path/to/go .venv/bin/python -m unittest discover -s tests -p '*_test.py'
# Calls configured real remote models and saves results under .pilot-state/mcp-smoke.
node scripts/smoke-mcp.mjs --auto-workspace
```

Automated tests use the official MCP client for real stdio handshakes, tool discovery, input validation, retrieval after saved edits, and update failures. Deterministic model protocol stubs check service behavior.

A separate real remote-model smoke test completed on 2026-10-04 (Beijing time): initial indexing and retrieval, embedding only 1 new unit while reusing 2 after a Python edit, removing corresponding evidence after deleting a JS file, and restoring the same index version after closing and restarting MCP. See the [MCP smoke results](eval/results/mcp-live-smoke-20261004.json). This validates the integration and update correctness, not retrieval quality. The three queries, including index waits, took 3.61, 5.29, and 3.74 seconds; these are not directly comparable with retrieval latency on a prebuilt index.
