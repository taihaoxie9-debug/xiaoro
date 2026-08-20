# Guide Semantic Model Selection

- decision: NO-GO
- attempt: 3
- cutover_allowed: false
- selected_model: none
- source_sha: 77a7c58f395fcdf8bfc4f8545bdb578cc9f3f8ab
- runner: guide-intent-model-ab-v3
- prompt: guide-semantic-intent-prompt-v7
- schema: guide-semantic-intent-v3
- adapter_enable_thinking: false
- timeout_seconds: 12
- adapter_request_contract: PASS
- case_count: 128
- normalized_result_rows: 256
- case_manifest_sha256: 016c909d71e0f838dd67604ec6f241bdefb7022c69b3cc9c58c602bab1d7482f
- stable_evidence_sha256: 2d9892f686148910d82a88d18d2ee5571b95e66a63a7cca4db1c6bf5f4ef3f77
- runtime_metrics_sha256: 566d5a1d267d8a8361baaa2431af684c89d951c5e19920a1eb67157b19249811
- summary_sha256: e40e1967d9029fe857f612eea4b564709b4dda42be3f93ce5495886c199cd9d3
- pipeline_replay_normalized_sha256: 115e835fc0bb89541f724ee3003351d39d68188476dd804ace2c89c6420094a0
- pipeline_replay_summary_sha256: 6b7ce63a5fd5d920c1e99508318d512ba6a716059f7098434877e4fd1d789dc4
- runner_exit_code: 3
- changed_scope_gates: 1269 passed; 230 passed; 59 passed
- evidence_integrity: PASS
- hard_timeout_triggered: false

## DeepSeek V4-Flash

- model: deepseek-ai/DeepSeek-V4-Flash
- passed: false
- normalized_pass_cases: 67
- failed_cases: 61
- provider_timeout_cases: 1
- schema_invalid_cases: 0
- semantic_mismatch_cases: 60
- schema_valid_cases: 127
- goal_accuracy: 107/128 (83.59375%)
- topic_accuracy: 120/128 (93.75%)
- concern_accuracy: 96/128 (75%)
- observation_accuracy: 115/128 (89.84375%)
- reference_accuracy: 106/128 (82.8125%)
- acts_accuracy: 116/128 (90.625%)
- critical_failure_count: 34
- hard_constraint_override_count: 0/128
- forbidden_field_acceptance_count: 0/128
- invalid_output_task_plan_invocation_count: 0/128
- task_plan_mismatch_count: 3/128
- wrong_product_selection_count: 0/128
- legacy_fallback_count: 0/128
- latency_p50_ms: 1517.254958
- latency_p95_ms: 4175.178375
- usage: UNAVAILABLE (127/128 rows had token usage)
- partial_prompt_tokens: 228076
- partial_completion_tokens: 7016
- partial_total_tokens: 235092
- actual_cost_cny: UNAVAILABLE

## DeepSeek V3.2

- model: deepseek-ai/DeepSeek-V3.2
- passed: false
- normalized_pass_cases: 73
- failed_cases: 55
- provider_timeout_cases: 7
- schema_invalid_cases: 1
- semantic_mismatch_cases: 47
- schema_valid_cases: 120
- goal_accuracy: 110/128 (85.9375%)
- topic_accuracy: 108/128 (84.375%)
- concern_accuracy: 98/128 (76.5625%)
- observation_accuracy: 107/128 (83.59375%)
- reference_accuracy: 104/128 (81.25%)
- acts_accuracy: 111/128 (86.71875%)
- critical_failure_count: 28
- hard_constraint_override_count: 0/128
- forbidden_field_acceptance_count: 0/128
- invalid_output_task_plan_invocation_count: 0/128
- task_plan_mismatch_count: 4/128
- wrong_product_selection_count: 0/128
- legacy_fallback_count: 0/128
- latency_p50_ms: 5377.826375
- latency_p95_ms: 12002.640792
- usage: UNAVAILABLE (120/128 rows had token usage)
- partial_prompt_tokens: 215417
- partial_completion_tokens: 9253
- partial_total_tokens: 224670
- actual_cost_cny: UNAVAILABLE

## Decision

Both frozen models failed the exact all-case semantic gate. V4-Flash passed
67/128 complete rows and V3.2 passed 73/128, so the mechanical decision remains
NO-GO. No default model was selected and Guide-only cutover is forbidden.

The offline pipeline replay reused the recorded real proposals and typed
failure codes. It did not replace real latency or usage evidence. The replay
made all 256 downstream rows observable: hard-constraint overrides,
forbidden-field acceptance, invalid-output TaskPlan invocation, wrong product
selection, and legacy fallback were all zero. The remaining TaskPlan
mismatches are downstream consequences of incorrect semantic proposals.

Raw normalized evidence remains outside Git at:
`/private/tmp/xiaoro-guide-intent-ab-77a7c58-20260812213823-attempt3`.

Pipeline replay evidence remains outside Git at:
`/private/tmp/xiaoro-guide-intent-ab-77a7c58-attempt3-pipeline-replay-20260812215757`.

## Two-Stage Route/Detail Status

- implementation_source: `3ebcb0f9e633e40c4ab8b80ab2ea0a19df4f869a`
- route_contract: PASS
- detail_contracts: PASS
- staged_cache_identity: PASS
- shared_repair_budget: PASS
- maximum_provider_requests_per_case: 3
- smoke_route: 32/32
- smoke_detail: 26/26
- supervised_runner: PASS
- real_two_stage_ab: NOT_RUN
- reason: `GUIDE_LLM_API_KEY=MISSING`
- route_95_percent_gate: UNAVAILABLE
- detail_90_percent_gate: UNAVAILABLE
- unsafe_task_plan_zero_gate: UNAVAILABLE
- selected_model: none
- completion_status: INCOMPLETE

The earlier three attempts above evaluated the retired single-stage semantic
contract and remain immutable historical evidence. They do not satisfy the
new two-stage route/detail gate. No production model is selected until the
supervised two-stage V4-Flash/V3.2 run passes the current layered thresholds.
