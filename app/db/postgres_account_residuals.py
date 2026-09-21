"""Remove classified account residuals after fencing and canonical erasure.

The allowlist is intentional: no dynamic deletion of unknown tables, no inference
of tenant identity from hashes, and no removal of durable erasure tombstones or
migration control records. Missing optional tables are distinct from read errors.
"""
from app.db.postgres_job_repository import ConnectionFactory

# Children with non-composite foreign keys use canonical parent ownership.
CHILDREN = {
    "topic_memory_links": ("topic_profiles", "topic_id"),
    "ingest_agent_claims": ("ingest_agent_rules", "rule_id"),
}
TABLES = (
    "youtube_retry_queue", "youtube_pipeline_runs", "youtube_connector_metrics",
    "browser_bookmarks", "content_url_index", "ingest_artifacts", "memory_fts_documents",
    "semantic_cache", "memory_review_schedule", "topic_profiles", "ingest_agent_rules",
    "youtube_memories", "video_reflection", "video_registry", "users",
)


def delete_account_residuals(factory: ConnectionFactory, *, user_id: str) -> dict[str, int]:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id is required")
    counts = {}
    with factory() as conn:
        if conn.execute("SELECT 1 FROM account_erasure_fences WHERE user_id=%s", (user_id,)).fetchone() is None:
            raise PermissionError("account erasure requires a durable fence")
        for table in (*CHILDREN, *TABLES):
            if conn.execute("SELECT to_regclass(%s) AS relation", (table,)).fetchone()["relation"] is None:
                counts[table] = 0
                continue
            if table in CHILDREN:
                parent, key = CHILDREN[table]
                cursor = conn.execute(
                    f"DELETE FROM {table} child USING {parent} parent "
                    f"WHERE child.{key}=parent.{key} AND parent.user_id=%s", (user_id,)
                )
            else:
                cursor = conn.execute(f"DELETE FROM {table} WHERE user_id=%s", (user_id,))
            counts[table] = int(cursor.rowcount)
    return counts
