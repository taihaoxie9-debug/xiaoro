from __future__ import annotations

from app.guide.understanding.contracts import TopicCode


_TOPIC_LABELS = {
    TopicCode.SUNSCREEN: "防晒",
    TopicCode.SERUM: "精华",
    TopicCode.SKINCARE: "护肤",
    TopicCode.BASE_MAKEUP: "底妆",
    TopicCode.COLOR_MAKEUP: "彩妆",
    TopicCode.CLEANSER: "洁面/卸妆",
    TopicCode.FRAGRANCE: "香水",
}


def topic_label(topic: TopicCode) -> str:
    return _TOPIC_LABELS[topic]
