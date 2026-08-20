from __future__ import annotations

import pytest

from app.guide.understanding.consultation_questions import (
    observable_questions,
)


_TURN_ID = "turn_parser_000000001"


@pytest.mark.parametrize(
    "message",
    [
        "我不知道自己是什么肤质",
        "帮我判断一下肤质",
        "我想测一下肤质。",
        "开始肤质问诊",
    ],
)
def test_explicit_consultation_entry_requires_a_complete_phrase(
    message: str,
) -> None:
    from app.guide.understanding.consultation_parsing import (
        parse_consultation_turn,
    )

    parsed = parse_consultation_turn(
        message,
        source_turn_id=_TURN_ID,
    )

    assert parsed is not None
    assert parsed.kind == "entry"
    assert parsed.answer is None
    assert parsed.clarification_reason is None


@pytest.mark.parametrize(
    "message",
    [
        "这款商品写着肤质测试",
        "我知道自己是油皮",
        "判断",
        "肤质",
    ],
)
def test_idle_parser_does_not_use_broad_entry_substrings(
    message: str,
) -> None:
    from app.guide.understanding.consultation_parsing import (
        parse_consultation_turn,
    )

    assert (
        parse_consultation_turn(
            message,
            source_turn_id=_TURN_ID,
        )
        is None
    )


@pytest.mark.parametrize(
    ("message", "answer"),
    [
        ("会", "yes"),
        ("是的。", "yes"),
        ("不会", "no"),
        ("没有", "no"),
        ("有时候", "sometimes"),
        ("偶尔会", "sometimes"),
        ("不知道", "unknown"),
        ("没留意", "unknown"),
    ],
)
def test_active_question_parses_only_bounded_answer_phrases(
    message: str,
    answer: str,
) -> None:
    from app.guide.understanding.consultation_parsing import (
        parse_consultation_turn,
    )

    parsed = parse_consultation_turn(
        message,
        active_question=observable_questions()[0],
        source_turn_id=_TURN_ID,
    )

    assert parsed is not None
    assert parsed.kind == "answer"
    assert parsed.answer == answer
    assert parsed.clarification_reason is None


@pytest.mark.parametrize(
    ("question_index", "message", "answer"),
    [
        (0, "洗脸后会紧绷", "yes"),
        (0, "洗脸后不紧绷", "no"),
        (1, "T区有时候会出油", "sometimes"),
        (2, "不会反复泛红", "no"),
        (3, "用护肤品会刺痛", "yes"),
        (4, "不清楚有没有脱屑", "unknown"),
    ],
)
def test_question_specific_answers_bind_to_active_question(
    question_index: int,
    message: str,
    answer: str,
) -> None:
    from app.guide.understanding.consultation_parsing import (
        parse_consultation_turn,
    )

    parsed = parse_consultation_turn(
        message,
        active_question=observable_questions()[question_index],
        source_turn_id=_TURN_ID,
    )

    assert parsed is not None
    assert parsed.kind == "answer"
    assert parsed.answer == answer


def test_question_specific_answer_is_not_reused_for_another_question() -> None:
    from app.guide.understanding.consultation_parsing import (
        parse_consultation_turn,
    )

    parsed = parse_consultation_turn(
        "洗脸后会紧绷",
        active_question=observable_questions()[1],
        source_turn_id=_TURN_ID,
    )

    assert parsed is not None
    assert parsed.kind == "clarify"
    assert parsed.answer is None


@pytest.mark.parametrize(
    "message",
    [
        "好像会，但不确定",
        "不是不会",
        "应该有吧",
        "确认",
    ],
)
def test_active_question_ambiguous_or_wrong_phase_input_clarifies(
    message: str,
) -> None:
    from app.guide.understanding.consultation_parsing import (
        parse_consultation_turn,
    )

    parsed = parse_consultation_turn(
        message,
        active_question=observable_questions()[0],
        source_turn_id=_TURN_ID,
    )

    assert parsed is not None
    assert parsed.kind == "clarify"
    assert parsed.answer is None
    assert parsed.clarification_reason == "answer_required"


@pytest.mark.parametrize(
    "message",
    [
        "是还是不是",
        "会还是不会",
        "是，还是不是",
        "会，还是不会",
        "是或不是",
        "会或者不会",
    ],
)
def test_positive_negative_alternatives_remain_ambiguous(
    message: str,
) -> None:
    from app.guide.understanding.consultation_parsing import (
        parse_consultation_turn,
    )

    parsed = parse_consultation_turn(
        message,
        active_question=observable_questions()[0],
        source_turn_id=_TURN_ID,
    )

    assert parsed is not None
    assert parsed.kind == "clarify"
    assert parsed.answer is None
    assert parsed.clarification_reason == "answer_required"


@pytest.mark.parametrize(
    ("message", "kind"),
    [
        ("确认", "confirm"),
        ("我确认是干皮", "confirm"),
        ("是的，我确认", "confirm"),
        ("对，确认这个判断", "confirm"),
        ("对，就是这样", "confirm"),
        ("不确认", "reject"),
        ("这个结论不对", "reject"),
        ("我不认可这个结论", "reject"),
        ("可能吧", "clarify"),
        ("确认是干皮还是油皮", "clarify"),
    ],
)
def test_confirmation_phase_requires_explicit_confirm_or_reject(
    message: str,
    kind: str,
) -> None:
    from app.guide.understanding.consultation_parsing import (
        parse_consultation_turn,
    )

    parsed = parse_consultation_turn(
        message,
        awaiting_confirmation=True,
        source_turn_id=_TURN_ID,
    )

    assert parsed is not None
    assert parsed.kind == kind
    assert parsed.answer is None
    assert parsed.clarification_reason == (
        "confirmation_required" if kind == "clarify" else None
    )


def test_answer_and_medical_red_flags_are_parsed_together() -> None:
    from app.guide.understanding.consultation_parsing import (
        parse_consultation_turn,
    )

    parsed = parse_consultation_turn(
        "会，而且持续红肿，还明显疼痛，有渗出",
        active_question=observable_questions()[0],
        source_turn_id=_TURN_ID,
    )

    assert parsed is not None
    assert parsed.kind == "answer"
    assert parsed.answer == "yes"
    assert tuple(item.code for item in parsed.escalation_triggers) == (
        "persistent_swelling",
        "pain",
        "oozing",
    )
    assert all(
        item.source_turn_id == _TURN_ID
        for item in parsed.escalation_triggers
    )


def test_exact_english_medical_red_flag_clauses_are_supported() -> None:
    from app.guide.understanding.consultation_parsing import (
        parse_consultation_turn,
    )

    parsed = parse_consultation_turn(
        "yes, persistent swelling, pain, oozing",
        active_question=observable_questions()[0],
        source_turn_id=_TURN_ID,
    )

    assert parsed is not None
    assert parsed.kind == "answer"
    assert tuple(item.code for item in parsed.escalation_triggers) == (
        "persistent_swelling",
        "pain",
        "oozing",
    )


@pytest.mark.parametrize(
    "message",
    [
        "不会，也没有红肿，没有疼痛，没有渗出",
        "这个产品宣传止痛成分",
        "之前红肿，现在已经消退",
        "不疼，也无渗出",
    ],
)
def test_medical_red_flags_do_not_match_negation_or_substrings(
    message: str,
) -> None:
    from app.guide.understanding.consultation_parsing import (
        parse_consultation_turn,
    )

    parsed = parse_consultation_turn(
        message,
        active_question=observable_questions()[0],
        source_turn_id=_TURN_ID,
    )

    assert parsed is not None
    assert parsed.escalation_triggers == ()


def test_parser_output_cannot_carry_user_target_conclusion_or_version() -> None:
    from app.guide.understanding.consultation_parsing import (
        parse_consultation_turn,
    )

    parsed = parse_consultation_turn(
        "我确认是油皮",
        awaiting_confirmation=True,
        source_turn_id=_TURN_ID,
    )

    assert parsed is not None
    payload = parsed.model_dump(mode="json")
    assert set(payload) == {
        "kind",
        "answer",
        "clarification_reason",
        "escalation_triggers",
    }
    assert not {"skin_target", "conclusion", "conversation_version"} & set(
        payload
    )


def test_parser_rejects_conflicting_trusted_context() -> None:
    from app.guide.understanding.consultation_parsing import (
        parse_consultation_turn,
    )

    with pytest.raises(ValueError, match="parser context"):
        parse_consultation_turn(
            "确认",
            active_question=observable_questions()[0],
            awaiting_confirmation=True,
            source_turn_id=_TURN_ID,
        )
