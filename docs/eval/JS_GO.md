# JavaScript and Go structural parsing

2026-10-04. Structural adapters add `.js`, `.jsx`, `.mjs`, `.cjs`, and `.go`, reusing the code-unit, retrieval, reranking, and budget-selection interfaces. Configuration, scripts, and other languages continue to use text fallback.

JavaScript uses the Compiler API from pinned `typescript@5.9.3`, supporting ESM, CommonJS, JSX, functions, and methods, and binding JS/TS imports and calls within the same virtual file set. Cross-JS/TS relationships are remapped to unified IDs; dynamic receivers and unknown callbacks remain unresolved. Physical CR/LF line numbers and compiler character offsets are handled separately, so Unicode separators do not move reference locations. See the [official allowJs documentation](https://www.typescriptlang.org/tsconfig/allowJs.html).

Go uses official `go/parser` to extract functions, receiver methods, types, statement boundaries, and same-symbol continuation units. Optional `languageOptions.go.mode="types"` enables `go/types` for cross-package functions, concrete receiver methods, generic calls, and type references within the snapshot. Default `languageOptions.go.mode="syntax"` uses basic syntactic binding. Locally shadowed callbacks, dynamic interface dispatch, and implementations outside the snapshot remain unresolved. Source units retain complete, nonoverlapping lines and cover all nonblank source. See the [Go parser documentation](https://pkg.go.dev/go/parser).

## Usage

`npm ci` supplies the JS/TS parser. Go indexing requires Go 1.22+; this run used Go 1.27.1. Select the executable with `OCE_GO_BINARY`. Parser helpers compile only this project's standard-library-based implementation, without compiling or executing the analyzed repository or downloading its dependencies. Helper caches are isolated by source and toolchain version.

```sh
export OCE_GO_BINARY=/path/to/go/bin/go
python3 scripts/prepare-source.py /path/to/repository --output /tmp/snapshot.json
python3 scripts/inspect-source.py /path/to/repository --snapshot /tmp/snapshot.json --output /tmp/structure.json
```

## Validation

All 36 Python and 23 Node tests passed, covering ESM/CommonJS, mixed JS/TS calls, Go receivers and shadowing, duplicate platform functions, syntax errors, long functions, Unicode/CRLF, and complete source coverage. All fields of the existing 2,333 Click, HTTPX, and Zod units remain identical.

Automatic discovery includes all eligible files: 64 in Cobra, 215 in Commander, and the original 321 in esbuild, producing 846, 1,090, and 11,295 structural units respectively. See the [structure-check records](results/js-go-structure-20261004.json). Cobra and Commander revisions and four bilingual tasks each were frozen before querying in `eval/js-go-v1/`. `scripts/roadmap/structure.py` runs text/structure comparisons, with answers used only for local scoring.

In basic Go parsing, esbuild's `api.Context` and `ctx.Watch` are both unresolved calls. Type checking connects `api.Context` to its definition in `pkg/api/api.go`; `ctx.Watch` still remains unresolved because its receiver is an interface.

## Actual text-versus-structure comparison

Keep the original full-subquestion reranking engine unchanged, alternating text fallback and structural parsing per question for 64 queries total. This isolates structural parsing without combining gains from the new fast engine.

| Repository | Queries per mode | Text coverage | Structure coverage | Complete queries, text / structure |
| --- | ---: | ---: | ---: | ---: |
| Cobra | 8 | 80.83% | 85% | 4 / 4 |
| Commander | 8 | 100% | 100% | 8 / 8 |
| esbuild | 16 | 81.25% | 81.25% | 12 / 13 |

Cobra gains help-handling evidence in both languages but loses one English context-inheritance unit. esbuild recovers platform-dependency writeback in both languages, while the Chinese Make test-entry task regresses. Structure can help but also changes retrieval and selection; relationship counts cannot replace per-task quality. Source, line numbers, budgets, and response hashes passed verification. See the [per-query comparison](results/js-go-retrieval-20261004.json).

## Compiler binding and configuration

`go/types` loads packages only from the verified snapshot, without running the repository, downloading modules, or starting an LSP service. Module paths come first from the snapshot root's `go.mod` and may also be supplied explicitly; without a module declaration, the internal name is `snapshot`. Type mode defaults to `linux/amd64`, with CGO disabled and no additional build tags. All files remain searchable, while type binding uses only non-test Go files for that target. Missing external packages preserve local bindings that can still be proved, with at most 20 diagnostics per file. Packages with duplicate declarations do not produce arbitrarily chosen bindings. Configure the default target in the snapshot:

```json
{"languageOptions":{"go":{"mode":"types","modulePath":"example.com/project","goos":"linux","goarch":"amd64"}}}
```

`goos` supports linux/darwin/windows/freebsd; `goarch` supports amd64/arm64/386/arm. Target configuration, toolchain version, and both helper sources participate in index identity. Nested modules and dependencies outside the snapshot are not loaded automatically. See the [official Go types API](https://pkg.go.dev/go/types).

Six added type-binding tests cover aliased imports, cross-package construction and receivers, generics, embedded methods, rejection of interface/callback bindings, platform selection, missing dependencies, and duplicate declarations. All 42 Python and 23 Node tests passed. Cobra/esbuild source spans remain identical; only relationships and diagnostics change, allowing reuse of index vectors for the same documents in subsequent comparisons.

## Final combination and default choice

Final new-corpus results combine fast retrieval and basic structural parsing. The comparison uses original full-subquestion reranking with text fallback from the section above; both changes affect the results.

| Repository | Original text coverage | Final default coverage | Final default median | Final default complete queries |
| --- | ---: | ---: | ---: | ---: |
| Cobra | 80.83% | 87.5% | 2.027 s | 5/8 |
| Commander | 100% | 100% | 2.767 s | 8/8 |
| esbuild | 81.25% | 84.38% | 2.426 s | 13/16 |

With the same fast engine, type relationships improve Cobra coverage from 87.5% to 91.67%, with complete queries rising from 5→6. esbuild falls from 84.38% to 81.25%, retaining 13 complete queries. The former recovers English help handling; the latter loses half the previously found evidence for the Chinese watch-lifecycle task. Therefore `syntax` remains the default, with `types` explicitly enabled when more precise static relationships are needed. No task-specific rules were added.

All 56 final-combination/type-comparison queries completed and passed source, line-number, hash, and budget checks. Type-mode index vectors reused original documents, with zero new embedding requests. After choosing defaults, validation confirmed every unit generated in explicit type mode matched evaluated units, and default syntax-mode retrieval fields also matched. See the [final comparison records](results/go-types-20261004.json) for results and the default choice. These small source-derived development sets retain per-task omissions.
