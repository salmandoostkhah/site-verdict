"""
Report exporters for AuditReport (JSON / HTML).

Usage:
    from seo_core.reporters import to_json, to_html, save_report
    save_report(report, "out.html")          # format inferred from extension
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from seo_core.models import AuditReport

__all__ = ["to_dict", "to_json", "to_html", "save_report", "SUPPORTED_FORMATS"]

SUPPORTED_FORMATS = ("json", "html")


# ───────────────────────────── JSON ─────────────────────────────
def to_dict(report: AuditReport) -> dict:
    """JSON-safe dict (datetimes -> ISO strings). Drops the duplicated `links_arch` alias."""
    data = report.model_dump(mode="json")
    data.pop("links_arch", None)
    data["_meta"] = {
        "generator": "Site Verdict",
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
    return data


def to_json(report: AuditReport, indent: int = 2) -> str:
    return json.dumps(to_dict(report), ensure_ascii=False, indent=indent)


# ───────────────────────────── HTML ─────────────────────────────
def _e(v: Any) -> str:
    """Escape any value for HTML; None -> em dash."""
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "✅" if v else "❌"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return html.escape(str(v))


def _score_class(score: Optional[float]) -> str:
    if score is None:
        return "na"
    return "good" if score >= 80 else "warn" if score >= 50 else "bad"


def _rows(pairs: Iterable[tuple[str, Any]]) -> str:
    return "".join(f"<tr><th>{html.escape(k)}</th><td>{_e(v)}</td></tr>" for k, v in pairs)


def _section(title: str, pairs: Iterable[tuple[str, Any]]) -> str:
    body = _rows(pairs)
    if not body:
        return ""
    return f'<section><h2>{html.escape(title)}</h2><table>{body}</table></section>'


def _list_section(title: str, items: Iterable[Any], css: str) -> str:
    items = list(items or [])
    if not items:
        return ""
    lis = "".join(f"<li>{_e(i)}</li>" for i in items)
    return f'<section class="{css}"><h2>{html.escape(title)} ({len(items)})</h2><ul>{lis}</ul></section>'


def _g(obj: Any, attr: str, default: Any = None) -> Any:
    return getattr(obj, attr, default) if obj is not None else default


_CSS = """
body{font-family:Tahoma,Vazirmatn,system-ui,sans-serif;background:#f5f7fa;color:#222;margin:0;padding:24px}
.wrap{max-width:960px;margin:auto}
header{background:#1e293b;color:#fff;padding:20px 24px;border-radius:12px;display:flex;justify-content:space-between;align-items:center}
header a{color:#93c5fd;word-break:break-all}
.score{font-size:42px;font-weight:bold;border-radius:50%;width:96px;height:96px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.good{background:#16a34a}.warn{background:#d97706}.bad{background:#dc2626}.na{background:#64748b}
section{background:#fff;border-radius:12px;padding:16px 20px;margin-top:16px;box-shadow:0 1px 3px #0001}
h2{margin:0 0 10px;font-size:18px}
table{width:100%;border-collapse:collapse}
th,td{padding:6px 8px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}
th{width:40%;color:#555;font-weight:normal}
.issues li{color:#b91c1c}.warnings li{color:#b45309}.recs li{color:#1d4ed8}
.err{background:#fee2e2;color:#991b1b}
footer{color:#888;font-size:12px;text-align:center;margin-top:20px}
"""


def to_html(report: AuditReport) -> str:
    r = report
    tech, op = r.technical, r.on_page
    sec, assets = _g(tech, "security"), _g(tech, "assets")
    content, social = _g(op, "content"), _g(op, "social")
    links, loc, sm = r.links or r.links_arch, r.local_seo, r.sitemap
    url = _e(r.url)

    parts: list[str] = []

    if r.status == "error":
        parts.append(f'<section class="err"><h2>Audit error</h2><p>{_e(r.error_message)}</p></section>')

    parts.append(_section("Technical", [
        ("Status code", _g(tech, "status_code")),
        ("Response time (ms)", _g(tech, "response_time_ms")),
        ("Page size (KB)", _g(tech, "page_size_kb")),
        ("Compressed", _g(tech, "is_compressed")),
        ("Mobile ready (viewport)", _g(tech, "has_viewport")),
        ("Crawlable", _g(tech, "is_crawlable")),
        ("Noindex", _g(tech, "is_noindex")),
        ("Canonical", _g(tech, "canonical_url") or _g(tech, "has_canonical")),
        ("robots.txt", _g(tech, "has_robots_txt")),
        ("Redirects", _g(tech, "redirect_count")),
        ("Structured data", _g(tech, "has_schema")),
    ]))
    if sec is not None:
        parts.append(_section("Security", [
            ("HTTPS", _g(sec, "is_https")),
            ("HSTS", _g(sec, "hsts_enabled")),
            ("Security score", _g(sec, "security_score")),
        ]))
    if assets is not None:
        parts.append(_section("Assets", [
            ("Total requests", _g(assets, "total_requests")),
            ("Render-blocking JS", _g(assets, "render_blocking_js_count")),
        ]))

    parts.append(_section("On-Page", [
        ("Title", _g(op, "title")),
        ("Title length / status", f"{_g(op, 'title_length', 0)} / {_g(op, 'title_status', '—')}"),
        ("Meta description", _g(op, "meta_description")),
        ("Meta desc. length / status",
         f"{_g(op, 'meta_description_length', 0)} / {_g(op, 'meta_description_status', '—')}"),
        ("H1 / H2 / H3", f"{_g(op, 'h1_count', 0)} / {_g(op, 'h2_count', 0)} / {_g(op, 'h3_count', 0)}"),
        ("Images (missing alt)", f"{_g(op, 'total_images', 0)} ({_g(op, 'images_missing_alt', 0)})"),
    ]))
    if content is not None:
        kws = ", ".join(f"{k.get('word')} ({k.get('count')})" for k in (content.top_keywords or [])[:10])
        parts.append(_section("Content", [
            ("Word count", content.word_count),
            ("Reading time (min)", content.reading_time_minutes),
            ("Text ratio (%)", content.text_ratio_percent),
            ("Language", content.language_code or content.lang_declared),
            ("Top keywords", kws or None),
        ]))
    if social is not None:
        parts.append(_section("Social", [
            ("OpenGraph", social.has_og),
            ("Complete OG", social.has_complete_og),
            ("Twitter card", social.has_twitter_card),
        ]))
    if links is not None:
        parts.append(_section("Links", [
            ("Internal", _g(links, "internal_count")),
            ("External", _g(links, "external_count")),
            ("Nofollow", _g(links, "nofollow_count")),
            ("Broken", _g(links, "broken_links_count")),
        ]))
    if loc is not None:
        cl = loc.checklist or {}
        parts.append(_section("Local SEO", [
            ("Local schema", loc.has_local_schema),
            ("Phone", cl.get("has_phone")),
            ("Address", cl.get("has_address")),
            ("Email", cl.get("has_email")),
            ("Maps embed", loc.has_google_maps_embed),
            ("Local score", _g(loc, "local_score")),
        ]))
    if sm is not None:
        parts.append(_section("Sitemap", [
            ("Found", sm.has_sitemap),
            ("Valid XML", _g(sm, "is_valid_xml")),
            ("Total URLs", _g(sm, "total_urls")),
            ("Broken (404)", _g(sm, "broken_404_count")),
        ]))
    if r.broken_links:
        parts.append(_list_section(
            "Broken links",
            (f"{_g(b, 'url', b)} → {_g(b, 'status_code', '')}" for b in r.broken_links),
            "issues",
        ))

    parts.append(_list_section("Issues", r.issues, "issues"))
    parts.append(_list_section("Warnings", r.warnings, "warnings"))
    parts.append(_list_section("Recommendations", r.recommendations, "recs"))

    safe_href = str(r.url).lower().startswith(("http://", "https://"))
    link = f'<a href="{url}" rel="noopener noreferrer nofollow">{url}</a>' if safe_href else url
    crawl = r.crawl_date.strftime("%Y-%m-%d %H:%M UTC") if r.crawl_date else "—"
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SEO Audit – {url}</title><style>{_CSS}</style></head>
<body><div class="wrap">
<header><div><h1 style="margin:0 0 6px">SEO Audit Report</h1>
{link}<br>
<small>Crawled: {_e(crawl)} · Issues: {r.issues_count} · Warnings: {r.warnings_count}</small></div>
<div class="score {_score_class(r.score)}">{_e(r.score)}</div></header>
{''.join(p for p in parts if p)}
<footer>Generated by Site Verdict</footer>
</div></body></html>"""


# ───────────────────────────── Save ─────────────────────────────
def save_report(report: AuditReport, path: str | Path, fmt: Optional[str] = None) -> Path:
    """Write report to disk. `fmt` defaults to the file extension."""
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    if fmt == "htm":
        fmt = "html"
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported format '{fmt}'. Use one of: {', '.join(SUPPORTED_FORMATS)}")
    text = to_json(report) if fmt == "json" else to_html(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path