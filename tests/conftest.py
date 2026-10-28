import socket

import httpx
import pytest

PUBLIC_IP = "93.184.216.34"

PAGE_HTML = """<html lang="fa-IR"><head>
<title>Best Widget Shop | Buy Widgets Online</title>
<meta name="description" content="We sell the best widgets at great prices.">
<meta property="og:title" content="Widgets">
<link rel="canonical" href="https://example.com/">
<meta name="viewport" content="width=device-width">
</head><body>
<h1>Welcome</h1><h2>Products</h2>
<p>We have many widgets for sale.</p>
<img src="a.jpg" alt="x" width="1" height="1"><img src="b.webp" loading="lazy">
<a href="https://example.com/about">About</a>
<a href="https://example.com/missing">Missing</a>
<a href="https://external.com/" target="_blank">Ext</a>
<a href="tel:+982112345678">call</a><a href="mailto:info@example.com">mail</a>
</body></html>"""

SITEMAP_XML = (
    '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://example.com/about</loc></url>"
    "<url><loc>https://example.com/missing</loc></url></urlset>"
)


def site_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if request.url.host == "external.com":
        return httpx.Response(200, text="ok")
    if path == "/":
        return httpx.Response(
            200,
            text=PAGE_HTML,
            headers={"content-type": "text/html", "strict-transport-security": "max-age=31536000"},
        )
    if path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nSitemap: https://example.com/sitemap.xml")
    if path == "/sitemap.xml":
        return httpx.Response(200, text=SITEMAP_XML, headers={"content-type": "application/xml"})
    if path == "/about":
        return httpx.Response(200, text="about")
    return httpx.Response(404)


@pytest.fixture
def public_dns(monkeypatch):
    """همه هاست‌ها به یک IP عمومی تفکیک می‌شوند تا تست‌ها بدون شبکه اجرا شوند."""
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, 0))]
    )


@pytest.fixture
def mock_http(monkeypatch, public_dns):
    """جایگزینی httpx.AsyncClient با کلاینتی روی MockTransport؛ handler قابل تعویض است."""
    state = {"handler": site_handler}
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.pop("verify", None)
        kwargs["transport"] = httpx.MockTransport(lambda req: state["handler"](req))
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return state
