"""
Local SEO analyzer.

Returns LocalSEOMetrics-compatible keys while retaining schema details,
addresses, map signals, and checklist results in the available list fields.
"""
from __future__ import annotations

import json
import re
from typing import Any, Tuple, List, Dict, Optional
from urllib.parse import urljoin

from seo_core.html_utils import parse_html


_MAP_PATTERNS = (
    r"google\.com/maps",
    r"maps\.google\.com",
    r"neshan\.org",
    r"balad\.ir",
    r"openstreetmap\.org",
)

_LOCAL_BUSINESS_TYPES = {
    "localbusiness",
    "restaurant",
    "store",
    "medicalbusiness",
    "professionalservice",
    "dentist",
    "attorney",
    "automotivebusiness",
    "financialservice",
    "lodgingbusiness",
    "organization",
}

_PHONE_TEXT_PATTERN = re.compile(
    r"(?:0|\+98)?9\d{9}|(?:0\d{2,3}[- ]?)?\d{7,8}"
)


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _schema_types(node: dict[str, Any]) -> list[str]:
    value = node.get("@type", [])
    return [str(item).strip() for item in _as_list(value) if str(item).strip()]


def _iter_schema_nodes(value: Any):
    """Yield JSON-LD nodes, including nested graphs and arrays."""
    if isinstance(value, list):
        for item in value:
            yield from _iter_schema_nodes(item)
    elif isinstance(value, dict):
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_schema_nodes(item)
        else:
            yield value


def _append_unique(values: list[str], value: Any) -> None:
    if value is None:
        return
    text = str(value).strip()
    if text and text not in values:
        values.append(text)


def analyze_local_seo(
    html: str, base_url: str = ""
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    soup = parse_html(html)
    issues: list[str] = []
    warnings: list[str] = []

    phones: list[str] = []
    emails: list[str] = []
    addresses: list[str] = []
    social_profiles: list[str] = []
    schema_type_names: list[str] = []
    business_names: list[str] = []
    opening_hours: list[str] = []
    postal_addresses: list[str] = []

    # --- Geo Metadata ---
    geo_names = ("geo.position", "geo.placename", "geo.region", "icbm")
    geo_tags = {
        name: soup.find(
            "meta",
            attrs={"name": re.compile(rf"^{re.escape(name)}$", re.I)},
        )
        for name in geo_names
    }
    has_geo_meta = any(geo_tags.values())
    coordinates = ""
    for name in ("geo.position", "icbm"):
        tag = geo_tags[name]
        if tag and tag.get("content", "").strip():
            coordinates = tag["content"].strip()
            break

    # --- Map Embeds & Links ---
    has_map_embed = any(
        any(re.search(pattern, iframe.get("src", ""), re.I) for pattern in _MAP_PATTERNS)
        for iframe in soup.find_all("iframe", src=True)
    )
    has_map_link = False
    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, anchor.get("href", "")) if base_url else anchor.get("href", "")
        if any(re.search(pattern, href, re.I) for pattern in _MAP_PATTERNS):
            has_map_link = True
            break

    # --- Phone & Email Extraction ---
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "").strip()
        if href.lower().startswith("tel:"):
            _append_unique(phones, re.sub(r"^tel:", "", href, flags=re.I))
        elif href.lower().startswith("mailto:"):
            email = re.sub(r"^mailto:", "", href, flags=re.I).split("?", 1)[0]
            _append_unique(emails, email)

    raw_text = soup.get_text(separator=" ")
    for match in _PHONE_TEXT_PATTERN.findall(raw_text):
        if len(re.sub(r"\D", "", match)) in (8, 10, 11):
            _append_unique(phones, match)

    # --- Address Extraction ---
    for element in soup.find_all(attrs={"itemprop": re.compile(r"^address$", re.I)}):
        _append_unique(addresses, element.get_text(" ", strip=True))
    for element in soup.find_all("address"):
        _append_unique(addresses, element.get_text(" ", strip=True))

    has_local_schema = False
    has_opening_hours = False

    def inspect_node(node: dict[str, Any]) -> None:
        nonlocal has_local_schema, has_opening_hours

        types = _schema_types(node)
        for type_name in types:
            _append_unique(schema_type_names, type_name)
            if type_name.rsplit("/", 1)[-1].lower() in _LOCAL_BUSINESS_TYPES:
                has_local_schema = True

        if node.get("name"):
            _append_unique(business_names, str(node["name"]).strip())

        telephone = node.get("telephone")
        for number in _as_list(telephone) if telephone else []:
            _append_unique(phones, str(number).strip())

        hours = node.get("openingHours")
        if hours:
            has_opening_hours = True
            for item in _as_list(hours):
                _append_unique(opening_hours, str(item).strip())

        specification = node.get("openingHoursSpecification")
        if specification:
            has_opening_hours = True
            for item in _as_list(specification):
                if isinstance(item, dict):
                    days = ", ".join(map(str, _as_list(item.get("dayOfWeek", []))))
                    opens = str(item.get("opens", "")).strip()
                    closes = str(item.get("closes", "")).strip()
                    _append_unique(opening_hours, " ".join(part for part in (days, opens, closes) if part))

        address = node.get("address")
        for item in _as_list(address) if address else []:
            if isinstance(item, dict):
                parts = [
                    item.get(key)
                    for key in (
                        "streetAddress",
                        "addressLocality",
                        "addressRegion",
                        "postalCode",
                        "addressCountry",
                    )
                    if item.get(key)
                ]
                rendered = ", ".join(str(part).strip() for part in parts if str(part).strip())
                _append_unique(addresses, rendered)
                _append_unique(postal_addresses, rendered)
            else:
                _append_unique(addresses, str(item).strip())
                _append_unique(postal_addresses, str(item).strip())

        same_as = node.get("sameAs")
        for profile in _as_list(same_as) if same_as else []:
            _append_unique(social_profiles, str(profile).strip())

        email = node.get("email")
        for item in _as_list(email) if email else []:
            _append_unique(emails, re.sub(r"^mailto:", "", str(item), flags=re.I).strip())

        contact_points = node.get("contactPoint")
        for contact in _as_list(contact_points) if contact_points else []:
            if isinstance(contact, dict):
                contact_phone = contact.get("telephone")
                for number in _as_list(contact_phone) if contact_phone else []:
                    _append_unique(phones, str(number).strip())
                contact_email = contact.get("email")
                for item in _as_list(contact_email) if contact_email else []:
                    _append_unique(emails, re.sub(r"^mailto:", "", str(item), flags=re.I).strip())

    # --- JSON-LD Parsing ---
    for script in soup.find_all("script", attrs={"type": re.compile(r"^application/ld\+json$", re.I)}):
        script_text = script.string or script.get_text()
        if not script_text.strip():
            continue
        try:
            data = json.loads(script_text)
        except (TypeError, ValueError):
            warnings.append("یکی از بلوک‌های JSON-LD قابل‌خواندن نبود.")
            continue
        for node in _iter_schema_nodes(data):
            inspect_node(node)

    has_address = bool(addresses)
    has_phone = bool(phones)
    has_map = has_map_embed or has_map_link
    has_geo_coordinates = bool(coordinates)

    checklist = {
        "has_local_schema": has_local_schema,
        "has_phone": has_phone,
        "has_address": has_address,
        "has_map": has_map,
        "has_geo_meta": has_geo_meta,
    }

    score = (
        (30 if has_local_schema else 0)
        + (25 if has_phone else 0)
        + (20 if has_address else 0)
        + (15 if has_map else 0)
        + (10 if has_geo_meta else 0)
    )

    if not has_local_schema:
        issues.append("اسکیما ساختاریافته محلی (LocalBusiness Schema) در صفحه یافت نشد.")
    if not has_phone:
        issues.append("شماره تماس یا لینک ارتباطی مستقیم (tel:) شناسایی نشد.")
    if not has_address:
        warnings.append("آدرس فیزیکی مشخص یا تگ <address> در صفحه یافت نشد.")
    if not has_map:
        warnings.append("نقشه تعاملی (گوگل مپ، نشان یا بلد) در صفحه یافت نشد.")
    if not has_geo_meta:
        warnings.append("متاتگ‌های موقعیت مکانی (geo.position / ICBM) درج نشده‌اند.")
    if not has_opening_hours:
        warnings.append("ساعات کاری در داده‌های ساختاریافته شناسایی نشد.")

    b_name = business_names[0] if business_names else ""

    # پچ دفاعی geo_coordinates: بازگرداندن Dict در صورت وجود مختصات یا None در صورت نبود آن
    coords: Optional[Dict[str, float]] = None
    if coordinates and coordinates.strip():
        # بررسی فرمت لات/لانگ مثل "35.6892, 51.3890" یا "35.6892; 51.3890"
        parts = re.split(r"[,; ]+", coordinates.strip())
        if len(parts) >= 2:
            try:
                coords = {"lat": float(parts[0]), "lng": float(parts[1])}
            except (ValueError, TypeError):
                coords = None

    # پچ passed_checks: شمارش تعداد چک‌های پاس‌شده به صورت int
    passed_count: int = sum(1 for passed in checklist.values() if passed)

    metrics: dict[str, Any] = {
        # --- فیلدهای استاندارد models.py ---
        "has_nap_schema": has_local_schema,
        "detected_telephones": sorted(phones),
        "detected_emails": sorted(emails),
        "has_postal_address": bool(postal_addresses or addresses),
        "has_geo_coordinates": has_geo_coordinates,
        "has_opening_hours": has_opening_hours,
        "has_google_maps_embed": has_map_embed,
        "detected_social_profiles": sorted(social_profiles),
        "local_score": score,
        "passed_checks": passed_count,  # مقدار عددی صحیح (int)
        "warnings": list(warnings),

        # --- فیلدهای ارجاعی و سازگار با اعتبارسنجی ---
        "has_local_schema": has_local_schema,
        "schema_types": sorted(schema_type_names),
        "business_name": b_name,
        "phone_numbers": sorted(phones),
        "emails": sorted(emails),
        "addresses": addresses,
        "has_map_embed": has_map_embed,
        "has_map_link": has_map_link,
        "has_geo_meta": has_geo_meta,
        "geo_coordinates": coords,      # دیکشنری مختصات یا None
        "opening_hours": opening_hours,
        "social_profiles": sorted(social_profiles),
        "checklist": checklist,
    }

    return metrics, issues, warnings


class LocalSEOAnalyzer:
    """Class wrapper used by the audit engine."""

    @staticmethod
    def analyze(
        html: str, base_url: str = ""
    ) -> Tuple[Dict[str, Any], List[str], List[str]]:
        return analyze_local_seo(html, base_url)