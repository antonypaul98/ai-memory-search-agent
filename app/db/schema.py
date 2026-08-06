"""SQLite schema versioning, FTS5, hashes, and cache metadata."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import Settings, get_settings

SCHEMA_VERSION = 9


def get_connection(settings: Settings | None = None) -> sqlite3.Connection:
    settings = settings or get_settings()
    Path(settings.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn


def migrate(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    with get_connection(settings) as conn:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current >= SCHEMA_VERSION:
            return
        if current < 1:
            _migrate_v1(conn)
        if current < 2:
            _migrate_v2(conn)
        if current < 3:
            _migrate_v3(conn)
        if current < 4:
            _migrate_v4(conn)
        if current < 5:
            _migrate_v5(conn)
        if current < 6:
            _migrate_v6(conn)
        if current < 7:
            _migrate_v7(conn)
        if current < 8:
            _migrate_v8(conn)
        if current < 9:
            _migrate_v9(conn)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _migrate_v1(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        INSERT OR IGNORE INTO app_meta (key, value) VALUES ('memory_index_version', '1');
        INSERT OR IGNORE INTO app_meta (key, value) VALUES ('preference_version', '1');
        """
    )


def _migrate_v2(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS content_hashes (
            video_id TEXT PRIMARY KEY,
            transcript_hash TEXT NOT NULL,
            normalized_path TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chunk_hashes (
            chunk_hash TEXT PRIMARY KEY,
            video_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            reused INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS memory_capsules_json (
            video_id TEXT PRIMARY KEY,
            capsule_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            video_id UNINDEXED,
            level UNINDEXED,
            doc_id UNINDEXED,
            title,
            body,
            tokenize='porter'
        );

        CREATE TABLE IF NOT EXISTS semantic_cache (
            cache_key TEXT PRIMARY KEY,
            question_normalized TEXT NOT NULL,
            question_embedding BLOB,
            answer_json TEXT NOT NULL,
            query_type TEXT NOT NULL,
            memory_index_version TEXT NOT NULL,
            preference_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        """
    )


def _migrate_v3(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            email TEXT UNIQUE,
            password_hash TEXT,
            display_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS background_jobs (
            job_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            job_type TEXT NOT NULL,
            playlist_id TEXT,
            playlist_title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            total_videos INTEGER NOT NULL DEFAULT 0,
            queued INTEGER NOT NULL DEFAULT 0,
            processing INTEGER NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0,
            skipped INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            error_summary TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            lease_owner TEXT,
            lease_until TEXT,
            paused INTEGER NOT NULL DEFAULT 0,
            force_refresh INTEGER NOT NULL DEFAULT 0,
            reflection_json TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS job_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            item_key TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            error TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(job_id, item_key)
        );

        CREATE TABLE IF NOT EXISTS job_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS captures (
            capture_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            url TEXT NOT NULL,
            url_hash TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL DEFAULT 'web',
            status TEXT NOT NULL,
            job_id TEXT,
            payload_json TEXT NOT NULL DEFAULT '',
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS browser_bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            browser_bookmark_id TEXT NOT NULL,
            folder_path TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL,
            url_hash TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            sync_status TEXT NOT NULL DEFAULT 'synced',
            source_browser TEXT NOT NULL DEFAULT 'chrome',
            last_synced_at TEXT NOT NULL,
            removed_in_browser INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, browser_bookmark_id)
        );

        INSERT OR IGNORE INTO users (user_id, email, password_hash, display_name, created_at)
        VALUES ('local-default', NULL, NULL, 'Local Demo User', datetime('now'));
        """
    )
    _migrate_video_registry_user_id(conn)


def _migrate_v4(conn: sqlite3.Connection) -> None:
    """Universal memory, lifecycle audit, trust history, knowledge graph."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_records (
            memory_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            external_id TEXT NOT NULL,
            canonical_url TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            source_author TEXT NOT NULL DEFAULT '',
            lifecycle_state TEXT NOT NULL DEFAULT 'captured',
            verification_status TEXT NOT NULL DEFAULT 'unverified',
            object_schema_version INTEGER NOT NULL DEFAULT 1,
            content_version INTEGER NOT NULL DEFAULT 1,
            provenance_json TEXT NOT NULL DEFAULT '{}',
            embedding_refs_json TEXT NOT NULL DEFAULT '{}',
            trust_snapshot_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            relationship_summary_json TEXT NOT NULL DEFAULT '{}',
            published_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, source_type, external_id)
        );

        CREATE INDEX IF NOT EXISTS idx_memory_records_user_lifecycle
            ON memory_records(user_id, lifecycle_state);
        CREATE INDEX IF NOT EXISTS idx_memory_records_user_updated
            ON memory_records(user_id, updated_at);

        CREATE TABLE IF NOT EXISTS memory_lifecycle_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            actor TEXT NOT NULL DEFAULT 'system',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_memory_lifecycle_memory
            ON memory_lifecycle_events(memory_id, created_at);

        CREATE TABLE IF NOT EXISTS memory_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            version_number INTEGER NOT NULL,
            lifecycle_state TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            trust_overall REAL,
            title TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(memory_id, version_number)
        );

        CREATE TABLE IF NOT EXISTS memory_trust_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            trust_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_memory_trust_history_memory
            ON memory_trust_history(memory_id, created_at);

        CREATE TABLE IF NOT EXISTS kg_entities (
            entity_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            aliases_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, entity_type, normalized_name)
        );

        CREATE INDEX IF NOT EXISTS idx_kg_entities_user_type
            ON kg_entities(user_id, entity_type);
        CREATE INDEX IF NOT EXISTS idx_kg_entities_user_name
            ON kg_entities(user_id, normalized_name);

        CREATE TABLE IF NOT EXISTS kg_relations (
            relation_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            subject_entity_id TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object_entity_id TEXT NOT NULL,
            memory_id TEXT,
            confidence REAL NOT NULL DEFAULT 1.0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_kg_relations_subject
            ON kg_relations(user_id, subject_entity_id);
        CREATE INDEX IF NOT EXISTS idx_kg_relations_object
            ON kg_relations(user_id, object_entity_id);
        CREATE INDEX IF NOT EXISTS idx_kg_relations_memory
            ON kg_relations(memory_id);

        CREATE TABLE IF NOT EXISTS kg_memory_entities (
            memory_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            mention_context TEXT NOT NULL DEFAULT '',
            start_time REAL,
            end_time REAL,
            confidence REAL NOT NULL DEFAULT 1.0,
            PRIMARY KEY (memory_id, entity_id)
        );

        CREATE INDEX IF NOT EXISTS idx_kg_memory_entities_entity
            ON kg_memory_entities(user_id, entity_id);
        """
    )


def _migrate_video_registry_user_id(conn: sqlite3.Connection) -> None:
    def _table_exists(name: str) -> bool:
        return bool(
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone()
        )

    if _table_exists("video_registry"):
        cols = {row[1] for row in conn.execute("PRAGMA table_info(video_registry)").fetchall()}
        if "user_id" not in cols:
            conn.execute(
                "ALTER TABLE video_registry ADD COLUMN user_id TEXT NOT NULL DEFAULT 'local-default'"
            )
    if _table_exists("video_reflection"):
        cols = {row[1] for row in conn.execute("PRAGMA table_info(video_reflection)").fetchall()}
        if "user_id" not in cols:
            conn.execute(
                "ALTER TABLE video_reflection ADD COLUMN user_id TEXT NOT NULL DEFAULT 'local-default'"
            )
    if _table_exists("semantic_cache"):
        cols = {row[1] for row in conn.execute("PRAGMA table_info(semantic_cache)").fetchall()}
        if "user_id" not in cols:
            conn.execute(
                "ALTER TABLE semantic_cache ADD COLUMN user_id TEXT NOT NULL DEFAULT 'local-default'"
            )


def _migrate_v5(conn: sqlite3.Connection) -> None:
    """Agent status support: capture stages + search event log."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(captures)").fetchall()}
    if "stage" not in cols:
        conn.execute("ALTER TABLE captures ADD COLUMN stage TEXT NOT NULL DEFAULT ''")
    if "stage_detail" not in cols:
        conn.execute("ALTER TABLE captures ADD COLUMN stage_detail TEXT NOT NULL DEFAULT ''")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS agent_search_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            query TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_agent_search_user_created
            ON agent_search_events(user_id, created_at DESC);
        """
    )


def _migrate_v6(conn: sqlite3.Connection) -> None:
    """YouTube Memory Agent: rich memories, pipeline runs, retry queue, metrics."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS youtube_memories (
            memory_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            video_id TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            channel TEXT NOT NULL DEFAULT '',
            channel_id TEXT NOT NULL DEFAULT '',
            published_at TEXT,
            duration_sec REAL,
            thumbnail TEXT NOT NULL DEFAULT '',
            playback_position_sec REAL,
            language TEXT,
            transcript_availability TEXT NOT NULL DEFAULT 'unknown',
            transcript_kind TEXT NOT NULL DEFAULT 'unknown',
            transcript_status TEXT NOT NULL DEFAULT 'pending',
            tags_json TEXT NOT NULL DEFAULT '[]',
            categories_json TEXT NOT NULL DEFAULT '[]',
            playlist_id TEXT,
            playlist_title TEXT,
            playlist_index INTEGER,
            saved_at TEXT NOT NULL,
            user_notes TEXT NOT NULL DEFAULT '',
            embedding_status TEXT NOT NULL DEFAULT 'pending',
            processing_status TEXT NOT NULL DEFAULT 'queued',
            content_hash TEXT NOT NULL DEFAULT '',
            chunk_count INTEGER NOT NULL DEFAULT 0,
            duplicate_of TEXT,
            is_duplicate INTEGER NOT NULL DEFAULT 0,
            raw_metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, video_id)
        );
        CREATE INDEX IF NOT EXISTS idx_yt_mem_user_channel
            ON youtube_memories(user_id, channel);
        CREATE INDEX IF NOT EXISTS idx_yt_mem_user_published
            ON youtube_memories(user_id, published_at);
        CREATE INDEX IF NOT EXISTS idx_yt_mem_user_status
            ON youtube_memories(user_id, processing_status);

        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            video_id TEXT NOT NULL DEFAULT '',
            capture_id TEXT,
            stage TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            elapsed_ms REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pipeline_runs_run
            ON pipeline_runs(run_id, id);

        CREATE TABLE IF NOT EXISTS connector_retry_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            connector_id TEXT NOT NULL,
            external_id TEXT NOT NULL,
            url TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 5,
            next_attempt_at TEXT NOT NULL,
            last_error TEXT NOT NULL DEFAULT '',
            dead_lettered INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_retry_due
            ON connector_retry_queue(dead_lettered, next_attempt_at);

        CREATE TABLE IF NOT EXISTS connector_metrics (
            metric_key TEXT NOT NULL,
            connector_id TEXT NOT NULL DEFAULT 'youtube.v1',
            value_real REAL NOT NULL DEFAULT 0,
            value_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (metric_key, connector_id)
        );
        """
    )


def _migrate_v7(conn: sqlite3.Connection) -> None:
    """Memory Intelligence Layer: topics, learning edges, concept capsules, creators."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS topic_profiles (
            topic_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'topic',
            summary TEXT NOT NULL DEFAULT '',
            memory_count INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            last_updated_at TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            UNIQUE(user_id, normalized_name)
        );
        CREATE INDEX IF NOT EXISTS idx_topic_profiles_user_count
            ON topic_profiles(user_id, memory_count DESC);

        CREATE TABLE IF NOT EXISTS topic_memory_links (
            topic_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            video_id TEXT NOT NULL,
            memory_id TEXT,
            strength REAL NOT NULL DEFAULT 1.0,
            evidence TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (topic_id, video_id)
        );
        CREATE INDEX IF NOT EXISTS idx_topic_links_video
            ON topic_memory_links(user_id, video_id);

        CREATE TABLE IF NOT EXISTS learning_edges (
            edge_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            source_video_id TEXT NOT NULL,
            target_video_id TEXT NOT NULL,
            relation TEXT NOT NULL,
            strength REAL NOT NULL DEFAULT 0.5,
            evidence TEXT NOT NULL DEFAULT '',
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            UNIQUE(user_id, source_video_id, target_video_id, relation)
        );
        CREATE INDEX IF NOT EXISTS idx_learning_edges_source
            ON learning_edges(user_id, source_video_id);
        CREATE INDEX IF NOT EXISTS idx_learning_edges_target
            ON learning_edges(user_id, target_video_id);

        CREATE TABLE IF NOT EXISTS concept_capsules (
            capsule_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            topic_ids_json TEXT NOT NULL DEFAULT '[]',
            memory_video_ids_json TEXT NOT NULL DEFAULT '[]',
            creator_names_json TEXT NOT NULL DEFAULT '[]',
            progress_total INTEGER NOT NULL DEFAULT 0,
            progress_completed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, normalized_name)
        );
        CREATE INDEX IF NOT EXISTS idx_concept_capsules_user
            ON concept_capsules(user_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS creator_profiles (
            creator_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            channel_id TEXT NOT NULL DEFAULT '',
            video_count INTEGER NOT NULL DEFAULT 0,
            topics_json TEXT NOT NULL DEFAULT '[]',
            total_duration_sec REAL NOT NULL DEFAULT 0,
            avg_duration_sec REAL NOT NULL DEFAULT 0,
            beginner_count INTEGER NOT NULL DEFAULT 0,
            advanced_count INTEGER NOT NULL DEFAULT 0,
            view_count INTEGER NOT NULL DEFAULT 0,
            helpful_count INTEGER NOT NULL DEFAULT 0,
            related_creators_json TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, normalized_name)
        );
        CREATE INDEX IF NOT EXISTS idx_creator_profiles_user
            ON creator_profiles(user_id, video_count DESC);

        CREATE TABLE IF NOT EXISTS intelligence_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            topic TEXT,
            video_id TEXT,
            query TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_intel_events_user_created
            ON intelligence_events(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_intel_events_type
            ON intelligence_events(user_id, event_type, created_at DESC);
        """
    )


def _migrate_v8(conn: sqlite3.Connection) -> None:
    """Universal connectors: import manager, cross-source URL/content index."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS import_runs (
            import_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            connector_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            total_items INTEGER NOT NULL DEFAULT 0,
            completed_items INTEGER NOT NULL DEFAULT 0,
            failed_items INTEGER NOT NULL DEFAULT 0,
            skipped_items INTEGER NOT NULL DEFAULT 0,
            duplicate_items INTEGER NOT NULL DEFAULT 0,
            unsupported_items INTEGER NOT NULL DEFAULT 0,
            detail TEXT NOT NULL DEFAULT '',
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_import_runs_user
            ON import_runs(user_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS import_run_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            url TEXT NOT NULL,
            external_id TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued',
            detail TEXT NOT NULL DEFAULT '',
            error TEXT,
            capture_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_import_items_run
            ON import_run_items(import_id, status);

        CREATE TABLE IF NOT EXISTS content_url_index (
            user_id TEXT NOT NULL,
            url_hash TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            content_hash TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL,
            connector_id TEXT NOT NULL,
            external_id TEXT NOT NULL,
            memory_id TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, url_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_content_url_hash
            ON content_url_index(user_id, content_hash);
        CREATE INDEX IF NOT EXISTS idx_content_url_external
            ON content_url_index(user_id, source_type, external_id);
        """
    )


def _migrate_v9(conn: sqlite3.Connection) -> None:
    """Composite tenant keys for video_registry / video_reflection (F-31 / P-06)."""
    _migrate_video_registry_user_id(conn)
    if not conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='video_registry'"
    ).fetchone():
        conn.executescript(
            """
            CREATE TABLE video_registry (
                user_id TEXT NOT NULL DEFAULT 'local-default',
                video_id TEXT NOT NULL,
                url TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                saved_at TEXT NOT NULL,
                last_viewed TEXT,
                view_count INTEGER NOT NULL DEFAULT 0,
                search_count INTEGER NOT NULL DEFAULT 0,
                last_searched TEXT,
                helpful_count INTEGER NOT NULL DEFAULT 0,
                not_helpful_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, video_id)
            );
            CREATE TABLE video_reflection (
                user_id TEXT NOT NULL DEFAULT 'local-default',
                video_id TEXT NOT NULL,
                save_reason TEXT NOT NULL DEFAULT '',
                goal TEXT NOT NULL DEFAULT '',
                reflection_note TEXT NOT NULL DEFAULT '',
                recommendations_enabled INTEGER NOT NULL DEFAULT 0,
                preferred_creator_only INTEGER NOT NULL DEFAULT 0,
                allow_other_creators INTEGER NOT NULL DEFAULT 1,
                difficulty TEXT NOT NULL DEFAULT '',
                preferred_style TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (user_id, video_id)
            );
            """
        )
        return

    # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
    pk_cols = [
        row[1]
        for row in conn.execute("PRAGMA table_info(video_registry)").fetchall()
        if row[5]
    ]
    if set(pk_cols) == {"user_id", "video_id"}:
        return

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS video_registry_v9 (
            user_id TEXT NOT NULL DEFAULT 'local-default',
            video_id TEXT NOT NULL,
            url TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            channel TEXT NOT NULL DEFAULT '',
            saved_at TEXT NOT NULL,
            last_viewed TEXT,
            view_count INTEGER NOT NULL DEFAULT 0,
            search_count INTEGER NOT NULL DEFAULT 0,
            last_searched TEXT,
            helpful_count INTEGER NOT NULL DEFAULT 0,
            not_helpful_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, video_id)
        );
        CREATE TABLE IF NOT EXISTS video_reflection_v9 (
            user_id TEXT NOT NULL DEFAULT 'local-default',
            video_id TEXT NOT NULL,
            save_reason TEXT NOT NULL DEFAULT '',
            goal TEXT NOT NULL DEFAULT '',
            reflection_note TEXT NOT NULL DEFAULT '',
            recommendations_enabled INTEGER NOT NULL DEFAULT 0,
            preferred_creator_only INTEGER NOT NULL DEFAULT 0,
            allow_other_creators INTEGER NOT NULL DEFAULT 1,
            difficulty TEXT NOT NULL DEFAULT '',
            preferred_style TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (user_id, video_id)
        );
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO video_registry_v9 (
            user_id, video_id, url, title, channel, saved_at, last_viewed,
            view_count, search_count, last_searched, helpful_count, not_helpful_count
        )
        SELECT
            COALESCE(NULLIF(user_id, ''), 'local-default'),
            video_id, url, title, channel, saved_at, last_viewed,
            view_count, search_count, last_searched, helpful_count, not_helpful_count
        FROM video_registry
        """
    )
    refl_cols = {row[1] for row in conn.execute("PRAGMA table_info(video_reflection)").fetchall()}
    if refl_cols:
        user_expr = (
            "COALESCE(NULLIF(user_id, ''), 'local-default')"
            if "user_id" in refl_cols
            else "'local-default'"
        )
        conn.execute(
            f"""
            INSERT OR IGNORE INTO video_reflection_v9 (
                user_id, video_id, save_reason, goal, reflection_note,
                recommendations_enabled, preferred_creator_only, allow_other_creators,
                difficulty, preferred_style
            )
            SELECT
                {user_expr},
                video_id, save_reason, goal, reflection_note,
                recommendations_enabled, preferred_creator_only, allow_other_creators,
                difficulty, preferred_style
            FROM video_reflection
            """
        )
    conn.executescript(
        """
        DROP TABLE video_registry;
        DROP TABLE IF EXISTS video_reflection;
        ALTER TABLE video_registry_v9 RENAME TO video_registry;
        ALTER TABLE video_reflection_v9 RENAME TO video_reflection;
        CREATE INDEX IF NOT EXISTS idx_video_registry_saved
            ON video_registry(user_id, saved_at DESC);
        """
    )


def bump_index_version(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    migrate(settings)
    with get_connection(settings) as conn:
        row = conn.execute(
            "SELECT value FROM app_meta WHERE key = 'memory_index_version'"
        ).fetchone()
        version = int(row["value"]) + 1 if row else 1
        conn.execute(
            "INSERT OR REPLACE INTO app_meta (key, value) VALUES ('memory_index_version', ?)",
            (str(version),),
        )
        return str(version)


def get_index_version(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    migrate(settings)
    with get_connection(settings) as conn:
        row = conn.execute(
            "SELECT value FROM app_meta WHERE key = 'memory_index_version'"
        ).fetchone()
        return row["value"] if row else "1"


def get_preference_version(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    migrate(settings)
    with get_connection(settings) as conn:
        row = conn.execute(
            "SELECT value FROM app_meta WHERE key = 'preference_version'"
        ).fetchone()
        return row["value"] if row else "1"


def invalidate_semantic_cache(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    migrate(settings)
    with get_connection(settings) as conn:
        conn.execute("DELETE FROM semantic_cache")
