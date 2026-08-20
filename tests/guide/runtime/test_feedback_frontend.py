import json
import subprocess
from pathlib import Path


CHAT_HTML = Path("app/static/chat.html")


def _function_source(
    html: str,
    signature: str,
    next_signature: str,
) -> str:
    start = html.index(signature)
    end = html.index(next_signature, start)
    return html[start:end]


def _run_node(script: str) -> object:
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _feedback_sources(html: str) -> str:
    signatures = (
        (
            "function createFeedbackIdempotencyKey()",
            "\n\n        function normalizeFeedbackTarget",
        ),
        (
            "function normalizeFeedbackTarget(receipt)",
            "\n\n        function feedbackOperationIdentity",
        ),
        (
            "function feedbackOperationIdentity(",
            "\n\n        async function submitTypedFeedback",
        ),
        (
            "async function submitTypedFeedback(",
            "\n\n        function feedbackTargetForElement",
        ),
        (
            "function feedbackTargetForElement(element)",
            "\n\n        // 评分星星交互",
        ),
    )
    return "\n".join(
        _function_source(html, start, end)
        for start, end in signatures
    )


def test_frontend_uses_typed_feedback_endpoint_for_all_owned_actions() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert "/api/v1/evaluation/feedback" not in html
    assert "/api/v1/chat/sessions/" in html
    assert "eventName === 'feedback_target'" in html
    assert "deferredPanels.feedbackTarget = feedbackTarget" in html
    assert "eventType: 'click'" in html
    assert "eventType: 'favorite'" in html
    assert "eventType: 'compare'" in html
    assert "eventType: 'negative_feedback'" in html
    assert "owner:" not in _function_source(
        html,
        "async function submitTypedFeedback(",
        "\n\n        function feedbackTargetForElement",
    )
    assert "session_id:" not in _function_source(
        html,
        "async function submitTypedFeedback(",
        "\n\n        function feedbackTargetForElement",
    )


def test_feedback_retry_reuses_one_cryptographic_idempotency_key() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    sources = _feedback_sources(html)
    result = _run_node(
        f"""
const {{ webcrypto }} = require('node:crypto');
const crypto = webcrypto;
const feedbackOperations = new Map();
const feedbackTargetsBySession = new Map();
let currentSessionId = 'session-a';
function getSessionId() {{ return currentSessionId; }}
const requests = [];
let attempt = 0;
async function fetch(url, options) {{
  requests.push({{ url, body: JSON.parse(options.body) }});
  attempt += 1;
  if (attempt === 1) throw new Error('temporary network failure');
  return {{
    ok: true,
    async json() {{
      return {{
        event_id: 'feedback_event_0123456789abcdefghijklmn',
        event_type: 'favorite',
        occurred_at: '2026-08-09T05:30:00Z',
      }};
    }},
  }};
}}
{sources}
const receipt = normalizeFeedbackTarget({{
  conversation_version: 4,
  displayed_product_ids: [91, 38],
  profile_version: null,
}});
feedbackTargetsBySession.set('session-a', receipt);
const submission = {{
  sessionId: 'session-a',
  target: receipt,
  eventType: 'favorite',
  payload: {{ product_id: 91 }},
  operationId: 'favorite:4:91',
}};
(async () => {{
  try {{
    await submitTypedFeedback(submission);
  }} catch (error) {{}}
  const replay = await submitTypedFeedback(submission);
  process.stdout.write(JSON.stringify({{
    keys: requests.map(item => item.body.idempotency_key),
    bodies: requests.map(item => item.body),
    replay,
  }}));
}})();
"""
    )

    assert len(result["keys"]) == 2
    assert result["keys"][0] == result["keys"][1]
    assert result["keys"][0].startswith("feedback_")
    assert "owner" not in result["bodies"][0]
    assert "session_id" not in result["bodies"][0]
    assert result["bodies"][0]["conversation_version"] == 4
    assert result["replay"]["event_type"] == "favorite"


def test_feedback_late_response_does_not_mutate_reactivated_session() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    sources = _feedback_sources(html)
    result = _run_node(
        f"""
const {{ webcrypto }} = require('node:crypto');
const crypto = webcrypto;
const feedbackOperations = new Map();
const feedbackTargetsBySession = new Map();
let currentSessionId = 'session-a';
function getSessionId() {{ return currentSessionId; }}
let resolveFetch;
async function fetch() {{
  return new Promise(resolve => {{ resolveFetch = resolve; }});
}}
{sources}
const receipt = normalizeFeedbackTarget({{
  conversation_version: 4,
  displayed_product_ids: [91, 38],
  profile_version: null,
}});
feedbackTargetsBySession.set('session-a', receipt);
let accepted = 0;
const pending = submitTypedFeedback({{
  sessionId: 'session-a',
  target: receipt,
  eventType: 'click',
  payload: {{ product_id: 91 }},
  operationId: 'click:4:91',
  onAccepted() {{ accepted += 1; }},
}});
currentSessionId = 'session-b';
feedbackTargetsBySession.set('session-b', normalizeFeedbackTarget({{
  conversation_version: 1,
  displayed_product_ids: [55],
  profile_version: null,
}}));
resolveFetch({{
  ok: true,
  async json() {{
    return {{
      event_id: 'feedback_event_0123456789abcdefghijklmn',
      event_type: 'click',
      occurred_at: '2026-08-09T05:30:00Z',
    }};
  }},
}});
(async () => {{
  const response = await pending;
  process.stdout.write(JSON.stringify({{
    accepted,
    ignored: response.ignored,
    currentSessionId,
  }}));
}})();
"""
    )

    assert result == {
        "accepted": 0,
        "ignored": True,
        "currentSessionId": "session-b",
    }


def test_feedback_target_lookup_is_session_and_version_scoped() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    sources = _feedback_sources(html)
    result = _run_node(
        f"""
const {{ webcrypto }} = require('node:crypto');
const crypto = webcrypto;
const feedbackOperations = new Map();
const feedbackTargetsBySession = new Map();
let currentSessionId = 'session-b';
function getSessionId() {{ return currentSessionId; }}
async function fetch() {{ throw new Error('unused'); }}
{sources}
feedbackTargetsBySession.set('session-a', normalizeFeedbackTarget({{
  conversation_version: 4,
  displayed_product_ids: [91, 38],
  profile_version: null,
}}));
feedbackTargetsBySession.set('session-b', normalizeFeedbackTarget({{
  conversation_version: 2,
  displayed_product_ids: [55],
  profile_version: null,
}}));
function element(version) {{
  return {{
    closest() {{
      return {{ dataset: {{ feedbackVersion: String(version) }} }};
    }},
  }};
}}
process.stdout.write(JSON.stringify({{
  foreign: feedbackTargetForElement(element(4)),
  current: feedbackTargetForElement(element(2)),
}}));
"""
    )

    assert result["foreign"] is None
    assert result["current"]["displayed_product_ids"] == [55]


def test_feedback_target_commits_only_after_verified_stream_eof() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    stream = _function_source(
        html,
        "async function sendStreamingMessage(",
        "\n        function buildDetailedProductReason",
    )
    target_branch = stream[
        stream.index("} else if (eventName === 'feedback_target')"):
        stream.index("} else if (eventName === 'products')")
    ]
    discard = stream[
        stream.index("const discardDeferredPanels = () =>"):
        stream.index("const flushDeferredPanels = () =>")
    ]
    eof = stream[stream.index("while (true)"):]

    assert "feedbackTargetsBySession.set" not in target_branch
    assert "deferredPanels.feedbackTarget = null" in discard
    assert "commitFeedbackTarget(" in eof
    assert eof.index("decoder.decode()") < eof.index(
        "commitFeedbackTarget("
    )
    assert eof.index("if (buffer)") < eof.index(
        "commitFeedbackTarget("
    )


def test_post_end_delivery_control_is_explicit_and_fail_closed() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    control_source = _function_source(
        html,
        "function handlePostEndDeliveryControl(",
        "\n\n        function createFeedbackIdempotencyKey",
    )
    result = _run_node(
        f"""
{control_source}
function exercise(data) {{
  const deferredPanels = {{
    feedbackTarget: {{ conversation_version: 4 }},
    products: [91, 38],
  }};
  let discarded = false;
  function discardDeferredPanels() {{
    discarded = true;
    deferredPanels.feedbackTarget = null;
    deferredPanels.products = [];
  }}
  try {{
    handlePostEndDeliveryControl(
      data,
      deferredPanels,
      discardDeferredPanels
    );
    return {{
      error: null,
      discarded,
      feedbackTarget: deferredPanels.feedbackTarget,
      products: deferredPanels.products,
    }};
  }} catch (error) {{
    return {{
      error: error.message,
      discarded,
      feedbackTarget: deferredPanels.feedbackTarget,
      products: deferredPanels.products,
    }};
  }}
}}
process.stdout.write(JSON.stringify({{
  targetFailure: exercise({{
    status: 'feedback_target_persist_failed',
    fatal: false,
  }}),
  conversationFailure: exercise({{
    status: 'conversation_commit_failed',
    fatal: true,
  }}),
  unknown: exercise({{
    status: 'future_delivery_state',
    fatal: false,
  }}),
}}));
"""
    )

    assert result == {
        "targetFailure": {
            "error": None,
            "discarded": False,
            "feedbackTarget": None,
            "products": [91, 38],
        },
        "conversationFailure": {
            "error": "GUIDE_DELIVERY_COMMIT_FAILED",
            "discarded": True,
            "feedbackTarget": None,
            "products": [],
        },
        "unknown": {
            "error": "GUIDE_STREAM_TERMINAL_VIOLATION",
            "discarded": True,
            "feedbackTarget": None,
            "products": [],
        },
    }

    stream = _function_source(
        html,
        "async function sendStreamingMessage(",
        "\n        function buildDetailedProductReason",
    )
    terminal_guard = stream[
        stream.index("const handleSseEvent ="):
        stream.index("if (eventName === 'message')")
    ]
    assert "if (receivedEnd)" in terminal_guard
    assert "eventName !== 'delivery_control'" in terminal_guard
    assert "handlePostEndDeliveryControl(" in terminal_guard
    assert "if (receivedError)" in terminal_guard


def test_feedback_controls_restore_after_switch_and_refresh() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    assert "function getStoredFeedbackTarget(sessionId)" in html
    normalize_source = _function_source(
        html,
        "function normalizeFeedbackTarget(receipt)",
        "\n\n        function getStoredFeedbackTarget",
    )
    lifecycle_source = _function_source(
        html,
        "function getStoredFeedbackTarget(sessionId)",
        "\n\n        function feedbackOperationIdentity",
    )
    lookup_source = _function_source(
        html,
        "function feedbackTargetForElement(element)",
        "\n\n        // 评分星星交互",
    )
    result = _run_node(
        f"""
const stored = {{}};
const localStorage = {{
  getItem(key) {{ return stored[key] ?? null; }},
  setItem(key, value) {{ stored[key] = value; }},
}};
const STORAGE_KEYS = {{ feedbackTargets: 'feedback-targets' }};
const feedbackTargetsBySession = new Map();
const chatMessages = null;
function getSessionId() {{ return 'session-a'; }}
const loadStoredJson = (key, fallback) => stored[key]
  ? JSON.parse(stored[key])
  : fallback;
const saveStoredJson = (key, value) => {{
  stored[key] = JSON.stringify(value);
}};
{normalize_source}
{lifecycle_source}
{lookup_source}
function control(version) {{
  return {{
    removed: false,
    closest() {{
      return {{ dataset: {{ feedbackVersion: String(version) }} }};
    }},
    remove() {{ this.removed = true; }},
  }};
}}
const versionThree = control(3);
const versionFour = control(4);
const root = {{
  querySelectorAll() {{ return [versionThree, versionFour]; }},
}};
commitFeedbackTarget('session-a', {{
  conversation_version: 3,
  displayed_product_ids: [55],
  profile_version: null,
}});
commitFeedbackTarget('session-a', {{
  conversation_version: 4,
  displayed_product_ids: [91, 38],
  profile_version: null,
}});
feedbackTargetsBySession.clear();
restoreFeedbackTargetForSession('session-a', root);
const versionThreeTarget = feedbackTargetForElement(versionThree);
const versionFourTarget = feedbackTargetForElement(versionFour);
clearFeedbackTarget('session-a');
const orphan = control(4);
restoreFeedbackTargetForSession('session-a', {{
  querySelectorAll() {{ return [orphan]; }},
}});
process.stdout.write(JSON.stringify({{
  versionThreeProducts: versionThreeTarget?.displayed_product_ids,
  versionFourProducts: versionFourTarget?.displayed_product_ids,
  versionThreeRemoved: versionThree.removed,
  versionFourRemoved: versionFour.removed,
  orphanRemoved: orphan.removed,
  hasTarget: feedbackTargetsBySession.has('session-a'),
}}));
"""
    )

    assert result == {
        "versionThreeProducts": [55],
        "versionFourProducts": [91, 38],
        "versionThreeRemoved": False,
        "versionFourRemoved": False,
        "orphanRemoved": True,
        "hasTarget": False,
    }
    feedback_source = _function_source(
        html,
        "function addFeedbackButtons(messageWrapper, messageId)",
        "\n\n        // 显示通知",
    )
    activate_source = _function_source(
        html,
        "function activateSession(sessionId)",
        "\n\n        function createFreshSession",
    )
    assert ".addEventListener('click'" not in feedback_source
    assert "data-feedback-message-id" in feedback_source
    assert (
        "chatMessages.addEventListener('click', handleMessageFeedback)"
        in html
    )
    assert "restoreFeedbackTargetForSession(sessionId)" in activate_source
    assert (
        "restoreFeedbackTargetForSession(bootSession.id)"
        in html
    )
