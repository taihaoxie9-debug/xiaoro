import hashlib
import json
import re
import subprocess
from pathlib import Path

from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.category_profiles import CategoryProfile

CHAT_HTML = Path("app/static/chat.html")
EXPECTED_PRE_EVIDENCE_RANKING_CHAT_SHA256 = (
    "70ec29f8298fb912e578b718a214619d590214ddcd556ad0ad7ab1613efdbc95"
)
CATEGORY_BROWSER_GATE = Path(
    "tools/guide_gates/category_profile_browser_gate.py"
)
PROHIBITED_IMAGE_CAPABILITY_COPY = (
    "图片识别",
    "识别图片里的品牌",
    "识别品牌、品类",
    "图片没有识别到清晰的品牌",
    "我没有识别到清晰的品牌",
    "识别到商品：",
    "已识别图片内容",
    "识别图片内容",
    "识别分数约",
    "重新识别",
    "OCR识别结果",
)
INTERNAL_PUBLIC_TERMS = (
    "候选",
    "代码核对",
    "硬条件",
    "证据等级",
    "放行",
    "页面记录版本",
    "本轮筛选",
)
PRODUCT_RENDERER_RANGES = (
    (
        "function buildInlineProductImage(",
        "\n\n        function renderStreamingMarkdownPreview",
    ),
    (
        "function renderProductShelf()",
        "\n\n        // ==================== 反馈功能",
    ),
    (
        "function renderLocalProductCard(",
        "\n\n        function renderImageAnalysisHint",
    ),
    (
        "function displayImageSearchResults(",
        "\n\n        // 发送流式消息",
    ),
    (
        "function displayProducts(products)",
        "\n\n        // 显示来源引用",
    ),
)


def _session_id_function_source(html: str) -> str:
    start = html.index("function createSessionId()")
    end = html.index(
        "\n\n        function formatTimeLabel",
        start,
    )
    return html[start:end]


def _execute_session_id_generator(
    function_source: str,
    *,
    force_fallback: bool,
) -> list[str]:
    crypto_expression = (
        "{ getRandomValues: webcrypto.getRandomValues.bind(webcrypto) }"
        if force_fallback
        else "webcrypto"
    )
    script = f"""
const vm = require('node:vm');
const {{ webcrypto }} = require('node:crypto');
const context = vm.createContext({{
  crypto: {crypto_expression},
  Uint8Array,
}});
vm.runInContext({json.dumps(function_source)}, context);
const ids = vm.runInContext(
  'Array.from({{ length: 256 }}, () => createSessionId())',
  context,
);
process.stdout.write(JSON.stringify(ids));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _javascript_function_source(
    html: str,
    signature: str,
    next_signature: str,
) -> str:
    start = html.index(
        (
            "function displayProducts("
            if signature == "function displayProducts(products)"
            else signature
        )
    )
    end = html.index(
        (
            "\n        // 显示通用底部商品卡：只消费后端合同给出的字段。"
            if next_signature.strip() == "// 显示商品卡片"
            else next_signature
        ),
        start,
    )
    return html[start:end]


def _execute_node_json(script: str) -> object:
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_frontend_baseline_hash_remains_documented_for_shell_audit() -> None:
    visual_lock = json.loads(
        Path(
            "docs/audits/frontend-integration/old_visual_shell_v1.json"
        ).read_text(encoding="utf-8")
    )

    assert visual_lock["source_sha256"] == (
        EXPECTED_PRE_EVIDENCE_RANKING_CHAT_SHA256
    )
    assert CHAT_HTML.is_file()


def test_chat_page_has_offline_icons_and_runtime_scope_controls() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert "window.feather = window.feather || { replace() {} }" in html
    assert "GUIDE_RUNTIME_MODE" in html
    assert "runtimeStatusPill" in html
    assert "slice1_text_skincare" in html
    assert "文本护肤 · 单图识别/适配 · 2–3 图比较" in html
    assert "compact_tags" in html
    assert "recommendation-contract-tag" in html
    assert "lumi_conversation_versions_v1" in html
    assert "getConversationVersion" in html
    assert "setConversationVersion" in html
    assert "conversation_version" in html
    assert "if (GUIDE_RUNTIME_MODE) return;" in html


def test_consultation_observation_uses_rose_label_without_left_rule() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert ".guide-presentation-observation {" in html
    assert "border-left: 0;" in html
    assert ".guide-presentation-observation h3 {" in html
    assert "color: var(--primary-deep);" in html


def test_product_title_and_advisor_label_use_rose_accent() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert ".guide-presentation-product h3 {" in html
    assert ".guide-product-advisor-reason strong {" in html
    assert ".guide-presentation-product h3 {\n            color: var(--primary-deep);" in html
    assert ".guide-product-advisor-reason strong {\n            color: var(--primary-deep);" in html


def test_ordinary_product_references_do_not_inherit_rose_accent() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert (
        ".guide-product-ref {\n"
        "            margin: 0 3px;\n"
        "            padding: 0;\n"
        "            border: 0;\n"
        "            border-bottom: 1px solid currentColor;\n"
        "            background: transparent;\n"
        "            color: inherit;"
    ) in html
    assert (
        ".guide-product-ref:hover {\n"
        "            color: var(--primary);"
    ) in html
    assert (
        ".guide-product-ref:focus-visible {\n"
        "            color: var(--primary);"
    ) in html


def test_session_id_source_uses_only_browser_cryptography() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    function_source = _session_id_function_source(html)

    assert "crypto.randomUUID()" in function_source
    assert "crypto.getRandomValues(" in function_source
    assert "Math.random" not in function_source
    assert "Date.now" not in function_source


def test_session_id_generator_is_unique_for_uuid_and_secure_fallback() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    function_source = _session_id_function_source(html)
    session_id_pattern = re.compile(
        r"^session_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    )

    for force_fallback in (False, True):
        session_ids = _execute_session_id_generator(
            function_source,
            force_fallback=force_fallback,
        )

        assert len(session_ids) == len(set(session_ids))
        assert all(
            session_id_pattern.fullmatch(session_id)
            for session_id in session_ids
        )


def test_feedback_buttons_require_a_trusted_target_in_all_runtimes() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    function_start = html.index(
        "function addFeedbackButtons(messageWrapper, messageId)"
    )
    function_body = html[function_start:function_start + 500]
    assert "if (GUIDE_RUNTIME_MODE) return;" not in function_body
    assert "normalizeFeedbackTarget(feedbackTarget)" in function_body
    assert "if (!target) return;" in function_body


def test_deleting_session_waits_for_backend_before_local_cleanup() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    function_start = html.index(
        "async function deleteSession(event, sessionId)"
    )
    function_end = html.index(
        "\n\n        function toggleFavoriteProduct",
        function_start,
    )
    function_body = html[function_start:function_end]
    abort_pos = function_body.index("abortSessionRequest(sessionId)")
    fetch_pos = function_body.index("const response = await fetch(")
    local_pos = function_body.index("saveStoredSessions(sessions)")

    assert abort_pos < fetch_pos < local_pos
    assert (
        "`/api/v1/chat/sessions/${encodeURIComponent(sessionId)}`"
        in function_body
    )
    assert "method: 'DELETE'" in function_body
    assert "if (response.status !== 204)" in function_body
    assert "clearConversationVersion(sessionId)" in function_body
    assert "showNotification('删除失败，请重试。')" in function_body


def test_guide_cards_do_not_render_fabricated_percent_scores() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert "% 契合" not in html
    assert "p.match_score ?? p.rerank_score ?? p.relevance" not in html
    assert "适配待确认" in html
    assert "明确适配" in html


def test_frontend_registers_complete_request_context_before_dom_writes() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert "const activeChatRequests = new Map()" in html
    assert "new AbortController()" in html
    assert "requestId:" in html
    assert "sessionId:" in html
    assert "controller:" in html
    assert "typingDiv:" in html

    function_start = html.index(
        "async function sendChatMessage("
    )
    function_end = html.index(
        "\n        // 执行图片搜索",
        function_start,
    )
    function_body = html[function_start:function_end]
    register_pos = function_body.index(
        "activeChatRequests.set(sessionId, requestContext)"
    )
    assert register_pos < function_body.index("chatMessages.appendChild")
    assert register_pos < function_body.index("await ")


def test_send_rejects_same_session_before_clearing_draft() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    listener_start = html.index(
        "sendBtn.addEventListener('click', async () =>"
    )
    listener_end = html.index(
        "\n        function sendLocalUnclearImageReply",
        listener_start,
    )
    listener_body = html[listener_start:listener_end]
    guard_pos = listener_body.index(
        "activeChatRequests.has(sessionId)"
    )
    assert (
        listener_body.index("const sessionId = getSessionId()")
        < guard_pos
    )
    assert guard_pos < listener_body.index("chatInput.value = ''")


def test_frontend_aborts_requests_on_session_switch_and_delete() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert "function abortSessionRequest(sessionId)" in html
    assert "active.controller.abort()" in html
    assert "&& !requestContext.controller.signal.aborted" in html

    switch_start = html.index("function setCurrentSession(sessionId)")
    switch_body = html[switch_start:switch_start + 400]
    assert "abortSessionRequest(currentSessionId)" in switch_body

    delete_start = html.index(
        "async function deleteSession(event, sessionId)"
    )
    delete_body = html[delete_start:delete_start + 500]
    assert "abortSessionRequest(sessionId)" in delete_body


def test_decision_process_is_thinking_only_not_a_terminal_panel() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    handler_start = html.index(
        "} else if (eventName === 'decision_process') {"
    )
    handler_end = html.index(
        "} else if (eventName === 'answer_contract') {",
        handler_start,
    )
    handler_body = html[handler_start:handler_end]
    flush_start = html.index("const flushDeferredPanels = () =>")
    flush_end = html.index(
        "\n\n            const resolveTypewriterIfIdle",
        flush_start,
    )
    flush_body = html[flush_start:flush_end]

    assert "updateThinkingStep(" in handler_body
    assert "displayDecisionProcess(" not in handler_body
    assert "decisionProcess" not in flush_body
    assert "对比判断" not in html
    assert "推荐思路" not in html


def test_current_session_reactivation_is_a_noop_before_dom_rehydrate() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    function_start = html.index("function activateSession(sessionId)")
    function_end = html.index(
        "\n        function createFreshSession()",
        function_start,
    )
    function_body = html[function_start:function_end]
    guard = "if (currentSessionId === sessionId) return;"

    assert guard in function_body
    assert function_body.index(guard) < function_body.index(
        "getStoredSessions()"
    )
    assert function_body.index(guard) < function_body.index(
        "chatMessages.innerHTML"
    )


def test_stream_uses_concrete_typing_node_signal_and_owner_guards() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    stream_start = html.index(
        "async function sendStreamingMessage("
    )
    stream_end = html.index(
        "\n        function buildDetailedProductReason",
        stream_start,
    )
    stream_body = html[stream_start:stream_end]

    assert "typingDiv" in stream_body.split("{", 1)[0]
    assert "requestContext" in stream_body.split("{", 1)[0]
    assert "chatMessages.querySelector('.typing')" not in stream_body
    assert "signal: requestContext.controller.signal" in stream_body
    assert (
        stream_body.count("isActiveChatRequest(requestContext)")
        >= 6
    )
    assert "before reader.read" in stream_body
    assert "before SSE block" in stream_body
    assert "before typewriter write" in stream_body
    assert "before finalize write" in stream_body
    assert "before version write" in stream_body


def test_request_cleanup_only_releases_the_same_context() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    function_start = html.index(
        "async function sendChatMessage("
    )
    function_end = html.index(
        "\n        // 执行图片搜索",
        function_start,
    )
    function_body = html[function_start:function_end]

    assert "finally {" in function_body
    assert (
        "activeChatRequests.get(sessionId) === requestContext"
        in function_body
    )
    assert "activeChatRequests.delete(sessionId)" in function_body
    assert "error?.name === 'AbortError'" in function_body
    assert (
        "!isActiveChatRequest(requestContext) || "
        "requestContext.controller.signal.aborted"
        in function_body
    )


def test_stream_resynchronizes_authoritative_version_before_turn_request() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    stream_body = _javascript_function_source(
        html,
        "async function sendStreamingMessage(",
        "\n        function buildDetailedProductReason",
    )

    sync_position = stream_body.index(
        "await synchronizeConversationVersion("
    )
    payload_position = stream_body.index("const bodyPayload =")
    request_position = stream_body.index(
        "fetch('/api/v1/chat/stream'"
    )

    assert sync_position < payload_position < request_position
    assert (
        "`/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/version`"
        in html
    )
    assert "signal: requestContext.controller.signal" in stream_body


def test_version_sync_rejects_committed_turn_that_was_not_rendered() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    bounded_source = _javascript_function_source(
        html,
        "function createBoundedRequestController(",
        "\n\n        async function synchronizeConversationVersion",
    )
    sync_source = _javascript_function_source(
        html,
        "async function synchronizeConversationVersion(",
        "\n\n        async function fetchFeedbackTarget",
    )

    result = _execute_node_json(
        f"""
const vm = require('node:vm');
const writes = [];
const context = vm.createContext({{
  AbortController,
  DOMException,
  setTimeout,
  clearTimeout,
  CONVERSATION_VERSION_SYNC_TIMEOUT_MS: 3000,
  getConversationVersion() {{ return 1; }},
  setConversationVersion(sessionId, version) {{
    writes.push([sessionId, version]);
  }},
  async fetch() {{
    return {{
      ok: true,
      async json() {{
        return {{
          session_id: 'session-version-gap',
          conversation_version: 2,
        }};
      }},
    }};
  }},
}});
vm.runInContext({json.dumps(bounded_source)}, context);
vm.runInContext({json.dumps(sync_source)}, context);
(async () => {{
  let error = null;
  let message = null;
  try {{
    await context.synchronizeConversationVersion(
      'session-version-gap'
    );
  }} catch (caught) {{
    error = caught.code;
    message = caught.message;
  }}
  process.stdout.write(JSON.stringify({{ error, message, writes }}));
}})();
"""
    )

    assert result == {
        "error": "GUIDE_VERSION_SYNC_RECOVERY_REQUIRED",
        "message": (
            "当前会话有一轮未完整显示。为避免跳过上下文，"
            "请开始新的咨询。"
        ),
        "writes": [],
    }


def test_sse_parse_errors_are_terminal_before_business_event_handling() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    parse_start = html.index("data = JSON.parse(dataPayload)")
    parse_catch = html.index("} catch (error) {", parse_start)
    handler_pos = html.index(
        "handleSseEvent(eventName, data)",
        parse_start,
    )
    assert parse_catch < handler_pos
    assert (
        "discardDeferredPanels()"
        in html[parse_start:handler_pos]
    )
    assert (
        "throw new Error('GUIDE_STREAM_INVALID_JSON')"
        in html[parse_start:handler_pos]
    )
    assert "data.message || data.error" in html


def test_guide_runtime_consumes_real_stages_without_fake_six_step_process() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert (
        "liveDecisionProcess = GUIDE_RUNTIME_MODE\n"
        "                    ? null\n"
        "                    : startImmediateDecisionProcess"
        in html
    )
    assert "eventName === 'stage'" in html
    assert "renderStage(" in html
    assert "data.message || '正在处理'," in html
    assert "data.stage || data.status || ''" in html
    assert "XiaoRoPresentation.advanceThinkingPipeline(" in html
    assert (
        "if (!GUIDE_RUNTIME_MODE) "
        "renderStage('已理解需求，正在匹配商品')"
        in html
    )
    assert (
        "if (!GUIDE_RUNTIME_MODE) "
        "renderStage('正在结合场景做判断')"
        in html
    )


def test_clean_runtime_enables_bounded_accessible_image_selection() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    runtime_start = html.index("if (GUIDE_RUNTIME_MODE) {")
    runtime_end = html.index("\n        // 反馈相关元素", runtime_start)
    runtime_block = html[runtime_start:runtime_end]

    assert "imageUploadBtn.style.display = 'none'" not in runtime_block
    assert "imageInput.disabled = true" not in runtime_block
    assert 'accept="image/jpeg,image/png,image/webp"' in html
    assert "const MAX_IMAGE_COUNT = 4" in html
    assert "const MAX_IMAGE_BYTES = 8 * 1024 * 1024" in html
    assert "const MAX_IMAGE_BATCH_BYTES = 20 * 1024 * 1024" in html
    assert 'id="imageUploadStatus"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert "最多添加 4 张图片" in html


def test_clean_runtime_image_onboarding_describes_real_bounded_flow() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert "const runtimeImageOnboardingExample" in html
    assert "单图可以先确认商品" in html
    assert "两到三张图会进入同一套商品对比" in html
    assert (
        "const onboardingExamples = GUIDE_RUNTIME_MODE"
        in html
    )


def test_entire_shared_chat_source_has_no_overstated_image_claims() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert "单图识别/适配" in html
    assert "图片处理" in html
    for prohibited in PROHIBITED_IMAGE_CAPABILITY_COPY:
        assert prohibited not in html


def test_clean_runtime_header_describes_image_similarity_and_comparison() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert 'id="runtimeHeaderSubtitle"' in html
    assert (
        '<div class="header-subtitle" id="runtimeHeaderSubtitle">'
        "肤质咨询 · 单图识别/适配 · 2–3 图比较 · 购买建议</div>"
        in html
    )


def test_shared_chat_public_copy_hides_internal_language() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    for term in INTERNAL_PUBLIC_TERMS:
        assert term not in html


def test_clean_runtime_image_preview_supports_remove_and_cancel() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert "function removePreviewImage(imageId)" in html
    assert "function clearImageDraft()" in html
    assert "clearImageDraft();" in html
    assert "aria-label=" in html
    assert "移除图片" in html
    assert "取消全部图片" in html
    assert "URL.revokeObjectURL" in html


def test_image_draft_is_owned_by_session_and_generation() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert "let imageDraftSessionId = null" in html
    assert "let imageDraftGeneration = 0" in html
    handle_start = html.index("async function handleFiles(files)")
    handle_end = html.index(
        "\n        // 处理图片文件",
        handle_start,
    )
    handle_body = html[handle_start:handle_end]
    assert "const draftSessionId = getSessionId()" in handle_body
    assert "const draftGeneration = imageDraftGeneration" in handle_body

    file_start = html.index("function handleImageFile(")
    file_end = html.index(
        "\n        // 关闭搜索模式栏",
        file_start,
    )
    file_body = html[file_start:file_end]
    assert "currentSessionId !== draftSessionId" in file_body
    assert "imageDraftSessionId !== draftSessionId" in file_body
    assert "imageDraftGeneration !== draftGeneration" in file_body


def test_session_switch_clears_old_image_draft_before_rebinding() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    switch_start = html.index("function setCurrentSession(sessionId)")
    switch_end = html.index(
        "\n        function restoreWelcomeState",
        switch_start,
    )
    switch_body = html[switch_start:switch_end]

    abort_pos = switch_body.index(
        "abortSessionRequest(currentSessionId)"
    )
    clear_pos = switch_body.index("clearImageDraft()")
    rebind_pos = switch_body.index("currentSessionId = sessionId")
    assert abort_pos < rebind_pos
    assert clear_pos < rebind_pos


def test_cancel_all_aborts_upload_and_revokes_created_bundle() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    abort_start = html.index("function abortSessionRequest(sessionId)")
    abort_end = html.index(
        "\n\n        function escapeHtml",
        abort_start,
    )
    abort_body = html[abort_start:abort_end]
    assert "active.controller.abort()" in abort_body
    assert "active.bundleReference" in abort_body
    assert "revokeImageBundle(" in abort_body

    cancel_start = html.index(
        "closeSearchMode.addEventListener('click', () =>"
    )
    cancel_end = html.index(
        "\n        // 创建预览项",
        cancel_start,
    )
    cancel_body = html[cancel_start:cancel_end]
    abort_pos = cancel_body.index(
        "abortSessionRequest(getSessionId())"
    )
    clear_pos = cancel_body.index("clearImageDraft()")
    assert abort_pos < clear_pos


def test_late_bundle_response_is_bound_only_to_original_request() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    function_start = html.index("async function sendChatMessage(")
    function_end = html.index(
        "\n        // 执行图片搜索",
        function_start,
    )
    function_body = html[function_start:function_end]

    assert "requestContext.bundleReference = bundleReference" in function_body
    assignment_pos = function_body.index(
        "requestContext.bundleReference = bundleReference"
    )
    owner_check_pos = function_body.index(
        "if (!isActiveChatRequest(requestContext))",
        function_body.index("bundleReference = await uploadImageBundle("),
    )
    assert owner_check_pos < assignment_pos


def test_clean_runtime_uploads_bundle_and_sends_only_server_reference() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    upload_start = html.index("async function uploadImageBundle(")
    upload_end = html.index(
        "\n        // 发送聊天消息",
        upload_start,
    )
    upload_body = html[upload_start:upload_end]
    stream_start = html.index("async function sendStreamingMessage(")
    stream_end = html.index(
        "\n        function buildDetailedProductReason",
        stream_start,
    )
    stream_body = html[stream_start:stream_end]

    assert "formData.append('session_id', sessionId)" in upload_body
    assert (
        "formData.append('images', image.file, image.name)"
        in upload_body
    )
    assert "'/api/v1/chat/image-bundles'" in upload_body
    assert "signal: requestContext.controller.signal" in upload_body
    assert "image_bundle_id" in stream_body
    assert "image_bundle_version" in stream_body
    assert "image_bundle_token" in stream_body
    assert "bundleReference.bundle_id" in stream_body
    assert (
        "if (!GUIDE_RUNTIME_MODE && "
        "Array.isArray(imageResults)"
        in stream_body
    )
    assert "localStorage.setItem('image_bundle" not in html
    assert "sessionStorage.setItem('image_bundle" not in html


def test_clean_runtime_does_not_call_legacy_image_analysis() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    function_start = html.index("async function sendChatMessage(")
    function_end = html.index(
        "\n        // 执行图片搜索",
        function_start,
    )
    function_body = html[function_start:function_end]

    assert (
        "if (GUIDE_RUNTIME_MODE && images?.length)"
        in function_body
    )
    clean_start = function_body.index(
        "if (GUIDE_RUNTIME_MODE && images?.length)"
    )
    clean_branch = function_body[
        clean_start : function_body.index(
            "if (options.resolveImageContext && images?.length)",
            clean_start,
        )
    ]
    assert "uploadImageBundle(" in clean_branch
    assert "buildImageContext(" not in clean_branch
    assert "buildImageResultsForBackend(" not in clean_branch
    assert "imageResults.push" not in clean_branch


def test_frontend_renders_typed_image_model_and_index_versions() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    stream_start = html.index("async function sendStreamingMessage(")
    stream_end = html.index(
        "\n        function buildDetailedProductReason",
        stream_start,
    )
    stream_body = html[stream_start:stream_end]
    display_start = html.index(
        "function displayImageObservation(observation)"
    )
    display_end = html.index(
        "\n        // 显示通用底部商品卡：只消费后端合同给出的字段。",
        display_start,
    )
    display_body = html[display_start:display_end]

    assert "eventName === 'image_observation'" in stream_body
    assert "deferredPanels.imageObservation" in stream_body
    assert "displayImageObservation(" in stream_body
    assert "observation.model_name" in display_body
    assert "observation.index_sha256" in display_body
    assert "data-image-model-version" in display_body
    assert "data-image-index-version" in display_body
    assert "百分百识别" not in display_body


def test_frontend_renders_typed_suitability_and_ocr_observations() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    stream_body = _javascript_function_source(
        html,
        "async function sendStreamingMessage(",
        "\n        function buildDetailedProductReason",
    )
    validator_body = _javascript_function_source(
        html,
        "function validateGuideTerminalPayload({",
        "\n        // 发送流式消息",
    )
    observation_body = _javascript_function_source(
        html,
        "function displayImageObservation(observation)",
        "\n        function displayImageSuitability",
    )
    suitability_body = _javascript_function_source(
        html,
        "function displayImageSuitability(suitability)",
        "\n        // 显示商品卡片",
    )

    assert "suitabilityData: null" in stream_body
    assert "data?.suitability_data || null" in stream_body
    assert "suitabilityData:" in stream_body
    assert "displayImageSuitability(" in stream_body
    assert "'image_suitability'" in validator_body
    assert "observation.ocr_state" in observation_body
    assert "observation.ocr_brand_consistency" in observation_body
    assert "observation.ocr_product_name_consistency" in observation_body
    assert "不覆盖 Canonical" in observation_body
    assert "suitability.status" in suitability_body
    assert "suitability.skin_target" in suitability_body
    assert "escapeHtml(" in suitability_body


def test_snapshot_replaces_data_image_bytes_with_safe_dom_placeholder() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    function_source = _javascript_function_source(
        html,
        "function redactSnapshotDataImages(container)",
        "\n\n        function sanitizeSnapshotHtml",
    )
    sanitize_source = _javascript_function_source(
        html,
        "function sanitizeSnapshotHtml(snapshot)",
        "\n\n        function loadStoredJson",
    )

    result = _execute_node_json(
        f"""
const replacements = [];
const selectors = [];
const document = {{
  createElement(tagName) {{
    return {{
      tagName,
      className: '',
      textContent: '',
      attributes: {{}},
      setAttribute(name, value) {{
        this.attributes[name] = value;
      }},
    }};
  }},
}};
function makeImage(source) {{
  return {{
    getAttribute(name) {{
      return name === 'src' ? source : null;
    }},
    replaceWith(replacement) {{
      replacements.push(replacement);
    }},
  }};
}}
const images = [
  makeImage('data:image/png;base64,raw-secret-bytes'),
  makeImage('  DATA:IMAGE/WEBP;BASE64,more-secret-bytes  '),
  makeImage('https://cdn.example.test/product.png'),
];
const container = {{
  querySelectorAll(selector) {{
    selectors.push(selector);
    return images;
  }},
}};
{function_source}
redactSnapshotDataImages(container);
process.stdout.write(JSON.stringify({{
  selectors,
  replacements,
}}));
"""
    )

    assert result["selectors"] == ["img[src]"]
    assert len(result["replacements"]) == 2
    assert all(
        replacement["className"] == "snapshot-image-placeholder"
        for replacement in result["replacements"]
    )
    assert all(
        replacement["attributes"]["role"] == "img"
        for replacement in result["replacements"]
    )
    assert all(
        replacement["textContent"] == "历史图片未保留"
        for replacement in result["replacements"]
    )
    assert "raw-secret-bytes" not in json.dumps(
        result,
        ensure_ascii=False,
    )
    assert "redactSnapshotDataImages(container)" in sanitize_source


def test_snapshot_sanitizer_removes_legacy_executable_markup() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    sanitizer_source = _javascript_function_source(
        html,
        "function sanitizeSnapshotInteractiveMarkup(container)",
        "\n\n        function sanitizeSnapshotHtml",
    )
    snapshot_source = _javascript_function_source(
        html,
        "function sanitizeSnapshotHtml(snapshot)",
        "\n\n        function loadStoredJson",
    )

    assert (
        "script, iframe, object, embed, link, meta, base"
        in sanitizer_source
    )
    assert "attributeName.startsWith('on')" in sanitizer_source
    assert "attributeName === 'srcdoc'" in sanitizer_source
    assert "element.removeAttribute(attribute.name)" in sanitizer_source
    assert "getSafeProductImageUrl(" in sanitizer_source
    assert "getSafeDetailUrl(" in sanitizer_source
    assert (
        "sanitizeSnapshotInteractiveMarkup(container)"
        in snapshot_source
    )


def test_detail_url_accepts_only_https_or_same_site_relative_urls() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    function_source = _javascript_function_source(
        html,
        "function getSafeDetailUrl(value)",
        "\n\n        function getProductLinkInfo",
    )
    values = [
        "https://shop.example.test/item/42?from=chat#detail",
        "/api/v1/search/products/42?from=chat",
        "http://shop.example.test/item/42",
        "javascript:alert(1)",
        "//evil.example.test/item/42",
        "https://shop.example.test/');alert(1)//",
        'https://shop.example.test/" onmouseover="alert(1)',
        "/api/v1/search/products/' onclick='alert(1)",
    ]
    result = _execute_node_json(
        f"""
const window = {{
  location: {{ origin: 'https://xiaoro.example.test' }},
}};
{function_source}
const values = {json.dumps(values)};
process.stdout.write(JSON.stringify(values.map(getSafeDetailUrl)));
"""
    )

    assert result == [
        "https://shop.example.test/item/42?from=chat#detail",
        "/api/v1/search/products/42?from=chat",
        "",
        "",
        "",
        "",
        "",
        "",
    ]


def test_product_image_url_is_allowlisted_and_attribute_escaped() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    assert "function getSafeProductImageUrl(value)" in html
    validator_source = _javascript_function_source(
        html,
        "function getSafeProductImageUrl(value)",
        "\n\n        function getProductImageSrc",
    )
    image_source = _javascript_function_source(
        html,
        "function getProductImageSrc(product, tone = 'rose')",
        "\n\n        function getProductImageState",
    )
    escape_source = _javascript_function_source(
        html,
        "function escapeHtml(value)",
        "\n\n        function buildProductPlaceholder",
    )
    values = [
        "/static/images/products/local.png",
        "static/images/products/local.png",
        "./static/images/products/local.png",
        "https://cdn.example.test/product.png?size=large",
        'x" onerror="window.__imageXss=1',
        "javascript:window.__imageXss=1",
        "data:image/svg+xml,<svg onload=window.__imageXss=1>",
        "//evil.example.test/product.png",
        "http://cdn.example.test/product.png",
        "https://cdn.example.test/' onerror='window.__imageXss=1",
        "https://user:pass@cdn.example.test/product.png",
    ]
    result = _execute_node_json(
        f"""
const window = {{
  location: {{ origin: 'https://xiaoro.example.test' }},
}};
function getProductDisplayMeta(product) {{
  return product?.displayMeta || {{}};
}}
function buildProductPlaceholder() {{
  return 'data:image/svg+xml,placeholder';
}}
{escape_source}
{validator_source}
{image_source}
const values = {json.dumps(values)};
process.stdout.write(JSON.stringify({{
  validated: values.map(getSafeProductImageUrl),
  allowedAttribute: getProductImageAttribute({{
    image_url: 'https://cdn.example.test/product.png?a=1&b=2'
  }}),
  blockedAttribute: getProductImageAttribute({{
    image_url: 'x" onerror="window.__imageXss=1'
  }}),
}}));
"""
    )

    assert result == {
        "validated": [
            "/static/images/products/local.png",
            "/static/images/products/local.png",
            "/static/images/products/local.png",
            "https://cdn.example.test/product.png?size=large",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
        "allowedAttribute": (
            "https://cdn.example.test/product.png?a=1&amp;b=2"
        ),
        "blockedAttribute": "data:image/svg+xml,placeholder",
    }


def test_all_product_renderers_use_allowlisted_escaped_image_attributes() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    for start_marker, end_marker in PRODUCT_RENDERER_RANGES:
        function_body = _javascript_function_source(
            html,
            start_marker,
            end_marker,
        )
        assert "getProductImageAttribute(" in function_body, start_marker
        assert 'src="${getProductImageSrc(' not in function_body
        assert 'src="${imageSrc}"' not in function_body


def test_product_link_labels_are_escaped_in_all_renderers() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert "${linkInfo.label}</a>" not in html
    assert "${linkLabel}</a>" not in html
    assert "${escapeHtml(linkInfo.label)}</a>" in html
    assert "${escapeHtml(linkLabel)}</a>" in html


def test_legacy_image_results_escape_all_backend_text_fields() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    function_body = _javascript_function_source(
        html,
        "function displayImageSearchResults(result, queryImage)",
        "\n\n        // 发送流式消息",
    )

    assert "${escapeHtml(result.ocr_info.text)}" in function_body
    assert "${escapeHtml(key)}: ${escapeHtml(value)}" in function_body
    assert 'title="${escapeHtml(product.name)}"' in function_body
    assert ">${escapeHtml(product.name)}</div>" in function_body
    assert "${escapeHtml(product.similarity)}%" in function_body
    assert "${escapeHtml(assetNote)}</div>" in function_body


def test_citation_navigation_has_no_inline_backend_javascript() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    renderer_body = _javascript_function_source(
        html,
        "function displayCitations(citations)",
        "\n\n        // 处理来源引用点击",
    )
    handler_body = _javascript_function_source(
        html,
        "function handleCitationNavigation(event)",
        "\n\n        function handleCitationClick",
    )
    click_body = _javascript_function_source(
        html,
        "function handleCitationClick(type, id)",
        "\n\n        // 显示避坑提示",
    )

    assert "onclick=" not in renderer_body
    assert 'data-citation-type="${escapeHtml(type)}"' in renderer_body
    assert 'data-citation-id="${escapeHtml(id)}"' in renderer_body
    assert "event.target?.closest(" in handler_body
    assert "'[data-citation-type]'" in handler_body
    assert "encodeURIComponent(String(id))" in click_body
    assert (
        "chatMessages.addEventListener("
        "'click', handleCitationNavigation)"
        in html
    )
    assert (
        "chatMessages.addEventListener("
        "'keydown', handleCitationNavigation)"
        in html
    )


def test_history_navigation_has_no_inline_persisted_javascript() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    renderer_body = _javascript_function_source(
        html,
        "function renderHistoryList()",
        "\n\n        async function deleteSession",
    )
    handler_body = _javascript_function_source(
        html,
        "function handleHistoryListClick(event)",
        "\n\n        historyList.addEventListener('click'",
    )

    assert "onclick=" not in renderer_body
    assert 'data-session-id="${escapeHtml(sessionId)}"' in renderer_body
    assert (
        'data-delete-session-id="${escapeHtml(sessionId)}"'
        in renderer_body
    )
    assert "'[data-delete-session-id]'" in handler_body
    assert "'[data-session-id]'" in handler_body
    assert (
        "historyList.addEventListener("
        "'click', handleHistoryListClick)"
        in html
    )
    assert (
        "historyList.addEventListener("
        "'keydown', handleHistoryListClick)"
        in html
    )


def test_recommendation_favorite_uses_persistable_delegation() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    renderer_body = _javascript_function_source(
        html,
        "function displayProducts(products)",
        "\n\n        // 显示来源引用",
    )
    handler_body = _javascript_function_source(
        html,
        "function handleRecommendationFavorite(event)",
        "\n\n        function handleProductDetailNavigation",
    )

    assert "onclick=" not in renderer_body
    assert (
        'data-favorite-product-id="${escapeHtml(productId)}"'
        in renderer_body
    )
    assert "'[data-favorite-product-id]'" in handler_body
    assert "event.preventDefault()" in handler_body
    assert "event.stopImmediatePropagation()" in handler_body
    assert "toggleFavoriteProduct(productId)" in handler_body

    favorite_listener = (
        "chatMessages.addEventListener("
        "'click', handleRecommendationFavorite)"
    )
    detail_listener = (
        "chatMessages.addEventListener("
        "'click', handleProductDetailNavigation)"
    )
    assert favorite_listener in html
    assert html.index(favorite_listener) < html.index(detail_listener)


def test_four_contract_products_persist_and_fourth_can_be_favorited() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    favorite_source = _javascript_function_source(
        html,
        "function toggleFavoriteProduct(productId)",
        "\n\n        function handleProductShelfClick",
    )
    shelf_source = _javascript_function_source(
        html,
        "function saveProductsToShelf(products)",
        "\n\n        function renderProductShelf",
    )
    result = _execute_node_json(
        f"""
let storedProducts = [];
function getStoredProducts() {{
  return storedProducts.map(item => ({{ ...item }}));
}}
function saveStoredProducts(products) {{
  storedProducts = products.map(item => ({{ ...item }}));
}}
function renderProductShelf() {{}}
{favorite_source}
{shelf_source}
const contractProducts = [1, 2, 3, 4].map(id => ({{
  id,
  name: `product-${{id}}`,
  brand: 'brand',
  category: 'category',
  price: id * 100,
  image_url: `/static/product-${{id}}.png`,
  detail_url: `/products/${{id}}`,
}}));
saveProductsToShelf(contractProducts);
const persistedIds = storedProducts.map(item => item.id).sort();
toggleFavoriteProduct(4);
const fourth = storedProducts.find(item => item.id === 4);
process.stdout.write(JSON.stringify({{
  persistedIds,
  fourthFavorite: fourth?.favorite ?? null,
}}));
"""
    )

    assert result == {
        "persistedIds": [1, 2, 3, 4],
        "fourthFavorite": True,
    }
    assert "products.forEach(product =>" in shelf_source
    assert "products.slice(0, 3)" not in shelf_source


def test_select_contract_products_uses_exact_ids_or_legacy_order() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    function_source = _javascript_function_source(
        html,
        "function selectContractProducts(products, contract)",
        "\n\n        // 发送流式消息",
    )
    result = _execute_node_json(
        f"""
{function_source}
const products = [
  {{ id: 1, name: 'first' }},
  {{ id: 2, name: 'second' }},
  {{ id: 3, name: 'third' }},
  {{ id: 4, name: 'fourth' }},
];
function ids(contract) {{
  return selectContractProducts(products, contract).map(item => item.id);
}}
function errorFor(contract) {{
  try {{
    ids(contract);
    return null;
  }} catch (error) {{
    return error.message;
  }}
}}
process.stdout.write(JSON.stringify({{
  legacy: ids(null),
  single: ids({{
    mode: 'single',
    visible_product_ids: [3],
    max_cards: 1,
  }}),
  comparison: ids({{
    mode: 'comparison',
    visible_product_ids: [4, 2],
    max_cards: 2,
  }}),
  recommendationFour: ids({{
    mode: 'recommendation',
    visible_product_ids: [1, 2, 3, 4],
    max_cards: 4,
  }}),
  none: ids({{
    mode: 'none',
    visible_product_ids: [],
    max_cards: 0,
  }}),
  missing: errorFor({{
    mode: 'single',
    visible_product_ids: [99],
    max_cards: 1,
  }}),
  countMismatch: errorFor({{
    mode: 'comparison',
    visible_product_ids: [1, 2],
    max_cards: 1,
  }}),
}}));
"""
    )

    assert result == {
        "legacy": [1, 2, 3],
        "single": [3],
        "comparison": [4, 2],
        "recommendationFour": [1, 2, 3, 4],
        "none": [],
        "missing": "CARD_DISPLAY_CONTRACT_MISMATCH",
        "countMismatch": "CARD_DISPLAY_CONTRACT_MISMATCH",
    }


def test_category_profile_is_derived_from_all_typed_cards_fail_closed() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    resolver_source = _javascript_function_source(
        html,
        "function resolveCategoryProfileForCards(",
        "\n\n        function formatCategoryFactValue",
    )
    result = _execute_node_json(
        f"""
{resolver_source}
const fact = {{
  field_key: 'spf_pa',
  label: '防晒指数',
  value: null,
  state: 'unavailable'
}};
const card = {{
  id: 53,
  category_profile: 'suncare',
  category_facts: [fact]
}};
const resolve = (products, intentProfile = null) => {{
  try {{
    return resolveCategoryProfileForCards(products, intentProfile);
  }} catch (error) {{
    return error.message;
  }}
}};
process.stdout.write(JSON.stringify({{
  followup: resolve([card]),
  revision: resolve([card], null),
  image: resolve([card], null),
  matchingIntent: resolve([card], 'suncare'),
  missingProfile: resolve([
    {{ id: 53, category_facts: [fact] }}
  ]),
  missingFacts: resolve([
    {{ id: 53, category_profile: 'suncare', category_facts: [] }}
  ]),
  mixedProfiles: resolve([
    card,
    {{
      id: 120,
      category_profile: 'fragrance',
      category_facts: [{{
        field_key: 'sillage',
        label: '扩香度',
        value: null,
        state: 'unavailable'
      }}]
    }}
  ]),
  mismatchedIntent: resolve([card], 'fragrance')
}}));
"""
    )

    assert result == {
        "followup": "suncare",
        "revision": "suncare",
        "image": "suncare",
        "matchingIntent": "suncare",
        "missingProfile": "CATEGORY_FACT_PAYLOAD_INVALID",
        "missingFacts": "CATEGORY_FACT_PAYLOAD_INVALID",
        "mixedProfiles": "CATEGORY_FACT_PAYLOAD_INVALID",
        "mismatchedIntent": "CATEGORY_FACT_PAYLOAD_INVALID",
    }


def test_category_fact_renderer_uses_only_typed_escaped_card_fields() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    escape_source = _javascript_function_source(
        html,
        "function escapeHtml(value)",
        "\n\n        function buildProductPlaceholder",
    )
    category_source = _javascript_function_source(
        html,
        "function formatCategoryFactValue(fact)",
        "\n\n        // 显示商品卡片",
    )
    display_source = _javascript_function_source(
        html,
        "function displayProducts(products)",
        "\n\n        // 显示来源引用",
    )
    result = _execute_node_json(
        f"""
{escape_source}
{category_source}
const product = {{
  id: 120,
  category_profile: 'fragrance',
  category_facts: [
    {{
      field_key: 'sillage',
      label: '<img src=x onerror=globalThis.pwned=2>',
      value: '<script>globalThis.pwned=3</script>',
      state: 'known',
      source_refs: ['private-source-must-not-render'],
      capabilities: ['display'],
    }},
    {{
      field_key: 'top_notes',
      label: '前调',
      value: null,
      state: 'unavailable',
    }},
    {{
      field_key: 'base_notes',
      label: '后调',
      value: null,
      state: 'conflict',
    }},
  ],
}};
const wrongProfile = {{
  id: 38,
  category_profile: 'skincare',
  category_facts: [{{
    field_key: 'efficacy',
    label: '功效',
    value: null,
    state: 'unavailable',
  }}],
}};
const invalidField = {{
  id: 120,
  category_profile: 'fragrance',
  category_facts: [{{
    field_key: '<img src=x onerror=globalThis.pwned=4>',
    label: '非法字段',
    value: null,
    state: 'unavailable',
  }}],
}};
const crossProfileField = {{
  id: 120,
  category_profile: 'fragrance',
  category_facts: [{{
    field_key: 'efficacy',
    label: '功效',
    value: null,
    state: 'unavailable',
  }}],
}};
const rendered = buildCategoryFactsHtml(product, 'fragrance');
process.stdout.write(JSON.stringify({{
  rendered,
  wrongProfile: buildCategoryFactsHtml(wrongProfile, 'fragrance'),
  invalidProfile: buildCategoryFactsHtml(product, 'not_a_profile'),
  invalidField: buildCategoryFactsHtml(invalidField, 'fragrance'),
  crossProfileField: buildCategoryFactsHtml(
    crossProfileField,
    'fragrance'
  ),
  pwned: globalThis.pwned ?? null,
}}));
"""
    )

    assert result["pwned"] is None
    assert "<img" not in result["rendered"]
    assert "<script" not in result["rendered"]
    assert "private-source-must-not-render" not in result["rendered"]
    assert "&lt;img" in result["rendered"]
    assert "&lt;script&gt;" in result["rendered"]
    assert "暂无可核验数据" in result["rendered"]
    assert "来源存在冲突" in result["rendered"]
    assert result["wrongProfile"] == ""
    assert result["invalidProfile"] == ""
    assert result["invalidField"] == ""
    assert result["crossProfileField"] == ""
    assert "category_facts" in category_source
    assert "answer" not in category_source
    assert "source_refs" not in category_source
    assert "capabilities" not in category_source
    assert "expectedCategoryProfile" not in display_source
    assert "buildCategoryFactsHtml(" not in display_source
    assert "categoryFactsHtml" not in display_source


def test_category_fact_renderer_accepts_backend_registry_fields() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    escape_source = _javascript_function_source(
        html,
        "function escapeHtml(value)",
        "\n\n        function buildProductPlaceholder",
    )
    category_source = _javascript_function_source(
        html,
        "function formatCategoryFactValue(fact)",
        "\n\n        // 显示商品卡片",
    )
    core_fields = {"product_identity", "brand", "category", "price"}
    registry = category_field_registry()
    facts_by_profile = {
        profile.value: [
            {
                "field_key": definition.key,
                "label": definition.key,
                "value": None,
                "state": "unavailable",
            }
            for definition in registry.definitions
            if profile in definition.profiles
            and definition.key not in core_fields
        ]
        for profile in CategoryProfile
    }
    result = _execute_node_json(
        f"""
{escape_source}
{category_source}
const factsByProfile = {json.dumps(facts_by_profile)};
const rendered = Object.fromEntries(
  Object.entries(factsByProfile).map(([profile, facts]) => [
    profile,
    buildCategoryFactsHtml(
      {{ id: 1, category_profile: profile, category_facts: facts }},
      profile
    )
  ])
);
process.stdout.write(JSON.stringify(rendered));
"""
    )

    assert set(result) == {
        profile.value for profile in CategoryProfile
    }
    assert all(result.values())
    assert all(
        rendered.count("category-fact-row") <= 10
        for rendered in result.values()
    )


def test_category_profile_browser_gate_covers_full_catalog_and_adversarial() -> None:
    source = CATEGORY_BROWSER_GATE.read_text(encoding="utf-8")

    assert "sync_playwright" in source
    assert "sys.path.insert" in source
    assert "headless=True" in source
    assert "browser.new_context(" in source
    assert '"normal"' in source
    assert '"adversarial"' in source
    assert "category_profile_for" in source
    assert "page_errors" in source
    assert "console_errors" in source
    assert "sse_errors" in source
    assert "unexpected_5xx" in source
    assert "failed_images" in source
    assert "cross_session_leakage" in source
    assert "late_event_pollution" in source
    assert 'locator(".recommendation-panel").last' in source
    assert 'route.fulfill(' in source
    assert "_product_id_for_profile" in source
    assert "wrong_profile_product_id" in source
    assert "invalid_profile" in source
    assert "invalid_field" in source
    assert "state_before_invalid" in source
    assert "state_after_invalid == state_before_invalid" in source
    assert "recovery_request_version" in source
    assert (
        'recovery_request_version == state_before_invalid["version"]'
        in source
    )
    assert "state_after_recovery" in source
    assert 'state_after_recovery["version"] == (' in source
    assert 'state_before_invalid["version"] + 1' in source
    assert "feedback_target=" in source
    assert '"lumi_feedback_targets_v1"' in source
    assert "profiles[product_id] == expected_profile" in source
    assert "next(iter(sorted(_profile_by_product_id())))" not in source
    assert "PILOT_PRODUCT_IDS" not in source
    assert "PILOT_BINDINGS" not in source
    assert "[91, 38]" not in source
    assert "[57, 53]" not in source
    assert "[80, 79]" not in source
    assert "[86, 114]" not in source
    assert "[103, 69]" not in source
    assert "[120, 121]" not in source


def test_guide_contract_products_bypass_legacy_text_filter() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    select_source = _javascript_function_source(
        html,
        "function selectContractProducts(products, contract)",
        "\n\n        function validateGuideTerminalPayload",
    )
    stream_body = _javascript_function_source(
        html,
        "async function sendStreamingMessage(",
        "\n        function buildDetailedProductReason",
    )
    finalize_start = stream_body.index(
        "const finalizeAfterTypewriter = async () =>"
    )
    finalize_end = stream_body.index(
        "const renderStage =",
        finalize_start,
    )
    finalize_source = stream_body[finalize_start:finalize_end]
    result = _execute_node_json(
        f"""
{select_source}
const authoritativeProducts = [
  {{ id: 93, product_id: 93, name: 'product-93' }},
  {{ id: 41, product_id: 41, name: 'product-41' }},
  {{ id: 12, product_id: 12, name: 'product-12' }},
  {{ id: 7, product_id: 7, name: 'product-7' }},
];
const cardDisplayContract = {{
  mode: 'comparison',
  visible_product_ids: [41, 7, 93, 12],
  max_cards: 4,
  reason: 'comparison',
}};
async function runCase(GUIDE_RUNTIME_MODE, guideOwned) {{
  let finalized = false;
  const requestContext = {{}};
  const isActiveChatRequest = () => true;
  const waitTypewriterDone = async () => {{}};
      const startStructuredPresentation = () => null;
      const structuredPresentationPromise = null;
      const structuredPresentationError = null;
      const structuredPresentationStarted = false;
  const text = 'compare these options';
  const fullText = 'Here is the recommendation.';
  let inlineProducts = selectContractProducts(
    authoritativeProducts,
    cardDisplayContract
  );
  const deferredPanels = {{ guideOwned }};
  const guidePresentationState = null;
  const sanitizeProductsForCurrentTurn = products => [...products];
  let filterCalls = 0;
  const filterProductsForRenderedText = (renderedText, products) => {{
    filterCalls += 1;
    return products.slice(0, 3);
  }};
  let renderedIds = [];
  const renderAssistantMarkdown = (renderedText, products) => {{
    renderedIds = products.map(product => product.id);
    return renderedText;
  }};
  const bubble = {{}};
  const rememberMessageRecord = () => {{}};
  const messageId = 'message-id';
  const startedAt = performance.now();
  const retrievalSources = [];
  const addFeedbackButtons = () => {{}};
  const aiDiv = {{}};
  const flushDeferredPanels = () => {{}};
  const saveCurrentSnapshot = () => {{}};
  const sessionTitle = 'session';
  const truncateText = value => value;
  {finalize_source}
  await finalizeAfterTypewriter();
  return {{ filterCalls, renderedIds }};
}}
(async () => {{
  process.stdout.write(JSON.stringify({{
    formalGuide: await runCase(false, true),
    standaloneGuide: await runCase(true, true),
    unownedLegacy: await runCase(false, false),
  }}));
}})();
"""
    )

    assert result == {
        "formalGuide": {
            "filterCalls": 0,
            "renderedIds": [41, 7, 93, 12],
        },
        "standaloneGuide": {
            "filterCalls": 0,
            "renderedIds": [41, 7, 93, 12],
        },
        "unownedLegacy": {
            "filterCalls": 1,
            "renderedIds": [41, 7, 93],
        },
    }
    assert (
        "if (!GUIDE_RUNTIME_MODE && !deferredPanels.guideOwned)"
        in finalize_source
    )


def test_terminal_payload_validation_fails_closed_before_card_render() -> None:
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
    result = _execute_node_json(
        f"""
{select_source}
{validate_source}
const products = [
  {{ id: 53, product_id: 53 }},
  {{ id: 55, product_id: 55 }},
];
const contract = {{
  mode: 'recommendation',
  visible_product_ids: [53, 55],
  max_cards: 2,
  reason: 'recommendation',
}};
const answerData = {{
  answer_contract: {{
    product_count: 2,
    winner_status: 'SELECTED',
    has_unknown_skin: false,
  }},
  product_count: 2,
  winner_status: 'SELECTED',
  has_unknown_skin: false,
}};
const decisionData = {{
  ordered_product_ids: [53, 55],
  winner_status: 'SELECTED',
  decision_process: {{
    steps: [{{
      data: {{
        winner_status: 'SELECTED',
        products: 2,
      }},
    }}],
    final_recommendation: null,
  }},
}};
const presentationContract = {{
  responsibility: 'recommendation',
  mode: 'recommendation',
  visible_product_ids: [53, 55],
  card_display: contract,
  winner: {{
    status: 'selected',
    winner_product_id: 53,
  }},
}};
function errorFor(payload) {{
  try {{
    validateGuideTerminalPayload(payload);
    return null;
  }} catch (error) {{
    return error.message;
  }}
}}
process.stdout.write(JSON.stringify({{
  valid: validateGuideTerminalPayload({{
    intent: 'recommend',
    answerContract: answerData.answer_contract,
    answerData,
    cardDisplayContract: contract,
    presentationContract,
    products,
    decisionProductIds: [53, 55],
    decisionData,
  }}).map(item => item.id),
  clarify: validateGuideTerminalPayload({{
    intent: 'clarify',
    answerContract: null,
    answerData: null,
    cardDisplayContract: null,
    presentationContract: null,
    products: [],
  }}),
  missingAnswer: errorFor({{
    intent: 'recommend',
    answerContract: null,
    answerData: null,
    cardDisplayContract: contract,
    presentationContract,
    products,
    decisionProductIds: [53, 55],
    decisionData,
  }}),
  countMismatch: errorFor({{
    intent: 'recommend',
    answerContract: {{
      ...answerData.answer_contract,
      product_count: 1,
    }},
    answerData: {{
      ...answerData,
      answer_contract: {{
        ...answerData.answer_contract,
        product_count: 1,
      }},
      product_count: 1,
    }},
    cardDisplayContract: contract,
    presentationContract,
    products,
    decisionProductIds: [53, 55],
    decisionData,
  }}),
  orderMismatch: errorFor({{
    intent: 'recommend',
    answerContract: answerData.answer_contract,
    answerData,
    cardDisplayContract: contract,
    presentationContract,
    products: [
      {{ id: 55, product_id: 55 }},
      {{ id: 53, product_id: 53 }},
    ],
    decisionProductIds: [53, 55],
    decisionData,
  }}),
}}));
"""
    )

    assert result == {
        "valid": [53, 55],
        "clarify": [],
        "missingAnswer": "GUIDE_RESPONSE_CONTRACT_INVALID",
        "countMismatch": "GUIDE_RESPONSE_CONTRACT_INVALID",
        "orderMismatch": "CARD_DISPLAY_CONTRACT_MISMATCH",
    }


def test_terminal_payload_accepts_only_known_zero_card_consultation_intents(
) -> None:
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
    result = _execute_node_json(
        f"""
{select_source}
{validate_source}
const knownIntents = [
  'consultation_entry',
  'consultation_answer',
  'consultation_clarification',
  'consultation_provisional',
  'consultation_confirmation',
  'consultation_rejection',
  'consultation_medical_escalation',
];
const answerContract = {{
  product_count: 0,
  winner_status: 'NOT_APPLICABLE',
  has_unknown_skin: false,
}};
const answerData = {{
  answer_contract: answerContract,
  ...answerContract,
}};
const zeroCards = {{
  mode: 'none',
  visible_product_ids: [],
  max_cards: 0,
  reason: 'no_products',
}};
const base = {{
  answerContract,
  answerData,
  cardDisplayContract: zeroCards,
  presentationContract: {{
    responsibility: 'consultation',
    mode: 'consultation',
    visible_product_ids: [],
    card_display: zeroCards,
    winner: {{ status: 'not_applicable' }},
  }},
  products: [],
  decisionProductIds: null,
  decisionData: null,
}};
function errorFor(payload) {{
  try {{
    validateGuideTerminalPayload(payload);
    return null;
  }} catch (error) {{
    return error.message;
  }}
}}
function resultFor(payload) {{
  try {{
    return {{ value: validateGuideTerminalPayload(payload) }};
  }} catch (error) {{
    return {{ error: error.message }};
  }}
}}
const known = knownIntents.map(intent => (
  resultFor({{ ...base, intent }})
));
const invalidCard = errorFor({{
  ...base,
  intent: 'consultation_entry',
  answerContract: {{
    ...answerContract,
    product_count: 1,
  }},
  answerData: {{
    answer_contract: {{
      ...answerContract,
      product_count: 1,
    }},
    ...answerContract,
    product_count: 1,
  }},
  cardDisplayContract: {{
    mode: 'single',
    visible_product_ids: [53],
    max_cards: 1,
    reason: 'product',
  }},
  products: [{{ id: 53, product_id: 53 }}],
}});
const invalidDecision = errorFor({{
  ...base,
  intent: 'consultation_entry',
  decisionProductIds: [],
  decisionData: {{
    ordered_product_ids: [],
    winner_status: 'NOT_APPLICABLE',
  }},
}});
process.stdout.write(JSON.stringify({{
  known,
  unknown: errorFor({{
    ...base,
    intent: 'consultation_future_mode',
  }}),
  invalidCard,
  invalidDecision,
}}));
"""
    )

    assert result == {
        "known": [
            {"value": []},
            {"value": []},
            {"value": []},
            {"value": []},
            {"value": []},
            {"value": []},
            {"value": []},
        ],
        "unknown": "GUIDE_RESPONSE_CONTRACT_INVALID",
        "invalidCard": "GUIDE_RESPONSE_CONTRACT_INVALID",
        "invalidDecision": "GUIDE_RESPONSE_CONTRACT_INVALID",
    }


def test_terminal_payload_rejects_status_winner_and_reference_mismatch() -> None:
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
    result = _execute_node_json(
        f"""
{select_source}
{validate_source}
const comparisonData = {{
  status: 'winner',
  references: [
    {{ ordinal: 1, image_id: 'image-a', product_id: 53 }},
    {{ ordinal: 2, image_id: 'image-b', product_id: 55 }},
  ],
  winner_reference: {{
    ordinal: 2,
    image_id: 'image-b',
    product_id: 55,
  }},
  tie_reason: null,
  comparison_dimensions: ['price'],
  evidence_refs: ['price:53', 'price:55'],
  evaluated_price_facts: [
    {{
      reference: {{
        ordinal: 1,
        image_id: 'image-a',
        product_id: 53,
      }},
      state: 'known',
      value: '125',
      source_refs: ['price:53'],
    }},
    {{
      reference: {{
        ordinal: 2,
        image_id: 'image-b',
        product_id: 55,
      }},
      state: 'known',
      value: '88.11',
      source_refs: ['price:55'],
    }},
  ],
}};
const base = {{
  intent: 'image_compare',
  answerContract: {{
    product_count: 2,
    winner_status: 'winner',
    has_unknown_skin: true,
  }},
  answerData: {{
    answer_contract: {{
      product_count: 2,
      winner_status: 'winner',
      has_unknown_skin: true,
    }},
    product_count: 2,
    winner_status: 'winner',
    has_unknown_skin: true,
  }},
  cardDisplayContract: {{
    mode: 'comparison',
    visible_product_ids: [53, 55],
    max_cards: 2,
    reason: 'comparison',
  }},
  presentationContract: {{
    responsibility: 'comparison',
    mode: 'comparison',
    visible_product_ids: [53, 55],
    card_display: {{
      mode: 'comparison',
      visible_product_ids: [53, 55],
      max_cards: 2,
      reason: 'comparison',
    }},
    winner: {{
      status: 'selected',
      winner_product_id: 55,
    }},
  }},
  products: [
    {{ id: 53, product_id: 53 }},
    {{ id: 55, product_id: 55 }},
  ],
  comparisonData,
  decisionProductIds: [53, 55],
  decisionData: {{
    ordered_product_ids: [53, 55],
    winner_status: 'winner',
    comparison_data: comparisonData,
    decision_process: {{
      steps: [{{
        data: {{
          winner_status: 'winner',
          products: 2,
          outcome: comparisonData,
        }},
      }}],
      final_recommendation: null,
    }},
  }},
  imageObservations: [
    {{
      image_id: 'image-a',
      confirmed_product_id: 53,
    }},
    {{
      image_id: 'image-b',
      confirmed_product_id: 55,
    }},
  ],
}};
const copy = value => JSON.parse(JSON.stringify(value));
function errorFor(mutate) {{
  const payload = copy(base);
  mutate(payload);
  try {{
    validateGuideTerminalPayload(payload);
    return null;
  }} catch (error) {{
    return error.message;
  }}
}}
process.stdout.write(JSON.stringify({{
  answerStatus: errorFor(payload => {{
    payload.answerContract.winner_status = 'tie';
  }}),
  answerWrapperStatus: errorFor(payload => {{
    payload.answerData.winner_status = 'tie';
  }}),
  decisionStatus: errorFor(payload => {{
    payload.decisionData.winner_status = 'tie';
  }}),
  nestedDecisionStatus: errorFor(payload => {{
    payload.decisionData.decision_process.steps[0].data
      .winner_status = 'tie';
  }}),
  comparisonStatus: errorFor(payload => {{
    payload.comparisonData.status = 'tie';
  }}),
  nestedOutcome: errorFor(payload => {{
    payload.decisionData.decision_process.steps[0].data
      .outcome.status = 'tie';
  }}),
  foreignWinner: errorFor(payload => {{
    payload.comparisonData.winner_reference.product_id = 999;
    payload.decisionData.comparison_data.winner_reference.product_id = 999;
    payload.decisionData.decision_process.steps[0].data
      .outcome.winner_reference.product_id = 999;
  }}),
  tieWithWinner: errorFor(payload => {{
    payload.answerContract.winner_status = 'tie';
    payload.answerData.answer_contract.winner_status = 'tie';
    payload.answerData.winner_status = 'tie';
    payload.decisionData.winner_status = 'tie';
    payload.decisionData.comparison_data.status = 'tie';
    payload.comparisonData.status = 'tie';
    const data = payload.decisionData.decision_process.steps[0].data;
    data.winner_status = 'tie';
    data.outcome.status = 'tie';
    payload.comparisonData.tie_reason = 'equal_price';
    payload.decisionData.comparison_data.tie_reason = 'equal_price';
    data.outcome.tie_reason = 'equal_price';
  }}),
  priceReference: errorFor(payload => {{
    payload.comparisonData.evaluated_price_facts[1]
      .reference.image_id = 'image-c';
    payload.decisionData.comparison_data
      .evaluated_price_facts[1].reference.image_id = 'image-c';
    payload.decisionData.decision_process.steps[0].data.outcome
      .evaluated_price_facts[1].reference.image_id = 'image-c';
  }}),
  observationOrder: errorFor(payload => {{
    payload.imageObservations.reverse();
  }}),
  productAlias: errorFor(payload => {{
    payload.products[1].product_id = 999;
  }}),
}}));
"""
    )

    assert result == {
        "answerStatus": "GUIDE_RESPONSE_CONTRACT_INVALID",
        "answerWrapperStatus": "GUIDE_RESPONSE_CONTRACT_INVALID",
        "decisionStatus": "GUIDE_RESPONSE_CONTRACT_INVALID",
        "nestedDecisionStatus": "GUIDE_RESPONSE_CONTRACT_INVALID",
        "comparisonStatus": "GUIDE_RESPONSE_CONTRACT_INVALID",
        "nestedOutcome": "GUIDE_RESPONSE_CONTRACT_INVALID",
        "foreignWinner": "GUIDE_RESPONSE_CONTRACT_INVALID",
        "tieWithWinner": "GUIDE_RESPONSE_CONTRACT_INVALID",
        "priceReference": "GUIDE_RESPONSE_CONTRACT_INVALID",
        "observationOrder": "GUIDE_RESPONSE_CONTRACT_INVALID",
        "productAlias": "GUIDE_RESPONSE_CONTRACT_INVALID",
    }


def test_terminal_payload_accepts_exact_four_image_comparison() -> None:
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
    product_ids = [53, 55, 57, 58]
    references = [
        {
            "ordinal": index,
            "image_id": f"image-{index}",
            "product_id": product_id,
        }
        for index, product_id in enumerate(product_ids, start=1)
    ]
    comparison = {
        "status": "winner",
        "context_source": "current_upload",
        "references": references,
        "winner_reference": references[1],
        "tie_reason": None,
        "comparison_dimensions": ["price"],
        "evidence_refs": [f"price:{item}" for item in product_ids],
        "evaluated_price_facts": [
            {
                "reference": reference,
                "state": "known",
                "value": str(200 - index),
                "source_refs": [f"price:{reference['product_id']}"],
            }
            for index, reference in enumerate(references)
        ],
    }
    answer = {
        "product_count": 4,
        "winner_status": "winner",
        "has_unknown_skin": True,
    }
    base = {
        "intent": "image_compare",
        "answerContract": answer,
        "answerData": {
            "answer_contract": answer,
            **answer,
        },
        "cardDisplayContract": {
            "mode": "comparison",
            "visible_product_ids": product_ids,
            "max_cards": 4,
            "reason": "comparison",
        },
        "presentationContract": {
            "responsibility": "comparison",
            "mode": "comparison",
            "visible_product_ids": product_ids,
            "card_display": {
                "mode": "comparison",
                "visible_product_ids": product_ids,
                "max_cards": 4,
                "reason": "comparison",
            },
            "winner": {
                "status": "selected",
                "winner_product_id": product_ids[1],
            },
        },
        "products": [
            {"id": product_id, "product_id": product_id}
            for product_id in product_ids
        ],
        "comparisonData": comparison,
        "decisionProductIds": product_ids,
        "decisionData": {
            "ordered_product_ids": product_ids,
            "winner_status": "winner",
            "comparison_data": comparison,
            "decision_process": {
                "steps": [
                    {
                        "data": {
                            "winner_status": "winner",
                            "products": 4,
                            "outcome": comparison,
                        }
                    }
                ],
                "final_recommendation": None,
            },
        },
        "imageObservations": [
            {
                "image_id": reference["image_id"],
                "confirmed_product_id": reference["product_id"],
            }
            for reference in references
        ],
    }
    result = _execute_node_json(
        f"""
{select_source}
{validate_source}
const base = {json.dumps(base)};
const valid = validateGuideTerminalPayload(base).map(item => item.id);
const invalid = JSON.parse(JSON.stringify(base));
invalid.comparisonData.references[2].ordinal = 4;
invalid.decisionData.comparison_data.references[2].ordinal = 4;
invalid.decisionData.decision_process.steps[0].data
  .outcome.references[2].ordinal = 4;
let invalidResult = null;
try {{
  validateGuideTerminalPayload(invalid);
}} catch (error) {{
  invalidResult = error.message;
}}
process.stdout.write(JSON.stringify({{ valid, invalidResult }}));
"""
    )

    assert result == {
        "valid": product_ids,
        "invalidResult": "GUIDE_RESPONSE_CONTRACT_INVALID",
    }


def test_terminal_payload_accepts_confirmed_session_image_comparison() -> None:
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
    result = _execute_node_json(
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
  context_source: 'confirmed_session',
  references,
  winner_reference: references[0],
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
const payload = {{
  intent: 'image_compare',
  answerContract: answer,
  answerData: {{ answer_contract: answer, ...answer }},
  cardDisplayContract: {{
    mode: 'comparison',
    visible_product_ids: productIds,
    max_cards: 2,
    reason: 'comparison',
  }},
  presentationContract: {{
    responsibility: 'comparison',
    mode: 'comparison',
    visible_product_ids: productIds,
    card_display: {{
      mode: 'comparison',
      visible_product_ids: productIds,
      max_cards: 2,
      reason: 'comparison',
    }},
    winner: {{
      status: 'selected',
      winner_product_id: 53,
    }},
  }},
  products: productIds.map(id => ({{ id, product_id: id }})),
  comparisonData: comparison,
  decisionProductIds: productIds,
  decisionData: {{
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
  }},
  imageObservations: [],
}};
process.stdout.write(JSON.stringify(
  validateGuideTerminalPayload(payload).map(item => item.id)
));
"""
    )

    assert result == [53, 55]


def test_frontend_requires_terminal_end_before_render_or_persistence() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    stream_body = _javascript_function_source(
        html,
        "async function sendStreamingMessage(",
        "\n        function buildDetailedProductReason",
    )
    products_start = stream_body.index(
        "} else if (eventName === 'products')"
    )
    products_end = stream_body.index(
        "} else if (eventName === 'citations')",
        products_start,
    )
    products_branch = stream_body[products_start:products_end]
    eof_start = stream_body.index("while (true)")
    eof_body = stream_body[eof_start:]

    assert "let receivedEnd = false" in stream_body
    assert "let receivedError = false" in stream_body
    assert "let receivedDeliveryControl = false" in stream_body
    assert "const discardDeferredPanels = () =>" in stream_body
    assert "if (receivedEnd)" in stream_body
    assert "eventName !== 'delivery_control'" in stream_body
    assert "receivedDeliveryControl = true" in stream_body
    assert "handlePostEndDeliveryControl(" in stream_body
    assert "if (receivedError)" in stream_body
    assert "receivedEnd = true" in stream_body
    assert "validateGuideTerminalPayload(" in stream_body
    assert "inlineProducts = sanitizedProducts" not in products_branch
    assert "if (!receivedEnd)" in eof_body
    assert "discardDeferredPanels()" in eof_body
    assert "GUIDE_STREAM_INCOMPLETE" in eof_body
    assert "如果没有end事件，也添加反馈按钮" not in eof_body
    assert "await finalizeAfterTypewriter()" not in eof_body


def test_stream_decoder_fatally_flushes_before_terminal_commit() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    stream_body = _javascript_function_source(
        html,
        "async function sendStreamingMessage(",
        "\n        function buildDetailedProductReason",
    )
    loop_position = stream_body.index("while (true)")
    flush_position = stream_body.index("decoder.decode()", loop_position)
    buffer_check_position = stream_body.index(
        "if (buffer",
        flush_position,
    )
    version_position = stream_body.index(
        "setConversationVersion(",
        flush_position,
    )
    finalize_position = stream_body.index(
        "pendingFinalize = finalizeAfterTypewriter()",
        flush_position,
    )

    assert "new TextDecoder('utf-8', { fatal: true })" in stream_body
    assert "GUIDE_STREAM_INVALID_UTF8" in stream_body
    assert "let deferredConversationVersion = null" in stream_body
    assert (
        "GUIDE_RUNTIME_MODE || deferredPanels.guideOwned"
        in stream_body
    )
    assert flush_position < buffer_check_position
    assert buffer_check_position < version_position < finalize_position


def test_card_panels_do_not_infer_fill_or_retruncate_products() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    stream_body = _javascript_function_source(
        html,
        "async function sendStreamingMessage(",
        "\n        function buildDetailedProductReason",
    )
    flush_start = stream_body.index("const flushDeferredPanels = () =>")
    flush_end = stream_body.index(
        "const resolveTypewriterIfIdle",
        flush_start,
    )
    flush_body = stream_body[flush_start:flush_end]
    renderer_body = _javascript_function_source(
        html,
        "function displayProducts(products)",
        "\n\n        // 显示来源引用",
    )

    assert "cardDisplayContract: null" in stream_body
    assert "eventName === 'card_display_contract'" in stream_body
    assert "deferredPanels.cardDisplayContract = data" in stream_body
    assert "selectContractProducts(" in flush_body
    assert "deferredPanels.cardDisplayContract" in flush_body
    for prohibited in (
        "filterProductsForRenderedText",
        "getProductNameVariants",
        "allRecognizedHeadings",
        "renderedNicknames",
        "cardProducts.length < 3",
        "cardProducts.slice(0, 3)",
    ):
        assert prohibited not in flush_body

    assert "products.slice(0, 3)" not in renderer_body
    assert "visibleProducts" not in renderer_body
    assert "saveProductsToShelf(products)" in renderer_body
    assert "products.map((p, index)" in renderer_body
    assert "${products.length} 款商品" in renderer_body


def test_scenario_review_summary_and_typed_pitfalls_have_owned_renderers() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    stream_body = _javascript_function_source(
        html,
        "async function sendStreamingMessage(",
        "\n        function buildDetailedProductReason",
    )
    review_body = _javascript_function_source(
        html,
        "function displayReviewEvidence(reviewEvidence)",
        "\n\n        // 显示避坑提示",
    )
    merchant_body = _javascript_function_source(
        html,
        "function displayMerchantClaims(merchantClaims)",
        "\n\n        function displayReviewEvidence",
    )
    pitfall_body = _javascript_function_source(
        html,
        "function displayPitfalls(pitfalls)",
        "\n\n        // 单个步骤卡片 HTML",
    )

    for field in (
        "scenarioEvidence: null",
        "merchantClaims: null",
        "reviewEvidence: null",
        "pitfalls: []",
    ):
        assert field in stream_body
    assert "eventName === 'scenario_evidence'" in stream_body
    assert "eventName === 'merchant_claims'" in stream_body
    assert "eventName === 'review_evidence'" in stream_body
    assert "eventName === 'pitfalls'" in stream_body
    assert "displayScenarioEvidence(" in stream_body
    assert "displayMerchantClaims(" in stream_body
    assert "displayReviewEvidence(" in stream_body
    assert "商家宣称" in merchant_body
    assert "未经独立核实" in merchant_body
    assert "安全类仅展示" in merchant_body
    assert "escapeHtml(item?.display_claim" in merchant_body
    assert "${item?.display_claim}" not in merchant_body
    assert "review-source-fact" in review_body
    assert "review-synthesis" in review_body
    assert "review-product-absence" in review_body
    assert "review-absence-notice" not in review_body
    assert "暂无已批准且可审计的用户评论来源" not in review_body
    for escaped_value in (
        "escapeHtml(fact?.quote",
        "escapeHtml(summary?.product_id",
        "escapeHtml(summary?.synthesis?.text",
        "escapeHtml(item?.product_id",
    ):
        assert escaped_value in review_body
    for unsafe_value in (
        "${fact?.quote}",
        "${summary?.product_id}",
        "${summary?.synthesis?.text}",
        "${item?.product_id}",
    ):
        assert unsafe_value not in review_body
    for forbidden in (
        "user_review_notes",
        "review_count",
        "product.description",
        "product.notes",
    ):
        assert forbidden not in review_body

    assert "severity === 'high'" in pitfall_body
    assert "const otherPitfalls" in pitfall_body
    assert "其他注意" in pitfall_body
    assert "evidence_refs" in pitfall_body
    assert "pitfall-evidence" in pitfall_body


def test_product_evidence_event_has_owned_escaped_renderer() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    stream_body = _javascript_function_source(
        html,
        "async function sendStreamingMessage(",
        "\n        function buildDetailedProductReason",
    )
    renderer_body = _javascript_function_source(
        html,
        "function displayProductEvidence(productEvidence)",
        "\n\n        function displayMerchantClaims",
    )

    assert "productEvidence: null" in stream_body
    assert "deferredPanels.productEvidence = null" in stream_body
    assert "eventName === 'product_evidence'" in stream_body
    assert "deferredPanels.productEvidence = data" in stream_body
    assert "displayProductEvidence(" in stream_body
    for escaped_value in (
        "escapeHtml(evidence?.product_id",
        "escapeHtml(sourceLabel",
        "escapeHtml(reviewLabel",
        "escapeHtml(evidence?.exact_text",
        "escapeHtml(value)",
        "escapeHtml(item)",
    ):
        assert escaped_value in renderer_body
    assert "消费者自评" in renderer_body
    assert "商家引用测试" in renderer_body
    assert "已审核" in renderer_body
    assert "安全边界" in renderer_body
    assert "packet?.ambiguity_reasons" in renderer_body
    assert "规格边界" in renderer_body
    for private_source_field in (
        "source_file",
        "resolved_image_file",
        "image_file",
        "source_url",
        "source_locator",
        "image_sha256",
        "source_sha256",
    ):
        assert private_source_field not in renderer_body


def test_consultation_typed_events_use_owned_zero_card_panels() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    stream_body = _javascript_function_source(
        html,
        "async function sendStreamingMessage(",
        "\n        function buildDetailedProductReason",
    )
    renderer_body = _javascript_function_source(
        html,
        "function displayConsultationUpdate(eventName, data)",
        "\n\n        // 显示商品卡片",
    )

    assert "consultationUpdates: []" in stream_body
    for event_name in (
        "consultation_observation",
        "consultation_provisional",
        "medical_escalation",
        "profile_confirmation",
    ):
        assert f"eventName === '{event_name}'" in stream_body
    assert "displayConsultationUpdate(" in stream_body
    assert "deferredPanels.consultationUpdates" in stream_body
    assert "displayProducts(" not in renderer_body
    assert "saveProductsToShelf(" not in renderer_body
    assert "session_profile" in renderer_body
    assert "当前会话画像已更新" in renderer_body
    assert "stop_skincare_advice" in renderer_body
    assert "next_question" in renderer_body
    assert "isActiveChatRequest(requestContext)" in stream_body


def test_detail_navigation_uses_delegated_listener_without_inline_onclick() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    validator_source = _javascript_function_source(
        html,
        "function getSafeDetailUrl(value)",
        "\n\n        function getProductLinkInfo",
    )
    handler_source = _javascript_function_source(
        html,
        "function handleProductDetailNavigation(event)",
        "\n\n        chatMessages.addEventListener('click'",
    )

    renderer_bodies = {}
    for start_marker, end_marker in PRODUCT_RENDERER_RANGES:
        function_body = _javascript_function_source(
            html,
            start_marker,
            end_marker,
        )
        renderer_bodies[start_marker] = function_body
        assert 'onclick="window.open(' not in function_body

    shelf_body = renderer_bodies["function renderProductShelf()"]
    assert "onclick=" not in shelf_body
    assert "getSafeDetailUrl(item.detail_url)" in shelf_body
    assert "encodeURIComponent(productId)" in shelf_body
    assert 'data-detail-url="${escapeHtml(detailUrl)}"' in shelf_body
    assert (
        "chatMessages.addEventListener("
        "'click', handleProductDetailNavigation)"
        in html
    )
    assert (
        "chatMessages.addEventListener("
        "'keydown', handleProductDetailNavigation)"
        in html
    )
    assert (
        "productShelf.addEventListener("
        "'click', handleProductShelfClick)"
        in html
    )
    assert (
        "productShelf.addEventListener("
        "'keydown', handleProductDetailNavigation)"
        in html
    )

    result = _execute_node_json(
        f"""
const opened = [];
const window = {{
  location: {{ origin: 'https://xiaoro.example.test' }},
  open(...args) {{
    opened.push(args);
    return {{ opener: 'unsafe' }};
  }},
}};
{validator_source}
{handler_source}
function runClick(detailUrl) {{
  const trigger = {{ dataset: {{ detailUrl }} }};
  const state = {{ prevented: false }};
  const event = {{
    type: 'click',
    target: {{
      closest(selector) {{
        if (selector === '[data-detail-url]') return trigger;
        if (selector === 'button') return null;
        return null;
      }},
    }},
    currentTarget: {{
      contains(node) {{
        return node === trigger;
      }},
    }},
    preventDefault() {{
      state.prevented = true;
    }},
  }};
  handleProductDetailNavigation(event);
  return state;
}}
const safeState = runClick('/api/v1/search/products/42');
const blockedState = runClick("javascript:alert('xss')");
process.stdout.write(JSON.stringify({{
  opened,
  safeState,
  blockedState,
}}));
"""
    )

    assert result["opened"] == [
        [
            "/api/v1/search/products/42",
            "_blank",
            "noopener,noreferrer",
        ]
    ]
    assert result["safeState"]["prevented"] is True
    assert result["blockedState"]["prevented"] is False


def test_runtime_one_to_four_image_drafts_are_allowed() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    function_source = _javascript_function_source(
        html,
        "function getRuntimeImageDraftError(imageCount, runtimeMode)",
        "\n\n        // 发送消息",
    )
    result = _execute_node_json(
        f"""
{function_source}
const cases = [
  [0, true],
  [1, true],
  [2, true],
      [3, true],
  [4, true],
  [4, false],
];
process.stdout.write(JSON.stringify(
  cases.map(([count, runtimeMode]) =>
    getRuntimeImageDraftError(count, runtimeMode)
  )
));
"""
    )

    assert result == [
        "",
        "",
        "",
        "",
        "",
        "",
    ]

    listener_body = _javascript_function_source(
        html,
        "sendBtn.addEventListener('click', async () =>",
        "\n\n        function sendLocalUnclearImageReply",
    )
    guard_pos = listener_body.index(
        "const runtimeImageDraftError = getRuntimeImageDraftError("
    )
    clear_pos = listener_body.index("const imagesToSend = [...uploadedImages]")
    send_pos = listener_body.index("await sendChatMessage(")
    guard_block = listener_body[guard_pos:clear_pos]

    assert "uploadedImages.length" in guard_block
    assert "setImageUploadStatus(" in guard_block
    assert "showNotification(runtimeImageDraftError)" in guard_block
    assert "return;" in guard_block
    assert guard_pos < clear_pos < send_pos


def test_runtime_image_action_matches_bundle_cardinality() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    function_source = _javascript_function_source(
        html,
        "function runtimeImageAction(imageCount)",
        "\n\n        function getRuntimeImageDraftError",
    )
    result = _execute_node_json(
        f"""
{function_source}
process.stdout.write(JSON.stringify([
  runtimeImageAction(1),
  runtimeImageAction(2),
  runtimeImageAction(3),
  runtimeImageAction(4),
]));
"""
    )

    assert result == [
        "identify",
        "compare",
        "compare",
        "compare",
    ]
    assert "defaultRuntimeImagePrompt" not in html
    assert "bodyPayload.image_action = imageAction" in html


def test_frontend_buffers_two_image_observations_in_event_order() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    stream_body = _javascript_function_source(
        html,
        "async function sendStreamingMessage(",
        "\n        function buildDetailedProductReason",
    )

    assert "imageObservations: []" in stream_body
    assert "deferredPanels.imageObservations.push(observation)" in stream_body
    assert (
        "deferredPanels.imageObservations.forEach(observation =>"
        in stream_body
    )
    assert "deferredPanels.imageObservations = []" in stream_body
    assert "deferredPanels.imageObservation = observation" not in stream_body
