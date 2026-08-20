# Pending Turn And Session Lifecycle Design

Date: 2026-08-16

Repository: `/Users/bytedance/Desktop/xiaoro-fresh`

Branch: `rebuild`

## Status

Approved for implementation.

## Goal

Close the current product-identity and multi-turn gaps without changing
long-term profile policy:

1. audit every known product nickname/alias source against the Canonical
   catalog before publishing runtime bindings;
2. preserve exact product, variant, and ambiguous family identity instead of
   silently selecting a convenient SKU;
3. preserve enough structured state to resume an unfinished clarification;
4. resolve short replies such as confirmation, rejection, correction,
   supplementation, and topic replacement deterministically;
5. delete backend short-term state when the user deletes a browser session;
6. prove isolation across refreshes, workers, tabs, and independent sessions.

## Non-Goals

- No long-term profile UI.
- No account/profile selection.
- No new cross-session profile inheritance.
- No LLM-owned state transition.
- No persistence of hidden candidates, ranking output, or chain of thought.
- No raw conversation transcript as decision authority.

## Canonical Product Alias Audit

The runtime alias asset is the published output of a full catalog audit, not
an ad-hoc dictionary of popular examples. Candidate discovery covers:

1. accepted identity relations in the current product-evidence manifest;
2. nicknames embedded in Canonical product names;
3. candidate aliases retained from the legacy repository for review only.

Every discovered surface receives exactly one reviewed disposition:

```text
approved_exact_product
approved_exact_variant
ambiguous_family
marketing_phrase
ingredient_nickname
unavailable_product
unresolved_candidate
```

`approved_exact_product` binds one Canonical product ID.
`approved_exact_variant` additionally carries the reviewed `variant_scope`;
the scope must match an accepted exact-variant evidence block for the same
product. `ambiguous_family` carries all plausible Canonical product IDs and
always returns typed reference clarification unless the message contains a
more specific approved surface. The other dispositions never enter the
runtime resolver.

The audit is fail-closed:

- every accepted evidence nickname relation must be reviewed;
- every published source reference must exist in the current evidence asset
  or be a content hash of the current Canonical asset;
- every bound product ID must exist in the Canonical catalog;
- duplicate normalized surfaces are rejected;
- product-level aliases cannot carry variant scope;
- variant aliases cannot publish without exact-variant evidence;
- generic multi-SKU terms such as `B5`, `菁纯`, `粉水`, and `琥珀` cannot
  silently choose a default SKU;
- marketing positions and ingredient nicknames such as `油皮救星`,
  `冰川蛋白`, and `律波肽` are explicitly excluded from product identity.

The checked-in audit report records candidate source, Canonical candidates,
evidence IDs, scope, disposition, and rationale. A coverage test reruns
discovery so adding products or accepted evidence cannot bypass review.

## Runtime Alias Resolution

The controlled runtime registry uses three identity policies:

```text
exact_product -> resolve one product ID
exact_variant -> resolve one product ID and retain reviewed variant scope
ambiguous_family -> recognize the surface but return ambiguous_reference
```

Longest approved surface wins, so `小棕瓶眼霜` is evaluated before `小棕瓶`.
Contextual clarification terms remain available for versioned defaults such
as generic `小黑瓶`, but aliases with no defensible default are always
clarified. The model may nominate source spans; it never owns product IDs or
variant identity.

## Current Failure

`ClarificationProgress` currently stores only:

```text
gap
attempts
```

For:

```text
干敏肌想要抗初老精华，预算1000左右
```

the system asks whether the range means `900-1100`, but does not retain:

- the original recommendation goal;
- category, skin, and efficacy constraints;
- the proposed budget range;
- the expected reply type.

The next message `是的` is therefore interpreted as a fresh turn and loses
the original task.

## Pending Turn Contract

Add a typed `PendingTurn` to `ConversationSnapshot`.

```text
kind: clarification
gap: budget | topic | goal | reference | concern
attempts: 1..2
source_conversation_version
source_message
expected_response: confirm_or_correct | supply_value
resume_mode: recommendation
resume_context: structured recommendation constraints
proposed_budget: optional exact minimum/maximum
```

`resume_context` contains only approved structured fields:

- category;
- skin;
- efficacy;
- exclusions and inclusions;
- facets and concepts;
- safety-sensitive flag.

It does not contain product IDs, ranking details, model prose, or hidden
candidates.

The first implementation automatically resumes budget clarification for a
recommendation. Other clarification gaps still retain typed source state but
remain explicit supply-value questions until a later focused extension.

## Reply State Machine

When a current-version snapshot owns a pending turn, code classifies the new
message before generic semantic routing:

```text
explicit new task/category
  -> cancel pending turn and process the new message normally

explicit corrected budget
  -> replace proposed budget and resume the original recommendation

affirmative short reply
  -> accept the proposed budget and resume

negative short reply
  -> keep the base task, clear the proposal, ask for an exact range

additional compatible constraints
  -> merge them with the base task and resume when the pending value is
     also resolved

ambiguous short reply
  -> preserve the pending turn and ask one bounded question
```

Affirmation and rejection use bounded exact phrases. They are never inferred
from arbitrary positive or negative sentiment.

## State Priority

For this flow:

```text
current explicit reply
-> pending turn
-> current session state
-> enabled confirmed profile values
-> defaults
```

Current explicit input always wins. A new explicit task cancels the pending
turn, preventing stale clarification from hijacking a topic change.

## Persistence And Delivery

The pending turn is stored in the existing SQLite conversation snapshot.
It uses the existing optimistic CAS version and public-event delivery
transaction. The state is committed only after a valid terminal SSE event is
delivered.

Successful resumption replaces `pending_turn` with the normal successful
recommendation snapshot. Rejection or ambiguity advances the pending turn
without creating product candidates.

## Session Deletion

Extend `ConversationStatePort` with owner-checked deletion:

```text
delete(session_id, expected_owner) -> bool
```

Add:

```text
DELETE /api/v1/chat/sessions/{session_id}
```

The endpoint:

- derives the trusted browser/account owner from the request;
- rejects owner mismatch;
- deletes the conversation snapshot and pending turn;
- does not delete the long-term profile;
- is idempotent when the session does not exist.

The browser waits for this request before removing local history. On a
network/server failure it keeps the history entry and shows a retryable error,
so frontend and backend do not silently diverge.

## Test Matrix

Required tests:

- exact screenshot path: approximate budget -> `是的` -> recommendation;
- affirmative paraphrases;
- rejection -> exact-range question;
- explicit corrected range -> recommendation;
- supplemental compatible constraint;
- explicit new topic cancels pending state;
- ambiguous answer preserves pending state;
- stale conversation version cannot resolve pending state;
- restart/cross-worker continuation;
- two sessions do not share pending state;
- delete removes SQLite and in-memory state;
- owner mismatch cannot delete;
- browser delete waits for backend success;
- browser and real SSE flow pass with no console/network errors.

## Long-Term Profile Boundary

This change neither reads nor writes new long-term profile fields. Deleting a
session deletes only short-term session state. Long-term profile viewing,
editing, opt-in, and account/dossier ownership remain a separate post-launch
design.
