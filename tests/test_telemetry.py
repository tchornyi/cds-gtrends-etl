import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    Histogram,
    HistogramDataPoint,
    Metric,
    MetricsData,
    ResourceMetrics,
    ScopeMetrics,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.util.instrumentation import InstrumentationScope

from google_trends_etl import telemetry


class TelemetryTests(unittest.TestCase):
    def test_configure_telemetry_installs_sdk_provider_when_endpoint_is_set(self):
        with patch.dict(
            "os.environ",
            {"OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "http://collector/v1/metrics"},
        ), patch.object(
            telemetry,
            "CDSJsonMetricExporter",
            return_value="exporter",
        ) as exporter, patch.object(
            telemetry,
            "PeriodicExportingMetricReader",
            return_value="reader",
        ) as reader, patch.object(telemetry, "MeterProvider", return_value="provider") as provider, patch.object(
            telemetry.metrics,
            "set_meter_provider",
        ) as set_meter_provider:
            telemetry.configure_telemetry()

        exporter.assert_called_once_with()
        reader.assert_called_once_with("exporter")
        provider.assert_called_once_with(metric_readers=["reader"])
        set_meter_provider.assert_called_once_with("provider")

    def test_configure_telemetry_leaves_provider_alone_without_endpoint(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(
            telemetry.metrics,
            "set_meter_provider",
        ) as set_meter_provider:
            telemetry.configure_telemetry()

        set_meter_provider.assert_not_called()

    def test_otel_headers_parse_metrics_headers(self):
        with patch.dict(
            "os.environ",
            {"OTEL_EXPORTER_OTLP_METRICS_HEADERS": "Authorization=Bearer%20token,X-Test=yes"},
        ):
            self.assertEqual(
                telemetry._otel_headers(),
                {"Authorization": "Bearer token", "X-Test": "yes"},
            )

    def test_metrics_data_converts_to_cds_otlp_json(self):
        metrics_data = MetricsData(
            resource_metrics=[
                ResourceMetrics(
                    resource=Resource.create({"cds.run.id": "run-123"}),
                    scope_metrics=[
                        ScopeMetrics(
                            scope=InstrumentationScope("test-meter", "1.2.3"),
                            metrics=[
                                Metric(
                                    name=telemetry.ROWS_AFFECTED_METRIC,
                                    description="Rows affected.",
                                    unit="{row}",
                                    data=Histogram(
                                        data_points=[
                                            HistogramDataPoint(
                                                attributes={
                                                    "pipeline": "top_search_trends",
                                                    "table": "top_search_trends",
                                                    "operation": "insert",
                                                },
                                                start_time_unix_nano=10,
                                                time_unix_nano=20,
                                                count=1,
                                                sum=25,
                                                bucket_counts=[0, 1],
                                                explicit_bounds=[0.0],
                                                min=25,
                                                max=25,
                                            )
                                        ],
                                        aggregation_temporality=AggregationTemporality.DELTA,
                                    ),
                                )
                            ],
                            schema_url="",
                        )
                    ],
                    schema_url="",
                )
            ]
        )

        payload = telemetry._metrics_data_to_otlp_json(metrics_data)
        resource_attrs = payload["resourceMetrics"][0]["resource"]["attributes"]
        metric = payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]
        point = metric["histogram"]["dataPoints"][0]

        self.assertIn(
            {"key": "cds.run.id", "value": {"stringValue": "run-123"}},
            resource_attrs,
        )
        self.assertEqual(metric["name"], telemetry.ROWS_AFFECTED_METRIC)
        self.assertEqual(metric["histogram"]["aggregationTemporality"], "AGGREGATION_TEMPORALITY_DELTA")
        self.assertEqual(point["count"], "1")
        self.assertEqual(point["sum"], 25)
        self.assertIn(
            {"key": "operation", "value": {"stringValue": "insert"}},
            point["attributes"],
        )

    def test_module_import_with_otel_endpoint_configures_cleanly(self):
        env = os.environ.copy()
        env["OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"] = "http://127.0.0.1:9/v1/metrics"
        env["OTEL_EXPORTER_OTLP_METRICS_HEADERS"] = "Authorization=Bearer%20token"

        result = subprocess.run(
            [sys.executable, "-c", "import google_trends_etl.telemetry; print('ok')"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)
        self.assertNotIn("Failed to configure OpenTelemetry", result.stderr)
    def test_record_rows_affected_smoke(self):
        telemetry.record_rows_affected(
            3,
            pipeline="test_pipeline",
            table="test_table",
            operation="insert",
        )

        self.assertEqual(telemetry.ROWS_AFFECTED_METRIC, "google_trends_etl.rows_affected")


if __name__ == "__main__":
    unittest.main()
