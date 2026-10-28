"""
Data models for the SEO Audit Engine (Hardened Enterprise Edition).
Single Source of Truth compatible with Pydantic V2.

Supported Features:
- Technical & Security Metrics (HSTS, CSP, Mixed Content, etc.)
- On-Page & Content Metrics (Readability, Keywords, Headings)
- Link Architecture & Broken Link Detection
- Local SEO Checks & Rich Schema
- Advanced Image Auditing (ImageAuditItem, ImageAuditMetrics, CLS Risk, WebP/AVIF, Lazy-load)
- Sitemap Auditing & Status Verification (SitemapItem, SitemapMetrics)
- Master Audit Report with bidirectional auto-synchronization
"""

from typing import List, Dict, Optional, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator, model_validator


# ==========================================
# 1. Social & OpenGraph Models
# ==========================================
class SocialMetrics(BaseModel):
    has_og: bool = False
    has_complete_og: bool = False
    has_twitter_card: bool = False
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_image: Optional[str] = None
    og_url: Optional[str] = None
    og_type: Optional[str] = None
    twitter_card: Optional[str] = None
    twitter_title: Optional[str] = None
    twitter_description: Optional[str] = None
    twitter_image: Optional[str] = None
    og_tags: Dict[str, str] = Field(default_factory=dict)
    twitter_tags: Dict[str, str] = Field(default_factory=dict)
    social_profiles: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_social_flags(self) -> "SocialMetrics":
        if self.og_title or self.og_image or self.og_description or self.og_tags:
            self.has_og = True
        if self.og_title and self.og_image and self.og_description:
            self.has_complete_og = True
        if self.twitter_card or self.twitter_title or self.twitter_tags:
            self.has_twitter_card = True
        return self


# ==========================================
# 2. Content & Text Analysis Models
# ==========================================
class ContentMetrics(BaseModel):
    word_count: int = 0
    character_count: int = 0
    reading_time_minutes: float = 0.0
    text_ratio_percent: float = 0.0
    h1_count: int = 0
    h2_count: int = 0
    h3_count: int = 0
    lang_declared: Optional[str] = None
    language_code: Optional[str] = None
    has_favicon: bool = False
    top_keywords: List[Dict[str, Any]] = Field(default_factory=list)
    keywords_density: Dict[str, float] = Field(default_factory=dict)
    flesch_kincaid_score: Optional[float] = None

    @field_validator("lang_declared", mode="before")
    @classmethod
    def normalize_lang_declared(cls, v: Any) -> Optional[str]:
        if isinstance(v, list) and v:
            return str(v[0]).strip()
        return str(v).strip() if v else None

    @field_validator("top_keywords", mode="before")
    @classmethod
    def normalize_top_keywords(cls, v: Any) -> List[Dict[str, Any]]:
        """
        لایه دفاعی برای تبدیل انعطاف‌پذیر تاپل‌های Counter، دیکشنری‌ها یا اشیاء به فرمت استاندارد Pydantic.
        از بروز خطای ValidationError در مواجهه با ورودی‌هایی نظیر [('github', 57), ...] جلوگیری می‌کند.
        """
        if not v:
            return []
        if not isinstance(v, (list, tuple)):
            return []

        normalized: List[Dict[str, Any]] = []
        for item in v:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                normalized.append({"word": str(item[0]), "count": item[1]})
            elif isinstance(item, dict):
                # اطمینان از وجود کلیدهای word و count
                w = item.get("word") or item.get("keyword") or str(item)
                c = item.get("count") or item.get("frequency") or 1
                normalized.append({"word": str(w), "count": c})
            elif hasattr(item, "word") and hasattr(item, "count"):
                normalized.append({"word": str(item.word), "count": item.count})
            else:
                normalized.append({"word": str(item), "count": 1})
        return normalized


# ==========================================
# 3. Security Metrics
# ==========================================
class SecurityMetrics(BaseModel):
    is_https: bool = False
    hsts_enabled: bool = False
    has_hsts: bool = False
    has_csp: bool = False
    has_x_frame_options: bool = False
    has_x_content_type_options: bool = False
    server_tokens: Optional[str] = None
    mixed_content: List[str] = Field(default_factory=list)
    mixed_content_urls: List[str] = Field(default_factory=list)
    mixed_content_count: int = 0
    security_score: int = 100

    @field_validator("mixed_content", "mixed_content_urls", mode="before")
    @classmethod
    def ensure_list_of_strings(cls, v: Any) -> List[str]:
        if isinstance(v, list):
            return [str(x) for x in v]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
        return []

    @model_validator(mode="after")
    def sync_security_counters(self) -> "SecurityMetrics":
        if self.hsts_enabled:
            self.has_hsts = True
        elif self.has_hsts:
            self.hsts_enabled = True

        urls = self.mixed_content or self.mixed_content_urls
        if urls:
            self.mixed_content = urls
            self.mixed_content_urls = urls
            self.mixed_content_count = len(urls)
        else:
            self.mixed_content_count = len(self.mixed_content_urls)
        return self


# ==========================================
# 4. Asset Metrics
# ==========================================
class AssetMetrics(BaseModel):
    total_css: int = 0
    total_js: int = 0
    total_requests: int = 0
    render_blocking_js_count: int = 0
    # تفکیک render-blocking: head = مسدودکننده اولین رندر، body = فقط مانع پارس
    render_blocking_head_count: int = 0
    render_blocking_body_count: int = 0
    css_files_count: int = 0
    js_files_count: int = 0
    total_images: int = 0
    total_images_count: int = 0
    render_blocking_scripts: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_asset_counters(self) -> "AssetMetrics":
        if self.css_files_count and not self.total_css:
            self.total_css = self.css_files_count
        elif self.total_css and not self.css_files_count:
            self.css_files_count = self.total_css

        if self.js_files_count and not self.total_js:
            self.total_js = self.js_files_count
        elif self.total_js and not self.js_files_count:
            self.js_files_count = self.total_js

        if self.total_images_count and not self.total_images:
            self.total_images = self.total_images_count
        elif self.total_images and not self.total_images_count:
            self.total_images_count = self.total_images

        if self.render_blocking_scripts and not self.render_blocking_js_count:
            self.render_blocking_js_count = len(self.render_blocking_scripts)
        elif self.render_blocking_js_count and not self.render_blocking_scripts:
            self.render_blocking_scripts = [f"script_{i+1}" for i in range(self.render_blocking_js_count)]
        return self


# ==========================================
# 5. Link Architecture & Broken Link Models
# ==========================================
class BrokenLink(BaseModel):
    url: str
    status_code: int = 0
    reason: Optional[str] = None
    source_url: Optional[str] = None
    source_element: Optional[str] = None


class LinkArchitectureMetrics(BaseModel):
    internal_count: int = 0
    external_count: int = 0
    total_links: int = 0
    nofollow_count: int = 0
    insecure_target_blank_count: int = 0
    top_anchors: List[Dict[str, Any]] = Field(default_factory=list)
    internal_links_count: int = 0
    external_links_count: int = 0
    nofollow_links_count: int = 0
    dofollow_links_count: int = 0
    broken_links_count: int = 0
    unverifiable_links: List[str] = Field(default_factory=list)

    @field_validator("top_anchors", mode="before")
    @classmethod
    def normalize_top_anchors(cls, v: Any) -> Any:
        # قبول فرمت قدیمی {متن: تعداد} و تبدیل به لیست دیکشنری
        if isinstance(v, dict):
            return [
                {"text": str(k), "anchor": str(k), "count": c}
                for k, c in sorted(v.items(), key=lambda kv: -kv[1])
            ]
        return v

    @model_validator(mode="after")
    def sync_link_counts(self) -> "LinkArchitectureMetrics":
        if self.internal_count and not self.internal_links_count:
            self.internal_links_count = self.internal_count
        elif self.internal_links_count and not self.internal_count:
            self.internal_count = self.internal_links_count

        if self.external_count and not self.external_links_count:
            self.external_links_count = self.external_count
        elif self.external_links_count and not self.external_count:
            self.external_count = self.external_links_count

        if self.nofollow_count and not self.nofollow_links_count:
            self.nofollow_links_count = self.nofollow_count
        elif self.nofollow_links_count and not self.nofollow_count:
            self.nofollow_count = self.nofollow_links_count

        if not self.total_links:
            self.total_links = self.internal_count + self.external_count
        return self


# ==========================================
# 6. Advanced Image Audit Models
# ==========================================
class ImageAuditItem(BaseModel):
    src: str = ""
    alt: Optional[str] = None
    has_alt: bool = True
    has_dimensions: bool = True
    width: Optional[str] = None
    height: Optional[str] = None
    is_lazy: bool = False
    is_nextgen: bool = False
    format: Optional[str] = None


class ImageAuditMetrics(BaseModel):
    total_images: int = 0
    images_missing_alt: int = 0
    images_without_alt_list: List[str] = Field(default_factory=list)
    images_missing_dimensions: int = 0
    images_nextgen_count: int = 0
    images_lazy_count: int = 0
    images_details: List[ImageAuditItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_image_audit_counts(self) -> "ImageAuditMetrics":
        if self.images_details and not self.total_images:
            self.total_images = len(self.images_details)
        if self.images_without_alt_list and not self.images_missing_alt:
            self.images_missing_alt = len(self.images_without_alt_list)
        return self


# ==========================================
# 7. Sitemap Audit Models
# ==========================================
class SitemapItem(BaseModel):
    url: str
    status_code: int = 0
    status: str = "ok"  # 'ok', 'broken_404', 'redirect', 'server_error', 'timeout', 'error'


class SitemapMetrics(BaseModel):
    has_robots_txt: bool = False
    robots_txt_status: Optional[int] = None
    has_sitemap: bool = False
    sitemap_url: Optional[str] = None
    is_valid_xml: bool = False
    is_sitemap_index: bool = False
    total_urls: int = 0
    checked_urls_count: int = 0
    ok_count: int = 0
    broken_404_count: int = 0
    redirect_count: int = 0
    server_error_count: int = 0
    broken_urls: List[str] = Field(default_factory=list)
    redirect_urls: List[str] = Field(default_factory=list)
    items: List[SitemapItem] = Field(default_factory=list)


# ==========================================
# 8. Local SEO Models
# ==========================================
class LocalSEOMetrics(BaseModel):
    checklist: Dict[str, bool] = Field(default_factory=dict)
    local_score: int = 0
    passed_checks: int = 0
    warnings: List[str] = Field(default_factory=list)
    has_nap_schema: bool = False
    has_postal_address: bool = False
    has_geo_coordinates: bool = False
    has_opening_hours: bool = False
    has_google_maps_embed: bool = False
    detected_telephones: List[str] = Field(default_factory=list)
    detected_emails: List[str] = Field(default_factory=list)
    detected_social_profiles: List[str] = Field(default_factory=list)
    has_local_schema: bool = False
    schema_types: List[str] = Field(default_factory=list)
    business_name: Optional[str] = None
    phone_numbers: List[str] = Field(default_factory=list)
    emails: List[str] = Field(default_factory=list)
    addresses: List[str] = Field(default_factory=list)
    has_map_embed: bool = False
    map_links: List[str] = Field(default_factory=list)
    has_geo_meta: bool = False
    geo_coordinates: Optional[Dict[str, float]] = None

    @field_validator("business_name", mode="before")
    @classmethod
    def normalize_optional_text(cls, v: Any) -> Optional[str]:
        if isinstance(v, list) and v:
            return str(v[0]).strip()
        return str(v).strip() if v else None

    @model_validator(mode="after")
    def sync_local_seo_keys(self) -> "LocalSEOMetrics":
        # همگام‌سازی تلفن، ایمیل و آدرس‌ها
        if self.phone_numbers and not self.detected_telephones:
            self.detected_telephones = list(self.phone_numbers)
        elif self.detected_telephones and not self.phone_numbers:
            self.phone_numbers = list(self.detected_telephones)

        if self.emails and not self.detected_emails:
            self.detected_emails = list(self.emails)
        elif self.detected_emails and not self.emails:
            self.emails = list(self.detected_emails)

        if self.has_map_embed or self.has_google_maps_embed:
            self.has_map_embed = True
            self.has_google_maps_embed = True

        if self.has_local_schema or self.has_nap_schema:
            self.has_local_schema = True
            self.has_nap_schema = True

        # بازسازی یا تکمیل دیکشنری checklist جهت اطمینان از خروجی رابط کاربری
        cl = dict(self.checklist) if self.checklist else {}
        cl.setdefault("has_nap_schema", self.has_nap_schema)
        cl.setdefault("has_local_business_schema", self.has_local_schema)
        cl.setdefault("has_address", bool(self.addresses) or self.has_postal_address)
        cl.setdefault("has_phone", bool(self.phone_numbers) or bool(self.detected_telephones))
        cl.setdefault("has_email", bool(self.emails) or bool(self.detected_emails))
        cl.setdefault("has_google_maps_embed", self.has_google_maps_embed)
        cl.setdefault("has_geo_coordinates", self.has_geo_coordinates or self.has_geo_meta)
        cl.setdefault("has_opening_hours", self.has_opening_hours)
        self.checklist = cl

        if not self.passed_checks:
            self.passed_checks = sum(1 for val in self.checklist.values() if val)
        return self


# ==========================================
# 9. Technical & On-Page Models
# ==========================================
class TechnicalMetrics(BaseModel):
    status_code: int = 200
    response_time: float = 0.0
    response_time_ms: float = 0.0
    page_size: float = 0.0
    page_size_kb: float = 0.0
    content_type: str = "text/html"
    is_crawlable: bool = True
    has_robots: bool = False
    has_robots_txt: bool = False
    robots_txt_status: Optional[int] = None
    has_sitemap: bool = False
    sitemap_status: Optional[int] = None
    sitemap_urls_count: int = 0
    is_compressed: bool = False
    redirect_count: int = 0
    has_canonical: bool = False
    canonical_url: Optional[str] = None
    canonical_matches: bool = True
    html_version: Optional[str] = None
    has_viewport: bool = False
    is_responsive: bool = False
    is_noindex: bool = False
    has_schema: bool = False
    security: Optional[SecurityMetrics] = None
    assets: Optional[AssetMetrics] = None

    @model_validator(mode="after")
    def sync_technical_flags(self) -> "TechnicalMetrics":
        if self.response_time and not self.response_time_ms:
            self.response_time_ms = self.response_time
        elif self.response_time_ms and not self.response_time:
            self.response_time = self.response_time_ms

        if self.page_size and not self.page_size_kb:
            self.page_size_kb = self.page_size
        elif self.page_size_kb and not self.page_size:
            self.page_size = self.page_size_kb

        if self.has_robots or self.has_robots_txt:
            self.has_robots = True
            self.has_robots_txt = True

        if self.has_viewport or self.is_responsive:
            self.has_viewport = True
            self.is_responsive = True

        return self


class OnPageMetrics(BaseModel):
    title: Optional[str] = None
    title_length: int = 0
    title_status: str = "missing"
    meta_description: Optional[str] = None
    meta_description_length: int = 0
    meta_description_status: str = "missing"
    h1_count: int = 0
    h1_list: List[str] = Field(default_factory=list)
    h2_count: int = 0
    h2_list: List[str] = Field(default_factory=list)
    h3_count: int = 0
    h3_list: List[str] = Field(default_factory=list)
    h4_count: int = 0
    total_images: int = 0
    images_count: int = 0
    images_missing_alt: int = 0
    images_without_alt: int = 0
    images_without_alt_list: List[str] = Field(default_factory=list)
    images_with_alt: int = 0
    internal_links_count: int = 0
    external_links_count: int = 0
    content: Optional[ContentMetrics] = None
    social: Optional[SocialMetrics] = None

    @model_validator(mode="after")
    def sync_onpage_metrics(self) -> "OnPageMetrics":
        if self.total_images and not self.images_count:
            self.images_count = self.total_images
        elif self.images_count and not self.total_images:
            self.total_images = self.images_count

        missing_alt = max(self.images_missing_alt, self.images_without_alt, len(self.images_without_alt_list))
        self.images_missing_alt = missing_alt
        self.images_without_alt = missing_alt

        if self.total_images >= self.images_missing_alt:
            self.images_with_alt = self.total_images - self.images_missing_alt

        return self


# ==========================================
# 10. Master Audit Report Model
# ==========================================
class AuditReport(BaseModel):
    url: str
    crawl_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "success"
    error_message: Optional[str] = None
    score: int = 100
    overall_score: int = 100
    issues_count: int = 0
    warnings_count: int = 0
    technical: TechnicalMetrics = Field(default_factory=TechnicalMetrics)
    on_page: OnPageMetrics = Field(default_factory=OnPageMetrics)
    links: Optional[LinkArchitectureMetrics] = None
    links_arch: Optional[LinkArchitectureMetrics] = None
    local_seo: Optional[LocalSEOMetrics] = None
    images_audit: Optional[ImageAuditMetrics] = None
    sitemap: Optional[SitemapMetrics] = None
    broken_links: List[BrokenLink] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    failed_analyzers: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_report_scores_and_links(self) -> "AuditReport":
        # همگام‌سازی امتیازها
        if self.overall_score != 100 and self.score == 100:
            self.score = self.overall_score
        elif self.score != 100 and self.overall_score == 100:
            self.overall_score = self.score

        # همگام‌سازی ساختار لینک‌ها
        active_links = self.links or self.links_arch
        if active_links:
            self.links = active_links
            self.links_arch = active_links

        # همگام‌سازی وضعیت سایت‌مپ با بخش تکنیکال
        if self.sitemap and self.sitemap.has_robots_txt:
            self.technical.has_robots = True
            self.technical.has_robots_txt = True
        if self.sitemap and self.sitemap.has_sitemap:
            self.technical.has_sitemap = True
            if self.sitemap.total_urls:
                self.technical.sitemap_urls_count = self.sitemap.total_urls

        # همگام‌سازی آنالیز تصاویر با OnPage
        if self.images_audit:
            if self.images_audit.total_images > 0:
                self.on_page.total_images = self.images_audit.total_images
                self.on_page.images_count = self.images_audit.total_images
            if self.images_audit.images_missing_alt > 0:
                self.on_page.images_missing_alt = self.images_audit.images_missing_alt
                self.on_page.images_without_alt = self.images_audit.images_missing_alt
            if self.images_audit.images_without_alt_list:
                self.on_page.images_without_alt_list = self.images_audit.images_without_alt_list

        self.issues_count = len(self.issues)
        self.warnings_count = len(self.warnings)
        return self