# Guide Phase 3A Final Handoff

## Status

- Phase 3A status: `COMPLETE`
- Round: `9`
- Production code checkpoint:
  `af1faf41ff6f91caa97611a312b154fbadd0f7fd`
- Documentation closure parent:
  `af1faf41ff6f91caa97611a312b154fbadd0f7fd`
- Documentation closure commit: `SELF` (the commit containing this handoff)
- Final audit disposition: `FINDINGS_CLEARED`; Round 9 incremental `PASS`
- Unresolved audit findings: `P0=0;P1=0;P2=0`
- Push, deployment, and traffic switch: not performed

## Task 14–22 Closure

| Task | Final source checkpoint | Closure |
| --- | --- | --- |
| 14 | `ffd41a4` | Candidate parsing is bound to the source bytes used for `source_sha256`; the exact replacement race is covered. |
| 15 | `95bc7ba` | Category-fact promotion recovers from post-swap directory fsync failure without returning failure against a changed production pointer. |
| 16 | `c854ba6` | Modified coordinated negation keeps the later negated category negative. |
| 17 | `966bedd`, `d568ce0` | Invalid text/image category payloads are rejected before conversation and feedback state commit. |
| 18 | `9bb991f` | Follow-up, revision, and image card flows preserve typed category facts. |
| 19 | `35120f5` | Explicit positive turns restore the intended later category without weakening double negation. |
| 20 | `2f21151`, `06d7ea5`, `be5263e`, `6dcb668`, `098be5a` | Conversation state commits only after validated terminal delivery; cancellation and real iterator-close paths do not commit. |
| 21 | `bee11b3` | All four required positive-turn variants pass understanding, planning, and formal routing. |
| 22 | `1088fd7` | Public products require deterministic whole-payload equivalence with typed `ProductCard` projections. |

## Category Foundation

The Guide defines exactly six profiles and maps all `39/39` Canonical raw
categories exactly once. Unknown categories fail closed.

| profile | Canonical products | pilot IDs | approved | unknown | conflict |
| --- | ---: | --- | ---: | ---: | ---: |
| `skincare` | 51 | `38, 91` | 0 | 18 | 0 |
| `suncare` | 12 | `53, 57` | 0 | 18 | 0 |
| `base_makeup` | 19 | `79, 80` | 0 | 20 | 0 |
| `color_makeup` | 6 | `86, 114` | 0 | 16 | 0 |
| `cleanser` | 12 | `69, 103` | 0 | 22 | 0 |
| `fragrance` | 3 | `120, 121` | 0 | 20 | 0 |

Production category facts remain:

```text
fact_count=0
approved=0
unknown=114
conflict=0
```

No candidate was automatically approved. No missing data field was inferred;
fields without approved evidence remain unknown.

## Data Hashes

Category production:

```text
manifest logical SHA-256:
08bd86a14c2b6caf727c89bf263ad018f10100a11b6f8d4b398e29c11fad187d
manifest raw SHA-256:
dc528a034779559e0ac9b6444f1b0365e3041478d71ebbc703da3aaaf0e6179c
facts raw SHA-256:
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
pilot report raw SHA-256:
282f6117a7a3c53d006c51f54eae1f963387d43ab61e4978e61be67adc636249
```

Category candidate fixture:

```text
pending=7
quarantine=12
approved=0
pending SHA-256:
a8e61b695be9961b8419f5410d33328174f8bd49d61a8b83c24a77b1b24ae842
quarantine SHA-256:
4241cff791fec04f87919d708d7373be742953a368bb26996d1d345983a7a474
```

Review production:

```text
approved sources=6
covered products=42,49,55
manifest logical SHA-256:
823c249166e93b4ab709b3423fa8a97a23e3ab3e7677e5d39d74abc21c165113
manifest raw SHA-256:
2d4acdb1251e1b65d2b92fb2b052734f58b56cd4cd558e783c0391432c630460
sources raw SHA-256:
22bac50e053a621826c831565b3a18e1df3592049ac35377298bac0ab0536171
audit raw SHA-256:
8172d6fbcf88c3c5b48e1a2f65e5698f2c8c7b4e0b61801ee9bc4bcb28a00a55
```

Review candidate fixture:

```text
pending=2
quarantine=4
approved=0
provenance_status=fixture_only
historical total/strict=336/111
historical status=not_rerun
pending SHA-256:
52ada19838518e3fa1f66cba719b224bce22efc9507928ea8d24f3060ed25cc5
quarantine SHA-256:
f6ea3e3f365095d95019875ea79cb20a6106246adfacd5652fd26382943077db
```

The six existing approved review sources and all production/candidate data
hashes are unchanged. Historical `336/111` remains provenance only and was
not rerun.

## Verification

Focused verification:

```text
candidate builder: 68 passed
exact candidate race nodes: 3 passed
final focused executions: 776
final focused failures: 0
composition: 574 + formal router 123 + exact runtime 79
```

Authoritative full verification:

```text
Guide full: 2619 passed, 1 existing Pydantic warning
Runtime full: 187 passed
Combined: 2806 passed
```

Evidence:

```text
/private/tmp/xiaoro-authoritative-full-final-098be5a/summary.txt
```

The authoritative environment was:

```text
/private/tmp/xiaoro-guide-runtime-venv/bin/python
Python 3.11.1
pytest 8.0.0
```

The locked `UV_OFFLINE` command could not obtain the missing Pillow `10.4.0`
CPython `3.12` arm64 wheel. That result is classified `ENVIRONMENT` and is
not claimed as a pass. The approved Python 3.11 environment completed the
authoritative full run.

Static and protection gates:

```text
compileall: PASS
app/guide boundary: PASS
app/guide_runtime boundary: PASS
git diff --check: PASS
protected diff from a29d727: empty
protected diff from a88d8af: empty
```

Ranking SHA-256 remains:

```text
4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f
```

Protected paths remain unchanged:

```text
app/services/**
app/database/**
data/canonical/**
app/guide/decision/deterministic_ranking.py
```

## Browser Evidence

Authoritative evidence root:

```text
/private/tmp/xiaoro-phase3a-authoritative-browser-098be5a
```

Results:

```text
shards=7/7
scenario classes=20/20
screenshots=10
page=0
console=0
SSE=0
server_transport=0
unexpected_http_5xx=0
image=0
cross_session=0
late=0
xss=0
```

Cancellation before the terminal ASGI `send()` left state rows=`0` and
target rows=`0`. A normal terminal response produced
`[feedback_target,end]` with matching version `1`. Server exception,
traceback, and `generator already executing` counts were all `0`. Task 21
variants passed `4/4`, and ports `19341–19347` were released.

Evidence hashes:

```text
manifest SHA-256:
5c9fa302ea2e6d16b2c75ff5616368e626bcae6a53601632af3cfd9029a97a8d
summary SHA-256:
896ed5f4fdba2919019742ea70cbba569f68af751df1779d2e275ed20083f3a1
```

## Final Audit

The unique `FINAL-CATEGORY-DATA-AUDIT` remains one invocation:

```text
checkpoint=5983350
audit key=1b3611b13ef377099ee008cdbcb30f950797fadc09d4b025a0fb24f44c6181c7
full-file invocations=1
```

It opened with `P1=1;P2=1`. Commit `4206f45` cleared both findings, and the
same full-file audit was not rerun.

A later independent incremental audit covered `6dcb668..098be5a`:

```text
report=/private/tmp/xiaoro_final_stage1_audit_098be5a/report.md
report SHA-256:
0035e75201667506f61d1408ab3af78f5ee02f8b8797380d32013aa6fe6f4789
result=no P0-P2
```

An earlier incremental audit found a post-send `P1`; `098be5a` fixed it.
Final unresolved findings are `P0=0;P1=0;P2=0`.

### Task 24 Scope Correction

The original 41-file manifest and audit key remain immutable historical
malformed-scope evidence. Its ledger row was not changed.

The corrected scope at checkpoint `5983350` contains 42 production files:

```text
scope manifest SHA-256:
9bd6fbef8072acfb770af95bdcead537a11e0c262ee85092c859ae177bdb14e1
audit key:
d88c16831e176cbc4b3445294a1d9fddf6ffcfd97eeafe3e04f451c1e595114e
review reader:
app/guide/retrieval/review_reader.py
Git blob:
4db1174c053b3fcb33aa1b7f4da9122969433467
file SHA-256:
2d15d42a5e5224567e930527abde2570741b0c13083790115d607fd8e1194a32
```

The production reference chain is `composition.py ->
build_review_evidence_reader -> load_approved_review_assets ->
ReviewEvidenceReader -> text/image flows`. Independent read-only targeted
verification passed `98` tests with `P0=0;P1=0;P2=0`,
`full_file_invocations=0`, and `targeted_reader_invocations=1`.

Task 24 is complete without a repeated full-file audit. Task 23 remains open,
so this evidence correction does not change the Round 8 `FAIL` disposition.

### Task 23 Incremental Audit Finding

The Task 23 candidate consists of formal-test commit `ae90462` and integration
fix `9751f95`. Domain commit `66be64d` has the same stable patch ID as
`9751f95`:

```text
6ee083a2914e3b3b022ae2f1c2c81fb223805d5c
```

The `ae90462` commit body preserves the initial formal HTTP/SSE RED as
`6 failed, 2 passed` on `4ee9fe0`. The current Integration Writer inspected
the commits and collected the eight new formal nodes, but did not rerun RED,
focused GREEN, formal router regression, compileall, or boundaries before the
independent incremental audit reported a new `P1`. A documentation-only
`git diff --check` passed after recording the finding.

The candidate connector expansion can over-propagate category negation across
an explicit positive predicate. Required RED/GREEN coverage is now Task 25:

```text
不考虑防晒并想买平价香水
不考虑防晒并推荐平价香水
不考虑防晒且想买平价香水
不考虑防晒并且推荐平价香水
```

These cases must restore positive fragrance intent through understanding,
task planning, and both formal message and SSE routes, without weakening
Task 23's pure coordinated-negation cases. The coordinator did not provide an
audit report path or hash, so none is asserted here.

Task 23 and Task 25 remain open. There is no Round 9 completion disposition.
Read-only checks found protected diffs from `a29d727` and `a88d8af` empty,
and ranking SHA-256 remains
`4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
This finding checkpoint changes documentation only; no business code, tests,
protected paths, or data assets were changed, and no push, deployment, or
traffic switch was performed.

### Task 26 Independent Read-Only Design Verification

An independent read-only design verification inspected frozen source
`ebed86efe23aa4921a6aa205349daa297adc8d05`, specifically the category
negation parser and its understanding, task-planning, and formal-route tests.
It produced three unresolved findings:

1. **P1 - Negative compounds/direct positive predicate boundary.** Direct
   `想买`, `想要`, `要买`, `推荐`, and `改买` after a conjunction must
   restore the later category. That expansion must not classify
   `并不想买`, `并非要买`, `想要避开的香水`, `推荐避雷香水`, or
   `想买但不买香水` as positive. Both sides require RED/GREEN coverage.
2. **P2 - Final repeated-category negation.**
   `不考虑防晒并改买香水但不要香水` must resolve as no positive fragrance
   intent. The last explicit negation must override the earlier positive
   fragrance occurrence.
3. **P2 - Missing formal HTTP positive coverage.** The existing formal
   coordinated-positive test exercises only `/api/v1/chat/stream`; Task 26
   must also cover `/api/v1/chat/message` and prove HTTP/SSE parity.

Task 26 records these requirements and depends on Task 25. Tasks 23, 25, and
26 remain unchecked. No focused, full, boundary, or browser run was performed
for this design-only verification, and no pass or completion disposition is
claimed. There is no standalone report path or hash. This checkpoint changes
documentation only; business code, tests, protected paths, and data assets
remain unchanged.

### Task 27 Incremental Audit Finding

The independent incremental audit inspected frozen candidate
`61171f029a4dceef7232f79b248660a04cd232b0`. Its understanding,
task-planning, and owner suites passed `452 passed in 2.37s`; a separate
12-case semantic matrix matched `7/12` required topic/task/owner outcomes and
mismatched `5/12`.

The matrix result was:

```text
4/4 explicit-positive controls:
  fragrance / recommend / guide_text (expected)
3/3 category-negation controls:
  no positive category / clarify / legacy (expected)
0/3 attribute-scope cases:
  no positive category / clarify / legacy (wrong; fragrance must remain)
0/2 final-"不推荐" cases:
  sunscreen or fragrance / recommend / guide_text
  (wrong; the final category negation must dominate)
```

The three attribute-scope mismatches are `避开甜腻的香水`,
`不要太甜的香水`, and `不想要太甜的香水`. The three negative controls
that must stay negative are `想要避开的香水`, `推荐避雷香水`, and
`想买但不买香水`. The two final-negation mismatches are
`推荐防晒但不推荐防晒` and
`不考虑防晒并改买香水但最后不推荐香水`.

The audit classified all three findings as P1:

1. **P1 - Attribute scope.** Broad category-negation cues consume attribute
   exclusions and incorrectly remove fragrance.
2. **P1 - `不推荐` symmetry.** Positive `推荐` is recognized, but final
   `不推荐` is not a corresponding category-negation cue, so the last
   repeated-category state remains positive.
3. **P1 - Missing formal HTTP/SSE evidence.** The candidate adds parser,
   task-planning, and owner tests, but
   `tests/guide/application/test_formal_chat_router_http.py` remains at blob
   `b648b3f331c5eabd34127557556bcce83bb92cbd`. Task 27 must add
   representative positive and negative RED/GREEN coverage to both
   `/api/v1/chat/message` and `/api/v1/chat/stream`.

Task 27 records scope-aware category negation and depends on Task 26. Tasks
23, 25, 26, and 27 remain unchecked. No full, boundary, or browser pass and
no Round 9 completion disposition is claimed. No standalone report path or
hash was supplied. This checkpoint changes documentation only; business code,
tests, protected paths, and data assets remain unchanged.

### Task 28 Independent Quantifier-Scope Audit Finding

The independent audit against frozen integration source
`0ee1002590a84973897b91365665e0cdef5870d9` reported one new P1:
category quantifiers and class demonstratives can be mistaken for the
attribute material that Task 27 must exempt from category negation.

The required category-negative controls are:

```text
不要所有的香水
避开全部的香水
排除这类的香水
拒绝这种香水
```

All four must remain fragrance-category negations and must not enter the
Guide. The fix must preserve Task 27's positive fragrance controls:
`避开甜腻的香水`, `不要太甜的香水`, and `不想要太甜的香水`.
Task 28 therefore requires understanding, task-planning, and owner-routing
RED/GREEN and depends on Task 27.

Formal `/api/v1/chat/message` and `/api/v1/chat/stream` evidence was not
executed for this checkpoint. The missing formal evidence is not a separate
new task; it remains part of the Tasks 25-27 integration, with the Task 28
cases added to the later unified formal matrix. No focused, formal, full,
boundary, or browser pass is claimed, and no standalone report path, report
hash, or test transcript is asserted.

Tasks 23, 25, 26, 27, and 28 remain unchecked with no completion
disposition. This checkpoint changes documentation only; business code,
tests, protected paths, and data assets remain unchanged.

### Task 29 Independent Quantifier/Constraint Audit Findings

The independent audit inspected frozen candidate
`d019dd2049901dd4fe76e5d4952d4c926235eec2`, including attribute-scope
predecessor `7779472932da3d9a502a5829dd8b782aeccc90e3`. The candidate's
understanding, task-planning, and owner-routing suites reported `581 passed`.
The supplied 14-case semantic matrix summary was 12-of-14 (`12/14`) matched
and `2/14` mismatched. The audit result was `P0=0;P1=2;P2=0`; no row-level
transcript, standalone report path, or report hash was supplied.

The two findings are:

1. **P1 - Incomplete category-quantifier synonyms.** `任意的`, `任何的`,
   `每一种的`, `每一款的`, and `一切的` must be normalized with Task
   28's existing quantifiers. Under each of `不要`, `避开`, `排除`, and
   `拒绝`, they must remain fragrance-category negations and must not enter
   the Guide.
2. **P1 - Silent loss of an attribute exclusion.** Restoring positive
   fragrance routing is insufficient if `避开甜腻的香水` or
   `不想要太甜的香水` reaches recommendation with only the category and
   drops the exclusion. The exclusion must survive in the existing authorized
   `ExclusionDraft`/`ExclusionConstraint` contract. If that contract does not
   authorize the property, the response must expose an explicit
   uncertainty/clarification and must not claim the constraint was applied.

Task 29 depends on Task 28 and requires understanding, task-planning, and
owner-routing RED/GREEN plus formal typed evidence for both
`/api/v1/chat/message` and `/api/v1/chat/stream`. The formal router test
remains at blob `b648b3f331c5eabd34127557556bcce83bb92cbd`, so `581 passed`
does not establish formal HTTP/SSE behavior.

Tasks 23 and 25-29 remain unchecked with no completion disposition. No full,
boundary, or browser pass is claimed. This checkpoint changes documentation
only; business code, tests, protected paths, and data assets remain unchanged.

### Task 30 Independent Consumed-Span Audit Findings

The independent read-only incremental audit inspected frozen candidate
`9f5cea0439ee3f78b074aceb28a9bdc3786a0c5f` over
`d019dd2..9f5cea0`, with regression range `9751f95..9f5cea0`. It reviewed
five files and reported 304 changed lines. The result was
`P0=0;P1=1;P2=1`. The report is
`/private/tmp/xiaoro_round9_task25_audit/report.md`, SHA-256
`197d350c5fd4c9f6eb624233ae11e24bb61d613403375a1acc339f9600c6be17`.

Read-only reproduction on the frozen candidate ran
`test_category_profile_parsing.py`, `test_task_planning.py`, and
`test_chat_api_adapter.py`; the focused result was
`1024 passed in 2.42s`. This evidence does not include formal HTTP/SSE:
`test_formal_chat_router_http.py` remains at blob
`b648b3f331c5eabd34127557556bcce83bb92cbd`.

The findings are:

1. **P1 - Nested negative unsupported attributes are re-consumed as the
   opposite ingredient exclusion.** For `避开不含酒精的香水`, the
   candidate emits Task 29's `unsupported_attribute_exclusion`, but
   `_parse_exclusions` separately extracts `酒精`. Planning then carries an
   `ExclusionConstraint("酒精")` into clarification, reversing “avoid
   alcohol-free perfume” into “exclude alcohol.” Text consumed as a category
   target or unsupported attribute must have span ownership and cannot be
   consumed again by generic exclusion parsing. Equivalent `不要`/`不想要`
   and `无酒精`/`无香精` forms must keep typed uncertainty/clarification
   without any ingredient exclusion.
2. **P2 - Category quantifiers leak non-domain exclusions.**
   `不要所有香水` and equivalent Task 28/29 quantifier forms remain
   category-negative, but `_parse_exclusions` can emit
   `ExclusionDraft("所有")`, which planning compiles to the same non-domain
   hard constraint. The full quantifier/class matrix must produce no
   `ExclusionDraft` or `ExclusionConstraint` for `所有` or its synonyms.

The positive control is `不要含酒精的香水`: it remains a normal ingredient
exclusion and must continue to produce the authorized alcohol
`ExclusionDraft`/`ExclusionConstraint`.

| Class | Representative text | Required formal result on both endpoints |
| --- | --- | --- |
| Unsupported nested negative attribute | `避开不含酒精的香水`; equivalent `不要`/`不想要` and `无酒精`/`无香精` forms | Guide typed clarification, fragrance retained, no products, and no ingredient Exclusion |
| Category quantifier/class target | `不要所有香水`; full Task 28/29 cue x quantifier x optional `的` matrix | legacy route, no Guide category profile/products, and no quantifier Exclusion |
| Ordinary ingredient exclusion control | `不要含酒精的香水` | Guide typed recommendation retaining the alcohol Exclusion and no unsupported-attribute uncertainty |

Task 30 depends on Task 29 and requires understanding, task-planning, and
owner-routing RED/GREEN plus a representative typed matrix for both
`/api/v1/chat/message` and `/api/v1/chat/stream`. Tasks 23 and 25-30 remain
unchecked with no completion disposition. No full, boundary, runtime, or
browser pass is claimed. This checkpoint changes documentation only; business
code, tests, protected paths, and data assets remain unchanged.

### Task 31 Ingredient-Exclusion Normalization Finding

The independent incremental audit inspected frozen candidate
`344e0e9e42740d4c19f839724d3f23570cd83568` over Task 30 candidate
`9f5cea0439ee3f78b074aceb28a9bdc3786a0c5f`, with regression range
`9751f95..344e0e9`. It reviewed two production files and reported 185
production changed lines. The result was `P0=0;P1=1;P2=0`. The report is
`/private/tmp/xiaoro-round9-task25-routing-audit/report.md`, SHA-256
`2a3d371c312bd830e59f5f74c46efa82c48bfc160058fb741c95d050bdefa5ff`.

Supplied candidate verification evidence reported `1354 passed` for the
focused understanding/planning/owner/decision-consumer coverage and
`191 passed` for formal coverage.

The new finding is:

1. **P1 - `不要有` keeps the existence predicate in the exclusion value.**
   `不要有酒精的香水` remains a positive fragrance attribute exclusion,
   but generic exclusion parsing consumes only `不要` and emits
   `ExclusionDraft("有酒精")`. Planning preserves the malformed value as
   `ExclusionConstraint("有酒精")`; a decision candidate containing
   `酒精` then returns `excluded_evidence_unknown` rather than
   `excluded_exclusion_match`. `不要有香精的香水` has the same required
   normalization boundary.

Task 31 must make the two primary inputs produce only the bare typed values:

```text
不要有酒精的香水 -> ExclusionDraft/ExclusionConstraint("酒精")
不要有香精的香水 -> ExclusionDraft/ExclusionConstraint("香精")
```

No leading `有`, `"有酒精"`, or `"有香精"` may survive. Parameterized
regression must preserve `不要含`, `不含`, `不能有`, and `无` forms for
both ingredients. Understanding, task planning, owner routing, and the
decision consumer each require RED/GREEN; the decision check must prove that
a candidate containing the excluded ingredient reaches
`excluded_exclusion_match`.

The unchanged formal router test blob is
`b648b3f331c5eabd34127557556bcce83bb92cbd` and contains no Task 31
representative. The supplied `191 passed` is therefore regression evidence,
not Task 31 closure. New representative verification is required on both
`/api/v1/chat/message` and `/api/v1/chat/stream`.

Task 31 depends on Task 30. Tasks 23 and 25-31 remain unchecked with no
completion disposition. No full, boundary, runtime, or browser pass is
claimed. This checkpoint changes documentation only; business code, tests,
protected paths, and data assets remain unchanged.

### Task 32 Nested-Absence Cartesian Audit Finding

The independent read-only incremental audit inspected frozen candidate
`76bdad3dea80e25a0ccc83960f9788b87bba8547` over Task 31 candidate
`344e0e9e42740d4c19f839724d3f23570cd83568`, with regression range
`9751f95..76bdad3`. It reviewed 10 files and reported 1335 changed lines.
The result was `P0=0;P1=1;P2=0`. The report is
`/private/tmp/xiaoro-round9-task25-audit/report.md`, SHA-256
`d36cd64226f4d6429293a371185034670d31ace6ba74489a5e2d5d93b529dfd1`.

Supplied candidate verification evidence reported `1438 passed` for the
focused understanding/planning/owner/decision suite, `131 passed` for the
formal router suite, and `35 passed` for the additional targeted matrix.

The new finding is:

1. **P1 - `不要有` bypasses nested-absence span ownership and reverses the
   exclusion.** Although ordinary `不要有酒精的香水` is now normalized
   correctly, `不要有不含酒精的香水` and
   `不要有无酒精的香水` produce fragrance plus
   `ExclusionDraft("酒精")`/`ExclusionConstraint("酒精")`, no typed
   uncertainty, and a recommendation. A product containing alcohol is then
   hard-excluded, reversing “exclude alcohol-free perfume” into “exclude
   alcohol.”

Task 32 must cover the complete Cartesian matrix:

```text
{避开, 不要, 不想要, 排除, 拒绝, 不要有}
× {不含, 无}
× {酒精, 香精}
× explicit category
```

Every nested-absence row must retain the explicit category, emit typed
`unsupported_attribute_exclusion`, clarify, and produce neither
`ExclusionDraft` nor `ExclusionConstraint`. The category dimension must be
frozen explicitly and include `香水` at minimum. Ordinary
`{不要有, 不要含, 不含, 不能有, 无}` plus either ingredient and a category
remains the positive control: it must emit only the bare ingredient exclusion,
and a candidate containing that ingredient must reach
`excluded_exclusion_match`.

Understanding, task planning, owner routing, and the decision consumer each
require Cartesian RED/GREEN. Both `/api/v1/chat/message` and
`/api/v1/chat/stream` require typed representatives that include the two audit
reproductions and collectively cover every matrix dimension; nested cases
must return clarification with zero products and no reversed exclusion.

Task 32 depends on Task 31. The reported `1438/131/35` results predate Task 32
coverage, and the unchanged formal router blob
`b648b3f331c5eabd34127557556bcce83bb92cbd` contains no Task 32
representative. Tasks 23 and 25-32 remain unchecked with no completion
disposition. No full, boundary, runtime, or browser pass is claimed. This
checkpoint changes documentation only; business code, tests, protected paths,
and data assets remain unchanged.

## Delivery Boundary

The server commit boundary is successful return from the terminal ASGI
`send()`. The browser commits its local snapshot only after EOF. There is no
client ACK, so network end-to-end exactly-once delivery would require a
future delivery ID plus ACK/query/retry protocol. This is a release remainder,
not an unresolved P0–P2 finding.

## Documentation Closure

This Round 7 closure changes only:

```text
.trae/specs/complete-category-aware-guide-data-foundation/tasks.md
.trae/specs/complete-category-aware-guide-data-foundation/checklist.md
.trae/specs/complete-category-aware-guide-data-foundation/progress.md
docs/audits/category-data-foundation/progress.md
docs/audits/category-data-foundation/final_handoff.md
```

Tasks and checklist are fully checked. Business code, protected paths, and
data assets are unchanged. No push, deployment, or traffic switch was
performed.

## Release Remainder

1. Add a delivery ID and ACK/query/retry protocol before claiming network
   end-to-end exactly-once delivery.
2. Obtain explicit authorization before push, deployment, or traffic switch.

## Round 9 Task 23 And 25-32 Integration Checkpoint

This non-release checkpoint starts at
`29db49771c3e50ea69f99321309d4060d7da4a4c` and freezes the final
production/test state at
`3981ff8a2f6aca96e59ff083e40b9994695daddd`. The shared formal TDD commit is
`7bba0e00b7ec327729e0b81964098ac54b172df6`, stable patch ID
`7e6cf9dc6c6ce29fd9665056cef98795c2a089cb`.

Task 23 baseline commits remain
`ae90462539f757d2160fe23323b19d1dd857e839` (formal tests, patch ID
`7c0534ffffb96181da008d7bb34981630a8bdf49`) and
`9751f95bda2bcc1b696b1581854d475220046cb6` (domain integration from
`66be64dd3a6fa43c14a22d8a68c5dee6768eeec5`, matching patch ID
`6ee083a2914e3b3b022ae2f1c2c81fb223805d5c`).

| Task | Source -> integration | Stable patch ID |
| --- | --- | --- |
| 25 | `0860312c53b0fabaedef228de1d4815b3d04f315` -> `e206242e8c9f52af6a0788e2c5f89c794711400c` | `877662ea25b775f56fe70e68400cc1e4be3f398a` |
| 26 | `61171f029a4dceef7232f79b248660a04cd232b0` -> `76b40af5f50d43d2eace661ac184d11863d81c7a` | `7ffffbc68b1b000504ad58e1d2bb021df4f9b0d0` |
| 27 | `7779472932da3d9a502a5829dd8b782aeccc90e3` -> `76f8b2fb4bd1b3594fe8ffad264e291dbb194fd2` | `9ff28a604a02fc938780406171dcf1fbaa3066b4` |
| 28 | `d019dd2049901dd4fe76e5d4952d4c926235eec2` -> `90d1624a4da8311a814ba5e5c5669aea06793194` | `e3b7dcb4c05b51a8e95a45842c4a0e20a5a7dcfe` |
| 29 | `9f5cea0439ee3f78b074aceb28a9bdc3786a0c5f` -> `eba513ff64e683d868a4ed041e240ecd686d5385` | `1a270f67b6ed935169ea59369b74ff7a72402359` |
| 30 | `344e0e9e42740d4c19f839724d3f23570cd83568` -> `afc52d34907446ecc7576d584e657e45e6ed402c` | `62548c8655d458e1a6c72fde325777e5b78160ee` |
| 31 | `76bdad3dea80e25a0ccc83960f9788b87bba8547` -> `660d85965c1717d241ce453dbdeec2593bd1dcaa` | `1645e418758fb279b0cc6a10f9cc78231e2a102e` |
| 32 | `b82e60089f3ea80d723fc524a7f62c3d64fdc9ec` -> `3981ff8a2f6aca96e59ff083e40b9994695daddd` | `3614632773d863a3237683982c4e799b54980890` |

All eight cherry-picks were conflict-free and source/integration stable patch
IDs matched.

### TDD And Verification

The new formal matrix runs `112` cases over both public endpoints and asserts
owner, typed fragrance profile, public products/card order where applicable,
and exactly one terminal outcome. It covers pure coordinated negation, the
full `5 x 4` positive predicate/connector equivalence classes, negative
compounds and last negation, typed unsupported-attribute clarification with
zero cards, legacy quantifiers, consumed-span ownership, bare ingredient
normalization through the real decision consumer, and Task 32 outer/inner
absence representatives.

```text
RED at 29db497: 72 failed, 40 passed
GREEN at 3981ff8: 112 passed in 13.42s
complete formal router file: 243 passed in 35.75s
final routing focused range: 1534 passed in 4.05s
contracts/presentation/decision: 337 passed in 1.06s
compileall: PASS
app/guide boundary: PASS
app/guide_runtime boundary: PASS
git diff checks: PASS
protected diff from a29d727: empty
protected diff from a88d8af: empty
```

RED and GREEN JUnit evidence:

```text
/tmp/xiaoro-round9-formal-red-29db497.xml
/tmp/xiaoro-round9-formal-green-3981ff8.xml
```

The final routing audit used profile `round9-routing-incremental-v1` over
`29db497..3981ff8`. Its two-file production scope contains Git blobs
`a04cd8a13109ea40293d9eb84e86ea23d0f0d71e` for
`contracts.py` and `3b900733effa97194a223b682885dc4a54a10279` for
`exact_parsing.py`. Scope manifest SHA-256 is
`0ef16e0438f27f63dcc6f2e0e18e4bf06662fede465b32bcb48e062f719e6ce4`;
the audit result is `P0=0;P1=0;P2=0`.

```text
scope=/tmp/xiaoro-round9-routing-audit-3981ff8/scope_manifest.txt
report=/tmp/xiaoro-round9-routing-audit-3981ff8/report.md
report SHA-256=5c0b99729cb9737d14d083a5d723f37ba8dd6806c0003a7ef715e98323b62b51
ranking SHA-256=4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f
```

Tasks 23 and 25-32 and their checklist rows are checked. This checkpoint does
not add a Round 9 final summary to `.trae` progress. No push, deployment,
traffic switch, protected-path modification, or automated approval occurred.

## Round 9 Final Handoff

The final product tree is frozen at
`af1faf41ff6f91caa97611a312b154fbadd0f7fd`. The documentation closure has
that commit as its writable parent and records its own final commit as
`SELF`. Both `tasks.md` and `checklist.md` have `0` unchecked rows.

### Verification

```text
formal RED at 29db497: 72 failed, 40 passed
formal GREEN at 3981ff8: 112 passed
complete formal router: 243 passed
focused: 2084 passed
Guide full: 3890 passed, 1 existing Pydantic warning
runtime full: 187 passed
browser: 7/7 shards, 20/20 classes, 13 screenshots
browser errors: page=0 console=0 SSE=0 server_transport=0
                unexpected_http_5xx=0 image=0 cross_session=0
                late=0 xss=0
```

The locked `UV_OFFLINE` commands are classified `ENVIRONMENT`: the offline
cache lacks the Pillow `10.4.0` CPython `3.12` arm64 wheel, no tests started,
and no network fallback was attempted. The approved Python `3.11.1` /
pytest `8.0.0` environment supplied the passing Guide and runtime results.

### Evidence

```text
Guide evidence:
  /private/tmp/xiaoro-round9-final-guide-af1faf4
  SHA256SUMS.txt SHA-256:
  a3b0969b6399d54f239f884367e765f7c70ba360fdfc449520842828666cb280
Focused/data evidence:
  /private/tmp/xiaoro-round9-final-data-af1faf4
Runtime/static evidence:
  /private/tmp/xiaoro-round9-final-runtime-static-af1faf4
  SHA256SUMS SHA-256:
  863467e095aec0dab2f81e5b86f17b2976aadb91c12e86eb1b283b9a4ebe6427
Browser evidence:
  /private/tmp/xiaoro-round9-final-browser-af1faf4
  evidence-manifest.sha256 SHA-256:
  245d0436b9261c45854cf5749b975799a6bd5e9dac080372dc9d64e89b56cbe9
  summary.json SHA-256:
  3069cda74c2833262357de1d4ba8d17462d0211aee3c115b5f5d1bc2ebddae13
```

### Data

```text
fact_count=0
approved=0
unknown=114
conflict=0
category candidates=7 pending + 12 quarantine
review candidates=2 pending + 4 quarantine
approved reviews=6
approved review products=42,49,55
historical review candidates=336/111, not_rerun
category asset SHA-256:
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
category manifest raw SHA-256:
dc528a034779559e0ac9b6444f1b0365e3041478d71ebbc703da3aaaf0e6179c
review asset SHA-256:
22bac50e053a621826c831565b3a18e1df3592049ac35377298bac0ab0536171
review manifest raw SHA-256:
2d4acdb1251e1b65d2b92fb2b052734f58b56cd4cd558e783c0391432c630460
```

### Audit And Protection

The independent read-only routing audit used profile
`round9-routing-incremental-v1`, scope manifest SHA-256
`0ef16e0438f27f63dcc6f2e0e18e4bf06662fede465b32bcb48e062f719e6ce4`,
and deterministic audit key
`547547839b0c85cebb677dbbc259fb430eaf784c4e91777a1fdb18acd2c4ed13`.
Its final result is `P0=0;P1=0;P2=0`, with
`full_file_invocations=0`.

Source `b82e600` and integration `3981ff8` have identical audited production
blobs:

```text
app/guide/understanding/contracts.py:
a04cd8a13109ea40293d9eb84e86ea23d0f0d71e
app/guide/understanding/exact_parsing.py:
3b900733effa97194a223b682885dc4a54a10279
```

Checkpoint `af1faf4` retains both blobs. Task 24 remains cleared with actual
reader `app/guide/retrieval/review_reader.py`, blob
`4db1174c053b3fcb33aa1b7f4da9122969433467`, corrected scope
`9bd6fbef8072acfb770af95bdcead537a11e0c262ee85092c859ae177bdb14e1`,
and `full_file_invocations=0`.

Protected diffs from `a29d727` and `a88d8af` are empty. Ranking SHA-256 is
unchanged:

```text
4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f
```

No business code, tests, protected paths, or data assets were changed during
closure. No push, deployment, or traffic switch was performed. Remaining
release work is only the two items listed in `Release Remainder`.
