from __future__ import annotations

from decimal import Decimal

import pytest

from app.guide.understanding import exact_parsing
from app.guide.understanding.contracts import (
    BudgetDraft,
    CategoryDraft,
    ExclusionDraft,
    ReferenceDraft,
    TopicCode,
    UnderstandingIssue,
)
from app.guide.understanding.exact_parsing import parse_exact_constraints
from tests.guide.legacy_text_understanding import understand_text


_RESET_BRIDGES = (
    "不过我想要",
    "相反改选",
    "最后还是买",
    "转头看看",
)
_RESET_ALIAS_TRANSITIONS = (
    ("香水", "防晒", TopicCode.SUNSCREEN),
    ("防晒", "面霜", TopicCode.SKINCARE),
    ("面霜", "粉底液", TopicCode.BASE_MAKEUP),
    ("粉底液", "口红", TopicCode.COLOR_MAKEUP),
    ("口红", "卸妆油", TopicCode.CLEANSER),
    ("卸妆油", "香水", TopicCode.FRAGRANCE),
)
_RESET_SENTENCE_CASES = tuple(
    (
        f"不要{source_alias}{bridge}{target_alias}",
        target_topic,
    )
    for bridge in _RESET_BRIDGES
    for source_alias, target_alias, target_topic in _RESET_ALIAS_TRANSITIONS
)
_UNKNOWN_INTERMEDIATE_TEXTS = tuple(
    f"{lead}{decision}"
    for lead in ("临时", "再三", "听完建议后")
    for decision in ("改变方向想看", "重新决定选择", "调整目标准备买")
)
_TASK29_CATEGORY_QUANTIFIERS = (
    "任意",
    "任一",
    "任何",
    "一切",
    "所有",
    "全部",
    "每个",
    "每一款",
    "每一种",
    "每一类",
    "各个",
    "各款",
    "各类",
    "这类",
    "这种",
    "这一类",
    "那种",
    "那一类",
)
_TASK30_NESTED_NEGATIVE_ATTRIBUTES = (
    "不含酒精的",
    "无酒精的",
    "无香精的",
)
_TASK32_OUTER_EXCLUSION_CUES = (
    "避开",
    "不要",
    "不想要",
    "排除",
    "拒绝",
    "不要有",
)
_TASK32_INNER_ABSENCE_CUES = ("不含", "无")
_TASK32_INGREDIENTS = ("酒精", "香精")
_TASK32_CATEGORIES = (("香水", TopicCode.FRAGRANCE),)
_CLAUSE_BOUNDARIES = ("，", ",", "。", ".", "！", "!", "？", "?", "；", ";")
_UNICODE_PUNCTUATION_RUNS = (
    "…",
    "……",
    "、",
    "……、？！",
    "《》",
    "“”",
    "—",
    "‽",
    "_",
)


def _parsed_category(
    message: str,
) -> tuple[TopicCode | None, list[UnderstandingIssue]]:
    constraints, issues = parse_exact_constraints(message)

    topic = next(
        (
            item.value
            for item in constraints
            if isinstance(item, CategoryDraft)
        ),
        None,
    )
    return topic, issues


def _parsed_topic(message: str) -> TopicCode | None:
    topic, issues = _parsed_category(message)

    assert issues == []
    return topic


@pytest.mark.parametrize(
    ("message", "topic"),
    [
        ("推荐一款修护精华", TopicCode.SERUM),
        ("推荐通勤防晒", TopicCode.SUNSCREEN),
        ("推荐精华水", TopicCode.SKINCARE),
        ("推荐持妆粉底液", TopicCode.BASE_MAKEUP),
        ("推荐显白口红", TopicCode.COLOR_MAKEUP),
        ("推荐温和卸妆油", TopicCode.CLEANSER),
        ("推荐木质调香水", TopicCode.FRAGRANCE),
    ],
)
def test_supported_category_topics_are_parsed(
    message: str,
    topic: TopicCode,
) -> None:
    assert _parsed_topic(message) is topic


@pytest.mark.parametrize(
    "message",
    [
        "卸全脸彩妆到底按几泵",
        "想卸除眼周彩妆",
        "怎么洗掉顽固彩妆",
    ],
)
def test_color_makeup_as_cleansing_object_routes_to_cleanser(
    message: str,
) -> None:
    assert _parsed_topic(message) is TopicCode.CLEANSER


def test_color_makeup_as_purchase_target_stays_color_makeup() -> None:
    assert _parsed_topic("推荐一套彩妆") is TopicCode.COLOR_MAKEUP


def test_face_wash_cream_alias_does_not_fall_through_to_face_cream() -> None:
    assert _parsed_topic("芙丽芳丝洗面霜") is TopicCode.CLEANSER
    assert _parsed_topic("科颜氏面霜") is TopicCode.SKINCARE


@pytest.mark.parametrize(
    ("message", "referent"),
    (
        ("它那个35个人测的靠谱吗？", "它"),
        ("这款还有其他规格吗？", "这款"),
        ("该产品需要每天用吗？", "该产品"),
    ),
)
def test_explicit_singular_pronoun_is_current_item_reference(
    message: str,
    referent: str,
) -> None:
    constraints, issues = parse_exact_constraints(message)
    references = [
        item
        for item in constraints
        if isinstance(item, ReferenceDraft)
    ]

    assert issues == []
    assert len(references) == 1
    assert references[0].kind == "current_item"
    assert references[0].ordinal is None
    assert references[0].source_span is not None
    span = references[0].source_span
    assert message[span.start:span.end] == referent


@pytest.mark.parametrize(
    "message",
    (
        "这个品类一般怎么判断质地好坏",
        "这个问题是什么意思",
    ),
)
def test_generic_demonstrative_is_not_current_item_reference(
    message: str,
) -> None:
    constraints, _ = parse_exact_constraints(message)

    assert not any(
        isinstance(item, ReferenceDraft)
        and item.kind == "current_item"
        for item in constraints
    )


@pytest.mark.parametrize(
    ("message", "topic"),
    [
        ("精华水", TopicCode.SKINCARE),
        ("眼部精华", TopicCode.SKINCARE),
        ("眼部精华液", TopicCode.SKINCARE),
        ("精华", TopicCode.SERUM),
        ("精华液", TopicCode.SERUM),
        ("防晒隔离", TopicCode.SUNSCREEN),
        ("气垫粉底液", TopicCode.BASE_MAKEUP),
        ("洁面霜", TopicCode.CLEANSER),
        ("卸妆油", TopicCode.CLEANSER),
    ],
)
def test_longest_category_alias_wins(
    message: str,
    topic: TopicCode,
) -> None:
    assert _parsed_topic(message) is topic


def test_category_alias_registry_is_longest_first() -> None:
    aliases = [alias for alias, _ in exact_parsing._CATEGORY_ALIASES]

    assert aliases == sorted(aliases, key=lambda value: (-len(value), value))
    assert aliases.index("卸妆油") < aliases.index("卸妆")
    assert aliases.index("防晒隔离") < aliases.index("防晒")
    assert aliases.index("精华水") < aliases.index("精华")


def test_longest_match_lexer_emits_typed_tokens_and_source_spans() -> None:
    lexer = getattr(exact_parsing, "_lex_exact_tokens", None)
    assert lexer is not None
    text = "不禁选择香水；不太想买防晒"

    rows = [
        (
            token.kind.value,
            text[token.source_span.start:token.source_span.end],
        )
        for token in lexer(text)
    ]

    assert rows == [
        ("positive_modal", "不禁"),
        ("selection_action", "选择"),
        ("category", "香水"),
        ("clause_boundary", "；"),
        ("hedge", "不太"),
        ("selection_action", "想买"),
        ("category", "防晒"),
    ]
    assert not any(
        kind == "negation_operator" and value == "不"
        for kind, value in rows
    )


@pytest.mark.parametrize("boundary", _CLAUSE_BOUNDARIES)
def test_lexer_emits_every_supported_punctuation_as_clause_boundary(
    boundary: str,
) -> None:
    lexer = getattr(exact_parsing, "_lex_exact_tokens", None)
    assert lexer is not None
    text = f"香水{boundary}选择洁面"

    boundary_tokens = [
        token
        for token in lexer(text)
        if token.kind.value == "clause_boundary"
    ]

    assert len(boundary_tokens) == 1
    span = boundary_tokens[0].source_span
    assert text[span.start:span.end] == boundary


@pytest.mark.parametrize("punctuation_run", _UNICODE_PUNCTUATION_RUNS)
def test_lexer_emits_unicode_punctuation_run_as_one_clause_boundary(
    punctuation_run: str,
) -> None:
    text = f"先选择香水{punctuation_run}最后不考虑了"

    boundary_tokens = [
        token
        for token in exact_parsing._lex_exact_tokens(text)
        if token.kind.value == "clause_boundary"
    ]

    assert len(boundary_tokens) == 1
    span = boundary_tokens[0].source_span
    assert text[span.start:span.end] == punctuation_run


@pytest.mark.parametrize(
    ("message", "minimum", "maximum"),
    (
        ("预算100-200元推荐香水", Decimal("100"), Decimal("200")),
        ("预算99.9元推荐香水", None, Decimal("99.9")),
        ("￥99.9元推荐香水", None, Decimal("99.9")),
    ),
)
def test_numeric_punctuation_is_not_lexed_as_clause_boundary(
    message: str,
    minimum: Decimal | None,
    maximum: Decimal,
) -> None:
    tokens = exact_parsing._lex_exact_tokens(message)
    constraints, issues = parse_exact_constraints(message)
    budget = next(
        item
        for item in constraints
        if isinstance(item, BudgetDraft)
    )

    assert not any(
        token.kind.value == "clause_boundary"
        for token in tokens
    )
    assert budget.minimum == minimum
    assert budget.maximum == maximum
    assert issues == []


@pytest.mark.parametrize(
    ("message", "maximum"),
    (
        ("预算 100.5 元以内的防晒", Decimal("100.5")),
        ("预算 １００．５ 元以内的防晒", Decimal("100.5")),
    ),
)
def test_decimal_bound_budget_never_matches_only_fractional_tail(
    message: str,
    maximum: Decimal,
) -> None:
    constraints, issues = parse_exact_constraints(message)
    budgets = [
        item
        for item in constraints
        if isinstance(item, BudgetDraft)
    ]

    assert budgets == [BudgetDraft(maximum=maximum)]
    assert issues == []


@pytest.mark.parametrize("boundary", (",", "，", ".", "．"))
def test_budget_number_stops_before_non_numeric_clause_punctuation(
    boundary: str,
) -> None:
    message = f"预算100{boundary}推荐防晒"
    tokens = exact_parsing._lex_exact_tokens(message)
    constraints, issues = parse_exact_constraints(message)
    budget = next(
        item
        for item in constraints
        if isinstance(item, BudgetDraft)
    )

    assert budget.minimum is None
    assert budget.maximum == Decimal("100")
    assert issues == []
    assert any(
        token.kind.value == "clause_boundary"
        and message[
            token.source_span.start:token.source_span.end
        ] == boundary
        for token in tokens
    )


@pytest.mark.parametrize("sign", ("-", "−", "－"))
@pytest.mark.parametrize("spacing", ("", " "))
@pytest.mark.parametrize(
    "raw_range",
    ("100到200", "100.5到200.75", "１００．５到２００．７５"),
)
def test_signed_budget_range_never_becomes_positive_range(
    sign: str,
    spacing: str,
    raw_range: str,
) -> None:
    message = f"预算{spacing}{sign}{spacing}{raw_range}元推荐香水"
    constraints, issues = parse_exact_constraints(message)

    assert not any(
        isinstance(item, BudgetDraft)
        for item in constraints
    )
    assert [issue.code for issue in issues] == ["invalid_budget"]


@pytest.mark.parametrize("sign", ("-", "−", "－"))
@pytest.mark.parametrize("spacing", ("", " "))
def test_budget_prefixed_negative_number_without_unit_fails_closed(
    sign: str,
    spacing: str,
) -> None:
    constraints, issues = parse_exact_constraints(
        f"预算{spacing}{sign}{spacing}100推荐香水"
    )

    assert not any(
        isinstance(item, BudgetDraft)
        for item in constraints
    )
    assert [issue.code for issue in issues] == ["invalid_budget"]


@pytest.mark.parametrize(
    ("raw_amount", "expected"),
    (
        ("1,000", Decimal("1000")),
        ("1，000", Decimal("1000")),
        ("１，０００", Decimal("1000")),
        ("1 000", Decimal("1000")),
        ("1\u00a0000", Decimal("1000")),
        ("1\u202f000", Decimal("1000")),
        ("1'000", Decimal("1000")),
        ("1’000", Decimal("1000")),
        ("1‘000", Decimal("1000")),
        ("1＇000", Decimal("1000")),
        ("1,000.50", Decimal("1000.50")),
        ("１，０００．５０", Decimal("1000.50")),
        ("1,000,000.50", Decimal("1000000.50")),
    ),
)
def test_grouped_budget_numeric_grammar_normalizes_one_complete_value(
    raw_amount: str,
    expected: Decimal,
) -> None:
    message = f"预算{raw_amount}元推荐防晒"
    constraints, issues = parse_exact_constraints(message)
    budgets = [
        item
        for item in constraints
        if isinstance(item, BudgetDraft)
    ]

    assert len(budgets) == 1
    assert budgets[0].minimum is None
    assert budgets[0].maximum == expected
    assert issues == []


@pytest.mark.parametrize(
    ("raw_range", "expected_minimum", "expected_maximum"),
    (
        ("1,000到2,000", Decimal("1000"), Decimal("2000")),
        ("１，０００．５０至２，０００．７５", Decimal("1000.50"), Decimal("2000.75")),
        ("1 000~2 000", Decimal("1000"), Decimal("2000")),
        ("1\u202f000～2\u202f000", Decimal("1000"), Decimal("2000")),
        ("1'000-2'000", Decimal("1000"), Decimal("2000")),
    ),
)
def test_grouped_budget_range_parses_both_complete_tokens(
    raw_range: str,
    expected_minimum: Decimal,
    expected_maximum: Decimal,
) -> None:
    constraints, issues = parse_exact_constraints(
        f"预算{raw_range}元推荐防晒"
    )
    budgets = [
        item
        for item in constraints
        if isinstance(item, BudgetDraft)
    ]

    assert len(budgets) == 1
    assert budgets[0].minimum == expected_minimum
    assert budgets[0].maximum == expected_maximum
    assert issues == []


@pytest.mark.parametrize(
    "raw_amount",
    (
        "1,",
        "1,00",
        "1,5",
        "1,000,",
        "1,000,00",
        "1,000，000",
        "1,000 000",
        "1 000,000",
        "1,000’000",
        "1 00",
        "1_000",
        "1/000",
        "1:000",
    ),
)
def test_ambiguous_or_malformed_grouped_budget_fails_closed(
    raw_amount: str,
) -> None:
    constraints, issues = parse_exact_constraints(
        f"预算{raw_amount}元推荐防晒"
    )

    assert not any(
        isinstance(item, BudgetDraft)
        for item in constraints
    )
    assert [issue.code for issue in issues] == ["invalid_budget"]


@pytest.mark.parametrize("boundary", ("。", ".", "！", "!", "？", "?", "；", ";"))
def test_terminal_clause_topic_does_not_inherit_prior_exclusion(
    boundary: str,
) -> None:
    message = f"不要香水{boundary}防晒"
    topic, issues = _parsed_category(message)
    events = exact_parsing._selection_events(message)

    assert topic is TopicCode.SUNSCREEN
    assert issues == []
    assert [
        (event.target_topic, event.polarity.value)
        for event in events
    ] == [(TopicCode.FRAGRANCE, "negative")]
    assert exact_parsing.parse_hard_category_exclusions(message) == (
        TopicCode.FRAGRANCE,
    )


@pytest.mark.parametrize("boundary", ("，", ",", "、"))
def test_category_list_punctuation_keeps_shared_negative_action(
    boundary: str,
) -> None:
    message = f"不要香水{boundary}防晒"
    topic, issues = _parsed_category(message)

    assert topic is None
    assert issues == []
    assert exact_parsing.parse_hard_category_exclusions(message) == (
        TopicCode.FRAGRANCE,
        TopicCode.SUNSCREEN,
    )


@pytest.mark.parametrize(
    ("message", "operator", "polarity", "strength", "target"),
    (
        (
            "无意选择香水",
            "negated",
            "negative",
            "explicit",
            "香水",
        ),
        (
            "不太想选择木质调的香水",
            "hedged",
            "unknown",
            "hedged",
            "木质调的香水",
        ),
    ),
)
def test_selection_event_owns_typed_operator_action_target_and_consumed_spans(
    message: str,
    operator: str,
    polarity: str,
    strength: str,
    target: str,
) -> None:
    events = exact_parsing._selection_events(message)

    assert len(events) == 1
    event = events[0]
    assert event.operator.value == operator
    assert event.polarity.value == polarity
    assert event.strength.value == strength
    assert event.action.value == "select"
    assert (
        message[event.action_span.start:event.action_span.end]
        == "选择"
    )
    assert (
        message[event.target_span.start:event.target_span.end]
        == target
    )
    assert (
        message[event.consumed_span.start:event.consumed_span.end]
        == message
    )


@pytest.mark.parametrize("message", ["持妆", "显白", "木质调"])
def test_attribute_words_alone_do_not_claim_category_owner(
    message: str,
) -> None:
    assert _parsed_topic(message) is None


@pytest.mark.parametrize("message", ["推荐精华油", "想买洁面仪"])
def test_alias_with_unsupported_suffix_fails_closed(
    message: str,
) -> None:
    topic, _ = _parsed_category(message)

    assert topic is None


def test_negated_category_does_not_override_positive_category() -> None:
    topic, issues = _parsed_category("不要防晒，推荐香水")

    assert topic is TopicCode.FRAGRANCE
    assert issues == []


@pytest.mark.parametrize(
    "message",
    [
        "不要给我推荐防晒，推荐香水",
        "无需考虑防晒，推荐香水",
        "不想买防晒，推荐香水",
        "别再看防晒，推荐香水",
        "不要防晒：推荐香水",
    ],
)
def test_clause_scoped_negation_keeps_only_later_positive_category(
    message: str,
) -> None:
    topic, issues = _parsed_category(message)

    assert topic is TopicCode.FRAGRANCE
    assert issues == []


def test_clause_scoped_negation_can_exclude_all_category_aliases() -> None:
    topic, issues = _parsed_category("不要给我推荐防晒和香水")

    assert topic is None
    assert issues == []


def test_selection_negation_spans_arbitrary_text_before_category() -> None:
    topic, issues = _parsed_category("不需要任何防晒，推荐香水")

    assert topic is TopicCode.FRAGRANCE
    assert issues == []


def test_selection_negation_applies_to_each_later_alias_in_clause() -> None:
    topic, issues = _parsed_category("不需要任何防晒和香水")

    assert topic is None
    assert issues == []


@pytest.mark.parametrize(
    "filler",
    [
        "给我推荐",
        "考虑",
        "任何",
        "任何相关的",
        "再看看",
        "优先排除掉",
    ],
)
def test_selection_negation_does_not_depend_on_filler_whitelist(
    filler: str,
) -> None:
    topic, issues = _parsed_category(
        f"不需要{filler}防晒，推荐香水"
    )

    assert topic is TopicCode.FRAGRANCE
    assert issues == []


@pytest.mark.parametrize(
    "cue",
    [
        "不要",
        "不用",
        "无需",
        "不想",
        "不考虑",
        "不需要",
        "别",
        "排除",
        "拒绝",
        "不是",
    ],
)
def test_explicit_selection_negation_cues_scope_to_category(
    cue: str,
) -> None:
    topic, issues = _parsed_category(f"{cue}香水，推荐防晒")

    assert topic is TopicCode.SUNSCREEN
    assert issues == []


@pytest.mark.parametrize(
    "message",
    [
        "不要香水但要防晒",
        "不考虑香水改要防晒",
    ],
)
def test_explicit_positive_reset_restores_later_category(
    message: str,
) -> None:
    topic, issues = _parsed_category(message)

    assert topic is TopicCode.SUNSCREEN
    assert issues == []


@pytest.mark.parametrize(
    "reset",
    [
        "但要",
        "但是要",
        "而是要",
        "改要",
        "还是要",
        "转而要",
        "换成",
        "只要",
    ],
)
def test_positive_selection_reset_restores_only_later_alias(
    reset: str,
) -> None:
    topic, issues = _parsed_category(
        f"不需要任何香水{reset}防晒"
    )

    assert topic is TopicCode.SUNSCREEN
    assert issues == []


@pytest.mark.parametrize(
    ("message", "topic"),
    _RESET_SENTENCE_CASES,
)
def test_structural_scope_restores_all_24_verifier_reset_sentences(
    message: str,
    topic: TopicCode,
) -> None:
    assert len(_RESET_SENTENCE_CASES) == 24
    assert _parsed_topic(message) is topic


@pytest.mark.parametrize(
    "intermediate_text",
    _UNKNOWN_INTERMEDIATE_TEXTS,
)
@pytest.mark.parametrize(
    ("source_alias", "target_alias", "target_topic"),
    _RESET_ALIAS_TRANSITIONS,
)
def test_unknown_nonempty_intermediate_text_restores_later_alias(
    intermediate_text: str,
    source_alias: str,
    target_alias: str,
    target_topic: TopicCode,
) -> None:
    assert _parsed_topic(
        f"不要{source_alias}{intermediate_text}{target_alias}"
    ) is target_topic


@pytest.mark.parametrize("cue", ["不要", "不需要"])
@pytest.mark.parametrize(
    "connector",
    [
        "和",
        "或",
        "、",
        "以及",
        "跟",
        "与",
        "及",
        "还有",
        "/",
        " 和/或 ",
    ],
)
def test_coordination_only_keeps_both_aliases_negated(
    cue: str,
    connector: str,
) -> None:
    assert _parsed_topic(f"{cue}香水{connector}防晒") is None


@pytest.mark.parametrize(
    "modifier",
    ["平价", "高端", "适合学生的"],
)
@pytest.mark.parametrize(
    "connector",
    ["以及", "并且", "并", "且"],
)
def test_modified_coordinated_category_remains_negated(
    connector: str,
    modifier: str,
) -> None:
    topic, issues = _parsed_category(
        f"不考虑防晒{connector}{modifier}香水"
    )

    assert topic is None
    assert issues == []


@pytest.mark.parametrize(
    "message",
    [
        "不考虑防晒并想买平价香水",
        "不考虑防晒并推荐平价香水",
        "不考虑防晒且想买平价香水",
        "不考虑防晒并且推荐平价香水",
    ],
)
def test_explicit_positive_predicate_stops_coordination_negation(
    message: str,
) -> None:
    assert _parsed_topic(message) is TopicCode.FRAGRANCE


@pytest.mark.parametrize(
    "connector",
    ["并且", "并", "且", "以及"],
)
@pytest.mark.parametrize(
    "predicate",
    ["想买", "想要", "要买", "推荐", "改买"],
)
def test_task26_direct_positive_predicate_restores_category(
    connector: str,
    predicate: str,
) -> None:
    assert _parsed_topic(
        f"不考虑防晒{connector}{predicate}平价香水"
    ) is TopicCode.FRAGRANCE


@pytest.mark.parametrize(
    "message",
    [
        "不考虑防晒并不想买香水",
        "不考虑防晒并非要买香水",
        "不考虑防晒并想要避开的香水",
        "不考虑防晒并推荐避雷香水",
        "不考虑防晒并想买但不买香水",
    ],
)
def test_task26_negative_compound_does_not_restore_category(
    message: str,
) -> None:
    topic, issues = _parsed_category(message)

    assert topic is None
    assert issues == []


def test_task26_last_category_negation_overrides_earlier_restoration() -> None:
    topic, issues = _parsed_category(
        "不考虑防晒并改买香水但不要香水"
    )

    assert topic is None
    assert issues == []


@pytest.mark.parametrize(
    "message",
    [
        "不甜的香水",
        "不贵的香水",
        "不含酒精的香水",
    ],
)
def test_task26_attribute_negation_keeps_positive_category(
    message: str,
) -> None:
    assert _parsed_topic(message) is TopicCode.FRAGRANCE


@pytest.mark.parametrize(
    "message",
    [
        "避开甜腻的香水",
        "不要太甜的香水",
        "不想要太甜的香水",
    ],
)
def test_task27_attribute_exclusion_keeps_positive_category(
    message: str,
) -> None:
    topic, issues = _parsed_category(message)

    assert topic is TopicCode.FRAGRANCE
    assert [item.code for item in issues] == [
        "unsupported_attribute_exclusion"
    ]


@pytest.mark.parametrize(
    "cue",
    ["不要", "避开", "排除", "拒绝"],
)
@pytest.mark.parametrize(
    "category_target",
    [
        "所有的",
        "所有",
        "全部的",
        "全部",
        "这类的",
        "这类",
        "这种的",
        "这种",
    ],
)
def test_task28_quantified_category_target_remains_negated(
    cue: str,
    category_target: str,
) -> None:
    assert _parsed_topic(f"{cue}{category_target}香水") is None


@pytest.mark.parametrize(
    "message",
    [
        "避开甜腻的香水",
        "不要太甜的香水",
        "不想要太甜的香水",
    ],
)
def test_task28_pure_attribute_target_remains_positive(
    message: str,
) -> None:
    topic, issues = _parsed_category(message)

    assert topic is TopicCode.FRAGRANCE
    assert [item.code for item in issues] == [
        "unsupported_attribute_exclusion"
    ]


@pytest.mark.parametrize("cue", ["不要", "避开", "排除", "拒绝"])
@pytest.mark.parametrize("quantifier", _TASK29_CATEGORY_QUANTIFIERS)
@pytest.mark.parametrize("particle", ["", "的"])
def test_task29_closed_quantifier_set_remains_category_negative(
    cue: str,
    quantifier: str,
    particle: str,
) -> None:
    assert _parsed_topic(f"{cue}{quantifier}{particle}香水") is None


@pytest.mark.parametrize("quantifier", _TASK29_CATEGORY_QUANTIFIERS)
def test_task29_quantifiers_are_lexed_by_grammatical_class(
    quantifier: str,
) -> None:
    tokens = exact_parsing._lex_exact_tokens(quantifier)

    assert [
        token.value
        for token in tokens
        if token.kind.value == "category_quantifier"
    ] == [quantifier]


@pytest.mark.parametrize("attribute", ["太甜的", "清新的", "全哑光的"])
def test_task29_attributes_do_not_emit_quantifier_tokens(
    attribute: str,
) -> None:
    assert not any(
        token.kind.value == "category_quantifier"
        for token in exact_parsing._lex_exact_tokens(attribute)
    )


@pytest.mark.parametrize(
    "message",
    [
        "避开甜腻的香水",
        "不要太甜的香水",
        "不想要太甜的香水",
    ],
)
def test_task29_unsupported_sensory_exclusion_is_typed_uncertainty(
    message: str,
) -> None:
    understanding = understand_text(message)

    categories = [
        item
        for item in understanding.exact_constraints
        if isinstance(item, CategoryDraft)
    ]
    exclusions = [
        item
        for item in understanding.exact_constraints
        if isinstance(item, ExclusionDraft)
    ]
    assert [item.value for item in categories] == [TopicCode.FRAGRANCE]
    assert exclusions == []
    assert [item.code for item in understanding.uncertainties] == [
        "unsupported_attribute_exclusion"
    ]
    assert "属性描述" in understanding.uncertainties[0].detail
    assert understanding.confidence == 0.0


@pytest.mark.parametrize("cue", ["不要", "避开", "排除", "不想要"])
@pytest.mark.parametrize(
    "attribute",
    _TASK30_NESTED_NEGATIVE_ATTRIBUTES,
)
def test_task30_consumed_unsupported_attribute_is_not_reparsed_as_exclusion(
    cue: str,
    attribute: str,
) -> None:
    understanding = understand_text(f"{cue}{attribute}香水")

    categories = [
        item
        for item in understanding.exact_constraints
        if isinstance(item, CategoryDraft)
    ]
    exclusions = [
        item
        for item in understanding.exact_constraints
        if isinstance(item, ExclusionDraft)
    ]
    assert [item.value for item in categories] == [TopicCode.FRAGRANCE]
    assert exclusions == []
    assert [item.code for item in understanding.uncertainties] == [
        "unsupported_attribute_exclusion"
    ]
    assert understanding.confidence == 0.0


@pytest.mark.parametrize("cue", ["不要", "避开", "排除", "拒绝"])
@pytest.mark.parametrize("quantifier", _TASK29_CATEGORY_QUANTIFIERS)
@pytest.mark.parametrize("particle", ["", "的"])
def test_task30_consumed_category_target_is_not_reparsed_as_exclusion(
    cue: str,
    quantifier: str,
    particle: str,
) -> None:
    understanding = understand_text(
        f"{cue}{quantifier}{particle}香水"
    )

    assert not any(
        isinstance(item, ExclusionDraft)
        for item in understanding.exact_constraints
    )


@pytest.mark.parametrize(
    "message",
    [
        "不要含酒精的香水",
        "不含酒精的香水",
    ],
)
def test_task30_ordinary_ingredient_exclusion_remains_authorized(
    message: str,
) -> None:
    understanding = understand_text(message)

    categories = [
        item.value
        for item in understanding.exact_constraints
        if isinstance(item, CategoryDraft)
    ]
    exclusions = [
        item.value
        for item in understanding.exact_constraints
        if isinstance(item, ExclusionDraft)
    ]
    assert categories == [TopicCode.FRAGRANCE]
    assert exclusions == ["酒精"]
    assert understanding.uncertainties == []


@pytest.mark.parametrize(
    "cue",
    ["不要有", "不要含", "不含", "不能有", "无"],
)
@pytest.mark.parametrize("ingredient", ["酒精", "香精"])
def test_task31_ingredient_exclusion_uses_bare_value(
    cue: str,
    ingredient: str,
) -> None:
    understanding = understand_text(f"{cue}{ingredient}的香水")

    categories = [
        item.value
        for item in understanding.exact_constraints
        if isinstance(item, CategoryDraft)
    ]
    exclusions = [
        item.value
        for item in understanding.exact_constraints
        if isinstance(item, ExclusionDraft)
    ]
    assert categories == [TopicCode.FRAGRANCE]
    assert exclusions == [ingredient]
    assert all(not value.startswith("有") for value in exclusions)
    assert understanding.uncertainties == []


@pytest.mark.parametrize("outer_cue", _TASK32_OUTER_EXCLUSION_CUES)
@pytest.mark.parametrize("inner_cue", _TASK32_INNER_ABSENCE_CUES)
@pytest.mark.parametrize("ingredient", _TASK32_INGREDIENTS)
@pytest.mark.parametrize(("category", "topic"), _TASK32_CATEGORIES)
def test_task32_nested_absence_span_has_priority_over_ingredient_exclusion(
    outer_cue: str,
    inner_cue: str,
    ingredient: str,
    category: str,
    topic: TopicCode,
) -> None:
    understanding = understand_text(
        f"{outer_cue}{inner_cue}{ingredient}的{category}"
    )

    categories = [
        item.value
        for item in understanding.exact_constraints
        if isinstance(item, CategoryDraft)
    ]
    exclusions = [
        item.value
        for item in understanding.exact_constraints
        if isinstance(item, ExclusionDraft)
    ]
    assert categories == [topic]
    assert exclusions == []
    assert [item.code for item in understanding.uncertainties] == [
        "unsupported_attribute_exclusion"
    ]
    assert understanding.confidence == 0.0


@pytest.mark.parametrize(
    "message",
    [
        "想要避开的香水",
        "推荐避雷香水",
        "想买但不买香水",
    ],
)
def test_task27_category_negation_removes_positive_category(
    message: str,
) -> None:
    assert _parsed_topic(message) is None


@pytest.mark.parametrize(
    "message",
    [
        "推荐防晒但不推荐防晒",
        "不考虑防晒并改买香水但最后不推荐香水",
    ],
)
def test_task27_last_same_topic_negation_wins(
    message: str,
) -> None:
    assert _parsed_topic(message) is None


@pytest.mark.parametrize(
    "message",
    [
        "不考虑防晒，不过我想要平价香水",
        "不考虑防晒但后来还是想买高端香水",
        "不考虑防晒以及后来还是想买高端香水",
        "不考虑防晒以及后来还是要买高端香水",
        "不考虑防晒以及后来还是想要高端香水",
        "不考虑防晒以及我后来还是想买高端香水",
        "不考虑防晒以及后来改买高端香水",
        "不考虑防晒转头看看适合学生的香水",
    ],
)
def test_real_positive_transition_restores_modified_category(
    message: str,
) -> None:
    assert _parsed_topic(message) is TopicCode.FRAGRANCE


@pytest.mark.parametrize(
    ("message", "topic"),
    [
        ("不要香水也不要防晒", None),
        (
            "不要香水不过我想要防晒也不要面霜",
            TopicCode.SUNSCREEN,
        ),
    ],
)
def test_last_negation_cue_negates_its_later_alias(
    message: str,
    topic: TopicCode | None,
) -> None:
    assert _parsed_topic(message) is topic


@pytest.mark.parametrize(
    ("message", "topic"),
    [
        ("不要防晒不过我想要防晒", TopicCode.SUNSCREEN),
        ("不要防晒和防晒", None),
        ("不要防晒隔离不过我想要防晒", TopicCode.SUNSCREEN),
        ("不要精华水相反改选精华", TopicCode.SERUM),
    ],
)
def test_structural_scope_handles_repeated_and_longest_aliases(
    message: str,
    topic: TopicCode | None,
) -> None:
    assert _parsed_topic(message) is topic


def test_reset_before_last_negation_cue_does_not_escape_its_scope() -> None:
    topic, issues = _parsed_category(
        "不需要香水但要防晒而不需要任何面霜"
    )

    assert topic is TopicCode.SUNSCREEN
    assert issues == []


@pytest.mark.parametrize(
    ("message", "topic"),
    [
        ("防晒不要，推荐香水", TopicCode.FRAGRANCE),
        ("防晒和香水都不要", None),
    ],
)
def test_suffix_category_negation_is_preserved(
    message: str,
    topic: TopicCode | None,
) -> None:
    parsed_topic, issues = _parsed_category(message)

    assert parsed_topic is topic
    assert issues == []


@pytest.mark.parametrize(
    "message",
    [
        "不贵的防晒",
        "不闷的防晒",
        "不要含酒精的防晒",
        "不要酒精的防晒",
    ],
)
def test_non_category_negation_does_not_hide_positive_category(
    message: str,
) -> None:
    assert _parsed_topic(message) is TopicCode.SUNSCREEN


def test_word_containing_negation_character_is_not_a_category_cue() -> None:
    topic, issues = _parsed_category("分别推荐防晒和香水")

    assert topic is None
    assert [item.code for item in issues] == ["ambiguous_category"]


@pytest.mark.parametrize(
    ("alias", "topic"),
    exact_parsing._CATEGORY_ALIASES,
)
def test_all_registered_category_aliases_remain_compatible(
    alias: str,
    topic: TopicCode,
) -> None:
    assert _parsed_topic(f"推荐{alias}") is topic


def test_distinct_positive_topics_require_clarification() -> None:
    topic, issues = _parsed_category("粉底液还是口红")

    assert topic is None
    assert [item.code for item in issues] == ["ambiguous_category"]
    assert "多个" in issues[0].detail
