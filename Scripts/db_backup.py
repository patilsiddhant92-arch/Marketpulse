"""Dated, pruned backups of the MarketPulse DuckDB files.

``backup_database`` copies ``<dir>/<stem>.duckdb`` to
``<dir>/backups/<stem>_YYYYmmdd_HHMMSS.duckdb`` (plus its ``.wal`` if one exists) and keeps
the newest ``keep`` copies (2 by default for the market DB, 7 for the small user DB). The copy is written under a ``.part`` name and renamed into place,
so a crash mid-copy never leaves a truncated file that looks like a backup. The source is
CHECKPOINTed first when a write connection can be opened (it cannot while another process
has the file open; the WAL is copied alongside in that case).
"""
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import duckdb

# Market-DB backups are full copies (GBs each on a multi-year history): keep the newest 2
# (user decision). There is no other backup slot - the old single-slot copies
# (marketpulse.backup / .preappend.backup / .predeals.backup) are no longer written anywhere.
DEFAULT_KEEP = int(os.environ.get("MP_DB_BACKUP_KEEP", "2") or 2)
DEFAULT_USER_KEEP = 7
# Head-room required on the backup volume beyond the file size itself.
_FREE_MARGIN_BYTES = 256 * 1024 * 1024


class BackupError(RuntimeError):
    """The backup could not be taken (e.g. not enough free disk space)."""


def backup_dir_for(db_path: Path) -> Path:
    return Path(db_path).parent / "backups"


def checkpoint(db_path: Path) -> bool:
    """Best-effort CHECKPOINT of ``db_path``; False if the file is held open elsewhere."""
    try:
        with duckdb.connect(str(db_path)) as con:
            con.execute("CHECKPOINT")
        return True
    except Exception as exc:  # noqa: BLE001 - a busy DB is normal (the app holds a reader)
        print(f"Note: could not CHECKPOINT {Path(db_path).name} before backup ({exc}); copying file + WAL.")
        return False


def _pattern(stem: str) -> re.Pattern:
    return re.compile(rf"^{re.escape(stem)}_\d{{8}}_\d{{6}}(?:_\d+)?\.duckdb$")


def list_backups(db_path: Path, backup_dir: Path | None = None) -> list[Path]:
    db_path = Path(db_path)
    folder = Path(backup_dir) if backup_dir else backup_dir_for(db_path)
    if not folder.exists():
        return []
    pat = _pattern(db_path.stem)
    return sorted(p for p in folder.iterdir() if p.is_file() and pat.match(p.name))


def prune_backups(db_path: Path, keep: int, backup_dir: Path | None = None) -> list[Path]:
    backups = list_backups(db_path, backup_dir)
    doomed = backups[:-keep] if keep > 0 else backups
    for path in doomed:
        for victim in (path, path.with_name(path.name + ".wal")):
            try:
                victim.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                print(f"Warning: could not prune old backup {victim}: {exc}")
    return doomed


def _ensure_space(folder: Path, needed: int) -> None:
    free = shutil.disk_usage(folder).free
    if free < needed + _FREE_MARGIN_BYTES:
        raise BackupError(
            f"Not enough free disk space for a backup in {folder}: need ~{(needed + _FREE_MARGIN_BYTES) / 1e9:.2f} GB, "
            f"free {free / 1e9:.2f} GB."
        )


def backup_database(
    db_path: Path,
    *,
    keep: int = DEFAULT_KEEP,
    backup_dir: Path | None = None,
    now: datetime | None = None,
    do_checkpoint: bool = True,
) -> Path | None:
    """Take a dated copy of ``db_path`` and prune to the newest ``keep``. None if no DB."""
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    folder = Path(backup_dir) if backup_dir else backup_dir_for(db_path)
    folder.mkdir(parents=True, exist_ok=True)
    if do_checkpoint:
        checkpoint(db_path)
    wal = db_path.with_name(db_path.name + ".wal")
    size = db_path.stat().st_size + (wal.stat().st_size if wal.exists() else 0)
    _ensure_space(folder, size)

    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    target = folder / f"{db_path.stem}_{stamp}.duckdb"
    n = 1
    while target.exists():
        target = folder / f"{db_path.stem}_{stamp}_{n}.duckdb"
        n += 1
    part = target.with_name(target.name + ".part")
    try:
        shutil.copy2(db_path, part)
        if wal.exists():
            shutil.copy2(wal, target.with_name(target.name + ".wal"))
        os.replace(part, target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    prune_backups(db_path, keep, folder)
    print(f"Backup written: {target}")
    return target


def backup_user_db(user_db_path: Path | None = None, *, keep: int = DEFAULT_USER_KEEP, now: datetime | None = None) -> Path | None:
    """Nightly backup of the user DB (journal / watchlists); keeps the newest ``keep``."""
    if user_db_path is None:
        from config import USER_DB_PATH

        user_db_path = USER_DB_PATH
    return backup_database(Path(user_db_path), keep=keep, now=now)
