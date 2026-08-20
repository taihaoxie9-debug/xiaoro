from typing import Protocol

from app.guide.decision.contracts import DecisionProductFacts


class DecisionFactPort(Protocol):
    def get_decision_facts(
        self,
        product_id: int,
    ) -> DecisionProductFacts: ...
