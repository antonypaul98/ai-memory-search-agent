"""Offline, temporary-directory tests for explicit local frame-session erasure."""
import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.home_agent.frame_session_erasure import erase_stopped_frame_session, main
from app.services.home_agent.frame_event_log import PrivateFrameEventLog


def fixture(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    journal = private / "events.jsonl"
    journal.write_text('{"visible": []}\n')
    journal.chmod(0o600)
    crops = private / "events-evidence"
    crops.mkdir(mode=0o700)
    name = f"0000-{uuid4().hex}.jpg"
    (crops / name).write_bytes(b"jpeg-placeholder")
    (crops / name).chmod(0o600)
    return journal, crops


def test_erases_only_matching_journal_and_crops(tmp_path):
    journal, crops = fixture(tmp_path)
    unrelated = journal.parent / "private-notes.txt"
    unrelated.write_text("preserve")
    assert erase_stopped_frame_session(journal) == {"journals_unlinked": 1, "event_crops_unlinked": 1}
    assert not journal.exists() and not crops.exists()
    assert unrelated.read_text() == "preserve"


def test_missing_crop_dir_is_supported(tmp_path):
    journal, crops = fixture(tmp_path)
    for child in crops.iterdir():
        child.unlink()
    crops.rmdir()
    assert erase_stopped_frame_session(journal)["event_crops_unlinked"] == 0


@pytest.mark.parametrize("entry", ["extra.txt", "nested", "symlink"])
def test_unexpected_entries_rejected_without_deleting(tmp_path, entry):
    journal, crops = fixture(tmp_path)
    if entry == "nested":
        (crops / entry).mkdir()
    elif entry == "symlink":
        (crops / entry).symlink_to(journal)
    else:
        (crops / entry).write_text("keep")
    with pytest.raises(PermissionError):
        erase_stopped_frame_session(journal)
    assert journal.exists() and len(list(crops.iterdir())) == 2


def test_symlink_evidence_dir_rejected(tmp_path):
    journal, crops = fixture(tmp_path)
    for child in crops.iterdir():
        child.unlink()
    crops.rmdir()
    (journal.parent / "events-evidence").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        erase_stopped_frame_session(journal)
    assert journal.exists()


def test_public_parent_rejected(tmp_path):
    journal, crops = fixture(tmp_path)
    journal.parent.chmod(0o755)
    with pytest.raises(PermissionError):
        erase_stopped_frame_session(journal)
    assert journal.exists() and crops.exists()


def test_hardlinked_journal_rejected(tmp_path):
    journal, crops = fixture(tmp_path)
    os.link(journal, journal.parent / "other.jsonl")
    with pytest.raises(PermissionError):
        erase_stopped_frame_session(journal)
    assert journal.exists() and crops.exists()


def test_bad_journal_path_rejected(tmp_path):
    for p in [Path("relative.jsonl"), tmp_path / "x.txt", "not-a-path"]:
        with pytest.raises(ValueError):
            erase_stopped_frame_session(p)


def test_explicit_confirmation_required(tmp_path):
    journal, _ = fixture(tmp_path)
    with pytest.raises(SystemExit):
        main(["--journal", str(journal)])
    assert journal.exists()
    main(["--journal", str(journal), "--confirm-erase-stopped-session"])
    assert not journal.exists()


def test_symlink_named_like_crop_rejected(tmp_path):
    journal, crops = fixture(tmp_path)
    (crops / ("0001-" + uuid4().hex + ".jpg")).symlink_to(journal)
    with pytest.raises(PermissionError):
        erase_stopped_frame_session(journal)
    assert journal.exists()


def test_hardlinked_crop_rejected(tmp_path):
    journal, crops = fixture(tmp_path)
    crop = next(crops.iterdir())
    os.link(crop, journal.parent / "linked-crop")
    with pytest.raises(PermissionError):
        erase_stopped_frame_session(journal)
    assert journal.exists() and crop.exists()

def test_active_journal_refuses_erasure_until_writer_closes(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    journal = private / "active.jsonl"
    with PrivateFrameEventLog(journal, camera_id="cam", room_name="office") as writer:
        writer.append_scan(scan_at=1.0, visible={}, events=[])
        evidence = private / "active-evidence"
        evidence.mkdir(mode=0o700)
        crop = evidence / f"0000-{uuid4().hex}.jpg"
        crop.write_bytes(b"jpeg-placeholder")
        crop.chmod(0o600)
        with pytest.raises(PermissionError, match="active"):
            erase_stopped_frame_session(journal)
        assert journal.exists() and crop.exists()
    assert erase_stopped_frame_session(journal) == {
        "journals_unlinked": 1, "event_crops_unlinked": 1,
    }
    assert not journal.exists() and not evidence.exists()
