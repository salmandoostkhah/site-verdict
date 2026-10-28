"""
Core Audit Engine for SEO Audit Dashboard.
Main orchestration module that coordinates all analyzers, computes scores,
and compiles the comprehensive audit report.
Hardened Architecture - Pydantic V2 Compatible.
"""

import asyncio
import inspect
import logging
import socket
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from config.settings import settings

from seo_core.formatting import to_fa_digits
from seo_core.html_utils import parse_html
from seo_core.models import (
    AssetMetrics,
    AuditReport,
    BrokenLink,
    ImageAuditMetrics,
    LinkArchitectureMetrics,
    LocalSEOMetrics,
    OnPageMetrics,
    SitemapMetrics,
    TechnicalMetrics,
)

logger = logging.getLogger("seo_core.engine")

# --------------------------------------------------------------------------
# Safe dynamic import of analyzers
# --------------------------------------------------------------------------
try:
    from seo_core.analyzers import technical as analyze_technical
except ImportError:
    try:
        from seo_core.analyzers.technical import analyze as analyze_technical
    except ImportError:
        analyze_technical = None

try:
    from seo_core.analyzers import sitemap as analyze_sitemap
except ImportError:
    try:
        from seo_core.analyzers.sitemap import analyze as analyze_sitemap
    except ImportError:
        analyze_sitemap = None

try:
    from seo_core.analyzers import on_page as analyze_on_page
except ImportError:
    try:
        from seo_core.analyzers.on_page import analyze as analyze_on_page
    except ImportError:
        analyze_on_page = None

try:
    from seo_core.analyzers import images as analyze_images
except ImportError:
    try:
        from seo_core.analyzers.images import analyze as analyze_images
    except ImportError:
        analyze_images = None

try:
    from seo_core.analyzers import links as analyze_links
except ImportError:
    try:
        from seo_core.analyzers.links import analyze as analyze_links
    except ImportError:
        analyze_links = None

try:
    from seo_core.analyzers import local_seo as analyze_local_seo
except ImportError:
    try:
        from seo_core.analyzers.local_seo import analyze as analyze_local_seo
    except ImportError:
        analyze_local_seo = None


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
def _get_callable(obj: Any, default_attr: str = "analyze") -> Optional[Any]:
    """استخراج تابع اجرایی در صورت ایمپورت شدن ماژول."""
    if obj is None:
        return None
    if callable(obj) and not hasattr(obj, "__file__"):
        return obj
    if hasattr(obj, default_attr) and callable(getattr(obj, default_attr)):
        return getattr(obj, default_attr)
    if hasattr(obj, f"analyze_{default_attr}") and callable(getattr(obj, f"analyze_{default_attr}")):
        return getattr(obj, f"analyze_{default_attr}")
    return obj if callable(obj) else None


def _filter_supported_kwargs(func: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """فیلتر هوشمند آرگومان‌ها متناسب با امضای دقیق تابع."""
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return {}

    parameters = signature.parameters

    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        return dict(kwargs)

    return {
        key: value
        for key, value in kwargs.items()
        if key in parameters
        and parameters[key].kind
        in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }


async def _invoke_analyzer(
    func: Any,
    *args: Any,
    **optional_kwargs: Any,
) -> Any:
    """اجرای ناهمگام و ایزوله تحلیل‌گرها بدون مسدودسازی Event Loop."""
    kwargs = _filter_supported_kwargs(func, optional_kwargs)

    if inspect.iscoroutinefunction(func):
        return await func(*args, **kwargs)

    result = await asyncio.to_thread(func, *args, **kwargs)
    if inspect.isawaitable(result):
        return await result

    return result


ANALYZER_FAILURE_PENALTY = 10
# سقف نمره وقتی حداقل یک تحلیل‌گر شکست خورده: گزارش ناقص نباید نمرهٔ کامل بگیرد
INCOMPLETE_AUDIT_SCORE_CAP = 70


def _record_analyzer_failure(report, issues: List[Any], name: str, err: Exception) -> int:
    """ثبت شکست یک تحلیل‌گر در گزارش و برگرداندن جریمهٔ نمره.

    شکست تحلیل‌گر یعنی بخشی از صفحه بررسی نشده؛ نباید نمره را بی‌صدا بالا نگه دارد.
    """
    logger.warning("%s analysis error: %s", name, err, exc_info=True)
    report.failed_analyzers.append(name)
    issues.append(f"تحلیل «{name}» با خطا متوقف شد و بررسی ناقص ماند ({type(err).__name__}).")
    return ANALYZER_FAILURE_PENALTY


def _split(res: Any) -> Tuple[Any, List[Any], List[Any], int]:
    """یونیفایر خروجی تحلیل‌گرها به ۴ مقدار (metrics, issues, warnings, penalty)."""
    if res is None:
        return None, [], [], 0

    if not isinstance(res, tuple):
        return res, [], [], 0

    metrics = res[0] if len(res) >= 1 else None
    issues = list(res[1] or []) if len(res) >= 2 else []
    warnings = list(res[2] or []) if len(res) >= 3 else []

    try:
        penalty = max(0, int(res[3] or 0)) if len(res) >= 4 else 0
    except (TypeError, ValueError):
        logger.warning("Invalid analyzer penalty ignored: %r", res[3])
        penalty = 0

    return metrics, issues, warnings, penalty


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

    def __init__(self, url: str, local_business: Optional[bool] = None):
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

                html_content = response.text or ""

                # ----------------------------------------------------------
                # تحلیل تکنیکال (Technical Analysis) - پچ قطعی استخراج دارایی‌ها
                # ----------------------------------------------------------
                # ۱. استخراج مستقل دارایی‌ها مستقیم از HTML بدون ریسک خطا
                try:
                    soup_tech = parse_html(html_content)
                    css_tags = [
                        link for link in soup_tech.find_all("link")
                        if "stylesheet" in (link.get("rel") or [])
                    ]
                    js_tags = [s for s in soup_tech.find_all("script") if s.get("src")]
                    blocking_scripts = [
                        s for s in js_tags
                        if not s.has_attr("async") and not s.has_attr("defer")
                        and str(s.get("type", "")).lower() != "module"
                    ]
                    img_tags = soup_tech.find_all("img")
                    all_reqs = len(css_tags) + len(js_tags) + len(img_tags)

                    head_blocking = sum(1 for s in blocking_scripts if s.find_parent("head") is not None)
                    extracted_assets = AssetMetrics(
                        total_css=len(css_tags),
                        total_js=len(js_tags),
                        total_requests=all_reqs,
                        render_blocking_js_count=len(blocking_scripts),
                        render_blocking_head_count=head_blocking,
                        render_blocking_body_count=len(blocking_scripts) - head_blocking,
                        css_files_count=len(css_tags),
                        js_files_count=len(js_tags),
                        total_images=len(img_tags),
                    )
                except Exception as asset_err:
                    logger.warning("Asset extraction fallback error: %s", asset_err)
                    extracted_assets = AssetMetrics()

                # ۲. فراخوانی امن تحلیل‌گر تکنیکال
                if analyze_technical:
                    try:
                        raw_tech = None
                        func = _get_callable(analyze_technical, "analyze")
                        if func:
                            raw_tech = await _invoke_analyzer(func, self.url, client=client, response=response)

                        tech_m, tech_i, tech_w, tech_p = _split(raw_tech)
                        if isinstance(tech_m, TechnicalMetrics):
                            report.technical = tech_m
                        elif isinstance(tech_m, dict):
                            report.technical = TechnicalMetrics(**tech_m)

                        all_issues.extend(tech_i)
                        all_warnings.extend(tech_w)
                        score = max(0, score - tech_p)
                    except Exception as e:
                        score = max(0, score - _record_analyzer_failure(report, all_issues, "Technical", e))

                # ۳. تضمین وجود شیء TechnicalMetrics و اتصال مقادیر واقعی دارایی‌ها
                if report.technical is None:
                    resp_time = (
                        getattr(response, "elapsed", None).total_seconds() * 1000
                        if getattr(response, "elapsed", None)
                        else 0.0
                    )
                    page_size = (
                        len(response.content) / 1024.0
                        if getattr(response, "content", None)
                        else 0.0
                    )
                    report.technical = TechnicalMetrics(
                        status_code=getattr(response, "status_code", 200),
                        response_time_ms=resp_time,
                        page_size_kb=page_size,
                    )

                # منبع واحد: خروجی تحلیل‌گر تکنیکال (همان عددی که هشدار render-blocking بر اساسش صادر شده)؛
                # استخراج موتور فقط وقتی استفاده می‌شود که تحلیل‌گر دارایی‌ها را پر نکرده باشد.
                if report.technical.assets is None or report.technical.assets == AssetMetrics():
                    report.technical.assets = extracted_assets
                # تحلیل‌گر تکنیکال این دو مقدار را پر نمی‌کند؛ از پاسخ واقعی استخراج می‌شوند
                report.technical.redirect_count = redirect_hops
                content_encoding = str(response.headers.get("Content-Encoding", "")).lower()
                report.technical.is_compressed = any(
                    enc in content_encoding for enc in ("gzip", "br", "deflate", "zstd")
                )

                # ----------------------------------------------------------
                # نقشه سایت و روبات (Sitemap & Robots Analysis)
                # ----------------------------------------------------------
                if analyze_sitemap:
                    try:
                        raw_sm = None
                        func = _get_callable(analyze_sitemap, "analyze_sitemap") or _get_callable(analyze_sitemap, "analyze")

                        if func:
                            raw_sm = await _invoke_analyzer(func, self.url, client=client, response=response)

                        sm_m, sm_i, sm_w, sm_p = _split(raw_sm)
                        if isinstance(sm_m, SitemapMetrics):
                            report.sitemap = sm_m
                        elif isinstance(sm_m, dict):
                            report.sitemap = SitemapMetrics(**sm_m)

                        if report.sitemap is not None:
                            report.technical.has_robots = report.sitemap.has_robots_txt
                            report.technical.has_robots_txt = report.sitemap.has_robots_txt
                            report.technical.robots_txt_status = report.sitemap.robots_txt_status
                            report.technical.has_sitemap = report.sitemap.has_sitemap
                            report.technical.sitemap_urls_count = report.sitemap.total_urls
                        all_issues.extend(sm_i)
                        all_warnings.extend(sm_w)
                        score = max(0, score - sm_p)
                    except Exception as e:
                        score = max(0, score - _record_analyzer_failure(report, all_issues, "Sitemap", e))

                # ----------------------------------------------------------
                # تحلیل محتوا و On-Page (Patched - Priority 1)
                # ----------------------------------------------------------
                if analyze_on_page:
                    try:
                        func = _get_callable(analyze_on_page, "analyze")
                        if func is None:
                            logger.warning("On-page analyzer has no callable entry point.")
                        else:
                            raw_onpage = await _invoke_analyzer(
                                func,
                                html_content,
                                url=self.url,
                            )

                            op_m, op_i, op_w, op_p = _split(raw_onpage)
                            if isinstance(op_m, OnPageMetrics):
                                report.on_page = op_m
                            elif isinstance(op_m, dict):
                                report.on_page = OnPageMetrics(**op_m)
                            elif op_m is not None:
                                logger.warning(
                                    "Unsupported On-page metrics type: %s",
                                    type(op_m).__name__,
                                )

                            all_issues.extend(op_i)
                            all_warnings.extend(op_w)
                            score = max(0, score - op_p)
                    except Exception as e:
                        score = max(0, score - _record_analyzer_failure(report, all_issues, "On-page", e))

                # ----------------------------------------------------------
                # تحلیل تصاویر (Images Analysis - Patched - Priority 1)
                # ----------------------------------------------------------
                if analyze_images:
                    try:
                        func = _get_callable(analyze_images, "analyze")
                        if func is None:
                            logger.warning("Images analyzer has no callable entry point.")
                        else:
                            raw_img = await _invoke_analyzer(
                                func,
                                html_content,
                                base_url=self.url,
                            )

                            img_m, img_i, img_w, img_p = _split(raw_img)
                            if isinstance(img_m, ImageAuditMetrics):
                                report.images_audit = img_m
                            elif isinstance(img_m, dict):
                                report.images_audit = ImageAuditMetrics(**img_m)
                            elif img_m is not None:
                                logger.warning(
                                    "Unsupported Images metrics type: %s",
                                    type(img_m).__name__,
                                )

                            all_issues.extend(img_i)
                            all_warnings.extend(img_w)
                            score = max(0, score - img_p)
                    except Exception as e:
                        score = max(0, score - _record_analyzer_failure(report, all_issues, "Images", e))

                # ----------------------------------------------------------
                # معماری لینک‌ها و بررسی پیوندها (Links Architecture)
                # ----------------------------------------------------------
                if analyze_links:
                    try:
                        raw_links = None
                        func = _get_callable(analyze_links, "analyze_links") or _get_callable(analyze_links, "analyze")
                        if func:
                            raw_links = await _invoke_analyzer(func, html_content, base_url=self.url, client=client)

                        # خروجی links به شکل (metrics, broken_details) است، نه ۴تایی استاندارد
                        broken_raw: List[Any] = []
                        if isinstance(raw_links, tuple) and len(raw_links) == 2:
                            broken_raw = list(raw_links[1] or [])
                            raw_links = (raw_links[0],)

                        links_m, links_i, links_w, links_p = _split(raw_links)
                        if isinstance(links_m, LinkArchitectureMetrics):
                            report.links = links_m
                            report.links_arch = links_m
                        elif isinstance(links_m, dict):
                            report.links = LinkArchitectureMetrics(**links_m)
                            report.links_arch = report.links

                        all_issues.extend(links_i)
                        all_warnings.extend(links_w)
                        score = max(0, score - links_p)

                        if broken_raw:
                            report.broken_links = [
                                BrokenLink(**b) if isinstance(b, dict) else b
                                for b in broken_raw
                            ]
                            all_warnings.append(
                                f"{len(report.broken_links)} لینک خراب در صفحه شناسایی شد."
                            )

                        logger.info(
                            "Links Architecture completed: %s internal, %s external, %s broken.",
                            getattr(report.links, "internal_count", 0),
                            getattr(report.links, "external_count", 0),
                            len(report.broken_links),
                        )

                    except Exception as e:
                        score = max(0, score - _record_analyzer_failure(report, all_issues, "Links", e))

                # ----------------------------------------------------------
                # سئو محلی (Local SEO Analysis)
                # ----------------------------------------------------------
                if analyze_local_seo:
                    try:
                        func = _get_callable(analyze_local_seo, "analyze_local_seo") or _get_callable(analyze_local_seo, "analyze")
                        if func:
                            raw_loc = await _invoke_analyzer(func, html_content, base_url=self.url)

                            loc_m, loc_i, loc_w, loc_p = _split(raw_loc)
                            if isinstance(loc_m, LocalSEOMetrics):
                                report.local_seo = loc_m
                            elif isinstance(loc_m, dict):
                                report.local_seo = LocalSEOMetrics(**loc_m)

                            is_local = self.local_business
                            if is_local is None and report.local_seo is not None:
                                ls = report.local_seo
                                is_local = bool(
                                    ls.has_local_schema or ls.has_nap_schema
                                    or ls.has_geo_coordinates or ls.has_geo_meta
                                    or ls.has_google_maps_embed or ls.has_map_embed
                                )
                            if is_local is False:
                                all_warnings.append(
                                    "Local SEO: سایت محلی تشخیص داده نشد؛ بخش Local SEO امتیازدهی نشد."
                                )
                            else:
                                all_issues.extend(loc_i)
                                all_warnings.extend(loc_w)
                                score = max(0, score - loc_p)
                    except Exception as e:
                        score = max(0, score - _record_analyzer_failure(report, all_issues, "Local SEO", e))

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
        if report.failed_analyzers:
            score = min(score, INCOMPLETE_AUDIT_SCORE_CAP)
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