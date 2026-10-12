from sqlalchemy import func, select
from app.core.models import HealthCheck, Heartbeat, Integration, aware, utcnow


def scope_query(request):
    from app.core.security import is_operator
    from app.api.deps import demo_owner
    from fastapi import HTTPException

    if is_operator(request):
        return select(Integration)
    if not request.app.state.settings.demo_mode:
        raise HTTPException(401, "Operator credentials are required")
    return select(Integration).where(Integration.demo_owner == demo_owner(request))


def latest_checks(session, ids):
    if not ids:
        return {}
    ranked = (
        select(
            HealthCheck.id,
            HealthCheck.integration_id,
            func.row_number()
            .over(
                partition_by=HealthCheck.integration_id,
                order_by=(HealthCheck.checked_at.desc(), HealthCheck.id.desc()),
            )
            .label("rank"),
        )
        .where(HealthCheck.integration_id.in_(ids))
        .subquery()
    )
    return {
        check.integration_id: check
        for check in session.scalars(
            select(HealthCheck)
            .join(ranked, HealthCheck.id == ranked.c.id)
            .where(ranked.c.rank == 1)
        )
    }


def service_status(integration, latest, settings):
    reference = aware(latest.checked_at if latest else integration.created_at)
    age = max(0, (utcnow() - reference).total_seconds())
    stale = age > integration.check_interval_seconds + settings.stale_grace_seconds
    return {
        "id": integration.id,
        "name": integration.display_name,
        "endpoint": integration.endpoint,
        "status": "STALE" if stale else latest.outcome if latest else "UNKNOWN",
        "last_outcome": latest.outcome if latest else None,
        "demo_key": integration.demo_key,
        "latency_ms": round(latest.latency_ms, 2)
        if latest and latest.latency_ms is not None
        else None,
        "failure_type": latest.failure_type if latest else None,
        "last_checked_at": aware(latest.checked_at).isoformat() if latest else None,
        "check_interval_seconds": integration.check_interval_seconds,
        "age_seconds": round(age, 1),
        "stale_after_seconds": integration.check_interval_seconds
        + settings.stale_grace_seconds,
    }


def broker_available(settings):
    try:
        import redis

        with redis.Redis.from_url(
            settings.redis_url, socket_timeout=1, socket_connect_timeout=1
        ) as client:
            return client.ping()
    except Exception:
        return False


def process_health(session, settings):
    roles = (
        ("scheduler", "worker")
        if settings.task_mode == "celery"
        else ("scheduler",)
        if settings.scheduler_enabled
        else ()
    )
    missing = []
    if settings.task_mode == "celery" and not broker_available(settings):
        missing.append("broker")
    ages = {}
    for role in roles:
        value = session.get(Heartbeat, role)
        age = (utcnow() - aware(value.updated_at)).total_seconds() if value else None
        ages[role] = round(age, 1) if age is not None else None
        if age is None or age > settings.lease_seconds:
            missing.append(role)
    return {
        "status": "ready" if not missing else "not_ready",
        "database": "available",
        "mode": "scheduled" if roles else "manual",
        "heartbeat_age_seconds": ages,
        "unavailable_components": missing,
    }
