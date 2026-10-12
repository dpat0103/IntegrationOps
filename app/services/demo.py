"""Independent synthetic providers backed by the database, available to every worker."""

import asyncio
import hashlib
from datetime import timedelta
import httpx
from sqlalchemy import select, text
from app.core.db import lock_writes
from app.core.models import DemoState, Integration, utcnow

SERVICES = {
    "payment": "Payment API",
    "shipping": "Shipping API",
    "identity": "Identity API",
}
MODES = {
    "healthy",
    "slow",
    "unauthorized",
    "rate_limit",
    "server_error",
    "malformed",
    "timeout",
}


def setup_demo(session, owner, ttl_hours=24):
    lock_writes(session)
    if session.bind.dialect.name == "postgresql":
        lock_key = int.from_bytes(hashlib.sha256(owner.encode()).digest()[:7], "big")
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    expires = utcnow() + timedelta(hours=ttl_hours)
    integrations = []
    for key, title in SERVICES.items():
        existing = session.scalar(
            select(Integration).where(
                Integration.demo_owner == owner, Integration.demo_key == key
            )
        )
        if existing is None:
            existing = Integration(
                name=f"{title} :: {owner}",
                endpoint=f"https://demo.integrationops.invalid/{key}",
                demo_owner=owner,
                demo_key=key,
                method="GET",
                expected_status=200,
                timeout_ms=1500,
                latency_threshold_ms=500,
                check_interval_seconds=30,
                expected_json_key="status",
                expected_json_value="healthy",
            )
            session.add(existing)
        state = session.get(DemoState, (owner, key))
        if state is None:
            session.add(
                DemoState(
                    owner=owner,
                    service=key,
                    mode="healthy",
                    delay_seconds=0.8,
                    expires_at=expires,
                )
            )
        else:
            state.expires_at = expires
        integrations.append(existing)
    session.commit()
    return integrations


def demo_transport(session, integration):
    state = session.get(DemoState, (integration.demo_owner, integration.demo_key))
    mode = state.mode if state else "healthy"
    delay = state.delay_seconds if state else 0.8

    async def handler(request):
        if mode in ("slow", "timeout"):
            await asyncio.sleep(delay if mode == "slow" else 4)
        if mode == "unauthorized":
            return httpx.Response(401, json={"error": "access denied"})
        if mode == "rate_limit":
            return httpx.Response(
                429, headers={"Retry-After": "60"}, json={"error": "rate limited"}
            )
        if mode == "server_error":
            return httpx.Response(503, json={"error": "service unavailable"})
        if mode == "malformed":
            return httpx.Response(200, json={"state": "healthy"})
        return httpx.Response(
            200, json={"status": "healthy", "provider": integration.demo_key}
        )

    return httpx.MockTransport(handler)
