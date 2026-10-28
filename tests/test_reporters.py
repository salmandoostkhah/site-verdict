import json

import pytest

from seo_core.models import AuditReport, ContentMetrics, LocalSEOMetrics, OnPageMetrics
from seo_core.reporters import save_report, to_dict, to_html, to_json


@pytest.fixture
def report():
    return AuditReport(
        url="https://example.com",
        score=72,
        on_page=OnPageMetrics(
            title="سلام <script>alert(1)</script>",
            content=ContentMetrics(word_count=350, top_keywords=[("seo", 12)]),
        ),
        local_seo=LocalSEOMetrics(phone_numbers=["021-123"]),
        issues=["Missing meta description"],
        warnings=["Large page"],
        recommendations=["Add alt text"],
    )


def test_json_roundtrip(report):
    data = json.loads(to_json(report))
    assert data["url"] == "https://example.com"
    assert data["score"] == 72
    assert data["on_page"]["content"]["word_count"] == 350
    assert "links_arch" not in data and "_meta" in data


def test_json_keeps_unicode(report):
    assert "سلام" in to_json(report)


def test_to_dict_datetime_serialized(report):
    assert isinstance(to_dict(report)["crawl_date"], str)


def test_html_contains_sections(report):
    out = to_html(report)
    for s in ("<!DOCTYPE html>", "72", "Technical", "On-Page", "Local SEO",
              "Missing meta description", "Add alt text", "seo (12)"):
        assert s in out


def test_html_escapes_xss(report):
    out = to_html(report)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_html_blocks_javascript_href():
    out = to_html(AuditReport(url='javascript:alert(1)'))
    assert 'href="javascript' not in out


def test_html_error_report():
    out = to_html(AuditReport(url="https://x.com", status="error", error_message="timeout"))
    assert "Audit error" in out and "timeout" in out


def test_html_minimal_report_no_crash():
    assert "SEO Audit Report" in to_html(AuditReport(url="https://x.com"))


@pytest.mark.parametrize("name,fmt,check", [
    ("r.json", None, lambda t: json.loads(t)["url"]),
    ("r.html", None, lambda t: t.startswith("<!DOCTYPE")),
    ("r.htm", None, lambda t: t.startswith("<!DOCTYPE")),
    ("r.txt", "json", lambda t: json.loads(t)["url"]),
])
def test_save_report(tmp_path, report, name, fmt, check):
    p = save_report(report, tmp_path / "sub" / name, fmt)
    assert check(p.read_text(encoding="utf-8"))


def test_save_report_bad_format(tmp_path, report):
    with pytest.raises(ValueError):
        save_report(report, tmp_path / "r.pdf")
