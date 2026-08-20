# Category Data Foundation Audit Progress

This file is append-only. Add a new checkpoint section for later implementation
work; do not rewrite earlier checkpoint evidence.

## 2026-08-10 - Task 1 Baseline Checkpoint

- Source commit: `a88d8afbfa0dfad59eafb3a505b939c33f7e699c`
  (`a29d727` plus the documentation-only execution plan commit).
- Integration commit: `SELF` (the commit containing this checkpoint).
- Stable patch ID: not applicable to this documentation-only baseline freeze.
- Production blob manifest: unchanged from the source commit; Task 1 changes only
  documentation and specification state.
- Focused result: `52 passed in 0.66s`.
- Boundary result: not run by Task 1.
- Browser result: not run by Task 1.
- Audit state: opening audit `FINDINGS`, with one real full-file invocation.
- Remaining blockers: opening audit findings `P0=0; P1=2; P2=1`; Tasks 2-13
  remain incomplete.

### Frozen Hashes

- Protected tree command scope: `app/services`, `app/database`,
  `data/canonical`, and
  `app/guide/decision/deterministic_ranking.py`.
- Protected tree entries: `46`.
- Protected tree SHA-256:
  `e2cc565f0101e657a21aefc6ad0e912958bd5a604acf0d965e85ed1b9bece3d3`.
- Ranking SHA-256:
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.

### Opening Audit Identity

- Audit source commit: `4dda1cae24082c385d01e756ed62f9d15c1894a3`.
- Audit profile: `category-data-full-file-v1`.
- Audit scope: `11` full files and `2,852` lines.
- Scope manifest SHA-256:
  `de2d9b153e4d7055bed7fb11e65877c769e95dad58879307745296a8da23f3d2`.
- Audit key:
  `2045d570c8853ebff855a4e4fe13420d6220062b20e97e112f0db1e874c4b167`.
- Report:
  `docs/audits/category-data-foundation/opening_audit.md`.
- P1: formal category routing covers only sunscreen and serum
  (`app/guide/understanding/contracts.py:21-24`).
- P1: decision facts do not expose category-specific fields
  (`app/guide/adapters/catalog/canonical_guide_catalog.py:49-89`).
- P2: approved review assets have no reproducible builder
  (`app/guide/retrieval/approved_review_assets.py:123-166`).
- The opening full-file audit invocation count remains `1`; finding repairs
  must use RED/GREEN and must not repeat the same-key full-file audit.

### Completion State

Phase 3A is not `COMPLETE`. Tasks 2-13 and all unverified checklist items
remain open.

## 2026-08-10 - Task 2 Integration Checkpoint

- Source commit: `a8b6ea11d6207b46a64401d62013f55aafc4e8d1`.
- Integration commit: `07acf9bab15d114988b63ec49ae3404032b3d4e9`.
- Stable patch ID:
  `c6f34d1537ceb0aef5891f9a5dda0c6ddffd3269`.
- Production blob manifest:
  - `app/guide/retrieval/category_profiles.py`:
    `4d4fd6a4822458796f831f5f1291fa80862c8fc3`
  - `app/guide/retrieval/category_taxonomy.py`:
    `b5b5aa3e893959e20ac926302cd8207eb4bcbedb`
- Focused result: category profiles and taxonomy `7 passed in 0.31s`;
  architecture and public contracts `137 passed in 0.57s`.
- Boundary result: `app/guide` and `app/guide_runtime` passed with zero
  violations; compileall and diff check passed.
- Data counts and hashes: exactly `6` profiles map all `39` Canonical raw
  categories across `103` products; profile product counts are
  `51/12/19/6/12/3`. Canonical data is unchanged.
- Protected state: protected tree SHA-256 remains
  `e2cc565f0101e657a21aefc6ad0e912958bd5a604acf0d965e85ed1b9bece3d3`;
  ranking SHA-256 remains
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- Browser result: not applicable to the Task 2 domain contract.
- Audit state: source audit `PASS`; no same-key full-file audit was repeated.
- Remaining blockers: Tasks 3-13 remain incomplete. Phase 3A is not
  `COMPLETE`.

## 2026-08-10 - Task 5 Integration Checkpoint

- Source commits:
  `8b3384d38f8c2773b32cc4eee082339b602761bf`,
  `c4a69b1dbe0837474cf16a3a233647ce3a68f391`, and
  `2e2e2be57b1cf9b648e0420e9e3a2d1407a5f4cb`.
- Integration commits:
  `950e5f20d1cf180306a10be42c96810140710f79`,
  `f33f2175acdad19b9efb992523da7abe639ed76f`, and
  `f1ddb763831b02c3203d8ec30cfcd4138353851f`.
- Stable patch IDs, in source and integration order:
  `d2bfa7fa9bb9db12993b7b0a8362866629ddd20c`,
  `a236f6eed51890ecade61a77d7ba8c5bb7de26f7`, and
  `ad68b419ad92be4433ca48b46379536f73f1304f`.
- Production blob manifest:
  `app/guide/retrieval/category_fact_assets.py` =
  `e7fae4844ee941e6152f3d9016b0a299b2cf0c18` in both source and
  integration.
- Focused result: approved category fact loader `50 passed in 0.71s`.
- Fixture data: `2` approved facts; facts SHA-256
  `6591aca45d3b1463a95a13063e8ebfc40666d6ac4d8acf464a4ed8853c493eb0`;
  logical manifest self-hash
  `f888b148c677ae9b3635aed5ca8e29c92a34c04e409ad4f2c101b178f1de879f`.
- Verifier result: category profiles and field contracts
  `29 passed in 0.31s`; architecture and public contracts
  `137 passed in 0.94s`.
- Boundary result: `app/guide` and `app/guide_runtime` passed with zero
  violations; compileall and diff check passed.
- Protected state: the diff from `a29d727` is empty; the `46`-entry protected
  tree SHA-256 remains
  `e2cc565f0101e657a21aefc6ad0e912958bd5a604acf0d965e85ed1b9bece3d3`;
  ranking SHA-256 remains
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- Browser result: not applicable to the Task 5 offline loader contract.
- Audit state: source corrective commits cover exact-duplicate collapse and
  embedded local-path rejection with regression tests. The integration writer
  ran the normal verifier matrix and did not repeat the opening full-file
  audit.
- Remaining blockers: Task 4 and Tasks 7-13 remain incomplete. Task 10 was not
  integrated. Phase 3A is not `COMPLETE`.

## 2026-08-10 - Task 6 Integration Checkpoint

- Source commits:
  `8683a10112573eef1dd63ba41a4fc1addf697c36`,
  `814253e6b889d4314f367bdc4812ee0e52eaface`, and
  `30134bc5cb37fd5a86760eda5138f6cbc3a1d91f`.
- Integration commits:
  `04ea50576b3e5cd02662b62fec69eaec9789cfcf`,
  `1b538a31cae11af295d23be50d762a4b6056ef62`, and
  `300aa8aa26c2afef7d7258678e4538bc6fdece4b`.
- Stable patch IDs, in source and integration order:
  `875a4d05dbc985b64a48d0670c303ced1ca7cb2f`,
  `cdeda5114e411b08b9f5c4182211847d00c6b59b`, and
  `e62a8ab5c356bb099428c8217af86d98b0e1ad5b`.
- Production blob manifest:
  `tools/guide_data/__init__.py` =
  `ee271922062f079bb35ecf893af99fcade426d68` and
  `tools/guide_data/build_category_fact_candidates.py` =
  `8b7d18256cc9499871ffe8f4b594e7968c28818c` in both source and
  integration.
- Focused result: deterministic category fact candidate builder
  `21 passed in 1.18s`.
- Fixture CLI result: `input_count=20`, `duplicate_count=1`,
  `pending_count=7`, `quarantine_count=12`, `approved_count=0`, and
  `conflict_group_count=1`. Pending SHA-256 is
  `a8e61b695be9961b8419f5410d33328174f8bd49d61a8b83c24a77b1b24ae842`;
  quarantine SHA-256 is
  `4241cff791fec04f87919d708d7373be742953a368bb26996d1d345983a7a474`.
- Verifier result: the shared category profiles/contracts and
  architecture/public-contract suites remained green; both boundaries,
  compileall, diff check, protected diff, protected tree hash, and ranking hash
  remained green and unchanged.
- Browser result: not applicable to the Task 6 offline candidate-builder
  contract.
- Audit state: source corrective commits harden output publication, path
  handling, authority validation, and candidate identity with regression
  tests. The integration writer ran the normal verifier matrix and did not
  repeat the opening full-file audit.
- Remaining blockers: Task 4 and Tasks 7-13 remain incomplete. Task 10 was not
  integrated. Phase 3A is not `COMPLETE`.

## 2026-08-10 - Task 10 Integration Checkpoint

- Source commits:
  `352d7e4b052d137e8f7fe291918638214173c3e5`,
  `e753c460bdf1198ed250eccad35aa141e5693339`, and
  `1538f630d30beeb29896d880e78b348d73cf3f63`.
- Integration commits:
  `b6bf8d20a7498801e80acaf9e41357bd9f0b371b`,
  `cecf1d188f069a19960fee7e3af5df5a4a389d31`, and
  `c4ad05aed17bd5926da2051d69d1f8cbdf92b1eb`.
- Stable patch IDs, in source and integration order:
  `b48776b5e0da71d3f3509e1d6432f0e63393b8b9`,
  `ede9e1b5a955ae9682f4f690a9ecb987ce285e3c`, and
  `3377b40bf30992d2d0b68d93a2f91bf6b2017515`.
- The integrated seven-file blob manifest matches the source branch exactly:
  fixture manifest `8075cf7829e56e2573d0721ef28e88c76da03835`,
  fixture HTML blobs `d11d1056ca19111a674a95ec46fc5b41c5795916`
  and `2cba8d6f2fffd43d37b9841f84fb60fd62f53d8b`, test blobs
  `164f8d6904e3122d86b4639d631968b1cea3b738` and
  `1b24f99e1938e226d9f990f4e317f868e7c52d3d`, and tool blobs
  `373843fb64a6f93ca7b7fdf3f162ed444e3d041c` and
  `c96a7f5d8bcbb923f2b4352bf7f8d52cf08fcc29`.
- Focused result: Task 10 builder/promotion plus approved loader, reader, and
  summary regressions `95 passed in 0.99s`; Guide architecture and public
  contracts `137 passed in 1.32s`.
- Fixture result: two independent builds were byte-identical. Counts were
  `extracted=7`, `deduplicated=1`, `pending=2`, `quarantine=4`, and
  `approved=0`. Pending SHA-256 was
  `52ada19838518e3fa1f66cba719b224bce22efc9507928ea8d24f3060ed25cc5`;
  quarantine SHA-256 was
  `f6ea3e3f365095d95019875ea79cb20a6106246adfacd5652fd26382943077db`;
  manifest raw-file SHA-256 was
  `2da5d0d88e6dc0849cd81674f4a8b3caf9f0dd3c25b26a2a88070a1a24e4a5a8`
  with logical self-hash
  `026fb7879b8321ec4b444119061cdb5c730c7e6f0952746a2f70ffa947941bd6`.
- Provenance result: the committed fixtures report `fixture_only`; historical
  `336` total and `111` strict candidates remain `not_rerun`. No current-cycle
  reconstruction of the unavailable original HTML is claimed.
- Existing approved assets remain byte-identical to the Phase 2 handoff
  `ef66868e60c1c786b75f201b4a24b0a382e16102` and baseline `a29d727`.
  Manifest, sources JSONL, and source-audit raw SHA-256 values remain
  `2d4acdb1251e1b65d2b92fb2b052734f58b56cd4cd558e783c0391432c630460`,
  `22bac50e053a621826c831565b3a18e1df3592049ac35377298bac0ab0536171`,
  and
  `8172d6fbcf88c3c5b48e1a2f65e5698f2c8c7b4e0b61801ee9bc4bcb28a00a55`.
  The catalog still has exactly `6` approved source IDs: two each for products
  `42`, `49`, and `55`.
- Static and protection result: compileall passed; `app/guide` and
  `app/guide_runtime` boundaries passed; diff check passed; the protected diff
  from `a29d727` is empty; ranking SHA-256 remains
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- Browser result: not applicable to the Task 10 offline review-data tools.
- Audit state: the source corrective commits add fail-closed queue and
  coordinated-tamper checks. The integration writer ran the normal verifier
  matrix and did not repeat the opening full-file audit.
- Remaining blockers: Task 4, Tasks 7-9, and Tasks 11-13 remain incomplete.
  Phase 3A is not `COMPLETE`. No push, deployment, or traffic switch was
  performed.

## 2026-08-10 - Task 7 Integration Checkpoint

- Source commits:
  `5eff4ab85050aab9932f3c7925b1eee6f8b886dc` and
  `6db72accb816928d8d41e327babddc83b7937342`.
- Integration commits:
  `0ffd0430b1bef8922ef011890b276af6059ca1f4` and
  `2d73bd676d1e52d0ad74444367b2818281a81e8c`.
- Stable patch IDs, in source and integration order:
  `bd1790495cf594dd63b105aba06fd77ce04eb7fa` and
  `4ac6d8a39cb20aa1887b46d29844e5b254ce1610`.
- The integrated four-file blob manifest matches the final source commit
  exactly:
  `app/guide/retrieval/category_fact_assets.py` =
  `713c8f68c7c7753b117368b956af18151b0f69b8`,
  `tests/guide/retrieval/test_category_fact_assets.py` =
  `daf5036668d1beecdf578b4d55bb9c1edd29d2f2`,
  `tests/guide/tools/test_promote_approved_category_facts.py` =
  `f9397157d144f886a9f16a70750ee902df35eb2c`, and
  `tools/guide_data/promote_approved_category_facts.py` =
  `0d98a7655144442b5baf8c402286f01c85933f05`.
- Regression result: Task 5/6/7 loader, candidate builder, and promotion
  suites `117 passed in 3.35s`; the complete Task 7 promotion suite
  independently passed `44 passed in 2.09s`.
- Verifier result: Guide architecture and public contracts
  `137 passed in 0.98s`. Compileall, both `app/guide` and
  `app/guide_runtime` boundaries, diff check, and protected diff passed.
- Mechanical zero-decision promotion rebuilt the actual Task 6 fixture queue
  with `input_count=20`, `duplicate_count=1`, `pending_count=7`,
  `quarantine_count=12`, `approved_count=0`, and
  `conflict_group_count=1`. Pending SHA-256 remained
  `a8e61b695be9961b8419f5410d33328174f8bd49d61a8b83c24a77b1b24ae842`;
  quarantine SHA-256 remained
  `4241cff791fec04f87919d708d7373be742953a368bb26996d1d345983a7a474`;
  the empty decisions SHA-256 was
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
- The production loader accepted `fact_count=0`. The manifest points to the
  immutable generation
  `category_facts_v1.e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855.jsonl`;
  its facts SHA-256 is the empty-file digest above. The manifest raw-file
  SHA-256 is
  `dc528a034779559e0ac9b6444f1b0365e3041478d71ebbc703da3aaaf0e6179c`
  and its logical self-hash is
  `08bd86a14c2b6caf727c89bf263ad018f10100a11b6f8d4b398e29c11fad187d`.
  Two consecutive production builds returned identical reports and identical
  bytes for the lock, manifest, and immutable facts generation.
- Audit key: coordinator-provided `5553c...`. The source audit over
  `5eff4ab` was `FINDINGS` with `P0=0; P1=2; P2=0`: self-declared queue
  hashes and unlocked decisions could forge approval, and sequential facts
  and manifest replacement exposed mixed generations. The audit probes were
  the RED evidence. Corrective commit `6db72ac` added externally locked
  decision digests, detached HMAC verification for non-empty approvals,
  immutable SHA-bound generations, atomic manifest publication, and
  regression tests. The focused read-only verification and integrated
  44-test run are GREEN with no remaining P0-P2 finding.
- HMAC remains a future non-empty-release responsibility: the independent
  reviewer/signing system must custody the key and supply the detached
  signature through a named environment variable. This zero-decision
  mechanical run intentionally used no HMAC and is not evidence of a human
  approval or production key release.
- Protected state: the diff from `a29d727` is empty; the protected tree
  SHA-256 remains
  `e2cc565f0101e657a21aefc6ad0e912958bd5a604acf0d965e85ed1b9bece3d3`;
  ranking SHA-256 remains
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- Browser result: not applicable to the Task 7 offline promotion contract.
- Remaining blockers: Task 4, Tasks 8-9, and Tasks 11-13 remain incomplete.
  Phase 3A is not `COMPLETE`. No push, deployment, or traffic switch was
  performed.

## 2026-08-10 - Task 8 Integration Checkpoint

- Source commit: `8bc2f2a492448a153efa26c45df49690492852e1`.
- Integration commit: `6999bc6ff4b2a43e0ccb43d827a9eb11b2e2bcbc`.
- Stable patch ID in both source and integration:
  `f8f0738e84187e69ae6127f5783f5e54cdd1a210`.
- The integrated five-file blob manifest matches the source commit exactly:
  empty facts generation =
  `e69de29bb2d1d6434b8b29ae775ad8c2e48c5391`,
  production manifest =
  `930b0c4784fab1950c709a4f34fc93c6da04cc12`,
  coverage report =
  `9488a27a9d939a2ce7fac7871e996fd22198e184`,
  coverage tests =
  `d02b6d518ca0e966a36124bee84ba1e0c9852320`, and
  coverage builder =
  `c47b5f799ae3853fecacd982c2dc173c8e065fde`.
- Focused result: Task 8 passed `4 passed in 0.61s`; the Task 8 plus Task 5/7
  compatibility regression matrix passed `100 passed in 3.65s`
  (`96` Task 5/7 cases plus the `4` Task 8 cases); Guide architecture and
  public contracts passed `137 passed in 1.07s`.
- Pilot mapping is exactly `12` IDs with two per profile:
  `skincare=38,91`, `suncare=53,57`, `base_makeup=79,80`,
  `color_makeup=86,114`, `cleanser=69,103`, and
  `fragrance=120,121`.
- Coverage counts are `approved=0`, `unknown=114`, and `conflict=0`.
  Per-profile unknown counts are
  `skincare=18`, `suncare=18`, `base_makeup=20`,
  `color_makeup=16`, `cleanser=22`, and `fragrance=20`; every profile has
  `approved=0` and `conflict=0`.
- The production asset has `fact_count=0` and loads normally. Its known-value
  source-ref condition is therefore vacuous; the non-empty approved fixture
  separately proves that the known `38/efficacy` and `53/spf_pa` fields retain
  source refs. All production fields without approved sources remain
  `unknown`.
- Two independent temporary zero-decision promotions and report builds were
  byte-identical to each other and to production. Raw SHA-256 values are
  manifest
  `dc528a034779559e0ac9b6444f1b0365e3041478d71ebbc703da3aaaf0e6179c`,
  empty facts
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`,
  and report
  `282f6117a7a3c53d006c51f54eae1f963387d43ab61e4978e61be67adc636249`.
  The manifest logical self-hash is
  `08bd86a14c2b6caf727c89bf263ad018f10100a11b6f8d4b398e29c11fad187d`.
- Static and protection result: compileall passed; both `app/guide` and
  `app/guide_runtime` boundaries passed with zero violations; diff check
  passed; the protected diff from `a29d727` is empty. The `46`-entry protected
  tree SHA-256 remains
  `e2cc565f0101e657a21aefc6ad0e912958bd5a604acf0d965e85ed1b9bece3d3`,
  and ranking SHA-256 remains
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- Task 8 read-only audit key:
  `P3A-T8-8BC2F2A-RO-20260809T191520Z`. The audit covered
  `8bc2f2a^..8bc2f2a` and reported no P0-P2 finding. Its report is
  `/private/tmp/P3A-T8-8BC2F2A-RO-20260809T191520Z/report.md`, with SHA-256
  `9cd33ec1daef64d1f74ecc3f38cbc5e47fdd3b3c567a136a9b767a1fd97ccd1c`.
  The opening full-file audit key
  `2045d570c8853ebff855a4e4fe13420d6220062b20e97e112f0db1e874c4b167`
  was not invoked again.
- Browser result: not applicable to the Task 8 offline pilot coverage
  contract.
- Remaining blockers: Task 4, Task 9, and Tasks 11-13 remain incomplete.
  Phase 3A is not `COMPLETE`. No push, deployment, or traffic switch was
  performed.

## 2026-08-10 - Task 9 Integration Checkpoint

- Source commits:
  `4df5c03d5e52179a8223fd99c1643a2c1a749613` and
  `ab1b457c9489e0fc84151fcef9bbf19abedf0aa0`.
- Integration commits:
  `958fa0c118da4cd14e5a620175256c9562acd7a4` and
  `16f6b30d6a6c52aa94e3af4e6803d50e01cf42a0`.
  The documentation commit containing this checkpoint is `SELF`.
- Source-to-integration mapping, with matching stable patch IDs:
  `4df5c03 -> 958fa0c` =
  `d4ea3878a23d217831c4410d6f3091841d71f1ee`; and
  `ab1b457 -> 16f6b30` =
  `f74ab437eadd6036563c4580ed3a967b7464137b`.
  Both source patches were absent before integration, both cherry-picks were
  conflict-free, and all `21` final source/integration file blobs match.
- The final seven-file production blob manifest matches source and integration
  exactly:
  - `app/guide/adapters/catalog/canonical_guide_catalog.py` =
    `448e2a13d270209f541749665f384b490a3f4ef3`
  - `app/guide/decision/contracts.py` =
    `3cbac2c9238ba03ca06c85c61db1ca7541cef16f`
  - `app/guide/presentation/contracts.py` =
    `0d30ebfa5ced153b7f0757c9f6b9007c40c43a96`
  - `app/guide/presentation/response_planning.py` =
    `1151c4d340b1d37092e91ed8400c12535dec2b6e`
  - `app/guide/retrieval/category_fact_contracts.py` =
    `4d586ed51e0bd881d52bda6e14ab1714fd9af0b6`
  - `app/guide/retrieval/category_fact_reader.py` =
    `9f4b31a6dc8ed447ecf339e03f07a469153cb8d3`
  - `app/guide/retrieval/ports.py` =
    `d164d16d45434009425fd9a6376f361015a7a863`
- Focused GREEN results were: audit-finding regressions `28 passed`; Task 9
  impact matrix `225 passed`; category asset compatibility `166 passed`;
  decision `231 passed`; presentation `53 passed`; and category
  architecture/public contracts `182 passed`. The full Guide suite passed
  `2154 passed` with one pre-existing Pydantic namespace warning.
- The full suite used the shared combined test environment at
  `/Users/bytedance/Desktop/xiaoro-shopping-master/.venv` (Python `3.11.1`,
  FastAPI `0.115.0`, httpx `0.27.2`, Pydantic `2.8.0`, pytest `9.1.1`,
  Pillow `12.2.0`) because host Python intentionally lacks FastAPI. Focused
  and static checks used host Python with Pydantic `2.13.4` and pytest
  `9.1.1`. No dependency was installed or downloaded during integration.
- Production sidecar verification loaded the real manifest with
  `fact_count=0`, all `12` fixed pilot bindings, and an empty approved facts
  generation. `CategoryFactReader` projected exactly `114` facts, all as
  typed `unknown` with null values, unknown provenance, empty source refs, and
  evidence-only capability. Manifest and facts raw SHA-256 values remain
  `dc528a034779559e0ac9b6444f1b0365e3041478d71ebbc703da3aaaf0e6179c`
  and
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
  Runtime composition wiring remains Task 11 and was not changed here.
- Authorization tests prove that `CategoryFactPort` cannot expose a core,
  cross-profile, unregistered, source-unauthorized, type-invalid, pending, or
  quarantine field. Display and compare projection revalidate the registry
  capability before consumption. There is no typed category preference
  contract yet, so category hard-filter and soft-rank consumption remain
  disabled; even independently policy-authorized hard/soft facts make no
  ranking or filtering contribution.
- Full-JSON invariance passed `6` dedicated cases: five complete
  `DecisionResult` comparisons and one complete public-card JSON comparison.
  Unknown, conflict, display-only, compare-only, and hard/soft category facts
  do not change the existing winner, ordered product IDs, visible card IDs, or
  public card payload.
- Static verification passed: compileall covered `app/guide`,
  `app/guide_runtime`, and `tools/guide_data`; both boundaries reported zero
  violations; diff check and the protected-path diff from `a29d727` were
  empty. Ranking SHA-256 remains
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- Task 9 opening audit used profile `category-data-full-file-v1`, source
  `4df5c03`, seven-file scope manifest
  `2aeb839be20ecab350fd562143e9629b8bbee005d527665a504134187758d70b`,
  and audit key
  `410993c3f332129728844d8aa9f5dafb4083f6dd9135d7a78fb1d5741611a324`.
  It reported one confirmed P1 authorization-boundary finding. RED evidence
  was `13 failed` for registry/profile/source/capability/value enforcement,
  `13 failed` for strict asset and runtime-object revalidation, and `2 failed`
  for missing-field construction bypasses. Corrective source `ab1b457`
  produced `13/13/2 passed` and the combined `28 passed` gate. An intermediate
  circular-import collection error was excluded from RED evidence. The same
  audit key was not invoked a second time.
- Browser result: not applicable to this internal port/projection task.
- Remaining blockers: Task 4 and Tasks 11-13 remain incomplete. Phase 3A is
  not `COMPLETE`. No push, deployment, traffic switch, or branch switch was
  performed.

## 2026-08-10 - Task 4 And Task 11 Integration Checkpoint

- Integration started from clean
  `2a23d38fed967100ac0b36b4f90d2381d6df04fb`. The seven source commits
  were cherry-picked in the required order without conflicts:
  - `cb764a85e11a65baf58c5816bae544c40e4216cb` ->
    `9c1fc096e97ebbfa31a1bd163ca14c0c00c362ce`
  - `f5ea603faa70f103503e95318776af2283998ba9` ->
    `ef465815a33392ed4325766213847e3dca8f1105`
  - `8182348264fda194d89c81d70449ff7568184709` ->
    `d2517c84d0213c93fb418c7b112280b569e669c8`
  - `3baea55b2d57d9cc6c682765b89d2a2cf5a2ea9d` ->
    `12eb280219b62be968784b0928d90e77dd333489`
  - `aad958a02b0819ec72137e5805f07fd47b34a4ce` ->
    `e05071be1cda7c73505a3d999be5a5de656b9265`
  - `21ed6935e55820dcdff8134a883b5d548dd51aa8` ->
    `2fb288e184cd18624823fa2943af03102988a677`
  - `10b822295c0020a5e100edd871118701bfdce793` ->
    `af65da896269f69c91f82dea6daaec837da34707`
- `cb764a85` and original Task 4 commit `a9d109ec` share stable patch ID
  `b62a78af6475012a2cb4c79a01ea6354fc2730f4` and identical post-image
  blobs. `f5ea603f` and `8fa5ed69` share
  `5ccb283079f41994f8860957729cd58de71d2c9f` and identical post-image
  blobs. All seven source/integration patch IDs match; all `37` final file
  blobs match. The mapping and blob-manifest SHA-256 values are
  `bdf98ed92afe9e4fc28684afc1d7b3aeb6242c9cc8b0003df2444a59d4922601`
  and
  `f6b131d30fb0add6392dd6bb6dae81c70ec0455f74e5fd06bdcd324f0294252f`.
- The approved runtime `/private/tmp/xiaoro-guide-runtime-venv` reported
  Python `3.11.1`, FastAPI `0.115.0`, Pydantic `2.8.0`, and Pillow `10.4.0`.
  Verification passed: alias matrix `223`, Task 4 focused `481`, Task 11
  focused `151`, Task 9 regression `315`, Guide full `2480` with one
  pre-existing Pydantic warning, and runtime full `148`.
- compileall passed for `app/guide`, `app/guide_runtime`, and
  `tools/guide_data`; both architecture boundaries reported zero violations.
  History/worktree diff checks and protected diffs from both `a29d727` and
  `2a23d38` passed. Protected tree SHA-256 remains
  `e2cc565f0101e657a21aefc6ad0e912958bd5a604acf0d965e85ed1b9bece3d3`;
  ranking SHA-256 remains
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- Runtime composition locks embedded category manifest SHA-256
  `08bd86a14c2b6caf727c89bf263ad018f10100a11b6f8d4b398e29c11fad187d`.
  The raw category manifest/facts SHA-256 values remain
  `dc528a034779559e0ac9b6444f1b0365e3041478d71ebbc703da3aaaf0e6179c`
  and
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`;
  `fact_count=0` and all 12 pilot bindings remain honest. Existing approved
  review count remains `6`.
- `webapp-testing/scripts/with_server.py --help` was run before browser use.
  The final gates used fresh port `18765` and fresh `0700` state/lock
  directories. Category normal and adversarial passed with zero page,
  console, SSE, HTTP 5xx, image, cross-session, late-event, or XSS errors.
  Ten natural sentences each passed formal HTTP and SSE with status 200,
  Guide owner, expected profile, one terminal `end`, no `error`, and
  backend-authoritative card order. All six normal category sentences
  returned 1-3 cards.
- The stable capability audit is
  `docs/audits/category-data-foundation/task11_audit.md`, key
  `1b41936a102cd442722a63302c91af2d0be659695c6b23cc57adeb2d6f5aa18d`.
  Its only opening full-file invocation had been prematurely named as the
  final category audit; this project did not register that name as the Phase
  3A final audit. It is recorded only as
  `formal-category-integration` opening `FINDINGS (P0=0;P1=1;P2=1)`.
  RED/GREEN and targeted read-only verification cleared the findings without
  a second full-file invocation. Task 12's actual final audit remains open.
- Final external evidence is
  `/private/tmp/xiaoro-phase3a-task4-11-integration.vXjgLR`; its 30-file
  `final-evidence-sha256.txt` has SHA-256
  `3fb972b6e854b3197783832f6627212a46b4912d4d1f9c18f89c95f75eb307b9`.
  Normal, natural HTTP/SSE, and adversarial JSON SHA-256 values are
  `0c764bcf72f7b983b0428ad79863116ec17d40a52591c877fae85c146a9fca49`,
  `fd05b4493e2cca45824771c9f780a3915fcb38ab642d3ffe7a1558f47c195fb9`,
  and
  `3eebe18ee87a8732a47b76857f3bd29a6f15e6c82d409fdedacce384f7596abe`.
- Task 4 and Task 11, including all subtasks, are complete. Tasks 12-13
  remain incomplete, so Phase 3A is not `COMPLETE`. No push, deployment,
  traffic switch, or branch switch was performed. The documentation commit
  containing this checkpoint is `SELF`.

## 2026-08-10 - Task 12 And Task 13 Final Closure

- The final production code checkpoint is
  `4206f45f5b0c4738c2592dc4d0115f947266132b`. Task 12 gate fixes integrated
  as `33f87dc`, `5983350`, and `4206f45`; all source/integration stable patch
  IDs and final blobs matched.
- Mechanical data verification confirmed `103` products, six profiles,
  `39/39` raw-category mappings, twelve fixed pilots, and category coverage
  `approved=0;unknown=114;conflict=0`. Category fixture output remained
  `7 pending + 12 quarantine`; review fixture output remained
  `2 pending + 4 quarantine`, `fixture_only`, with historical `336/111`
  marked `not_rerun`. The existing six approved reviews for products
  `42,49,55` remained byte-for-byte unchanged.
- The final dedicated two-image gate submitted and validated both `compare`
  and `negative_feedback`. The final browser matrix passed all seven shards
  on isolated ports `18841-18847`, produced ten PNG screenshots and three
  session JSON sidecars, and reported zero page, console, SSE, HTTP 5xx,
  image, cross-session, late-event, or XSS errors. Evidence manifest
  SHA-256 is
  `2743047e89db7727346a1cbb666885a190365735bcb6ba726cc85d5fefb23303`.
- The unique `FINAL-CATEGORY-DATA-AUDIT` ran once at checkpoint `5983350`
  with key
  `1b3611b13ef377099ee008cdbcb30f950797fadc09d4b025a0fb24f44c6181c7`
  and opened `P0=0;P1=1;P2=1`. RED was `28 failed, 1 passed`. The
  single-writer review-promotion fix added externally locked decisions,
  detached HMAC authorization, immutable sources/audit generations, and one
  atomic manifest pointer. Targeted independent verification cleared both
  findings with `P0=0;P1=0;P2=0`; the full-file audit was not repeated.
- Post-fix normal gates passed: focused `120`, Guide full `2511`, runtime
  full `155`, compileall, both boundaries, protected diff, and diff check.
  Ranking SHA-256 remains
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
  Post-fix 41-file production blob manifest SHA-256 is
  `7e6579a578270fa58370d2e082569c179590fd03f0147c0cda1ff00955450a0b`.
- Tasks and checklist are complete. Final handoff is
  `docs/audits/category-data-foundation/final_handoff.md`. Phase 3A is
  `COMPLETE`; no push, deployment, traffic switch, protected-path change,
  or automated approval occurred.

## 2026-08-10 - Round 7 Final Closure Checkpoint

- Final production code checkpoint:
  `098be5a5ce4a7b9beb2a05babb557662a394dfe9`.
- Documentation closure commit: `SELF`.
- Task 14 source-byte binding is `ffd41a4`; Task 15 fsync recovery is
  `95bc7ba`; Task 16 modified negation is `c854ba6`; Task 17 text/image
  precommit validation is `966bedd` and `d568ce0`; Task 18 card-flow
  preservation is `9bb991f`; Task 19 positive turn is `35120f5`; Task 20
  delivery evolution is `2f21151`, `06d7ea5`, `be5263e`, `6dcb668`, and
  `098be5a`; Task 21 is `bee11b3`; Task 22 is `1088fd7`.

### Verification

- Candidate builder: `68 passed`, including the exact race nodes
  `3 passed`.
- Final focused executions: `776`, `0 failed`, composed of `574`,
  formal router `123`, and exact runtime `79`.
- Authoritative full evidence:
  `/private/tmp/xiaoro-authoritative-full-final-098be5a/summary.txt`.
- Guide full: `2619 passed`, with one existing Pydantic warning.
- Runtime full: `187 passed`; combined full result: `2806 passed`.
- Approved interpreter:
  `/private/tmp/xiaoro-guide-runtime-venv/bin/python`, Python `3.11.1`,
  pytest `8.0.0`.
- The locked `UV_OFFLINE` command lacked the Pillow `10.4.0` CPython `3.12`
  arm64 wheel and is classified `ENVIRONMENT`; it is not claimed as passing.
  The approved Python 3.11 environment supplied the authoritative full result.
- compileall, both `app/guide` and `app/guide_runtime` boundaries, and
  `git diff --check` passed. Protected diffs from `a29d727` and `a88d8af`
  are empty. Ranking SHA-256 remains
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.

### Browser Evidence

- Evidence root:
  `/private/tmp/xiaoro-phase3a-authoritative-browser-098be5a`.
- All `7/7` shards and `20/20` scenario classes passed, with ten screenshots.
- page, console, SSE, server transport, unexpected HTTP 5xx, image,
  cross-session, late-event, and XSS metrics are all `0`.
- ASGI cancellation before the terminal `send()` left state rows=`0` and
  target rows=`0`.
- Normal terminal chunk order is `[feedback_target,end]`, with matching
  version `1`.
- Server exception, traceback, and `generator already executing` counts are
  all `0`; Task 21 variants passed `4/4`.
- Ports `19341–19347` were released.
- Evidence manifest SHA-256:
  `5c9fa302ea2e6d16b2c75ff5616368e626bcae6a53601632af3cfd9029a97a8d`.
- Summary SHA-256:
  `896ed5f4fdba2919019742ea70cbba569f68af751df1779d2e275ed20083f3a1`.

### Audit Disposition

- The unique `FINAL-CATEGORY-DATA-AUDIT` remains exactly one invocation at
  checkpoint `5983350`, key
  `1b3611b13ef377099ee008cdbcb30f950797fadc09d4b025a0fb24f44c6181c7`.
- Its original `P1=1;P2=1` was cleared by `4206f45`; the same full-file audit
  was not rerun.
- A later independent incremental audit over `6dcb668..098be5a` is recorded at
  `/private/tmp/xiaoro_final_stage1_audit_098be5a/report.md`, report SHA-256
  `0035e75201667506f61d1408ab3af78f5ee02f8b8797380d32013aa6fe6f4789`,
  with no `P0–P2`.
- An earlier incremental audit found a post-send `P1`; `098be5a` fixed it.
- Final unresolved findings are `P0=0;P1=0;P2=0`.

### Data And Release State

- Category manifest logical/raw SHA-256 values remain
  `08bd86a14c2b6caf727c89bf263ad018f10100a11b6f8d4b398e29c11fad187d`
  and
  `dc528a034779559e0ac9b6444f1b0365e3041478d71ebbc703da3aaaf0e6179c`.
  Facts remain the empty-file SHA-256
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`;
  pilot report SHA-256 remains
  `282f6117a7a3c53d006c51f54eae1f963387d43ab61e4978e61be67adc636249`.
- Category candidate pending/quarantine SHA-256 values remain
  `a8e61b695be9961b8419f5410d33328174f8bd49d61a8b83c24a77b1b24ae842`
  and
  `4241cff791fec04f87919d708d7373be742953a368bb26996d1d345983a7a474`.
- Review manifest, sources, and audit raw SHA-256 values remain
  `2d4acdb1251e1b65d2b92fb2b052734f58b56cd4cd558e783c0391432c630460`,
  `22bac50e053a621826c831565b3a18e1df3592049ac35377298bac0ab0536171`,
  and
  `8172d6fbcf88c3c5b48e1a2f65e5698f2c8c7b4e0b61801ee9bc4bcb28a00a55`.
  Review candidate pending/quarantine SHA-256 values remain
  `52ada19838518e3fa1f66cba719b224bce22efc9507928ea8d24f3060ed25cc5`
  and
  `f6ea3e3f365095d95019875ea79cb20a6106246adfacd5652fd26382943077db`.
- The six approved review sources for products `42`, `49`, and `55` are
  unchanged. Historical `336/111` remains `not_rerun` provenance only.
- No approval was automated. Production remains `fact_count=0`,
  `approved=0`, `unknown=114`, `conflict=0`; fields without approved evidence
  remain unknown.
- The server commit boundary is successful return from the terminal ASGI
  `send()`; the browser commits its local snapshot only after EOF. There is
  no client ACK, so network end-to-end exactly-once requires a future delivery
  ID plus ACK/query/retry protocol. This is a release remainder, not an
  unresolved P0–P2 finding.
- This closure changes only the five authorized documentation files. Business
  code, protected paths, and data assets are unchanged. No push, deployment,
  or traffic switch was performed.

## 2026-08-10 - Task 24 Scope Correction Checkpoint

- Frozen source commit:
  `59833501223213991cb37ba765e5b9ac42cae7d9`.
- Integration commit: `SELF`.
- The original 41-file scope manifest
  `ed8de1ff252b477ef7ba559ac3e19212be6967ccf1efd27fcb1238aafe0e905b`
  and audit key
  `1b3611b13ef377099ee008cdbcb30f950797fadc09d4b025a0fb24f44c6181c7`
  remain unchanged as historical malformed-scope evidence. The existing
  ledger row was not rewritten.
- The corrected 42-file scope manifest is
  `9bd6fbef8072acfb770af95bdcead537a11e0c262ee85092c859ae177bdb14e1`;
  its audit key is
  `d88c16831e176cbc4b3445294a1d9fddf6ffcfd97eeafe3e04f451c1e595114e`.
- The corrected runtime file is
  `app/guide/retrieval/review_reader.py`, Git blob
  `4db1174c053b3fcb33aa1b7f4da9122969433467`, file SHA-256
  `2d15d42a5e5224567e930527abde2570741b0c13083790115d607fd8e1194a32`.
  The nonexistent `app/guide/retrieval/review_evidence_reader.py` path is not
  part of the corrected scope.
- The runtime reference chain was confirmed as
  `composition.py -> build_review_evidence_reader ->
  load_approved_review_assets -> ReviewEvidenceReader -> text/image flows`.
- Independent read-only targeted verification passed `98` tests with
  `P0=0;P1=0;P2=0`,
  `full_file_invocations=0`, and `targeted_reader_invocations=1`.
  No final full-file audit was repeated.
- Task 24 is complete. Task 23 remains unchecked, so the Round 8 completion
  state remains blocked by Task 23.
- This checkpoint changes only authorized audit/specification documents.
  Business code, protected paths, and data assets are unchanged. No push,
  deployment, or traffic switch was performed.

## 2026-08-10 - Task 23 Incremental Audit Finding Checkpoint

- Candidate domain commit:
  `66be64dd3a6fa43c14a22d8a68c5dee6768eeec5`.
- Candidate integrated commits:
  `ae90462539f757d2160fe23323b19d1dd857e839` and
  `9751f95bda2bcc1b696b1581854d475220046cb6`.
- Documentation checkpoint: `SELF`.
- Domain and integration stable patch ID:
  `6ee083a2914e3b3b022ae2f1c2c81fb223805d5c`.
  The final blobs for `exact_parsing.py`, `test_task_planning.py`, and
  `test_category_profile_parsing.py` match between `66be64d` and `9751f95`.
- Candidate blob manifest:
  - `tests/guide/application/test_formal_chat_router_http.py` =
    `b648b3f331c5eabd34127557556bcce83bb92cbd`
  - `app/guide/understanding/exact_parsing.py` =
    `ad80c8423793df63ed285ff927639c5a9761cfc9`
  - `tests/guide/intent/test_task_planning.py` =
    `c152a81edbf1acc0081a926d33c6a7492bc2ed7a`
  - `tests/guide/understanding/test_category_profile_parsing.py` =
    `de956b93d7d6fda41a48f211ffd4f6a1f6244346`
- Existing RED provenance is preserved in the `ae90462` commit body:
  `RED on 4ee9fe0: 6 failed, 2 passed across message and stream endpoints`.
  The current Integration Writer inspected that commit and collected its
  eight parameterized formal HTTP/SSE nodes, but did not independently rerun
  RED or execute focused GREEN before this finding. The routing writer's
  `301` focused range, formal router regression, compileall, and both
  boundaries were not run by this writer, so no pass is claimed for them.
  A documentation-only `git diff --check` passed after these edits.
- A coordinator-reported independent incremental audit found a new `P1`.
  No report path or report hash was supplied with the finding, so this
  checkpoint does not invent one. The connector expansion can propagate the
  earlier category negation across an explicit positive predicate and
  incorrectly suppress fragrance for at least:
  `不考虑防晒并想买平价香水`,
  `不考虑防晒并推荐平价香水`,
  `不考虑防晒且想买平价香水`, and
  `不考虑防晒并且推荐平价香水`.
- Task 25 is open and requires understanding, task planning, and formal
  message/SSE RED/GREEN for those positive-predicate cases while preserving
  Task 23's pure coordinated-negation behavior.
- Task 23 remains unchecked and this candidate integration has no completion
  disposition. No Round 9 final summary or completion claim was written.
- Read-only protection checks performed before documentation edits found
  empty protected diffs from both `a29d727` and `a88d8af`. Ranking SHA-256
  remains
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- This checkpoint changes only authorized task, checklist, and audit
  documents. Business code, tests, protected paths, and data assets are
  unchanged. No push, deployment, or traffic switch was performed.

## 2026-08-10 - Task 26 Independent Read-Only Design Verification

- Frozen source commit:
  `ebed86efe23aa4921a6aa205349daa297adc8d05`.
- Documentation checkpoint: `SELF`.
- Stable patch ID: not applicable to this documentation-only checkpoint.
- Read-only design scope:
  - `app/guide/understanding/exact_parsing.py` =
    `ad80c8423793df63ed285ff927639c5a9761cfc9`
  - `tests/guide/understanding/test_category_profile_parsing.py` =
    `de956b93d7d6fda41a48f211ffd4f6a1f6244346`
  - `tests/guide/intent/test_task_planning.py` =
    `c152a81edbf1acc0081a926d33c6a7492bc2ed7a`
  - `tests/guide/application/test_formal_chat_router_http.py` =
    `b648b3f331c5eabd34127557556bcce83bb92cbd`
- Focused, full, boundary, and browser results: not run; this was a
  design-only verification and no pass is claimed. Production/data hashes
  are unchanged because no business code, tests, or data assets were edited.
- The verification was performed directly against the frozen source. No
  standalone report path or report hash exists, and none is invented here.

### Findings

1. **P1 - Negative compounds and direct positive predicates lack a complete
   boundary.** `_CATEGORY_COORDINATED_POSITIVE_TURN` currently recognizes
   only `还是想买/要买/想要` and `改买`. Task 25 requires direct positive
   predicates after a conjunction, and Task 26 must cover the full direct set
   `想买/想要/要买/推荐/改买`. A simple predicate expansion is unsafe:
   `并不想买`, `并非要买`, `想要避开的香水`, `推荐避雷香水`, and
   `想买但不买香水` are explicitly negative and must not restore fragrance.
   The RED matrix must prove both the direct-positive and negative-compound
   sides through understanding, task planning, and formal HTTP/SSE.
2. **P2 - A final repeated-category negation can lose to an earlier positive
   occurrence.** In `不考虑防晒并改买香水但不要香水`, the first fragrance
   occurrence can remain in `positive_matches` even when the final repeated
   fragrance occurrence is negated. The final explicit negation must dominate
   the earlier restoration, with regression coverage at every required layer.
3. **P2 - Formal positive-route coverage is SSE-only.**
   `test_coordinated_positive_turns_use_formal_fragrance_route` posts only to
   `/api/v1/chat/stream`, while the coordinated-negation matrix covers both
   `/api/v1/chat/message` and `/api/v1/chat/stream`. Task 26 must add the
   missing non-stream HTTP assertions and keep HTTP/SSE behavior aligned.

- Task 26 is open and depends on Task 25. Tasks 23, 25, and 26 remain
  unchecked; there is no new completion disposition.
- This checkpoint changes only the four authorized task/checklist/audit
  documents. Business code, tests, protected paths, and data assets are
  unchanged. No push, deployment, or traffic switch was performed.

## 2026-08-10 - Round 9 Task 23 And 25-32 Integration Checkpoint

- Integration base:
  `29db49771c3e50ea69f99321309d4060d7da4a4c`.
- Final production/test checkpoint:
  `3981ff8a2f6aca96e59ff083e40b9994695daddd`.
- Documentation checkpoint: `SELF`.
- The shared formal matrix was committed before the domain integrations as
  `7bba0e00b7ec327729e0b81964098ac54b172df6`, stable patch ID
  `7e6cf9dc6c6ce29fd9665056cef98795c2a089cb`.
- Existing Task 23 integration was reused from baseline:
  formal commit `ae90462539f757d2160fe23323b19d1dd857e839`,
  stable patch ID `7c0534ffffb96181da008d7bb34981630a8bdf49`; domain source
  `66be64dd3a6fa43c14a22d8a68c5dee6768eeec5` maps to integration
  `9751f95bda2bcc1b696b1581854d475220046cb6`, with matching stable
  patch ID `6ee083a2914e3b3b022ae2f1c2c81fb223805d5c`.

### Task 25-32 Source Mapping

| Task | Source | Integration | Stable patch ID |
| --- | --- | --- | --- |
| 25 | `0860312c53b0fabaedef228de1d4815b3d04f315` | `e206242e8c9f52af6a0788e2c5f89c794711400c` | `877662ea25b775f56fe70e68400cc1e4be3f398a` |
| 26 | `61171f029a4dceef7232f79b248660a04cd232b0` | `76b40af5f50d43d2eace661ac184d11863d81c7a` | `7ffffbc68b1b000504ad58e1d2bb021df4f9b0d0` |
| 27 | `7779472932da3d9a502a5829dd8b782aeccc90e3` | `76f8b2fb4bd1b3594fe8ffad264e291dbb194fd2` | `9ff28a604a02fc938780406171dcf1fbaa3066b4` |
| 28 | `d019dd2049901dd4fe76e5d4952d4c926235eec2` | `90d1624a4da8311a814ba5e5c5669aea06793194` | `e3b7dcb4c05b51a8e95a45842c4a0e20a5a7dcfe` |
| 29 | `9f5cea0439ee3f78b074aceb28a9bdc3786a0c5f` | `eba513ff64e683d868a4ed041e240ecd686d5385` | `1a270f67b6ed935169ea59369b74ff7a72402359` |
| 30 | `344e0e9e42740d4c19f839724d3f23570cd83568` | `afc52d34907446ecc7576d584e657e45e6ed402c` | `62548c8655d458e1a6c72fde325777e5b78160ee` |
| 31 | `76bdad3dea80e25a0ccc83960f9788b87bba8547` | `660d85965c1717d241ce453dbdeec2593bd1dcaa` | `1645e418758fb279b0cc6a10f9cc78231e2a102e` |
| 32 | `b82e60089f3ea80d723fc524a7f62c3d64fdc9ec` | `3981ff8a2f6aca96e59ff083e40b9994695daddd` | `3614632773d863a3237683982c4e799b54980890` |

All eight cherry-picks were applied in the listed order without conflicts.
Every source/integration stable patch ID matched, and no protected path was
touched.

### Shared TDD Evidence

- The shared HTTP/SSE matrix contains `112` parameterized cases across both
  `/api/v1/chat/message` and `/api/v1/chat/stream`. It covers Task 23 pure
  coordinated negation; Task 25's four exact sentences and the complete
  `5 predicates x 4 connectors` equivalence classes; Task 26 negative
  compounds and final negation; Task 27/29 typed attribute clarification;
  Task 28/29 legacy quantifiers; Task 30/32 nested absence with a captured
  real `TaskPlan` and no `ExclusionConstraint`; and Task 31 bare ingredient
  values reaching the real decision consumer as
  `excluded_exclusion_match`.
- RED on old main `29db497`: `72 failed, 40 passed`; failures were the
  expected owner, typed clarification, consumed-span, quantifier, final
  revision, and exclusion-normalization gaps. JUnit:
  `/tmp/xiaoro-round9-formal-red-29db497.xml`.
- GREEN at `3981ff8`: `112 passed in 13.42s`. JUnit:
  `/tmp/xiaoro-round9-formal-green-3981ff8.xml`.

### Final Verification

- Complete formal router file: `243 passed in 35.75s`.
- Final routing focused range
  (`test_category_profile_parsing.py`, `test_task_planning.py`,
  `test_chat_api_adapter.py`, `test_recommendation.py`):
  `1534 passed in 4.05s`.
- Complete contracts/presentation/decision directories:
  `337 passed in 1.06s`.
- compileall: PASS.
- `app/guide` boundary: PASS, zero violations.
- `app/guide_runtime` boundary: PASS, zero violations.
- `git diff --check` and cached diff check: PASS.
- Protected diffs from `a29d727` and `a88d8af`: empty.
- Ranking SHA-256:
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- Approved environment:
  `/private/tmp/xiaoro-guide-runtime-venv/bin/python`, Python `3.11.1`,
  pytest `8.0.0`, FastAPI `0.115.0`, Pydantic `2.8.0`.

### Independent Routing Audit

- Audit profile: `round9-routing-incremental-v1`.
- Range: `29db497..3981ff8`.
- Scope: `2` production files, `193` changed lines:
  - `app/guide/understanding/contracts.py`, blob
    `a04cd8a13109ea40293d9eb84e86ea23d0f0d71e`;
  - `app/guide/understanding/exact_parsing.py`, blob
    `3b900733effa97194a223b682885dc4a54a10279`.
- Scope manifest:
  `/tmp/xiaoro-round9-routing-audit-3981ff8/scope_manifest.txt`.
- Scope manifest SHA-256:
  `0ef16e0438f27f63dcc6f2e0e18e4bf06662fede465b32bcb48e062f719e6ce4`.
- Report:
  `/tmp/xiaoro-round9-routing-audit-3981ff8/report.md`, SHA-256
  `5c0b99729cb9737d14d083a5d723f37ba8dd6806c0003a7ef715e98323b62b51`.
- Result: `P0=0;P1=0;P2=0`.

Tasks 23 and 25-32 and their checklist rows are complete. This is an
integration checkpoint only; no Round 9 final summary was added to the
`.trae` progress document. No push, deployment, traffic switch, protected
path change, or data approval was performed.

## 2026-08-10 - Task 27 Incremental Audit Finding Checkpoint

- Frozen candidate source:
  `61171f029a4dceef7232f79b248660a04cd232b0`, including predecessor
  `0860312c53b0fabaedef228de1d4815b3d04f315`.
- Documentation checkpoint: `SELF`.
- Stable patch ID: not applicable to this read-only finding checkpoint; the
  candidate was not integrated or given a completion disposition here.
- Candidate audit scope:
  - `app/guide/understanding/exact_parsing.py` =
    `1aaf68b1f48f8f4a6206c00db3a7c0609fd06589`
  - `tests/guide/understanding/test_category_profile_parsing.py` =
    `691363e653eaba15990d6cb4ad44f4711b559511`
  - `tests/guide/intent/test_task_planning.py` =
    `c3c7701d12b281c9df8c97d07e5d5c5ced7a8dfc`
  - `tests/guide/application/test_chat_api_adapter.py` =
    `41bd6db5731e390d75d6b74c4f5074ae948e0bbd`
  - unchanged `tests/guide/application/test_formal_chat_router_http.py` =
    `b648b3f331c5eabd34127557556bcce83bb92cbd`
- Focused result: the candidate's understanding, task-planning, and owner
  suites passed `452 passed in 2.37s`.
- Independent semantic audit matrix: `12` representative cases executed;
  `7/12` matched the required topic/task/owner result and `5/12` did not.
  No standalone report path or hash was supplied, so none is asserted here.

### Matrix Results

- Existing explicit-positive controls matched `4/4`: the four Task 25 cases
  `不考虑防晒并想买平价香水`, `不考虑防晒并推荐平价香水`,
  `不考虑防晒且想买平价香水`, and
  `不考虑防晒并且推荐平价香水` resolved to
  `fragrance / recommend / guide_text`.
- Category-negation controls matched `3/3`: `想要避开的香水`,
  `推荐避雷香水`, and `想买但不买香水` resolved to
  `no positive category / clarify / legacy`.
- Attribute-scope cases mismatched `3/3`: `避开甜腻的香水`,
  `不要太甜的香水`, and `不想要太甜的香水` incorrectly resolved to
  `no positive category / clarify / legacy`; each must preserve
  `fragrance / recommend / guide_text`.
- Final-`不推荐` cases mismatched `2/2`:
  `推荐防晒但不推荐防晒` incorrectly resolved to
  `sunscreen / recommend / guide_text`, and
  `不考虑防晒并改买香水但最后不推荐香水` incorrectly resolved to
  `fragrance / recommend / guide_text`. Both must end with no positive
  category and must not use the Guide owner.

### Findings

1. **P1 - Attribute negation is not scope-aware.** The broad `避开`, `不想`,
   and `不要` category cues scan through attribute text to a later category
   alias. This makes requests that exclude a sweet fragrance attribute look
   like requests that exclude the fragrance category. Task 27 must distinguish
   attribute targets from category targets without weakening the three
   category-negation controls.
2. **P1 - `不推荐` is not symmetric with positive `推荐`.** The candidate
   recognizes `推荐` as a positive predicate but does not recognize
   `不推荐` as a category-negation cue. The repeated-topic state therefore
   remains positive instead of honoring the final explicit negation. Task 27
   must make final `不推荐` dominate earlier positive occurrences for both
   same-category and cross-category revisions.
3. **P1 - Formal HTTP/SSE RED/GREEN evidence is missing.** The candidate adds
   parser, task-planning, and `classify_chat_owner` coverage, but the formal
   router test blob is unchanged. Owner-level tests do not prove
   `/api/v1/chat/message` and `/api/v1/chat/stream` behavior. Task 27 must add
   representative positive and negative RED/GREEN matrices to both formal
   endpoints.

- Task 27 is open and depends on Task 26. Tasks 23, 25, 26, and 27 remain
  unchecked; there is no Round 9 completion disposition.
- Full, boundary, and browser suites were not run for this finding
  checkpoint, and no pass is claimed for them.
- This checkpoint changes only the four authorized task/checklist/audit
  documents. Business code, tests, protected paths, and data assets are
  unchanged. No push, deployment, or traffic switch was performed.

## 2026-08-10 - Task 28 Independent Quantifier-Scope Audit Finding

- Frozen integration source:
  `0ee1002590a84973897b91365665e0cdef5870d9`.
- Documentation checkpoint: `SELF`.
- Stable patch ID: not applicable to this documentation-only finding
  checkpoint.
- The independent audit reported one new `P1`. No standalone report path,
  report hash, or executed test transcript was supplied, so none is asserted
  here.

### Finding

1. **P1 - Category quantifiers and class demonstratives must not be treated
   as attribute scope.** A Task 27 scope exception that preserves fragrance
   for an intervening attribute can also overmatch `所有的`, `全部的`,
   `这类的`, or `这种`. `不要所有的香水`, `避开全部的香水`,
   `排除这类的香水`, and `拒绝这种香水` quantify or identify the
   fragrance category itself, so they must remain category-negative and must
   not enter the Guide. This boundary must not regress Task 27's
   attribute-scope controls: `避开甜腻的香水`, `不要太甜的香水`, and
   `不想要太甜的香水` must still preserve positive fragrance intent.

- Task 28 is open, depends on Task 27, and requires understanding,
  task-planning, and owner-routing RED/GREEN for the quantifier cases and the
  Task 27 attribute controls.
- Formal `/api/v1/chat/message` and `/api/v1/chat/stream` evidence was not
  executed for this checkpoint. That evidence gap is not recorded as another
  standalone task: it remains part of the Tasks 25-27 integration, and the
  Task 28 cases must be included in the later unified formal matrix.
- Tasks 23, 25, 26, 27, and 28 remain unchecked; there is no completion
  disposition.
- Focused, formal, full, boundary, and browser suites were not run for this
  documentation-only checkpoint, and no pass is claimed.
- This checkpoint changes only the four authorized task/checklist/audit
  documents. Business code, tests, protected paths, and data assets are
  unchanged. No push, deployment, or traffic switch was performed.

## 2026-08-10 - Task 29 Independent Quantifier/Constraint Audit Findings

- Frozen candidate source:
  `d019dd2049901dd4fe76e5d4952d4c926235eec2`, including attribute-scope
  predecessor `7779472932da3d9a502a5829dd8b782aeccc90e3`.
- Integration documentation source:
  `b2410253ad331ec973320922e5f34d998da61676`.
- Documentation checkpoint: `SELF`.
- Stable patch ID: not applicable to this documentation-only finding
  checkpoint; the candidate was not integrated or given a completion
  disposition here.
- Candidate audit scope:
  - `app/guide/understanding/exact_parsing.py` =
    `62eb054d47e9d8997909421bff68d3c588f2ab43`
  - `tests/guide/understanding/test_category_profile_parsing.py` =
    `ab63ba274a155a90705762eeb8b61890990f77a3`
  - `tests/guide/intent/test_task_planning.py` =
    `bcb467a22f78074e31408f19e054e93e5dbd539e`
  - `tests/guide/application/test_chat_api_adapter.py` =
    `324b4723c8a85eb32b0e61a72a69b8206a0a3f13`
  - unchanged `tests/guide/application/test_formal_chat_router_http.py` =
    `b648b3f331c5eabd34127557556bcce83bb92cbd`
- Reported focused result: the candidate's understanding, task-planning,
  and owner-routing suites passed `581 passed`.
- Independent semantic audit matrix: `14` representative cases were
  evaluated; the supplied summary was 12-of-14 (`12/14`) matched and `2/14`
  mismatched. The audit result was `P0=0;P1=2;P2=0`. No row-level
  transcript, standalone report path, or report hash was supplied, so none
  is asserted here.

### Findings

1. **P1 - The Task 28 category-quantifier set is not synonym-complete.**
   The candidate handles the existing `所有`, `全部`, `这类`, `这种`, and
   `任何` forms, but does not comprehensively normalize `任意的`,
   `每一种的`, `每一款的`, or `一切的`. Task 29 must treat
   `任意的`, `任何的`, `每一种的`, `每一款的`, and `一切的` as
   category targets under each of `不要`, `避开`, `排除`, and `拒绝`.
   Every combination must remain fragrance-category negative and must not
   enter the Guide, consistently with Task 28's existing quantifiers.
2. **P1 - Restoring attribute-scope routing can silently discard the user's
   exclusion.** Candidate `7779472` restores positive fragrance routing for
   attribute exclusions, but `避开甜腻的香水` and
   `不想要太甜的香水` can reach a recommendation plan without a typed
   exclusion constraint. Task 29 must preserve the exclusion semantics in
   the existing authorized `ExclusionDraft`/`ExclusionConstraint` contract.
   If that contract does not authorize the requested property, the result
   must carry an explicit uncertainty/clarification instead of behaving as
   though the exclusion was applied.

- Task 29 is open, depends on Task 28, and requires understanding,
  task-planning, and owner-routing RED/GREEN for both findings.
- Formal `/api/v1/chat/message` and `/api/v1/chat/stream` typed evidence was
  not supplied. The formal router test blob is unchanged, so the reported
  `581 passed` does not establish formal HTTP/SSE behavior. Task 29 must add
  typed RED/GREEN evidence for both endpoints.
- Tasks 23 and 25-29 remain unchecked; there is no Round 9 completion
  disposition.
- Full, boundary, and browser suites were not run for this finding
  checkpoint, and no pass is claimed for them.
- This checkpoint changes only the four authorized task/checklist/audit
  documents. Business code, tests, protected paths, and data assets are
  unchanged. No push, deployment, or traffic switch was performed.

## 2026-08-10 - Task 30 Independent Consumed-Span Audit Findings

- Frozen candidate source:
  `9f5cea0439ee3f78b074aceb28a9bdc3786a0c5f`, based on Task 29 candidate
  `d019dd2049901dd4fe76e5d4952d4c926235eec2`.
- Integration documentation source:
  `9ea706d07ba9e9b6b31a4a702167bb5c8126c8c8`.
- Documentation checkpoint: `SELF`.
- Stable patch ID: not applicable to this documentation-only finding
  checkpoint; the candidate was not integrated or given a completion
  disposition here.
- Independent incremental audit:
  - scope: `d019dd2..9f5cea0`, with regression range
    `9751f95..9f5cea0`
  - files reviewed: `5`
  - changed lines reported: `304`
  - report:
    `/private/tmp/xiaoro_round9_task25_audit/report.md`
  - report SHA-256:
    `197d350c5fd4c9f6eb624233ae11e24bb61d613403375a1acc339f9600c6be17`
  - result: `P0=0;P1=1;P2=1`
- Candidate blobs:
  - `app/guide/understanding/contracts.py` =
    `a04cd8a13109ea40293d9eb84e86ea23d0f0d71e`
  - `app/guide/understanding/exact_parsing.py` =
    `46ab0700397ff438454a220bb50a2febcfd248eb`
  - `tests/guide/understanding/test_category_profile_parsing.py` =
    `5abb4fc11adbaa4a7671bfcca05dbf6f9cf0dcc3`
  - `tests/guide/intent/test_task_planning.py` =
    `4a9f9c36fba907a5e9eea7b51b362d38256dd545`
  - `tests/guide/application/test_chat_api_adapter.py` =
    `0b4f0e7e4d612fa66523a692db875b60bbb06c2f`
  - unchanged `tests/guide/application/test_formal_chat_router_http.py` =
    `b648b3f331c5eabd34127557556bcce83bb92cbd`
- Focused evidence was reproduced read-only on the frozen candidate:
  `tests/guide/understanding/test_category_profile_parsing.py`,
  `tests/guide/intent/test_task_planning.py`, and
  `tests/guide/application/test_chat_api_adapter.py` reported
  `1024 passed in 2.42s`.

### Findings

1. **P1 - Nested negative unsupported attributes are re-consumed as the
   opposite ingredient exclusion.** Candidate `9f5cea0` identifies
   `避开不含酒精的香水` as an unsupported fragrance attribute, but its
   value-based filtering compares normalized target `不含酒精` with
   `_parse_exclusions` output `酒精`. The mismatch leaves both
   `unsupported_attribute_exclusion` and `ExclusionDraft("酒精")`;
   task planning then creates `ExclusionConstraint("酒精")` before
   clarification. Task 30 must establish consumed-span ownership: text
   already consumed as a category target or unsupported attribute cannot be
   parsed again as a generic exclusion. `避开不含酒精的香水`, and
   equivalent `不要`/`不想要` plus `无酒精`/`无香精` forms, must keep
   Task 29's typed uncertainty/clarification without any reversed ingredient
   exclusion.
2. **P2 - Category quantifier spans leak non-domain exclusions.** The
   category quantifier is intentionally excluded from unsupported-attribute
   targets, then `_parse_exclusions` re-consumes it. For example,
   `不要所有香水` yields `ExclusionDraft("所有")`, and planning compiles
   the same non-domain hard constraint. The current owner remains legacy and
   the plan clarifies, so recommendation execution is not reached, but the
   structured understanding/planning contracts are polluted. Task 30 must
   assert that Task 28/29's full quantifier matrix produces neither
   `ExclusionDraft` nor `ExclusionConstraint` for `所有` or any equivalent
   quantifier/class term.

### Required RED/GREEN Matrix

| Class | Representative text | Understanding/task plan | Owner and both formal endpoints |
| --- | --- | --- | --- |
| Unsupported nested negative attribute | `避开不含酒精的香水`; equivalent `不要`/`不想要` and `无酒精`/`无香精` forms | fragrance + `unsupported_attribute_exclusion`; clarify; no `ExclusionDraft`/`ExclusionConstraint` | Guide-owned typed clarification with no products on `/message` and `/stream` |
| Category quantifier/class target | `不要所有香水`; full Task 28/29 cue x quantifier x optional `的` matrix | no positive category; clarify; no quantifier Exclusion | legacy-owned on `/message` and `/stream`; no Guide category profile or products |
| Ordinary ingredient exclusion control | `不要含酒精的香水` | fragrance + alcohol `ExclusionDraft`/`ExclusionConstraint`; no unsupported-attribute uncertainty | Guide-owned typed recommendation on `/message` and `/stream`, preserving the alcohol exclusion |

- Task 30 is open and depends on Task 29. Every matrix row requires
  understanding, task-planning, owner-routing, and formal endpoint
  RED/GREEN.
- Formal `/api/v1/chat/message` and `/api/v1/chat/stream` evidence is still
  missing. The unchanged formal router blob means `1024 passed` covers only
  focused understanding/planning/owner routing.
- Tasks 23 and 25-30 remain unchecked; there is no Round 9 completion
  disposition.
- Full, boundary, runtime, and browser suites were not run for this
  documentation checkpoint, and no pass is claimed for them.
- This checkpoint changes only the four authorized task/checklist/audit
  documents. Business code, tests, protected paths, and data assets are
  unchanged. No push, deployment, or traffic switch was performed.

## 2026-08-10 - Task 31 Ingredient-Exclusion Normalization Finding

- Frozen candidate source:
  `344e0e9e42740d4c19f839724d3f23570cd83568`, based on Task 30 candidate
  `9f5cea0439ee3f78b074aceb28a9bdc3786a0c5f`.
- Integration documentation source:
  `562b2277814e3edb80f902f9f2737c30d72ba60d`.
- Documentation checkpoint: `SELF`.
- Stable patch ID: not applicable to this documentation-only finding
  checkpoint; the candidate was not integrated or given a completion
  disposition here.
- Independent incremental audit:
  - candidate scope: `9f5cea0..344e0e9`
  - regression range: `9751f95..344e0e9`
  - production files reviewed: `2`
  - production changed lines reported: `185`
  - report:
    `/private/tmp/xiaoro-round9-task25-routing-audit/report.md`
  - report SHA-256:
    `2a3d371c312bd830e59f5f74c46efa82c48bfc160058fb741c95d050bdefa5ff`
  - result: `P0=0;P1=1;P2=0`
- Candidate blobs:
  - `app/guide/understanding/exact_parsing.py` =
    `788f709fc522263dbf4a33614fcb66c10287958d`
  - `tests/guide/understanding/test_category_profile_parsing.py` =
    `71c97235ad23c86bfda9affe26b6f99406d1cef0`
  - `tests/guide/intent/test_task_planning.py` =
    `10f60d23501d615996f579cc227f47f77e7a2b97`
  - `tests/guide/application/test_chat_api_adapter.py` =
    `585302f6819fc5e3384d5a074bd5cb2c738fc6ee`
  - unchanged `tests/guide/decision/test_recommendation.py` =
    `843738be2c76dbbbe0c4d6b5c5ba7b259380a07e`
  - unchanged `tests/guide/application/test_formal_chat_router_http.py` =
    `b648b3f331c5eabd34127557556bcce83bb92cbd`
- Supplied candidate verification evidence reported focused
  understanding/planning/owner/decision-consumer coverage at `1354 passed`
  and formal coverage at `191 passed`.

### Finding

1. **P1 - Ordinary `不要有` ingredient exclusions retain the existence
   predicate and fail the hard exclusion.** Candidate `344e0e9` correctly
   treats `不要有酒精的香水` as an attribute exclusion rather than a
   fragrance-category negation, but generic exclusion parsing consumes only
   `不要`. Understanding therefore emits `ExclusionDraft("有酒精")`, and
   task planning compiles `ExclusionConstraint("有酒精")`. The decision
   consumer checks that full value against ingredient evidence; a product
   containing `酒精` consequently returns `excluded_evidence_unknown`
   instead of `excluded_exclusion_match`. The same normalization boundary
   applies to `香精`.

### Required RED/GREEN Matrix

| Class | Representative text | Understanding/task plan | Owner/decision/formal result |
| --- | --- | --- | --- |
| Existence-predicate ingredient exclusion | `不要有酒精的香水` | fragrance + exactly `ExclusionDraft("酒精")` and `ExclusionConstraint("酒精")`; never `"有酒精"` | Guide-owned; a candidate containing alcohol is `excluded_exclusion_match`; representative `/message` and `/stream` verification |
| Existence-predicate ingredient exclusion | `不要有香精的香水` | fragrance + exactly `ExclusionDraft("香精")` and `ExclusionConstraint("香精")`; never `"有香精"` | Guide-owned; a candidate containing fragrance is `excluded_exclusion_match`; representative `/message` and `/stream` verification |
| Existing cue regressions | `不要含`/`不含`/`不能有`/`无` + `酒精` or `香精` + `的香水` | each cue normalizes to the bare ingredient in both typed contracts | Guide-owned; decision consumer preserves exact-match exclusion behavior |

- Task 31 is open and depends on Task 30. Understanding, task-planning,
  owner-routing, and decision-consumer layers each require explicit RED then
  GREEN coverage.
- The supplied `1354 passed` and `191 passed` results predate Task 31
  coverage. In particular, the formal router blob is unchanged and contains
  no `不要有酒精的香水` or `不要有香精的香水` representative, so those
  green counts are regression evidence and do not clear the P1.
- Tasks 23 and 25-31 remain unchecked; there is no Round 9 completion
  disposition.
- Full, boundary, runtime, and browser suites were not run for this
  documentation checkpoint, and no pass is claimed for them.
- This checkpoint changes only the four authorized task/checklist/audit
  documents. Business code, tests, protected paths, and data assets are
  unchanged. No push, deployment, or traffic switch was performed.

## 2026-08-10 - Task 32 Nested-Absence Cartesian Audit Finding

- Frozen candidate source:
  `76bdad3dea80e25a0ccc83960f9788b87bba8547`, based on Task 31 candidate
  `344e0e9e42740d4c19f839724d3f23570cd83568`.
- Integration documentation source:
  `59536f8591ec5a4a7cc7538259fbd6ec7e4489ba`.
- Documentation checkpoint: `SELF`.
- Stable patch ID: not applicable to this documentation-only finding
  checkpoint; the candidate was not integrated or given a completion
  disposition here.
- Independent incremental audit:
  - candidate scope: `344e0e9..76bdad3`
  - regression range: `9751f95..76bdad3`
  - files reviewed: `10`
  - changed lines reported: `1335`
  - report:
    `/private/tmp/xiaoro-round9-task25-audit/report.md`
  - report SHA-256:
    `d36cd64226f4d6429293a371185034670d31ace6ba74489a5e2d5d93b529dfd1`
  - result: `P0=0;P1=1;P2=0`
- Candidate blobs:
  - `app/guide/understanding/exact_parsing.py` =
    `5a4bf6e4309d5bb4f889bd5d5dc4a9f945d01bf3`
  - `tests/guide/understanding/test_category_profile_parsing.py` =
    `bc7bdd8f1940c2e5493bc2e58af546f6b632cfe7`
  - `tests/guide/intent/test_task_planning.py` =
    `7711f3254c0d5196e44e43669a6ac7e830890725`
  - `tests/guide/application/test_chat_api_adapter.py` =
    `f9e662725c10d92684f568a7a807abeeb8f6cec7`
  - `tests/guide/decision/test_recommendation.py` =
    `f3c1e8adac99f6cb0c04cf5bb39a89a5827f7adb`
  - unchanged `tests/guide/application/test_formal_chat_router_http.py` =
    `b648b3f331c5eabd34127557556bcce83bb92cbd`
- Supplied candidate verification evidence reported `1438 passed` for the
  focused understanding/planning/owner/decision suite, `131 passed` for the
  formal router suite, and `35 passed` for the additional targeted matrix.

### Finding

1. **P1 - The new `不要有` normalization bypasses consumed nested-absence
   spans and reverses the user's constraint.** Candidate `76bdad3` correctly
   normalizes ordinary `不要有酒精的香水` to a bare alcohol exclusion, but
   treating `不要有` as a generic negation while also treating every
   `不要有...` category cue as negative leaves the nested attribute outside
   `_category_exclusion_targets` span ownership.
   `不要有不含酒精的香水` and `不要有无酒精的香水` therefore retain
   fragrance, emit `ExclusionDraft("酒精")` and
   `ExclusionConstraint("酒精")`, expose no uncertainty, and recommend.
   A candidate containing alcohol is then hard-excluded as
   `excluded_exclusion_match`. This reverses “exclude alcohol-free perfume”
   into “exclude alcohol” and violates Tasks 29-30.

### Required Cartesian RED/GREEN Matrix

The nested-absence matrix is:

```text
outer cue:
  避开 | 不要 | 不想要 | 排除 | 拒绝 | 不要有
× inner absence:
  不含 | 无
× ingredient:
  酒精 | 香精
× explicit category
```

This is 24 cases per category representative. The category dimension must be
explicitly frozen and include `香水` at minimum.

| Class | Required understanding/task plan | Required owner/decision/formal behavior |
| --- | --- | --- |
| Full nested-absence Cartesian matrix | retain the explicit category; emit typed `unsupported_attribute_exclusion`; no `ExclusionDraft` or `ExclusionConstraint`; plan is clarify | Guide-owned typed clarification; no recommendation decision or products |
| Ordinary ingredient-exclusion controls | `{不要有, 不要含, 不含, 不能有, 无}` × `{酒精, 香精}` × category emits exactly the bare ingredient in both typed exclusion contracts; no uncertainty | Guide-owned recommendation; a candidate containing the ingredient reaches `excluded_exclusion_match` |

- Understanding, task planning, owner routing, and the decision consumer each
  require explicit RED followed by GREEN for the complete Cartesian matrix
  and the ordinary controls.
- Formal `/api/v1/chat/message` and `/api/v1/chat/stream` do not need to
  duplicate every Cartesian row, but their typed representative set must
  include both audit reproductions and collectively cover every outer cue,
  both absence forms, both ingredients, and the frozen category dimension.
  Each nested representative must clarify with zero products and no reversed
  ingredient exclusion.
- Task 32 is open and depends on Task 31. The reported `1438/131/35` green
  counts predate Task 32 coverage and do not clear the P1; the unchanged
  formal router blob has no Task 32 representative.
- Tasks 23 and 25-32 remain unchecked; there is no Round 9 completion
  disposition.
- Full, boundary, runtime, and browser suites were not run for this
  documentation checkpoint, and no pass is claimed for them.
- This checkpoint changes only the four authorized task/checklist/audit
  documents. Business code, tests, protected paths, and data assets are
  unchanged. No push, deployment, or traffic switch was performed.

## 2026-08-10 - Round 9 Final Closure Handoff

- Product code checkpoint and writable closure parent:
  `af1faf41ff6f91caa97611a312b154fbadd0f7fd`.
- Documentation closure commit: `SELF` (the commit containing this
  checkpoint). Tasks and checklist each have `0` unchecked rows.
- Formal TDD evidence is RED `72 failed, 40 passed` at `29db497` and GREEN
  `112 passed` at `3981ff8`; the complete formal router passed `243`.
  Final focused verification passed `2084`, Guide full passed `3890` with
  one existing Pydantic warning, and runtime full passed `187`.
- The exact locked `UV_OFFLINE` commands did not start tests because the
  cache lacked the Pillow `10.4.0` CPython `3.12` arm64 wheel; this is
  classified `ENVIRONMENT`. The approved Python `3.11.1` / pytest `8.0.0`
  environment supplied the passing Guide and runtime results.
- Browser verification passed `7/7` shards and `20/20` scenario classes with
  `13` screenshots. Page, console, SSE, server transport, unexpected HTTP
  5xx, image, cross-session, late-event, and XSS metrics are all `0`.

### Final Evidence

```text
Guide:
  /private/tmp/xiaoro-round9-final-guide-af1faf4
  SHA256SUMS.txt SHA-256:
  a3b0969b6399d54f239f884367e765f7c70ba360fdfc449520842828666cb280
Focused/data:
  /private/tmp/xiaoro-round9-final-data-af1faf4
  evidence-sha256.txt SHA-256:
  eeea1edb7643bd543f00e61b29e7812e381073c807d1e8ef46b47d0de3c36157
Runtime/static:
  /private/tmp/xiaoro-round9-final-runtime-static-af1faf4
  SHA256SUMS SHA-256:
  863467e095aec0dab2f81e5b86f17b2976aadb91c12e86eb1b283b9a4ebe6427
Browser:
  /private/tmp/xiaoro-round9-final-browser-af1faf4
  evidence-manifest.sha256 SHA-256:
  245d0436b9261c45854cf5749b975799a6bd5e9dac080372dc9d64e89b56cbe9
  summary.json SHA-256:
  3069cda74c2833262357de1d4ba8d17462d0211aee3c115b5f5d1bc2ebddae13
```

### Data Disposition

- Production remains `fact_count=0`, `approved=0`, `unknown=114`,
  `conflict=0`; category candidates remain `7 pending + 12 quarantine`.
- Review candidates remain `2 pending + 4 quarantine`. The six approved
  review sources still cover products `42`, `49`, and `55`, two each.
  Historical `336/111` remains `not_rerun` provenance.
- Category asset and manifest raw SHA-256 values remain
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
  and
  `dc528a034779559e0ac9b6444f1b0365e3041478d71ebbc703da3aaaf0e6179c`.
- Review asset and manifest raw SHA-256 values remain
  `22bac50e053a621826c831565b3a18e1df3592049ac35377298bac0ab0536171`
  and
  `2d4acdb1251e1b65d2b92fb2b052734f58b56cd4cd558e783c0391432c630460`.

### Audit And Protection

- The final independent read-only routing audit used profile
  `round9-routing-incremental-v1` and scope manifest SHA-256
  `0ef16e0438f27f63dcc6f2e0e18e4bf06662fede465b32bcb48e062f719e6ce4`.
  Its deterministic audit key is
  `547547839b0c85cebb677dbbc259fb430eaf784c4e91777a1fdb18acd2c4ed13`.
  Result: `P0=0;P1=0;P2=0`, `full_file_invocations=0`.
- Source `b82e600` and integration `3981ff8` have identical production blobs:
  `contracts.py=a04cd8a13109ea40293d9eb84e86ea23d0f0d71e` and
  `exact_parsing.py=3b900733effa97194a223b682885dc4a54a10279`.
  Checkpoint `af1faf4` retains the same blobs.
- Task 24 remains cleared with corrected 42-file scope
  `9bd6fbef8072acfb770af95bdcead537a11e0c262ee85092c859ae177bdb14e1`
  and real reader blob
  `4db1174c053b3fcb33aa1b7f4da9122969433467`;
  its targeted verification used `full_file_invocations=0`.
- Protected diffs from `a29d727` and `a88d8af` are empty. Ranking SHA-256
  remains
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.

No push, deployment, traffic switch, protected-path edit, data approval, or
business-code change was performed. Remaining release work is limited to
explicit authorization for push/deployment/traffic switch and the existing
future delivery ID plus ACK/query/retry protocol.
