"""Tenant-scoped query layer for persisted Home Agent physical memory."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from .physical_memory import ObjectSighting

class PhysicalMemoryStore(Protocol):
    def latest(self, *, user_id: str, object_name: str, min_confidence: float = 0.0) -> ObjectSighting | None: ...
    def history(self, *, user_id: str, object_name: str, min_confidence: float = 0.0, limit: int = 20) -> list[ObjectSighting]: ...
class InspectableEvidenceStore(Protocol):
    def describe_observation(self, *, user_id: str, observation_id: str) -> dict | None: ...
    def get_image(self, *, user_id: str, frame_id: str) -> bytes | None: ...
@dataclass(frozen=True, slots=True)
class WhereAnswer:
    object_name: str; location: str; observed_at: str; confidence: float; source_id: str; evidence_id: str
    evidence_frame_id: str | None = None; evidence_image_sha256: str | None = None; evidence_detector_id: str | None = None
    @property
    def text(self)->str: return f"{self.object_name} was last seen at {self.location} at {self.observed_at}."
@dataclass(frozen=True, slots=True)
class MovementEvent:
    object_name: str; from_location: str; to_location: str; moved_at: str; confidence: float; source_id: str; from_evidence_id: str; to_evidence_id: str
@dataclass(frozen=True, slots=True)
class BeforeLocationAnswer:
    object_name: str; location: str; before_location: str; moved_at: str; confidence: float; source_id: str; evidence_id: str; destination_evidence_id: str
    @property
    def text(self)->str: return f"{self.object_name} was at {self.location} before {self.before_location}."

class HomeAgentQueryService:
    def __init__(self, store: PhysicalMemoryStore)->None: self._store=store
    def _where_answer(self, *, user_id:str, sighting:ObjectSighting)->WhereAnswer:
        evidence=None; describe=getattr(self._store,"describe_observation",None)
        if callable(describe): evidence=describe(user_id=user_id, observation_id=sighting.evidence_id)
        return WhereAnswer(sighting.object_name,sighting.location,sighting.observed_at.isoformat(),sighting.confidence,sighting.source_id,sighting.evidence_id,evidence.get("frame_id") if evidence else None,evidence.get("image_sha256") if evidence else None,evidence.get("detector_id") if evidence else None)
    def where_is(self, *, user_id:str, object_name:str, min_confidence:float=.5)->WhereAnswer|None:
        s=self._store.latest(user_id=user_id,object_name=object_name,min_confidence=min_confidence); return self._where_answer(user_id=user_id,sighting=s) if s else None
    def where_is_between(self, *, user_id:str, object_name:str, since:datetime, until:datetime, min_confidence:float=.5, limit:int=100)->WhereAnswer|None:
        if since.tzinfo is None or until.tzinfo is None: raise ValueError("time boundaries must be timezone-aware")
        if since>=until: raise ValueError("since must be earlier than until")
        for s in self.history(user_id=user_id,object_name=object_name,min_confidence=min_confidence,limit=limit):
            if s.observed_at.tzinfo is None: raise ValueError("physical-memory timestamps must be timezone-aware")
            if since<=s.observed_at<until: return self._where_answer(user_id=user_id,sighting=s)
        return None
    def where_is_before_departure(self, *, user_id:str, object_name:str, min_confidence:float=.5, event_min_confidence:float=.5, limit:int=100)->WhereAnswer|None:
        """Fail closed unless this tenant has a qualified evidence-backed departure anchor."""
        resolver=getattr(self._store,"latest_presence_event",None)
        if not callable(resolver): return None
        departure=resolver(user_id=user_id,kind="home_departure",min_confidence=event_min_confidence)
        if departure is None: return None
        for s in self.history(user_id=user_id,object_name=object_name,min_confidence=min_confidence,limit=limit):
            if s.observed_at.tzinfo is None: raise ValueError("physical-memory timestamps must be timezone-aware")
            if s.observed_at < departure.occurred_at_utc: return self._where_answer(user_id=user_id,sighting=s)
        return None
    def evidence_image(self, *, user_id:str, answer:WhereAnswer)->bytes|None:
        return self.evidence_frame(user_id=user_id,frame_id=answer.evidence_frame_id) if answer.evidence_frame_id else None
    def evidence_frame(self, *, user_id:str, frame_id:str)->bytes|None:
        if not frame_id.strip(): return None
        f=getattr(self._store,"get_image",None); return f(user_id=user_id,frame_id=frame_id) if callable(f) else None
    def history(self, *, user_id:str, object_name:str, min_confidence:float=0.0, limit:int=20)->list[ObjectSighting]: return self._store.history(user_id=user_id,object_name=object_name,min_confidence=min_confidence,limit=limit)
    def movement_history(self, *, user_id:str, object_name:str, min_confidence:float=.5, limit:int=20, since:datetime|None=None, until:datetime|None=None)->list[MovementEvent]:
        if since is not None and since.tzinfo is None: raise ValueError("since must be timezone-aware")
        if until is not None and until.tzinfo is None: raise ValueError("until must be timezone-aware")
        if since is not None and until is not None and since>=until: raise ValueError("since must be earlier than until")
        sightings=self.history(user_id=user_id,object_name=object_name,min_confidence=min_confidence,limit=limit); events=[]; previous=None
        for current in reversed(sightings):
            if previous is not None and current.location!=previous.location:
                moved_at=current.observed_at
                if moved_at.tzinfo is None: raise ValueError("physical-memory timestamps must be timezone-aware")
                if (since is None or moved_at>=since) and (until is None or moved_at<until): events.append(MovementEvent(current.object_name,previous.location,current.location,moved_at.isoformat(),current.confidence,current.source_id,previous.evidence_id,current.evidence_id))
            previous=current
        return events
    def before_location(self, *, user_id:str, object_name:str, location:str, min_confidence:float=.5, limit:int=20)->BeforeLocationAnswer|None:
        target=location.strip().casefold()
        if not target: return None
        for m in reversed(self.movement_history(user_id=user_id,object_name=object_name,min_confidence=min_confidence,limit=limit)):
            if m.to_location.strip().casefold()==target: return BeforeLocationAnswer(m.object_name,m.from_location,m.to_location,m.moved_at,m.confidence,m.source_id,m.from_evidence_id,m.to_evidence_id)
        return None
