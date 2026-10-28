"""
Technical SEO Analyzer – Hardened Enterprise Edition
رفع قطعی باگ‌های شمارش تگ‌ها و حذف خطاهای Proactor سوکت در ویندوز (Python 3.14).
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from seo_core.html_utils import parse_html

from seo_core.models import AssetMetrics, SecurityMetrics, TechnicalMetrics

logger = logging.getLogger(__name__)


def _extract_safe_url_and_root(raw_url: Any, response: Optional[httpx.Response] = None) -> Tuple[str, str]:
    """استخراج امن URL و ریشه وب‌سایت با پشتیبانی کامل از انواع ورودی‌ها."""
    url_str = ""
    if raw_url is not None:
        if hasattr(raw_url, "host"):
            url_str = str(raw_url)
        else:
            url_str = str(raw_url).strip()

    if not url_str and response is not None and getattr(response, "url", None):
        url_str = str(response.url).strip()

    root_base = ""
    if url_str:
        try:
            parsed = urlparse(url_str)
            if parsed.scheme and parsed.netloc:
                root_base = f"{parsed.scheme}://{parsed.netloc}"
        except ValueError:
            root_base = ""

    return url_str, root_base


async def analyze(
    url: Any,
    response: Optional[httpx.Response] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[TechnicalMetrics, List[str], List[str], int]:
    """
    آنالیز فنی وب‌سایت، هدرهای امنیتی، ریسپانسیو و منابع خارجی استاتیک.
    """
    # مدیریت جابه‌جایی احتمالی آرگومان‌ها
    if isinstance(url, httpx.Response) and response is None:
        response = url
        url = str(response.url)

    url_str, root_base = _extract_safe_url_and_root(url, response)

    issues: List[str] = []
    warnings: List[str] = []
    penalty: int = 0

    if response is None:
        warnings.append("پاسخ HTTP معتبری برای آنالیز فنی دریافت نشد.")
        return TechnicalMetrics(), issues, warnings, 20

    raw_html = response.text or ""
    soup = parse_html(raw_html)
    headers = {k.lower(): v for k, v in response.headers.items()}
    is_https = url_str.lower().startswith("https://") or str(response.url).lower().startswith("https://")

    # ۱. بررسی هدرهای امنیتی
    has_hsts = "strict-transport-security" in headers if is_https else False
    if is_https and not has_hsts:
        warnings.append("هدر امنیتی HSTS (Strict-Transport-Security) فعال نیست.")
        penalty += 3

    has_x_frame = "x-frame-options" in headers or "frame-ancestors" in headers.get("content-security-policy", "")
    if not has_x_frame:
        warnings.append("محافظت در برابر کلیک‌جکینگ (X-Frame-Options یا CSP) یافت نشد.")
        penalty += 2

    has_csp = "content-security-policy" in headers
    if not has_csp:
        warnings.append("سیاست امنیت محتوا (Content-Security-Policy) تعریف نشده است.")
        penalty += 2

    has_x_content_type = "nosniff" in headers.get("x-content-type-options", "").lower()

    # ۲. استخراج و بررسی Mixed Content در HTTPS
    mixed_content_urls: List[str] = []
    if is_https:
        for tag in soup.find_all(["img", "script", "link", "iframe"]):
            src = tag.get("src") or tag.get("href") or ""
            if isinstance(src, str) and src.lower().startswith("http://"):
                mixed_content_urls.append(src)
        if mixed_content_urls:
            issues.append(f"تعداد {len(mixed_content_urls)} منبع با پروتکل ناامن HTTP (Mixed Content) یافت شد.")
            penalty += min(len(mixed_content_urls) * 2, 10)

    security_obj = SecurityMetrics(
        is_https=is_https,
        hsts_enabled=has_hsts,
        has_hsts=has_hsts,
        has_csp=has_csp,
        has_x_frame_options=has_x_frame,
        has_x_content_type_options=has_x_content_type,
        mixed_content_urls=mixed_content_urls,
        mixed_content_count=len(mixed_content_urls),
    )

    # ۳. استخراج قطعی و بدون خطای فایل‌های استاتیک (CSS, JS, Images, Render-Blocking)
    # الف) CSS: بررسی انعطاف‌پذیر rel در تگ‌های link
    css_files: List[str] = []
    for link in soup.find_all("link"):
        rel = link.get("rel", [])
        if isinstance(rel, list):
            rel_str = " ".join(rel).lower()
        else:
            rel_str = str(rel).lower()
        if "stylesheet" in rel_str:
            href = link.get("href")
            if href:
                css_files.append(str(href))
    css_count = len(css_files)

    # ب) JS: کلیه اسکریپت‌های دارای src
    js_files: List[str] = []
    render_blocking_scripts: List[str] = []
    head_blocking = 0
    body_blocking = 0
    for s in soup.find_all("script"):
        src = s.get("src")
        if src:
            src_str = str(src).strip()
            js_files.append(src_str)
            # بررسی وضعیت render-blocking
            is_async = s.has_attr("async")
            is_defer = s.has_attr("defer")
            is_module = s.get("type", "").lower() == "module"
            if not is_async and not is_defer and not is_module:
                render_blocking_scripts.append(src_str)
                if s.find_parent("head") is not None:
                    head_blocking += 1
                else:
                    body_blocking += 1

    js_count = len(js_files)
    render_blocking_count = len(render_blocking_scripts)

    if render_blocking_count > 3:
        warnings.append(f"{render_blocking_count} اسکریپت مسدودکننده رندر بدون صفات async یا defer یافت شد.")
        penalty += min((render_blocking_count - 3), 5)

    # ج) تصاویر و مجموع درخواست‌ها
    img_tags = soup.find_all("img")
    images_count = len(img_tags)
    total_assets = css_count + js_count + images_count

    assets_obj = AssetMetrics(
        total_css=css_count,
        total_js=js_count,
        total_requests=total_assets,
        render_blocking_js_count=render_blocking_count,
        render_blocking_head_count=head_blocking,
        render_blocking_body_count=body_blocking,
        css_files_count=css_count,
        js_files_count=js_count,
        total_images=images_count,
        total_images_count=images_count,
        render_blocking_scripts=render_blocking_scripts,
    )

    # ۴. زمان پاسخ، حجم صفحه و بررسی‌های ساختاری
    page_size_kb = len(response.content) / 1024.0 if getattr(response, "content", None) else 0.0
    try:
        elapsed = getattr(response, "elapsed", None)
    except RuntimeError:
        # httpx فقط پس از بسته شدن پاسخ elapsed را مقداردهی می‌کند
        elapsed = None
    response_time_ms = (elapsed.total_seconds() * 1000.0) if elapsed else 0.0

    if response_time_ms > 2000:
        issues.append(f"زمان پاسخ سرور بسیار کند است: {response_time_ms:.0f} میلی‌ثانیه.")
        penalty += 10
    elif response_time_ms > 800:
        warnings.append(f"زمان پاسخ سرور کمی بالا است: {response_time_ms:.0f} میلی‌ثانیه.")
        penalty += 4

    # ۵. متاتگ Robots
    # هم متاتگ robots/googlebot و هم هدر X-Robots-Tag؛ مقدار none معادل noindex,nofollow است
    robots_directives: List[str] = []
    for meta in soup.find_all("meta", attrs={"name": lambda x: x and str(x).strip().lower() in ("robots", "googlebot")}):
        robots_directives.append(str(meta.get("content", "")))
    headers = getattr(response, "headers", None) or {}
    try:
        robots_directives.extend(headers.get_list("x-robots-tag"))
    except AttributeError:
        header_val = headers.get("X-Robots-Tag") or headers.get("x-robots-tag")
        if header_val:
            robots_directives.append(str(header_val))
    tokens = set()
    for directive in robots_directives:
        for part in directive.lower().split(","):
            part = part.strip()
            # فرم «useragent: noindex» در هدر
            if ":" in part:
                part = part.split(":", 1)[1].strip()
            if part:
                tokens.add(part)
    is_noindex = bool(tokens & {"noindex", "none"})
    if is_noindex:
        issues.append("صفحه دارای تگ noindex است و در موتورهای جستجو ایندکس نخواهد شد.")
        penalty += 25

    # ۶. تگ کنونیکال
    canonical_tag = soup.find("link", rel=lambda r: r and "canonical" in (r if isinstance(r, list) else [str(r)]))
    canonical_url = canonical_tag.get("href") if canonical_tag else None
    if not canonical_url:
        warnings.append("تگ کنونیکال (Canonical URL) در صفحه تعریف نشده است.")
        penalty += 3

    # ۷. متاتگ Viewport
    viewport_meta = soup.find("meta", attrs={"name": lambda x: x and str(x).lower() == "viewport"})
    has_viewport = bool(viewport_meta and viewport_meta.get("content"))
    if not has_viewport:
        issues.append("متاتگ viewport برای نمایش صحیح در موبایل یافت نشد.")
        penalty += 15

    # ۸. نشانه‌گذاری ساختاریافته (Schema / JSON-LD)
    schemas = soup.find_all("script", type="application/ld+json")
    has_schema = len(schemas) > 0
    if not has_schema:
        warnings.append("هیچ ساختار داده نشانه‌گذاری (JSON-LD Schema) در صفحه یافت نشد.")
        penalty += 3

    # ۹. وضعیت robots.txt و Sitemap اینجا بررسی نمی‌شود؛
    # مقدار واقعی را موتور از خروجی sitemap.py در TechnicalMetrics قرار می‌دهد.

    # ۱۰. ساخت مدل نهایی TechnicalMetrics هماهنگ با Pydantic V2
    metrics = TechnicalMetrics(
        status_code=int(response.status_code),
        response_time=float(response_time_ms),
        response_time_ms=float(response_time_ms),
        page_size=float(page_size_kb),
        page_size_kb=float(page_size_kb),
        has_viewport=bool(has_viewport),
        is_responsive=bool(has_viewport),
        has_schema=bool(has_schema),
        has_canonical=bool(canonical_url),
        canonical_url=str(canonical_url) if canonical_url else None,
        is_noindex=bool(is_noindex),
        security=security_obj,
        assets=assets_obj,
    )

    return metrics, issues, warnings, penalty


class TechnicalAnalyzer:
    analyze = staticmethod(analyze)