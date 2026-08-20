# Track B Pilot Data Candidate Summary

## Source Recovery

```text
baseline=603e8c4dbf8206d3f963ed174f5397757baf5277
approved_source_roots=2
inventory_status=incomplete
inventory_rejected_entries=23
inventory_file_count=64449
inventory_sha256=1e26747208d3f83c01f4137a9f1faa06a5e2384fc78594c808f23e014e51a0c5
locked_review_sources_found=3
locked_review_sources_missing=0
locked_review_sources_duplicate=0
locked_source_report_sha256=6819dadb23ed38540f24f0849cfec82c4db3a816f23c4a35310b285172f915ae
historical_html_sha_match=3/3
historical_intermediate_336_111=NOT_REPRODUCED
saved_page_parameters=69
saved_page_explicit_reviews=6
```

The inventory covered both user-approved roots. Unsupported entries were
skipped under the bounded inventory contract, so the aggregate status is
`incomplete`; all three locked HTML bytes were still uniquely found by full
SHA-256. No filename, item ID, OCR text, or historical aggregate was used to
claim a source match.

The real Tmall parser bound all three pages to their approved item and SKU
identities and replayed six explicit reviews. The source recovery does not
claim that historical intermediate counts `336/111` were reproduced.

## Candidate Stage

```text
seed_dump_sha256=ae45bbb513868619e578f63f252fff549ad62289aba0d474e2ae65aa754bc386
seed_product_rows=15
seed_database_inputs=59
seed_database_pending=8
seed_database_quarantine=51
seed_database_pending_sha256=bbf05ef0ce61d8df2e1318f5a373bc16e542723274b1768850c1b065f42a0195
seed_database_quarantine_sha256=15b1f4759520955f32a5ead635420d313bdb8c3a28dc158a70e799ebf2af7a71
pilot_status_rows=201
pilot_known=89
pilot_pending=7
pilot_quarantine=19
pilot_unknown=86
pilot_status_sha256=55ea31e3ca28dbfb1e0db8880d1d8306627746cff6230388249bb27e6c343f92
category_pending_rows=9
category_pending_sha256=a7d112716fa90e803f159d23a0a41f17ef7c83a776ca118644f782b25ec08217
category_quarantine_rows=51
category_quarantine_sha256=15b1f4759520955f32a5ead635420d313bdb8c3a28dc158a70e799ebf2af7a71
pilot_matrix_sha256=4a2f02efdc80acf830d05703fd8e548e82da18776c3f8a0684177d2ec8f6dc82
```

Only the exact `COPY public.products (...) FROM stdin;` section was parsed.
Canonical core fields were never emitted as candidates. Explicit official
source tags and bounded saved-page parameter nodes may produce pending
candidates; unbound fields, marketing, Q&A, unauthorized OCR uses, conflicts,
and inapplicable fields remain quarantined or unknown.

Candidate queues, status rows, the source manifest, raw HTML, and the
verification matrix remain local and are not committed.

## Non-Promotion Boundary

```text
candidate_writer_reviewers=0
candidate_writer_approvals=0
candidate_writer_signatures=0
promotion_invocations=0
production_fact_count=0
approved_review_sources=6
```

This checkpoint ends at candidate generation. It creates no verifier
decision, signature, approval, or production write.

## Protected Assets

```text
canonical_manifest=e0430a244af451a3fa73642295c4a79128e1622dfeed19ff8140eda9f2df0c69
canonical_products=0ba95df8c38d39f5bc0d73a32c318b157903abb64778c3e7b0acebfb75e95734
deterministic_ranking=4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f
category_manifest=dc528a034779559e0ac9b6444f1b0365e3041478d71ebbc703da3aaaf0e6179c
approved_review_manifest=2d4acdb1251e1b65d2b92fb2b052734f58b56cd4cd558e783c0391432c630460
approved_reviews=22bac50e053a621826c831565b3a18e1df3592049ac35377298bac0ab0536171
```
