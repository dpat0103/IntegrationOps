from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def build_engine_and_session(database_url: str):
    # Render and several managed Postgres providers expose a generic
    # postgresql:// URL. This project ships psycopg v3, so normalize the URL
    # explicitly instead of relying on SQLAlchemy's psycopg2 default.
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    elif database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql://")

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine, session_factory


def init_db(engine) -> None:
    from app.core import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
