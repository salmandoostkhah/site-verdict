"""Default analysis stages for the audit pipeline.

Each stage locates its analyzer through an injected ``resolve(name)`` callable,
so the engine (or tests) can supply/replace analyzers without import tricks.
Shared per-run data lives in ``ctx.extras``: ``response`` and ``redirect_hops``.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from seo_core.html_utils import parse_html
from seo_core.invoke import _get_callable, _invoke_analyzer
from seo_core.models import (
    AssetMetrics,
    BrokenLink,
    ImageAuditMetrics,
    LinkArchitectureMetrics,
    LocalSEOMetrics,
    OnPageMetrics,
    SitemapMetrics,
    TechnicalMetrics,
)
from seo_core.pipeline import (
    AuditContext,
    Stage,
    StageRegistry,
    StageResult,
    normalize_result,
)

logger = logging.getLogger("seo_core.stages")

Resolver = Callable[[str], Any]

ORDER_TECHNICAL = 10
ORDER_SITEMAP = 20
ORDER_ON_PAGE = 30
ORDER_IMAGES = 40
ORDER_LINKS = 50
ORDER_LOCAL = 60


def default_resolver(name: str) -> Any:
    """Import ``seo_core.analyzers.<name>``; return None if unavailable."""
    try:
        import importlib

        return importlib.import_module(f"seo_core.analyzers.{name}")
    except ImportError:
        return None


def _coerce(value: Any, cls: type) -> Any:
    if isinstance(value, cls):
        return value
    if isinstance(value, dict):
        return cls(**value)
    if value is not None:
        logger.warning("Unsupported %s metrics type: %s", cls.__name__, type(value).__name__)
    return None


def _extract_assets(html: str) -> AssetMetrics:
    try:
        soup = parse_html(html)
        css = [l for l in soup.find_all("link") if "stylesheet" in (l.get("rel") or [])]
        js = [s for s in soup.find_all("script") if s.get("src")]
        blocking = [
            s for s in js
            if not s.has_attr("async") and not s.has_attr("defer")
            and str(s.get("type", "")).lower() != "module"
        ]
        imgs = soup.find_all("img")
        head_blocking = sum(1 for s in blocking if s.find_parent("head") is not None)
        return AssetMetrics(
            total_css=len(css),
            total_js=len(js),
            total_requests=len(css) + len(js) + len(imgs),
            render_blocking_js_count=len(blocking),
            render_blocking_head_count=head_blocking,
            render_blocking_body_count=len(blocking) - head_blocking,
            css_files_count=len(css),
            js_files_count=len(js),
            total_images=len(imgs),
        )
    except Exception as err:  # boundary: asset extraction must never abort
        logger.warning("Asset extraction fallback error: %s", err)
        return AssetMetrics()


def _finalize_technical(ctx: AuditContext) -> None:
    """Guarantee report.technical exists and carries response-derived facts."""
    report = ctx.report
    response = ctx.extras.get("response")
    if response is None:
        return
    if report.technical is None:
        report.technical = TechnicalMetrics(status_code=getattr(response, "status_code", 200))
    tech = report.technical
    # AuditReport.technical has a non-None default, so fill timing/size whenever
    # the analyzer left them at zero (analyzer missing or failed).
    if not tech.response_time_ms:
        elapsed = getattr(response, "elapsed", None)
        if elapsed:
            tech.response_time_ms = elapsed.total_seconds() * 1000.0
    if not tech.page_size_kb:
        content = getattr(response, "content", None)
        if content:
            tech.page_size_kb = len(content) / 1024.0
    if tech.assets is None or tech.assets == AssetMetrics():
        tech.assets = _extract_assets(ctx.html)
    tech.redirect_count = ctx.extras.get("redirect_hops", 0)
    encoding = str(response.headers.get("Content-Encoding", "")).lower()
    tech.is_compressed = any(e in encoding for e in ("gzip", "br", "deflate", "zstd"))


def build_default_registry(resolve: Resolver = default_resolver) -> StageRegistry:
    """Create the standard six-stage registry."""
    registry = StageRegistry()

    async def technical(ctx: AuditContext) -> Optional[StageResult]:
        try:
            func = _get_callable(resolve("technical"), "analyze")
            if not func:
                return None
            raw = await _invoke_analyzer(
                func, ctx.url, client=ctx.client, response=ctx.extras.get("response")
            )
            res = normalize_result(raw)
            ctx.report.technical = _coerce(res.metrics, TechnicalMetrics)
            return StageResult(issues=res.issues, warnings=res.warnings, penalty=res.penalty)
        finally:
            _finalize_technical(ctx)

    async def sitemap(ctx: AuditContext) -> Optional[StageResult]:
        mod = resolve("sitemap")
        func = _get_callable(mod, "analyze_sitemap") or _get_callable(mod, "analyze")
        if not func:
            return None
        raw = await _invoke_analyzer(
            func, ctx.url, client=ctx.client, response=ctx.extras.get("response")
        )
        res = normalize_result(raw)
        ctx.report.sitemap = _coerce(res.metrics, SitemapMetrics)
        sm, tech = ctx.report.sitemap, ctx.report.technical
        if sm is not None and tech is not None:
            tech.has_robots = sm.has_robots_txt
            tech.has_robots_txt = sm.has_robots_txt
            tech.robots_txt_status = sm.robots_txt_status
            tech.has_sitemap = sm.has_sitemap
            tech.sitemap_urls_count = sm.total_urls
        return StageResult(issues=res.issues, warnings=res.warnings, penalty=res.penalty)

    async def on_page(ctx: AuditContext) -> Optional[StageResult]:
        mod = resolve("on_page")
        func = _get_callable(mod, "analyze")
        if func is None:
            if mod is not None:
                logger.warning("On-page analyzer has no callable entry point.")
            return None
        res = normalize_result(await _invoke_analyzer(func, ctx.html, url=ctx.url))
        ctx.report.on_page = _coerce(res.metrics, OnPageMetrics)
        return StageResult(issues=res.issues, warnings=res.warnings, penalty=res.penalty)

    async def images(ctx: AuditContext) -> Optional[StageResult]:
        mod = resolve("images")
        func = _get_callable(mod, "analyze")
        if func is None:
            if mod is not None:
                logger.warning("Images analyzer has no callable entry point.")
            return None
        res = normalize_result(await _invoke_analyzer(func, ctx.html, base_url=ctx.url))
        ctx.report.images_audit = _coerce(res.metrics, ImageAuditMetrics)
        return StageResult(issues=res.issues, warnings=res.warnings, penalty=res.penalty)

    async def links(ctx: AuditContext) -> Optional[StageResult]:
        mod = resolve("links")
        func = _get_callable(mod, "analyze_links") or _get_callable(mod, "analyze")
        if not func:
            return None
        raw = await _invoke_analyzer(func, ctx.html, base_url=ctx.url, client=ctx.client)
        broken_raw: list = []
        # links returns (metrics, broken_details), not the standard 4-tuple
        if isinstance(raw, tuple) and len(raw) == 2:
            broken_raw = list(raw[1] or [])
            raw = (raw[0],)
        res = normalize_result(raw)
        metrics = _coerce(res.metrics, LinkArchitectureMetrics)
        if metrics is not None:
            ctx.report.links = metrics
            ctx.report.links_arch = metrics
        warnings = list(res.warnings)
        if broken_raw:
            ctx.report.broken_links = [
                BrokenLink(**b) if isinstance(b, dict) else b for b in broken_raw
            ]
            warnings.append(f"{len(ctx.report.broken_links)} لینک خراب در صفحه شناسایی شد.")
        return StageResult(issues=res.issues, warnings=warnings, penalty=res.penalty)

    async def local_seo(ctx: AuditContext) -> Optional[StageResult]:
        mod = resolve("local_seo")
        func = _get_callable(mod, "analyze_local_seo") or _get_callable(mod, "analyze")
        if not func:
            return None
        res = normalize_result(await _invoke_analyzer(func, ctx.html, base_url=ctx.url))
        ctx.report.local_seo = _coerce(res.metrics, LocalSEOMetrics)

        is_local = ctx.local_business
        ls = ctx.report.local_seo
        if is_local is None and ls is not None:
            is_local = bool(
                ls.has_local_schema or ls.has_nap_schema or ls.has_geo_coordinates
                or ls.has_geo_meta or ls.has_google_maps_embed or ls.has_map_embed
            )
        if is_local is False:
            return StageResult(
                warnings=["Local SEO: سایت محلی تشخیص داده نشد؛ بخش Local SEO امتیازدهی نشد."]
            )
        return StageResult(issues=res.issues, warnings=res.warnings, penalty=res.penalty)

    registry.register(Stage("Technical", technical, order=ORDER_TECHNICAL))
    registry.register(Stage("Sitemap", sitemap, order=ORDER_SITEMAP))
    registry.register(Stage("On-page", on_page, order=ORDER_ON_PAGE))
    registry.register(Stage("Images", images, order=ORDER_IMAGES))
    registry.register(Stage("Links", links, order=ORDER_LINKS))
    registry.register(Stage("Local SEO", local_seo, order=ORDER_LOCAL))
    return registry