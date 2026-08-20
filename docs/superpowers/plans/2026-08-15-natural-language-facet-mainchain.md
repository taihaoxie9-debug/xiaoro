# Natural Language Facet Main-Chain Closure Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Follow strict TDD: every production change starts from a failing focused test.

**One-line goal:** Finish the text recommendation main chain by (1) stopping the model-degradation雷, (2) enforcing the safety hard-gate so nothing is silently let through, and (3) wiring natural-language preferences into the already-proven soft-ranking engine — without breaking recall, safety, or existing order.

**Repository:** `/Users/bytedance/Desktop/xiaoro-fresh` only. Never use `/Users/bytedance/Desktop/xiaoro-shopping-master`. The IDE may show old-repo files; they are not execution authority.

**Branch:** `rebuild`. Data layer is `DATA_GREEN` at commit `bd57b75`.

---

## 0. What This Plan Is Built On (verified facts, not assumptions)

Everything below was measured against real data / real model calls during design. Do not re-litigate; treat as ground truth.

### 0.1 Data layer is done and frozen
- 103 products, 1,338 parameter groups classified, `silently_skipped=0`.
- 279 verified facts in production (`merchant_parameter` only), 82 products, 27 fields.
- Dual verifier + signed promotion + reproducible readiness. SHA locks unchanged.

### 0.2 Soft-ranking engine already proven
- `app/guide/decision/facet_ranking.py` ranks matched → unknown → mismatch.
- `app/guide/decision/recommendation.py` applies facet rank only when facets exist; no-facet path keeps exact old price order.
- `tests/guide/decision/test_recommendation.py` covers finish soft-rank / no-capability-no-effect / no-facet-keeps-order. All green.
- **Recall never shrinks: a missing or mismatched facet reorders, never removes.**

### 0.3 Field coverage in current production (why "fields feel thin")
Measured distinct-product coverage of the 279 facts:

| field | products | note |
|---|---|---|
| efficacy | 28 | usable soft-rank now |
| suitable_skin | 18 | usable soft-rank now |
| origin | 37 | usable |
| shade | 13 | base/color makeup only |
| finish | **4** | too thin from params alone |
| texture | **1** | too thin from params alone |
| spf_pa | 2 | thin |

Root cause of thinness (verified, NOT a bug, NOT OCR error): of 1,338 params, ~55% are `not_applicable` (品牌/商品编号/生产厂家/备案名称 — e-commerce noise), ~23% `pending` (conflicting values), ~22% `quarantine` (safety or already-in-canonical). What's left (279) is the clean usable set. Params tables are simply low signal-to-noise.

### 0.4 The OCR goldmine exists and was wrongly benched
- Old v2 already ran OCR on ~95/103 products (660 detail images), stored in old repo `.tmp_user_download_audit/detail_review/detail_*_ocr.json` + `historical_ocr_value_scan_20260708.json` (1,169 records).
- It was benched under the old rule "merchant claims display-only, never rank." That rule is right for hard filters, but it also blocked soft ranking. Soft ranking is exactly where claims belong.
- Measured signal in OCR (distinct products): texture 33, longevity 32, skin 26, finish 22, sun 16, safety-claim 23. This is 5–33× more than the params table for finish/texture.
- Noise is ~13% of images (直播间/宠粉/领券/NO.1/爆款) and follows fixed templates → a stop-word list removes most.

### 0.5 Safety data reality (the hard-gate can rarely be satisfied)
Canonical 103:
- `safety` (special-cosmetic registration nature): known 73 / unknown 30.
- `ingredients_present` (what it contains): known 37 / unknown 66.
- `verified_absences` (proven to NOT contain X): **known 0 / unknown 103**.

Consequence: "does it contain / is it registered" can be answered for many; "prove it does NOT contain X" can be answered for **none**. Alcohol/香精 are the only ingredients the exact parser whitelists today.

### 0.6 Model degradation雷 (root-caused, deterministic, NOT random)
Live DeepSeek V4-Pro probe found specific inputs fail 8/8 (not "occasional"):
- "想要哑光一点的粉底" → detail stage emits `acts:[{kind:add_preference, target:"finish:matte"}]`.
- `SemanticActTarget` whitelist has `texture_preference`/`fragrance_preference` but **no `finish_preference`**, and the model emits free-form `"finish:matte"` / `"skin_type:oily_sensitive"` instead of an enum.
- Strict schema rejects → repair retries same value → `invalid_output` → semantic lane degrades to exact-only → 该答的变成澄清 (e.g. base makeup topic dropped → false clarification).
- route stage is fine (~50 completion tokens, never truncated). It is **not** a max_tokens=256 truncation problem; it is a schema/prompt alignment problem.

---

## 1. Non-Negotiable Rules (the铁律)

1. **Recall stays wide.** Soft facets reorder only; never delete a candidate for a missing/mismatched facet.
2. **Hard gates stay hard, on evidence.** Budget/category/safety/exclusion filter only with strong evidence. Merchant claims (params, OCR, title) are soft-rank / display only, never hard-filter.
3. **Two axes decide soft-vs-hard — memorize this table:**

   | user tone | data available | action |
   |---|---|---|
   | safety/allergy ("我酒精过敏/绝对不能") | strong evidence | **hard filter** (existing `ExclusionConstraint`) |
   | safety/allergy | only claim / none | **fail-closed** ("无法为你核实，请看实物成分表") |
   | preference ("想要/偏向不含酒精") | claim/OCR | **soft rank** (`FacetConstraint`), labeled 商家宣称 |
   | ambiguous / bare ("不含酒精的") | any | **default to hard side** — never silently soft-rank a bare exclusion |

   Rule of thumb: **软的宁可丢，硬的宁可停。** Merchant claims only ever serve *preference*; the moment tone is safety/allergy, claims auto-downgrade and no longer count.
4. **Unknown is tolerated, never faked.** Unknown soft field → drop that dimension. Unknown hard gate → fail-closed. Never `issues=[]` silent pass-through for a hard/safety ask.
5. **Model nominates, code decides.** Model emits enum concern + span; code maps to a known field_key + normalized value. Unknown field_key → silently dropped, never raise, never clarify, never degrade the whole turn.
6. **Claims are quoted, not invented.** Model may润色/connect existing claim/review text; it must not fabricate. No-evidence products get no claim/review话术.

---

## 2. Data Usage Matrix (final, drives both ranking and display)

| data | rank use | display use | red line |
|---|---|---|---|
| params (efficacy/skin/origin) | soft rank | show | — |
| OCR claims (texture/finish/longevity/sun) | translate → soft rank | **quote原话 as label** | tag 商家宣称 |
| marketing slang (油皮亲妈/夏日救星) | translate → suitable_skin=油性 etc. | **quote原话 as label** | untranslatable → drop |
| pure hype (NO.1/爆款/明星同款) | drop | drop | never show |
| reviews (only pids 42/49/55) | no rank | "多数评论提到…" | no evidence → no review话术 |
| canonical safety (registration nature) | weak evidence | "已备案 / 非特殊化妆品" | only if known |
| merchant safety claim (孕妇/温和/敏感肌适用) | **no rank** | "商家标注为…（未经核实）" | transcribe, never endorse |
| ingredient exclusion (不含X) | **no rank** | — | fail-closed unless strong evidence |

**One claim, two stored forms:** `normalized_value`（for ranking, e.g. 油性）+ `display_claim`（原话，e.g. 油皮亲妈）+ `source_class` + `source_locator`. Ranking uses the normalized value; the card quotes the原话 with a 商家宣称 tag so the model quotes instead of inventing.

---

## 3. Execution Order (priority high → low)

Do them in this order. Each is TDD (RED → GREEN). Stop a path after two same-layer failures; keep the other green; report earliest failing layer.

### Task -1: Close the safety hard-gate silent pass-through (HIGHEST — ship even if nothing else)
**Why:** Live probe showed "孕妇能用" / "无矿物油" currently return `issues=[]` and get a normal recommendation — silent pass-through = the one真事故-level bug.

**Files:** `app/guide/understanding/exact_parsing.py` or intent layer; tests in `tests/guide/intent/` + `tests/guide/decision/test_recommendation.py`.

- [x] RED: freeze cases 孕妇能用 / 无矿物油 / 任意冷门成分排除; assert they do NOT produce a silent normal recommendation.
- [x] GREEN: an exclusion/safety ask that code cannot verify with strong evidence must fail-closed (clarify or explicit "无法核实"), never `issues=[]` pass-through. Judge by **evidence verifiability**, not by enumerating ingredients (infinite list — do NOT try to enumerate).
- [x] Regression: alcohol/香精 (whitelisted) still hard-filter; unverifiable exclusions fail-closed.

**Acceptance:** no hard/safety ask ever silently yields a plain recommendation.

### Task 0: Fix the model-degradation雷 (schema/prompt alignment)
**Why:** "哑光粉底" fails 8/8 today via `invalid_output`.

**Files:** `app/guide/understanding/semantic_contracts.py` (`SemanticActTarget`), the route/detail prompts, adapter tests.

- [x] RED: assert `add_preference` with a finish preference validates; assert the compiler tolerates an unknown/free-form preference target without raising.
- [x] GREEN part A: add the missing enum member(s) (e.g. `finish_preference`) so legitimate preferences validate.
- [x] GREEN part B: tighten prompt so `add_preference.target` MUST be an enum, never free-form `"finish:matte"`/`"skin_type:x"`; the concrete value rides a dedicated field, not a colon-string.
- [x] GREEN part C: compiler drops unknown preference targets silently (trace, no raise, no degrade). **This is the general fix for "infinite unknown fields" —未知就丢，不整句崩。**
- [x] Regression: rerun the live probe set; `invalid_output` count = 0 on 哑光粉底 / 油敏肌防晒; degradation rate ≈ 0.

**Acceptance:** known-preference inputs no longer degrade; unknown ones drop the dimension and still recommend.

### Task 1: Map semantic preferences → FacetConstraint (the wire)
**Files:** `app/guide/intent/task_planning.py::_compile_constraints`; tests in `tests/guide/intent/test_task_planning.py`.

- [x] RED: a preference understanding produces `FacetConstraint(field_key=..., value=...)`; a preference not applicable to the resolved category is **absent (dropped)**, not a clarification.
- [x] GREEN: append `FacetConstraint` for preference drafts, guarded by category applicability (`for_profile`); drop non-applicable; dedupe; unknown field_key dropped.

**Acceptance:** applicable preference → facet; non-applicable → dropped; no new clarification.

### Task 2: Tone-strength split (soft vs hard) — reuse, don't build a new line
**Why:** "我酒精过敏" must hard-filter; "想要不含酒精" may soft-rank. This is one label + one branch, NOT a new pipeline. Hard path already exists (`ExclusionConstraint` + `_exclusion_disposition` + `excluded_evidence_unknown` fail-closed). Soft path is the facet from Task 1.

**Files:** semantic contract (add a strength tag), `_compile_constraints` branch; tests.

- [x] RED: same ingredient wording with allergy tone → `ExclusionConstraint` (hard); with preference tone → `FacetConstraint` (soft); ambiguous/bare → hard side.
- [x] GREEN: model emits strength tag (safety / preference / unknown); compiler routes: safety→exclusion, preference→facet, unknown→treat as safety (fail toward strict).

**Acceptance:** tone decides soft/hard; both outlets are existing code; ambiguous defaults strict.

### Task 3: End-to-end text flow ranks by facet
**Files:** `tests/guide/application/test_text_recommendation_flow.py`.

- [x] RED: base makeup, 3 catalog products (match/unknown/mismatch finish), colloquial "想要哑光一点的粉底": all eligible (recall unchanged), order match→unknown→mismatch, no clarification, `facet:finish` in dimensions.
- [x] GREEN: thread plan constraints into the decision call in the flow.
- [x] Add second-turn regression: turn1 "500内适合油敏肌的防晒" → 3 cards; turn2 "第二个怎么样" → locks card 2, no re-clarify, context intact.

**Acceptance:** colloquial preference reorders real candidates end to end without breaking recall or clarifying; multi-turn reference holds.

### Task 4: Safety/no-regression guards
- [x] Safety/allergy hard-filter still dominates even when a soft facet is present (facet cannot rescue an excluded unsafe product).
- [x] No-preference path is byte-identical to today (order + evidence).
- [x] GREEN.

### Task 5: Phase-A gate
```bash
.venv/bin/python -m pytest \
  tests/guide/understanding tests/guide/intent \
  tests/guide/decision/test_recommendation.py \
  tests/guide/application/test_text_recommendation_flow.py -q
.venv/bin/python -m pytest -c pytest-guide.ini -q tests/guide
.venv/bin/python -m pytest -c pytest-guide.ini -q tests/guide/runtime
.venv/bin/python -m compileall -q app tools
.venv/bin/python -m pytest -c pytest-guide.ini -q \
  tests/guide/test_architecture_boundaries.py tests/guide/runtime/test_import_boundary.py
git diff --check
```
**Acceptance:** all green; ranking SHA `4737c189…`, Canonical 103, manifest lock, 6 review sources all unchanged.

### Task 6 (SEPARATE track, NOT in the 1.5-day window): OCR claim ingestion
**Why separate:** it's a data-layer job (re-provenance the old OCR into fresh), not a main-chain wire. Do it after Phase A is green.

- [x] Import 99 legacy OCR JSON sources into the fresh trusted data layer with `source_class=merchant_description_ocr`, real source/record SHA, locator, and Canonical PID/profile alignment.
- [x] Review image-by-image in eight category batches. Agents only nominated exact source text and category meaning; the main thread applied explicit row decisions. No shared vocabulary scan was used for discovery.
- [x] Preserve `display_claim` as an exact OCR substring and store the reviewed normalized value separately. Reject non-exact text, consumer testimonials, overlong text, hype, and cross-SKU material instead of guessing.
- [x] Capabilities are field-policy driven: ordinary claims may display/compare/soft-rank but never hard-filter; safety-style claims are `safety_transcript` with evidence/display only.
- [x] Production result after existing-data recovery and live crawling: 1,106 claims across 98 products from 103 source files. Ordinary coverage includes texture 59 products, finish 24, longevity 20, efficacy 59, and suitable skin 30; 103 safety transcripts remain display-only.

---

## 4. Definition of "Main Chain Done"

Main chain is functionally complete when Task -1 … Task 5 are green:
1. No safety hard-gate silent pass-through.
2. No model-degradation on known preferences.
3. Colloquial preferences reorder real candidates; recall/safety/clarify intact; multi-turn holds.

Explicitly OUT of "done": OCR claim ingestion (Task 6), full Phase-2 browser matrix, 128-case model gate, frontend polish, deploy.

---

## 5. Verification Evidence To Record (honest, no rounding up)
- focused / Guide full / runtime pass counts.
- Live probe rerun: `invalid_output` count before/after.
- One transcript: colloquial → ordered ids → no clarification; one showing a missing-facet candidate stayed eligible.
- One safety transcript: unverifiable exclusion → fail-closed, not silent pass.
- SHA/Canonical/manifest/review locks unchanged; no residual pytest/uvicorn/playwright processes.

---

## 6. Can This Be Done in 1.5 Days? (honest estimate)

**Task -1 + Task 0 + Task 1 + Task 2 + Task 3 + Task 4 + Task 5: realistic in ~1.5 days.** Reasons:
- They sit on two already-green layers (facet engine + exclusion/fail-closed). Net new code is small: one enum member + prompt tightening (Task 0), one compile branch (Task 1), one strength tag + branch (Task 2), plus focused tests. No new pipeline.
- Task -1 is a guard + fail-closed, not new data.
- Gates (Task 5) are reused, not authored.

**Realistic risks that could eat the 1.5 days:**
- Task 0 prompt tightening may need 2–3 live probe iterations (model behavior). Cap at 2 iterations per the two-failure stop rule.
- Task 2 tone tagging on genuinely ambiguous phrasing will not be perfect — accept ~90% ordinary phrasing; ambiguous always defaults strict (safe, not accurate).

**NOT in 1.5 days (do not attempt in this window):** Task 6 OCR ingestion (data re-provenance is real work), full browser matrix, 128 model gate, deploy. Pulling any of these in will blow the estimate.

**Bottom line:** the *main chain wire* (Tasks -1→5) is a 1.5-day job. The *data enrichment* (Task 6 OCR) is a separate follow-up. Keeping them separate is what makes 1.5 days credible.

---

## 7. Execution Evidence (2026-08-14)

- Current status: Tasks -1 through 6 complete; model/intent field expansion and atomic-fact redesign remain intentionally pending.
- Real DeepSeek V4-Pro:
  - `想要哑光一点的粉底` → typed `finish` preference, no repair.
  - `偏向不含酒精的防晒` → typed soft ingredient preference, no repair.
  - `我酒精过敏，推荐防晒` → typed safety-strength exclusion, no repair.
  - `预算几百块上下，要适合油敏肌的防晒` → successful proposal and typed `BUDGET` clarification; one format repair, no `invalid_output` fallback.
- Current-code tests:
  - High-risk understanding/intent regression: `3839 passed`.
  - Guide full: `7198 passed`, 5 pre-existing warnings.
  - Runtime focused: `228 passed`.
  - Compileall + architecture/import boundaries: `25 passed`.
  - `git diff --check`: pass.
- Protected assets:
  - Canonical products: `103`.
  - Approved review sources: `6`.
  - Deterministic ranking SHA-256: `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- Task 6 OCR assets:
  - Merchant claims: `1,106` across `98` products.
  - Source OCR files: `103`; rejected review nominations: `9`.
  - Recovered exact-source nominations: `90`; added OCR products: `81`, `144`, `145`, `146`; PID `59` gained its first claim through recovery.
  - First live crawl added products `78`, `80`, `126`, and `127`: 37 detail images, 34 non-empty OCR records, and 57 exact-source claims.
  - Second live crawl added 14 identity-verified products: 180 detail images, all with non-empty OCR, and 239 exact-source claims.
  - Third thin-source crawl added products `30`, `34`, `39`, `46`, `69`, `109`, and `134`: 88 detail images and 103 exact-source claims.
  - Separate official-source inventory preserves 16 exact candidates for products `108` and `121`; it is not loaded by runtime and grants no hard-filter capability.
  - Products `26` and `100` remain fail-closed because Canonical identity is missing or conflicts with the bound JD SKU.
  - Product `53` remains unresolved because its sparse Taobao source contains only pricing policy and no identity-matched public replacement was found.
  - Claims SHA-256: `f972613d72c46ff1a5991d027528c77480e613d9ad069217c10e7da6e21003df`.
  - Manifest SHA-256: `d96d7d5e93acefbadab59b4ec232496678561a13c1fc1fe9028a861e29c1dc41`.
  - Guide full: `7213 passed`, 5 pre-existing warnings.
  - Runtime: `230 passed`; OCR/runtime focused: `87 passed`.
