"""
Enterprise Hardened Link Architecture & Broken Link Analyzer
"""

import asyncio
import logging
from collections import Counter
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urljoin, urlparse

import httpx

from config.settings import settings
from seo_core.html_utils import parse_html
from seo_core.models import LinkArchitectureMetrics

logger = logging.getLogger(__name__)

LINK_TIMEOUT = settings.LINK_TIMEOUT
MAX_CONCURRENT_CHECKS = settings.MAX_CONCURRENT_LINK_CHECKS
from seo_core.safe_http import (  # noqa: E402
    MAX_REDIRECTS,
    SSRFSecurityError,
    bounded_request,
    is_safe_url,
    make_safe_transport,
)

# کدهایی که معمولاً به معنی مسدودسازی ربات هستند، نه لینک شکسته
BOT_BLOCK_STATUSES = {401, 403, 429}



class LinksAnalyzer:
    """
    Enterprise Hardened Link Architecture Analyzer
    پشتیبانی کامل از فراخوانی کلاسی، فراخوانی شیء‌گرا و تزریق ناهمگام کلاینت
    """

    def __init__(
        self,
        base_url: str = "",
        html: str = "",
        client: Optional[httpx.AsyncClient] = None,
        *args,
        **kwargs,
    ):
        """
        سازنده دفاعی: در صورتی که ترتیب آرگومان‌ها (html, url) یا (url, html) باشد
        به‌صورت هوشمند پارامترها را تشخیص داده و ست می‌کند.
        """
        # تشخیص هوشمند آرگومان‌ها
        first_arg = base_url
        second_arg = html

        if first_arg.strip().startswith("<") or ("<html" in first_arg.lower()):
            self.html = first_arg
            self.base_url = second_arg
        elif second_arg.strip().startswith("<") or ("<html" in second_arg.lower()):
            self.base_url = first_arg
            self.html = second_arg
        else:
            self.base_url = first_arg or kwargs.get("url", "")
            self.html = second_arg or kwargs.get("html_content", "")

        self.client = client
        self.user_agent = kwargs.get(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )

    @classmethod
    async def _check_link(
        cls,
        client: httpx.AsyncClient,
        target_url: str,
        semaphore: asyncio.Semaphore,
        timeout: float = LINK_TIMEOUT,
    ) -> Tuple[str, int, bool]:
        """بررسی سلامت لینک با مدیریت همزمانی و ایمنی SSRF."""
        async with semaphore:
            try:
                res = await cls._request_safely(client, "HEAD", target_url, timeout)
                if res is not None and res.status_code in (405, 403, 400):
                    # fallback به GET برای سرورهایی که HEAD را مسدود می‌کنند
                    res = await cls._request_safely(client, "GET", target_url, timeout)
                if res is None:
                    return target_url, 0, True

                is_broken = res.status_code >= 400 and res.status_code not in BOT_BLOCK_STATUSES
                return target_url, res.status_code, is_broken

            except httpx.TimeoutException as e:
                # timeout نشانه قطعی شکستگی نیست (مثلاً x.com درخواست ربات را معلق می‌کند)
                logger.debug("Timeout checking link %s: %s", target_url, e)
                return target_url, 0, False
            except httpx.RequestError as e:
                logger.debug("Failed checking link %s: %s", target_url, e)
                return target_url, 0, True
            except Exception as e:
                logger.debug("Unexpected error checking link %s: %s", target_url, e)
                return target_url, 0, True

    @staticmethod
    async def _request_safely(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        timeout: float,
    ) -> Optional[httpx.Response]:
        """
        دنبال کردن دستی ریدایرکت‌ها و اعتبارسنجی SSRF در هر گام؛
        مستقل از کلاینت (داخلی یا تزریق‌شده) عمل می‌کند.
        در صورت مقصد ناامن یا ریدایرکت بیش از حد None برمی‌گرداند.
        """
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            if not await is_safe_url(current):
                logger.debug("Blocked unsafe link target: %s", current)
                return None
            # برای بررسی سلامت لینک بدنه لازم نیست؛ دانلود بدنه‌های بزرگ رخ نمی‌دهد
            res = await bounded_request(client, method, current, timeout=timeout, read_body=False)
            location = res.headers.get("Location")
            if not (res.is_redirect and location):
                return res
            current = urljoin(str(res.url), location)
        logger.debug("Too many redirects for %s", url)
        return None

    @classmethod
    def extract_links(cls, html: str, base_url: str) -> Dict[str, Any]:
        """استخراج و دسته‌بندی تمام پیوندها و متن‌های لنگر (Anchor Text)."""
        soup = parse_html(html)
        base_domain = urlparse(base_url).netloc.lower()

        internal_count = 0
        external_count = 0
        nofollow_count = 0
        insecure_target_blank_count = 0
        anchors = []
        # dict با حفظ ترتیب ظاهر شدن لینک‌ها؛ حذف تکراری بدون تغییر ترتیب
        candidates_seen: Dict[str, None] = {}

        for a_tag in soup.find_all("a", href=True):
            raw_href = a_tag["href"].strip()
            if not raw_href or raw_href.startswith(
                ("javascript:", "mailto:", "tel:", "#", "data:")
            ):
                continue

            full_url = urljoin(base_url, raw_href)
            parsed = urlparse(full_url)
            if parsed.scheme not in ("http", "https"):
                continue

            rel_attr = a_tag.get("rel", [])
            if isinstance(rel_attr, str):
                rel_attr = rel_attr.lower().split()
            else:
                rel_attr = [r.lower() for r in rel_attr]

            target_attr = a_tag.get("target", "").lower()

            # بررسی nofollow
            if "nofollow" in rel_attr:
                nofollow_count += 1

            target_domain = parsed.netloc.lower()
            is_internal = not target_domain or (target_domain == base_domain)

            if is_internal:
                internal_count += 1
            else:
                external_count += 1
                # بررسی ایمنی target="_blank"
                if target_attr == "_blank":
                    if "noopener" not in rel_attr and "noreferrer" not in rel_attr:
                        insecure_target_blank_count += 1

            anchor_text = a_tag.get_text(strip=True)
            if anchor_text:
                anchors.append(anchor_text)

            candidates_seen[full_url] = None

        total_links = internal_count + external_count
        top_anchors = [
            {"text": text, "anchor": text, "count": count}
            for text, count in Counter(anchors).most_common(10)
        ]

        return {
            "internal_count": internal_count,
            "external_count": external_count,
            "total_links": total_links,
            "nofollow_count": nofollow_count,
            "insecure_target_blank_count": insecure_target_blank_count,
            "candidates": list(candidates_seen),
            "top_anchors": top_anchors,
        }

    @classmethod
    async def analyze_all(
        cls,
        html: str,
        base_url: str,
        user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        allow_insecure: Optional[bool] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Tuple[LinkArchitectureMetrics, List[Dict[str, Any]]]:
        """
        متد مرجع ناهمگام کلاسی برای تحلیل ساختار لینک‌ها و شناسایی لینک‌های شکسته.
        """
        if allow_insecure is None:
            allow_insecure = settings.ALLOW_INSECURE_TLS

        data = cls.extract_links(html, base_url)
        candidates = data["candidates"]
        broken_details: List[Dict[str, Any]] = []
        unverifiable: List[str] = []

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)

        headers = {"User-Agent": user_agent}

        # مدیریت دفاعی لایف‌سایکل کلاینت
        if client is not None and not client.is_closed:
            tasks = [
                cls._check_link(client, url, semaphore)
                for url in candidates
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=LINK_TIMEOUT,
                verify=not allow_insecure,
                transport=make_safe_transport(verify=not allow_insecure),
                trust_env=False,
            ) as session:
                tasks = [
                    cls._check_link(session, url, semaphore)
                    for url in candidates
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

        base_host = (urlparse(base_url).hostname or "").lower().removeprefix("www.")
        for res in results:
            if isinstance(res, tuple):
                url, status, is_broken = res
                link_host = (urlparse(url).hostname or "").lower().removeprefix("www.")
                if is_broken and status == 0 and link_host != base_host:
                    # خطای شبکه روی لینک خارجی معمولاً مسدودسازی ربات است، نه شکستگی قطعی
                    logger.debug("Unverifiable external link: %s", url)
                    unverifiable.append(url)
                    continue
                if is_broken:
                    broken_details.append(
                        {
                            "url": url,
                            "status_code": status,
                            "reason": f"HTTP {status}" if status > 0 else "Network Error",
                            "source_url": base_url,
                            "source_element": "a",
                        }
                    )

        metrics = LinkArchitectureMetrics(
            total_links=data["total_links"],
            internal_count=data["internal_count"],
            external_count=data["external_count"],
            nofollow_count=data["nofollow_count"],
            insecure_target_blank_count=data["insecure_target_blank_count"],
            top_anchors=data["top_anchors"],
            broken_links_count=len(broken_details),
            unverifiable_links=unverifiable,
        )

        return metrics, broken_details

    async def run(
        self,
    ) -> Tuple[LinkArchitectureMetrics, List[Dict[str, Any]]]:
        """متد کمکی اجرای نمونه شیء."""
        return await self.analyze_all(
            html=self.html,
            base_url=self.base_url,
            user_agent=self.user_agent,
            client=self.client,
        )


# ---------------------------------------------------------------------------
# توابع سازگاری سطح ماژول (Module-level Compatibility Wrappers)
# ---------------------------------------------------------------------------
async def analyze_links(
    html: str,
    base_url: str,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[LinkArchitectureMetrics, List[Dict[str, Any]]]:
    """تابع سطح ماژول جهت فراخوانی مستقیم تحلیل لینک‌ها."""
    return await LinksAnalyzer.analyze_all(html=html, base_url=base_url, client=client)


async def analyze(
    html: str,
    base_url: str,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[LinkArchitectureMetrics, List[Dict[str, Any]]]:
    """نام مستعار تابع تحلیل جهت هماهنگی با سایر آنالایزرها."""
    return await LinksAnalyzer.analyze_all(html=html, base_url=base_url, client=client)