from __future__ import annotations
import asyncio
import time
import uuid
from dataclasses import dataclass
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.models import HealthCheck, Integration, utcnow
from app.core.security import (
    CredentialError,
    UnsafeTarget,
    PublicTransport,
    validate_url,
    decrypted_headers,
)


@dataclass
class ProbeResult:
    outcome: str
    http_status: int | None = None
    latency_ms: float | None = None
    failure_type: str | None = None
    error_message: str | None = None


def classify_http_status(status):
    if status in (401, 403):
        return "AUTHENTICATION_FAILURE"
    if status == 429:
        return "RATE_LIMITED"
    if status >= 500:
        return "UPSTREAM_FAILURE"
    if status >= 400:
        return "HTTP_ERROR"
    return "UNEXPECTED_STATUS"


async def probe_integration(integration, transport=None, settings=None):
    settings = settings or get_settings()
    started = time.perf_counter()

    def result(outcome, failure=None, message=None, status=None):
        return ProbeResult(
            outcome, status, (time.perf_counter() - started) * 1000, failure, message
        )

    try:
        if transport is None:
            validate_url(integration.endpoint)
        headers = decrypted_headers(integration.headers_json, settings)
        if headers and not integration.endpoint.startswith("https://"):
            raise UnsafeTarget("Request headers require HTTPS")
        timeout = integration.timeout_ms / 1000
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(
                timeout=timeout,
                transport=transport or PublicTransport(),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    integration.method, integration.endpoint, headers=headers
                ) as response:
                    if response.status_code != integration.expected_status:
                        return result(
                            "FAILED",
                            classify_http_status(response.status_code),
                            f"Expected HTTP {integration.expected_status}, received {response.status_code}",
                            response.status_code,
                        )
                    size = 0
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 65536:
                            return result(
                                "FAILED",
                                "RESPONSE_VALIDATION_FAILURE",
                                "Response exceeded 64 KiB",
                                response.status_code,
                            )
                        body.extend(chunk)
                    if integration.expected_json_key:
                        import json

                        try:
                            payload = json.loads(body)
                        except (ValueError, UnicodeDecodeError):
                            return result(
                                "FAILED",
                                "RESPONSE_VALIDATION_FAILURE",
                                "Response was not valid JSON",
                                response.status_code,
                            )
                        if not isinstance(payload, dict):
                            return result(
                                "FAILED",
                                "RESPONSE_VALIDATION_FAILURE",
                                "Expected a JSON object",
                                response.status_code,
                            )
                        if integration.expected_json_key not in payload:
                            return result(
                                "FAILED",
                                "RESPONSE_VALIDATION_FAILURE",
                                "Expected response field was missing",
                                response.status_code,
                            )
                        if (
                            integration.expected_json_value is not None
                            and str(payload[integration.expected_json_key])
                            != integration.expected_json_value
                        ):
                            return result(
                                "FAILED",
                                "RESPONSE_VALIDATION_FAILURE",
                                "Expected response field had a different value",
                                response.status_code,
                            )
                    elapsed = (time.perf_counter() - started) * 1000
                    if (
                        integration.latency_threshold_ms
                        and elapsed > integration.latency_threshold_ms
                    ):
                        return result(
                            "DEGRADED",
                            "HIGH_LATENCY",
                            "Response exceeded the configured latency threshold",
                            response.status_code,
                        )
                    return result("HEALTHY", status=response.status_code)
    except UnsafeTarget:
        return result(
            "FAILED",
            "UNSAFE_TARGET",
            "Destination was blocked by the outbound target policy",
        )
    except CredentialError:
        return result(
            "FAILED",
            "CONFIGURATION_ERROR",
            "Request credentials are unavailable; operator action is required",
        )
    except (httpx.TimeoutException, asyncio.TimeoutError):
        return result(
            "FAILED",
            "TIMEOUT",
            "Service did not respond before the configured deadline",
        )
    except httpx.RequestError:
        return result("FAILED", "NETWORK_ERROR", "Could not connect to the service")


def persist_result(session, integration, execution_id, result):
    check = HealthCheck(
        execution_id=execution_id,
        integration_id=integration.id,
        outcome=result.outcome,
        http_status=result.http_status,
        latency_ms=result.latency_ms,
        failure_type=result.failure_type,
        error_message=result.error_message,
    )
    integration.last_checked_at = utcnow()
    session.add(check)
    session.flush()
    return check


async def execute_check(
    session: Session,
    integration: Integration,
    *,
    execution_id=None,
    transport=None,
    settings=None,
):
    """Low-level probe storage. Scheduled/API checks use replay-safe orchestration."""
    execution_id = execution_id or str(uuid.uuid4())
    existing = session.scalar(
        select(HealthCheck).where(HealthCheck.execution_id == execution_id)
    )
    if existing:
        if existing.integration_id != integration.id:
            raise ValueError("Execution ID belongs to a different integration")
        return existing
    result = await probe_integration(integration, transport, settings)
    return persist_result(session, integration, execution_id, result)
