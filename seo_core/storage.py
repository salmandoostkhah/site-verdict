"""
Persistence layer for Site Verdict audits (SQLite via the standard library).

Each audit is stored as a row in the ``audits`` table with its scalar summary
columns (url, crawl date, score, status) plus the full report as JSON, so the
schema stays stable while ``AuditReport`` evolves.

Schema changes are applied through ``MIGRATIONS``; the applied version is kept
in the ``schema_version`` table.
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Union

from pydantic import ValidationError

from seo_core.models import AuditReport

logger = logging.getLogger("seo_core.storage")

DB_ENV_VAR = "SITE_VERDICT_DB"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "site_verdict.db"

_MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    crawl_date TEXT NOT NULL,
    score INTEGER NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audits_url ON audits(url, id);
"""

# Each entry upgrades the schema from version (index) to version (index + 1).
MIGRATIONS: List[str] = [_MIGRATION_1]
SCHEMA_VERSION = len(MIGRATIONS)


class StorageError(Exception):
    """Raised when the database cannot be opened, migrated or queried."""


@dataclass(frozen=True)
class AuditSummary:
    id: int
    url: str
    crawl_date: str
    score: int
    status: str


def resolve_db_path(path: Optional[Union[str, Path]] = None) -> Path:
    """Return the DB path: explicit argument, then env var, then the default."""
    if path is not None:
        return Path(path)
    env_value = os.environ.get(DB_ENV_VAR, "").strip()
    if env_value:
        return Path(env_value)
    return DEFAULT_DB_PATH


class Storage:
    def __init__(self, path: Optional[Union[str, Path]] = None) -> None:
        self.path = resolve_db_path(path)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(f"cannot create database directory: {exc}") from exc
        self._migrate()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn: Optional[sqlite3.Connection] = None
        try:
            conn = sqlite3.connect(str(self.path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        except sqlite3.Error as exc:
            if conn is not None:
                conn.rollback()
            raise StorageError(f"database error: {exc}") from exc
        finally:
            if conn is not None:
                conn.close()

    def _migrate(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
            )
            row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            current = row["v"] or 0
            if current > SCHEMA_VERSION:
                raise StorageError(
                    f"database schema version {current} is newer than supported {SCHEMA_VERSION}"
                )
            for version in range(current, SCHEMA_VERSION):
                conn.executescript(MIGRATIONS[version])
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (version + 1,)
                )
                logger.info("applied storage migration %s", version + 1)

    def schema_version(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            return int(row["v"] or 0)

    def save_audit(self, report: AuditReport) -> int:
        """Store a report and return its new id."""
        payload = report.model_dump_json()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO audits (url, crawl_date, score, status, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    report.url,
                    report.crawl_date.isoformat(),
                    int(report.overall_score),
                    report.status,
                    payload,
                ),
            )
            return int(cursor.lastrowid)

    def list_audits(self, url: Optional[str] = None, limit: int = 50) -> List[AuditSummary]:
        """Return summaries, newest first, optionally filtered by exact URL."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        query = "SELECT id, url, crawl_date, score, status FROM audits"
        params: List[object] = []
        if url is not None:
            query += " WHERE url = ?"
            params.append(url)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            AuditSummary(
                id=int(r["id"]),
                url=r["url"],
                crawl_date=r["crawl_date"],
                score=int(r["score"]),
                status=r["status"],
            )
            for r in rows
        ]

    def get_audit(self, audit_id: int) -> Optional[AuditReport]:
        """Return the stored report, or None if the id does not exist."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM audits WHERE id = ?", (int(audit_id),)
            ).fetchone()
        if row is None:
            return None
        try:
            return AuditReport.model_validate_json(row["payload"])
        except ValidationError as exc:
            logger.error("stored audit %s failed validation: %s", audit_id, exc)
            raise StorageError(f"stored audit {audit_id} is corrupted") from exc