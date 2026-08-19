from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.understanding.consultation_escalation import (
    ConsultationEscalationTrigger,
)
from app.guide.understanding.consultation_questions import (
    ConsultationQuestion,
    ObservationAnswer,
)


ConsultationParseKind = Literal[
    "entry",
    "answer",
    "confirm",
    "reject",
    "clarify",
]
ClarificationReason = Literal[
    "answer_required",
    "confirmation_required",
]

_TERMINAL_PUNCTUATION = re.compile(r"[\s,，。.!！:：;；?？]+")
_CLAUSE_BOUNDARY = re.compile(
    r"[,，。.!！;；?？]+|(?:而且|另外|同时|并且|还是|或者|或)"
)
_ENTRY_PHRASES = frozenset(
    {
        "我不知道自己是什么肤质",
        "不知道自己是什么肤质",
        "我不清楚自己是什么肤质",
        "我不知道肤质",
        "帮我判断一下肤质",
        "帮我判断肤质",
        "我想测一下肤质",
        "想做肤质判断",
        "开始肤质问诊",
        "开始肤质测试",
    }
)
_ANSWER_PHRASES: dict[str, ObservationAnswer] = {
    **{
        phrase: "yes"
        for phrase in (
            "是",
            "是的",
            "会",
            "会的",
            "有",
            "有的",
            "经常",
            "经常会",
            "明显会",
            "yes",
        )
    },
    **{
        phrase: "no"
        for phrase in (
            "不",
            "不是",
            "不会",
            "没有",
            "不太会",
            "从不",
            "no",
        )
    },
    **{
        phrase: "sometimes"
        for phrase in (
            "有时",
            "有时候",
            "偶尔",
            "偶尔会",
            "时有时无",
            "sometimes",
        )
    },
    **{
        phrase: "unknown"
        for phrase in (
            "不知道",
            "不清楚",
            "没注意",
            "没留意",
            "无法判断",
            "unknown",
        )
    },
}
_QUESTION_ANSWER_PHRASES: dict[
    str,
    dict[str, ObservationAnswer],
] = {
    "post_cleanse_tightness": {
        "洗脸后会紧绷": "yes",
        "洁面后会紧绷": "yes",
        "洗脸后不紧绷": "no",
        "洁面后不紧绷": "no",
    },
    "t_zone_oiliness": {
        "t区会出油": "yes",
        "额头和鼻子会出油": "yes",
        "t区不会出油": "no",
        "额头和鼻子不会出油": "no",
        "t区有时候会出油": "sometimes",
    },
    "recurrent_redness": {
        "会反复泛红": "yes",
        "不会反复泛红": "no",
        "偶尔会泛红": "sometimes",
    },
    "stinging": {
        "用护肤品会刺痛": "yes",
        "基础护肤品会刺痛": "yes",
        "用护肤品不会刺痛": "no",
        "基础护肤品不会刺痛": "no",
    },
    "flaking": {
        "会脱屑": "yes",
        "会起皮": "yes",
        "不会脱屑": "no",
        "不会起皮": "no",
        "不清楚有没有脱屑": "unknown",
    },
}
_CONFIRM_PHRASES = frozenset(
    {
        "确认",
        "我确认",
        "是的我确认",
        "yesiconfirm",
        "iconfirm",
        "confirm",
    }
)
_GENERIC_CONFIRMATION = re.compile(
    r"^(?:(?:对|是的|没错)(?:就是)?这样|"
    r"(?:对|是的|没错)?(?:我)?(?:确认|认可|同意)"
    r"(?:(?:这个|这项|该)(?:判断|结论|结果))?)$"
)
_TARGET_WORDS = (
    "油敏肌",
    "油性敏感肌",
    "油皮",
    "油性肤质",
    "干皮",
    "干性肤质",
    "混合皮",
    "混合性肤质",
    "敏感肌",
    "敏感性肤质",
    "中性皮",
    "中性肤质",
    "oily_sensitive",
    "oily",
    "dry",
    "combination",
    "sensitive",
    "normal",
)
_TARGET_CONFIRMATION = re.compile(
    r"^(?:我)?确认(?:我)?是(?:"
    + "|".join(re.escape(item) for item in _TARGET_WORDS)
    + r")$"
)
_REJECT_PHRASES = frozenset(
    {
        "不确认",
        "我不确认",
        "不是",
        "不对",
        "这个结论不对",
        "我不认可这个结论",
        "我拒绝这个结论",
        "reject",
        "no",
    }
)
_CLAUSE_PREFIXES = (
    "我现在的皮肤",
    "我最近的皮肤",
    "我目前的皮肤",
    "我的皮肤",
    "现在皮肤",
    "最近皮肤",
    "目前皮肤",
    "皮肤",
    "我现在",
    "我最近",
    "我目前",
    "现在",
    "最近",
    "目前",
    "我",
    "也",
    "还",
)
_RED_FLAG_PHRASES: tuple[
    tuple[
        Literal["persistent_swelling", "pain", "oozing"],
        frozenset[str],
    ],
    ...,
] = (
    (
        "persistent_swelling",
        frozenset(
            {
                "持续红肿",
                "一直红肿",
                "红肿一直不退",
                "持续肿胀",
                "反复肿胀",
                "persistentswelling",
            }
        ),
    ),
    (
        "pain",
        frozenset(
            {
                "明显疼痛",
                "持续疼痛",
                "一直疼",
                "疼痛",
                "很疼",
                "pain",
            }
        ),
    ),
    (
        "oozing",
        frozenset(
            {
                "有渗出",
                "出现渗出",
                "正在渗出",
                "有液体渗出",
                "流黄水",
                "渗出",
                "oozing",
            }
        ),
    ),
)


class ConsultationTurnParse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    kind: ConsultationParseKind
    answer: ObservationAnswer | None = None
    clarification_reason: ClarificationReason | None = None
    escalation_triggers: tuple[
        ConsultationEscalationTrigger,
        ...,
    ] = Field(
        default_factory=tuple,
        max_length=3,
    )

    @field_validator("escalation_triggers", mode="before")
    @classmethod
    def freeze_triggers(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if (self.kind == "answer") != (self.answer is not None):
            raise ValueError("only answer parse results carry an answer")
        if (self.kind == "clarify") != (
            self.clarification_reason is not None
        ):
            raise ValueError(
                "only clarification results carry a clarification reason"
            )
        codes = [item.code for item in self.escalation_triggers]
        if len(codes) != len(set(codes)):
            raise ValueError("escalation trigger codes must be unique")
        return self


def parse_consultation_turn(
    message: str,
    *,
    source_turn_id: str,
    active_question: ConsultationQuestion | None = None,
    awaiting_confirmation: bool = False,
) -> ConsultationTurnParse | None:
    if not isinstance(message, str):
        raise TypeError("message must be a string")
    if active_question is not None and not isinstance(
        active_question,
        ConsultationQuestion,
    ):
        raise TypeError("active_question must be a ConsultationQuestion")
    if active_question is not None and awaiting_confirmation:
        raise ValueError("consultation parser context is conflicting")

    clauses = _clauses(message)
    triggers = _red_flags(
        clauses,
        source_turn_id=source_turn_id,
    )
    if active_question is not None:
        question_answers = _QUESTION_ANSWER_PHRASES[
            active_question.code
        ]
        answers = {
            answer
            for clause in clauses
            if (
                answer := (
                    _ANSWER_PHRASES.get(_normalize(clause))
                    or question_answers.get(_normalize(clause))
                )
            )
            is not None
        }
        if len(answers) == 1:
            return ConsultationTurnParse(
                kind="answer",
                answer=answers.pop(),
                escalation_triggers=triggers,
            )
        return ConsultationTurnParse(
            kind="clarify",
            clarification_reason="answer_required",
            escalation_triggers=triggers,
        )
    normalized = _normalize(message)
    if awaiting_confirmation:
        if (
            is_explicit_consultation_confirmation(message)
            or _TARGET_CONFIRMATION.fullmatch(normalized) is not None
        ):
            kind: ConsultationParseKind = "confirm"
            reason = None
        elif normalized in _REJECT_PHRASES:
            kind = "reject"
            reason = None
        else:
            kind = "clarify"
            reason = "confirmation_required"
        return ConsultationTurnParse(
            kind=kind,
            clarification_reason=reason,
            escalation_triggers=triggers,
        )

    entry_clauses = [
        _normalize(clause)
        for clause in clauses
        if _normalize(clause) in _ENTRY_PHRASES
    ]
    if len(entry_clauses) == 1:
        return ConsultationTurnParse(
            kind="entry",
            escalation_triggers=triggers,
        )
    return None


def is_explicit_consultation_confirmation(message: str) -> bool:
    if not isinstance(message, str):
        return False
    normalized = _normalize(message)
    return (
        normalized in _CONFIRM_PHRASES
        or _GENERIC_CONFIRMATION.fullmatch(normalized) is not None
    )


def _normalize(value: str) -> str:
    return _TERMINAL_PUNCTUATION.sub("", value).casefold()


def _clauses(message: str) -> tuple[str, ...]:
    return tuple(
        clause.strip()
        for clause in _CLAUSE_BOUNDARY.split(message)
        if clause.strip()
    )


def _red_flags(
    clauses: tuple[str, ...],
    *,
    source_turn_id: str,
) -> tuple[ConsultationEscalationTrigger, ...]:
    normalized_clauses = {
        _medical_clause(clause)
        for clause in clauses
    }
    return tuple(
        ConsultationEscalationTrigger(
            code=code,
            source_turn_id=source_turn_id,
        )
        for code, phrases in _RED_FLAG_PHRASES
        if normalized_clauses & phrases
    )


def _medical_clause(value: str) -> str:
    normalized = _normalize(value)
    changed = True
    while changed:
        changed = False
        for prefix in _CLAUSE_PREFIXES:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
                changed = True
                break
    return normalized
