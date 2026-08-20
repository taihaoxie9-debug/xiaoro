from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
import re
import unicodedata

from app.guide.retrieval.category_taxonomy import (
    most_specific_compatible_topic,
)
from app.guide.understanding.colloquial_budget import (
    parse_colloquial_budget,
)
from app.guide.understanding.contracts import (
    BudgetDraft,
    CategoryDraft,
    EfficacyDraft,
    EfficacyTarget,
    ExactConstraintDraft,
    ExactRevisionConfirmation,
    ExactRevisionOperation,
    ExactRevisionTarget,
    ExclusionDraft,
    InclusionDraft,
    ReferenceDraft,
    SkinDraft,
    SkinTarget,
    SourceSpan,
    TopicCode,
    UnderstandingIssue,
)

_DIGIT = r"[0-9０-９]"
_NUMBER_INNER = rf"(?:{_DIGIT}|[,，٬'’‘＇.． \u00a0\u202f])"
_NUMBER = rf"(?:{_DIGIT}{_NUMBER_INNER}*{_DIGIT}|{_DIGIT})"
_NUMERIC_SIGN = r"[-−－]"
_RANGE_SEPARATOR = r"(?:到|至|[~～\-−－])"
_SIGNED_BUDGET_PREFIX = re.compile(
    rf"预算\s*(?P<sign>{_NUMERIC_SIGN})\s*"
    rf"(?P<value>{_NUMBER})"
)
_NEGATIVE_BUDGET = re.compile(
    rf"(?P<sign>{_NUMERIC_SIGN})\s*(?P<value>{_NUMBER})\s*"
    rf"(?:元|块|以内|内|以下|以上|到|至)"
)
_RANGE = re.compile(
    rf"(?<![-−－0-9０-９.．])(?P<minimum>{_NUMBER})\s*"
    rf"(?:元|块)?\s*{_RANGE_SEPARATOR}\s*"
    rf"(?P<maximum>{_NUMBER})\s*(?:元|块)?"
)
_MAXIMUM = re.compile(
    rf"(?<![-−－0-9０-９.．])(?P<maximum>{_NUMBER})\s*"
    rf"(?:元|块)?\s*(?:以内|内|以下)"
)
_MINIMUM = re.compile(
    rf"(?<![-−－0-9０-９.．])(?P<minimum>{_NUMBER})\s*"
    rf"(?:元|块)?\s*(?:以上|起)"
)
_BUDGET_PREFIX = re.compile(
    rf"预算\s*(?P<maximum>{_NUMBER})(?:\s*(?:元|块))?"
)
_BARE_CURRENCY = re.compile(
    rf"(?<![-−－0-9０-９.．])(?P<maximum>{_NUMBER})\s*(?:元|块)"
)
_BUDGET_REVISION_CUE = re.compile(
    r"(?:(?:预算\s*)?(?:降到|改成|调整到)|控制在)"
)
_BUDGET_GROUP_SEPARATORS = frozenset(
    {
        ",",
        "，",
        "٬",
        "'",
        "’",
        "‘",
        "＇",
        " ",
        "\u00a0",
        "\u202f",
    }
)
_BUDGET_DECIMAL_SEPARATORS = frozenset({".", "．"})
_CATEGORY_LIST_PUNCTUATION = frozenset(
    {",", "，", "、", "/", "／", "&", "＆", "+", "＋"}
)

_CATEGORY_ALIASES = tuple(sorted(
    {
        "防晒隔离": TopicCode.SUNSCREEN,
        "防晒乳液": TopicCode.SUNSCREEN,
        "防晒霜": TopicCode.SUNSCREEN,
        "防晒乳": TopicCode.SUNSCREEN,
        "防晒": TopicCode.SUNSCREEN,
        "眼部精华": TopicCode.SKINCARE,
        "精华水": TopicCode.SKINCARE,
        "爽肤水": TopicCode.SKINCARE,
        "乳液": TopicCode.SKINCARE,
        "乳霜": TopicCode.SKINCARE,
        "眼霜": TopicCode.SKINCARE,
        "面膜": TopicCode.SKINCARE,
        "面霜": TopicCode.SKINCARE,
        "护肤": TopicCode.SKINCARE,
        "精华液": TopicCode.SERUM,
        "精华": TopicCode.SERUM,
        "气垫粉底液": TopicCode.BASE_MAKEUP,
        "气垫粉底": TopicCode.BASE_MAKEUP,
        "粉底液": TopicCode.BASE_MAKEUP,
        "遮瑕膏": TopicCode.BASE_MAKEUP,
        "妆前乳": TopicCode.BASE_MAKEUP,
        "散粉": TopicCode.BASE_MAKEUP,
        "蜜粉": TopicCode.BASE_MAKEUP,
        "气垫": TopicCode.BASE_MAKEUP,
        "底妆": TopicCode.BASE_MAKEUP,
        "单色眼影": TopicCode.COLOR_MAKEUP,
        "眼影": TopicCode.COLOR_MAKEUP,
        "口红": TopicCode.COLOR_MAKEUP,
        "唇膏": TopicCode.COLOR_MAKEUP,
        "腮红": TopicCode.COLOR_MAKEUP,
        "彩妆": TopicCode.COLOR_MAKEUP,
        "卸妆洁肤液/卸妆水": TopicCode.CLEANSER,
        "洁面乳/泡沫洁面乳": TopicCode.CLEANSER,
        "洁面乳/洁面泡沫": TopicCode.CLEANSER,
        "卸妆水/洁肤液": TopicCode.CLEANSER,
        "洁面霜/洁面": TopicCode.CLEANSER,
        "洁颜油/卸妆油": TopicCode.CLEANSER,
        "洁颜霜/卸妆膏": TopicCode.CLEANSER,
        "洁面/清洁": TopicCode.CLEANSER,
        "泡沫洁面乳": TopicCode.CLEANSER,
        "洁面泡沫": TopicCode.CLEANSER,
        "卸妆油": TopicCode.CLEANSER,
        "洁颜油": TopicCode.CLEANSER,
        "卸妆水": TopicCode.CLEANSER,
        "洁肤液": TopicCode.CLEANSER,
        "卸妆膏": TopicCode.CLEANSER,
        "洁颜霜": TopicCode.CLEANSER,
        "洁面乳": TopicCode.CLEANSER,
        "洁面霜": TopicCode.CLEANSER,
        "洗面霜": TopicCode.CLEANSER,
        "洁面": TopicCode.CLEANSER,
        "卸妆": TopicCode.CLEANSER,
        "香水": TopicCode.FRAGRANCE,
    }.items(),
    key=lambda item: (-len(item[0]), item[0]),
))
_UNSUPPORTED_CATEGORY_SUFFIXES = {
    "眼部精华": ("油",),
    "精华": ("油",),
    "洁面": ("仪",),
    "护肤": ("步骤", "流程", "顺序", "方法", "哪一步", "哪步"),
}
_UNSUPPORTED_CATEGORY_PREFIXES = {
    "护肤": (
        "叠加",
        "叠加其他",
        "搭配",
        "搭配其他",
        "配合",
        "配合其他",
    ),
}
_EFFICACY_ALIASES = (
    ("抗衰老", EfficacyTarget.ANTI_AGING),
    ("补水保湿", EfficacyTarget.HYDRATION),
    ("舒缓", EfficacyTarget.SOOTHING),
    ("修护", EfficacyTarget.REPAIR),
    ("修复", EfficacyTarget.REPAIR),
    ("抗老", EfficacyTarget.ANTI_AGING),
    ("抗皱", EfficacyTarget.ANTI_AGING),
    ("美白", EfficacyTarget.BRIGHTENING),
    ("提亮", EfficacyTarget.BRIGHTENING),
    ("保湿", EfficacyTarget.HYDRATION),
    ("补水", EfficacyTarget.HYDRATION),
    ("控油", EfficacyTarget.OIL_CONTROL),
    ("祛痘", EfficacyTarget.ACNE_CARE),
)
_EFFICACY_ALIAS_PATTERN = "|".join(
    re.escape(alias) for alias, _target in _EFFICACY_ALIASES
)
_EFFICACY_REVISION_CUE = re.compile(
    r"(?:功效\s*)?(?:改成|改为|换成)"
)
_EFFICACY_TARGET_FIRST_WITHDRAWAL = re.compile(
    rf"(?P<proof>(?P<value>{_EFFICACY_ALIAS_PATTERN})\s*"
    r"(?:先)?(?:撤掉|去掉|取消|删掉))"
)
_EFFICACY_ACTION_FIRST_WITHDRAWAL = re.compile(
    rf"(?P<proof>(?:先)?(?:撤掉|去掉|取消|删掉)\s*"
    rf"(?P<value>{_EFFICACY_ALIAS_PATTERN}))"
)
_NONASSERTIVE_REVISION_MARKERS = (
    "如果",
    "假如",
    "要是",
    "是否",
    "也许",
    "可能",
    "不要",
    "别",
    "不必",
)
_SKIN_ALIASES = (
    ("油敏肌", SkinTarget.OILY_SENSITIVE),
    ("油敏", SkinTarget.OILY_SENSITIVE),
    ("敏感肌", SkinTarget.SENSITIVE),
    ("敏感皮", SkinTarget.SENSITIVE),
    ("油皮", SkinTarget.OILY),
    ("油性", SkinTarget.OILY),
    ("干性", SkinTarget.DRY),
    ("混合", SkinTarget.COMBINATION),
    ("敏感", SkinTarget.SENSITIVE),
    ("中性", SkinTarget.NORMAL),
)
_SKIN_REVISION_CONFIRMATION = re.compile(
    r"(?P<proof>"
    r"(?:肤质\s*)?"
    r"(?:改成|换成|改为)\s*"
    r"(?P<value>"
    + "|".join(
        re.escape(alias)
        for alias, _target in _SKIN_ALIASES
    )
    + r"))"
)
_CATEGORY_QUANTIFIERS = (
    "每一款",
    "每一种",
    "每一类",
    "这一类",
    "那一类",
    "任意",
    "任一",
    "任何",
    "一切",
    "所有",
    "全部",
    "每个",
    "各个",
    "各款",
    "各类",
    "这类",
    "这种",
    "那种",
)
_CATEGORY_PRENOMINAL_ATTRIBUTE_TARGET = re.compile(
    r"^\s*[^，,。.!！?？；;：:\n\r]+\s*的\s*$"
)
_ORDINAL = re.compile(
    r"第\s*(?P<value>[一二两三四五六七八九1-9])\s*"
    r"(?P<unit>款|个|支|瓶|种|张)"
)
_CURRENT_ITEM_REFERENCE = re.compile(
    r"(?P<referent>"
    r"该商品|该产品|这款商品|这款产品|这个商品|这个产品|"
    r"这款|它"
    r")(?!们)"
)
_ORDINAL_VALUES = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_INGREDIENTS = ("酒精", "香精")
_CATEGORY_BOUNDARY_PATTERN = "(?:" + "|".join(
    re.escape(alias)
    for alias, _topic in _CATEGORY_ALIASES
) + ")"
_HARD_ABSENCE_EXCLUSION = re.compile(
    rf"(?:绝对不能有|严禁含有|不能有|不可含|不要含|不要有|不含)"
    rf"\s*(?P<value>[^，,。.!！?？；;：:\n\r]{{1,64}}?)\s*"
    rf"(?=(?:的\s*)?{_CATEGORY_BOUNDARY_PATTERN}|[，,。.!！?？；;：:\n\r]|$)"
)
_BARE_ABSENCE_EXCLUSION = re.compile(
    rf"无\s*(?P<value>[^，,。.!！?？；;：:\n\r]{{0,63}}?"
    rf"(?:酸|醇|酯|油|精|剂|粉|蜡|硅|香|色素))\s*"
    rf"(?=(?:的\s*)?{_CATEGORY_BOUNDARY_PATTERN}|[，,。.!！?？；;：:\n\r]|$)"
)
_EXPLICIT_ALLERGY_EXCLUSION = re.compile(
    r"(?:我)?对\s*(?P<value>[^，,。.!！?？；;：:\n\r]{1,64}?)\s*"
    r"(?:过敏|不耐受)"
)
_HARD_INGREDIENT_INCLUSION = re.compile(
    rf"(?:必须|务必|一定|绝对)(?:要|得)?"
    rf"(?:含有|含|有|添加)\s*"
    rf"(?P<value>[^，,。.!！?？；;：:\n\r]{{1,64}}?)\s*"
    rf"(?=(?:的\s*)?{_CATEGORY_BOUNDARY_PATTERN}|"
    rf"[，,。.!！?？；;：:\n\r]|$)"
)
_EXCLUSION_WITHDRAWAL = re.compile(
    r"^\s*(?P<proof>(?:取消|去掉|撤销)\s*"
    r"(?:之前\s*)?(?:对\s*)?"
    r"(?P<value>[^，,。.!！?？；;：:\n\r]{1,64}?)\s*(?:的\s*)?"
    r"(?:这个)?(?:排除|排除条件))\s*$"
)
_EXCLUSION_NO_LONGER_REQUIRED = re.compile(
    r"^\s*(?P<proof>不再(?:要求)?排除\s*"
    r"(?P<value>[^，,。.!！?？；;：:\n\r]{1,64}))\s*$"
)
_EXCLUSION_TARGET_FIRST_WITHDRAWAL = re.compile(
    r"^\s*(?P<proof>"
    r"(?!(?:把|不用|不必|可以|允许))"
    r"(?P<value>[^，,。.!！?？；;：:\n\r]{1,32}?)\s*"
    r"(?:这条)?(?:排除|限制)\s*"
    r"(?:取消(?:掉)?|去掉|删(?:掉|了)|撤(?:掉|了))"
    r")\s*$"
)
_EXCLUSION_NO_LONGER_AVOIDED = re.compile(
    r"^\s*(?P<proof>"
    r"(?:不用|不必)\s*(?:再)?(?:避开|排除)\s*"
    r"(?P<value>[^，,。.!！?？；;：:\n\r]{1,32}?)\s*(?:了)?"
    r")\s*$"
)
_EXCLUSION_LIMIT_WITHDRAWAL = re.compile(
    r"^\s*(?P<proof>"
    r"把\s*(?:不要|避开|排除)\s*"
    r"(?P<value>[^，,。.!！?？；;：:\n\r]{1,32}?)\s*"
    r"(?:这个|这条)?(?:限制|条件)\s*"
    r"(?:删(?:掉|了)|去掉|取消|撤掉)"
    r")\s*$"
)
_EXCLUSION_ALLOWED = re.compile(
    r"^\s*(?P<proof>"
    r"(?:可以|允许)\s*(?:含|有|添加)?\s*"
    r"(?P<value>[^，,。.!！?？；;：:\n\r]{1,32}?)"
    r"(?:[，,]\s*(?:前面|之前)?(?:那条|这个)?\s*"
    r"(?:限制|条件)?\s*(?:撤掉|删掉|取消|去掉))?"
    r")\s*$"
)
_EXCLUSION_NEGATED = re.compile(
    r"^\s*(?P<proof>"
    r"(?P<value>[^，,。.!！?？；;：:\n\r]{1,32}?)\s*"
    r"不(?:再)?排除(?:了)?"
    r"(?:[，,]\s*继续(?:选|推荐)(?:吧)?)?"
    r")\s*$"
)
_EXCLUSION_DISABLED_WITHDRAWAL = re.compile(
    r"^\s*(?P<proof>把\s*"
    r"(?P<value>酒精|香精)\s*(?:禁用|排除)\s*"
    r"(?:条件|限制)\s*(?:拿掉|删掉|删除|撤掉|取消))\s*$"
)
_EXCLUSION_TARGET_ALLOWED = re.compile(
    r"^\s*(?P<proof>(?P<value>酒精|香精)\s*"
    r"(?:可以|允许)\s*(?:接受|含有|使用)?(?:了)?\s*"
    r"[，,]\s*(?:删掉|删除|撤掉|取消)\s*"
    r"(?:那项|这项|该项)?\s*(?:限制|条件))\s*$"
)
_EXCLUSION_FILTER_WITHDRAWAL = re.compile(
    r"^\s*(?P<proof>别再把\s*(?:含)?"
    r"(?P<value>酒精|香精)\s*(?:的)?\s*筛出去)\s*$"
)
_EXCLUSION_EXPIRED_WITHDRAWAL = re.compile(
    r"^\s*(?P<proof>(?:前面说|之前说)?\s*"
    r"(?:避开|排除)\s*(?P<value>酒精|香精)\s*"
    r"(?:这条)?\s*(?:作废|不算了)"
    r"(?:[，,]\s*继续(?:选|推荐)(?:吧)?)?)\s*$"
)
_EXCLUSION_REQUIREMENT_RELEASED = re.compile(
    r"^\s*(?P<proof>(?:解除|撤回)\s*(?:无)?"
    r"(?P<value>酒精|香精)\s*(?:要求|限制)"
    r"(?:[，,]\s*其余条件照旧)?)\s*$"
)
_EXCLUSION_PREVIOUS_INVALID = re.compile(
    r"^\s*(?P<proof>(?:之前的?)?\s*"
    r"(?P<value>酒精|香精)\s*排除\s*(?:不算了|作废))\s*$"
)
_EXCLUSION_ALLOWED_AND_DELETED = re.compile(
    r"^\s*(?P<proof>(?:允许|可以)\s*含\s*"
    r"(?P<value>酒精|香精)\s*[，,]\s*把\s*"
    r"(?:禁用项|限制|条件)\s*(?:删除|删掉|移除))\s*$"
)
_EXCLUSION_LIST_REMOVAL = re.compile(
    r"^\s*(?P<proof>(?P<value>酒精|香精)\s*"
    r"(?:这一项|这项)?\s*从\s*(?:避开|排除|禁用)"
    r"清单\s*(?:移除|删除|删掉))\s*$"
)
_INCLUSION_WITHDRAWAL = re.compile(
    r"^\s*(?P<proof>(?:取消|去掉|撤销)\s*"
    r"(?:必须|务必|一定)?(?:要|得)?"
    r"(?:含有|含|有|添加)\s*"
    r"(?P<value>[^，,。.!！?？；;：:\n\r]{1,64}))\s*$"
)
_HIGH_RISK_POPULATION_SAFETY = re.compile(
    r"(?:孕妇|孕期|备孕|哺乳期|婴幼儿|儿童)"
    r"[^，,。.!！?？；;：:\n\r]{0,8}"
    r"(?:能用|可用|可以用|适用|能不能用|能否使用)"
)
_ACTIVE_DAMAGE_SAFETY = re.compile(
    r"(?:皮肤|肌肤)?(?:破损|伤口|红肿|灼热|刺痛|过敏反应)"
    r"[^，,。.!！?？；;：:\n\r]{0,8}"
    r"(?:能用|可用|可以用|还能用|适用|能不能用|能否使用)"
)
_SAFETY_OUTCOME_QUERY = re.compile(
    r"(?:安全(?:吗|么|不|如何|的)|"
    r"安全性(?:怎么样|如何|高吗)?|"
    r"是否安全|"
    r"会不会(?:导致|引起)?(?:过敏|刺激)|"
    r"是否(?:会)?(?:过敏|刺激)|"
    r"能否保证安全)"
)
_SOFT_EXCLUSION_CUES = (
    "优先考虑",
    "可以接受",
    "更想要",
    "偏向",
    "倾向",
    "优先",
    "尽量",
    "最好",
    "想要",
    "希望",
)
_HARD_SAFETY_CUES = ("过敏", "不耐受", "绝对", "必须", "务必")
_CLAUSE_BOUNDARY_LEXEMES = (
    "但是",
    "不过",
    "可是",
    "然而",
    "然后",
    "但",
    "却",
    "而",
    "\n",
    "\r",
)
_REVISION_LEXEMES = (
    "后来",
    "最后",
    "最终",
    "转而",
    "转头",
    "相反",
    "而是",
)
_MODAL_LEXEMES = (
    "也可能",
    "可能",
    "也许",
    "或许",
    "大概",
)


@dataclass(frozen=True)
class _CategoryTargetMatch:
    topic: TopicCode
    value: str
    start: int
    end: int


@dataclass(frozen=True)
class _OrdinalReferenceValue:
    kind: str
    ordinal: int


class _TokenKind(str, Enum):
    CLAUSE_BOUNDARY = "clause_boundary"
    CATEGORY = "category"
    CATEGORY_QUANTIFIER = "category_quantifier"
    INGREDIENT = "ingredient"
    ORDINAL = "ordinal"
    SELECTION_ACTION = "selection_action"
    REVISION = "revision"
    MODAL = "modal"
    NEGATION_OPERATOR = "negation_operator"
    HEDGE = "hedge"
    REPORTING_MODAL = "reporting_modal"
    POSITIVE_MODAL = "positive_modal"


class _SelectionAction(str, Enum):
    BUY = "buy"
    SELECT = "select"
    CONSIDER = "consider"
    NEED = "need"
    RECOMMEND = "recommend"
    VIEW = "view"
    AVOID = "avoid"


class _SelectionOperator(str, Enum):
    AFFIRMATIVE = "affirmative"
    NEGATED = "negated"
    HEDGED = "hedged"
    WRAPPED = "wrapped"
    NESTED = "nested"
    MODAL = "modal"


class _SelectionPolarity(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"


class _SelectionStrength(str, Enum):
    EXPLICIT = "explicit"
    HEDGED = "hedged"
    WRAPPED = "wrapped"


@dataclass(frozen=True)
class _ExactToken:
    kind: _TokenKind
    value: object
    source_span: SourceSpan
    is_revision: bool = False


@dataclass(frozen=True)
class _Lexeme:
    text: str
    kind: _TokenKind
    value: object
    is_revision: bool = False


@dataclass(frozen=True)
class _Clause:
    source_span: SourceSpan
    tokens: tuple[_ExactToken, ...]


@dataclass(frozen=True)
class _SelectionEvent:
    operator: _SelectionOperator
    polarity: _SelectionPolarity
    strength: _SelectionStrength
    action: _SelectionAction
    operator_stack: tuple[_ExactToken, ...]
    action_span: SourceSpan
    target_span: SourceSpan
    target_category_span: SourceSpan
    consumed_span: SourceSpan
    clause_span: SourceSpan
    target_topic: TopicCode
    attribute_span: SourceSpan | None
    inherited_target: bool
    is_revision: bool


@dataclass(frozen=True)
class _RevisionTargetIssue:
    code: str
    action_span: SourceSpan
    target_topics: tuple[TopicCode, ...]


@dataclass(frozen=True)
class _CategorySelectionAnalysis:
    states: dict[TopicCode, _SelectionPolarity]
    hard_exclusions: frozenset[TopicCode]
    attribute_targets: tuple[_CategoryTargetMatch, ...]
    events: tuple[_SelectionEvent, ...]
    revision_target_issues: tuple[_RevisionTargetIssue, ...]
    owned_spans: tuple[SourceSpan, ...]


@dataclass
class _SpanOwnership:
    spans: list[SourceSpan]

    def claim(self, span: SourceSpan) -> None:
        if not self.overlaps(span):
            self.spans.append(span)

    def overlaps(self, span: SourceSpan) -> bool:
        return any(
            span.start < owned.end and owned.start < span.end
            for owned in self.spans
        )


_ACTION_LEXEMES = (
    ("准备买", _SelectionAction.BUY),
    ("想购买", _SelectionAction.BUY),
    ("想入手", _SelectionAction.BUY),
    ("要购买", _SelectionAction.BUY),
    ("想挑选", _SelectionAction.SELECT),
    ("要买", _SelectionAction.BUY),
    ("想买", _SelectionAction.BUY),
    ("想要", _SelectionAction.NEED),
    ("改买", _SelectionAction.BUY),
    ("改选", _SelectionAction.SELECT),
    ("改要", _SelectionAction.NEED),
    ("转选", _SelectionAction.SELECT),
    ("想看", _SelectionAction.VIEW),
    ("看看", _SelectionAction.VIEW),
    ("换成", _SelectionAction.SELECT),
    ("购买", _SelectionAction.BUY),
    ("入手", _SelectionAction.BUY),
    ("选择", _SelectionAction.SELECT),
    ("挑选", _SelectionAction.SELECT),
    ("考虑", _SelectionAction.CONSIDER),
    ("需要", _SelectionAction.NEED),
    ("推荐", _SelectionAction.RECOMMEND),
    ("避开", _SelectionAction.AVOID),
    ("避雷", _SelectionAction.AVOID),
    ("排除", _SelectionAction.AVOID),
    ("拒绝", _SelectionAction.AVOID),
    ("买", _SelectionAction.BUY),
    ("要", _SelectionAction.NEED),
    ("想", _SelectionAction.NEED),
    ("用", _SelectionAction.NEED),
    ("需", _SelectionAction.NEED),
    ("别", _SelectionAction.AVOID),
)
_REVISION_ACTION_LEXEMES = frozenset(
    {"改买", "改选", "改要", "转选", "换成"}
)
_HEDGE_LEXEMES = (
    "没有特别",
    "并非真的",
    "并非真心",
    "没那么",
    "没怎么",
    "没多么",
    "没真正",
    "不是很",
    "不一定",
    "不怎么",
    "不见得",
    "谈不上",
    "称不上",
    "不太",
    "不大",
    "未必",
    "未曾",
    "没有",
)
_REPORTING_MODAL_LEXEMES = ("没有说", "不能说", "没说")
_POSITIVE_MODAL_LEXEMES = (
    "无论如何都",
    "毫无疑问",
    "忍不住",
    "不由得",
    "不禁",
    "无比",
)
_NEGATION_OPERATOR_LEXEMES = (
    "无意",
    "无需",
    "并非",
    "不是",
    "不能",
    "不",
    "没",
    "未",
    "无",
)
_CLEANSING_OBJECT_PREFIX = re.compile(
    r"(?:卸除|卸|清洁|洗掉|洗净)[^，,。.!！?？；;：:\n\r]{0,8}$"
)


def _build_lexemes() -> tuple[_Lexeme, ...]:
    lexemes = [
        *(
            _Lexeme(value, _TokenKind.CLAUSE_BOUNDARY, value)
            for value in _CLAUSE_BOUNDARY_LEXEMES
        ),
        *(
            _Lexeme(value, _TokenKind.REVISION, value)
            for value in _REVISION_LEXEMES
        ),
        *(
            _Lexeme(value, _TokenKind.MODAL, value)
            for value in _MODAL_LEXEMES
        ),
        *(
            _Lexeme(value, _TokenKind.POSITIVE_MODAL, value)
            for value in _POSITIVE_MODAL_LEXEMES
        ),
        *(
            _Lexeme(value, _TokenKind.REPORTING_MODAL, value)
            for value in _REPORTING_MODAL_LEXEMES
        ),
        *(
            _Lexeme(value, _TokenKind.HEDGE, value)
            for value in _HEDGE_LEXEMES
        ),
        *(
            _Lexeme(value, _TokenKind.NEGATION_OPERATOR, value)
            for value in _NEGATION_OPERATOR_LEXEMES
        ),
        *(
            _Lexeme(
                value,
                _TokenKind.SELECTION_ACTION,
                action,
                is_revision=value in _REVISION_ACTION_LEXEMES,
            )
            for value, action in _ACTION_LEXEMES
        ),
        *(
            _Lexeme(alias, _TokenKind.CATEGORY, topic)
            for alias, topic in _CATEGORY_ALIASES
        ),
        *(
            _Lexeme(
                value,
                _TokenKind.CATEGORY_QUANTIFIER,
                value,
            )
            for value in _CATEGORY_QUANTIFIERS
        ),
        *(
            _Lexeme(value, _TokenKind.INGREDIENT, value)
            for value in _INGREDIENTS
        ),
    ]
    return tuple(
        sorted(
            lexemes,
            key=lambda item: (
                -len(item.text),
                item.kind.value,
                item.text,
            ),
        )
    )


_LEXEMES = _build_lexemes()


def _lex_exact_tokens(text: str) -> tuple[_ExactToken, ...]:
    tokens: list[_ExactToken] = []
    index = 0
    while index < len(text):
        punctuation_end = _punctuation_run_end(text, start=index)
        if punctuation_end is not None:
            tokens.append(
                _ExactToken(
                    kind=_TokenKind.CLAUSE_BOUNDARY,
                    value=text[index:punctuation_end],
                    source_span=SourceSpan(
                        start=index,
                        end=punctuation_end,
                    ),
                )
            )
            index = punctuation_end
            continue
        ordinal = _ORDINAL.match(text, index)
        candidates = [
            lexeme
            for lexeme in _LEXEMES
            if text.startswith(lexeme.text, index)
            and _lexeme_is_valid(text, index=index, lexeme=lexeme)
        ]
        lexeme = candidates[0] if candidates else None
        if ordinal is not None and (
            lexeme is None
            or ordinal.end() - ordinal.start() > len(lexeme.text)
        ):
            raw_value = ordinal.group("value")
            value = (
                int(raw_value)
                if raw_value.isdigit()
                else _ORDINAL_VALUES[raw_value]
            )
            tokens.append(
                _ExactToken(
                    kind=_TokenKind.ORDINAL,
                    value=_OrdinalReferenceValue(
                        kind=(
                            "image_ordinal"
                            if ordinal.group("unit") == "张"
                            else "candidate_ordinal"
                        ),
                        ordinal=value,
                    ),
                    source_span=SourceSpan(
                        start=ordinal.start(),
                        end=ordinal.end(),
                    ),
                )
            )
            index = ordinal.end()
            continue
        if lexeme is None:
            index += 1
            continue
        end = index + len(lexeme.text)
        tokens.append(
            _ExactToken(
                kind=lexeme.kind,
                value=_lexeme_value_in_context(
                    text,
                    index=index,
                    lexeme=lexeme,
                ),
                source_span=SourceSpan(start=index, end=end),
                is_revision=lexeme.is_revision,
            )
        )
        index = end
    return tuple(tokens)


def _lexeme_value_in_context(
    text: str,
    *,
    index: int,
    lexeme: _Lexeme,
) -> object:
    if (
        lexeme.kind is _TokenKind.CATEGORY
        and lexeme.value is TopicCode.COLOR_MAKEUP
        and _CLEANSING_OBJECT_PREFIX.search(text[:index])
    ):
        return TopicCode.CLEANSER
    return lexeme.value


def _punctuation_run_end(text: str, *, start: int) -> int | None:
    if (
        not unicodedata.category(text[start]).startswith("P")
        or _is_numeric_punctuation(text, index=start)
    ):
        return None
    end = start + 1
    while (
        end < len(text)
        and unicodedata.category(text[end]).startswith("P")
        and not _is_numeric_punctuation(text, index=end)
    ):
        end += 1
    return end


def _is_numeric_punctuation(text: str, *, index: int) -> bool:
    normalized = unicodedata.normalize("NFKC", text[index])
    if normalized not in {
        ".",
        ",",
        "-",
        "−",
        "/",
        ":",
        "'",
        "’",
        "٬",
    }:
        return False
    left = index - 1
    while left >= 0 and text[left].isspace():
        left -= 1
    right = index + 1
    while right < len(text) and text[right].isspace():
        right += 1
    return (
        left >= 0
        and right < len(text)
        and text[left].isdigit()
        and text[right].isdigit()
    )


def _lexeme_is_valid(
    text: str,
    *,
    index: int,
    lexeme: _Lexeme,
) -> bool:
    end = index + len(lexeme.text)
    if (
        lexeme.kind is _TokenKind.NEGATION_OPERATOR
        and lexeme.text == "并非"
        and text.startswith("并非常", index)
    ):
        return False
    if (
        lexeme.kind is _TokenKind.SELECTION_ACTION
        and lexeme.text == "别"
        and index > 0
        and text[index - 1] in "区分性类个"
    ):
        return False
    if (
        lexeme.kind is _TokenKind.SELECTION_ACTION
        and lexeme.text == "想"
        and any(
            text.startswith(action_text, end)
            for action_text, _ in _ACTION_LEXEMES
            if action_text != "想"
        )
    ):
        return False
    if (
        lexeme.kind is _TokenKind.SELECTION_ACTION
        and lexeme.text == "要"
        and index > 0
        and text[index - 1] == "不"
        and any(
            text.startswith(f"{prefix}{ingredient}", end)
            for prefix in ("", "含", "有")
            for ingredient in _INGREDIENTS
        )
    ):
        return False
    if lexeme.kind is not _TokenKind.CATEGORY:
        return True
    unsupported_suffixes = _UNSUPPORTED_CATEGORY_SUFFIXES.get(
        lexeme.text,
        (),
    )
    unsupported_prefixes = _UNSUPPORTED_CATEGORY_PREFIXES.get(
        lexeme.text,
        (),
    )
    return not any(
        text.startswith(suffix, end)
        for suffix in unsupported_suffixes
    ) and not any(
        text[:index].endswith(prefix)
        for prefix in unsupported_prefixes
    )


def _split_clauses(
    text: str,
    tokens: tuple[_ExactToken, ...],
) -> tuple[_Clause, ...]:
    clauses: list[_Clause] = []
    clause_start = 0
    clause_tokens: list[_ExactToken] = []
    for index, token in enumerate(tokens):
        if token.kind is not _TokenKind.CLAUSE_BOUNDARY:
            clause_tokens.append(token)
            continue
        if _continues_category_list(
            tokens,
            boundary_index=index,
            clause_tokens=clause_tokens,
        ):
            continue
        if token.source_span.start > clause_start or clause_tokens:
            clauses.append(
                _Clause(
                    source_span=SourceSpan(
                        start=clause_start,
                        end=token.source_span.start,
                    ),
                    tokens=tuple(clause_tokens),
                )
            )
        clause_start = token.source_span.end
        clause_tokens = []
    if clause_start < len(text) or clause_tokens:
        clauses.append(
            _Clause(
                source_span=SourceSpan(
                    start=clause_start,
                    end=len(text),
                ),
                tokens=tuple(clause_tokens),
            )
        )
    return tuple(clauses)


def _continues_category_list(
    tokens: tuple[_ExactToken, ...],
    *,
    boundary_index: int,
    clause_tokens: list[_ExactToken],
) -> bool:
    boundary = tokens[boundary_index]
    raw_boundary = str(boundary.value)
    if (
        not raw_boundary
        or any(
            value not in _CATEGORY_LIST_PUNCTUATION
            for value in raw_boundary
        )
    ):
        return False
    if not any(
        token.kind is _TokenKind.CATEGORY
        for token in clause_tokens
    ):
        return False
    following_tokens: list[_ExactToken] = []
    for token in tokens[boundary_index + 1:]:
        if token.kind is _TokenKind.CLAUSE_BOUNDARY:
            break
        following_tokens.append(token)
    if not any(
        token.kind is _TokenKind.CATEGORY
        for token in following_tokens
    ):
        return False
    return not any(
        token.kind
        in {
            _TokenKind.SELECTION_ACTION,
            _TokenKind.REVISION,
            _TokenKind.MODAL,
            _TokenKind.NEGATION_OPERATOR,
            _TokenKind.HEDGE,
            _TokenKind.REPORTING_MODAL,
            _TokenKind.POSITIVE_MODAL,
        }
        for token in following_tokens
    )


def parse_exact_constraints(
    text: str,
) -> tuple[list[ExactConstraintDraft], list[UnderstandingIssue]]:
    constraints: list[ExactConstraintDraft] = []
    issues: list[UnderstandingIssue] = []
    tokens = _lex_exact_tokens(text)
    ownership = _SpanOwnership(spans=[])

    budget, budget_issue = _parse_budget(
        text,
        ownership=ownership,
    )
    if budget is not None:
        constraints.append(budget)
    if budget_issue is not None:
        issues.append(budget_issue)

    current_item = _parse_current_item_reference(
        text,
        ownership=ownership,
    )
    if current_item is not None:
        constraints.append(current_item)

    references, reference_issues = _parse_ordinal_references(
        tokens,
        ownership=ownership,
    )
    constraints.extend(references)
    issues.extend(reference_issues)

    analysis = _analyze_category_selection(text, tokens=tokens)
    for span in analysis.owned_spans:
        ownership.claim(span)
    issues.extend(
        UnderstandingIssue(
            code=issue.code,
            detail=(
                "改选动作缺少明确的新目标，请补充一个目标品类。"
                if issue.code == "missing_revision_target"
                else "改选动作包含多个新目标，请只确认一个目标品类。"
            ),
        )
        for issue in analysis.revision_target_issues
    )
    category, category_issue = _parse_category_analysis(analysis)
    if category is not None:
        constraints.append(CategoryDraft(value=category))
    if category_issue is not None:
        issues.append(category_issue)
    category_targets = list(analysis.attribute_targets)
    attribute_issue = _parse_attribute_exclusion_issue(
        category_targets,
        category,
    )
    if attribute_issue is not None:
        issues.append(attribute_issue)

    skin = _parse_skin(text)
    if skin is not None:
        constraints.append(SkinDraft(value=skin))

    efficacy = _parse_efficacy(text)
    if efficacy is not None:
        constraints.append(EfficacyDraft(value=efficacy))

    constraints.extend(
        InclusionDraft(value=value)
        for value in _parse_hard_ingredient_inclusions(
            text,
            ownership=ownership,
        )
    )
    exclusion_values = _parse_exclusions(
        text,
        tokens=tokens,
        ownership=ownership,
        selection_events=analysis.events,
    )
    exclusion_values.extend(
        _parse_generic_hard_exclusions(
            text,
            ownership=ownership,
        )
    )
    constraints.extend(
        ExclusionDraft(value=value)
        for value in dict.fromkeys(exclusion_values)
    )
    safety_issue = _parse_unverified_safety_requirement(text)
    if safety_issue is not None:
        issues.append(safety_issue)
    return constraints, issues


def parse_exact_revision_confirmations(
    text: str,
) -> list[ExactRevisionConfirmation]:
    """Project typed revision evidence from exact selection events."""
    tokens = _lex_exact_tokens(text)
    confirmations: list[ExactRevisionConfirmation] = []
    seen: set[
        tuple[
            ExactRevisionOperation,
            ExactRevisionTarget,
            int,
            int,
        ]
    ] = set()
    for event in _selection_events_from_tokens(text, tokens):
        if not event.is_revision:
            continue
        if event.polarity is _SelectionPolarity.POSITIVE:
            operation = ExactRevisionOperation.REVISE_CONSTRAINT
        elif event.polarity is _SelectionPolarity.NEGATIVE:
            operation = ExactRevisionOperation.WITHDRAW_CONSTRAINT
        else:
            continue
        proof_span = _revision_confirmation_span(
            text=text,
            event=event,
            tokens=tokens,
        )
        key = (
            operation,
            ExactRevisionTarget.CATEGORY,
            proof_span.start,
            proof_span.end,
        )
        if key in seen:
            continue
        seen.add(key)
        confirmations.append(
            ExactRevisionConfirmation(
                operation=operation,
                target=ExactRevisionTarget.CATEGORY,
                source_span=proof_span,
                affected_value=event.target_topic.value,
            )
        )
    for proof_span in _budget_revision_confirmation_spans(text):
        key = (
            ExactRevisionOperation.REVISE_CONSTRAINT,
            ExactRevisionTarget.BUDGET,
            proof_span.start,
            proof_span.end,
        )
        if key in seen:
            continue
        seen.add(key)
        confirmations.append(
            ExactRevisionConfirmation(
                operation=ExactRevisionOperation.REVISE_CONSTRAINT,
                target=ExactRevisionTarget.BUDGET,
                source_span=proof_span,
            )
        )
    skin_match = _SKIN_REVISION_CONFIRMATION.search(text)
    if skin_match is not None:
        alias = skin_match.group("value")
        confirmations.append(
            ExactRevisionConfirmation(
                operation=ExactRevisionOperation.REVISE_CONSTRAINT,
                target=ExactRevisionTarget.SKIN,
                source_span=SourceSpan(
                    start=skin_match.start("proof"),
                    end=skin_match.end("proof"),
                ),
                affected_value=_skin_target_for_alias(alias).value,
            )
        )
    efficacy_revision = _efficacy_revision_confirmation(text)
    if efficacy_revision is not None:
        confirmations.append(efficacy_revision)
    else:
        efficacy_withdrawal = _efficacy_withdrawal_confirmation(text)
        if efficacy_withdrawal is not None:
            confirmations.append(efficacy_withdrawal)
    for pattern, target in (
        (
            _EXCLUSION_WITHDRAWAL,
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
        ),
        (
            _EXCLUSION_NO_LONGER_REQUIRED,
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
        ),
        (
            _EXCLUSION_TARGET_FIRST_WITHDRAWAL,
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
        ),
        (
            _EXCLUSION_NO_LONGER_AVOIDED,
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
        ),
        (
            _EXCLUSION_LIMIT_WITHDRAWAL,
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
        ),
        (
            _EXCLUSION_ALLOWED,
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
        ),
        (
            _EXCLUSION_NEGATED,
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
        ),
        (
            _EXCLUSION_DISABLED_WITHDRAWAL,
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
        ),
        (
            _EXCLUSION_TARGET_ALLOWED,
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
        ),
        (
            _EXCLUSION_FILTER_WITHDRAWAL,
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
        ),
        (
            _EXCLUSION_EXPIRED_WITHDRAWAL,
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
        ),
        (
            _EXCLUSION_REQUIREMENT_RELEASED,
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
        ),
        (
            _EXCLUSION_PREVIOUS_INVALID,
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
        ),
        (
            _EXCLUSION_ALLOWED_AND_DELETED,
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
        ),
        (
            _EXCLUSION_LIST_REMOVAL,
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
        ),
        (
            _INCLUSION_WITHDRAWAL,
            ExactRevisionTarget.INGREDIENT_INCLUSION,
        ),
    ):
        match = pattern.fullmatch(text)
        if match is None:
            continue
        confirmations.append(
            ExactRevisionConfirmation(
                operation=ExactRevisionOperation.WITHDRAW_CONSTRAINT,
                target=target,
                source_span=SourceSpan(
                    start=match.start("proof"),
                    end=match.end("proof"),
                ),
                affected_value="".join(
                    match.group("value").split()
                ),
            )
        )
    return confirmations


def _efficacy_revision_confirmation(
    text: str,
) -> ExactRevisionConfirmation | None:
    cue = _EFFICACY_REVISION_CUE.search(text)
    if cue is None or _nonassertive_revision_prefix(
        text,
        start=cue.start(),
    ):
        return None
    clause_end = next(
        (
            index
            for index in range(cue.end(), len(text))
            if text[index] in "，,。.!！?？；;：:\n\r"
        ),
        len(text),
    )
    for alias, target in _EFFICACY_ALIASES:
        value_start = text.find(alias, cue.end(), clause_end)
        if value_start < 0:
            continue
        return ExactRevisionConfirmation(
            operation=ExactRevisionOperation.REVISE_CONSTRAINT,
            target=ExactRevisionTarget.EFFICACY,
            source_span=SourceSpan(
                start=cue.start(),
                end=value_start + len(alias),
            ),
            affected_value=target.value,
        )
    return None


def _efficacy_withdrawal_confirmation(
    text: str,
) -> ExactRevisionConfirmation | None:
    for pattern in (
        _EFFICACY_TARGET_FIRST_WITHDRAWAL,
        _EFFICACY_ACTION_FIRST_WITHDRAWAL,
    ):
        for match in pattern.finditer(text):
            if _nonassertive_revision_prefix(
                text,
                start=match.start("proof"),
            ):
                continue
            alias = match.group("value")
            target = next(
                target
                for candidate, target in _EFFICACY_ALIASES
                if candidate == alias
            )
            return ExactRevisionConfirmation(
                operation=(
                    ExactRevisionOperation.WITHDRAW_CONSTRAINT
                ),
                target=ExactRevisionTarget.EFFICACY,
                source_span=SourceSpan(
                    start=match.start("proof"),
                    end=match.end("proof"),
                ),
                affected_value=target.value,
            )
    return None


def parse_exact_efficacy_withdrawals(
    text: str,
) -> tuple[EfficacyTarget, ...]:
    confirmation = _efficacy_withdrawal_confirmation(text)
    if confirmation is None or confirmation.affected_value is None:
        return ()
    return (EfficacyTarget(confirmation.affected_value),)


def _nonassertive_revision_prefix(
    text: str,
    *,
    start: int,
) -> bool:
    clause_start = max(
        (
            text.rfind(separator, 0, start)
            for separator in "，,。.!！?？；;：:\n\r"
        ),
        default=-1,
    ) + 1
    prefix = text[clause_start:start]
    return any(
        marker in prefix
        for marker in _NONASSERTIVE_REVISION_MARKERS
    )


def _budget_revision_confirmation_spans(
    text: str,
) -> list[SourceSpan]:
    spans: list[SourceSpan] = []
    for cue in _BUDGET_REVISION_CUE.finditer(text):
        value_start = cue.end()
        while (
            value_start < len(text)
            and text[value_start].isspace()
        ):
            value_start += 1
        tail = text[value_start:]
        colloquial = parse_colloquial_budget(tail)
        if (
            colloquial is not None
            and colloquial.start == 0
            and colloquial.clarification is None
        ):
            spans.append(
                SourceSpan(
                    start=cue.start(),
                    end=value_start + colloquial.end,
                )
            )
            continue
        numeric = next(
            (
                match
                for pattern in (
                    _RANGE,
                    _MAXIMUM,
                    _BARE_CURRENCY,
                )
                if (match := pattern.match(tail)) is not None
            ),
            None,
        )
        if numeric is not None:
            spans.append(
                SourceSpan(
                    start=cue.start(),
                    end=value_start + numeric.end(),
                )
            )
    return spans


def _revision_confirmation_span(
    *,
    text: str,
    event: _SelectionEvent,
    tokens: tuple[_ExactToken, ...],
) -> SourceSpan:
    proof_span = event.consumed_span
    markers = [
        token
        for token in tokens
        if (
            token.kind is _TokenKind.REVISION
            and event.clause_span.start <= token.source_span.start
            and token.source_span.end <= event.action_span.start
        )
    ]
    if not markers:
        return proof_span
    marker = max(markers, key=lambda token: token.source_span.end)
    gap = text[marker.source_span.end:proof_span.start]
    if any(
        not character.isspace()
        and not unicodedata.category(character).startswith("P")
        for character in gap
    ):
        return proof_span
    return SourceSpan(
        start=min(marker.source_span.start, proof_span.start),
        end=proof_span.end,
    )


def exact_revision_confirmation_matches_message(
    *,
    text: str,
    confirmation: ExactRevisionConfirmation,
) -> bool:
    """Return whether exact parsing reproduces this proof for this message."""
    if not isinstance(text, str) or not isinstance(
        confirmation,
        ExactRevisionConfirmation,
    ):
        return False
    span = confirmation.source_span
    if span.start >= len(text) or span.end > len(text):
        return False
    if not text[span.start:span.end].strip():
        return False
    return confirmation in parse_exact_revision_confirmations(text)


def parse_hard_category_exclusions(
    text: str,
) -> tuple[TopicCode, ...]:
    """Return final explicit category exclusions without inferring a topic."""
    analysis = _analyze_category_selection(text)
    return tuple(
        topic
        for topic in analysis.states
        if topic in analysis.hard_exclusions
    )


def _parse_budget(
    text: str,
    *,
    ownership: _SpanOwnership | None = None,
) -> tuple[BudgetDraft | None, UnderstandingIssue | None]:
    match = _SIGNED_BUDGET_PREFIX.search(text)
    if match is not None:
        _claim_match(match, ownership)
        return None, UnderstandingIssue(
            code="invalid_budget",
            detail="预算必须大于 0",
        )

    match = _RANGE.search(text)
    if match:
        if _numeric_expression_is_incomplete(
            text,
            start=match.start("minimum"),
            end=match.end("maximum"),
        ):
            _claim_match(match, ownership)
            return None, UnderstandingIssue(
                code="invalid_budget",
                detail="预算数字格式无效",
            )
        sign_start = _unary_sign_before(
            text,
            number_start=match.start("minimum"),
        )
        if sign_start is not None:
            if ownership is not None:
                ownership.claim(
                    SourceSpan(start=sign_start, end=match.end())
                )
            return None, UnderstandingIssue(
                code="invalid_budget",
                detail="预算必须大于 0",
            )
        _claim_match(match, ownership)
        return _validated_budget(
            minimum=match.group("minimum"),
            maximum=match.group("maximum"),
        )
    match = next(
        (
            candidate
            for candidate in _NEGATIVE_BUDGET.finditer(text)
            if _is_unary_numeric_sign(
                text,
                sign_start=candidate.start("sign"),
            )
        ),
        None,
    )
    if match is not None:
        _claim_match(match, ownership)
        return None, UnderstandingIssue(
            code="invalid_budget",
            detail="预算必须大于 0",
        )
    colloquial = parse_colloquial_budget(text)
    if colloquial is not None:
        if ownership is not None:
            ownership.claim(
                SourceSpan(
                    start=colloquial.start,
                    end=colloquial.end,
                )
            )
        if colloquial.clarification is not None:
            return None, UnderstandingIssue(
                code="unsupported_budget_format",
                detail=colloquial.clarification,
            )
        if (
            colloquial.minimum is not None
            and colloquial.maximum is not None
            and colloquial.minimum > colloquial.maximum
        ):
            return None, UnderstandingIssue(
                code="invalid_budget",
                detail="预算下限不能高于上限",
            )
        if any(
            value is not None and value <= 0
            for value in (
                colloquial.minimum,
                colloquial.maximum,
            )
        ):
            return None, UnderstandingIssue(
                code="invalid_budget",
                detail="预算必须大于 0",
            )
        return (
            BudgetDraft(
                minimum=colloquial.minimum,
                maximum=colloquial.maximum,
            ),
            None,
        )

    for pattern, minimum_key, maximum_key in (
        (_MAXIMUM, None, "maximum"),
        (_MINIMUM, "minimum", None),
        (_BUDGET_PREFIX, None, "maximum"),
        (_BARE_CURRENCY, None, "maximum"),
    ):
        match = pattern.search(text)
        if not match:
            continue
        _claim_match(match, ownership)
        value_key = minimum_key or maximum_key
        if (
            value_key is not None
            and _numeric_expression_is_incomplete(
                text,
                start=match.start(value_key),
                end=match.end(value_key),
            )
        ):
            return None, UnderstandingIssue(
                code="invalid_budget",
                detail="预算数字格式无效",
            )
        return _validated_budget(
            minimum=match.group(minimum_key) if minimum_key else None,
            maximum=match.group(maximum_key) if maximum_key else None,
        )
    return None, None


def _numeric_expression_is_incomplete(
    text: str,
    *,
    start: int,
    end: int,
) -> bool:
    if (
        start >= 2
        and _is_numeric_token_connector(text[start - 1])
        and text[start - 2].isdigit()
    ):
        return True
    if end >= len(text) or not _is_numeric_token_connector(text[end]):
        return False

    next_index = end + 1
    while next_index < len(text) and text[next_index].isspace():
        next_index += 1
    if next_index >= len(text):
        return False
    if text[next_index].isdigit():
        return True
    if text[end].isspace():
        return False
    return text[next_index] in {
        "元",
        "块",
        "到",
        "至",
        "~",
        "～",
        "-",
        "−",
        "－",
        "以",
        "内",
        "起",
    }


def _is_numeric_token_connector(character: str) -> bool:
    return (
        character.isspace()
        or unicodedata.category(character).startswith("P")
        or character in {"+", "＋", "−", "~", "～"}
    )


def _unary_sign_before(
    text: str,
    *,
    number_start: int,
) -> int | None:
    index = number_start - 1
    while index >= 0 and text[index].isspace():
        index -= 1
    if (
        index < 0
        or not re.fullmatch(_NUMERIC_SIGN, text[index])
        or not _is_unary_numeric_sign(text, sign_start=index)
    ):
        return None
    return index


def _is_unary_numeric_sign(
    text: str,
    *,
    sign_start: int,
) -> bool:
    index = sign_start - 1
    while index >= 0 and text[index].isspace():
        index -= 1
    if index < 0:
        return True
    if text[index].isdigit():
        return False
    if text[index] not in {"元", "块"}:
        return True
    index -= 1
    while index >= 0 and text[index].isspace():
        index -= 1
    return index < 0 or not text[index].isdigit()


def _claim_match(
    match: re.Match[str],
    ownership: _SpanOwnership | None,
) -> None:
    if ownership is not None:
        ownership.claim(
            SourceSpan(start=match.start(), end=match.end())
        )


def _parse_ordinal_references(
    tokens: tuple[_ExactToken, ...],
    *,
    ownership: _SpanOwnership,
) -> tuple[list[ReferenceDraft], list[UnderstandingIssue]]:
    tokens_by_kind: dict[str, list[_ExactToken]] = {}
    for token in tokens:
        if (
            token.kind is not _TokenKind.ORDINAL
            or ownership.overlaps(token.source_span)
            or not isinstance(token.value, _OrdinalReferenceValue)
        ):
            continue
        tokens_by_kind.setdefault(token.value.kind, []).append(token)
        ownership.claim(token.source_span)

    references: list[ReferenceDraft] = []
    issues: list[UnderstandingIssue] = []
    for kind, kind_tokens in tokens_by_kind.items():
        unique_tokens: dict[int, _ExactToken] = {}
        for token in kind_tokens:
            if isinstance(token.value, _OrdinalReferenceValue):
                unique_tokens.setdefault(token.value.ordinal, token)
        if len(unique_tokens) > 3:
            issues.append(
                UnderstandingIssue(
                    code=(
                        "too_many_image_references"
                        if kind == "image_ordinal"
                        else "too_many_candidate_references"
                    ),
                    detail=(
                        f"检测到超过三个 {kind} 序号，"
                        "一次最多处理三个。"
                    ),
                )
            )
            continue
        references.extend(
            ReferenceDraft(
                kind=kind,
                ordinal=ordinal,
                source_span=token.source_span,
            )
            for ordinal, token in unique_tokens.items()
        )
    return references, issues


def _parse_current_item_reference(
    text: str,
    *,
    ownership: _SpanOwnership,
) -> ReferenceDraft | None:
    match = _CURRENT_ITEM_REFERENCE.search(text)
    if match is None:
        return None
    span = SourceSpan(
        start=match.start("referent"),
        end=match.end("referent"),
    )
    if ownership.overlaps(span):
        return None
    ownership.claim(span)
    return ReferenceDraft(
        kind="current_item",
        source_span=span,
    )


def _validated_budget(
    *,
    minimum: str | None,
    maximum: str | None,
) -> tuple[BudgetDraft | None, UnderstandingIssue | None]:
    try:
        minimum_value = (
            _parse_budget_decimal(minimum)
            if minimum is not None
            else None
        )
        maximum_value = (
            _parse_budget_decimal(maximum)
            if maximum is not None
            else None
        )
    except (InvalidOperation, ValueError):
        return None, UnderstandingIssue(
            code="invalid_budget",
            detail="预算数字格式无效",
        )

    values = [
        value
        for value in (minimum_value, maximum_value)
        if value is not None
    ]
    if any(not value.is_finite() or value <= 0 for value in values):
        return None, UnderstandingIssue(
            code="invalid_budget",
            detail="预算必须是大于 0 的有限数字",
        )
    if (
        minimum_value is not None
        and maximum_value is not None
        and minimum_value > maximum_value
    ):
        return None, UnderstandingIssue(
            code="invalid_budget",
            detail="预算下限不能高于上限",
        )
    return (
        BudgetDraft(
            minimum=minimum_value,
            maximum=maximum_value,
        ),
        None,
    )


def _parse_budget_decimal(raw_value: str) -> Decimal:
    value = raw_value.strip()
    decimal_positions = [
        index
        for index, character in enumerate(value)
        if character in _BUDGET_DECIMAL_SEPARATORS
    ]
    if len(decimal_positions) > 1:
        raise ValueError("multiple decimal separators")

    if decimal_positions:
        decimal_index = decimal_positions[0]
        integer_part = value[:decimal_index]
        fractional_part = value[decimal_index + 1:]
        if not _is_budget_digits(fractional_part):
            raise ValueError("invalid decimal fraction")
    else:
        integer_part = value
        fractional_part = None

    separators = [
        character
        for character in integer_part
        if character in _BUDGET_GROUP_SEPARATORS
    ]
    if separators:
        if len(set(separators)) != 1:
            raise ValueError("mixed grouping separators")
        separator = separators[0]
        groups = integer_part.split(separator)
        if (
            not 1 <= len(groups[0]) <= 3
            or not _is_budget_digits(groups[0])
            or any(
                len(group) != 3 or not _is_budget_digits(group)
                for group in groups[1:]
            )
        ):
            raise ValueError("invalid digit grouping")
        normalized_integer = "".join(
            unicodedata.normalize("NFKC", group)
            for group in groups
        )
    else:
        if not _is_budget_digits(integer_part):
            raise ValueError("invalid integer")
        normalized_integer = unicodedata.normalize(
            "NFKC",
            integer_part,
        )

    normalized_fraction = (
        unicodedata.normalize("NFKC", fractional_part)
        if fractional_part is not None
        else None
    )
    normalized = (
        f"{normalized_integer}.{normalized_fraction}"
        if normalized_fraction is not None
        else normalized_integer
    )
    return Decimal(normalized)


def _is_budget_digits(value: str) -> bool:
    return bool(value) and all(
        character in "0123456789０１２３４５６７８９"
        for character in value
    )


def _parse_category_analysis(
    analysis: _CategorySelectionAnalysis,
) -> tuple[TopicCode | None, UnderstandingIssue | None]:
    topic_states = analysis.states
    topics = [
        topic
        for topic, polarity in topic_states.items()
        if polarity is _SelectionPolarity.POSITIVE
    ]
    if topics:
        selected = topics[0]
        for topic in topics[1:]:
            compatible = most_specific_compatible_topic(
                selected,
                topic,
            )
            if compatible is None:
                return None, UnderstandingIssue(
                    code="ambiguous_category",
                    detail=(
                        "检测到多个不同品类，请只保留一个明确的推荐品类。"
                    ),
                )
            selected = compatible
        return selected, None
    if any(
        polarity is _SelectionPolarity.UNKNOWN
        for polarity in topic_states.values()
    ):
        return None, UnderstandingIssue(
            code="ambiguous_category",
            detail=(
                "购买或选择立场仍不明确，请确认是否要继续推荐该品类。"
            ),
        )
    return None, None


def _parse_attribute_exclusion_issue(
    targets: list[_CategoryTargetMatch],
    category: TopicCode | None,
) -> UnderstandingIssue | None:
    if category is None or not any(
        target.topic is category for target in targets
    ):
        return None
    return UnderstandingIssue(
        code="unsupported_attribute_exclusion",
        detail=(
            "当前不能把这类感官或其他属性描述作为可验证的"
            "硬筛条件；请确认是否只按品类推荐。"
        ),
    )


def _analyze_category_selection(
    text: str,
    *,
    tokens: tuple[_ExactToken, ...] | None = None,
) -> _CategorySelectionAnalysis:
    parsed_tokens = (
        _lex_exact_tokens(text)
        if tokens is None
        else tokens
    )
    category_tokens = tuple(
        token
        for token in parsed_tokens
        if token.kind is _TokenKind.CATEGORY
        and isinstance(token.value, TopicCode)
    )
    states = {
        token.value: _SelectionPolarity.POSITIVE
        for token in category_tokens
    }
    hard_exclusions: set[TopicCode] = set()
    attribute_targets: list[_CategoryTargetMatch] = []
    owned_spans: list[SourceSpan] = []
    events, revision_target_issues = (
        _selection_events_and_issues_from_tokens(text, parsed_tokens)
    )
    for event in events:
        if (
            event.is_revision
            and event.polarity is _SelectionPolarity.POSITIVE
        ):
            revision_targets = {
                candidate.target_topic
                for candidate in events
                if (
                    candidate.is_revision
                    and candidate.action_span == event.action_span
                )
            }
            prior_topics = {
                token.value
                for token in category_tokens
                if token.source_span.start < event.action_span.start
            }
            for prior_topic in prior_topics - revision_targets:
                if (
                    states.get(prior_topic)
                    is _SelectionPolarity.POSITIVE
                ):
                    states.pop(prior_topic, None)
        owned_spans.extend(
            token.source_span
            for token in event.operator_stack
        )
        owned_spans.extend(
            (event.action_span, event.target_category_span)
        )
        if event.attribute_span is not None:
            attribute_targets.append(
                _CategoryTargetMatch(
                    topic=event.target_topic,
                    value=text[
                        event.attribute_span.start:event.attribute_span.end
                    ],
                    start=event.attribute_span.start,
                    end=event.attribute_span.end,
                )
            )
            owned_spans.append(event.attribute_span)
            continue
        states[event.target_topic] = event.polarity
        if (
            event.polarity is _SelectionPolarity.NEGATIVE
            and event.strength is _SelectionStrength.EXPLICIT
        ):
            hard_exclusions.add(event.target_topic)
        else:
            hard_exclusions.discard(event.target_topic)
    for issue in revision_target_issues:
        invalid_topics = {
            token.value
            for token in category_tokens
            if token.source_span.start < issue.action_span.start
        }
        invalid_topics.update(issue.target_topics)
        for topic in invalid_topics:
            states.pop(topic, None)
            hard_exclusions.discard(topic)
    deduplicated_targets = {
        (target.topic, target.start, target.end): target
        for target in attribute_targets
    }
    return _CategorySelectionAnalysis(
        states=states,
        hard_exclusions=frozenset(hard_exclusions),
        attribute_targets=tuple(deduplicated_targets.values()),
        events=events,
        revision_target_issues=revision_target_issues,
        owned_spans=_deduplicate_spans(owned_spans),
    )


def _selection_events(text: str) -> tuple[_SelectionEvent, ...]:
    tokens = _lex_exact_tokens(text)
    return _selection_events_from_tokens(text, tokens)


def _selection_events_from_tokens(
    text: str,
    tokens: tuple[_ExactToken, ...],
) -> tuple[_SelectionEvent, ...]:
    events, _ = _selection_events_and_issues_from_tokens(text, tokens)
    return events


def _selection_events_and_issues_from_tokens(
    text: str,
    tokens: tuple[_ExactToken, ...],
) -> tuple[
    tuple[_SelectionEvent, ...],
    tuple[_RevisionTargetIssue, ...],
]:
    events: list[_SelectionEvent] = []
    revision_target_issues: list[_RevisionTargetIssue] = []
    active_targets: tuple[_ExactToken, ...] = ()
    for clause in _split_clauses(text, tokens):
        (
            clause_events,
            explicit_targets,
            clause_issues,
        ) = _clause_selection_events(
            text,
            clause=clause,
            active_targets=active_targets,
        )
        events.extend(clause_events)
        revision_target_issues.extend(clause_issues)
        if clause_issues:
            active_targets = ()
        if explicit_targets:
            active_targets = explicit_targets
    return tuple(events), tuple(revision_target_issues)


def _clause_selection_events(
    text: str,
    *,
    clause: _Clause,
    active_targets: tuple[_ExactToken, ...],
) -> tuple[
    tuple[_SelectionEvent, ...],
    tuple[_ExactToken, ...],
    tuple[_RevisionTargetIssue, ...],
]:
    categories = tuple(
        token
        for token in clause.tokens
        if token.kind is _TokenKind.CATEGORY
    )
    actions = tuple(
        token
        for token in clause.tokens
        if token.kind is _TokenKind.SELECTION_ACTION
        and isinstance(token.value, _SelectionAction)
    )
    if not actions:
        events, targets = _operator_only_events(
            text,
            clause=clause,
            categories=categories,
        )
        return events, targets, ()

    events: list[_SelectionEvent] = []
    revision_target_issues: list[_RevisionTargetIssue] = []
    last_explicit_targets: tuple[_ExactToken, ...] = ()
    current_active_targets = active_targets
    claimed_category_spans: set[tuple[int, int]] = set()
    pending_operator_stack: tuple[_ExactToken, ...] = ()
    previous_action_end = clause.source_span.start
    for index, action_token in enumerate(actions):
        next_action_start = (
            actions[index + 1].source_span.start
            if index + 1 < len(actions)
            else clause.source_span.end
        )
        local_operator_stack = _operator_tokens(
            clause.tokens,
            start=previous_action_end,
            end=action_token.source_span.start,
        )
        is_revision = (
            action_token.is_revision
            or _has_revision_marker(
                clause.tokens,
                start=previous_action_end,
                end=action_token.source_span.start,
            )
        )
        operator_stack = (
            local_operator_stack
            if action_token.value is _SelectionAction.AVOID
            else (*pending_operator_stack, *local_operator_stack)
        )
        forward_targets = tuple(
            token
            for token in categories
            if (
                action_token.source_span.end
                <= token.source_span.start
                < next_action_start
                and (
                    token.source_span.start,
                    token.source_span.end,
                )
                not in claimed_category_spans
            )
        )
        explicit_targets = forward_targets
        direction = "forward"
        if not explicit_targets and index + 1 == len(actions):
            explicit_targets = tuple(
                token
                for token in categories
                if (
                    previous_action_end
                    <= token.source_span.start
                    and token.source_span.end
                    <= action_token.source_span.start
                    and (
                        token.source_span.start,
                        token.source_span.end,
                    )
                    not in claimed_category_spans
                )
            )
            direction = "backward"
        operator, polarity, strength = _selection_semantics(
            action=action_token,
            operator_stack=operator_stack,
        )
        if (
            is_revision
            and polarity is _SelectionPolarity.POSITIVE
            and len(explicit_targets) != 1
            and (
                current_active_targets
                or any(
                    target.source_span.start
                    < action_token.source_span.start
                    for target in categories
                )
            )
        ):
            revision_target_issues.append(
                _RevisionTargetIssue(
                    code=(
                        "missing_revision_target"
                        if not explicit_targets
                        else "ambiguous_revision_target"
                    ),
                    action_span=action_token.source_span,
                    target_topics=tuple(
                        target.value
                        for target in explicit_targets
                        if isinstance(target.value, TopicCode)
                    ),
                )
            )
            claimed_category_spans.update(
                (
                    token.source_span.start,
                    token.source_span.end,
                )
                for token in explicit_targets
            )
            pending_operator_stack = ()
            previous_action_end = action_token.source_span.end
            continue
        inherited = False
        targets = explicit_targets
        if (
            not targets
            and polarity is _SelectionPolarity.NEGATIVE
            and current_active_targets
        ):
            targets = current_active_targets
            direction = "inherited"
            inherited = True
        if explicit_targets:
            last_explicit_targets = explicit_targets
            current_active_targets = explicit_targets
            claimed_category_spans.update(
                (
                    token.source_span.start,
                    token.source_span.end,
                )
                for token in explicit_targets
            )
        if not targets:
            pending_operator_stack = operator_stack
            previous_action_end = action_token.source_span.end
            continue
        pending_operator_stack = ()

        for target_index, target in enumerate(targets):
            attribute_span = _selection_attribute_span(
                text,
                clause=clause,
                action=action_token,
                target=target,
                direction=direction,
                polarity=polarity,
                target_count=len(targets),
            )
            target_span = _selection_target_span(
                action=action_token,
                target=target,
                direction=direction,
                attribute_span=attribute_span,
                previous_target=(
                    targets[target_index - 1]
                    if target_index > 0
                    else None
                ),
            )
            event_start = min(
                (
                    operator_stack[0].source_span.start
                    if operator_stack
                    else action_token.source_span.start
                ),
                target_span.start,
            )
            event_end = max(
                action_token.source_span.end,
                target_span.end,
            )
            events.append(
                _SelectionEvent(
                    operator=operator,
                    polarity=polarity,
                    strength=strength,
                    action=action_token.value,
                    operator_stack=operator_stack,
                    action_span=action_token.source_span,
                    target_span=target_span,
                    target_category_span=target.source_span,
                    consumed_span=SourceSpan(
                        start=event_start,
                        end=event_end,
                    ),
                    clause_span=clause.source_span,
                    target_topic=target.value,
                    attribute_span=attribute_span,
                    inherited_target=inherited,
                    is_revision=is_revision,
                )
            )
        previous_action_end = action_token.source_span.end
    return (
        tuple(events),
        last_explicit_targets,
        tuple(revision_target_issues),
    )


def _operator_only_events(
    text: str,
    *,
    clause: _Clause,
    categories: tuple[_ExactToken, ...],
) -> tuple[tuple[_SelectionEvent, ...], tuple[_ExactToken, ...]]:
    operator_stack = _operator_tokens(
        clause.tokens,
        start=clause.source_span.start,
        end=clause.source_span.end,
    )
    if (
        not categories
        or not operator_stack
        or any(
            token.kind is _TokenKind.INGREDIENT
            for token in clause.tokens
        )
    ):
        return (), ()
    direct_operators = tuple(
        token
        for token in operator_stack
        if text[token.source_span.start:token.source_span.end]
        in {"不是", "并非", "无需", "无意"}
    )
    if not direct_operators:
        return (), ()
    synthetic_action = _ExactToken(
        kind=_TokenKind.SELECTION_ACTION,
        value=_SelectionAction.CONSIDER,
        source_span=direct_operators[-1].source_span,
    )
    operator, polarity, strength = _selection_semantics(
        action=synthetic_action,
        operator_stack=operator_stack,
    )
    events = tuple(
        _SelectionEvent(
            operator=operator,
            polarity=polarity,
            strength=strength,
            action=_SelectionAction.CONSIDER,
            operator_stack=operator_stack,
            action_span=synthetic_action.source_span,
            target_span=category.source_span,
            target_category_span=category.source_span,
            consumed_span=SourceSpan(
                start=min(
                    operator_stack[0].source_span.start,
                    category.source_span.start,
                ),
                end=max(
                    operator_stack[-1].source_span.end,
                    category.source_span.end,
                ),
            ),
            clause_span=clause.source_span,
            target_topic=category.value,
            attribute_span=None,
            inherited_target=False,
            is_revision=False,
        )
        for category in categories
    )
    return events, categories


def _has_revision_marker(
    tokens: tuple[_ExactToken, ...],
    *,
    start: int,
    end: int,
) -> bool:
    return any(
        token.kind is _TokenKind.REVISION
        and start <= token.source_span.start
        and token.source_span.end <= end
        for token in tokens
    )


def _operator_tokens(
    tokens: tuple[_ExactToken, ...],
    *,
    start: int,
    end: int,
) -> tuple[_ExactToken, ...]:
    return tuple(
        token
        for token in tokens
        if (
            start <= token.source_span.start
            and token.source_span.end <= end
            and token.kind
            in {
                _TokenKind.NEGATION_OPERATOR,
                _TokenKind.HEDGE,
                _TokenKind.MODAL,
                _TokenKind.REPORTING_MODAL,
                _TokenKind.POSITIVE_MODAL,
            }
        )
    )


def _selection_semantics(
    *,
    action: _ExactToken,
    operator_stack: tuple[_ExactToken, ...],
) -> tuple[
    _SelectionOperator,
    _SelectionPolarity,
    _SelectionStrength,
]:
    if any(
        token.kind is _TokenKind.REPORTING_MODAL
        for token in operator_stack
    ):
        return (
            _SelectionOperator.WRAPPED,
            _SelectionPolarity.UNKNOWN,
            _SelectionStrength.WRAPPED,
        )
    if any(
        token.kind is _TokenKind.MODAL
        for token in operator_stack
    ):
        return (
            _SelectionOperator.MODAL,
            _SelectionPolarity.UNKNOWN,
            _SelectionStrength.HEDGED,
        )
    if any(
        token.kind is _TokenKind.HEDGE
        for token in operator_stack
    ):
        return (
            _SelectionOperator.HEDGED,
            _SelectionPolarity.UNKNOWN,
            _SelectionStrength.HEDGED,
        )
    negation_count = sum(
        token.kind is _TokenKind.NEGATION_OPERATOR
        for token in operator_stack
    )
    if action.value is _SelectionAction.AVOID:
        negation_count += 1
    if negation_count > 2:
        return (
            _SelectionOperator.NESTED,
            _SelectionPolarity.UNKNOWN,
            _SelectionStrength.WRAPPED,
        )
    if negation_count == 1:
        return (
            _SelectionOperator.NEGATED,
            _SelectionPolarity.NEGATIVE,
            _SelectionStrength.EXPLICIT,
        )
    return (
        _SelectionOperator.AFFIRMATIVE,
        _SelectionPolarity.POSITIVE,
        _SelectionStrength.EXPLICIT,
    )


def _selection_attribute_span(
    text: str,
    *,
    clause: _Clause,
    action: _ExactToken,
    target: _ExactToken,
    direction: str,
    polarity: _SelectionPolarity,
    target_count: int,
) -> SourceSpan | None:
    if (
        polarity is not _SelectionPolarity.NEGATIVE
        or target_count != 1
    ):
        return None
    if direction == "forward":
        start = action.source_span.end
        end = target.source_span.start
    elif direction == "backward":
        start = action.source_span.end
        end = clause.source_span.end
    else:
        return None
    raw_value = text[start:end]
    stripped = raw_value.strip()
    if stripped == "的":
        return None
    if not _is_prenominal_attribute_target(raw_value):
        return None
    if _is_closed_quantifier_target(
        text,
        tokens=clause.tokens,
        start=start,
        end=end,
    ):
        return None
    return SourceSpan(start=start, end=end)


def _selection_target_span(
    *,
    action: _ExactToken,
    target: _ExactToken,
    direction: str,
    attribute_span: SourceSpan | None,
    previous_target: _ExactToken | None,
) -> SourceSpan:
    if direction == "forward":
        start = (
            previous_target.source_span.end
            if previous_target is not None
            else action.source_span.end
        )
        return SourceSpan(start=start, end=target.source_span.end)
    if direction == "backward" and attribute_span is not None:
        return SourceSpan(
            start=target.source_span.start,
            end=attribute_span.end,
        )
    return target.source_span


def _is_prenominal_attribute_target(text: str) -> bool:
    return _CATEGORY_PRENOMINAL_ATTRIBUTE_TARGET.fullmatch(text) is not None


def _is_closed_quantifier_target(
    text: str,
    *,
    tokens: tuple[_ExactToken, ...],
    start: int,
    end: int,
) -> bool:
    quantifiers = [
        token
        for token in tokens
        if (
            token.kind is _TokenKind.CATEGORY_QUANTIFIER
            and start <= token.source_span.start
            and token.source_span.end <= end
        )
    ]
    if len(quantifiers) != 1:
        return False
    raw_value = "".join(text[start:end].split())
    quantifier = text[
        quantifiers[0].source_span.start:quantifiers[0].source_span.end
    ]
    return raw_value in {
        quantifier,
        f"{quantifier}的",
        f"{quantifier}相关的",
    }


def _deduplicate_spans(
    spans: list[SourceSpan],
) -> tuple[SourceSpan, ...]:
    unique = {
        (span.start, span.end): span
        for span in spans
    }
    return tuple(
        unique[key]
        for key in sorted(unique)
    )


def _parse_efficacy(text: str) -> EfficacyTarget | None:
    for alias, target in _EFFICACY_ALIASES:
        if alias in text:
            return target
    return None


def _parse_skin(text: str) -> SkinTarget | None:
    if (
        any(alias in text for alias in ("油皮", "油性"))
        and any(
            alias in text
            for alias in ("敏感肌", "敏感皮", "敏感")
        )
    ):
        return SkinTarget.OILY_SENSITIVE
    for alias, target in _SKIN_ALIASES:
        if alias in text:
            return target
    return None


def _skin_target_for_alias(alias: str) -> SkinTarget:
    for candidate, target in _SKIN_ALIASES:
        if candidate == alias:
            return target
    raise AssertionError(f"unknown skin alias: {alias}")


def _parse_exclusions(
    text: str,
    *,
    tokens: tuple[_ExactToken, ...],
    ownership: _SpanOwnership,
    selection_events: tuple[_SelectionEvent, ...],
) -> list[str]:
    values: list[str] = []
    clauses = _split_clauses(text, tokens)
    for ingredient in (
        token
        for token in tokens
        if token.kind is _TokenKind.INGREDIENT
    ):
        if ownership.overlaps(ingredient.source_span):
            continue
        clause = next(
            (
                item
                for item in clauses
                if (
                    item.source_span.start
                    <= ingredient.source_span.start
                    < item.source_span.end
                )
            ),
            None,
        )
        if clause is None:
            continue
        operators = [
            token
            for token in clause.tokens
            if (
                token.kind is _TokenKind.NEGATION_OPERATOR
                and token.source_span.end
                <= ingredient.source_span.start
            )
        ]
        if not operators:
            continue
        operator = operators[-1]
        if _is_soft_exclusion_preference(
            text,
            exclusion_start=operator.source_span.start,
        ):
            continue
        nested_negative_selection = any(
            event.polarity is _SelectionPolarity.NEGATIVE
            and event.strength is _SelectionStrength.EXPLICIT
            and event.action_span.end
            <= ingredient.source_span.start
            < event.target_category_span.start
            for event in selection_events
        )
        if (
            not nested_negative_selection
            and not _is_ingredient_absence_operator(
                text,
                operator=operator,
                ingredient=ingredient,
            )
        ):
            continue
        ownership.claim(ingredient.source_span)
        values.append(ingredient.value)
    return list(dict.fromkeys(values))


def _parse_generic_hard_exclusions(
    text: str,
    *,
    ownership: _SpanOwnership,
) -> list[str]:
    values: list[str] = []
    for pattern in (
        _HARD_ABSENCE_EXCLUSION,
        _BARE_ABSENCE_EXCLUSION,
        _EXPLICIT_ALLERGY_EXCLUSION,
    ):
        for match in pattern.finditer(text):
            if ownership.overlaps(
                SourceSpan(start=match.start(), end=match.end())
            ):
                continue
            if _is_soft_exclusion_preference(
                text,
                exclusion_start=match.start(),
            ):
                continue
            value = "".join(match.group("value").split())
            if value:
                values.append(value)
    for ingredient in _INGREDIENTS:
        if re.search(
            rf"(?:我)?(?:对)?{re.escape(ingredient)}"
            rf"(?:过敏|不耐受)",
            text,
        ):
            values.append(ingredient)
    return list(dict.fromkeys(values))


def _parse_hard_ingredient_inclusions(
    text: str,
    *,
    ownership: _SpanOwnership,
) -> list[str]:
    values: list[str] = []
    for match in _HARD_INGREDIENT_INCLUSION.finditer(text):
        span = SourceSpan(start=match.start(), end=match.end())
        if ownership.overlaps(span):
            continue
        value = "".join(match.group("value").split())
        if not value:
            continue
        ownership.claim(span)
        values.append(value)
    return list(dict.fromkeys(values))


def _is_soft_exclusion_preference(
    text: str,
    *,
    exclusion_start: int,
) -> bool:
    clause_start = max(
        (
            text.rfind(boundary, 0, exclusion_start)
            + len(boundary)
            for boundary in ("，", ",", "。", ".", "！", "!", "？", "?", "；", ";")
        ),
        default=0,
    )
    prefix = "".join(text[clause_start:exclusion_start].split())
    if any(cue in prefix for cue in _HARD_SAFETY_CUES):
        return False
    return any(prefix.endswith(cue) for cue in _SOFT_EXCLUSION_CUES)


def _parse_unverified_safety_requirement(
    text: str,
) -> UnderstandingIssue | None:
    if not (
        _HIGH_RISK_POPULATION_SAFETY.search(text)
        or _ACTIVE_DAMAGE_SAFETY.search(text)
        or _SAFETY_OUTCOME_QUERY.search(text)
    ):
        return None
    return UnderstandingIssue(
        code="unverified_safety_requirement",
        detail=(
            "当前无法用强证据核实该人群或安全要求；"
            "请以实物完整成分表、备案信息或专业意见为准。"
        ),
    )


def _is_ingredient_absence_operator(
    text: str,
    *,
    operator: _ExactToken,
    ingredient: _ExactToken,
) -> bool:
    raw_operator = text[
        operator.source_span.start:operator.source_span.end
    ]
    if raw_operator in {"无意", "无需", "并非", "不是"}:
        return False
    gap = "".join(
        text[operator.source_span.end:ingredient.source_span.start].split()
    )
    if raw_operator == "无":
        return gap in {"", "含", "有"}
    if raw_operator in {"不", "不能", "没", "未"}:
        return gap in {"", "含", "有", "要", "要含", "要有"}
    return False
