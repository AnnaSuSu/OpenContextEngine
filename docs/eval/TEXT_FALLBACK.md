# Generic text fallback

2026-10-04. Unknown languages, configuration, and scripts can now use the existing vector retrieval, BM25, two-wave reranking, and budget-selection pipeline. Python and TypeScript/TSX retain their original structural adapters. Other eligible text is marked `language=text`, without claiming semantic parsing support for those languages.

## Behavior and boundaries

- Split text on original physical lines, by default at most 65 lines with a target of at most 1,800 characters, preferring a blank-line boundary in the latter half. Keep an exceptionally long single line intact rather than inventing sublines. Existing model-input and output-budget limits still apply, so a very long line may not fully participate in model scoring or final output.
- Retain paths, start/end line numbers, and original text. Normalize CRLF/CR/LF and omit UTF-8 BOM from units. Unicode paragraph separators are not mistaken for physical line breaks and do not change final returned line numbers.
- Each text unit has a distinct identifier and empty relationship/edge lists. Matching names do not imply function calls, cross-file references, or cross-language relationships.
- Exclude common dependency/build directories, lockfiles, compressed outputs, common binary extensions, local `.env`, private-key extensions, files matching generated-code markers such as `Code generated ... DO NOT EDIT.`, and symbolic links. Content checks also exclude binary control bytes, non-UTF-8 text, and files over 1 MiB. The exclusion policy is explicit and limited, without claiming to detect all generated code.
- Automatic discovery prefers Git's tracked + unignored file set and honors ignore rules. Ordinary directories use recursive traversal without following links. Snapshots retain exclusion reasons; directly supplied snapshots also undergo file-eligibility checks, and index metadata records accepted/excluded counts.
- Syntax errors in supported languages still fail explicitly rather than silently falling back to text. Blank files produce no units. An entirely blank or excluded input explicitly rejects index construction without model requests.
- File policy, text adapter, and source digests participate in index identity; existing indexes must rebuild for the new identity. Online model rounds remain one embedding and at most two rerank waves, without a separate text-model path.

## Usage

Place snapshot outputs outside the indexed directory so they are not discovered as source on the next pass:

```sh
python3 scripts/prepare-source.py /path/to/repository --output /tmp/source-snapshot.json
python3 scripts/inspect-source.py /path/to/repository \
  --snapshot /tmp/source-snapshot.json --output /tmp/source-units.json
```

These commands only parse and inspect files, without model calls. Pass snapshots to the existing `build_index` / retrieval worker; models continue to use authorized remote services. This change adds no Tree-sitter, LSP, or one-command deployment service for arbitrary repositories.

## Validation

Local automated tests cover mixed languages, extensionless configuration, CRLF/BOM/Unicode, complete-line slicing, long lines, exclusion reasons, Git ignore, path/link boundaries, cache reuse, empty indexes, and existing retrieval-model budgets. All 24 Python and 23 Node tests passed.

Reparsing the original 52 Click, HTTPX, and Zod files leaves all fields of 2,333 code units identical to the old index. Replaying the original v6 selection results for 60 responses with the new units yields byte-identical output text. This is structural compatibility and deterministic replay, not 60 new model queries. See the [compatibility records](results/text-fallback-compatibility-20261004.json).

### New mixed-language repository

Freeze public `evanw/esbuild` at `v0.25.0`, commit `e9174d671b1882758cd32ac5e146200f5bee3e45`, unused in earlier parameter tuning. Automatic discovery includes 321 files (8,529,804 bytes), excluding 17 items. Text fallback handles 301 files and structural parsing handles 20 TypeScript files. The 7,865 units comprise 5,590 text and 2,275 TypeScript units. Text fallback adds 5,590 units beyond this repository's structural-only units; this describes index volume, not a before/after query-performance comparison.

Before querying, freeze 8 source-derived tasks with Chinese and English variants: Go boolean options and watch lifecycle, JS subprocess input and platform-dependency generation, TS synchronous worker, YAML release workflow, Make test entry point, and Shell binary installation. Answers are used only for local offline scoring; the remote worker receives only public source, questions, and implementation. Use a uniform 4,000-token budget, at most 80 second-wave candidates, and no query cache. Before querying, the new protocol uniformly excludes blank-only lines from reference spans.

The first complete post-fix index took **286.59 seconds**, with 984 offline embedding requests. All 16 actual queries completed:

| Metric | Result |
| --- | ---: |
| Required evidence coverage | **81.25%** |
| Complete-evidence queries | **12/16 (75%)** |
| Median query time | **6.283 seconds** |
| Query P95 | **8.758 seconds** |
| Returned source / line-number mismatches | **0** |

Both language variants fully cover 6 tasks: Go boolean options, JS subprocess stdin closure, TS synchronous worker, YAML release validation, Make test entry point, and Shell installation. Both miss the frozen reference for Go watch lifecycle. Both JS platform-dependency queries recover platform package-name aggregation but miss package-configuration writeback. This validates searchability and pipeline compatibility, without establishing the completeness of structural retrieval for text units.

See [observed results](results/text-fallback-smoke-20261004.json) for per-query output, omissions, and index information. Data is in `eval/text-fallback-v1/`; execution and verification scripts are in `scripts/text-fallback/`. Separate Python checks confirm all 7,865 local/remote units and index identities match, independently verify all 16 returned responses line by line, and recompute every reference-fact score in agreement with the Node scorer. Original outputs remain locally in `runs/text-fallback-v1/`, excluded from Git by repository convention.

This is small functional validation using source-derived tasks, not an independent benchmark. ACE was not rerun, and results do not establish Python/TS-level retrieval quality for all languages. Latency is internal to the remote process and is not directly comparable with the earlier Mac-client 4.51 seconds.

One index build was aborted before querying to fix Unicode physical-line handling. Frozen questions and answers stayed unchanged. Final results include only the complete post-fix build and queries.
