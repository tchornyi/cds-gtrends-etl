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

The main ETL command applies pending migrations before extracting and loading
data, so Docker entrypoints only need to run `uv run google-trends-etl`.
Set `PRE_LOAD_SLEEP_SECONDS` to control the simulated delay before loading
records into PostgreSQL. The default is `20`.
