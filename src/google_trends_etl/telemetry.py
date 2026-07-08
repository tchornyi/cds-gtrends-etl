"""OpenTelemetry metrics for ETL runs."""

from __future__ import annotations

import logging

from opentelemetry import metrics

from google_trends_etl import __version__

LOGGER = logging.getLogger(__name__)

METER_NAME = "google_trends_etl"
ROWS_AFFECTED_METRIC = "google_trends_etl.rows_affected"

_METER = metrics.get_meter(METER_NAME, __version__)
_ROWS_AFFECTED = _METER.create_histogram(
    ROWS_AFFECTED_METRIC,
    unit="{row}",
    description="Rows inserted or upserted by one completed ETL run.",
)


def record_rows_affected(
    rows: int,
    *,
    pipeline: str,
    table: str,
    operation: str,
) -> None:
    _ROWS_AFFECTED.record(
        rows,
        {
            "pipeline": pipeline,
            "table": table,
            "operation": operation,
        },
    )
    _flush_metrics()


def _flush_metrics() -> None:
    provider = metrics.get_meter_provider()
    force_flush = getattr(provider, "force_flush", None)
    if not callable(force_flush):
        return
    try:
        force_flush(timeout_millis=5_000)
    except Exception:  # pragma: no cover - exporter/provider failures are external.
        LOGGER.exception("Failed to flush OpenTelemetry metrics.")