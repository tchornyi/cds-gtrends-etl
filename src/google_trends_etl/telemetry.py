"""OpenTelemetry metrics for ETL runs."""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote
from urllib.request import Request, urlopen

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics._internal.instrument import Histogram as HistogramInstrument
from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    Gauge,
    Histogram,
    MetricExportResult,
    MetricExporter,
    MetricsData,
    PeriodicExportingMetricReader,
    Sum,
)

from google_trends_etl import __version__

LOGGER = logging.getLogger(__name__)

METER_NAME = "google_trends_etl"
ROWS_AFFECTED_METRIC = "google_trends_etl.rows_affected"


class CDSJsonMetricExporter(MetricExporter):
    """OTLP/HTTP JSON metric exporter for the CDS portal ingest endpoint."""

    def __init__(self) -> None:
        super().__init__(
            preferred_temporality={HistogramInstrument: AggregationTemporality.DELTA}
        )
        self._endpoint = os.environ["OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"]
        self._headers = _otel_headers()
        self._timeout = float(
            os.environ.get(
                "OTEL_EXPORTER_OTLP_METRICS_TIMEOUT",
                os.environ.get("OTEL_EXPORTER_OTLP_TIMEOUT", "10"),
            )
        )
        self._last_successful_payload: bytes | None = None

    def export(
        self,
        metrics_data: MetricsData,
        timeout_millis: float = 10_000,
        **kwargs: Any,
    ) -> MetricExportResult:
        body = json.dumps(
            _metrics_data_to_otlp_json(metrics_data),
            separators=(",", ":"),
        ).encode("utf-8")
        if body == self._last_successful_payload:
            return MetricExportResult.SUCCESS

        headers = {
            **self._headers,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        request = Request(self._endpoint, data=body, headers=headers, method="POST")
        timeout = min(self._timeout, timeout_millis / 1000)

        try:
            with urlopen(request, timeout=timeout) as response:
                if 200 <= response.status < 300:
                    self._last_successful_payload = body
                    return MetricExportResult.SUCCESS
                LOGGER.error("Failed to export metrics batch code: %s", response.status)
        except HTTPError as exc:
            reason = exc.read().decode("utf-8", errors="replace")
            LOGGER.error(
                "Failed to export metrics batch code: %s, reason: %s",
                exc.code,
                reason,
            )
        except URLError:
            LOGGER.exception("Failed to export metrics batch.")

        return MetricExportResult.FAILURE

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        return True

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
        return None


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
        exporter = CDSJsonMetricExporter()
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


def _otel_headers() -> dict[str, str]:
    raw_headers = os.environ.get(
        "OTEL_EXPORTER_OTLP_METRICS_HEADERS",
        os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", ""),
    )
    headers: dict[str, str] = {}
    for item in raw_headers.split(","):
        key, separator, value = item.partition("=")
        if separator and key.strip():
            headers[unquote(key.strip())] = unquote(value.strip())
    return headers


def _metrics_data_to_otlp_json(metrics_data: MetricsData) -> dict[str, Any]:
    return {
        "resourceMetrics": [
            {
                "resource": {"attributes": _attributes(resource_metrics.resource.attributes)},
                "scopeMetrics": [
                    {
                        "scope": {
                            "name": scope_metrics.scope.name,
                            "version": scope_metrics.scope.version or "",
                        },
                        "metrics": [
                            _metric_to_otlp_json(metric)
                            for metric in scope_metrics.metrics
                        ],
                    }
                    for scope_metrics in resource_metrics.scope_metrics
                ],
            }
            for resource_metrics in metrics_data.resource_metrics
        ]
    }


def _metric_to_otlp_json(metric: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": metric.name,
        "description": metric.description or "",
        "unit": metric.unit or "",
    }
    data = metric.data
    if isinstance(data, Gauge):
        item["gauge"] = {
            "dataPoints": [_number_data_point(point) for point in data.data_points]
        }
    elif isinstance(data, Sum):
        item["sum"] = {
            "aggregationTemporality": _temporality(data.aggregation_temporality),
            "isMonotonic": data.is_monotonic,
            "dataPoints": [_number_data_point(point) for point in data.data_points],
        }
    elif isinstance(data, Histogram):
        item["histogram"] = {
            "aggregationTemporality": _temporality(data.aggregation_temporality),
            "dataPoints": [_histogram_data_point(point) for point in data.data_points],
        }
    return item


def _number_data_point(point: Any) -> dict[str, Any]:
    item = _base_data_point(point)
    if isinstance(point.value, int):
        item["asInt"] = str(point.value)
    else:
        item["asDouble"] = float(point.value)
    return item


def _histogram_data_point(point: Any) -> dict[str, Any]:
    item = _base_data_point(point)
    item.update(
        {
            "count": str(point.count),
            "sum": point.sum,
            "bucketCounts": [str(count) for count in point.bucket_counts],
            "explicitBounds": list(point.explicit_bounds),
            "min": point.min,
            "max": point.max,
        }
    )
    return item


def _base_data_point(point: Any) -> dict[str, Any]:
    return {
        "attributes": _attributes(point.attributes or {}),
        "startTimeUnixNano": str(point.start_time_unix_nano),
        "timeUnixNano": str(point.time_unix_nano),
    }


def _attributes(values: Any) -> list[dict[str, Any]]:
    return [{"key": key, "value": _any_value(value)} for key, value in values.items()]


def _any_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [_any_value(item) for item in value]}}
    return {"stringValue": str(value)}


def _temporality(value: AggregationTemporality) -> str:
    if value == AggregationTemporality.DELTA:
        return "AGGREGATION_TEMPORALITY_DELTA"
    return "AGGREGATION_TEMPORALITY_CUMULATIVE"
