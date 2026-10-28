from datetime import datetime

from seo_core.models import (
    AuditReport,
    ContentMetrics,
    LinkArchitectureMetrics,
    OnPageMetrics,
    SitemapMetrics,
    TechnicalMetrics,
)


def test_audit_report_defaults():
    r = AuditReport(url="https://example.com")
    assert r.status == "success"
    assert r.score == 100 and r.overall_score == 100
    assert r.issues == [] and r.warnings == [] and r.broken_links == []
    assert isinstance(r.technical, TechnicalMetrics)
    assert isinstance(r.on_page, OnPageMetrics)
    assert isinstance(r.crawl_date, datetime)
    assert r.links is None and r.sitemap is None


def test_score_sync_both_directions():
    assert AuditReport(url="u", overall_score=40).score == 40
    assert AuditReport(url="u", score=55).overall_score == 55


def test_links_and_links_arch_are_synced():
    la = LinkArchitectureMetrics(internal_count=3)
    r = AuditReport(url="u", links_arch=la)
    assert r.links is la and r.links_arch is la
    r2 = AuditReport(url="u", links=la)
    assert r2.links_arch is la


def test_sitemap_propagates_to_technical():
    r = AuditReport(url="u", sitemap=SitemapMetrics(has_sitemap=True, total_urls=12))
    assert r.technical.has_sitemap is True
    assert r.technical.sitemap_urls_count == 12


def test_link_counts_sync():
    m = LinkArchitectureMetrics(internal_links_count=4, external_count=2, nofollow_count=1)
    assert m.internal_count == 4
    assert m.external_links_count == 2
    assert m.nofollow_links_count == 1
    assert m.total_links == 6


def test_content_metrics_defaults():
    c = ContentMetrics()
    assert c.word_count == 0
    assert c.top_keywords == []


def test_report_json_serializable():
    data = AuditReport(url="https://example.com", score=70).model_dump(mode="json")
    assert data["score"] == 70
    assert isinstance(data["crawl_date"], str)
