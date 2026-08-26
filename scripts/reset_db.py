"""Safely clear local AI Memory Search Agent data stores.

Examples:
    python scripts/reset_db.py --dry-run
    python scripts/reset_db.py --yes

The command only removes paths configured for SQLite, Chroma, and transcript
artifacts. It refuses obviously dangerous targets such as the filesystem root,
the user's home directory, or the repository working directory itself.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Iterable

from app.config import Settings, get_settings


def _configured_targets(settings: Settings) -> list[Path]:
    sqlite = Path(settings.sqlite_path).expanduser()
    return [
        sqlite,
        Path(f"{sqlite}-wal"),
        Path(f"{sqlite}-shm"),
        Path(settings.chroma_persist_dir).expanduser(),
        Path(settings.transcript_artifact_dir).expanduser(),
    ]


def _assert_safe_target(path: Path) -> Path:
    resolved = path.resolve()
    forbidden = {Path("/").resolve(), Path.home().resolve(), Path.cwd().resolve()}
    if resolved in forbidden:
        raise ValueError(f"Refusing to delete unsafe path: {resolved}")
    if len(resolved.parts) < 3:
        raise ValueError(f"Refusing to delete suspiciously broad path: {resolved}")
    return resolved


def reset_local_data(
    settings: Settings | None = None,
    *,
    dry_run: bool = False,
) -> list[Path]:
    """Remove configured local data targets and return paths that existed.

    This function is intentionally deterministic and testable. Confirmation is
    handled by the CLI entry point; callers using this function directly are
    responsible for ensuring the operation is desired.
    """
    settings = settings or get_settings()
    existing: list[Path] = []

    for raw_target in _configured_targets(settings):
        target = _assert_safe_target(raw_target)
        if not target.exists():
            continue
        existing.append(target)
        if dry_run:
            continue
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    return existing


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clear local SQLite, Chroma, and transcript data for this project."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm destructive deletion without an interactive prompt.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show configured data paths that would be removed without deleting them.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    settings = get_settings()

    targets = [_assert_safe_target(path) for path in _configured_targets(settings)]
    print("Configured data targets:")
    for target in targets:
        print(f"  - {target}")

    if args.dry_run:
        existing = reset_local_data(settings, dry_run=True)
        print(f"Dry run: {len(existing)} existing target(s) would be removed.")
        return 0

    if not args.yes:
        print("Nothing deleted. Re-run with --yes after reviewing the paths above.")
        return 2

    removed = reset_local_data(settings)
    print(f"Reset complete: removed {len(removed)} existing target(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
