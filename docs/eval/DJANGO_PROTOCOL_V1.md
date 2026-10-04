# Django Chinese semantic-search pilot protocol v1

This run evaluates code-evidence coverage from a single natural-language search. Chinese is the primary result, with equivalent English queries as the paired comparison. The 10 independent development tasks produce 20 queries, not 20 independent tasks. This initial protocol covers ACE only; subsequent open-source tools and OpenContextEngine use the same scope, questions, and budgets.

## Frozen inputs

| Item | Setting for this run |
| --- | --- |
| Repository | `django/django` |
| Source revision | `f59aef2ee9b5c988fd4179d8f2835030bd76297c`, pinned from `stable/5.2.x` |
| Index scope | All 883 `django/**/*.py` files at that revision, totaling 5680101 bytes |
| Exclusions | Tests, documentation, templates, translations, static assets, and OpenContextEngine evaluation material; production Python files are not filtered by task relevance |
| Tasks | Login, routing, middleware, transactions, CSRF, page caching, settings, uploads, signals, and class-based view permissions |
| Reference answers | Codex read the frozen source for each task before this run's ACE queries and annotated 40 required facts with code evidence |
| ACE interface | `@augmentcode/auggie-sdk` 0.2.0, `DirectContext.search()`, maximum requested response of 40000 characters (actual lengths are reported in the results) |
| Query order | Sequential by task, alternating which language runs first; each language variant runs once, without agent follow-up or an answer model |
| Primary budget | 4000 tokens; supplementary budgets of 2000 and 8000 tokens |
| Tokenizer | `js-tiktoken` 1.0.21 with `cl100k_base`; character counts are not treated as token counts |

English queries add no symbols, paths, or solution hints absent from the Chinese version. Both languages share the same reference answers. Tasks represent everyday semantic code location, including simple single-file cases and necessary cross-file connections; they need not avoid all common business terms in the source. The protocol, questions, answers, file manifest, and implementation hashes were recorded in [freeze.json](../../eval/django-v1/freeze.json) before the first request.

## Reference answers and scoring

Readable facts and source links are in [reference answers v1](DJANGO_REFERENCE_V1.md); exact spans, source text, and hashes are in [answers.v1.json](../../eval/django-v1/answers.v1.json). Each task has several required facts, each potentially supported by multiple equivalent evidence alternatives. An alternative may require several spans together. v1 uses implementation spans verified for this run. Newly discovered equivalent alternatives require a versioned revision rather than a silent scoring change.

Preserve each response's original order and text, counting paths, line numbers, and other metadata against the budget. Take the first B tokens and remove any incomplete trailing line. Do not select or reorder snippets using reference answers. Code beyond the budget is not added back into the scored prefix. Also retain a diagnostic score for the original response without local token truncation, distinguishing missing returned evidence from budget truncation.

Compare every returned numbered code line with the frozen source. Unknown paths, incorrect line numbers, and rewritten or truncated code do not count as valid evidence. A fact is covered when every required code line of any equivalent alternative appears. Facts have equal weight. Correct paths, symbol names alone, or scattered keywords do not replace code evidence.

`Coverage@B = covered required facts / total required facts for the task`

Compute coverage per task, then average equally across the 10 tasks, separately for Chinese and English. Omission rate is `1 - Coverage@B`; complete-retrieval rate is the proportion of tasks with all facts covered. List missing facts per task, not just aggregate scores. Report the English mean minus the Chinese mean in percentage points as a description of this paired query set, without claiming statistical significance or a universal language gap.

Automated scores strictly measure coverage of this version's preannotated source evidence, not completeness over every possible answer. If later source review finds equivalent evidence or annotation errors, publish a new answer version, retain old scores, and rescore all groups' saved original responses consistently. Answer-only revisions usually do not require another ACE run.

Unannotated returned code is not automatically irrelevant, so tokens outside reference spans are not reported as a noise rate. Irrelevant-content proportions require a separate relevance review. Report observed query time, returned tokens, and failures; monetary cost remains unknown when the SDK does not provide billing data.

## Failures and execution limits

The full run is capped at 600 seconds, indexing at 240 seconds, each logical query at 60 seconds, and each HTTP request at 45 seconds. Allow at most 160 HTTP requests, including at most 24 retrieval requests. Limited SDK retries for retryable server failures are allowed, but retries are bounded. Record any logical query failure and stop subsequent queries. Failed and unexecuted tasks count as zero coverage in the planned-task denominator and are also reported separately; they cannot be removed to report successful tasks only.

Requests target only the official tenant's indexing and retrieval endpoints. Do not call `searchAndAsk()` or chat endpoints, or upload reference labels. Credentials come from the user's existing local session; run records contain no tokens or tenant addresses. Save each response immediately, retaining completed results even if the full run times out.

## Reproduction and offline analysis

Obtain the matching Django commit, then run:

```sh
npm ci
npm run prepare-django -- /absolute/path/to/django
npm test
npm run ace-django -- --dry-run
```

`--dry-run` checks file and label hashes, source scope, dependencies, and execution limits without network requests. After local `auggie login`, this command calls ACE:

```sh
npm run ace-django
```

Logs print the local run directory. Score existing results without contacting ACE again:

```sh
npm run score-django -- runs/ace-django-TIMESTAMP
```

The run directory stores frozen inputs, index status, request status and timings, and 20 original responses. Scoring adds response prefixes and per-fact scores for each budget. `runs/` is excluded from Git and requires separate backup for long-term retention. This pilot did not automatically upload or publish its records. Django reference source retains its [license](../../eval/django-v1/DJANGO_LICENSE.txt).

This is a development pilot without a held-out set, repeated runs, or independent multi-annotator labeling. It cannot establish broad superiority over another tool. Multi-turn agent performance is outside this run's scope.

## Reference-answer revision after execution

The frozen protocol and v1 inputs remain unchanged. A post-query review of the routing task on 2026-10-03 produced [reference answers v2](../../eval/django-v1/answers.v2.json), removing only the view-execution requirement that exceeded the question's scope and retaining v1 scores. Use `npm run score-django -- runs/ace-django-TIMESTAMP answers.v2.json` to rescore the same original responses offline. See [results and revision rationale](DJANGO_ACE_RESULTS.md).
