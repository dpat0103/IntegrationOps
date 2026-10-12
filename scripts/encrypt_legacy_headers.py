"""Convert legacy plaintext headers in an owned database. Dry-run by default."""

import argparse
from sqlalchemy import select
from app.core.config import get_settings
from app.core.db import build_engine_and_session, init_db
from app.core.models import Integration
from app.core.security import encrypted_headers
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    engine, factory = build_engine_and_session(settings.database_url)
    init_db(engine)
    with factory() as session:
        rows = list(
            session.scalars(
                select(Integration).where(Integration.headers_json.is_not(None))
            )
        )
        legacy = [row for row in rows if not row.headers_json.startswith("enc:")]
        if args.apply:
            if not settings.integration_secret_key:
                raise ValueError(
                    "Set INTEGRATION_SECRET_KEY before applying credential migration"
                )
            for row in legacy:
                row.headers_json = encrypted_headers(
                    json.loads(row.headers_json), settings
                )
            session.commit()
        print(json.dumps({"legacy_records": len(legacy), "applied": args.apply}))
    engine.dispose()


if __name__ == "__main__":
    main()
