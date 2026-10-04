# Expanded evaluation omission diagnosis

2026-10-03. Inspect the four Chinese/English queries for Zod `safe-parsing` and HTTPX `multipart-upload`. This adds diagnostic records only; frozen questions, reference answers, retrieval engine, and original scores are unchanged.

## Findings

HTTPX's apparent omission comes from scoring blank lines as required evidence. The earlier report incorrectly interpreted it as missing business code. Zod is a real retrieval omission, primarily in initial candidate filtering and candidate retention after relationship expansion. Its relevant source was indexed correctly.

To locate the failing stages, a separate process reads the original index and runs the original queries with the original 4,000-token budget, adding only intermediate-variable recording before the frozen engine returns. All four diagnostic response SHA256 hashes match the formal evaluation byte for byte. The stage traces therefore explain the original outputs rather than infer causes from rewritten queries. This uses four embedding and eight rerank requests; diagnostic timings and scores are excluded from formal aggregates.

## HTTPX: two blank lines account for the 50% score

The original reference treats a continuous span across functions as one complete fact. The scorer at `src/eval/evidence.mjs:85` requires every line in that span, while the structural index requires coverage of all nonblank source lines.

| Fact scored as missing | Only unreturned line | Actual content |
| --- | --- | --- |
| Field conversion and individual serialization | `httpx/_multipart.py:257` | Blank line between `_iter_fields` and `iter_chunks` |
| File headers and file-chunk output | `httpx/_multipart.py:218` | Blank line between `render_data` and `render` |

Both languages retrieve, rerank, and select seven relevant method units, including `FileField.render_data`, `FileField.render`, `MultipartStream._iter_fields`, and `MultipartStream.iter_chunks`. All required nonblank source lines are returned. Only the blank lines make the two facts incomplete. Under nonblank-source scoring, both language variants should score 100%, matching ACE.

Applying a uniform diagnostic that ignores only missing blank lines to all 120 original responses changes only these two queries. Diagnostic OpenContextEngine coverage is **91.81%**, with complete retrieval on **50/60 (83.33%)**; ACE remains **85.69%** and **40/60 (66.67%)**. This is explicitly marked diagnostic rescoring. Original `scores.v1.json` and frozen **90.14% / 48/60** results are retained. Formal adoption should version the protocol and rescore all systems consistently rather than credit only one system.

## Zod: indexed key code never reaches final candidates

Required evidence spans four units totaling about 362 tokens by the engine's unit-cost measure:

| Unit | ID | Source lines | Chinese trace | English trace |
| --- | ---: | --- | --- | --- |
| `handleResult` body | 324 | `src/types.ts:98–106` | Selected | Selected |
| `handleResult.error` getter | 325 | `src/types.ts:107–112` | Found by relationship expansion; rank 104 before retention, then cut | Never enters candidate set |
| `ZodType.parse` | 368 | `src/types.ts:241–245` | Found by relationship expansion; rank 109 before retention, then cut | Never enters candidate set |
| `ZodType.safeParse` | 369 | `src/types.ts:247–266` | Found by relationship expansion; rank 110 before retention, then cut | Never enters candidate set |

**For Chinese, relationship-expanded candidates are cut again.** The first dense/BM25 fusion pool lacks three key units. Static relationship expansion finds them, but they have no first-wave reranking scores and their original fusion scores are 0. Retention filters on existing scores and removes them before second-wave model scoring. The second-wave model never sees and rejects this code.

At `src/retrieval/batched.py:81–84`, retention takes the top 64 candidates, adds the 16 expanded candidates with the highest fusion scores, then deduplicates. All 16 additions already occur in the top 64, so no new unit is added. Although there are 118 candidates and 65 expanded units, only 64 reach the second wave. The getter, parse, and safeParse rank 54, 62, and 63 within expansion, outside the added range.

**For English, the omission occurs earlier.** Three key units do not reach the 28 fused first-wave candidates for each subquestion. The `handleResult` body is retrieved, but its best first-wave rank in a relevant pool is 7, while expansion uses only the top 3 seeds per pool. It therefore does not bring in the getter or related entry points. `safeParse` is related to the selected seed `ParseContext`, but that seed expands only the 10 neighbors with highest fusion scores, excluding `safeParse`. This query also retains only 64 units.

Two factors amplify the problem:

- The TypeScript adapter splits the nested `get error()` into its own unit. Finding the body does not provide complete failure-result construction without another unit, creating a gap between partial function retrieval and complete evidence.
- Chinese regex splitting discards clauses shorter than 8 characters, so the clause asking how errors are aggregated does not become a separate subquestion. English retains the equivalent subquestion and still fails, so this is not the sole cause.

The 0% score means none of the three facts is completely satisfied, not that no related code is found. The success-result branch is returned, but error construction, parsing entry points, and context creation remain missing. This occurs before final token packing; increasing the output cap alone cannot restore discarded candidates.

## Directions for subsequent validation

This diagnosis does not change the algorithm. Prioritize bounded checks: ignore blank lines in scoring; make relationship-expansion slots actually add unretained candidates and use relationship types such as calls and containment; inspect semantic completeness of short methods and nested getters. Avoid materially slowing the service by expanding all candidates or adding reranking rounds. These directions have not yet been tested after implementation and do not guarantee recovery of Zod scores.

## Evidence

- [Four-query stage summary and original-output equivalence](results/expanded-stage-diagnosis-20261003.json)
- [Blank-line diagnosis across all 120 queries](results/expanded-blank-line-diagnostic-20261003.json)
- Full stage records and source units: `.pilot-state/expanded-v1/diagnostics/`.
- Capture scripts: `scripts/diagnostics/retrieval-stages.py` / `.mjs`; archived original harness: `.pilot-state/expanded-v1/diagnostic-harness.tar.gz`.
