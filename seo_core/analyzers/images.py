"""
Advanced Image SEO Analyzer
Focuses on WebP/AVIF adoption, CLS risks (dimensions), lazy-loading, and alt texts.
"""
from typing import Tuple, List
from seo_core.html_utils import parse_html
from seo_core.models import ImageAuditMetrics, ImageAuditItem


def analyze(html: str) -> Tuple[ImageAuditMetrics, List[str], List[str], int]:
    issues: List[str] = []
    warnings: List[str] = []
    penalty: int = 0

    if not html:
        return ImageAuditMetrics(), issues, warnings, penalty

    soup = parse_html(html)
    img_tags = soup.find_all("img")
    total_images = len(img_tags)

    images_details: List[ImageAuditItem] = []
    missing_alt_list: List[str] = []
    missing_dimensions_count = 0
    nextgen_count = 0
    lazy_count = 0

    nextgen_extensions = {".webp", ".avif"}

    for img in img_tags:
        src = (img.get("src") or img.get("data-src") or "").strip()
        alt = (img.get("alt") or "").strip()
        width = img.get("width")
        height = img.get("height")
        loading = (img.get("loading") or "").lower().strip()

        # تشخیص فرمت فایل
        format_detected = "unknown"
        clean_src = src.split("?")[0].lower()
        for ext in [".webp", ".avif", ".png", ".jpg", ".jpeg", ".svg", ".gif"]:
            if clean_src.endswith(ext):
                format_detected = ext.replace(".", "")
                break

        is_nextgen = any(clean_src.endswith(ext) for ext in nextgen_extensions)
        if is_nextgen:
            nextgen_count += 1

        # بررسی Lazy Loading
        is_lazy = loading == "lazy"
        if is_lazy:
            lazy_count += 1

        # ابعاد تصویر برای جلوگیری از Layout Shift
        has_dimensions = bool(width and height)
        if not has_dimensions:
            missing_dimensions_count += 1

        # بررسی متن جایگزین Alt
        has_alt = bool(alt)
        if not has_alt and src:
            missing_alt_list.append(src)

        images_details.append(
            ImageAuditItem(
                src=src,
                alt=alt,
                has_alt=has_alt,
                has_dimensions=has_dimensions,
                width=str(width) if width else None,
                height=str(height) if height else None,
                is_lazy=is_lazy,
                is_nextgen=is_nextgen,
                format=format_detected
            )
        )

    images_missing_alt = len(missing_alt_list)

    # سیستم امتیازدهی و هشدارها
    if images_missing_alt > 0:
        issues.append(f"{images_missing_alt} تصویر فاقد متن جایگزین (Alt) هستند.")
        penalty += min(images_missing_alt * 2, 8)

    if missing_dimensions_count > 0:
        warnings.append(
            f"{missing_dimensions_count} تصویر فاقد ابعاد صریح (Width/Height) هستند (ریسک CLS)."
        )
        penalty += min(missing_dimensions_count, 5)

    if total_images > 0 and (nextgen_count / total_images) < 0.4:
        warnings.append("کمتر از ۴۰٪ تصاویر از فرمت‌های نسل جدید (WebP/AVIF) استفاده می‌کنند.")
        penalty += 3

    metrics = ImageAuditMetrics(
        total_images=total_images,
        images_missing_alt=images_missing_alt,
        images_without_alt_list=missing_alt_list,
        images_missing_dimensions=missing_dimensions_count,
        images_nextgen_count=nextgen_count,
        images_lazy_count=lazy_count,
        images_details=images_details
    )

    return metrics, issues, warnings, penalty