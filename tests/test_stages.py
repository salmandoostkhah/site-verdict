import asyncio
import functools
from datetime import timedelta
from types import SimpleNamespace

from seo_core.models import (
    AuditReport,
    LinkArchitectureMetrics,
    LocalSEOMetrics,
    OnPageMetrics,
    SitemapMetrics,
    TechnicalMetrics,
)
from seo_core.pipeline import AuditContext, run_stages
from seo_core.stages import build_default_registry

HTML = (
    '<html><head><link rel="stylesheet" href="a.css">'
    '<script src="x.js"></script></head>'
    '<body><script src="y.js" defer></script><img src="i.png"></body></html>'
)


def run_async(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


def make_response(encoding=""):
    return SimpleNamespace(
        status_code=200,
        elapsed=timedelta(milliseconds=150),
        content=b"x" * 2048,
        headers={"Content-Encoding": encoding} if encoding else {},
    )


def make_ctx(local_business=None, encoding=""):
    ctx = AuditContext(
        url="https://example.com/",
        html=HTML,
        report=AuditReport(url="https://example.com/"),
        local_business=local_business,
    )
    ctx.extras["response"] = make_response(encoding)
    ctx.extras["redirect_hops"] = 2
    return ctx


def make_resolver(**analyzers):
    return lambda name: analyzers.get(name)


@run_async
async def test_registry_order_and_names():
    reg = build_default_registry(make_resolver())
    assert [s.name for s in reg.ordered()] == [
        "Technical", "Sitemap", "On-page", "Images", "Links", "Local SEO",
    ]


@run_async
async def test_missing_analyzers_still_build_technical_defaults():
    ctx = make_ctx(encoding="gzip")
    await run_stages(build_default_registry(make_resolver()), ctx)
    tech = ctx.report.technical
    assert tech is not None
    assert tech.status_code == 200
    assert round(tech.response_time_ms) == 150
    assert tech.page_size_kb == 2.0
    assert tech.redirect_count == 2
    assert tech.is_compressed is True
    assert tech.assets.total_css == 1
    assert tech.assets.total_js == 2
    assert tech.assets.total_images == 1
    assert tech.assets.render_blocking_js_count == 1
    assert tech.assets.render_blocking_head_count == 1
    assert ctx.score == 100
    assert ctx.report.failed_analyzers == []


@run_async
async def test_technical_failure_still_finalizes_and_penalizes():
    def boom(url):
        raise RuntimeError("bad")

    ctx = make_ctx()
    await run_stages(build_default_registry(make_resolver(technical=boom)), ctx)
    assert ctx.report.technical is not None
    assert ctx.report.technical.redirect_count == 2
    assert ctx.report.failed_analyzers == ["Technical"]
    assert ctx.score == 70  # failure penalty 10, then cap 70 applies


@run_async
async def test_technical_dict_metrics_coerced_and_penalty_applied():
    def tech(url):
        return ({"status_code": 200, "has_sitemap": False}, ["i"], ["w"], 5)

    ctx = make_ctx()
    await run_stages(build_default_registry(make_resolver(technical=tech)), ctx)
    assert isinstance(ctx.report.technical, TechnicalMetrics)
    assert ctx.issues == ["i"]
    assert ctx.warnings == ["w"]
    assert ctx.score == 95


@run_async
async def test_sitemap_updates_technical_fields():
    async def sitemap(url):
        return SitemapMetrics(
            has_robots_txt=True, robots_txt_status=200,
            has_sitemap=True, total_urls=42,
        )

    ctx = make_ctx()
    await run_stages(build_default_registry(make_resolver(sitemap=sitemap)), ctx)
    tech = ctx.report.technical
    assert tech.has_robots_txt is True
    assert tech.robots_txt_status == 200
    assert tech.has_sitemap is True
    assert tech.sitemap_urls_count == 42


@run_async
async def test_on_page_metrics_issues_and_penalty():
    def on_page(html):
        return (OnPageMetrics(), ["no title"], ["short"], 8)

    ctx = make_ctx()
    await run_stages(build_default_registry(make_resolver(on_page=on_page)), ctx)
    assert isinstance(ctx.report.on_page, OnPageMetrics)
    assert "no title" in ctx.issues
    assert ctx.score == 92


@run_async
async def test_links_two_tuple_sets_broken_links_and_warning():
    async def links(html, base_url=None, client=None):
        return (
            LinkArchitectureMetrics(internal_count=3, external_count=1),
            [{"url": "https://example.com/404", "status_code": 404}],
        )

    ctx = make_ctx()
    await run_stages(build_default_registry(make_resolver(links=links)), ctx)
    assert ctx.report.links.internal_count == 3
    assert ctx.report.links_arch is ctx.report.links
    assert len(ctx.report.broken_links) == 1
    assert ctx.report.broken_links[0].status_code == 404
    assert any("لینک خراب" in w for w in ctx.warnings)


def _local(html, base_url=None):
    return (LocalSEOMetrics(), ["local issue"], ["local warn"], 6)


@run_async
async def test_local_explicit_false_skips_scoring():
    ctx = make_ctx(local_business=False)
    await run_stages(build_default_registry(make_resolver(local_seo=_local)), ctx)
    assert "local issue" not in ctx.issues
    assert ctx.score == 100
    assert any("Local SEO" in w for w in ctx.warnings)


@run_async
async def test_local_auto_detect_negative_skips_scoring():
    ctx = make_ctx(local_business=None)
    await run_stages(build_default_registry(make_resolver(local_seo=_local)), ctx)
    assert "local issue" not in ctx.issues
    assert ctx.score == 100


@run_async
async def test_local_true_scores():
    ctx = make_ctx(local_business=True)
    await run_stages(build_default_registry(make_resolver(local_seo=_local)), ctx)
    assert "local issue" in ctx.issues
    assert "local warn" in ctx.warnings
    assert ctx.score == 94


@run_async
async def test_one_failing_stage_does_not_stop_others():
    def on_page(html):
        raise ValueError("x")

    def images(html, base_url=None):
        return (None, ["img issue"], [], 3)

    ctx = make_ctx()
    resolver = make_resolver(on_page=on_page, images=images)
    await run_stages(build_default_registry(resolver), ctx)
    assert ctx.report.failed_analyzers == ["On-page"]
    assert "img issue" in ctx.issues