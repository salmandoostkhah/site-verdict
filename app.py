"""
Site Verdict - Streamlit Dashboard.

Tabs Included:
1. Technical & Performance
2. Sitemap & 404
3. On-Page & Content
4. Advanced Image SEO
5. Link Architecture
6. Social & OpenGraph Previews
7. Security & SSL
8. Local SEO & NAP
9. Issues & Recommendations
"""
from __future__ import annotations

import asyncio
import html
from urllib.parse import urlparse
import streamlit as st

from seo_core.access import get_val as _get_val
from seo_core.formatting import to_fa_digits, to_latin_digits

# Defensive Engine Import
try:
    from seo_core.engine import AuditEngine
except ImportError:
    try:
        from seo_core.engine import SEOEngine as AuditEngine
    except ImportError:
        AuditEngine = None


def safe_text(val) -> str:
    """HTML escape for safe rendering against XSS attacks."""
    if val is None:
        return ""
    return html.escape(str(val), quote=True)


def is_safe_image_url(url: str | None) -> bool:
    """
    اعتبارسنجی پروتکل تصویر برای جلوگیری از حملات XSS و اسکیماهای مخرب (مانند javascript: و data:).
    تنها پروتکل‌های امن http و https مجاز هستند.
    """
    if not url or not isinstance(url, str):
        return False
    url_cleaned = url.strip().lower()
    return url_cleaned.startswith(("http://", "https://"))


def _fm(target, label, value, **kwargs):
    """st.metric با نمایش ارقام فارسی یکدست."""
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        value = to_fa_digits(value)
    if isinstance(kwargs.get("help"), str):
        kwargs["help"] = to_fa_digits(kwargs["help"])
    return target.metric(label, value, **kwargs)




st.set_page_config(
    page_title="Site Verdict",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Custom RTL CSS
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;600;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Vazirmatn', -apple-system, BlinkMacSystemFont, sans-serif !important;
        direction: rtl;
        text-align: right;
    }
    
    .stMetric label {
        font-family: 'Vazirmatn' !important;
        font-weight: 600 !important;
    }
    
    .main-score-box {
        padding: 24px;
        border-radius: 12px;
        text-align: center;
        color: white;
        margin-bottom: 25px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
    }
    .score-good {
        background: linear-gradient(135deg, #10b981 0%, #059669 100%);
    }
    .score-warning {
        background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
    }
    .score-danger {
        background: linear-gradient(135deg, #ef4444 0%, #b91c1c 100%);
    }
    
    .preview-box {
        background: #ffffff;
        color: #202124;
        padding: 16px;
        border-radius: 8px;
        border: 1px solid #dfe1e5;
        margin: 15px 0;
        font-family: Arial, sans-serif !important;
        direction: ltr;
        text-align: left;
    }
    .google-url {
        font-size: 12px;
        color: #202124;
        margin-bottom: 4px;
    }
    .google-title {
        font-size: 18px;
        color: #1a0dab;
        text-decoration: none;
        cursor: pointer;
        font-weight: 500;
        line-height: 1.3;
    }
    .google-desc {
        font-size: 13px;
        color: #4d5156;
        margin-top: 4px;
        line-height: 1.4;
    }
    
    .social-card {
        background: #242526;
        border: 1px solid #3e4042;
        border-radius: 10px;
        overflow: hidden;
        max-width: 520px;
        margin: 15px auto;
        color: #e4e6eb;
        direction: ltr;
        text-align: left;
    }
    .social-img {
        width: 100%;
        height: 270px;
        object-fit: cover;
        background: #18191a;
    }
    .social-info {
        padding: 12px;
    }
    .social-domain {
        font-size: 11px;
        text-transform: uppercase;
        color: #b0b3b8;
    }
    .social-title {
        font-size: 16px;
        font-weight: bold;
        margin: 4px 0;
        color: #e4e6eb;
    }
    .social-desc {
        font-size: 13px;
        color: #b0b3b8;
        line-height: 1.3;
    }
    
    .tag-badge {
        display: inline-block;
        background: #374151;
        color: #f3f4f6;
        padding: 4px 10px;
        margin: 3px;
        border-radius: 6px;
        font-size: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Application Header
st.title("🚀 ممیزی هوشمند و پیشرفته سئو")
st.caption("سیستم تحلیل عمیق سئو تکنیکال، محتوا، نقشه سایت، تصاویر و هویت محلی با معماری Hardened")

with st.form("audit_form"):
    target_url = st.text_input(
        "آدرس وب‌سایت هدف را وارد کنید:",
        placeholder="https://example.com",
        help="آدرس باید به همراه پروتکل وارد شود یا پروتکل به شکل خودکار به https تبدیل خواهد شد.",
    )
    submit_button = st.form_submit_button("🚀 شروع تحلیل و ممیزی جامع")

if submit_button:
    if not target_url.strip():
        st.error("لطفاً یک آدرس وب‌سایت معتبر وارد کنید.")
    else:
        clean_url = to_latin_digits(target_url).strip()
        if not clean_url.startswith(("http://", "https://")):
            clean_url = "https://" + clean_url

        if AuditEngine is None:
            st.error("موتور ممیزی سئو لود نشد. از صحت ساختار فایل‌های پروژه مطمئن شوید.")
        else:
            with st.spinner("در حال پویش سایت، بررسی نقشه سایت، معماری لینک‌ها و تحلیل تخصصی..."):
                try:
                    engine = AuditEngine(clean_url)
                    report = asyncio.run(engine.audit())

                    if report:
                        st.session_state["seo_report"] = report
                except Exception as e:
                    st.error(f"خطا در اجرای ممیزی: {safe_text(e)}")

# Display Results
if "seo_report" in st.session_state:
    report = st.session_state["seo_report"]

    score = _get_val(report, "score", 0)
    try:
        score_int = int(score)
    except (TypeError, ValueError):
        score_int = 0

    if score_int >= 80:
        score_class = "score-good"
        score_label = "وضعیت عالی و بهینه"
    elif score_int >= 50:
        score_class = "score-warning"
        score_label = "نیازمند بهبود و اصلاح"
    else:
        score_class = "score-danger"
        score_label = "وضعیت بحرانی"

    st.markdown(
        f"""
        <div class="main-score-box {score_class}">
            <h1 style="margin:0; font-size:48px;">{to_fa_digits(score_int)} / ۱۰۰</h1>
            <h3 style="margin:5px 0 0 0;">{score_label}</h3>
            <p style="margin:5px 0 0 0; opacity:0.85;">گزارش ممیزی سئو برای: {safe_text(_get_val(report, "url"))}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Tabs Interface
    (
        tab_tech,
        tab_sitemap,
        tab_onpage,
        tab_images,
        tab_links,
        tab_social,
        tab_security,
        tab_local,
        tab_issues,
    ) = st.tabs([
        "⚙️ فنی و سرور",
        "🗺️ نقشه سایت و ۴۰۴",
        "📄 سئو داخلی و متون",
        "🖼️ سئوی تصاویر",
        "🔗 ساختار لینک‌ها",
        "🌐 پیش‌نمایش شبکه‌ها",
        "🔒 امنیت و SSL",
        "📍 سئو محلی",
        "⚠️ ایرادات و پیشنهادات",
    ])

    tech = _get_val(report, "technical", None)
    sitemap = _get_val(report, "sitemap", None)
    onpage = _get_val(report, "on_page", None)
    img_audit = _get_val(report, "images_audit", None)
    links = _get_val(report, "links_arch", _get_val(report, "links", None))
    local_seo = _get_val(report, "local_seo", None)

    # -------------------------------------------------------------
    # Tab 1: Technical & Performance
    # -------------------------------------------------------------
    with tab_tech:
        st.subheader("عملکرد سرور و شاخص‌های فنی وب‌سایت")
        col1, col2, col3, col4 = st.columns(4)
        _fm(col1, "کد وضعیت HTTP", _get_val(tech, "status_code"))
        _fm(col2, "زمان پاسخ سرور (TTFB)", f"{float(_get_val(tech, 'response_time_ms', 0) or 0):.0f} میلی‌ثانیه")
        _fm(col3, "حجم صفحه (HTML)", f"{_get_val(tech, 'page_size_kb', 0):.1f} کیلوبایت")
        _fm(col4, "تعداد ریدایرکت‌ها", _get_val(tech, "redirect_count", 0))

        st.divider()
        st.subheader("پیکربندی‌ها و قابلیت‌های ایندکس")
        t_col1, t_col2, t_col3 = st.columns(3)
        t_col1.write(f"فشرده‌سازی محتوا (Gzip/Brotli): {'✅' if _get_val(tech, 'is_compressed', False) else '❌'}")
        t_col1.write(f"تگ Viewport (موبایل‌فرندلی): {'✅' if _get_val(tech, 'has_viewport') else '❌'}")
        t_col2.write(f"تگ کنونیکال (Canonical): {'✅' if _get_val(tech, 'has_canonical') else '❌'}")
        t_col2.write(f"دستور Noindex: {'❌ مسدود' if _get_val(tech, 'is_noindex', False) else '✅ ایندکس آزاد'}")
        t_col3.write(f"فایل robots.txt: {'✅ موجود' if _get_val(tech, 'has_robots_txt') else '❌ یافت نشد'}")
        t_col3.write(f"معرفی در Sitemap: {'✅ بله' if _get_val(tech, 'has_sitemap') else '❌ خیر'}")

        st.divider()
        st.subheader("تحلیل فایل‌های استاتیک و اسکریپت‌ها")
        a_col1, a_col2, a_col3, a_col4 = st.columns(4)
        # دارایی‌ها در tech.assets (AssetMetrics) ذخیره می‌شوند، نه در سطح اول tech
        assets = _get_val(tech, "assets", None)
        _fm(a_col1, "تعداد فایل‌های CSS", _get_val(assets, "total_css", 0))
        _fm(a_col2, "تعداد اسکریپت‌های JS", _get_val(assets, "total_js", 0))
        _fm(a_col3, "کل درخواست‌های جانبی", _get_val(assets, "total_requests", 0))
        _fm(a_col4, "اسکریپت‌های مسدودکننده (Render-Blocking)", _get_val(assets, "render_blocking_js_count", 0), delta_color="inverse")
        st.caption(
            f"از این تعداد: {_get_val(assets, 'render_blocking_head_count', 0)} در <head> "
            f"(مسدودکننده اولین رندر) و {_get_val(assets, 'render_blocking_body_count', 0)} در <body> "
            "(مانع پارس، بدون async/defer)."
        )

    # -------------------------------------------------------------
    # Tab 2: Sitemap & 404
    # -------------------------------------------------------------
    with tab_sitemap:
        st.subheader("وضعیت سلامت نقشه سایت (Sitemap.xml)")
        if _get_val(sitemap, "has_sitemap"):
            st.info(f"آدرس نقشه سایت کشف‌شده: `{_get_val(sitemap, 'sitemap_url')}`")
            sm1, sm2, sm3, sm4 = st.columns(4)
            _fm(sm1, "کل لینک‌های شناسایی‌شده", _get_val(sitemap, "total_urls", 0))
            _fm(sm2, "لینک‌های نمونه‌برداری‌شده", _get_val(sitemap, "checked_urls_count", 0))
            _fm(sm3, "لینک‌های سالم (۲۰۰)", _get_val(sitemap, "ok_count", 0))
            _fm(sm4, "لینک‌های شکسته (۴۰۴)", _get_val(sitemap, "broken_404_count", 0), delta_color="inverse")

            broken_sitemap_urls = _get_val(sitemap, "broken_urls", [])
            if broken_sitemap_urls:
                st.error("❌ لینک‌های دارای خطای ۴۰۴ در نقشه سایت:")
                st.code("\n".join(broken_sitemap_urls))

            redirect_sitemap_urls = _get_val(sitemap, "redirect_urls", [])
            if redirect_sitemap_urls:
                st.warning("⚠️ لینک‌های ریدایرکت‌شده در نقشه سایت:")
                st.code("\n".join(redirect_sitemap_urls))

            items = _get_val(sitemap, "items", [])
            if items:
                with st.expander("مشاهده جدول وضعیت آدرس‌های بررسی‌شده نقشه سایت"):
                    sm_rows = []
                    for it in items:
                        sm_rows.append({
                            "آدرس URL": _get_val(it, "url"),
                            "کد وضعیت": _get_val(it, "status_code", "—"),
                            "نتیجه": _get_val(it, "status"),
                        })
                    st.dataframe(sm_rows, width="stretch")
        else:
            st.warning("هیچ فایل نقشه سایتی (sitemap.xml) برای این وب‌سایت یافت نشد.")

    # -------------------------------------------------------------
    # Tab 3: On-Page & Content
    # -------------------------------------------------------------
    with tab_onpage:
        st.subheader("پیش‌نمایش در نتایج جستجوی گوگل (SERP Snippet)")
        preview_url = _get_val(report, "url", "https://example.com")
        preview_title = _get_val(onpage, "title", "بدون عنوان")
        preview_desc = _get_val(onpage, "meta_description", "توضیحات متا برای این صفحه ثبت نشده است.")

        st.markdown(
            f"""
            <div class="preview-box">
                <div class="google-url">{safe_text(preview_url)}</div>
                <div class="google-title">{safe_text(preview_title)}</div>
                <div class="google-desc">{safe_text(preview_desc)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.divider()
        st.subheader("طول و استاندارد متادیتاها")
        m_col1, m_col2 = st.columns(2)
        _fm(m_col1, "طول تگ عنوان (Title)", f"{_get_val(onpage, 'title_length', 0)} کاراکتر", help="بازه استاندارد بین ۵۰ تا ۶۰ کاراکتر است.")
        _fm(m_col2, "طول توضیحات متا (Meta Description)", f"{_get_val(onpage, 'meta_description_length', 0)} کاراکتر", help="بازه استاندارد بین ۱۲۰ تا ۱۶۰ کاراکتر است.")

        st.divider()
        st.subheader("ساختار سرتیترها و آمار متنی")
        content = _get_val(onpage, "content", None)
        c_cnt1, c_cnt2, c_cnt3, c_cnt4 = st.columns(4)
        _fm(c_cnt1, "تعداد واژگان", _get_val(content, "word_count", 0))
        _fm(c_cnt2, "نسبت متن به کد", f"{_get_val(content, 'text_ratio_percent', 0):.1f}%")
        _fm(c_cnt3, "تعداد H1", _get_val(content, "h1_count", _get_val(onpage, "h1_count", 0)))
        _fm(c_cnt4, "تعداد H2", _get_val(content, "h2_count", _get_val(onpage, "h2_count", 0)))

        keywords = _get_val(content, "top_keywords", [])
        if keywords:
            st.write("**کلمات کلیدی پرتکرار صفحه:**")
            badges_html = ""
            for kw in keywords:
                word = kw.get("word") if isinstance(kw, dict) else getattr(kw, "word", str(kw))
                cnt = kw.get("count") if isinstance(kw, dict) else getattr(kw, "count", "")
                cnt_str = f" ({cnt})" if cnt else ""
                badges_html += f"<span class='tag-badge'>{safe_text(word)}{cnt_str}</span>"
            st.markdown(badges_html, unsafe_allow_html=True)

    # -------------------------------------------------------------
    # Tab 4: Advanced Image SEO (Dedicated Tab)
    # -------------------------------------------------------------
    with tab_images:
        st.subheader("🖼️ ممیزی تخصصی سئوی تصاویر و تجربه کاربری (CLS)")

        total_imgs = _get_val(img_audit, "total_images", _get_val(onpage, "total_images", 0))
        missing_alt = _get_val(img_audit, "images_missing_alt", _get_val(onpage, "images_missing_alt", 0))
        missing_dim = _get_val(img_audit, "images_missing_dimensions", 0)
        nextgen_cnt = _get_val(img_audit, "images_nextgen_count", 0)
        lazy_cnt = _get_val(img_audit, "images_lazy_count", 0)

        im_c1, im_c2, im_c3, im_c4, im_c5 = st.columns(5)
        _fm(im_c1, "کل تصاویر", total_imgs)
        _fm(im_c2, "بدون متن Alt", missing_alt, delta=missing_alt if missing_alt > 0 else 0, delta_color="inverse")
        _fm(im_c3, "بدون ابعاد (CLS Risk)", missing_dim, delta=missing_dim if missing_dim > 0 else 0, delta_color="inverse")
        _fm(im_c4, "فرمت نسل جدید (WebP/AVIF)", nextgen_cnt)
        _fm(im_c5, "بارگذاری تنبل (Lazy)", lazy_cnt)

        st.divider()

        if missing_alt > 0:
            st.error(f"❌ تعداد {missing_alt} تصویر فاقد صفت alt هستند که موجب افت رتبه سئو و اختلال در دسترسی‌پذیری می‌شود.")
        else:
            st.success("✅ تمامی تصاویر صفحه دارای متن جایگزین (Alt) مناسب هستند.")

        if missing_dim > 0:
            st.warning(f"⚠️ تعداد {missing_dim} تصویر فاقد ویژگی‌های صریح width و height می‌باشند. این موضوع ریسک پرش صفحه (Cumulative Layout Shift) را افزایش می‌دهد.")

        details = _get_val(img_audit, "images_details", [])
        if details:
            st.subheader("فهرست و مشخصات کامل تصاویر صفحه")
            details_rows = []
            for item in details:
                details_rows.append({
                    "آدرس تصویر (SRC)": _get_val(item, "src"),
                    "متن Alt": _get_val(item, "alt", "—"),
                    "دارای Alt": "✅" if _get_val(item, "has_alt") else "❌",
                    "دارای ابعاد": "✅" if _get_val(item, "has_dimensions") else "❌",
                    "عرض (Width)": _get_val(item, "width", "—"),
                    "ارتفاع (Height)": _get_val(item, "height", "—"),
                    "نسل جدید": "✅" if _get_val(item, "is_nextgen") else "❌",
                    "Lazy Load": "✅" if _get_val(item, "is_lazy") else "❌",
                    "فرمت": _get_val(item, "format", "—"),
                })
            st.dataframe(details_rows, width="stretch")
        else:
            missing_alt_list = _get_val(onpage, "images_without_alt_list", [])
            if missing_alt_list:
                st.subheader("فهرست تصاویر بدون Alt:")
                st.code("\n".join(missing_alt_list))

    # -------------------------------------------------------------
    # Tab 5: Link Architecture
    # -------------------------------------------------------------
    with tab_links:
        st.subheader("معماری و توزیع پیوندهای صفحه")
        l1, l2, l3, l4 = st.columns(4)
        _fm(l1, "لینک‌های داخلی", _get_val(links, "internal_count", _get_val(links, "internal_links_count", 0)))
        _fm(l2, "لینک‌های خارجی", _get_val(links, "external_count", _get_val(links, "external_links_count", 0)))
        _fm(l3, "لینک‌های Nofollow", _get_val(links, "nofollow_count", _get_val(links, "nofollow_links_count", 0)))
        _fm(l4, "لینک‌های ناامن (Target=_blank)", _get_val(links, "insecure_target_blank_count", 0), delta_color="inverse")

        unverifiable = _get_val(links, "unverifiable_links", []) or []
        if unverifiable:
            st.divider()
            st.warning(
                f"❓ لینک‌های بررسی‌نشدنی ({to_fa_digits(len(unverifiable))} مورد): "
                "سرور مقصد پاسخ نداد؛ معمولاً به‌دلیل مسدودسازی ربات و نه شکسته بودن لینک."
            )
            st.code("\n".join(str(u) for u in unverifiable))

        anchors = _get_val(links, "top_anchors", [])
        if anchors:
            st.divider()
            st.subheader("انکرتکست‌های پرتکرار (Anchor Texts)")
            anchors_html = ""
            for anc in anchors:
                text = anc.get("text") if isinstance(anc, dict) else getattr(anc, "text", str(anc))
                cnt = anc.get("count") if isinstance(anc, dict) else getattr(anc, "count", "")
                cnt_str = f" ({cnt})" if cnt else ""
                anchors_html += f"<span class='tag-badge'>{safe_text(text)}{cnt_str}</span>"
            st.markdown(anchors_html, unsafe_allow_html=True)

    # -------------------------------------------------------------
    # Tab 6: Social & OpenGraph Previews (Patched & Hardened)
    # -------------------------------------------------------------
    with tab_social:
        st.subheader("پیش‌نمایش اشتراک‌گذاری در شبکه‌های اجتماعی (Open Graph / Twitter)")
        social = _get_val(onpage, "social", None)

        s_col1, s_col2, s_col3 = st.columns(3)
        s_col1.write(f"تگ‌های Open Graph کامل: {'✅' if _get_val(social, 'has_complete_og') else '❌'}")
        s_col2.write(f"حداقل تگ‌های OG: {'✅' if _get_val(social, 'has_og') else '❌'}")
        s_col3.write(f"کارت توییتر (Twitter Card): {'✅' if _get_val(social, 'has_twitter_card') else '❌'}")

        og_img = _get_val(social, "og_image", "")
        og_title = _get_val(social, "og_title", _get_val(onpage, "title", "بدون عنوان"))
        og_desc = _get_val(social, "og_description", _get_val(onpage, "meta_description", "بدون توضیحات"))

        parsed_domain = urlparse(_get_val(report, "url", "")).netloc

        # گارد امنیتی: جلوگیری از تزریق اسکیماهای خطرناک مانند javascript: در تگ img
        if og_img and is_safe_image_url(og_img):
            img_markup = f'<img src="{safe_text(og_img)}" class="social-img" alt="OG Image">'
        elif og_img and not is_safe_image_url(og_img):
            img_markup = '<div style="height:140px; background:#18191a; display:flex; align-items:center; justify-content:center; color:#ff4d4f; font-size:13px;">آدرس تصویر Open Graph به دلیل پروتکل ناامن مسدود شد</div>'
        else:
            img_markup = '<div style="height:140px; background:#18191a; display:flex; align-items:center; justify-content:center; color:#777;">تصویر Open Graph تنظیم نشده است</div>'

        st.markdown(
            f"""
            <div class="social-card">
                {img_markup}
                <div class="social-info">
                    <div class="social-domain">{safe_text(parsed_domain)}</div>
                    <div class="social-title">{safe_text(og_title)}</div>
                    <div class="social-desc">{safe_text(og_desc)}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # -------------------------------------------------------------
    # Tab 7: Security & SSL
    # -------------------------------------------------------------
    with tab_security:
        st.subheader("امنیت سرور، ارتباطات و گواهینامه SSL")
        sec = _get_val(tech, "security", None)

        sec_col1, sec_col2, sec_col3, sec_col4 = st.columns(4)
        sec_col1.write(f"پروتکل امن HTTPS: {'✅' if _get_val(sec, 'is_https') else '❌'}")
        sec_col2.write(f"پیکربندی HSTS: {'✅' if _get_val(sec, 'has_hsts', _get_val(sec, 'hsts_enabled')) else '❌'}")
        sec_col3.write(f"هدر X-Frame-Options: {'✅' if _get_val(sec, 'has_x_frame_options') else '❌'}")
        sec_col4.write(f"هدر Content Security Policy: {'✅' if _get_val(sec, 'has_csp') else '❌'}")

        mixed = _get_val(sec, "mixed_content_urls", _get_val(sec, "mixed_content", []))
        if mixed:
            st.divider()
            st.error(f"❌ خطای محتوای ترکیبی (Mixed Content) یافت شد ({len(mixed)} منبع غیرامن):")
            st.code("\n".join(mixed))
        else:
            st.success("✅ هیچ محتوای ترکیبی و ناامنی در صفحه یافت نشد.")

    # -------------------------------------------------------------
    # Tab 8: Local SEO & NAP
    # -------------------------------------------------------------
    with tab_local:
        st.subheader("سئوی محلی (Local SEO) و هویت کسب‌وکار")
        loc_score = _get_val(local_seo, "local_score", 0)

        loc_m1, loc_m2, loc_m3, loc_m4 = st.columns(4)
        _fm(loc_m1, "امتیاز سئو محلی", f"{to_fa_digits(loc_score)} / ۱۰۰")
        _fm(loc_m2, "اسکیما NAP", "✅ دارد" if (bool(_get_val(local_seo, "has_nap_schema", False)) or bool(_get_val(local_seo, "has_local_schema", False))) else "❌ ندارد")
        _fm(loc_m3, "مختصات جغرافیایی", "✅ دارد" if _get_val(local_seo, "has_geo_coordinates", _get_val(local_seo, "has_geo_meta")) else "❌ ندارد")
        _fm(loc_m4, "نقشه گوگل تعبیه‌شده", "✅ دارد" if _get_val(local_seo, "has_google_maps_embed", _get_val(local_seo, "has_map_embed")) else "❌ ندارد")

        phones = _get_val(local_seo, "detected_telephones", _get_val(local_seo, "phone_numbers", []))
        emails = _get_val(local_seo, "detected_emails", _get_val(local_seo, "emails", []))

        st.divider()
        lp_col1, lp_col2 = st.columns(2)
        with lp_col1:
            st.write("**شماره‌های تماس شناسایی شده:**")
            if phones:
                for p in phones:
                    st.write(f"📞 `{safe_text(p)}`")
            else:
                st.caption("هیچ شماره تماسی یافت نشد.")

        with lp_col2:
            st.write("**ایمیل‌های شناسایی شده:**")
            if emails:
                for e in emails:
                    st.write(f"✉️ `{safe_text(e)}`")
            else:
                st.caption("هیچ ایمیلی یافت نشد.")

        chk = _get_val(local_seo, "checklist", {})
        if chk:
            st.divider()
            st.subheader("چک‌لیست استانداردهای سئو محلی")
            for k, v in chk.items():
                st.write(f"{'✅' if v else '❌'} {safe_text(k)}")

    # -------------------------------------------------------------
    # Tab 9: Issues & Recommendations
    # -------------------------------------------------------------
    with tab_issues:
        st.subheader("فهرست ایرادات، هشدارها و توصیه‌های کلیدی سئو")
        issues = _get_val(report, "issues", [])
        warnings = _get_val(report, "warnings", [])
        recommendations = _get_val(report, "recommendations", [])
        broken = _get_val(report, "broken_links", [])

        if not issues and not warnings and not broken:
            st.balloons()
            st.success("🎉 تبریک! هیچ ایراد بحرانی یا هشداری در صفحه پیدا نشد.")

        if issues:
            st.error(f"🔴 ایرادات بحرانی ({to_fa_digits(len(issues))} مورد):")
            for iss in issues:
                st.markdown(f"- {safe_text(iss)}")

        if warnings:
            st.warning(f"🟡 هشدارهای نیازمند بررسی ({to_fa_digits(len(warnings))} مورد):")
            for w in warnings:
                st.markdown(f"- {safe_text(w)}")

        if broken:
            st.error(f"🔗 پیوندهای شکسته داخل صفحه ({len(broken)} مورد):")
            for b in broken:
                url_b = _get_val(b, "url")
                code_b = _get_val(b, "status_code")
                st.write(f"- `{url_b}` (وضعیت: {code_b})")

        if recommendations:
            st.divider()
            st.subheader("💡 توصیه‌های هوشمند برای بهبود سئو:")
            for rec in recommendations:
                st.info(f"👉 {safe_text(rec)}")