"""Complete, read-only supplemental privacy inventory for production Postgres.

Only explicitly classified portable tables are exported. Credentials, cached
answers, derived indexes, migration control and retained image bytes are excluded.
Optional domains that have never been initialized are represented by empty lists;
permission/schema/read failures propagate rather than masquerading as empty data.
"""
from __future__ import annotations

import json
from typing import Any

from app.db.postgres_job_repository import ConnectionFactory

# table -> (canonical parent, shared parent key). Child labels are not ownership
# authority, and inconsistent child labels are never exposed to another tenant.
PARENT_OWNERS = {
    "memory_lifecycle_events": ("memory_records", "memory_id"),
    "memory_versions": ("memory_records", "memory_id"),
    "memory_trust_history": ("memory_records", "memory_id"),
    "job_items": ("background_jobs", "job_id"),
    "job_events": ("background_jobs", "job_id"),
    "job_item_leases": ("background_jobs", "job_id"),
    "import_run_items": ("import_runs", "import_id"),
    "agent_tool_calls": ("agent_runs", "run_id"),
    "ingest_agent_claims": ("ingest_agent_rules", "rule_id"),
    "topic_memory_links": ("topic_profiles", "topic_id"),
}
PORTABLE_TABLES = (
    *PARENT_OWNERS,
    "video_reflection", "youtube_pipeline_runs", "youtube_retry_queue",
    "youtube_connector_metrics", "import_runs", "agent_runs", "ingest_agent_rules",
    "concept_capsules", "creator_profiles", "learning_edges", "intelligence_events",
    "home_object_sightings", "home_image_evidence", "home_physical_objects",
    "home_image_observations", "connector_oauth_tokens",
)
# Exclusions happen in SQL, before private bytes/credentials reach Python.
EXCLUDED_COLUMNS = {
    "home_image_evidence": ["image_bytes"],
    "connector_oauth_tokens": ["encrypted_payload"],
}


def _redact_json_fields(row: dict[str, Any]) -> dict[str, Any]:
    from app.services.event_bus import _redact_payload

    result = {}
    for key, value in row.items():
        if key.endswith("_json") and isinstance(value, str) and value:
            # Do not return an unparsed payload which may conceal credentials.
            value = json.dumps(_redact_payload(json.loads(value)), sort_keys=True)
        result[key] = value
    return _redact_payload(result)


def export_postgres_history(factory: ConnectionFactory, *, user_id: str) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id is required")
    result = {}
    with factory() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        for table in PORTABLE_TABLES:
            exists = conn.execute("SELECT to_regclass(%s) AS relation", (table,)).fetchone()
            if exists["relation"] is None:
                result[table] = []
                continue
            parent = PARENT_OWNERS.get(table)
            if parent:
                parent_table, key = parent
                join = f"JOIN {parent_table} parent ON parent.{key} = child.{key}"
                predicate = "parent.user_id = %s"
                if table not in ("job_events", "job_item_leases"):
                    # A corrupt child label is neither exported under its false
                    # tenant nor disclosed to the parent's tenant.
                    inconsistent = conn.execute(
                        f"SELECT 1 FROM {table} child {join} WHERE parent.user_id=%s "
                        "AND child.user_id IS DISTINCT FROM parent.user_id LIMIT 1", (user_id,)
                    ).fetchone()
                    if inconsistent:
                        raise ValueError("privacy export found inconsistent canonical ownership")
            else:
                join, predicate = "", "child.user_id = %s"
            cursor = conn.execute(
                f"SELECT to_jsonb(child) - %s::text[] AS record FROM {table} child {join} "
                f"WHERE {predicate} ORDER BY to_jsonb(child)::text",
                (EXCLUDED_COLUMNS.get(table, []), user_id),
            )
            rows = []
            while batch := cursor.fetchmany(1000):
                rows.extend(_redact_json_fields(row["record"]) for row in batch)
            result[table] = rows
    return result
