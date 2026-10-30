"""Explicit local erasure of one stopped Home frame-journal session.

Only the exact JSONL journal and its optional matching evidence directory are
eligible. This unlinks files; it is not secure media wiping or backup erasure.
No expiry scheduler or camera access is involved.
"""
from __future__ import annotations

import fcntl
import os
import re
import stat
from pathlib import Path

_CROP = re.compile(r"[0-9]{4}-[0-9a-f]{32}\.jpg\Z")
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


def _private_directory(fd: int) -> None:
    mode = os.fstat(fd).st_mode
    if not stat.S_ISDIR(mode) or mode & 0o077:
        raise PermissionError("session directory must be private (0700)")


def _private_file(name: str, fd: int) -> None:
    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
            or info.st_nlink != 1):
        raise PermissionError("session file must be private, regular, and unlinked elsewhere")


def erase_stopped_frame_session(journal: Path) -> dict[str, int]:
    """Unlink only a named stopped session's journal and matching event crops.

    Requires explicit path, existing private parent, no symlinks, and no extra
    entries in the evidence directory. All entries are validated before deletion.
    Do not call while a preview or replay process is writing this session.
    """
    if (not isinstance(journal, Path) or not journal.is_absolute()
            or journal.suffix.lower() != ".jsonl" or journal.name in {".", ".."}):
        raise ValueError("provide an absolute .jsonl journal path")
    parent_fd = os.open(journal.parent, _DIR_FLAGS)
    journal_fd = None
    try:
        _private_directory(parent_fd)
        _private_file(journal.name, parent_fd)
        journal_fd = os.open(journal.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                             | getattr(os, "O_NONBLOCK", 0), dir_fd=parent_fd)
        opened = os.fstat(journal_fd)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_mode & 0o077
                or opened.st_nlink != 1):
            raise PermissionError("session journal must be private and regular")
        try:
            fcntl.flock(journal_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PermissionError("session journal is active; stop recording before erasure") from exc
        named = os.stat(journal.name, dir_fd=parent_fd, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise PermissionError("session journal changed during erasure preflight")
        crop_dir = journal.stem + "-evidence"
        try:
            evidence_fd = os.open(crop_dir, _DIR_FLAGS, dir_fd=parent_fd)
        except FileNotFoundError:
            evidence_fd = None
        crop_names: list[str] = []
        if evidence_fd is not None:
            try:
                _private_directory(evidence_fd)
                crop_names = os.listdir(evidence_fd)
                if len(crop_names) > 256:
                    raise PermissionError("unexpected number of event crops")
                for name in crop_names:
                    if not _CROP.fullmatch(name):
                        raise PermissionError("unexpected entry in evidence directory")
                    _private_file(name, evidence_fd)
                for name in crop_names:
                    os.unlink(name, dir_fd=evidence_fd)
            finally:
                os.close(evidence_fd)
            os.rmdir(crop_dir, dir_fd=parent_fd)
        os.unlink(journal.name, dir_fd=parent_fd)
        return {"journals_unlinked": 1, "event_crops_unlinked": len(crop_names)}
    finally:
        if journal_fd is not None:
            os.close(journal_fd)
        os.close(parent_fd)


def main(argv: list[str] | None = None) -> None:
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--confirm-erase-stopped-session", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_erase_stopped_session:
        parser.error("explicit --confirm-erase-stopped-session is required")
    print(json.dumps(erase_stopped_frame_session(args.journal), sort_keys=True))


if __name__ == "__main__":
    main()
