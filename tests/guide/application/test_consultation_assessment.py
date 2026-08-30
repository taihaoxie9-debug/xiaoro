from pydantic import ValidationError
import pytest

from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
)


def test_consultation_observation_rejects_legacy_code_answer_shape() -> None:
    with pytest.raises(ValidationError):
        ConsultationObservation(
            code="post_cleanse_tightness",
            answer="yes",
            source_turn_id="turn_000000000001",
        )
