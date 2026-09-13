"""Guard server-side URL fetches against SSRF.

Only public http(s) URLs are allowed: the host must resolve exclusively to
public addresses (no loopback, private, link-local, reserved or multicast).
"""

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    """Raised when a URL must not be fetched by the server."""


def _is_public_ip(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%", 1)[0])  # drop an IPv6 zone id like %en0
    if ip.version == 6 and ip.ipv4_mapped:  # ::ffff:127.0.0.1 is really 127.0.0.1
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def check_public_url(url: str) -> str:
    """Return the URL if it is safe to fetch, else raise UnsafeURLError."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError("Only http(s) URLs are allowed")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no host")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as e:
        raise UnsafeURLError(f"Host does not resolve: {host}") from e
    addrs = {info[4][0] for info in infos}
    if not addrs or not all(_is_public_ip(a) for a in addrs):
        raise UnsafeURLError("URL points to a private or local address")
    return url


def is_public_url(url: str) -> bool:
    try:
        check_public_url(url)
        return True
    except UnsafeURLError:
        return False


async def fetch_public(url: str, timeout: float = 15.0, max_redirects: int = 3):
    """GET a public URL, re-checking every redirect hop. Returns httpx.Response."""
    from urllib.parse import urljoin

    import httpx

    current = check_public_url(url)
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
        for _ in range(max_redirects + 1):
            resp = await client.get(current)
            location = resp.headers.get("location")
            if resp.is_redirect and location:
                current = check_public_url(urljoin(current, location))
                continue
            return resp
    raise UnsafeURLError("Too many redirects")
