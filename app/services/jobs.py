"""Database-owned run reservation and expiring claims. Queue messages carry only the stable run ID."""

import uuid
from datetime import timedelta
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from app.core.db import lock_writes
from app.core.models import CheckRun, Heartbeat, Integration, aware, utcnow


class RunBusy(Exception):
    pass


class RunExhausted(Exception):
    pass


def heartbeat(session, name):
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    statement = insert(Heartbeat).values(name=name, updated_at=utcnow())
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["name"], set_={"updated_at": utcnow()}
        )
    )


def reserve_run(session, integration_id, settings, execution_id=None, scheduled=False):
    lock_writes(session)
    integration = session.scalar(
        select(Integration).where(Integration.id == integration_id).with_for_update()
    )
    if not integration or not integration.active:
        session.rollback()
        return None, False
    if execution_id:
        run = session.get(CheckRun, execution_id)
        if run:
            if run.integration_id != integration_id:
                session.rollback()
                raise ValueError("Run ID belongs to another service")
            session.commit()
            return run, True
    pending = session.scalar(
        select(CheckRun).where(
            CheckRun.integration_id == integration_id,
            CheckRun.status.in_(["QUEUED", "RUNNING"]),
        )
    )
    now = utcnow()
    if pending:
        expired = pending.lease_until is None or aware(pending.lease_until) <= now
        if (
            not scheduled
            and execution_id
            and pending.execution_id != execution_id
            and not expired
        ):
            session.rollback()
            raise RunBusy("A check is already in progress")
        if expired and pending.attempts >= settings.max_run_attempts:
            pending.status = "FAILED"
            pending.error_code = "ATTEMPTS_EXHAUSTED"
            pending.finished_at = now
            session.commit()
            return None, False
        session.commit()
        return pending, expired
    if (
        scheduled
        and integration.last_checked_at
        and (now - aware(integration.last_checked_at)).total_seconds()
        < integration.check_interval_seconds
    ):
        session.rollback()
        return None, False
    run = CheckRun(
        execution_id=execution_id or str(uuid.uuid4()),
        integration_id=integration_id,
        status="QUEUED",
        scheduled_at=now,
        lease_until=now + timedelta(seconds=settings.lease_seconds),
    )
    session.add(run)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if scheduled:
            return None, False
        raise RunBusy("A check is already in progress")
    return run, True


def claim_run(session, execution_id, settings):
    now = utcnow()
    token = str(uuid.uuid4())
    session.rollback()
    changed = session.execute(
        update(CheckRun)
        .execution_options(synchronize_session=False)
        .where(
            CheckRun.execution_id == execution_id,
            CheckRun.attempts < settings.max_run_attempts,
            or_(
                CheckRun.status == "QUEUED",
                (CheckRun.status == "RUNNING") & (CheckRun.lease_until <= now),
            ),
        )
        .values(
            status="RUNNING",
            lease_token=token,
            lease_until=now + timedelta(seconds=settings.lease_seconds),
            started_at=now,
            attempts=CheckRun.attempts + 1,
        )
    )
    session.commit()
    if changed.rowcount != 1:
        session.expire_all()
        run = session.get(CheckRun, execution_id)
        if not run or run.status in ("FAILED", "CANCELLED"):
            raise RunExhausted("Run cannot be executed")
        raise RunBusy("Run already completed or claimed")
    return token


def release_for_retry(session, execution_id, token):
    session.rollback()
    session.execute(
        update(CheckRun)
        .where(CheckRun.execution_id == execution_id, CheckRun.lease_token == token)
        .values(
            status="QUEUED",
            lease_token=None,
            lease_until=utcnow(),
            error_code="MONITOR_ERROR",
        )
    )
    session.commit()
