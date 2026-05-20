"""Database backup and restore for Meli."""
from __future__ import annotations

import shutil
import sqlite3
import structlog
from datetime import datetime, timezone
from pathlib import Path

from meli.config import get_config

log = structlog.get_logger()


def backup_database(destination: Path | None = None) -> Path:
    """Create an encrypted backup of the SQLite database."""
    cfg = get_config()
    src = Path(cfg.db_path)

    if not src.exists():
        raise FileNotFoundError(f"Database not found at {src}")

    if destination is None:
        backup_dir = cfg.data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        destination = backup_dir / f"meli_backup_{ts}.db"

    # Use SQLite's online backup API for consistency
    src_conn = sqlite3.connect(str(src))
    dst_conn = sqlite3.connect(str(destination))
    src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()

    destination.chmod(0o600)
    log.info("Database backed up", dest=str(destination), size=destination.stat().st_size)
    return destination


def restore_database(backup_path: Path) -> None:
    """Restore the database from a backup file."""
    cfg = get_config()
    dst = Path(cfg.db_path)

    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    # Validate it's a SQLite file
    with open(backup_path, "rb") as f:
        magic = f.read(16)
    if not magic.startswith(b"SQLite format 3"):
        raise ValueError("Not a valid SQLite database file")

    # Swap files
    tmp = dst.with_suffix(".db.tmp")
    shutil.copy2(backup_path, tmp)
    tmp.chmod(0o600)

    if dst.exists():
        dst.rename(dst.with_suffix(".db.pre-restore"))

    tmp.rename(dst)
    log.info("Database restored", source=str(backup_path))


def vacuum_database() -> None:
    """Run VACUUM to reclaim space."""
    cfg = get_config()
    conn = sqlite3.connect(cfg.db_path)
    conn.execute("VACUUM")
    conn.close()
    log.info("Database vacuumed")


def get_database_stats() -> dict:
    """Return size and row counts for key tables."""
    cfg = get_config()
    db_path = Path(cfg.db_path)
    size_bytes = db_path.stat().st_size if db_path.exists() else 0

    conn = sqlite3.connect(str(db_path))
    tables = ["events", "attackers", "credentials", "commands", "payloads", "alerts"]
    counts = {}
    for table in tables:
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = row[0] if row else 0
        except Exception:
            counts[table] = 0
    conn.close()

    return {
        "size_bytes": size_bytes,
        "size_human": _fmt(size_bytes),
        "path": str(db_path),
        "table_counts": counts,
    }


def _fmt(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} TB"
