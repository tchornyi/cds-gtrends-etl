"""Database connection helpers."""

from __future__ import annotations

from typing import Any

import psycopg

from google_trends_etl.config import Settings, load_settings


def connect(settings: Settings | None = None) -> psycopg.Connection[Any]:
    settings = settings or load_settings()
    if settings.database_url:
        return psycopg.connect(settings.database_url)
    return psycopg.connect(**settings.pg_params)
