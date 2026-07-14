"""OpenTelemetry metrics for ETL runs."""

from __future__ import annotations

import logging
import os

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

from google_trends_etl import __version__

LOGGER = logging.getLogger(__name__)

METER_NAME = "google_trends_etl"
ROWS_AFFECTED_METRIC = "google_trends_etl.rows_affected"


def configure_telemetry() -> None:
    """Install the SDK-backed OTLP meter provider used by CDS.

    CDS injects OTEL_EXPORTER_OTLP_METRICS_* and OTEL_RESOURCE_ATTRIBUTES for
    deployed runs. The exporter reads those variables itself; do not construct a
    Resource here, because that would risk dropping the CDS run correlation.
    """
    if not os.environ.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"):
        LOGGER.debug("OTLP metrics endpoint is not set; using default meter provider.")
        return

    try:
        exporter = OTLPMetricExporter()
        reader = PeriodicExportingMetricReader(exporter)
        provider = MeterProvider(metric_readers=[reader])
        metrics.set_meter_provider(provider)
    except Exception:  # pragma: no cover - deployment/environment failures are external.
        LOGGER.exception("Failed to configure OpenTelemetry metrics exporter.")


configure_telemetry()

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
