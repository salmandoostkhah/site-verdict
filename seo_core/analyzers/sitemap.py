"""
Sitemap and 404 Broken Link Analyzer.
Hardened with SSRF protection, Async DNS validation, and Pydantic V2 compatibility.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from config.settings import settings
from seo_core.models import SitemapItem, SitemapMetrics
from seo_core.safe_http import MAX_REDIRECTS, bounded_request, is_safe_url

logger = logging.getLogger(__name__)

# محدودیت تعداد درخواست‌های همزمان برای جلوگیری از فشار روی سرور مقصد
CONCURRENT_LIMIT = settings.MAX_CONCURRENT_SITEMAP_CHECKS
# حداکثر تعداد آدرس‌هایی که از سایت‌مپ برای بررسی وضعیت ۴۰۴ اسکن می‌شوند
DEFAULT_MAX_URLS_TO_CHECK = settings.MAX_SITEMAP_URLS_TO_CHECK
# حداکثر تعداد ریدایرکت مجاز هنگام دریافت robots.txt و sitemap
MAX_REDIRECTS = 5


async def _safe_get(client: httpx.AsyncClient, url: str, timeout: float) -> Optional[httpx.Response]:
    """
    دریافت GET با دنبال کردن دستی ریدایرکت‌ها و بررسی SSRF قبل از هر گام.
    در صورت مقصد ناامن یا ریدایرکت بیش از حد None برمی‌گرداند.
    """
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if not await is_safe_url(current):
            logger.debug("Blocked unsafe sitemap/robots target: %s", current)
            return None
        resp = await bounded_request(client, "GET", current, timeout=timeout)
        location = resp.headers.get("Location")
        if not (resp.is_redirect and location):
            return resp
        current = urljoin(str(resp.url), location)
    logger.debug("Too many redirects for %s", url)
    return None


def _normalize_url(url: str, base_url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return urljoin(base_url, url)
    return url


def _extract_sitemaps_from_robots(robots_text: str, base_url: str) -> List[str]:
    """استخراج آدرس‌های نقشه سایت که در robots.txt ثبت شده‌اند"""
    sitemaps = []
    for line in robots_text.splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                sitemap_url = parts[1].strip()
                if sitemap_url:
                    sitemaps.append(_normalize_url(sitemap_url, base_url))
    return sitemaps


async def _check_single_url(
    client: httpx.AsyncClient,
    url: str,
    semaphore: asyncio.Semaphore,
) -> SitemapItem:
    """بررسی کد وضعیت HTTP یک URL با هندلینگ خطا و شناسایی ۴۰۴ یا ریدایرکت به همراه گارد SSRF"""
    async with semaphore:
        # لایه امنیتی ۱: بررسی SSRF قبل از ارسال هرگونه ریکوئست
        if not await is_safe_url(url):
            return SitemapItem(
                url=url,
                status_code=None,
                status="unsafe_blocked",
            )

        try:
            # ابتدا با HEAD تست می‌کنیم تا پهنای باند بیهوده مصرف نشود
            resp = await bounded_request(client, "HEAD", url, timeout=6.0, read_body=False)
            if resp.status_code in (405, 501):
                # در صورت عدم پشتیبانی سرور از HEAD، فال‌بک به GET
                resp = await bounded_request(client, "GET", url, timeout=6.0, read_body=False)

            status_code = resp.status_code
            status_type = "ok"

            if 200 <= status_code < 300:
                status_type = "ok"
            elif 300 <= status_code < 400:
                status_type = "redirect"
            elif status_code == 404:
                status_type = "broken_404"
            elif 400 <= status_code < 500:
                status_type = "broken_other"
            elif status_code >= 500:
                status_type = "server_error"

            return SitemapItem(
                url=url,
                status_code=status_code,
                status=status_type,
            )
        except httpx.TimeoutException:
            return SitemapItem(url=url, status_code=None, status="timeout")
        except Exception:
            return SitemapItem(url=url, status_code=None, status="error")


async def analyze_sitemap(
    base_url: str,
    client: httpx.AsyncClient,
    max_urls_to_check: int = DEFAULT_MAX_URLS_TO_CHECK,
) -> Tuple[SitemapMetrics, List[str], List[str], int]:
    """
    بررسی کامل نقشه سایت و تست سلامت لینک‌های آن با رعایت کامل اصول امنیتی Hardened.
    خروجی: (metrics, issues, warnings, penalty)
    """
    issues: List[str] = []
    warnings: List[str] = []
    penalty: int = 0

    parsed_root = urlparse(base_url)
    root_origin = f"{parsed_root.scheme}://{parsed_root.netloc}"

    candidates = [
        f"{root_origin}/sitemap.xml",
        f"{root_origin}/sitemap_index.xml",
        f"{root_origin}/sitemap/sitemap.xml",
    ]

    # ۱. بررسی robots.txt برای کشف آدرس نقشه
    robots_url = f"{root_origin}/robots.txt"
    robots_status: Optional[int] = None
    try:
        robots_resp = await _safe_get(client, robots_url, timeout=5.0)
        if robots_resp is not None:
            robots_status = robots_resp.status_code
            if robots_resp.status_code == 200:
                found_in_robots = _extract_sitemaps_from_robots(robots_resp.text, root_origin)
                candidates = found_in_robots + [c for c in candidates if c not in found_in_robots]
    except Exception:
        pass

    has_robots_txt = robots_status == 200
    if not has_robots_txt:
        warnings.append("فایل robots.txt برای وب‌سایت یافت نشد.")
        penalty += 3

    target_sitemap_url: Optional[str] = None
    sitemap_content: Optional[str] = None

    for candidate_url in candidates:
        try:
            resp = await _safe_get(client, candidate_url, timeout=8.0)
            if resp is None:
                continue
            if resp.status_code == 200 and ("xml" in resp.headers.get("content-type", "").lower() or resp.text.strip().startswith("<?xml")):
                target_sitemap_url = str(resp.url)
                sitemap_content = resp.text
                break
        except Exception:
            continue

    if not target_sitemap_url or not sitemap_content:
        warnings.append("نقشه سایت (sitemap.xml) برای وب‌سایت یافت نشد.")
        return SitemapMetrics(
            has_robots_txt=has_robots_txt,
            robots_txt_status=robots_status,
            has_sitemap=False,
        ), issues, warnings, penalty + 5

    # ۲. پارس کردن XML نقشه سایت
    urls_found: List[str] = []
    is_index = False
    try:
        root_element = ET.fromstring(sitemap_content)
        tag = root_element.tag.lower()

        if "sitemapindex" in tag:
            is_index = True
            for loc in root_element.findall(".//{*}loc"):
                if loc.text:
                    urls_found.append(loc.text.strip())
        else:
            for loc in root_element.findall(".//{*}loc"):
                if loc.text:
                    urls_found.append(loc.text.strip())
    except ET.ParseError:
        issues.append(f"فرمت فایل نقشه سایت در آدرس {target_sitemap_url} معتبر نیست (خطای سینتکس XML).")
        return SitemapMetrics(
            has_robots_txt=has_robots_txt,
            robots_txt_status=robots_status,
            has_sitemap=True,
            sitemap_url=target_sitemap_url,
            is_valid_xml=False,
        ), issues, warnings, penalty + 7

    total_urls = len(urls_found)
    subset_to_check = urls_found[:max_urls_to_check]

    # ۳. بررسی وضعیت HTTP آدرس‌ها به‌صورت موازی با Semaphore و محافظت SSRF
    semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
    tasks = [_check_single_url(client, u, semaphore) for u in subset_to_check]
    results: List[SitemapItem] = await asyncio.gather(*tasks)

    # ۴. تجمیع و تحلیل آمار
    ok_count = 0
    broken_404_count = 0
    redirect_count = 0
    server_error_count = 0
    broken_urls = []
    redirect_urls = []

    for item in results:
        if item.status == "ok":
            ok_count += 1
        elif item.status == "broken_404":
            broken_404_count += 1
            broken_urls.append(item.url)
        elif item.status == "redirect":
            redirect_count += 1
            redirect_urls.append(item.url)
        elif item.status == "server_error":
            server_error_count += 1
        elif item.status == "unsafe_blocked":
            warnings.append(f"لینک مشکوک و ناامن شبکه داخلی در نقشه سایت مسدود شد: {item.url}")

    # ۵. ارزیابی جرایم سئو
    if broken_404_count > 0:
        issues.append(f"{broken_404_count} لینک خراب (خطای ۴۰۴) در نقشه سایت شناسایی شد!")
        penalty += min(20, broken_404_count * 5)

    if redirect_count > 0:
        warnings.append(f"{redirect_count} لینک ریدایرکت‌شده در نقشه سایت یافت شد (نقشه سایت باید فقط شامل URLهای نهایی ۲۰۰ باشد).")
        penalty += min(8, redirect_count * 2)

    metrics = SitemapMetrics(
        has_robots_txt=has_robots_txt,
        robots_txt_status=robots_status,
        has_sitemap=True,
        sitemap_url=target_sitemap_url,
        is_valid_xml=True,
        is_sitemap_index=is_index,
        total_urls=total_urls,
        checked_urls_count=len(results),
        ok_count=ok_count,
        broken_404_count=broken_404_count,
        redirect_count=redirect_count,
        server_error_count=server_error_count,
        broken_urls=broken_urls,
        redirect_urls=redirect_urls,
        items=results,
    )

    return metrics, issues, warnings, penalty