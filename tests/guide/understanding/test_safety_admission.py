from __future__ import annotations

from app.guide.understanding.safety_admission import (
    SafetyObservation,
    admit_safety_signal,
    classify_safety_observations,
)
from app.guide.understanding.turn_meaning_contracts import (
    TurnObservationCandidate,
)


def _candidate(
    code: str,
    *,
    raw_text: str,
    present: bool = True,
    trigger: str | None = None,
    duration: str | None = None,
    severity: str | None = None,
) -> TurnObservationCandidate:
    return TurnObservationCandidate.model_validate(
        {
            "observation_id": f"obs_{code}",
            "code": code,
            "present": present,
            "qualifier": None,
            "raw_text": raw_text,
            "location": None,
            "trigger": trigger,
            "duration": duration,
            "severity": severity,
        },
        strict=True,
    )


def test_safety_signal_uses_only_source_grounded_observations() -> None:
    ordinary = admit_safety_signal(
        message="最近护肤后会发热泛红",
        candidates=(
            _candidate(
                "burning",
                raw_text="发热",
                duration="current",
            ),
            _candidate(
                "redness",
                raw_text="泛红",
                duration="current",
            ),
        ),
    )
    hallucinated = admit_safety_signal(
        message="最近只是有点干",
        candidates=(
            _candidate(
                "oozing",
                raw_text="渗液",
                duration="current",
            ),
        ),
    )
    severe = admit_safety_signal(
        message="现在仍然在渗，而且碰水会疼",
        candidates=(
            _candidate(
                "oozing",
                raw_text="渗",
                duration="current",
            ),
            _candidate(
                "pain",
                raw_text="碰水会疼",
                duration="current",
            ),
        ),
    )

    assert ordinary.requires_escalation is False
    assert hallucinated.requires_escalation is False
    assert severe.trigger_codes == ("oozing",)


def test_shared_policy_keeps_one_deterministic_highest_priority_trigger(
) -> None:
    signal = classify_safety_observations(
        (
            SafetyObservation(
                code="pain",
                present=True,
                trigger=None,
                duration="current",
                severity="moderate",
            ),
            SafetyObservation(
                code="broken_skin",
                present=True,
                trigger=None,
                duration="current",
                severity="moderate",
            ),
            SafetyObservation(
                code="burning",
                present=True,
                trigger="new_product",
                duration="persistent",
                severity="severe",
            ),
        )
    )

    assert signal.trigger_codes == ("broken_skin",)


def test_absent_damage_observation_never_escalates() -> None:
    signal = admit_safety_signal(
        message="没有破皮",
        candidates=(
            _candidate(
                "broken_skin",
                raw_text="没有破皮",
                present=False,
            ),
        ),
    )

    assert signal.trigger_codes == ()
