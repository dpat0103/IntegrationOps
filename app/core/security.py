"""Operator authorization, encrypted request headers, and DNS-pinned public probes."""

import asyncio
import hmac
import ipaddress
import json
import socket
from urllib.parse import urlsplit
import httpcore
import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from httpcore._backends.auto import AutoBackend


class UnsafeTarget(ValueError):
    pass


class CredentialError(ValueError):
    pass


operator_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="OperatorBearer",
    description="Operator token for real configuration changes. Public demo controls need no token.",
)


def is_operator(request: Request):
    expected = request.app.state.settings.operator_token
    value = request.headers.get("authorization", "")
    scheme, separator, token = value.partition(" ")
    return bool(
        expected
        and separator
        and scheme.lower() == "bearer"
        and hmac.compare_digest(token.encode(), expected.encode())
    )


def require_operator(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(operator_bearer),
):
    if not is_operator(request):
        raise HTTPException(
            401,
            "Operator credentials are required",
            headers={"WWW-Authenticate": "Bearer"},
        )


def validate_url(value):
    parsed = urlsplit(str(value))
    if parsed.query or parsed.fragment:
        raise UnsafeTarget(
            "Use a path-only target URL; place credentials in encrypted headers"
        )
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise UnsafeTarget(
            "Only HTTP(S) targets without embedded credentials are supported"
        )
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost") or "%" in host:
        raise UnsafeTarget("Local destinations are not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    validate_address(address)


def validate_address(address):
    address = ipaddress.ip_address(address)
    if getattr(address, "ipv4_mapped", None):
        address = address.ipv4_mapped
    if not address.is_global:
        raise UnsafeTarget(
            "Private, local, reserved, and metadata destinations are not allowed"
        )


class PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connect to the validated IP, keeping HTTP Host and TLS SNI at the original hostname."""

    def __init__(self):
        self.backend = AutoBackend()

    async def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
        if isinstance(host, bytes):
            host = host.decode("ascii")
        try:
            result = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(
                    host, port, type=socket.SOCK_STREAM
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise httpcore.ConnectTimeout("DNS lookup timed out") from exc
        except OSError as exc:
            raise httpcore.ConnectError("DNS lookup failed") from exc
        addresses = list(dict.fromkeys(item[4][0] for item in result))
        if not addresses:
            raise httpcore.ConnectError("DNS lookup returned no addresses")
        for address in addresses:
            validate_address(address)
        last_error = None
        for address in addresses:
            try:
                return await self.backend.connect_tcp(
                    address, port, timeout, local_address, socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        raise last_error

    async def connect_unix_socket(self, *args, **kwargs):
        raise UnsafeTarget("Unix sockets are not supported")

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


class PublicTransport(httpx.AsyncHTTPTransport):
    def __init__(self):
        super().__init__(trust_env=False, retries=0)
        # HTTPX 0.28 / HTTPCore 1.0 adapter; covered by network-backend and live tests.
        self._pool._network_backend = PublicNetworkBackend()


def encrypted_headers(headers, settings):
    if not headers:
        return None
    if not settings.integration_secret_key:
        raise HTTPException(
            422, "Configure INTEGRATION_SECRET_KEY before storing request headers"
        )
    blocked = {"host", "connection", "content-length", "transfer-encoding"}
    if blocked.intersection(key.lower() for key in headers):
        raise HTTPException(422, "Routing and connection headers cannot be overridden")
    try:
        cipher = Fernet(settings.integration_secret_key.encode())
    except ValueError:
        raise HTTPException(503, "The credential encryption key is not valid")
    return "enc:" + cipher.encrypt(json.dumps(headers).encode()).decode()


def decrypted_headers(value, settings):
    if not value:
        return {}
    if not value.startswith("enc:") or not settings.integration_secret_key:
        raise CredentialError(
            "Stored request headers require encryption and a configured key"
        )
    try:
        return json.loads(
            Fernet(settings.integration_secret_key.encode()).decrypt(value[4:].encode())
        )
    except (InvalidToken, ValueError):
        raise CredentialError("Stored request headers could not be decrypted")
