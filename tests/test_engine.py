import asyncio
import socket

import httpx
import pytest

from seo_core import engine, invoke, pipeline
from seo_core.stages import default_resolver
from seo_core.engine import AuditEngine
from seo_core.safe_http import SSRFSecurityError, is_safe_url, resolve_validated_ips
from seo_core.models import AuditReport


def _audit(url="https://example.com/"):
    return asyncio.run(AuditEngine(url).audit())


def _audit_broken_on_page(broken, url="https://example.com/"):
    def resolve(name):
        return broken if name == "on_page" else default_resolver(name)

    return asyncio.run(AuditEngine(url, resolver=resolve).audit())


def _safe(url):
    import asyncio
    return asyncio.run(is_safe_url(url))


# ---------- SSRF guard ----------

@pytest.mark.parametrize(
    "url",
    ["ftp://example.com", "http://localhost", "http://127.0.0.1", "http://0.0.0.0", "not a url"],
)
def test_unsafe_urls_rejected(url):
    assert _safe(url) is False


def test_private_ip_resolution_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 0))])
    assert _safe("https://intranet.example") is False
    with pytest.raises(SSRFSecurityError):
        resolve_validated_ips("intranet.example")


def test_public_ip_accepted(public_dns):
    assert _safe("https://example.com") is True


def test_scheme_added_when_missing():
    assert AuditEngine("example.com").url == "https://example.com"


def test_audit_blocks_private_target():
    r = _audit("http://127.0.0.1/")
    assert r.status == "error" and r.score == 0
    assert "SSRF" in r.error_message


# ---------- full audit (mocked network) ----------

def test_full_audit(mock_http):
    r = _audit()
    assert isinstance(r, AuditReport)
    assert r.status == "success", r.error_message
    assert 0 < r.score < 100
    assert r.score == r.overall_score
    assert r.on_page.h1_count == 1
    assert r.on_page.content.language_code == "fa"
    assert r.technical.status_code == 200
    assert r.technical.assets is not None
    assert r.images_audit.total_images == 2
    assert r.sitemap.has_sitemap and r.technical.has_sitemap
    assert r.technical.has_robots_txt == r.sitemap.has_robots_txt is True
    assert r.links.internal_count == 2 and r.links_arch is r.links
    assert r.local_seo.checklist["has_phone"] is True
    assert r.issues_count == len(r.issues)
    assert r.warnings_count == len(r.warnings)
    assert r.recommendations


def test_broken_links_reported_not_as_issues(mock_http):
    r = _audit()
    assert [b.url for b in r.broken_links] == ["https://example.com/missing"]
    assert r.links.broken_links_count == 1
    # جزئیات لینک خراب نباید به‌صورت dict خام وارد لیست خطاها شود
    assert not any("source_element" in i for i in r.issues + r.warnings)


def test_network_error_sets_error_status(mock_http):
    def boom(request):
        raise httpx.ConnectError("down", request=request)

    mock_http["handler"] = boom
    r = _audit()
    assert r.status == "error" and r.score == 0
    assert "Network" in r.error_message


def test_redirect_to_private_ip_blocked(mock_http, monkeypatch):
    def resolve(host, *a, **k):
        ip = "192.168.1.1" if host == "internal.example" else "93.184.216.34"
        return [(2, 1, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    mock_http["handler"] = lambda req: (
        httpx.Response(302, headers={"location": "http://internal.example/"})
        if req.url.host == "example.com"
        else httpx.Response(200, text="secret")
    )
    r = _audit()
    assert r.status == "error" and r.score == 0


def test_analyzer_failure_does_not_crash(mock_http, monkeypatch):
    def broken(*a, **k):
        raise ValueError("boom")

    r = _audit_broken_on_page(broken)
    assert r.status == "success"
    assert r.on_page.h1_count == 0
    # شکست تحلیل‌گر نباید بی‌صدا باشد: ثبت در گزارش + کاهش نمره
    assert r.failed_analyzers == ["On-page"]
    assert any("On-page" in i for i in r.issues)


def test_analyzer_failure_lowers_score(mock_http, monkeypatch):
    def broken(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(pipeline, "INCOMPLETE_AUDIT_SCORE_CAP", 100)
    monkeypatch.setattr(pipeline, "STAGE_FAILURE_PENALTY", 0)
    without_penalty = _audit_broken_on_page(broken).score
    monkeypatch.setattr(pipeline, "STAGE_FAILURE_PENALTY", 10)
    with_penalty = _audit_broken_on_page(broken).score
    assert without_penalty - with_penalty == 10


def test_failed_analyzer_caps_score(mock_http, monkeypatch):
    def broken(*a, **k):
        raise ValueError("boom")

    r = _audit_broken_on_page(broken)
    assert r.score <= pipeline.INCOMPLETE_AUDIT_SCORE_CAP
    assert r.overall_score == r.score


def test_no_failures_means_empty_failed_analyzers(mock_http):
    assert _audit().failed_analyzers == []


def test_run_audit_alias(mock_http):
    r = asyncio.run(AuditEngine("https://example.com/").run_audit())
    assert r.status == "success"


def _split_dns(monkeypatch):
    def resolve(host, *a, **k):
        ip = "10.0.0.5" if host == "intranet.example" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)


def test_redirect_to_private_host_never_requested(mock_http, monkeypatch):
    _split_dns(monkeypatch)
    hits = []

    def handler(request):
        hits.append(str(request.url))
        if request.url.host == "intranet.example":
            return httpx.Response(200, text="secret")
        return httpx.Response(302, headers={"Location": "https://intranet.example/admin"})

    mock_http["handler"] = handler
    r = _audit()
    assert r.status == "error" and r.score == 0
    assert "SSRF" in r.error_message
    assert not any("intranet.example" in h for h in hits)


def test_redirect_to_non_http_scheme_blocked(mock_http):
    mock_http["handler"] = lambda req: httpx.Response(301, headers={"Location": "file:///etc/passwd"})
    r = _audit()
    assert r.status == "error" and "SSRF" in r.error_message


def test_redirect_loop_limited(mock_http):
    hits = []

    def handler(request):
        hits.append(str(request.url))
        return httpx.Response(302, headers={"Location": "/loop"})

    mock_http["handler"] = handler
    r = _audit()
    assert r.status == "error" and "SSRF" in r.error_message
    assert len(hits) == engine.MAX_REDIRECTS + 1


def test_safe_redirect_followed(mock_http):
    from tests.conftest import site_handler

    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"Location": "/"})
        return site_handler(request)

    mock_http["handler"] = handler
    r = _audit("https://example.com/old")
    assert r.status == "success", r.error_message
    assert r.on_page.h1_count == 1
    assert r.technical.redirect_count == 1


def test_engine_assets_match_technical_analyzer(mock_http):
    """عدد نمایش‌داده‌شده در داشبورد باید همان عددی باشد که هشدار تحلیل‌گر بر اساسش است."""
    from tests.conftest import site_handler

    html = ("<html><head><title>t</title>"
            + "".join(f'<script src="/m{i}.js" type="module"></script>' for i in range(5))
            + "</head><body><h1>x</h1></body></html>")

    def handler(request):
        if request.url.path == "/":
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return site_handler(request)

    mock_http["handler"] = handler
    r = _audit("https://example.com/")
    assert r.status == "success", r.error_message
    assert r.technical.assets.total_js == 5
    assert r.technical.assets.render_blocking_js_count == 0


@pytest.mark.parametrize("encoding,expected", [
    ("gzip", True), ("br", True), ("zstd", True), ("", False), ("identity", False),
])
def test_engine_compression_from_content_encoding(mock_http, encoding, expected):
    from tests.conftest import PAGE_HTML, site_handler

    def handler(request):
        if request.url.path == "/":
            headers = {"content-type": "text/html"}
            if encoding:
                headers["content-encoding"] = encoding
            # httpx بدنه را بر اساس هدر رمزگشایی می‌کند، پس باید واقعاً فشرده باشد
            body = PAGE_HTML.encode()
            if encoding == "gzip":
                import gzip
                body = gzip.compress(body)
            elif encoding == "br":
                brotli = pytest.importorskip("brotli")
                body = brotli.compress(body)
            return httpx.Response(200, content=body, headers=headers)
        return site_handler(request)

    mock_http["handler"] = handler
    r = _audit()
    assert r.technical.is_compressed is expected

# ---------- regression: real TypeError inside an analyzer is not swallowed ----------

def test_invoke_analyzer_propagates_internal_type_error():
    async def broken(url, client=None):
        raise TypeError("bug inside analyzer")

    with pytest.raises(TypeError, match="bug inside analyzer"):
        asyncio.run(invoke._invoke_analyzer(broken, "https://example.com", client=object()))


def test_invoke_analyzer_filters_unsupported_kwargs():
    def sync_fn(html, base_url=""):
        return ("ok", [], [], 0)

    result = asyncio.run(invoke._invoke_analyzer(sync_fn, "<html>", base_url="x", client=object()))
    assert result == ("ok", [], [], 0)



def test_local_seo_penalty_skipped_for_non_local_site(mock_http):
    r_local = asyncio.run(AuditEngine("https://example.com/", local_business=True).audit())
    r_non = asyncio.run(AuditEngine("https://example.com/", local_business=False).audit())
    assert r_local.status == r_non.status == "success"
    assert r_non.score >= r_local.score
    assert any("سایت محلی تشخیص داده نشد" in w for w in r_non.warnings)
    assert not any("سایت محلی تشخیص داده نشد" in w for w in r_local.warnings)