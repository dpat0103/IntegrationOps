from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import func, select
from app.core.models import DemoState, RateLimitBucket, utcnow


def demo_budget(session, owner, limit=60):
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    now = utcnow()
    key = f"{owner}:{int(now.timestamp()) // 60}"
    insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    statement = insert(RateLimitBucket).values(
        key=key, count=1, expires_at=now + timedelta(minutes=2)
    )
    result = session.execute(
        statement.on_conflict_do_update(
            index_elements=["key"],
            set_={"count": RateLimitBucket.count + 1},
            where=RateLimitBucket.count < limit,
        ).returning(RateLimitBucket.count)
    ).scalar()
    session.commit()
    if result is None:
        raise HTTPException(
            429,
            "Demo action limit reached. Please wait a minute.",
            headers={"Retry-After": "60"},
        )
    if not session.scalar(
        select(DemoState.owner).where(DemoState.owner == owner).limit(1)
    ):
        sessions = (
            session.scalar(select(func.count(func.distinct(DemoState.owner)))) or 0
        )
        if sessions >= 1000:
            raise HTTPException(429, "The demo is busy. Please try again later.")
