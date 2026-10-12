from alembic import context
from sqlalchemy import create_engine
from app.core.db import Base
from app.core import models  # noqa: F401 — register metadata for migration inspection

config = context.config
connection = config.attributes.get("connection")
if connection is None:
    from app.core.config import get_settings

    engine = create_engine(get_settings().database_url)
    with engine.begin() as connection:
        context.configure(
            connection=connection, target_metadata=Base.metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
else:
    context.configure(
        connection=connection, target_metadata=Base.metadata, render_as_batch=True
    )
    with context.begin_transaction():
        context.run_migrations()
