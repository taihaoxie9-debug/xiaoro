# Product Knowledge Coverage Closure

## Verdict

- Demo content closure: **GO**
- Strict production release: **NO_GO**
- Tested code commit: `954f62d`
- Final real-evidence commit: `1eae587`

This closes the current Demo product-knowledge and general-knowledge content
scope. It does not claim that every catalog product has complete reviewed
facts, or that the runtime is approved for strict production release.

## Product Evidence Gate

- ProductEvidence manifest SHA-256:
  `ca5cee9dc0e70e64f3e30b2faf7aed35d45fae45272a299c540bfb79d071b351`
- Evidence rows: 1,262
- Accepted `answer` rows: 1,079
- Exact answer rows in Top 5: 1,079 / 1,079
- Non-answer rows: 183
- Non-answer selections: 0
- FAQ rows: 47 across 12 categories
- FAQ direct questions in Top 5: 47 / 47
- FAQ natural rewrites in Top 5: 47 / 47
- Cross-product selections: 0
- Wrong-variant selections: 0
- Answer coverage failures: 0
- Deterministic mismatches: 0

## Catalog Coverage

- Canonical products: 103
- Products with ProductEvidence: 86
- Products with Category Facts: 92
- Union-covered products: 98
- Already available: 97
- Catalog cleanup: 3
- Honest unknown: 3

Catalog identity cleanup remains explicit:

- PID 26: `无` (`placeholder`)
- PID 90: `理肤泉` (`underspecified`)
- PID 100: `000` (`placeholder`)

Valid products with no ProductEvidence or Category Facts remain honest
unknowns:

- PID 60: `灵芝焕能强韧精华水`
- PID 72: `雅诗兰黛特润修护肌活精华眼霜15ml`
- PID 93: `怡丽丝尔优悦活颜眼唇抚纹精华霜15g`

The five products outside union coverage are PIDs 60, 72, 90, 93, and 100.
No identity or missing fact was guessed.

## General Knowledge Regression

- Reviewed topics/sources: 22
- Deterministic cases: 28
- Recall@3: 1.0
- Wrong-topic citations: 0
- Wrong-section citations: 0
- Entity coverage failures: 0
- Relation coverage failures: 0
- Deterministic mismatches: 0

ProductEvidence remains isolated from general knowledge. A single-product
merchant statement cannot become a general skincare conclusion.

## Real Runtime Acceptance

Both runs used the real DeepSeek provider, backend, SSE stream, production
frontend, DOM validation, screenshots, network capture, and console capture.

| Run | Trajectories | Turns | Passed | All error counters |
|---|---:|---:|---:|---:|
| `real-run-01` | 8 | 9 | 9 | 0 |
| `real-run-02` | 8 | 9 | 9 | 0 |

Validated scenarios cover core ingredients, FAQ paraphrase, version
difference, packaging/storage, current-item follow-up, multi-aspect answers,
honest no-evidence output, and fail-closed safety wording.

Evidence:

- `docs/audits/product-knowledge/coverage-closure/real-run-01/`
- `docs/audits/product-knowledge/coverage-closure/real-run-02/`

## Regression Results

- Focused product-knowledge suite: 319 passed
- Architecture and anti-patch suite: 196 passed
- Full pytest: 9,383 passed, 5 existing warnings
- `compileall app tools`: passed
- `git diff --check`: passed

The full suite includes historical Task11 tests whose evidence files are
intentionally not versioned in this worktree. Existing artifacts from the
read-only sibling Task11 worktree were copied temporarily for those tests and
removed afterward. No historical audit directory was added to this branch.

## Boundaries Preserved

- Raw `qa_facts` were not imported.
- No text-vector retrieval path was added.
- No second dispatcher or second ProductEvidence retriever was added.
- The model does not select evidence IDs.
- ProductEvidence does not enter GeneralKnowledgeRetriever.
- `answer`, `compare`, `rank`, and `safety` permissions remain separate.
- Missing reviewed facts remain explicit unknowns.
- Sentence, product-ID, evidence-ID, and case-ID production patches remain
  prohibited by the architecture gates.
