from decimal import Decimal

from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
    RecommendationQueryContext,
)
from app.guide.intent.followup_planning import plan_followup
from app.guide.understanding.followup_parsing import parse_followup
from app.guide.understanding.contracts import FollowupDraft


def snapshot() -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id="s-1",
        version=1,
        query_context=RecommendationQueryContext(
            category="serum",
            budget_minimum=None,
            budget_maximum=Decimal("500"),
            skin="sensitive",
            efficacy="repair",
            exclusions=[],
        ),
        candidates=[
            DisplayedCandidateRef(
                product_id=91,
                ordinal=1,
                skin_match="unknown",
                matched_efficacies=["修护"],
            ),
            DisplayedCandidateRef(
                product_id=38,
                ordinal=2,
                skin_match="unknown",
                matched_efficacies=["修护"],
            ),
        ],
    )


def four_candidate_snapshot() -> ConversationSnapshot:
    current = snapshot()
    return ConversationSnapshot(
        session_id=current.session_id,
        version=current.version,
        query_context=current.query_context,
        candidates=[
            *current.candidates,
            DisplayedCandidateRef(
                product_id=55,
                ordinal=3,
                skin_match="unknown",
                matched_efficacies=["修护"],
            ),
            DisplayedCandidateRef(
                product_id=72,
                ordinal=4,
                skin_match="unknown",
                matched_efficacies=["修护"],
            ),
        ],
    )


def test_valid_ordinal_followup_plan() -> None:
    plan = plan_followup(
        parse_followup("第二款呢"),
        snapshot=snapshot(),
        request_version=1,
    )
    assert plan is not None
    assert plan.mode == "followup"
    assert plan.ordinal == 2


def test_missing_snapshot_clarifies() -> None:
    plan = plan_followup(
        parse_followup("第二款呢"),
        snapshot=None,
        request_version=1,
    )
    assert plan is not None
    assert plan.mode == "clarify"
    assert plan.clarification == (
        "我还没有前面那组商品，请先发起一次推荐。"
    )


def test_stale_version_and_out_of_range_clarify() -> None:
    stale = plan_followup(
        parse_followup("第二款呢"),
        snapshot=snapshot(),
        request_version=0,
    )
    assert stale is not None
    assert stale.mode == "clarify"
    assert "状态已变化" in stale.clarification

    out_of_range = plan_followup(
        parse_followup("第四款"),
        snapshot=snapshot(),
        request_version=1,
    )
    assert out_of_range is not None
    assert out_of_range.mode == "clarify"
    assert "只展示了 2 款" in out_of_range.clarification


def test_fourth_ordinal_is_valid_and_fifth_is_out_of_range() -> None:
    current = four_candidate_snapshot()

    valid = plan_followup(
        parse_followup("第四款呢"),
        snapshot=current,
        request_version=1,
    )
    assert valid is not None
    assert valid.mode == "followup"
    assert valid.ordinal == 4

    out_of_range = plan_followup(
        parse_followup("第五款呢"),
        snapshot=current,
        request_version=1,
    )
    assert out_of_range is not None
    assert out_of_range.mode == "clarify"
    assert "只展示了 4 款" in out_of_range.clarification
    assert "没有第 5 款" in out_of_range.clarification


def test_exact_ordinal_above_visible_range_is_parsed_then_clarified() -> None:
    draft = parse_followup("第九款")
    assert draft is not None
    assert draft.ordinal == 9

    plan = plan_followup(
        draft,
        snapshot=snapshot(),
        request_version=1,
    )
    assert plan is not None
    assert plan.mode == "clarify"
    assert "只展示了 2 款" in plan.clarification


def test_unsupported_ambiguous_followup_clarifies() -> None:
    plan = plan_followup(
        FollowupDraft(issue="unsupported_followup"),
        snapshot=snapshot(),
        request_version=1,
    )
    assert plan is not None
    assert plan.mode == "clarify"
    assert "序号和最低价" in plan.clarification
