from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import HealthCheck, Integration, utcnow
from app.core.security import UnsafeEndpointError, decode_headers, validate_resolved_endpoint
from app.services.metrics import CHECKS_TOTAL, CHECK_DURATION


@dataclass
class ProbeResult:
    outcome: str
    http_status: int | None = None
    latency_ms: float | None = None
    failure_type: str | None = None
    error_message: str | None = None
    retry_after_seconds: int | None = None
    response_content_type: str | None = None
    response_size_bytes: int | None = None


def classify_http_status(status: int) -> str:
    if status in (401, 403):
        return "AUTHENTICATION_FAILURE"
    if status == 429:
        return "RATE_LIMITED"
    if status >= 500:
        return "UPSTREAM_FAILURE"
    if status >= 400:
        return "HTTP_ERROR"
    return "UNEXPECTED_STATUS"


def _retry_after_seconds(response: httpx.Response) -> int | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        return None


async def probe_integration(
    integration: Integration,
    transport: httpx.AsyncBaseTransport | None = None,
    *,
    allow_private_endpoints: bool = False,
    integration_secret_key: str | None = None,
) -> ProbeResult:
    # Mock transports are used by tests and never touch the network.
    if transport is None:
        try:
            await validate_resolved_endpoint(integration.endpoint, allow_private=allow_private_endpoints)
        except UnsafeEndpointError as exc:
            return ProbeResult(outcome="FAILED", failure_type="UNSAFE_ENDPOINT", error_message=str(exc))

    headers = decode_headers(integration.headers_json, integration_secret_key)
    timeout = integration.timeout_ms / 1000
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport, follow_redirects=False) as client:
            response = await client.request(integration.method, integration.endpoint, headers=headers)
        latency_ms = (time.perf_counter() - started) * 1000
        CHECK_DURATION.observe(latency_ms / 1000)
        content_type = response.headers.get("content-type")
        response_size = len(response.content)

        if response.status_code != integration.expected_status:
            failure_type = classify_http_status(response.status_code)
            return ProbeResult(
                outcome="FAILED",
                http_status=response.status_code,
                latency_ms=latency_ms,
                failure_type=failure_type,
                error_message=f"Expected HTTP {integration.expected_status}, received {response.status_code}",
                retry_after_seconds=_retry_after_seconds(response),
                response_content_type=content_type,
                response_size_bytes=response_size,
            )

        if integration.expected_json_key:
            try:
                payload = response.json()
            except ValueError:
                return ProbeResult(
                    outcome="FAILED", http_status=response.status_code, latency_ms=latency_ms,
                    failure_type="RESPONSE_VALIDATION_FAILURE", error_message="Response was not valid JSON",
                    response_content_type=content_type, response_size_bytes=response_size,
                )
            if integration.expected_json_key not in payload:
                return ProbeResult(
                    outcome="FAILED", http_status=response.status_code, latency_ms=latency_ms,
                    failure_type="RESPONSE_VALIDATION_FAILURE",
                    error_message=f"Missing expected JSON key: {integration.expected_json_key}",
                    response_content_type=content_type, response_size_bytes=response_size,
                )
            if integration.expected_json_value is not None and str(payload[integration.expected_json_key]) != integration.expected_json_value:
                return ProbeResult(
                    outcome="FAILED", http_status=response.status_code, latency_ms=latency_ms,
                    failure_type="RESPONSE_VALIDATION_FAILURE",
                    error_message=f"Unexpected value for {integration.expected_json_key}",
                    response_content_type=content_type, response_size_bytes=response_size,
                )

        if integration.latency_threshold_ms and latency_ms > integration.latency_threshold_ms:
            return ProbeResult(
                outcome="DEGRADED", http_status=response.status_code, latency_ms=latency_ms,
                failure_type="HIGH_LATENCY",
                error_message=f"Latency {latency_ms:.0f}ms exceeded {integration.latency_threshold_ms}ms threshold",
                response_content_type=content_type, response_size_bytes=response_size,
            )

        return ProbeResult(
            outcome="HEALTHY", http_status=response.status_code, latency_ms=latency_ms,
            response_content_type=content_type, response_size_bytes=response_size,
        )

    except httpx.TimeoutException:
        latency_ms = (time.perf_counter() - started) * 1000
        CHECK_DURATION.observe(latency_ms / 1000)
        return ProbeResult(outcome="FAILED", latency_ms=latency_ms, failure_type="TIMEOUT", error_message=f"Request exceeded {integration.timeout_ms}ms timeout")
    except httpx.RequestError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        CHECK_DURATION.observe(latency_ms / 1000)
        return ProbeResult(outcome="FAILED", latency_ms=latency_ms, failure_type="NETWORK_ERROR", error_message=str(exc))


async def execute_check(
    session: Session,
    integration: Integration,
    *,
    execution_id: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    allow_private_endpoints: bool = False,
    integration_secret_key: str | None = None,
) -> HealthCheck:
    execution_id = execution_id or str(uuid.uuid4())
    existing = session.scalar(select(HealthCheck).where(HealthCheck.execution_id == execution_id))
    if existing:
        return existing

    result = await probe_integration(
        integration,
        transport=transport,
        allow_private_endpoints=allow_private_endpoints,
        integration_secret_key=integration_secret_key,
    )
    check = HealthCheck(
        execution_id=execution_id,
        integration_id=integration.id,
        outcome=result.outcome,
        http_status=result.http_status,
        latency_ms=result.latency_ms,
        failure_type=result.failure_type,
        error_message=result.error_message,
        retry_after_seconds=result.retry_after_seconds,
        response_content_type=result.response_content_type,
        response_size_bytes=result.response_size_bytes,
    )
    integration.last_checked_at = utcnow()
    session.add(check)
    session.flush()
    CHECKS_TOTAL.labels(outcome=result.outcome, failure_type=result.failure_type or "NONE").inc()
    return check
