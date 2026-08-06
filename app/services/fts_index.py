"""SQLite FTS5 lexical search for hybrid retrieval."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.db.schema import get_connection, migrate


class FTSIndex:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        migrate(self._settings)

    def upsert(self, *, video_id: str, level: str, doc_id: str, title: str, body: str) -> None:
        with get_connection(self._settings) as conn:
            conn.execute(
                "DELETE FROM memory_fts WHERE doc_id = ?",
                (doc_id,),
            )
            conn.execute(
                "INSERT INTO memory_fts (video_id, level, doc_id, title, body) VALUES (?, ?, ?, ?, ?)",
                (video_id, level, doc_id, title, body),
            )

    def search(self, query: str, *, limit: int = 20, video_ids: list[str] | None = None) -> list[dict]:
        if not query.strip():
            return []
        try:
            with get_connection(self._settings) as conn:
                if video_ids:
                    placeholders = ",".join("?" for _ in video_ids)
                    sql = (
                        f"SELECT doc_id, video_id, level, title, snippet(memory_fts, 4, '[', ']', '…', 20) AS snippet "
                        f"FROM memory_fts WHERE memory_fts MATCH ? AND video_id IN ({placeholders}) "
                        f"ORDER BY rank LIMIT ?"
                    )
                    rows = conn.execute(sql, (query, *video_ids, limit)).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT doc_id, video_id, level, title, snippet(memory_fts, 4, '[', ']', '…', 20) AS snippet "
                        "FROM memory_fts WHERE memory_fts MATCH ? ORDER BY rank LIMIT ?",
                        (query, limit),
                    ).fetchall()
            results = []
            for rank, row in enumerate(rows, start=1):
                results.append(
                    {
                        "doc_id": row["doc_id"],
                        "video_id": row["video_id"],
                        "level": row["level"],
                        "title": row["title"],
                        "matched_text": row["snippet"],
                        "relevance_score": max(0.1, 1.0 / rank),
                        "rank": rank,
                    }
                )
            return results
        except Exception:
            return []

    def delete_video(self, video_id: str) -> None:
        with get_connection(self._settings) as conn:
            conn.execute("DELETE FROM memory_fts WHERE video_id = ?", (video_id,))
