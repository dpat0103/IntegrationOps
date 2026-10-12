from app.core.config import get_settings
from app.core.db import build_engine_and_session, init_db

if __name__ == "__main__":
    engine, _ = build_engine_and_session(get_settings().database_url)
    init_db(engine)
    engine.dispose()
