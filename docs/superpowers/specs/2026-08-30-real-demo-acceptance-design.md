# Real Demo Acceptance Design

**Status:** Approved for implementation on 2026-08-30

## Goal

Prove that XiaoRo produces useful results for the seven user-facing Guide
entry modes through the real semantic provider, real backend, real SSE
transport, and real browser. Repair reproducible defects at their earliest
shared owner until the bounded Demo acceptance suite passes.

This replaces the earlier inference that architectural correctness and
fixture screenshots were sufficient evidence for Demo readiness.

## Delivery Boundary

The target is a controlled Demo release, not zero-variance production.

The required entry modes are:

1. explore recommendation
2. fit recommendation
3. product knowledge
4. comparison
5. image identity
6. image fit recommendation
7. image comparison

Each mode is exercised as a continuous trajectory containing an initial
request, a contextual follow-up, and a correction or refinement. The bounded
suite therefore covers exactly twenty-one real turns instead of seven
isolated first turns.

The suite does not attempt arbitrary prompt fuzzing or exhaustive production
stability sampling.

## Definition Of Real

A business-result turn is real only when all of the following are true:

- the browser submits the visible user text or image through `/api/v1/chat/stream`;
- semantic translation uses the configured DeepSeek provider;
- product identity, facts, prices, and images come from the candidate's real
  canonical assets;
- the production Guide route, processor, reducer, CAS, and SSE envelope run;
- the shipped `app/static/chat.html` consumes the exact emitted SSE bytes;
- terminal DOM, browser console, network observations, and screenshot are
  captured from that request.

Synthetic presentation fixtures remain useful for renderer unit tests, but
they cannot authorize Demo GO.

## Acceptance Model

### Business usefulness

Every successful terminal must be structurally valid and useful.

- Recommendations show the requested number of available products, use the
  correct category and budget, and expose at least one fact-backed reason per
  visible product.
- Product knowledge answers the asked field or returns a precise evidence-gap
  statement. A generic empty answer is a failure.
- Comparisons show at least two meaningful fact-backed dimensions. A table
  whose effective cells are all `unknown` or `尚未确认` is a failure.
- Image identity binds the current upload to the displayed product.
- Image recommendation and image comparison preserve current-upload
  ordinals and never substitute persisted images silently.
- Follow-ups preserve the intended candidate, image, profile, and budget
  context. Corrections replace only the named constraint.

### Browser quality

Every terminal must have:

- no `GUIDE_RESPONSE_CONTRACT_INVALID`, internal error, or raw internal
  language;
- no duplicate answer owner or repeated card surface;
- no wrong product, image, price, or specification binding;
- no text overlap, clipped controls, or unusable mobile layout;
- one terminal presentation owned by the emitted public contract.

### Bounded provider policy

A provider transport failure may be retried once. A deterministic fallback is
acceptable for Demo only when the final result remains fact-backed and useful.
A clear request becoming an unrelated clarification, a wrong binding, an
empty result, or an internal error remains a hard failure.

Repeated sampling to obtain a lucky green result is forbidden.

## Generic Comparison Repair

The current contract correctly preserves
`requested_comparison_dimensions` as dimensions explicitly requested by the
user. That field must not be overloaded with inferred defaults.

`plan_comparison_rows()` will select display rows in two modes:

1. When the user names dimensions, preserve those dimensions in user order.
2. When the user asks for a generic comparison, select up to three
   category-appropriate dimensions that have publishable evidence for the
   compared products.

Category priorities are deterministic:

| Category | Default comparison priority |
|---|---|
| skincare | efficacy, texture, reference_price |
| suncare | spf_pa, texture, water_resistance, reference_price |
| base_makeup | finish, coverage, longevity, texture, reference_price |
| color_makeup | finish, coverage, texture, reference_price |
| cleanser | cleansing_power, texture, suitable_skin, reference_price |
| fragrance | fragrance_family, concentration, longevity, reference_price |

`brand_main` and `profile_match` are optional rows. They are shown only when
they contain evidence-backed values instead of being unconditional empty
decoration.

The public contract continues to expose the exact user-requested dimensions.
Its row validation changes from exact equality with a hard-coded
`brand_main + requested + profile_match` list to these rules:

- row dimension IDs are ordered and unique;
- every explicitly requested dimension occurs exactly once and in user order;
- every row preserves visible product order;
- generic comparisons contain at least two useful fact-backed rows;
- explicit evidence gaps may remain unknown, but generic default rows may not
  be all unknown.

A generic comparison does not authorize a winner. Without an explicit user
priority, profile requirement, or relative requirement, the public winner
remains `insufficient` even when the table contains useful descriptive facts.

No sentence, product ID, alias, or screenshot-specific branch is allowed.

## Real Trajectory Runner

The existing mainline browser audit remains the single browser execution
engine. It gains a Demo trajectory set rather than a second browser
implementation.

Seven trajectories run against a clean state root and unique browser origin.
Each trajectory keeps one session across its turns. The runner stores, per
turn:

- request payload;
- exact raw SSE;
- presentation contract;
- terminal DOM summary;
- console and network observations;
- screenshot;
- usefulness evaluation.

Desktop executes every real business turn. Mobile re-renders the exact
captured real SSE through the shipped frontend so layout validation is not
confounded by another provider sample. The final terminal for each mode is
reviewed on desktop and mobile, producing fourteen manual review rows.

## Automatic Repair Loop

The executor does not pause for ordinary failures.

For each reproducible failure:

1. preserve the failing SSE, DOM, network, console, and screenshot;
2. classify the earliest owner;
3. write a failing class-level regression test;
4. verify the test fails for the observed reason;
5. implement the minimum shared-owner repair;
6. run the focused tests;
7. rerun the affected real trajectory;
8. rerun all seven trajectories before declaring GO.

Owner classification is:

| Failure | Earliest owner |
|---|---|
| wrong meaning or responsibility | semantic translation contract |
| missing default task behavior | task planning policy |
| known facts omitted from output | presentation packet/planning |
| public SSE authorities disagree | execution/public envelope |
| correct contract rendered incorrectly | frontend renderer |
| follow-up loses or corrupts context | reducer/state owner |

Frontend code is changed only when the terminal contract is correct and the
DOM is wrong.

## Stop Rules

Execution continues without user approval for ordinary defects and bounded
retests. It stops only for:

- missing or revoked credentials;
- destructive data or repository operations requiring consent;
- an external dependency that remains unavailable;
- a required repair that would change this approved delivery boundary.

Provider randomness alone is not a reason to start an unbounded repair loop.

## GO Criteria

Demo GO requires:

- all seven trajectories complete;
- every required turn passes business-usefulness checks;
- zero wrong product or image bindings;
- zero internal or terminal contract errors;
- zero state corruption across follow-ups;
- fourteen final desktop/mobile screenshot reviews pass;
- focused and affected regression suites pass;
- debug instrumentation is removed after the active debug-session cleanup
  gate is satisfied.

Strict production release status remains independent and may remain NO_GO.
