# General Knowledge Retrieval Stability Report

Date: 2026-08-31

Status: PASS

## Published Corpus

- Schema: `guide-general-knowledge-v2`
- Manifest SHA-256:
  `b51a789c718a2193512b847a21590c9a45ad42cfb293c978abab3d72bc5f8cde`
- Blocks SHA-256:
  `8774da2a540b7fa43fa0601b19feb76eb1668f04233afab3881d0d6a84e6a683`
- Source documents: 22
- Published reviewed blocks: 209
- Audited candidates: 241

## Deterministic Retrieval

Evidence:
`docs/audits/general-knowledge/retrieval-stability/deterministic/`

- Cases: 28
- Represented source topics: 22
- Recall@3: 100%
- Wrong-topic citations: 0
- Wrong-section citations: 0
- Entity coverage failures: 0
- Relation coverage failures: 0
- Deterministic mismatches: 0
- Expected no-hit results: 1 (`gk-no-hit-weather`)

## Real Acceptance

Evidence:

- `docs/audits/general-knowledge/retrieval-stability/real-run-01/`
- `docs/audits/general-knowledge/retrieval-stability/real-run-02/`

Both consecutive DeepSeek, backend, SSE, and browser runs passed:

- Trajectories per run: 6
- Passed turns per run: 6/6
- Wrong responsibilities: 0
- Wrong knowledge sources: 0
- Wrong knowledge sections: 0
- Coverage mismatches: 0
- Frontend contract violations: 0
- Console errors: 0

## Regression

- Full pytest: 9321 passed, 5 warnings
- Architecture and anti-patch gates: 169 passed
- Python compile check: passed
- Git whitespace check: passed

## Boundaries And Remaining Gaps

- No text-vector retrieval path was added.
- The existing single dispatcher and single `GeneralKnowledgeRetriever`
  remain authoritative.
- No production branch uses a question sentence, case ID, source block ID,
  or knowledge ID as a condition.
- Answers and visible citations remain bound to reviewed knowledge blocks.
- The corpus has no direct reviewed compatibility evidence for some
  ingredient pairs, including niacinamide plus retinol. These requests
  return the reviewed per-ingredient evidence and an explicit compatibility
  evidence gap instead of deriving an unsupported conclusion. This is an
  honest corpus gap, not a retrieval failure.
