from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import HealthCheck, Integration, utcnow
from app.services.metrics import CHECKS_TOTAL, CHECK_DURATION


@dataclass
class ProbeResult:
    outcome: str
    http_status: int | None = None
    latency_ms: float | None = None
    failure_type: str | None = None
    error_message: str | None = None


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


async def probe_integration(integration: Integration, transport: httpx.AsyncBaseTransport | None = None) -> ProbeResult:
    headers = json.loads(integration.headers_json) if integration.headers_json else {}
    timeout = integration.timeout_ms / 1000
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport, follow_redirects=True) as client:
            response = await client.request(integration.method, integration.endpoint, headers=headers)
        latency_ms = (time.perf_counter() - started) * 1000
        CHECK_DURATION.observe(latency_ms / 1000)

        if response.status_code != integration.expected_status:
            failure_type = classify_http_status(response.status_code)
            return ProbeResult(
                outcome="FAILED",
                http_status=response.status_code,
                latency_ms=latency_ms,
                failure_type=failure_type,
                error_message=f"Expected HTTP {integration.expected_status}, received {response.status_code}",
            )

        if integration.expected_json_key:
            try:
                payload = response.json()
            except ValueError:
                return ProbeResult(
                    outcome="FAILED",
                    http_status=response.status_code,
                    latency_ms=latency_ms,
                    failure_type="RESPONSE_VALIDATION_FAILURE",
                    error_message="Response was not valid JSON",
                )
            if integration.expected_json_key not in payload:
                return ProbeResult(
                    outcome="FAILED",
                    http_status=response.status_code,
                    latency_ms=latency_ms,
                    failure_type="RESPONSE_VALIDATION_FAILURE",
                    error_message=f"Missing expected JSON key: {integration.expected_json_key}",
                )
            if integration.expected_json_value is not None and str(payload[integration.expected_json_key]) != integration.expected_json_value:
                return ProbeResult(
                    outcome="FAILED",
                    http_status=response.status_code,
                    latency_ms=latency_ms,
                    failure_type="RESPONSE_VALIDATION_FAILURE",
                    error_message=f"Unexpected value for {integration.expected_json_key}",
                )

        if integration.latency_threshold_ms and latency_ms > integration.latency_threshold_ms:
            return ProbeResult(
                outcome="DEGRADED",
                http_status=response.status_code,
                latency_ms=latency_ms,
                failure_type="HIGH_LATENCY",
                error_message=f"Latency {latency_ms:.0f}ms exceeded {integration.latency_threshold_ms}ms threshold",
            )

        return ProbeResult(outcome="HEALTHY", http_status=response.status_code, latency_ms=latency_ms)

    except httpx.TimeoutException:
        latency_ms = (time.perf_counter() - started) * 1000
        CHECK_DURATION.observe(latency_ms / 1000)
        return ProbeResult(
            outcome="FAILED",
            latency_ms=latency_ms,
            failure_type="TIMEOUT",
            error_message=f"Request exceeded {integration.timeout_ms}ms timeout",
        )
    except httpx.RequestError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        CHECK_DURATION.observe(latency_ms / 1000)
        return ProbeResult(
            outcome="FAILED",
            latency_ms=latency_ms,
            failure_type="NETWORK_ERROR",
            error_message=str(exc),
        )


async def execute_check(
    session: Session,
    integration: Integration,
    *,
    execution_id: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> HealthCheck:
    execution_id = execution_id or str(uuid.uuid4())
    existing = session.scalar(select(HealthCheck).where(HealthCheck.execution_id == execution_id))
    if existing:
        return existing

    result = await probe_integration(integration, transport=transport)
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
    CHECKS_TOTAL.labels(outcome=result.outcome, failure_type=result.failure_type or "NONE").inc()
    return check
