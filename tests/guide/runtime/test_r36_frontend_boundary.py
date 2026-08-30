from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from app.guide.presentation.public_contracts import (
    PublicPresentationContract,
)


CHAT_HTML = Path("app/static/chat.html")
DEMO_HTML = Path("app/static/demo.html")
DEMO_FIXTURE = Path("app/static/guide-demo-fixture.js")
RUNTIME_APP = Path("app/guide_runtime/app.py")
BROWSER_HARNESS = Path(
    "tools/guide_gates/run_mainline_contract_browser_audit.py"
)


def _node_json(script: str) -> object:
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _javascript_function_source(
    source: str,
    signature: str,
    next_signature: str,
) -> str:
    start = source.index(signature)
    end = source.index(next_signature, start)
    return source[start:end]


def _demo_contracts() -> list[dict[str, object]]:
    html = DEMO_HTML.read_text(encoding="utf-8")
    script = html.rsplit("<script>", 1)[1].split("</script>", 1)[0]
    declarations = script[: script.index("const chains =")]
    names = (
        "recommendation",
        "productKnowledge",
        "comparison",
        "imageIdentity",
        "imageRecommendation",
        "imageSuitability",
        "serumRecommendation",
        "serumKnowledge",
        "consultationObservation",
        "profileConfirmation",
        "serumComparison",
    )
    return _node_json(
        "\n".join(
            (
                "global.window = { XiaoRoPresentation: {} };",
                declarations,
                f"process.stdout.write(JSON.stringify([{','.join(names)}]));",
                "})();",
            )
        )
    )


def _fixture_contracts() -> list[dict[str, object]]:
    source = DEMO_FIXTURE.read_text(encoding="utf-8")
    instrumented = source.replace(
        "    const state = new Map();",
        (
            "    root.__XIAORO_SCRIPTED_CONTRACTS__ = ["
            "recommendation, productKnowledge, consultation, "
            "profileConfirmation, comparison, imageIdentity, "
            "imageRecommendation, imageComparison];\n"
            "    const state = new Map();"
        ),
        1,
    )
    return _node_json(
        "\n".join(
            (
                "global.window = global;",
                instrumented,
                (
                    "process.stdout.write(JSON.stringify("
                    "global.__XIAORO_SCRIPTED_CONTRACTS__));"
                ),
            )
        )
    )


def _all_scripted_contracts() -> list[dict[str, object]]:
    return [*_demo_contracts(), *_fixture_contracts()]


def test_chat_query_cannot_enable_fixture_transport() -> None:
    chat = CHAT_HTML.read_text(encoding="utf-8")
    app_source = RUNTIME_APP.read_text(encoding="utf-8")
    route = app_source[
        app_source.index('    @app.get("/chat")') :
        app_source.index('    @app.get("/demo")')
    ]
    harness = BROWSER_HARNESS.read_text(encoding="utf-8")

    assert "guide-demo-fixture.js" not in chat
    assert "GUIDE_DEMO_MODE" not in chat
    assert "XiaoRoDemoFixture" not in chat
    assert "query_params" not in route
    assert "recording_chat_path" not in route
    assert 'page.goto(f"{base_url.rstrip(\'/\')}/chat")' in harness
    assert 'page.route("http://**/*", handle)' in harness
    assert 'page.route("https://**/*", handle)' in harness


def test_offline_fixture_emits_only_production_public_events() -> None:
    source = DEMO_FIXTURE.read_text(encoding="utf-8")
    events_source = _javascript_function_source(
        source,
        "    function eventsForTurn(turn, version) {",
        "    function streamResponse(events) {",
    )

    assert "['message'," not in events_source


def test_demo_contracts_validate_as_public_presentation_contracts() -> None:
    contracts = _all_scripted_contracts()

    assert contracts
    for contract in contracts:
        PublicPresentationContract.model_validate(contract)


def test_send_waits_for_pending_image_reads() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    send_handler = html[
        html.index("sendBtn.addEventListener('click', async () => {") :
        html.index(
            "\n\n        function sendLocalUnclearImageReply",
            html.index("sendBtn.addEventListener('click', async () => {"),
        )
    ]
    wait_source = _javascript_function_source(
        html,
        "async function waitForPendingImageReads()",
        "\n\n        // 处理文件",
    )

    wait_position = send_handler.index(
        "await waitForPendingImageReads();"
    )
    assert wait_position < send_handler.index(
        "const text = chatInput.value.trim();"
    )
    assert wait_position < send_handler.index(
        "const imagesToSend = [...uploadedImages];"
    )

    result = _node_json(
        f"""
let releaseFirst;
let releaseSecond;
let pendingImageReads = Promise.resolve();
const calls = [];
function handleFiles(files) {{
  calls.push([...files]);
  return new Promise(resolve => {{
    if (calls.length === 1) releaseFirst = resolve;
    else releaseSecond = resolve;
  }});
}}
function queueImageFiles(files) {{
  const queuedRead = pendingImageReads.then(
    () => handleFiles(files)
  );
  pendingImageReads = queuedRead.catch(() => undefined);
  return queuedRead;
}}
{wait_source}
(async () => {{
  queueImageFiles(['first']);
  const waiting = waitForPendingImageReads().then(
    () => calls.push(['send'])
  );
  await new Promise(resolve => setImmediate(resolve));
  queueImageFiles(['second']);
  releaseFirst();
  await new Promise(resolve => setImmediate(resolve));
  const beforeSecond = calls.map(items => items[0]);
  releaseSecond();
  await waiting;
  process.stdout.write(JSON.stringify({{
    beforeSecond,
    after: calls.map(items => items[0]),
  }}));
}})();
"""
    )

    assert result == {
        "beforeSecond": ["first", "second"],
        "after": ["first", "second", "send"],
    }


def test_terminal_rejects_presentation_winner_mismatch() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    select_source = _javascript_function_source(
        html,
        "function selectContractProducts(products, contract)",
        "\n\n        function validateGuideTerminalPayload",
    )
    validate_source = _javascript_function_source(
        html,
        "function validateGuideTerminalPayload(",
        "\n\n        // 发送流式消息",
    )
    result = _node_json(
        f"""
{select_source}
{validate_source}
const productIds = [53, 55];
const references = [
  {{ ordinal: 1, image_id: 'image-1', product_id: 53 }},
  {{ ordinal: 2, image_id: 'image-2', product_id: 55 }},
];
const comparison = {{
  status: 'winner',
  context_source: 'current_upload',
  references,
  winner_reference: references[1],
  tie_reason: null,
  comparison_dimensions: ['price'],
  evidence_refs: ['price:53', 'price:55'],
  evaluated_price_facts: references.map(reference => ({{
    reference,
    state: 'known',
    value: '100',
    source_refs: [`price:${{reference.product_id}}`],
  }})),
}};
const answer = {{
  product_count: 2,
  winner_status: 'winner',
  has_unknown_skin: true,
}};
const cardDisplayContract = {{
  mode: 'comparison',
  visible_product_ids: productIds,
  max_cards: 2,
  reason: 'comparison',
}};
const decisionData = {{
  ordered_product_ids: productIds,
  winner_status: 'winner',
  comparison_data: comparison,
  decision_process: {{
    steps: [{{
      data: {{
        winner_status: 'winner',
        products: 2,
        outcome: comparison,
      }},
    }}],
    final_recommendation: null,
  }},
}};
const presentationContract = {{
  responsibility: 'comparison',
  mode: 'comparison',
  visible_product_ids: productIds,
  card_display: cardDisplayContract,
  winner: {{
    status: 'selected',
    winner_product_id: 53,
    reason: '错误地选择了第一款',
    fact_ids: ['fact:53'],
    dimension_ids: ['price'],
    tie_reason: null,
  }},
}};
let error = null;
try {{
  validateGuideTerminalPayload({{
    intent: 'image_compare',
    answerContract: answer,
    answerData: {{ answer_contract: answer, ...answer }},
    cardDisplayContract,
    presentationContract,
    products: productIds.map(id => ({{ id, product_id: id }})),
    comparisonData: comparison,
    decisionProductIds: productIds,
    decisionData,
    imageObservations: references.map(reference => ({{
      image_id: reference.image_id,
      confirmed_product_id: reference.product_id,
    }})),
  }});
}} catch (caught) {{
  error = caught.message;
}}
process.stdout.write(JSON.stringify({{ error }}));
"""
    )

    assert result == {
        "error": "GUIDE_RESPONSE_CONTRACT_INVALID",
    }


def test_explore_demo_copy_contains_no_selected_winner_language() -> None:
    selected_winner = re.compile(
        r"(首选|最佳|最推荐|优先选|更适合作为|胜出)"
    )
    explore_contracts = [
        contract
        for contract in _all_scripted_contracts()
        if contract.get("recommendation_mode") == "explore"
    ]

    assert explore_contracts
    for contract in explore_contracts:
        assert contract["winner"]["status"] == "not_applicable"
        visible_copy = "\n".join(
            str(value)
            for section in contract["sections"]
            for value in (
                section.get("copy_text"),
                section.get("advisor_reason"),
            )
            if value
        )
        assert selected_winner.search(visible_copy) is None
