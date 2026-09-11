"""Bounded capture sessions for Home Agent vision ingestion.

This layer does not open a camera. It creates short-lived, user- and source-bound
sessions that must be active before a structured vision detection can pass to
the consent-gated vision adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .observation_ingest import ObservationConsent
from .vision_adapter import ConsentGatedVisionAdapter, VisionDetection


DEFAULT_CAPTURE_SESSION_TTL = timedelta(minutes=5)
MAX_CAPTURE_SESSION_TTL = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class CaptureSession:
    session_id: str
    user_id: str
    source_id: str
    started_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id is required")
        if not self.user_id.strip():
            raise ValueError("user_id is required")
        if not self.source_id.strip():
            raise ValueError("source_id is required")
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("started_at must be timezone-aware")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")
        if self.expires_at <= self.started_at:
            raise ValueError("expires_at must be after started_at")
        if self.expires_at - self.started_at > MAX_CAPTURE_SESSION_TTL:
            raise ValueError("capture session exceeds maximum duration")

    def allows(self, *, user_id: str, source_id: str, observed_at: datetime, now: datetime) -> bool:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if self.user_id != user_id or self.source_id != source_id:
            return False
        if not (self.started_at <= observed_at < self.expires_at):
            return False
        return self.started_at <= now < self.expires_at


class BoundedVisionCaptureService:
    """Require an explicit bounded capture session before vision ingestion."""

    def __init__(self, adapter: ConsentGatedVisionAdapter) -> None:
        self._adapter = adapter

    def start_session(
        self,
        *,
        user_id: str,
        source_id: str,
        now: datetime | None = None,
        ttl: timedelta = DEFAULT_CAPTURE_SESSION_TTL,
    ) -> CaptureSession:
        if not user_id.strip():
            raise ValueError("user_id is required")
        if not source_id.strip():
            raise ValueError("source_id is required")
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        if ttl > MAX_CAPTURE_SESSION_TTL:
            raise ValueError("ttl exceeds maximum capture-session duration")

        started_at = now or datetime.now(timezone.utc)
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise ValueError("now must be timezone-aware")

        return CaptureSession(
            session_id=str(uuid4()),
            user_id=user_id,
            source_id=source_id,
            started_at=started_at,
            expires_at=started_at + ttl,
        )

    def ingest_detection(
        self,
        *,
        user_id: str,
        session: CaptureSession,
        detection: VisionDetection,
        consent: ObservationConsent,
        now: datetime | None = None,
    ) -> bool:
        resolved_now = now or datetime.now(timezone.utc)
        if not session.allows(
            user_id=user_id,
            source_id=detection.source_id,
            observed_at=detection.observed_at,
            now=resolved_now,
        ):
            raise PermissionError("capture session is missing, mismatched, or expired")

        return self._adapter.ingest_detection(
            user_id=user_id,
            detection=detection,
            consent=consent,
            now=resolved_now,
        )
