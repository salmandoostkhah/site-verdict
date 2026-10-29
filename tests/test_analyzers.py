import asyncio

import httpx
import pytest

from seo_core.analyzers import images, links, local_seo, on_page, sitemap, technical
from seo_core.models import (
    ImageAuditMetrics,
    LinkArchitectureMetrics,
    OnPageMetrics,
    SitemapMetrics,
    TechnicalMetrics,
)
from tests.conftest import PAGE_HTML, SITEMAP_XML, site_handler


def _client():
    return httpx.AsyncClient(transport=httpx.MockTransport(site_handler))


# ---------- on_page ----------

def test_on_page_full_page():
    m, issues, warnings, penalty = on_page.analyze(PAGE_HTML)
    assert isinstance(m, OnPageMetrics)
    assert m.title_status == "good"
    assert m.meta_description_status == "too_short"
    assert m.h1_count == 1 and m.h1_list == ["Welcome"]
    assert m.h2_count == 1
    assert m.content.language_code == "fa"
    assert m.content.word_count > 0
    assert m.content.reading_time_minutes > 0
    assert m.social.has_og is True
    assert isinstance(penalty, int)


def test_on_page_empty_html():
    m, issues, _, penalty = on_page.analyze("")
    assert m.title_status == "missing"
    assert m.h1_count == 0
    assert len(issues) >= 3
    assert penalty > 0


def test_on_page_reading_time():
    html = "<html lang='en'><body><p>" + "word " * 400 + "</p></body></html>"
    m = on_page.analyze(html)[0]
    assert m.content.language_code == "en"
    assert m.content.reading_time_minutes == pytest.approx(2.0)


def test_word_count_ignores_digits_and_tatweel():
    # ارقام عربی-هندی نباید کلمه حساب شوند (regex قبلی ٣٤٥ را کلمه می‌شمرد)
    text = "سلام دنیا ۱۲۳۴ ٣٤٥ کـــشیده abc"
    html = f"<html lang='fa'><body><p>{text}</p></body></html>"
    m = on_page.analyze(html)[0]
    assert m.content.word_count == 3  # سلام، دنیا، abc


def test_word_count_keeps_zwnj_words_whole():
    # «می‌خواهم» با نیم‌فاصله یک کلمه است، نه «خواهم» به‌تنهایی
    text = "می\u200cخواهم کتاب\u200cها"
    html = f"<html lang='fa'><body><p>{text}</p></body></html>"
    m = on_page.analyze(html)[0]
    assert m.content.word_count == 2


# ---------- images ----------

def test_images_counts():
    m, _, _, penalty = images.analyze(PAGE_HTML)
    assert isinstance(m, ImageAuditMetrics)
    assert m.total_images == 2
    assert m.images_missing_alt == 1
    assert m.images_missing_dimensions == 1
    assert m.images_lazy_count == 1
    assert m.images_nextgen_count == 1
    assert penalty > 0


def test_images_empty_html():
    m = images.analyze("")[0]
    assert m.total_images == 0


# ---------- local_seo ----------

def test_local_seo_detects_contacts():
    data, issues, warnings = local_seo.analyze_local_seo(PAGE_HTML, "https://example.com")
    assert data["phone_numbers"] == ["+982112345678"]
    assert data["emails"] == ["info@example.com"]
    assert data["checklist"]["has_phone"] is True
    assert data["checklist"]["has_address"] is False


# ---------- links ----------

def test_links_architecture_and_broken(public_dns):
    async def run():
        async with _client() as c:
            return await links.analyze(PAGE_HTML, "https://example.com/", client=c)

    m, broken = asyncio.run(run())
    assert isinstance(m, LinkArchitectureMetrics)
    assert m.internal_count == 2 and m.external_count == 1
    assert m.insecure_target_blank_count == 1
    assert [b["url"] for b in broken] == ["https://example.com/missing"]
    assert broken[0]["status_code"] == 404
    assert m.broken_links_count == 1


# ---------- technical ----------

def test_technical_with_response():
    async def run():
        async with _client() as c:
            resp = await c.get("https://example.com/")
            return await technical.analyze("https://example.com/", response=resp, client=c)

    m, issues, warnings, penalty = asyncio.run(run())
    assert isinstance(m, TechnicalMetrics)
    assert m.status_code == 200
    assert m.has_canonical and m.has_viewport
    # robots.txt را تحلیلگر technical حدس نمی‌زند؛ موتور از sitemap پر می‌کند
    assert m.has_robots_txt is False
    assert m.security.is_https and m.security.has_hsts


def _tech(html, headers=None):
    resp = httpx.Response(200, text=html, headers=headers or {},
                          request=httpx.Request("GET", "https://example.com/"))
    return asyncio.run(technical.analyze("https://example.com/", response=resp))[0]


@pytest.mark.parametrize("html,headers,expected", [
    ('<meta name="robots" content="index, follow">', None, False),
    ('<meta name="ROBOTS" content="NoIndex">', None, True),
    ('<meta name="robots" content="none">', None, True),
    ('<meta name="googlebot" content="noindex">', None, True),
    ("<p>x</p>", {"X-Robots-Tag": "noindex"}, True),
    ("<p>x</p>", {"X-Robots-Tag": "googlebot: noindex, nofollow"}, True),
    ("<p>x</p>", {"X-Robots-Tag": "noarchive"}, False),
])
def test_technical_noindex_sources(html, headers, expected):
    assert _tech(f"<html><head>{html}</head></html>", headers).is_noindex is expected


def test_technical_render_blocking_counts():
    html = ("<html><head>"
            '<script src="/a.js"></script><script src="/b.js" async></script>'
            '<script src="/c.js" defer></script><script src="/d.js" type="module"></script>'
            '<script>inline()</script></head></html>')
    a = _tech(html).assets
    assert a.total_js == 4
    assert a.render_blocking_js_count == 1
    assert a.render_blocking_scripts == ["/a.js"]


# ---------- sitemap ----------

def test_sitemap_found_via_robots(public_dns):
    async def run():
        async with _client() as c:
            return await sitemap.analyze_sitemap("https://example.com/", c)

    m, issues, _, penalty = asyncio.run(run())
    assert isinstance(m, SitemapMetrics)
    assert m.has_sitemap and m.is_valid_xml
    assert m.sitemap_url == "https://example.com/sitemap.xml"
    assert m.total_urls == 2
    assert m.ok_count == 1 and m.broken_404_count == 1
    assert penalty > 0


def test_sitemap_missing(public_dns):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))) as c:
            return await sitemap.analyze_sitemap("https://example.com/", c)

    m, _, warnings, _ = asyncio.run(run())
    assert m.has_sitemap is False
    assert m.has_robots_txt is False and m.robots_txt_status == 404
    assert warnings


def test_sitemap_robots_present_without_sitemap(public_dns):
    def handler(r):
        if r.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:\n")
        return httpx.Response(404)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await sitemap.analyze_sitemap("https://example.com/", c)

    m, _, _, _ = asyncio.run(run())
    assert m.has_robots_txt is True and m.robots_txt_status == 200
    assert m.has_sitemap is False


def test_sitemap_request_failure(public_dns):
    def handler(r):
        raise httpx.ConnectError("boom", request=r)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await sitemap.analyze_sitemap("https://example.com/", c)

    m, _, warnings, _ = asyncio.run(run())
    assert m.has_robots_txt is False and m.robots_txt_status is None
    assert m.has_sitemap is False
    assert warnings


def test_links_redirect_to_private_ip_blocked_with_injected_client(public_dns, monkeypatch):
    import socket

    def resolve(host, *a, **k):
        ip = "10.0.0.5" if host == "intranet.example" else "93.184.216.34"
        return [(2, 1, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    hits = []

    def handler(request):
        hits.append(str(request.url))
        if request.url.host == "intranet.example":
            return httpx.Response(200)
        return httpx.Response(302, headers={"Location": "https://intranet.example/admin"})

    html = '<a href="https://example.com/go">go</a>'

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await links.analyze(html, "https://example.com/", client=c)

    m, broken = asyncio.run(run())
    assert not any("intranet.example" in h for h in hits)
    assert [b["url"] for b in broken] == ["https://example.com/go"]
    assert broken[0]["status_code"] == 0


def test_links_allow_insecure_defaults_to_settings(monkeypatch):
    from config.settings import settings

    captured = {}
    real_client = httpx.AsyncClient

    def factory(*a, **k):
        captured["verify"] = k.get("verify")
        return real_client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))

    monkeypatch.setattr(settings, "ALLOW_INSECURE_TLS", True)
    monkeypatch.setattr(httpx, "AsyncClient", factory)
    asyncio.run(links.analyze("<p>no links</p>", "https://example.com/"))
    assert captured["verify"] is False


def _split_dns(monkeypatch):
    import socket

    def resolve(host, *a, **k):
        ip = "10.0.0.5" if host == "intranet.example" else "93.184.216.34"
        return [(2, 1, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)


def test_sitemap_redirects_to_private_host_blocked(monkeypatch):
    _split_dns(monkeypatch)
    hits = []

    def handler(request):
        hits.append(str(request.url))
        if request.url.host == "intranet.example":
            return httpx.Response(200, text=SITEMAP_XML, headers={"content-type": "application/xml"})
        # هم robots.txt و هم همه کاندیداهای sitemap به هاست داخلی ریدایرکت می‌شوند
        return httpx.Response(302, headers={"Location": "https://intranet.example" + request.url.path})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await sitemap.analyze_sitemap("https://example.com/", c)

    m, _, _, _ = asyncio.run(run())
    assert not any("intranet.example" in h for h in hits)
    assert m.has_sitemap is False
    assert m.has_robots_txt is False and m.robots_txt_status is None


def test_sitemap_safe_redirect_followed(public_dns):
    def handler(request):
        if request.url.path == "/sitemap.xml":
            return httpx.Response(301, headers={"Location": "/new-sitemap.xml"})
        if request.url.path == "/new-sitemap.xml":
            return httpx.Response(200, text=SITEMAP_XML, headers={"content-type": "application/xml"})
        if request.url.path == "/robots.txt":
            return httpx.Response(301, headers={"Location": "/robots-real.txt"})
        if request.url.path == "/robots-real.txt":
            return httpx.Response(200, text="User-agent: *\n")
        return httpx.Response(200)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await sitemap.analyze_sitemap("https://example.com/", c)

    m, _, _, _ = asyncio.run(run())
    assert m.has_robots_txt is True and m.robots_txt_status == 200
    assert m.has_sitemap and m.sitemap_url == "https://example.com/new-sitemap.xml"


def test_sitemap_redirect_loop_limited(public_dns):
    hits = []

    def handler(request):
        hits.append(request.url.path)
        return httpx.Response(302, headers={"Location": request.url.path})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await sitemap.analyze_sitemap("https://example.com/", c)

    m, _, _, _ = asyncio.run(run())
    assert m.has_sitemap is False
    assert hits.count("/robots.txt") == sitemap.MAX_REDIRECTS + 1


# ---------- links: status classification ----------

def _check(handler_or_exc):
    def handler(request):
        if isinstance(handler_or_exc, Exception):
            raise handler_or_exc
        return httpx.Response(handler_or_exc)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await links.LinksAnalyzer._check_link(
                c, "https://example.org/x", asyncio.Semaphore(1))

    return asyncio.run(run())


@pytest.mark.parametrize("status,broken", [
    (200, False), (404, True), (410, True), (500, True),
    (401, False), (403, False), (429, False),
])
def test_link_status_classification(public_dns, status, broken):
    _, code, is_broken = _check(status)
    assert code == status
    assert is_broken is broken


def test_link_timeout_not_broken(public_dns):
    assert _check(httpx.ReadTimeout("slow")) == ("https://example.org/x", 0, False)


def test_link_connection_error_is_broken(public_dns):
    assert _check(httpx.ConnectError("refused")) == ("https://example.org/x", 0, True)


def test_render_blocking_split_head_and_body():
    html = ("<html><head>"
            '<script src="/h1.js"></script><script src="/h2.js" defer></script>'
            '</head><body>'
            '<script src="/b1.js"></script><script src="/b2.js" type="module"></script>'
            '</body></html>')
    a = _tech(html).assets
    assert a.render_blocking_js_count == 2
    assert a.render_blocking_head_count == 1
    assert a.render_blocking_body_count == 1
    assert a.render_blocking_scripts == ["/h1.js", "/b1.js"]

# ---------- regression: alt penalty counted once ----------

def test_alt_penalty_not_duplicated_in_on_page():
    html = "<html><body><h1>T</h1><img src='a.png'><img src='b.png'></body></html>"
    _, issues, _, _ = on_page.analyze(html)
    assert not any("Alt" in i for i in issues)


# ---------- regression: external status-0 links are not broken ----------

def _links_with_handler(handler, html):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await links.analyze_links(html, "https://example.com/", client=c)
    return asyncio.run(run())


def test_external_network_error_not_reported_broken(public_dns):
    def handler(request):
        raise httpx.ConnectError("refused")
    html = "<a href='https://other.org/x'>x</a>"
    m, broken = _links_with_handler(handler, html)
    assert broken == []
    assert m.broken_links_count == 0
    assert m.unverifiable_links == ["https://other.org/x"]


def test_internal_network_error_still_broken(public_dns):
    def handler(request):
        raise httpx.ConnectError("refused")
    html = "<a href='https://example.com/page'>p</a>"
    m, broken = _links_with_handler(handler, html)
    assert len(broken) == 1 and broken[0]["source_url"] == "https://example.com/"
    assert m.unverifiable_links == []


def test_link_candidates_all_checked_in_stable_order():
    from seo_core.analyzers.links import LinksAnalyzer as LinkArchitectureAnalyzer

    html = "".join(
        f'<a href="https://example.org/p{i}">x</a>' for i in range(120)
    ) + '<a href="https://example.org/p3">dup</a>'
    data = LinkArchitectureAnalyzer.extract_links(html, "https://example.org/")
    assert len(data["candidates"]) == 120
    assert data["candidates"][:3] == [
        "https://example.org/p0",
        "https://example.org/p1",
        "https://example.org/p2",
    ]