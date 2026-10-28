"""
تست‌های خودکار SSRF و سقف حجم پاسخ؛ کاملاً محلی و بدون اتصال به سرویس خارجی.
"""

import asyncio
import functools
import gzip
import socket

import httpx
import pytest

from seo_core import safe_http
from seo_core.safe_http import (
    ResponseTooLargeError,
    SSRFSecurityError,
    bounded_request,
    is_blocked_ip,
    make_safe_transport,
    resolve_validated_ips,
)


def run_async(fn):
    """اجرای تست async بدون نیاز به افزونهٔ pytest-asyncio."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


def _fake_dns(monkeypatch, *ips):
    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.169.254",
    "0.0.0.0", "::1", "fe80::1", "::ffff:127.0.0.1", "224.0.0.1",
])
def test_blocked_ips(ip):
    assert is_blocked_ip(ip)


def test_public_ip_allowed():
    assert not is_blocked_ip("93.184.216.34")


def test_mixed_dns_answer_rejected(monkeypatch):
    # یک IP خصوصی در کنار IP عمومی کل پاسخ را نامعتبر می‌کند
    _fake_dns(monkeypatch, "93.184.216.34", "127.0.0.1")
    with pytest.raises(SSRFSecurityError):
        resolve_validated_ips("evil.test")


def test_localhost_name_rejected():
    with pytest.raises(SSRFSecurityError):
        resolve_validated_ips("localhost")


@run_async
async def test_connect_pins_validated_ip(monkeypatch):
    _fake_dns(monkeypatch, "93.184.216.34")
    backend = safe_http._PinnedNetworkBackend()
    seen = {}

    async def fake_connect(host, port, **kwargs):
        seen["host"] = host
        raise httpx.ConnectError("stop")

    monkeypatch.setattr(backend._inner, "connect_tcp", fake_connect)
    with pytest.raises(httpx.ConnectError):
        await backend.connect_tcp("example.test", 443)
    assert seen["host"] == "93.184.216.34"


@run_async
async def test_connect_falls_back_to_next_validated_ip(monkeypatch):
    import httpcore
    monkeypatch.setattr(
        safe_http, "resolve_validated_ips", lambda host: ["93.184.216.34", "93.184.216.35"]
    )
    backend = safe_http._PinnedNetworkBackend()
    tried = []

    async def fake_connect(host, port, **kwargs):
        tried.append(host)
        if host.endswith(".34"):
            raise httpcore.ConnectError("down")
        return "stream"

    monkeypatch.setattr(backend._inner, "connect_tcp", fake_connect)
    assert await backend.connect_tcp("example.test", 443) == "stream"
    assert tried == ["93.184.216.34", "93.184.216.35"]


@run_async
async def test_dns_rebinding_blocked_at_connect(monkeypatch):
    # بررسی اولیه عمومی بوده اما در لحظه اتصال DNS به loopback تغییر کرده است
    _fake_dns(monkeypatch, "127.0.0.1")
    async with httpx.AsyncClient(transport=make_safe_transport(), trust_env=False) as client:
        with pytest.raises(SSRFSecurityError):
            await client.get("http://rebind.test:8765/")


@run_async
async def test_unix_socket_rejected():
    with pytest.raises(SSRFSecurityError):
        await safe_http._PinnedNetworkBackend().connect_unix_socket("/tmp/x.sock")


def _mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@run_async
async def test_size_cap_by_content_length():
    def handler(request):
        return httpx.Response(200, headers={"Content-Length": "999999"}, content=b"x")
    async with _mock_client(handler) as client:
        with pytest.raises(ResponseTooLargeError):
            await bounded_request(client, "GET", "https://a.test/", max_bytes=1000)


@run_async
async def test_size_cap_by_streamed_bytes():
    async def body():
        for _ in range(20):
            yield b"x" * 100

    def handler(request):
        return httpx.Response(200, content=body())
    async with _mock_client(handler) as client:
        with pytest.raises(ResponseTooLargeError):
            await bounded_request(client, "GET", "https://a.test/", max_bytes=1000)


@run_async
async def test_decompression_bomb_capped():
    bomb = gzip.compress(b"\0" * 100_000)

    def handler(request):
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=bomb)
    async with _mock_client(handler) as client:
        with pytest.raises(ResponseTooLargeError):
            await bounded_request(client, "GET", "https://a.test/", max_bytes=10_000)


@run_async
async def test_small_response_passes_and_keeps_encoding_header():
    def handler(request):
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=gzip.compress(b"hello"))
    async with _mock_client(handler) as client:
        resp = await bounded_request(client, "GET", "https://a.test/")
    assert resp.text == "hello"
    assert resp.headers["Content-Encoding"] == "gzip"


@run_async
async def test_read_body_false_skips_cap():
    def handler(request):
        return httpx.Response(200, headers={"Content-Length": "999999"}, content=b"x")
    async with _mock_client(handler) as client:
        resp = await bounded_request(client, "HEAD", "https://a.test/", max_bytes=10, read_body=False)
    assert resp.status_code == 200


@run_async
async def test_redirect_not_followed_automatically():
    def handler(request):
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/"})
    async with _mock_client(handler) as client:
        resp = await bounded_request(client, "GET", "https://a.test/")
    assert resp.status_code == 302