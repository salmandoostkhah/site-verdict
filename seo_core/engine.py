"""
Core Audit Engine for SEO Audit Dashboard.
Main orchestration module that coordinates all analyzers, computes scores,
and compiles the comprehensive audit report.
Hardened Architecture - Pydantic V2 Compatible.
"""

import logging
import socket
from typing import Any, Callable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from config.settings import settings

from seo_core.formatting import to_fa_digits
from seo_core.models import AuditReport
from seo_core.pipeline import AuditContext, run_stages
from seo_core.stages import build_default_registry

logger = logging.getLogger("seo_core.engine")

# --------------------------------------------------------------------------
# SSRF & Network Security Layer (Hardened Security)
# --------------------------------------------------------------------------
from seo_core.safe_http import (  # noqa: E402
    SSRFSecurityError,
    MAX_REDIRECTS,
    ResponseTooLargeError,
    bounded_request,
    is_safe_url,
    make_safe_transport,
)


async def _get_with_safe_redirects(
    client: httpx.AsyncClient, url: str
) -> Tuple[httpx.Response, int]:
    """
    دنبال کردن دستی ریدایرکت‌ها با اعتبارسنجی SSRF *قبل* از هر درخواست؛
    هیچ درخواستی به مقصد ناامن ارسال نمی‌شود.
    خروجی: (پاسخ نهایی، تعداد گام‌های ریدایرکت طی‌شده)
    """
    current = url
    for hops in range(MAX_REDIRECTS + 1):
        if not await is_safe_url(current):
            raise SSRFSecurityError(f"آدرس ناامن یا غیرمجاز در مسیر ریدایرکت: {current}")
        response = await bounded_request(client, "GET", current)
        location = response.headers.get("Location")
        if not (response.is_redirect and location):
            return response, hops
        current = urljoin(str(response.url), location)
    raise SSRFSecurityError(f"تعداد ریدایرکت‌ها بیش از حد مجاز ({MAX_REDIRECTS}) است: {url}")


# --------------------------------------------------------------------------
# توابع کمکی یکسان‌سازی خروجی و فراخوانی ایمن تحلیل‌گرها
# --------------------------------------------------------------------------
def _sanitize_list(items: List[Any]) -> List[str]:
    """تبدیل امن عناصر به متن و حذف مقادیر تکراری."""
    clean_list: List[str] = []
    seen = set()
    for item in items:
        if isinstance(item, dict):
            val = str(item.get("message") or item.get("issue") or item.get("text") or item)
        else:
            val = str(item).strip()
        val = to_fa_digits(val) if val else val
        if val and val not in seen:
            seen.add(val)
            clean_list.append(val)
    return clean_list


# --------------------------------------------------------------------------
# Main Engine Class
# --------------------------------------------------------------------------
class AuditEngine:
    """موتور پردازش ناهمگام و یکپارچه تحلیل سئو و گزارش‌گیری."""

    def __init__(
        self,
        url: str,
        local_business: Optional[bool] = None,
        resolver: Optional[Callable[[str], Any]] = None,
    ):
        # resolver(name) -> ماژول/تابع تحلیل‌گر؛ None = ایمپورت پیش‌فرض
        self.resolver = resolver
        # None = تشخیص خودکار؛ True/False = تعیین دستی کاربر
        self.local_business = local_business
        parsed = urlparse(url.strip())
        if not parsed.scheme:
            url = f"https://{url.strip()}"
        self.url = url.strip()
        self.parsed = urlparse(self.url)
        self.domain = self.parsed.netloc or ""
        self.client_timeout = 25.0

    async def audit(self) -> AuditReport:
        """اجرای چرخه کامل ممیزی سئو با تفکیک دقیق منابع و اعمال پچ‌ها."""
        report = AuditReport(
            url=self.url,
            status="pending",
            score=100,
        )

        score = 100
        all_issues: List[Any] = []
        all_warnings: List[Any] = []

        # ۱. اعتبارسنجی امنیتی اولیه URL
        try:
            if not await is_safe_url(self.url):
                report.status = "error"
                report.error_message = f"آدرس ارائه‌شده ناامن است یا دسترسی به آن مجاز نیست (SSRF Protection): {self.url}"
                report.score = 0
                return report
        except SSRFSecurityError as sec_err:
            report.status = "error"
            report.error_message = f"خطای مسدودسازی امنیتی SSRF: {sec_err}"
            report.score = 0
            return report

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Site-Verdict/0.1"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fa,en;q=0.9",
        }

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.client_timeout, connect=10.0),
                follow_redirects=False,
                headers=headers,
                verify=not settings.ALLOW_INSECURE_TLS,
                transport=make_safe_transport(verify=not settings.ALLOW_INSECURE_TLS),
                trust_env=False,
            ) as client:

                # دریافت صفحه اصلی
                # دریافت با اعتبارسنجی SSRF در هر گام ریدایرکت
                response, redirect_hops = await _get_with_safe_redirects(client, self.url)

                ctx = AuditContext(
                    url=self.url,
                    html=response.text or "",
                    client=client,
                    report=report,
                    local_business=self.local_business,
                    extras={"response": response, "redirect_hops": redirect_hops},
                )
                await run_stages((build_default_registry(self.resolver) if self.resolver else build_default_registry()), ctx)
                score = ctx.score
                all_issues = ctx.issues
                all_warnings = ctx.warnings

        except SSRFSecurityError as sec_err:
            logger.warning("SSRF block during fetch: %s", sec_err)
            report.status = "error"
            report.error_message = f"خطای مسدودسازی امنیتی SSRF: {sec_err}"
            report.score = 0
            return report
        except (httpx.RequestError, socket.error) as net_err:
            logger.error("Network or Transport Error: %s", net_err)
            report.status = "error"
            report.error_message = f"Network Communication Error: {net_err}"
            report.score = 0
            return report

        # ----------------------------------------------------------
        # تجمیع، پاکسازی و نهایی‌سازی گزارش
        # ----------------------------------------------------------
        report.score = max(0, min(100, int(score)))
        report.overall_score = report.score
        report.issues = _sanitize_list(all_issues)
        report.warnings = _sanitize_list(all_warnings)
        report.issues_count = len(report.issues)
        report.warnings_count = len(report.warnings)

        # تولید توصیه‌های هوشمند (Recommendations)
        recs: List[str] = []
        if report.score < 60:
            recs.append("بهینه‌سازی کلی ساختار فنی و محتوایی سایت در اولویت قرار گیرد.")
        if report.issues:
            recs.append(f"رفع {len(report.issues)} خطای بحرانی شناسایی‌شده در تحلیل سئو.")
        if report.warnings:
            recs.append(f"بررسی و اصلاح {len(report.warnings)} مورد هشدار برای بهبود رتبه سایت.")
        if not recs:
            recs.append("وضعیت فنی و سئوی درون‌صفحه‌ای بسیار مطلوب ارزیابی شد.")
        report.recommendations = recs

        report.status = "success"
        return report

    async def run_audit(self) -> AuditReport:
        """Alias متد audit جهت سازگاری با کدهای قبلی و فراخوانی در Streamlit."""
        return await self.audit()


# Aliases جهت سازگاری کامل به عقب (رفع ImportError در app.py)
SEOEngine = AuditEngine
SEOScraper = AuditEngine