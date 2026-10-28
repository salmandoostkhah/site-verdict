#!/usr/bin/env python3
"""
Site Verdict CLI — aligned with models.py field names (all AttributeErrors fixed).
"""
import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import urlparse

from seo_core.engine import AuditEngine
from seo_core.formatting import to_fa_digits, to_latin_digits
from seo_core.reporters import SUPPORTED_FORMATS, save_report

_builtin_print = print


def _fa_line(text: str) -> str:
    """ارقام مقدار را فارسی می‌کند؛ برچسب قبل از اولین «:» دست‌نخورده می‌ماند (مثلاً «H1 Count»)."""
    label, sep, value = text.partition(":")
    if not sep:
        return to_fa_digits(text)
    return label + sep + to_fa_digits(value)


def print(*args, **kwargs) -> None:  # noqa: A001 - خروجی CLI همیشه ارقام فارسی دارد
    _builtin_print(*(_fa_line(a) if isinstance(a, str) else a for a in args), **kwargs)


def _raw(text: str) -> None:
    """چاپ بدون تبدیل ارقام؛ برای محتوای کاربر (عنوان، توضیحات، URL، مسیر فایل)."""
    _builtin_print(text)


def _validate_output_format(output: str | None, fmt: str | None) -> None:
    """Reject unsupported output formats BEFORE running the (slow) audit."""
    if not output:
        return
    resolved = (fmt or Path(output).suffix.lstrip(".")).lower()
    if resolved == "htm":
        resolved = "html"
    if resolved not in SUPPORTED_FORMATS:
        print(f"❌ Unsupported format '{resolved}'. Use one of: {', '.join(SUPPORTED_FORMATS)}")
        sys.exit(1)


def run_cli(url: str, output: str | None = None, fmt: str | None = None,
            local: bool | None = None) -> None:
    url = to_latin_digits(url).strip()
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        print(f"❌ Invalid URL: {url}")
        sys.exit(1)

    _validate_output_format(output, fmt)

    try:
        engine = AuditEngine(url, local_business=local)
        report = asyncio.run(engine.audit())
    except Exception as e:
        print(f"❌ Audit failed: {e}")
        sys.exit(1)

    if report.status == "error":
        print(f"❌ Audit error: {report.error_message}")
        sys.exit(1)

    print(f"\n{'='*50}")
    _raw(f"🔍 SEO Audit Report: {url}")
    print(f"{'='*50}")
    print(f"📊 Overall Score: {report.score}/100")

    # ── Technical ────────────────────────────────────────────────────────────
    if report.technical:
        tech = report.technical

        # response_time_ms is the canonical field; response_time is the alias
        rt = tech.response_time_ms if tech.response_time_ms is not None else tech.response_time

        # page_size_kb is the canonical field; fall back to byte-based calc
        size_kb = tech.page_size_kb
        if size_kb is None and tech.page_size:
            size_kb = tech.page_size / 1024

        # Mobile-friendliness: has_viewport and is_responsive are kept in sync
        # by the TechnicalMetrics validator — either one is authoritative.
        mobile_ready = tech.has_viewport or tech.is_responsive

        print("\n🔧 Technical:")
        print(f"  Response Time : {round(rt) if rt is not None else '—'} ms")
        print(f"  Page Size     : {f'{size_kb:.1f} KB' if size_kb is not None else '—'}")
        print(f"  Mobile Ready  : {mobile_ready}")
        print(f"  Crawlable     : {tech.is_crawlable}")
        print(f"  Canonical     : {tech.has_canonical}")
        print(f"  Noindex       : {tech.is_noindex}")

        if tech.security:
            sec = tech.security
            print(f"  HTTPS         : {sec.is_https}")
            print(f"  HSTS          : {sec.hsts_enabled}")
            print(f"  Security Score: {sec.security_score}")

        if tech.assets:
            ast = tech.assets
            print(f"  Render-block JS: {ast.render_blocking_js_count}")
            print(f"  Total Requests : {ast.total_requests}")

    # ── On-Page ──────────────────────────────────────────────────────────────
    if report.on_page:
        op = report.on_page

        # title is Optional[str] — no .value needed
        title = op.title or "—"

        # word_count lives inside on_page.content (ContentMetrics), not on OnPageMetrics
        word_count = op.content.word_count if op.content else None

        print("\n📄 On-Page:")
        _raw(f"  Title         : {title}")
        print(f"  Title Length  : {op.title_length}")
        print(f"  Title Status  : {op.title_status}")
        _raw(f"  Meta Desc     : {op.meta_description or '—'}")
        print(f"  Word Count    : {word_count if word_count is not None else '—'}")
        print(f"  H1 Count      : {op.h1_count}")
        print(f"  Images        : {op.total_images}  (missing alt: {op.images_missing_alt})")

        if op.content:
            cnt = op.content
            print(f"  Text Ratio    : {cnt.text_ratio_percent}%")
            print(f"  Reading Time  : {cnt.reading_time_minutes} min")
            print(f"  Language      : {cnt.language_code or '—'}")

        if op.social:
            soc = op.social
            print(f"  OG Tags       : {soc.has_og}")
            print(f"  Twitter Card  : {soc.has_twitter_card}")

    # ── Links ─────────────────────────────────────────────────────────────────
    links = report.links_arch or report.links
    if links:
        print("\n🔗 Links:")
        print(f"  Internal      : {links.internal_count}")
        print(f"  External      : {links.external_count}")
        print(f"  Nofollow      : {links.nofollow_count}")
        print(f"  Broken        : {links.broken_links_count}")
        unverifiable = getattr(links, "unverifiable_links", [])
        if unverifiable:
            print(f"  Unverifiable  : {len(unverifiable)} (external, probably bot-blocking)")
            for u in unverifiable:
                _raw(f"    ? {u}")

    # ── Local SEO ─────────────────────────────────────────────────────────────
    if report.local_seo:
        loc = report.local_seo

        # has_local_schema and has_nap_schema are model attributes
        local_schema = loc.has_local_schema or loc.has_nap_schema

        # has_phone / has_address live only as keys in loc.checklist dict
        checklist = loc.checklist or {}
        phone_found   = checklist.get("has_phone", False)
        address_found = checklist.get("has_address", False)
        email_found   = checklist.get("has_email", False)

        print("\n📍 Local SEO:")
        print(f"  Local Schema  : {local_schema}")
        print(f"  Phone Found   : {phone_found}")
        print(f"  Address Found : {address_found}")
        print(f"  Email Found   : {email_found}")
        print(f"  Maps Embed    : {loc.has_google_maps_embed}")
        print(f"  Geo Meta      : {loc.has_geo_meta}")
        print(f"  Local Score   : {loc.local_score}")

    # ── Sitemap ───────────────────────────────────────────────────────────────
    if report.sitemap:
        sm = report.sitemap
        print("\n🗺  Sitemap:")
        print(f"  Found         : {sm.has_sitemap}")
        print(f"  Valid XML     : {sm.is_valid_xml}")
        print(f"  Total URLs    : {sm.total_urls}")
        print(f"  Broken URLs   : {sm.broken_404_count}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n⚠️  Issues: {report.issues_count} | 💡 Warnings: {report.warnings_count}")
    for issue in report.issues:
        print(f"  ✖ {issue}")
    for warning in report.warnings:
        print(f"  ! {warning}")

    if report.recommendations:
        print("\n📝 Top Recommendations:")
        for rec in report.recommendations[:5]:
            print(f"  • {rec}")

    print(f"\n{'='*50}\n")

    if output:
        try:
            path = save_report(report, output, fmt)
        except (ValueError, OSError) as e:
            print(f"❌ Could not save report: {e}")
            sys.exit(1)
        _raw(f"💾 Report saved: {path}")


def _force_utf8_output() -> None:
    """Windows با خروجی pipe از cp1252 استفاده می‌کند و ایموجی‌ها را نمی‌تواند چاپ کند."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> None:
    _force_utf8_output()
    parser = argparse.ArgumentParser(prog="cli.py", description="Site Verdict CLI")
    parser.add_argument("url", help="URL to audit (http/https)")
    parser.add_argument("-o", "--output", help="save report to file (.json / .html)")
    parser.add_argument("-f", "--format", choices=SUPPORTED_FORMATS,
                        help="output format (default: inferred from --output extension)")
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--local", dest="local", action="store_const", const=True,
                     help="treat site as a local business (apply Local SEO scoring)")
    grp.add_argument("--non-local", dest="local", action="store_const", const=False,
                     help="treat site as NOT a local business (skip Local SEO scoring)")
    args = parser.parse_args(argv)
    run_cli(args.url, args.output, args.format, args.local)


if __name__ == "__main__":
    main()