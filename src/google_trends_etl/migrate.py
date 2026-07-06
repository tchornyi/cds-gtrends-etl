"""Forward-only SQL migration runner."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, Sequence

import psycopg

from google_trends_etl.config import ConfigError, load_settings
from google_trends_etl.db import connect

LOGGER = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

SCHEMA_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def apply_migrations(
    conn: psycopg.Connection[Any],
    *,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> list[str]:
    migration_files = sorted(migrations_dir.glob("*.sql"))
    applied_now: list[str] = []

    with conn.transaction():
        conn.execute(SCHEMA_MIGRATIONS_SQL)
        applied = {
            row[0]
            for row in conn.execute("SELECT filename FROM schema_migrations")
        }

        for path in migration_files:
            if path.name in applied:
                continue
            LOGGER.info("Applying migration %s.", path.name)
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)",
                (path.name,),
            )
            applied_now.append(path.name)

    if applied_now:
        LOGGER.info("Applied %s migration(s).", len(applied_now))
    else:
        LOGGER.info("No pending migrations.")
    return applied_now


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply pending Google Trends ETL migrations.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    _configure_logging(args.log_level)

    try:
        settings = load_settings()
    except ConfigError as exc:
        parser.error(str(exc))

    with connect(settings) as conn:
        apply_migrations(conn)
    return 0


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


if __name__ == "__main__":
    raise SystemExit(main())
