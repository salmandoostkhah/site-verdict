import sqlite3

import pytest

from seo_core.models import AuditReport
from seo_core.storage import (
    DB_ENV_VAR,
    SCHEMA_VERSION,
    Storage,
    StorageError,
    resolve_db_path,
)


@pytest.fixture
def storage(tmp_path):
    return Storage(tmp_path / "test.db")


def make_report(url="https://example.com", score=80):
    return AuditReport(url=url, overall_score=score, score=score)


def test_creates_schema_and_version(storage):
    assert storage.schema_version() == SCHEMA_VERSION
    with sqlite3.connect(storage.path) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"audits", "schema_version"} <= names


def test_reopening_does_not_reapply_migrations(tmp_path):
    path = tmp_path / "re.db"
    Storage(path)
    again = Storage(path)
    with sqlite3.connect(path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert count == SCHEMA_VERSION
    assert again.schema_version() == SCHEMA_VERSION


def test_newer_schema_is_rejected(tmp_path):
    path = tmp_path / "future.db"
    Storage(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION + 1,))
    with pytest.raises(StorageError):
        Storage(path)


def test_save_and_get_roundtrip(storage):
    report = make_report(score=73)
    audit_id = storage.save_audit(report)
    loaded = storage.get_audit(audit_id)
    assert loaded is not None
    assert loaded.url == report.url
    assert loaded.overall_score == 73
    assert loaded.crawl_date == report.crawl_date


def test_get_missing_returns_none(storage):
    assert storage.get_audit(999) is None


def test_list_newest_first_and_filtered_by_url(storage):
    a = storage.save_audit(make_report("https://a.example"))
    b = storage.save_audit(make_report("https://b.example"))
    c = storage.save_audit(make_report("https://a.example", score=50))

    all_ids = [s.id for s in storage.list_audits()]
    assert all_ids == [c, b, a]

    only_a = storage.list_audits(url="https://a.example")
    assert [s.id for s in only_a] == [c, a]
    assert only_a[0].score == 50


def test_list_respects_limit(storage):
    for _ in range(3):
        storage.save_audit(make_report())
    assert len(storage.list_audits(limit=2)) == 2
    with pytest.raises(ValueError):
        storage.list_audits(limit=0)


def test_url_is_bound_not_interpolated(storage):
    storage.save_audit(make_report("https://a.example"))
    assert storage.list_audits(url="x' OR '1'='1") == []


def test_corrupted_payload_raises(storage):
    audit_id = storage.save_audit(make_report())
    with sqlite3.connect(storage.path) as conn:
        conn.execute("UPDATE audits SET payload = '{bad' WHERE id = ?", (audit_id,))
    with pytest.raises(StorageError):
        storage.get_audit(audit_id)


def test_resolve_db_path_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv(DB_ENV_VAR, raising=False)
    assert resolve_db_path(tmp_path / "x.db") == tmp_path / "x.db"
    monkeypatch.setenv(DB_ENV_VAR, str(tmp_path / "env.db"))
    assert resolve_db_path() == tmp_path / "env.db"
    assert resolve_db_path(tmp_path / "arg.db") == tmp_path / "arg.db"