# Frontend Final Renderer Audit v1

Date: 2026-08-19

Scope: final Guide renderer contract before paid copywriter and browser gates.
Desktop and mobile screenshots remain a Task 10 requirement and are not
claimed by this static audit.

## Blocking checks

| Check | Evidence | Result |
|---|---|---|
| Current renderer cache key | `app/static/chat.html:11` | pass |
| Typed presentation validation | `app/static/guide-presentation.js:146-195` | pass |
| One structured main-answer owner | `app/static/chat.html:7215-7242` | pass |
| Legacy image panels suppressed when Guide owns presentation | `app/static/chat.html:6987-7023` | pass |
| Full shelf and pitfalls retain one external owner | `app/static/guide-presentation.js:929-955`, `app/static/chat.html:7039-7053` | pass |
| Current 20-case mode matrix v2 | `tests/fixtures/guide/presentation/frontend_mode_matrix_v2.jsonl:1-20` | pass |
| Product knowledge and image suitability use dedicated duties | `tests/guide/runtime/test_frontend_mode_matrix.py:52-55`, `tests/guide/runtime/test_frontend_mode_matrix.py:165-172` | pass |
| Product title and advisor label use rose | `app/static/chat.html:1507-1514` | pass |
| Ordinary product references inherit body color | `app/static/chat.html:1554-1574` | pass |
| G inline image has intrinsic dimensions and lazy decoding | `app/static/guide-presentation.js:604-607` | pass |
| Full-shelf images have intrinsic dimensions and lazy decoding | `app/static/chat.html:8374-8377` | pass |
| Input, send, and image controls have accessible names | `app/static/chat.html:3161-3168` | pass |
| Product references have visible keyboard focus | `app/static/chat.html:1569-1574` | pass |
| Desktop and mobile input areas honor bottom safe area | `app/static/chat.html:2206`, `app/static/chat.html:3018` | pass |
| Reduced-motion override covers final Guide motion | `app/static/chat.html:1690-1697` | pass |

## Verification

```text
frontend renderer regression: 102 passed
git diff --check: pass
node --check app/static/guide-presentation.js: pass
```

Primary regression guards:

```text
tests/guide/runtime/test_frontend_presentation_stream.py:406
tests/guide/runtime/test_frontend_scope.py:175
tests/guide/runtime/test_frontend_final_format_gate.py:20
tests/guide/runtime/test_frontend_final_format_gate.py:63
```

## Non-blocking follow-up

`app/static/chat.html` still has 12 pre-existing `transition: all` declarations
outside the final Guide controls changed tonight. The approved scope forbids a
global page-shell cleanup before acceptance, so these remain follow-up work.
Actual overlap, clipping, horizontal overflow, image load, console, and
network behavior must still pass the real desktop/mobile browser gate.
