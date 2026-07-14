import unittest
from unittest.mock import patch

from google_trends_etl import telemetry


class TelemetryTests(unittest.TestCase):
    def test_configure_telemetry_installs_sdk_provider_when_endpoint_is_set(self):
        with patch.dict(
            "os.environ",
            {"OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "http://collector/v1/metrics"},
        ), patch.object(telemetry, "OTLPMetricExporter", return_value="exporter") as exporter, patch.object(
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
