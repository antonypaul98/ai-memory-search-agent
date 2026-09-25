"""Unambiguous, deterministic IDs shared by vector writers and canonical refs."""
from __future__ import annotations

import hashlib
import json


def tenant_vector_id(level: str, user_id: str, external_id: str, index: int | None = None) -> str:
    # Delimiter-joined raw components alias (a_b, c) with (a, b_c).
    # A versioned namespace leaves previously persisted IDs/references untouched.
    identity = json.dumps([level, user_id, external_id, index], ensure_ascii=True, separators=(",", ":"))
    return "v2:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
