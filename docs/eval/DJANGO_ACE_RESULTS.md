# Django ACE first-run semantic-search results

2026-10-03. Official ACE SDK `@augmentcode/auggie-sdk` 0.2.0, `DirectContext.search()`. Frozen Django commit `f59aef2ee9b5c988fd4179d8f2835030bd76297c`; all 883 production Python files indexed (5680101 bytes). Each of 10 independent development tasks was queried once in Chinese and once in English: 20 successful queries. Chinese is the primary result, with English as the paired comparison.

This was an ACE-only development pilot; the OpenContextEngine engine and open-source tools had not yet entered the comparison. Scores measure preannotated source-evidence coverage, not natural-language answer accuracy. See the [protocol](DJANGO_PROTOCOL_V1.md) for tasks, scope, and budgets.

## Main results and budget sensitivity

The table uses revised reference answers v2, averaging tasks equally. A fact counts only when all required source evidence appears. Response prefixes preserve the original ranking, and paths and line numbers count against the token budget.

| Token budget | Chinese coverage | English coverage | Complete Chinese tasks | Complete English tasks |
| --- | --- | --- | --- | --- |
| 2,000 | 66% | 60.17% | 3/10 | 2/10 |
| 4,000 | 86.5% | 84% | 5/10 | 5/10 |
| 8,000 | 88.5% | 88.5% | 5/10 | 5/10 |

At 4,000 tokens, the reference-evidence omission rate is 13.5% for Chinese and 16% for English, a Chinese lead of 2.5 percentage points. Both reach 88.5% at 8,000 tokens. Original responses contain only 4,331–5,057 tokens, so the 8,000-token score includes all returned content; it does not mean ACE performed additional retrieval at that budget. One run, one repository, and 10 development tasks do not support statistical significance or a general language advantage.

| Task | Chinese covered facts / total | English covered facts / total |
| --- | --- | --- |
| Web login | 4/5 | 4/5 |
| Route loading and matching | 4/4 | 2/4 |
| Middleware execution | 3/4 | 3/4 |
| Transactions and nesting | 3/4 | 4/4 |
| Form CSRF validation | 3/5 | 3/5 |
| Page caching | 4/4 | 4/4 |
| Project settings loading | 3/3 | 3/3 |
| Upload memory and disk handling | 4/4 | 4/4 |
| Signal dispatch and exceptions | 3/4 | 3/4 |
| Class-based view permissions | 3/3 | 3/3 |

## One reference-answer correction

The v1 answers frozen before retrieval scored **84%** in Chinese and **81.5%** in English at 4,000 tokens, with complete coverage on 4/10 and 5/10 tasks respectively. The [original scores](../../eval/results/django-ace-20261003/scores.v1.json) are retained unchanged.

Post-run manual review found that `routing/request-to-view` required code that actually executes the view, while both questions asked only how routing configuration is loaded and how a path is matched to a view. v2 removes the out-of-scope `base.py:181, 197` requirements and retains path resolution and matching results at `313–315`. The task count and 40 facts are unchanged; the other 39 facts are retained as written.

This correction followed inspection of ACE outputs and was not blind review. Both languages were rescored offline with the same version, without rerunning retrieval; subsequent tools must use that same version. Both gain 2.5 percentage points at 4,000 tokens. See the [original v1 answers](DJANGO_REFERENCE_V1.md), [answers.v2.json and revision rationale](../../eval/django-v1/answers.v2.json), and [per-fact v2 scores](../../eval/results/django-ace-20261003/scores.v2.json).

## Evidence still missing

| Task | Review of original responses and budget prefixes |
| --- | --- |
| Login | Both languages find the form, backend dispatch, password checks, and session writes; the default backend's account-eligibility condition is missing. |
| Routing | Chinese is complete under v2. The original English response includes URL-pattern loading beyond 4,000 tokens; required recursive-matching evidence is incomplete even in the original response. |
| Synchronous middleware | Both find chain construction and request-hook short-circuiting. Evidence for whether synchronous view middleware continues to the view after returning a response is incomplete; the asynchronous branch cannot replace the requested synchronous branch. |
| Transactions | English is complete. Chinese misses autocommit restoration after exit, while the main commit, rollback, and nesting evidence is present. |
| CSRF | Both miss complete evidence for when the execution entry point applies Origin/Referer checks. Token-validation rejection is covered in the original responses but cut off by the 4,000-token prefix. |
| Signals | Both find registration, normal sending, and robust exception handling; complete sender filtering and dereferencing of live receivers are missing. |

An uncovered fact does not mean the entire feature was missed or that the returned context cannot support a reasonable answer. This uses a versioned, strict source-span coverage standard. References may still omit equivalent implementations or be overly detailed, requiring further versioned corrections. Unannotated code is not automatically irrelevant, so no noise rate is reported.

## Timing, response truncation, and cost

- Indexing took 99.421 seconds; 20 queries totaled 58.535 seconds; the full run took 157.979 seconds.
- Median query time was 2.824 seconds, ranging from 2.301–4.497 seconds.
- All 39 HTTP requests returned 200, including 20 retrieval requests. No retrieval retry was observed.
- The requested response cap was 40,000 characters; actual responses contained 19,027–20,000 characters. The last numbered source line was truncated in 7 original responses. The scorer rejected these incomplete lines; other numbered lines matched the frozen revision. This records the observation without attributing the limit to the server or SDK.
- The SDK supplied neither billing amounts nor billed tokens for this run. The token counts above measure returned text locally and do not represent billed usage.

## Retention and reproduction

The local original directory is `runs/ace-django-2026-10-03T09-25-00.710Z/`, containing 20 original responses, frozen inputs, both score versions, budget prefixes, and SDK index status. The publishable [run statistics](../../eval/results/django-ace-20261003/report.json) contain no credentials or tenant addresses. Original responses and index status remain in the ignored local directory.

The local archive `runs/archives/django-ace-20261003.tar.gz` includes frozen production source, the Django license, queries, protocol, both answer and score versions, original responses, runtime implementation, and the current scorer. A per-file SHA256 manifest and an external SHA256 file verify archive integrity. Credentials and SDK index status are excluded. The archive is stored only on this machine, without a backup on another machine.

```sh
# The default uses frozen v1 answers in the run directory; select v2 explicitly below.
npm run score-django -- runs/ace-django-2026-10-03T09-25-00.710Z answers.v2.json
```

Scoring reads only local frozen source and saved responses, without contacting ACE. All 14 tests passed, covering complementary spans, equivalent evidence, fabricated source, budget truncation, duplicate returns, and existing SDK integration. Subsequent open-source comparisons should use the same 883 files and 10 paired tasks rather than changing questions first.
