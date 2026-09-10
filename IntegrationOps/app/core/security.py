from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import socket
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken


BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "metadata",
}
BLOCKED_METADATA_IPS = {"169.254.169.254"}


class UnsafeEndpointError(ValueError):
    pass


def _is_unsafe_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or str(ip) in BLOCKED_METADATA_IPS
    )


def validate_endpoint_url(url: str, *, allow_private: bool = False) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeEndpointError("Endpoint must be an http(s) URL with a hostname")
    host = parsed.hostname.lower().rstrip(".")
    if allow_private:
        return
    if host in BLOCKED_HOSTNAMES or host.endswith(".localhost") or _is_unsafe_ip(host):
        raise UnsafeEndpointError("Private, loopback, link-local, or metadata endpoints are not allowed")


async def validate_resolved_endpoint(url: str, *, allow_private: bool = False) -> None:
    validate_endpoint_url(url, allow_private=allow_private)
    if allow_private:
        return
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeEndpointError(f"Endpoint hostname could not be resolved: {exc}") from exc
    for info in infos:
        address = info[4][0]
        if _is_unsafe_ip(address):
            raise UnsafeEndpointError("Endpoint resolves to a private, loopback, link-local, or metadata address")


def _fernet(secret_key: str | None) -> Fernet | None:
    if not secret_key:
        return None
    # Derive a valid Fernet key from any high-entropy deployment secret. This
    # works with platform-generated secrets as well as Fernet-formatted keys.
    derived = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest())
    return Fernet(derived)


def encode_headers(headers: dict[str, str] | None, secret_key: str | None) -> str | None:
    if not headers:
        return None
    raw = json.dumps(headers, separators=(",", ":")).encode()
    fernet = _fernet(secret_key)
    if fernet:
        return "fernet:" + fernet.encrypt(raw).decode()
    return "plain:" + raw.decode()


def decode_headers(value: str | None, secret_key: str | None) -> dict[str, str]:
    if not value:
        return {}
    if value.startswith("fernet:"):
        fernet = _fernet(secret_key)
        if not fernet:
            raise RuntimeError("INTEGRATION_SECRET_KEY is required to decrypt stored headers")
        try:
            raw = fernet.decrypt(value.removeprefix("fernet:").encode())
        except InvalidToken as exc:
            raise RuntimeError("Stored integration headers could not be decrypted") from exc
        return json.loads(raw)
    if value.startswith("plain:"):
        return json.loads(value.removeprefix("plain:"))
    # Backward compatibility with the first MVP format.
    return json.loads(value)


def generate_fernet_key() -> str:
    return Fernet.generate_key().decode()
