"""
لایه شبکه امن مشترک: پین‌کردن IP در لحظه اتصال و سقف حجم پاسخ.
"""

import asyncio
import contextlib
import datetime
import ipaddress
import socket
from typing import List, Optional

import httpcore
import httpx

# سقف حجم بدنه پاسخ (پس از رفع فشرده‌سازی)
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 5


class SSRFSecurityError(httpx.RequestError):
    """خطای امنیتی ناشی از مسدودسازی آدرس‌های لوکال یا شبکه خصوصی (SSRF)."""
    pass


class ResponseTooLargeError(httpx.RequestError):
    """حجم پاسخ از سقف مجاز بیشتر است."""
    pass


def is_blocked_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    # آدرس‌های IPv4-mapped مثل ::ffff:127.0.0.1 بر اساس IPv4 داخلی بررسی می‌شوند
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_reserved
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
    )


def resolve_validated_ips(hostname: str) -> List[str]:
    """
    تفکیک DNS و اعتبارسنجی تمام IPها؛ در صورت وجود حتی یک IP ناامن استثنا پرتاب می‌کند.
    خروجی: فهرست IPهای تأییدشده.
    """
    if not hostname:
        raise SSRFSecurityError("نام هاست خالی یا نامعتبر است.")

    if hostname.lower() in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        raise SSRFSecurityError(f"دسترسی به آدرس لوکال مسدود است: {hostname}")

    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise SSRFSecurityError(f"خطا در تفکیک DNS برای {hostname}: {e}")

    ips: List[str] = []
    for item in addr_info:
        ip_str = str(item[4][0])
        try:
            blocked = is_blocked_ip(ip_str)
        except ValueError:
            raise SSRFSecurityError(f"فرمت آی‌پی نامعتبر است: {ip_str}")
        if blocked:
            raise SSRFSecurityError(f"دسترسی به آی‌پی خصوصی مسدود است: {ip_str}")
        if ip_str not in ips:
            ips.append(ip_str)
    if not ips:
        raise SSRFSecurityError(f"هیچ آی‌پی برای {hostname} یافت نشد.")
    return ips


async def is_safe_url(url: str) -> bool:
    """بررسی ناهمگام امن بودن URL (پروتکل و همه IPهای هاست)؛ DNS در thread جدا اجرا می‌شود."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        await asyncio.to_thread(resolve_validated_ips, parsed.hostname)
        return True
    except SSRFSecurityError:
        return False
    except (ValueError, OSError):
        return False


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """
    اتصال TCP فقط به IPی که همین لحظه اعتبارسنجی شده است؛
    بنابراین DNS Rebinding بین بررسی و اتصال (TOCTOU) ممکن نیست.
    SNI و بررسی گواهی TLS همچنان با نام هاست اصلی انجام می‌شود.
    """

    def __init__(self) -> None:
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        ips = await asyncio.to_thread(resolve_validated_ips, host)
        last_exc: Optional[BaseException] = None
        # همه IPهای تأییدشده به ترتیب امتحان می‌شوند (fallback بین A/AAAA)
        for ip in ips:
            try:
                return await self._inner.connect_tcp(
                    ip, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_exc = exc
        assert last_exc is not None
        raise last_exc

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise SSRFSecurityError("اتصال Unix socket مجاز نیست.")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


_EXC_MAP = {
    httpcore.ConnectTimeout: httpx.ConnectTimeout,
    httpcore.ReadTimeout: httpx.ReadTimeout,
    httpcore.WriteTimeout: httpx.WriteTimeout,
    httpcore.PoolTimeout: httpx.PoolTimeout,
    httpcore.ConnectError: httpx.ConnectError,
    httpcore.ReadError: httpx.ReadError,
    httpcore.WriteError: httpx.WriteError,
    httpcore.ProxyError: httpx.ProxyError,
    httpcore.UnsupportedProtocol: httpx.UnsupportedProtocol,
    httpcore.RemoteProtocolError: httpx.RemoteProtocolError,
    httpcore.LocalProtocolError: httpx.LocalProtocolError,
}


@contextlib.contextmanager
def _map_exceptions():
    try:
        yield
    except httpx.RequestError:
        raise
    except Exception as exc:
        for cls in type(exc).__mro__:
            if cls in _EXC_MAP:
                raise _EXC_MAP[cls](str(exc)) from exc
        raise


class _ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream) -> None:
        self._stream = stream

    async def __aiter__(self):
        with _map_exceptions():
            async for part in self._stream:
                yield part

    async def aclose(self) -> None:
        if hasattr(self._stream, "aclose"):
            await self._stream.aclose()


class _PinnedTransport(httpx.AsyncBaseTransport):
    """
    Transport مبتنی بر API عمومی httpcore (بدون دست‌زدن به صفات خصوصی httpx)
    که اتصال را از طریق _PinnedNetworkBackend برقرار می‌کند.
    """

    def __init__(self, verify: bool = True) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=verify),
            max_connections=100,
            max_keepalive_connections=20,
            keepalive_expiry=5.0,
            network_backend=_PinnedNetworkBackend(),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        with _map_exceptions():
            resp = await self._pool.handle_async_request(req)
        return httpx.Response(
            status_code=resp.status,
            headers=resp.headers,
            stream=_ResponseStream(resp.stream),
            extensions=resp.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


def make_safe_transport(verify: bool = True) -> httpx.AsyncBaseTransport:
    """Transport با بک‌اند پین‌شده؛ کلاینت باید با trust_env=False ساخته شود تا پراکسی محیطی دورش نزند."""
    return _PinnedTransport(verify=verify)


async def bounded_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    timeout: Optional[float] = None,
    max_bytes: int = MAX_RESPONSE_BYTES,
    read_body: bool = True,
) -> httpx.Response:
    """
    ارسال درخواست بدون ریدایرکت و خواندن بدنه تا سقف max_bytes.
    با read_body=False فقط وضعیت و هدرها برگردانده می‌شود.
    """
    kwargs = {} if timeout is None else {"timeout": timeout}
    request = client.build_request(method, url, **kwargs)
    response = await client.send(request, stream=True, follow_redirects=False)
    chunks: List[bytes] = []
    try:
        if read_body:
            declared = response.headers.get("Content-Length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise ResponseTooLargeError(f"حجم پاسخ ({declared} بایت) بیش از سقف مجاز است: {url}")
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ResponseTooLargeError(f"حجم پاسخ بیش از {max_bytes} بایت است: {url}")
                chunks.append(chunk)
    finally:
        await response.aclose()

    # بدنه از قبل رفع فشرده‌سازی شده؛ هدر Content-Encoding بعد از ساخت پاسخ برای گزارش بازگردانده می‌شود
    encoding = response.headers.get("Content-Encoding")
    headers = [
        (k, v) for k, v in response.headers.multi_items()
        if k.lower() not in ("content-encoding", "content-length")
    ]
    result = httpx.Response(
        response.status_code,
        headers=headers,
        content=b"".join(chunks),
        request=request,
        extensions=response.extensions,
    )
    if encoding:
        result.headers["Content-Encoding"] = encoding
    # پاسخ‌های از پیش خوانده‌شده (مثلاً MockTransport) ممکن است elapsed نداشته باشند
    try:
        result.elapsed = response.elapsed
    except RuntimeError:
        result.elapsed = datetime.timedelta(0)
    return result