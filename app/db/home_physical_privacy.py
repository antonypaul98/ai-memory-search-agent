"""Exact-tenant privacy primitives for Home Agent physical-memory data."""
from __future__ import annotations

from app.db.postgres_privacy_tables import table_exists

from typing import Any

from app.db.postgres_job_repository import ConnectionFactory


def export_user_home_physical_data(
    connection_factory: ConnectionFactory,
    *,
    user_id: str,
) -> dict[str, list[dict[str, Any]]]:
    """Export one tenant's Home physical-memory rows without raw image bytes."""
    user_id = _required_user_id(user_id)
    with connection_factory() as conn:
        sightings = conn.execute(
            """SELECT evidence_id, object_name, location, observed_at, confidence, source_id
               FROM home_object_sightings WHERE user_id = %s
               ORDER BY observed_at, evidence_id""",
            (user_id,),
        ).fetchall()
        evidence = conn.execute(
            """SELECT frame_id, image_sha256, source_id, location, observed_at, detector_id, created_at
               FROM home_image_evidence WHERE user_id = %s
               ORDER BY observed_at, frame_id""",
            (user_id,),
        ).fetchall()
        objects = conn.execute(
            """SELECT object_id, object_class, identity_kind
               FROM home_physical_objects WHERE user_id = %s
               ORDER BY object_class, object_id""",
            (user_id,),
        ).fetchall()
        observations = conn.execute(
            """SELECT observation_id, object_id, frame_id, box_json
               FROM home_image_observations WHERE user_id = %s
               ORDER BY observation_id""",
            (user_id,),
        ).fetchall()
    return {
        "sightings": [dict(row) for row in sightings],
        "image_evidence": [dict(row) for row in evidence],
        "physical_objects": [dict(row) for row in objects],
        "image_observations": [dict(row) for row in observations],
    }


def delete_user_home_physical_data(
    connection_factory: ConnectionFactory,
    *,
    user_id: str,
) -> dict[str, int]:
    """Atomically erase exactly one tenant's Home physical-memory rows and image bytes."""
    user_id = _required_user_id(user_id)
    with connection_factory() as conn:
        observation_count = _delete_count(
            conn,
            "DELETE FROM home_image_observations WHERE user_id = %s",
            user_id,
        )
        evidence_count = _delete_count(
            conn,
            "DELETE FROM home_image_evidence WHERE user_id = %s",
            user_id,
        )
        object_count = _delete_count(
            conn,
            "DELETE FROM home_physical_objects WHERE user_id = %s",
            user_id,
        )
        sighting_count = _delete_count(
            conn,
            "DELETE FROM home_object_sightings WHERE user_id = %s",
            user_id,
        )
    return {
        "image_observations": observation_count,
        "image_evidence": evidence_count,
        "physical_objects": object_count,
        "sightings": sighting_count,
    }


def _delete_count(conn: Any, statement: str, user_id: str) -> int:
    if not table_exists(conn, statement.split()[2]):
        return 0
    result = conn.execute(statement, (user_id,))
    return max(0, int(getattr(result, "rowcount", 0) or 0))


def _required_user_id(user_id: str) -> str:
    normalized = str(user_id).strip()
    if not normalized:
        raise ValueError("user_id is required")
    return normalized
