# cds-proto-etl

A small ETL that snapshots the top Google Trending Now searches into PostgreSQL.
Each successful run stores one immutable snapshot in `current_trends`.

## Setup

```bash
cp .env.example .env
```

Then edit `.env` with either `DATABASE_URL` or all `PG*` settings.

## Run

```bash
uv run google-trends-etl
```

Optional commands:

```bash
uv run google-trends-migrate
uv run google-trends-etl --skip-migrations --log-level DEBUG
uv run google-trends-etl --geo GB
```
