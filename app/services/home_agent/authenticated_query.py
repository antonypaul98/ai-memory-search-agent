"""Authenticated identity boundary for Home Agent physical-memory queries."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from app.models.user import UserPublic
from .query_service import BeforeLocationAnswer, HomeAgentQueryService, MovementEvent, WhereAnswer
from .physical_memory import ObjectSighting

@dataclass(frozen=True, slots=True)
class AuthenticatedHomeAgentQuery:
    service: HomeAgentQueryService
    user: UserPublic
    def where_is(self, *, object_name:str, min_confidence:float=.5)->WhereAnswer|None:
        return self.service.where_is(user_id=self.user.user_id,object_name=object_name,min_confidence=min_confidence)
    def where_is_before_departure(self, *, object_name:str, min_confidence:float=.5, event_min_confidence:float=.5, limit:int=100)->WhereAnswer|None:
        return self.service.where_is_before_departure(user_id=self.user.user_id,object_name=object_name,min_confidence=min_confidence,event_min_confidence=event_min_confidence,limit=limit)
    def where_is_today(self, *, object_name:str, min_confidence:float=.5, now:datetime|None=None, limit:int=100)->WhereAnswer|None:
        resolved_now=now or datetime.now(timezone.utc)
        if resolved_now.tzinfo is None: raise ValueError("now must be timezone-aware")
        local_now=resolved_now.astimezone(ZoneInfo(self.user.timezone_name)); local_start=datetime.combine(local_now.date(),time.min,tzinfo=local_now.tzinfo); local_end=local_start+timedelta(days=1)
        return self.service.where_is_between(user_id=self.user.user_id,object_name=object_name,since=local_start,until=local_end,min_confidence=min_confidence,limit=limit)
    def history(self, *, object_name:str, min_confidence:float=0.0, limit:int=20)->list[ObjectSighting]: return self.service.history(user_id=self.user.user_id,object_name=object_name,min_confidence=min_confidence,limit=limit)
    def movement_history(self, *, object_name:str, min_confidence:float=.5, limit:int=20, since:datetime|None=None, until:datetime|None=None)->list[MovementEvent]:
        return self.service.movement_history(user_id=self.user.user_id,object_name=object_name,min_confidence=min_confidence,limit=limit,since=since,until=until)
    def before_location(self, *, object_name:str, location:str, min_confidence:float=.5, limit:int=20)->BeforeLocationAnswer|None:
        return self.service.before_location(user_id=self.user.user_id,object_name=object_name,location=location,min_confidence=min_confidence,limit=limit)
