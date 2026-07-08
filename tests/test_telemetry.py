import unittest

from google_trends_etl.telemetry import ROWS_AFFECTED_METRIC, record_rows_affected


class TelemetryTests(unittest.TestCase):
    def test_record_rows_affected_smoke(self):
        record_rows_affected(
            3,
            pipeline="test_pipeline",
            table="test_table",
            operation="insert",
        )

        self.assertEqual(ROWS_AFFECTED_METRIC, "google_trends_etl.rows_affected")


if __name__ == "__main__":
    unittest.main()