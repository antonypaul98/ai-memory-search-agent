from datetime import datetime, timedelta, timezone

from app.services.home_agent.presence_derivation import PresenceObservation, derive_presence_transition


def obs(state: str, minute: int, confidence: float = 0.95) -> PresenceObservation:
    return PresenceObservation(
        state=state,
        observed_at_utc=datetime(2026, 9, 22, 20, minute, tzinfo=timezone.utc),
        confidence=confidence,
        source_id="front-door-camera",
        evidence_id=f"frame-{minute}",
    )


def test_derives_departure_only_after_confirmed_away_state():
    event = derive_presence_transition([obs("home", 0), obs("away", 1), obs("away", 2)])
    assert event is not None
    assert event.kind == "home_departure"
    assert event.occurred_at_utc == obs("away", 1).observed_at_utc
    assert event.evidence_id == "frame-1"


def test_derives_arrival_only_after_confirmed_home_state():
    event = derive_presence_transition([obs("away", 0), obs("home", 1), obs("home", 2)])
    assert event is not None
    assert event.kind == "home_arrival"


def test_single_noisy_state_flip_fails_closed():
    assert derive_presence_transition([obs("home", 0), obs("away", 1), obs("home", 2)]) is None


def test_low_confidence_observation_cannot_confirm_transition():
    assert derive_presence_transition([obs("home", 0), obs("away", 1, 0.4), obs("away", 2)]) is None


def test_returns_newest_confirmed_transition():
    event = derive_presence_transition([
        obs("home", 0), obs("away", 1), obs("away", 2),
        obs("home", 3), obs("home", 4),
    ])
    assert event is not None
    assert event.kind == "home_arrival"
    assert event.evidence_id == "frame-3"
