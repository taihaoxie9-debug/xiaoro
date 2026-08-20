from pathlib import Path


CHAT = Path("app/static/chat.html").resolve()
MODULE = Path("app/static/guide-presentation.js").resolve()


def test_g_inline_card_images_reserve_space_and_defer_decode() -> None:
    source = MODULE.read_text(encoding="utf-8")
    start = source.index("function createInlineProductCard(")
    end = source.index("\n        function createDirectFacts", start)
    function = source[start:end]

    assert "image.width = 112" in function
    assert "image.height = 114" in function
    assert "image.loading = 'lazy'" in function
    assert "image.decoding = 'async'" in function


def test_final_chat_controls_have_accessible_names() -> None:
    html = CHAT.read_text(encoding="utf-8")

    assert (
        'class="chat-textarea" id="chatInput" '
        'name="message" aria-label="输入消息" autocomplete="off"'
    ) in html
    assert (
        'class="send-btn" id="sendBtn" '
        'type="button" aria-label="发送消息"'
    ) in html
    assert (
        'type="file" id="imageInput" name="images" '
        'aria-label="选择商品图片"'
    ) in html


def test_preview_and_full_card_images_have_stable_dimensions() -> None:
    html = CHAT.read_text(encoding="utf-8")

    preview_start = html.index("function createPreviewItem(")
    preview_end = html.index(
        "\n        function _extractProductOCRText",
        preview_start,
    )
    preview = html[preview_start:preview_end]
    assert "image.width = 60" in preview
    assert "image.height = 60" in preview
    assert "image.decoding = 'async'" in preview

    full_start = html.index("function displayProducts(")
    full_end = html.index(
        "\n        function displayDecisionProcess",
        full_start,
    )
    full = html[full_start:full_end]
    assert 'width="180"' in full
    assert 'height="118"' in full
    assert 'loading="lazy"' in full
    assert 'decoding="async"' in full
    assert "aria-label=\"${isFavorite ? '取消收藏' : '收藏'}" in full


def test_final_format_has_focus_and_mobile_safe_area() -> None:
    html = CHAT.read_text(encoding="utf-8")

    assert (
        ".guide-product-ref:focus-visible {\n"
        "            color: var(--primary);\n"
        "            outline: 2px solid currentColor;"
    ) in html
    assert "padding-bottom: calc(24px + env(safe-area-inset-bottom));" in html
    assert (
        "@media (prefers-reduced-motion: reduce)" in html
        and ".preview-item" in html[
            html.index("@media (prefers-reduced-motion: reduce)") :
            html.index("@media (prefers-reduced-motion: reduce)") + 500
        ]
    )
