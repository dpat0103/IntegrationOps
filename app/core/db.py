from pathlib import Path
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def build_engine_and_session(database_url):
    connect_args = (
        {"check_same_thread": False, "timeout": 30}
        if database_url.startswith("sqlite")
        else {}
    )
    engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def sqlite_settings(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")

    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine):
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(719001)"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def lock_writes(session):
    if session.in_transaction():
        session.rollback()
    if session.bind.dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
