from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.repositories.errors import InvalidRepositoryUrl

_LOOPBACK_HOSTS = frozenset(
    {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
)
_METADATA_IPV4 = ipaddress.ip_address("169.254.169.254")


def validate_clone_url(url: str, *, allowed_hosts: tuple[str, ...]) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise InvalidRepositoryUrl(f"Repository URL is not allowed: {url}")

    if parsed.username is not None or parsed.password is not None:
        raise InvalidRepositoryUrl(f"Repository URL is not allowed: {url}")

    hostname = parsed.hostname
    if hostname.lower() in _LOOPBACK_HOSTS or _is_blocked_host_literal(hostname):
        raise InvalidRepositoryUrl(f"Repository URL is not allowed: {url}")

    allowed = {host.lower() for host in allowed_hosts}
    if hostname.lower() not in allowed:
        raise InvalidRepositoryUrl(f"Repository URL is not allowed: {url}")

    try:
        resolved = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise InvalidRepositoryUrl(
            f"Repository URL is not allowed: {url}"
        ) from exc

    if not resolved:
        raise InvalidRepositoryUrl(f"Repository URL is not allowed: {url}")

    for info in resolved:
        address = info[4][0]
        if _is_blocked_ip(_ip_from_getaddrinfo(str(address))):
            raise InvalidRepositoryUrl(f"Repository URL is not allowed: {url}")


def _is_blocked_host_literal(hostname: str) -> bool:
    try:
        return _is_blocked_ip(ipaddress.ip_address(hostname))
    except ValueError:
        return False


def _ip_from_getaddrinfo(address: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if "%" in address:
        address = address.split("%", 1)[0]
    return ipaddress.ip_address(address)


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or ip == _METADATA_IPV4
    )
