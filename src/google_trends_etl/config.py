"""Configuration loading for the Google Trends ETL."""

from __future__ import annotations

import os
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    pg_params: Mapping[str, str]
    trends_geo: str
    trends_top_n: int


def load_settings(*, geo_override: str | None = None) -> Settings:
    load_dotenv(override=False)

    database_url = _non_empty("DATABASE_URL")
    pg_params = MappingProxyType({} if database_url else _load_pg_params())

    trends_geo = (geo_override or _non_empty("TRENDS_GEO") or "US").strip().upper()
    if not trends_geo:
        raise ConfigError("TRENDS_GEO must not be empty.")

    trends_top_n = _parse_top_n()

    return Settings(
        database_url=database_url,
        pg_params=pg_params,
        trends_geo=trends_geo,
        trends_top_n=trends_top_n,
    )


def _non_empty(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _load_pg_params() -> dict[str, str]:
    env_to_param = {
        "PGHOST": "host",
        "PGPORT": "port",
        "PGDATABASE": "dbname",
        "PGUSER": "user",
        "PGPASSWORD": "password",
        "PGSSLMODE": "sslmode",
    }
    missing = [name for name in env_to_param if not _non_empty(name)]
    if missing:
        names = ", ".join(missing)
        raise ConfigError(
            "Set DATABASE_URL or provide all PostgreSQL variables: "
            f"PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD, PGSSLMODE. Missing: {names}."
        )
    return {param: _non_empty(env) or "" for env, param in env_to_param.items()}


def _parse_positive_int(name: str, *, default: str) -> int:
    raw_value = os.environ.get(name, default).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw_value!r}.") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero, got {value}.")
    return value


def _parse_top_n() -> int:
    value = _parse_positive_int("TRENDS_TOP_N", default="25")
    if value > 25:
        raise ConfigError("TRENDS_TOP_N must be between 1 and 25.")
    return value
