"""Phase 3 bookmark sync/re-import regression tests."""

from unittest.mock import patch

from app.config import Settings
from app.db.schema import get_connection
from app.models.capture import BookmarkImportItem, BookmarkImportRequest
from app.models.user import LOCAL_DEFAULT_USER_ID
from app.services.import_manager import ImportManager


def _payload(
    ids: list[str], *, complete: bool, mode: str = "scheduled"
) -> BookmarkImportRequest:
    return BookmarkImportRequest(
        source_browser="chrome",
        sync_mode=mode,
        snapshot_complete=complete,
        items=[
            BookmarkImportItem(
                browser_bookmark_id=bid,
                folder_path="Saved",
                url=f"https://example.com/{bid}",
                title=f"Bookmark {bid}",
            )
            for bid in ids
        ],
    )


def _sync(manager: ImportManager, payload: BookmarkImportRequest) -> dict:
    # Processing is irrelevant to snapshot-state tests; all URLs are treated as
    # already indexed so no network or embedding provider is used.
    with patch.object(manager._dupes, "known_url_hashes", return_value=set()), patch.object(
        manager._dupes, "check"
    ) as check:
        check.return_value.is_duplicate = True
        check.return_value.reason = "already indexed"
        return manager.import_bookmarks(
            payload,
            user_id=LOCAL_DEFAULT_USER_ID,
            async_processing=False,
        )


def _rows(settings: Settings) -> dict[str, dict]:
    with get_connection(settings) as conn:
        rows = conn.execute(
            """
            SELECT browser_bookmark_id, sync_status, removed_in_browser, source_browser
            FROM browser_bookmarks
            WHERE user_id = ?
            ORDER BY browser_bookmark_id
            """,
            (LOCAL_DEFAULT_USER_ID,),
        ).fetchall()
    return {row["browser_bookmark_id"]: dict(row) for row in rows}


def test_complete_snapshot_marks_missing_bookmarks_removed(test_settings: Settings) -> None:
    manager = ImportManager(test_settings)
    _sync(manager, _payload(["a", "b"], complete=True, mode="manual"))
    _sync(manager, _payload(["b", "c"], complete=True))

    rows = _rows(test_settings)
    assert rows["a"]["removed_in_browser"] == 1
    assert rows["a"]["sync_status"] == "removed"
    assert rows["b"]["removed_in_browser"] == 0
    assert rows["b"]["sync_status"] == "synced"
    assert rows["c"]["removed_in_browser"] == 0


def test_incomplete_snapshot_never_marks_unseen_bookmarks_removed(
    test_settings: Settings,
) -> None:
    manager = ImportManager(test_settings)
    _sync(manager, _payload(["a", "b"], complete=True, mode="manual"))
    _sync(manager, _payload(["b"], complete=False))

    rows = _rows(test_settings)
    assert rows["a"]["removed_in_browser"] == 0
    assert rows["a"]["sync_status"] == "synced"


def test_empty_complete_snapshot_marks_all_browser_bookmarks_removed(
    test_settings: Settings,
) -> None:
    manager = ImportManager(test_settings)
    _sync(manager, _payload(["a", "b"], complete=True, mode="manual"))
    result = _sync(manager, _payload([], complete=True))

    rows = _rows(test_settings)
    assert all(row["removed_in_browser"] == 1 for row in rows.values())
    assert all(row["sync_status"] == "removed" for row in rows.values())
    assert result["status"] == "completed"
    assert result["snapshot_complete"] is True


def test_snapshot_reconciliation_is_scoped_by_browser_and_user(
    test_settings: Settings,
) -> None:
    manager = ImportManager(test_settings)
    _sync(manager, _payload(["chrome-a"], complete=True, mode="manual"))

    with get_connection(test_settings) as conn:
        now = "2026-01-01T00:00:00+00:00"
        conn.execute(
            """
            INSERT INTO browser_bookmarks (
                user_id, browser_bookmark_id, folder_path, url, url_hash, title,
                sync_status, source_browser, last_synced_at, removed_in_browser
            ) VALUES (?, ?, '', ?, ?, ?, 'synced', 'firefox', ?, 0)
            """,
            (
                LOCAL_DEFAULT_USER_ID,
                "firefox-a",
                "https://example.com/firefox-a",
                "hash-firefox",
                "Firefox",
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO browser_bookmarks (
                user_id, browser_bookmark_id, folder_path, url, url_hash, title,
                sync_status, source_browser, last_synced_at, removed_in_browser
            ) VALUES (?, ?, '', ?, ?, ?, 'synced', 'chrome', ?, 0)
            """,
            (
                "other-user",
                "other-a",
                "https://example.com/other-a",
                "hash-other",
                "Other",
                now,
            ),
        )

    _sync(manager, _payload([], complete=True))

    with get_connection(test_settings) as conn:
        firefox = conn.execute(
            "SELECT removed_in_browser FROM browser_bookmarks WHERE user_id=? AND browser_bookmark_id='firefox-a'",
            (LOCAL_DEFAULT_USER_ID,),
        ).fetchone()
        other = conn.execute(
            "SELECT removed_in_browser FROM browser_bookmarks WHERE user_id='other-user' AND browser_bookmark_id='other-a'"
        ).fetchone()
    assert firefox["removed_in_browser"] == 0
    assert other["removed_in_browser"] == 0
