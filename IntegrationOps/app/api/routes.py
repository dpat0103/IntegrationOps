from __future__ import annotations
import json, math
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.core.models import HealthCheck, Incident, Integration
from app.core.schemas import CheckRead, IncidentRead, IntegrationCreate, IntegrationRead, IntegrationUpdate, Overview, SimulatorState, SLORead
from app.core.security import UnsafeEndpointError, encode_headers, validate_endpoint_url
from app.services.orchestrator import DEMO_INTEGRATION_NAME, run_integration_check

router = APIRouter(prefix="/api")

def _require_general_write(request: Request) -> None:
    if not request.app.state.settings.public_write_enabled:
        raise HTTPException(status_code=403, detail='General writes are disabled on this public demo')

def _pct(values, percentile):
    if not values: return None
    values=sorted(values); idx=max(0,min(len(values)-1, math.ceil(percentile*len(values))-1)); return round(values[idx],2)

def _validate_endpoint(request: Request, endpoint: str):
    try: validate_endpoint_url(endpoint, allow_private=request.app.state.settings.private_endpoints_allowed)
    except UnsafeEndpointError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.get('/health')
def api_health(): return {'status':'ok','service':'IntegrationOps'}

@router.get('/runtime')
def runtime_info(request: Request):
    s = request.app.state.settings
    return {'environment': s.environment, 'task_mode': s.task_mode, 'demo_mode': s.demo_mode, 'public_write_enabled': s.public_write_enabled}

@router.post('/demo/integration', response_model=IntegrationRead)
def create_or_refresh_demo_integration(request: Request, session: Session=Depends(get_db)):
    s = request.app.state.settings
    if not s.demo_mode:
        raise HTTPException(status_code=404, detail='Demo mode is disabled')

    endpoint = s.resolved_demo_integration_url
    # This URL is server-controlled configuration, not user input. Validate the
    # scheme/hostname shape but intentionally allow private addressing so the
    # Docker worker can reach the API by its Compose service name.
    try:
        validate_endpoint_url(endpoint, allow_private=True)
    except UnsafeEndpointError as exc:
        raise HTTPException(status_code=500, detail=f'Invalid demo endpoint configuration: {exc}') from exc

    integration = session.scalar(select(Integration).where(Integration.name == DEMO_INTEGRATION_NAME))
    if integration is None:
        integration = Integration(name=DEMO_INTEGRATION_NAME)
        session.add(integration)

    # Refresh the endpoint as well as the demo contract so upgrades from older
    # versions do not leave a stale localhost URL in PostgreSQL.
    integration.endpoint = endpoint
    integration.method = 'GET'
    integration.expected_status = 200
    integration.timeout_ms = 1500
    integration.latency_threshold_ms = 700
    integration.availability_target_pct = 99.0
    integration.p95_latency_target_ms = 1000
    integration.check_interval_seconds = 60
    integration.expected_json_key = 'status'
    integration.expected_json_value = 'healthy'
    integration.active = True
    session.commit()
    session.refresh(integration)
    return integration

@router.post('/integrations', response_model=IntegrationRead, status_code=201)
def create_integration(payload: IntegrationCreate, request: Request, session: Session=Depends(get_db)):
    _require_general_write(request)
    if session.scalar(select(Integration).where(Integration.name==payload.name)): raise HTTPException(409,'Integration name already exists')
    _validate_endpoint(request, str(payload.endpoint))
    integration=Integration(name=payload.name, endpoint=str(payload.endpoint), method=payload.method, expected_status=payload.expected_status,
      timeout_ms=payload.timeout_ms, latency_threshold_ms=payload.latency_threshold_ms, availability_target_pct=payload.availability_target_pct,
      p95_latency_target_ms=payload.p95_latency_target_ms, check_interval_seconds=payload.check_interval_seconds,
      expected_json_key=payload.expected_json_key, expected_json_value=payload.expected_json_value,
      headers_json=encode_headers(payload.headers, request.app.state.settings.integration_secret_key), active=payload.active)
    session.add(integration); session.commit(); session.refresh(integration); return integration

@router.get('/integrations', response_model=list[IntegrationRead])
def list_integrations(session: Session=Depends(get_db)): return list(session.scalars(select(Integration).order_by(Integration.id)))

@router.get('/integrations/{integration_id}', response_model=IntegrationRead)
def get_integration(integration_id:int, session:Session=Depends(get_db)):
    obj=session.get(Integration,integration_id)
    if not obj: raise HTTPException(404,'Integration not found')
    return obj

@router.patch('/integrations/{integration_id}', response_model=IntegrationRead)
def update_integration(integration_id:int,payload:IntegrationUpdate,request:Request,session:Session=Depends(get_db)):
    _require_general_write(request)
    obj=session.get(Integration,integration_id)
    if not obj: raise HTTPException(404,'Integration not found')
    data=payload.model_dump(exclude_unset=True)
    if data.get('endpoint') is not None: data['endpoint']=str(data['endpoint']); _validate_endpoint(request,data['endpoint'])
    if 'headers' in data: obj.headers_json=encode_headers(data.pop('headers'),request.app.state.settings.integration_secret_key)
    for k,v in data.items(): setattr(obj,k,v)
    session.commit(); session.refresh(obj); return obj

@router.delete('/integrations/{integration_id}',status_code=204)
def delete_integration(integration_id:int,request:Request,session:Session=Depends(get_db)):
    _require_general_write(request)
    obj=session.get(Integration,integration_id)
    if not obj: raise HTTPException(404,'Integration not found')
    session.delete(obj); session.commit()

@router.post('/integrations/{integration_id}/check',response_model=CheckRead)
async def manual_check(integration_id:int,request:Request,session:Session=Depends(get_db)):
    obj=session.get(Integration,integration_id)
    if not obj: raise HTTPException(404,'Integration not found')
    s=request.app.state.settings
    if not s.public_write_enabled and not (s.demo_mode and obj.name == DEMO_INTEGRATION_NAME):
        raise HTTPException(403,'Manual checks are limited to the built-in integration on this public demo')
    return await run_integration_check(session,obj,failure_threshold=s.failure_threshold,recovery_threshold=s.recovery_threshold,
      slack_webhook_url=s.slack_webhook_url,allow_private_endpoints=s.private_endpoints_allowed,integration_secret_key=s.integration_secret_key,
      demo_mode=s.demo_mode,demo_integration_url=s.resolved_demo_integration_url)

@router.get('/integrations/{integration_id}/checks',response_model=list[CheckRead])
def integration_checks(integration_id:int,limit:int=100,session:Session=Depends(get_db)):
    if not session.get(Integration,integration_id): raise HTTPException(404,'Integration not found')
    return list(session.scalars(select(HealthCheck).where(HealthCheck.integration_id==integration_id).order_by(HealthCheck.checked_at.desc(),HealthCheck.id.desc()).limit(min(max(limit,1),500))))

@router.get('/integrations/{integration_id}/slo',response_model=SLORead)
def integration_slo(integration_id:int,hours:int=24,session:Session=Depends(get_db)):
    obj=session.get(Integration,integration_id)
    if not obj: raise HTTPException(404,'Integration not found')
    hours=min(max(hours,1),720); since=datetime.now(timezone.utc)-timedelta(hours=hours)
    checks=list(session.scalars(select(HealthCheck).where(HealthCheck.integration_id==integration_id,HealthCheck.checked_at>=since)))
    avail=(round(sum(c.outcome in ('HEALTHY','DEGRADED') for c in checks)/len(checks)*100,2) if checks else None)
    lats=[c.latency_ms for c in checks if c.latency_ms is not None]; p95=_pct(lats,.95)
    budget=None
    if avail is not None and obj.availability_target_pct is not None and obj.availability_target_pct<100:
        allowed=100-obj.availability_target_pct; consumed=max(0,100-avail); budget=round(max(0,100-(consumed/allowed*100)),2)
    return SLORead(integration_id=obj.id,window_hours=hours,availability_pct=avail,availability_target_pct=obj.availability_target_pct,
      availability_met=None if avail is None or obj.availability_target_pct is None else avail>=obj.availability_target_pct,
      p95_latency_ms=p95,p95_latency_target_ms=obj.p95_latency_target_ms,
      latency_met=None if p95 is None or obj.p95_latency_target_ms is None else p95<=obj.p95_latency_target_ms,
      checks=len(checks),error_budget_remaining_pct=budget)

@router.get('/incidents',response_model=list[IncidentRead])
def list_incidents(status:str|None=None,session:Session=Depends(get_db)):
    stmt=select(Incident).order_by(Incident.started_at.desc())
    if status: stmt=stmt.where(Incident.status==status.upper())
    return list(session.scalars(stmt.limit(200)))

@router.get('/overview',response_model=Overview)
def overview(session:Session=Depends(get_db)):
    ints=list(session.scalars(select(Integration).where(Integration.active.is_(True)))); statuses={'HEALTHY':0,'DEGRADED':0,'FAILED':0}
    for i in ints:
        latest=session.scalar(select(HealthCheck).where(HealthCheck.integration_id==i.id).order_by(HealthCheck.checked_at.desc(),HealthCheck.id.desc()).limit(1))
        if latest: statuses[latest.outcome]=statuses.get(latest.outcome,0)+1
    since=datetime.now(timezone.utc)-timedelta(hours=24); recent=list(session.scalars(select(HealthCheck).where(HealthCheck.checked_at>=since)))
    available=[c for c in recent if c.outcome in ('HEALTHY','DEGRADED')]; lats=[c.latency_ms for c in recent if c.latency_ms is not None]
    return Overview(total_integrations=len(ints),healthy=statuses['HEALTHY'],degraded=statuses['DEGRADED'],down=statuses['FAILED'],
      active_incidents=session.scalar(select(func.count()).select_from(Incident).where(Incident.status=='OPEN')) or 0,checks_24h=len(recent),
      availability_24h=round(len(available)/len(recent)*100,2) if recent else None,avg_latency_ms_24h=round(sum(lats)/len(lats),2) if lats else None,p95_latency_ms_24h=_pct(lats,.95))

@router.get('/status')
def current_status(session:Session=Depends(get_db)):
    rows=[]
    for i in session.scalars(select(Integration).where(Integration.active.is_(True)).order_by(Integration.name)):
        latest=session.scalar(select(HealthCheck).where(HealthCheck.integration_id==i.id).order_by(HealthCheck.checked_at.desc(),HealthCheck.id.desc()).limit(1))
        rows.append({'id':i.id,'name':i.name,'endpoint':i.endpoint,'status':latest.outcome if latest else 'UNKNOWN','latency_ms':round(latest.latency_ms,2) if latest and latest.latency_ms is not None else None,'failure_type':latest.failure_type if latest else None,'last_checked_at':latest.checked_at.isoformat() if latest else None,'availability_target_pct':i.availability_target_pct,'p95_latency_target_ms':i.p95_latency_target_ms})
    return rows

@router.post('/simulator/state')
def set_simulator_state(payload:SimulatorState,request:Request):
    if not request.app.state.settings.demo_mode: raise HTTPException(404,'Demo mode is disabled')
    request.app.state.simulator_mode=payload.mode; request.app.state.simulator_delay_seconds=payload.delay_seconds
    return {'mode':payload.mode,'delay_seconds':payload.delay_seconds}

@router.get('/simulator/state')
def get_simulator_state(request:Request):
    if not request.app.state.settings.demo_mode: raise HTTPException(404,'Demo mode is disabled')
    return {'mode':request.app.state.simulator_mode,'delay_seconds':request.app.state.simulator_delay_seconds}
