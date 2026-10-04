# Cross-repository first-search evaluation: Click, HTTPX, and Zod

2026-10-03; frozen version `expanded-v1`. This adds 30 natural-language tasks and 95 source-evidence units, each queried once in Chinese and English: 60 queries per system, 120 total. The earlier ten Django tasks used for development tuning are excluded from these aggregates.

> Diagnostic correction: the two HTTPX upload results scored at 50% lack only blank lines between functions; all business-code evidence was returned. The earlier interpretation as missing code was inaccurate. This report retains frozen scoring. See the [omission diagnosis](EXPANDED_DIAGNOSIS.md) for the cause and uniform diagnostic rescoring. The Zod parsing entry point is still a real retrieval omission.

## Main metrics at 4,000 tokens

Required evidence coverage counts a fact only when all required source lines are actually returned. Facts are equally weighted within tasks, tasks within repositories, and repositories overall. Complete-retrieval rate requires every annotated fact for the query.

| Repository | OpenContextEngine Chinese | ACE Chinese | OpenContextEngine English | ACE English |
| --- | ---: | ---: | ---: | ---: |
| click | 97.50% | 88.33% | 100.00% | 95.00% |
| httpx | 85.00% | 76.67% | 85.00% | 76.67% |
| zod | 86.67% | 87.50% | 86.67% | 90.00% |
| Overall | 89.72% | 84.17% | 90.56% | 87.22% |

| Overall metric | OpenContextEngine | ACE |
| --- | ---: | ---: |
| Evidence coverage (both languages) | 90.14% | 85.69% |
| Complete-retrieval rate | 80.00% | 66.67% |
| Complete-evidence queries | 48/60 | 40/60 |
| Successful queries | 60/60 | 60/60 |
| Median client query time | 3.76 s | 2.15 s |
| Client query P95 | 5.94 s | 3.16 s |

Across 60 matched query comparisons, OpenContextEngine coverage wins / ties / losses are **15 / 40 / 5**. Chinese and English variants come from the same 30 tasks and are not 60 independent samples. Medians average the middle two values; P95 uses nearest-rank.

## Interpretation and confirmed omissions

Under this run's frozen 4,000-token scoring, OpenContextEngine leads overall by 4.44 percentage points, driven by Click and HTTPX. Zod averages 86.67% across languages, below ACE's 88.75%. ACE's median query is about 1.75 times faster. The architecture works across the added languages, with local retrieval-quality gaps.

- Zod `safe-parsing`, both languages: OpenContextEngine 0%, ACE 100%. Original context includes internal validation spans for several types but misses the required parsing entry point, context construction, and result wrapper.
- HTTPX `multipart-upload`, both languages: frozen scores are OpenContextEngine 50%, ACE 100%. Later diagnosis found only two missing blank lines, with business code fully returned. See the correction above.
- Zod `tagged-union`, Chinese: OpenContextEngine 66.67%, ACE 100%, missing tag-map construction.
- OpenContextEngine also misses some cookie, proxy-matching, decoding, and atomic-write evidence. Not every omission loses to ACE; per-query details are in the machine-readable summary.

ACE's original responses average about 5,461 tokens with 94.58% evidence coverage; OpenContextEngine averages about 3,631 tokens with 90.14% coverage. Equal-budget metrics show better evidence retention within limited context in this run, not more complete overall candidate recall. Separate ablations are still needed to distinguish recall, reranking, and budget-selection contributions.

After this run, only scoring and source verification were performed. Parameters were not adjusted for these omissions, and queries were not rerun to select better scores.

## Scope and frozen conditions

| Repository and version | Commit | Source files | OpenContextEngine units |
| --- | --- | ---: | ---: |
| click 8.1.8 | `934813e4d421071a1b3db3973c02fe2721359a6e` | 16 | 598 |
| httpx 0.28.1 | `26d48e0634e6ee9cdc0533996db289ce4b430177` | 23 | 583 |
| zod v3.24.2 | `e30870369d5b8f31ff4d0130d4439fd997deb523` | 13 | 1152 |

Both systems use the same production-source subsets: Click `src/click`, HTTPX `httpx`, and Zod `src`, excluding tests, examples, benchmarks, documentation, and dependencies. The 52 files total 826,815 bytes. Questions do not directly supply file or function names; language order alternates by task.

Configuration was frozen before querying: `batched-dag-v4`, `structural-units-v2`, Qwen3-Embedding-4B, Qwen3-Reranker-4B, two batch-reranking waves (batch size 32, batch token budget 8192), and no cross-query cache. Python and TypeScript share the retrieval pipeline; all models run on remote GPUs. ACE uses `DirectContext.search` from `@augmentcode/auggie-sdk@0.2.0`. No agent or external query rewriting was added.

ACE requests `maxOutputLength: 40000`, with actual outputs archived. Both systems preserve original result order and use `cl100k_base` for the 4,000-token cap, including paths and line numbers. Excess output is truncated and incomplete trailing lines removed. References do not influence snippet selection. OpenContextEngine selects within 4,000 tokens online.

Source, questions, answers, and engine are recorded with SHA256 hashes. Codex wrote tasks and reference evidence from source before querying; this run did not revise answers or tune the engine based on outputs. This is internal expanded validation on new repositories, not independent third-party annotation, blind testing, or a public held-out set. The three libraries are small and well known; results do not establish behavior on large unfamiliar projects.

## Latency and indexing

Both systems receive requests from the same Mac, serially within each system. Their execution periods overlap, with independent backends. OpenContextEngine uses authenticated SSH forwarding, while ACE accesses its official API. Hardware, deployment, and output lengths differ, so timings describe these deployments rather than isolate algorithm performance. Indexing and querying are timed separately with resident models; concurrency and model cold starts were not measured.

| Repository | OpenContextEngine query median / P95 (s) | ACE query median / P95 (s) | OpenContextEngine initial index (s) | ACE upload and index (s) |
| --- | ---: | ---: | ---: | ---: |
| click | 4.37 / 6.09 | 2.19 / 3.30 | 17.79 | 125.95 |
| httpx | 3.85 / 5.60 | 2.10 / 2.98 | 16.88 | 124.86 |
| zod | 3.26 / 4.21 | 2.17 / 2.73 | 32.58 | 5.52 |

After initial indexing, OpenContextEngine restarted because the new deployment lacked the TypeScript compiler. Installing the pinned dependency allowed Python index reuse and Zod completion. This preceded formal queries and did not change the frozen algorithm. The table uses initial-build timings retained in index metadata. ACE reported every file as newlyUploaded for all three repositories. Index latency includes different upload and polling processes and cannot directly measure parser or GPU performance differences.

## Supplementary budgets and output checks

| Output-prefix budget | OpenContextEngine coverage | ACE coverage |
| --- | ---: | ---: |
| 2000 | 85.00% | 42.78% |
| 4000 | 90.14% | 85.69% |
| 8000 | 90.14% | 94.58% |

The 2,000/8,000 results score offline prefixes of the same original responses. OpenContextEngine's original request budget remains 4,000, so the 8,000 setting does not represent both systems retrieving independently at an 8,000-token budget.

| Original-output diagnostic | OpenContextEngine | ACE |
| --- | ---: | ---: |
| Mean original-response tokens | 3630.7 | 5461.4 |
| Original-response evidence coverage | 90.14% | 94.58% |
| Numbered lines mismatching frozen source | 0 | 6 |

All 6 ACE line mismatches are partial lines at actual response ends truncated by the character limit; none scored. At the primary 4,000-token budget, both systems have 0 mismatches. These are not 6 instances of fabricated source.

Original response lengths differ, so original-response coverage is diagnostic and does not replace the equal-budget metric. Unannotated code is not automatically irrelevant; full precision was not measured. ACE supplied no billing data suitable for cost calculation, so costs are not estimated.

## Archives and review

- Frozen inputs: `eval/expanded-v1/{click,httpx,zod}`; frozen engine: `eval/expanded-v1/engine-freeze.json`.
- The [machine-readable summary](results/expanded-comparison-20261003.json) includes per-query differences, omissions, report/scoring hashes, and original run directories.
- The [completeness audit](results/expanded-audit-20261003.json) checks frozen files, source, remote index identities, engine hashes, 120 original responses, and OpenContextEngine's budget and lack of query caching.
- Run: `node scripts/expanded/ace.mjs click|httpx|zod` and `node scripts/expanded/opencontextengine.mjs click|httpx|zod`. The former calls the subscription API; the latter requires authorized remote services and SSH forwarding.
- Offline scoring: `node scripts/expanded/score.mjs RUN_DIRECTORY`; summary: `node scripts/expanded/summarize.mjs SIX_RUN_DIRECTORIES`; audit: `python3 scripts/expanded/audit.py SIX_RUN_DIRECTORIES`.

Original run directories:

- `runs/ace-click-expanded-2026-10-03T15-32-08.412Z`
- `runs/ace-httpx-expanded-2026-10-03T15-35-01.321Z`
- `runs/ace-zod-expanded-2026-10-03T15-37-49.629Z`
- `runs/reponerve-click-expanded-2026-10-03T15-32-00.397Z`
- `runs/reponerve-httpx-expanded-2026-10-03T15-33-33.211Z`
- `runs/reponerve-zod-expanded-2026-10-03T15-34-56.318Z`
