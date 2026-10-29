import re
from collections import Counter
from typing import Tuple, List
from bs4 import BeautifulSoup
from ..html_utils import parse_html
from ..models import OnPageMetrics, ContentMetrics, SocialMetrics


def _length_status(text: str, length: int, low: int, high: int) -> str:
    if not text:
        return "missing"
    if length < low:
        return "too_short"
    if length > high:
        return "too_long"
    return "good"


def analyze(html: str) -> Tuple[OnPageMetrics, List[str], List[str], int]:
    soup = parse_html(html)
    issues: List[str] = []
    warnings: List[str] = []
    penalty = 0

    # --- Title ---
    title_tag = soup.find("title")
    title = title_tag.get_text().strip() if title_tag else ""
    title_length = len(title)
    title_status = _length_status(title, title_length, 30, 65)
    if not title:
        issues.append("تگ Title یافت نشد.")
        penalty += 15
    elif title_status != "good":
        issues.append(f"طول عنوان نامناسب است ({title_length} کاراکتر؛ بهینه: ۳۰-۶۵).")
        penalty += 5

    # --- Meta Description ---
    meta_desc_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    meta_description = meta_desc_tag.get("content", "").strip() if meta_desc_tag else ""
    meta_desc_length = len(meta_description)
    meta_description_status = _length_status(meta_description, meta_desc_length, 70, 165)
    if not meta_description:
        issues.append("توضیحات متا (Meta Description) یافت نشد.")
        penalty += 10
    elif meta_description_status != "good":
        issues.append(f"طول توضیحات متا نامناسب است ({meta_desc_length} کاراکتر؛ بهینه: ۷۰-۱۶۵).")
        penalty += 4

    # --- Headings ---
    h1_tags = soup.find_all("h1")
    h2_tags = soup.find_all("h2")
    h3_tags = soup.find_all("h3")
    h1_count = len(h1_tags)
    h2_count = len(h2_tags)
    h3_count = len(h3_tags)

    h1_list = [tag.get_text().strip() for tag in h1_tags if tag.get_text().strip()]
    h2_list = [tag.get_text().strip() for tag in h2_tags if tag.get_text().strip()]
    h3_list = [tag.get_text().strip() for tag in h3_tags if tag.get_text().strip()]

    if h1_count == 0:
        issues.append("صفحه فاقد تگ H1 است.")
        penalty += 10
    elif h1_count > 1:
        issues.append(f"چند تگ H1 یافت شد ({h1_count} عدد؛ بهتر است دقیقاً ۱ تگ H1 باشد).")
        penalty += 5

    # --- Images & Alt ---
    img_tags = soup.find_all("img")
    total_images = len(img_tags)
    images_missing_alt = sum(
        1 for img in img_tags
        if not img.get("alt") or not img.get("alt", "").strip()
    )
    # هشدار و جریمه Alt فقط در analyzers/images.py اعمال می‌شود تا دوبار شمرده نشود

    # --- Content Analysis ---
    text_soup = BeautifulSoup(html, "html.parser")
    for unneeded_tag in text_soup(["script", "style", "noscript", "template", "svg"]):
        unneeded_tag.decompose()

    clean_text = text_soup.get_text(separator=" ", strip=True)
    all_words = re.findall(r"\b[a-zA-Z\u0621-\u063A\u0641-\u064A\u0671-\u06D3\u06D5\u200c]{3,}\b", clean_text)

    word_count = len(all_words)

    if word_count < 300:
        warnings.append(f"حجم محتوای متنی کم است ({word_count} کلمه؛ حداقل ۳۰۰ کلمه پیشنهاد می‌شود).")
        penalty += 10

    html_length = len(html.encode("utf-8"))
    text_length = len(clean_text.encode("utf-8"))
    text_ratio_percent = round((text_length / html_length) * 100, 2) if html_length > 0 else 0.0

    stop_words = {
        "and", "the", "for", "with", "this", "that", "from", "are", "was",
        "این", "برای", "است", "های", "شده", "شود", "کنند", "کرد", "بود",
        "یک", "خود", "دیگر", "توسط", "روی", "همه", "اما", "اگر"
    }
    meaningful_words = [w.lower() for w in all_words if w.lower() not in stop_words]
    raw_top_keywords = Counter(meaningful_words).most_common(10)
    top_keywords = [{"word": word, "count": count} for word, count in raw_top_keywords]

    lang_tag = soup.find("html")
    lang_declared = lang_tag.get("lang", "") if lang_tag else ""
    has_favicon = bool(soup.find("link", rel=re.compile(r"^(shortcut\s+)?icon$", re.I)))

    content_metrics = ContentMetrics(
        word_count=word_count,
        reading_time_minutes=round(word_count / 200, 1),
        text_ratio_percent=text_ratio_percent,
        h1_count=h1_count,
        h2_count=h2_count,
        h3_count=h3_count,
        lang_declared=lang_declared,
        language_code=(lang_declared or "").split("-")[0].lower() or None,
        has_favicon=has_favicon,
        top_keywords=top_keywords,
    )

    # --- Social / OpenGraph / Twitter Cards ---
    def _meta_prop(property_name: str) -> str:
        tag = soup.find("meta", attrs={"property": property_name})
        if not tag:
            tag = soup.find("meta", attrs={"name": property_name})
        return tag.get("content", "").strip() if tag else ""

    og_title = _meta_prop("og:title")
    og_description = _meta_prop("og:description")
    og_image = _meta_prop("og:image")
    twitter_card = _meta_prop("twitter:card")

    social_metrics = SocialMetrics(
        og_title=og_title,
        og_description=og_description,
        og_image=og_image,
        has_og=bool(og_title or og_description or og_image),
        has_complete_og=bool(og_title and og_description and og_image),
        twitter_card=twitter_card,
        has_twitter_card=bool(twitter_card),
    )

    # --- OnPageMetrics Assembly ---
    metrics = OnPageMetrics(
        title=title,
        title_length=title_length,
        title_status=title_status,
        meta_description=meta_description,
        meta_description_length=meta_desc_length,
        meta_description_status=meta_description_status,
        h1_count=h1_count,
        h1_list=h1_list,
        h2_count=h2_count,
        h2_list=h2_list,
        h3_count=h3_count,
        h3_list=h3_list,
        total_images=total_images,
        images_missing_alt=images_missing_alt,
        content=content_metrics,
        social=social_metrics,
    )

    return metrics, issues, warnings, penalty