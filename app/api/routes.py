import math
import asyncio
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from app.api.deps import demo_owner, get_db, same_origin, service_for_request
from app.core.db import lock_writes
from app.core.models import (
    CheckRun,
    DemoState,
    HealthCheck,
    Incident,
    Integration,
    utcnow,
)
from app.core.schemas import (
    CheckRead,
    DemoScenario,
    IncidentRead,
    IntegrationCreate,
    IntegrationRead,
    IntegrationUpdate,
    Overview,
    RunRead,
    SimulatorState,
)
from app.core.security import (
    UnsafeTarget,
    encrypted_headers,
    require_operator,
    validate_url,
)
from app.services.demo import setup_demo
from app.services.jobs import RunBusy, RunExhausted, reserve_run
from app.services.orchestrator import run_integration_check
from app.services.status import (
    latest_checks,
    process_health,
    scope_query,
    service_status,
)

router = APIRouter(prefix="/api")


def integration_read(integration):
    result = IntegrationRead.model_validate(integration).model_dump()
    result["name"] = integration.display_name
    return result


def checked_url(endpoint):
    try:
        validate_url(endpoint)
    except UnsafeTarget as exc:
        raise HTTPException(422, str(exc))
    return str(endpoint)


@router.get("/health/live")
def liveness():
    return {"status": "alive", "service": "IntegrationOps"}


@router.get("/health/ready")
@router.get("/health")
def readiness(request: Request, session=Depends(get_db)):
    try:
        session.execute(select(1))
        result = process_health(session, request.app.state.settings)
        return JSONResponse(
            result, status_code=200 if result["status"] == "ready" else 503
        )
    except SQLAlchemyError:
        return JSONResponse(
            {"status": "not_ready", "database": "unavailable"}, status_code=503
        )


@router.get("/config")
def configuration(request: Request):
    settings = request.app.state.settings
    return {
        "demo_mode": settings.demo_mode,
        "automatic_checks": settings.scheduler_enabled
        or settings.task_mode == "celery",
        "task_mode": settings.task_mode,
        "failure_threshold": settings.failure_threshold,
        "recovery_threshold": settings.recovery_threshold,
        "stale_grace_seconds": settings.stale_grace_seconds,
        "recovery_requires": "HEALTHY",
        "retention_days": settings.retention_days,
    }


@router.post(
    "/integrations",
    response_model=IntegrationRead,
    status_code=201,
    dependencies=[Depends(require_operator)],
)
def create_integration(
    payload: IntegrationCreate, request: Request, session=Depends(get_db)
):
    values = payload.model_dump(exclude={"headers"})
    values["endpoint"] = checked_url(payload.endpoint)
    values["headers_json"] = encrypted_headers(
        payload.headers, request.app.state.settings
    )
    integration = Integration(**values)
    session.add(integration)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Integration name already exists")
    return integration_read(integration)


@router.get("/integrations", response_model=list[IntegrationRead])
def integrations(request: Request, session=Depends(get_db)):
    return [
        integration_read(item)
        for item in session.scalars(scope_query(request).order_by(Integration.id))
    ]


@router.get("/integrations/{integration_id}", response_model=IntegrationRead)
def get_integration(integration_id: int, request: Request, session=Depends(get_db)):
    return integration_read(service_for_request(session, integration_id, request))


@router.patch(
    "/integrations/{integration_id}",
    response_model=IntegrationRead,
    dependencies=[Depends(require_operator)],
)
def update_integration(
    integration_id: int,
    payload: IntegrationUpdate,
    request: Request,
    session=Depends(get_db),
):
    integration = service_for_request(session, integration_id, request)
    if integration.demo_owner:
        raise HTTPException(
            403, "Use the constrained demo controls for simulated services"
        )
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "headers":
            integration.headers_json = encrypted_headers(
                value, request.app.state.settings
            )
        else:
            setattr(
                integration, key, checked_url(value) if key == "endpoint" else value
            )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Integration name already exists")
    return integration_read(integration)


@router.delete(
    "/integrations/{integration_id}",
    status_code=204,
    dependencies=[Depends(require_operator)],
)
def delete_integration(integration_id: int, request: Request, session=Depends(get_db)):
    integration = service_for_request(session, integration_id, request)
    session.delete(integration)
    session.commit()


@router.post("/integrations/{integration_id}/check")
async def check(integration_id: int, request: Request, session=Depends(get_db)):
    same_origin(request)
    integration = service_for_request(session, integration_id, request)
    if not integration.active:
        raise HTTPException(409, "Service monitoring is paused")
    settings = request.app.state.settings
    if integration.demo_owner:
        from app.services.limits import demo_budget

        demo_budget(session, integration.demo_owner)
    try:
        if settings.task_mode == "celery":
            run, publish = reserve_run(session, integration_id, settings)
            if not run:
                raise HTTPException(409, "Service monitoring is paused")
            if publish:
                from app.tasks import check_integration

                try:
                    await asyncio.to_thread(
                        check_integration.apply_async,
                        args=[run.execution_id],
                        task_id=run.execution_id,
                    )
                except Exception:
                    import logging

                    logging.getLogger(__name__).warning(
                        "Check run %s remains queued after publication failure",
                        run.execution_id,
                    )
            return JSONResponse(
                RunRead.model_validate(run).model_dump(mode="json"), status_code=202
            )
        result = await run_integration_check(session, integration, settings=settings)
        return CheckRead.model_validate(result)
    except (RunBusy, RunExhausted):
        raise HTTPException(409, "A check is already running; wait for it to finish")


@router.get("/runs/{execution_id}")
def run_state(execution_id: str, request: Request, session=Depends(get_db)):
    run = session.get(CheckRun, execution_id)
    if not run:
        raise HTTPException(404, "Run not found")
    service_for_request(session, run.integration_id, request)
    result = RunRead.model_validate(run).model_dump()
    check = session.scalar(
        select(HealthCheck).where(HealthCheck.execution_id == execution_id)
    )
    result["check"] = CheckRead.model_validate(check).model_dump() if check else None
    return result


@router.get("/integrations/{integration_id}/checks", response_model=list[CheckRead])
def check_history(
    integration_id: int,
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    session=Depends(get_db),
):
    service_for_request(session, integration_id, request)
    return list(
        session.scalars(
            select(HealthCheck)
            .where(HealthCheck.integration_id == integration_id)
            .order_by(HealthCheck.checked_at.desc(), HealthCheck.id.desc())
            .limit(limit)
        )
    )


@router.get("/incidents", response_model=list[IncidentRead])
def incidents(
    request: Request,
    status: str | None = None,
    integration_id: int | None = None,
    session=Depends(get_db),
):
    ids = scope_query(request).with_only_columns(Integration.id)
    statement = (
        select(Incident)
        .where(Incident.integration_id.in_(ids))
        .order_by(Incident.started_at.desc(), Incident.id.desc())
    )
    if status:
        if status.upper() not in ("OPEN", "RESOLVED"):
            raise HTTPException(422, "Status must be OPEN or RESOLVED")
        statement = statement.where(Incident.status == status.upper())
    if integration_id:
        service_for_request(session, integration_id, request)
        statement = statement.where(Incident.integration_id == integration_id)
    return list(session.scalars(statement.limit(200)))


@router.get("/status")
def statuses(request: Request, session=Depends(get_db)):
    settings = request.app.state.settings
    services = list(
        session.scalars(
            scope_query(request)
            .where(Integration.active.is_(True))
            .order_by(Integration.name)
        )
    )
    latest = latest_checks(session, [item.id for item in services])
    return [service_status(item, latest.get(item.id), settings) for item in services]


@router.get("/overview", response_model=Overview)
def overview(request: Request, session=Depends(get_db)):
    services = list(
        session.scalars(scope_query(request).where(Integration.active.is_(True)))
    )
    ids = [item.id for item in services]
    latest = latest_checks(session, ids)
    states = [
        service_status(item, latest.get(item.id), request.app.state.settings)["status"]
        for item in services
    ]
    window = utcnow() - timedelta(hours=24)
    predicate = (HealthCheck.integration_id.in_(ids), HealthCheck.checked_at >= window)
    total, available, average = session.execute(
        select(
            func.count(HealthCheck.id),
            func.sum(
                case((HealthCheck.outcome.in_(["HEALTHY", "DEGRADED"]), 1), else_=0)
            ),
            func.avg(HealthCheck.latency_ms),
        ).where(*predicate)
    ).one()
    count = (
        session.scalar(
            select(func.count(HealthCheck.id)).where(
                *predicate, HealthCheck.latency_ms.is_not(None)
            )
        )
        or 0
    )
    p95 = (
        session.scalar(
            select(HealthCheck.latency_ms)
            .where(*predicate, HealthCheck.latency_ms.is_not(None))
            .order_by(HealthCheck.latency_ms)
            .offset(max(0, math.ceil(count * 0.95) - 1))
            .limit(1)
        )
        if count
        else None
    )
    return Overview(
        total_integrations=len(services),
        healthy=states.count("HEALTHY"),
        degraded=states.count("DEGRADED"),
        down=states.count("FAILED"),
        stale=states.count("STALE"),
        unknown=states.count("UNKNOWN"),
        active_incidents=session.scalar(
            select(func.count())
            .select_from(Incident)
            .where(Incident.integration_id.in_(ids), Incident.status == "OPEN")
        )
        or 0,
        checks_24h=total,
        availability_24h=round((available or 0) / total * 100, 2) if total else None,
        avg_latency_ms_24h=round(average, 2) if average is not None else None,
        p95_latency_ms_24h=round(p95, 2) if p95 is not None else None,
    )


@router.post("/demo", dependencies=[Depends(same_origin)])
def create_demo(request: Request, session=Depends(get_db)):
    if not request.app.state.settings.demo_mode:
        raise HTTPException(404, "Demo is disabled")
    owner = demo_owner(request)
    from app.services.limits import demo_budget

    demo_budget(session, owner)
    return [
        integration_read(item)
        for item in setup_demo(
            session, owner, request.app.state.settings.demo_ttl_hours
        )
    ]


@router.get("/demo")
def demo(request: Request, session=Depends(get_db)):
    owner = demo_owner(request)
    return [
        {"service": state.service, "mode": state.mode}
        for state in session.scalars(select(DemoState).where(DemoState.owner == owner))
    ]


@router.post("/demo/scenario", dependencies=[Depends(same_origin)])
def demo_scenario(payload: DemoScenario, request: Request, session=Depends(get_db)):
    if not request.app.state.settings.demo_mode:
        raise HTTPException(404, "Demo is disabled")
    owner = demo_owner(request)
    from app.services.limits import demo_budget

    demo_budget(session, owner)
    lock_writes(session)
    integration = session.scalar(
        select(Integration)
        .where(Integration.demo_owner == owner, Integration.demo_key == payload.service)
        .with_for_update()
    )
    if integration is None:
        raise HTTPException(409, "Create the example services first")
    pending = session.scalar(
        select(CheckRun.execution_id).where(
            CheckRun.integration_id == integration.id,
            CheckRun.status.in_(["QUEUED", "RUNNING"]),
        )
    )
    if pending:
        session.rollback()
        raise HTTPException(
            409, "Wait for the current check before changing the scenario"
        )
    state = session.get(DemoState, (owner, payload.service))
    if not state:
        raise HTTPException(409, "Create the example services first")
    state.mode = payload.mode
    state.expires_at = utcnow() + timedelta(
        hours=request.app.state.settings.demo_ttl_hours
    )
    session.commit()
    return {"service": payload.service, "mode": payload.mode}


# Legacy operator-only simulator for API compatibility; public demos use isolated DB state.
@router.post("/simulator/state", dependencies=[Depends(require_operator)])
def legacy_simulator(payload: SimulatorState, request: Request):
    request.app.state.simulator_mode = payload.mode
    request.app.state.simulator_delay_seconds = payload.delay_seconds
    return payload.model_dump()


@router.get("/simulator/state", dependencies=[Depends(require_operator)])
def legacy_simulator_state(request: Request):
    return {
        "mode": request.app.state.simulator_mode,
        "delay_seconds": request.app.state.simulator_delay_seconds,
    }
