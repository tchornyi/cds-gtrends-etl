from datetime import datetime
import unittest

import pandas as pd

from google_trends_etl.extract_country_search_volumes import (
    CountryExtract,
    CountryInterest,
    InterestBatch as CountryInterestBatch,
)
from google_trends_etl.extract_search_volumes import InterestBatch
from google_trends_etl.transform_country_search_volumes import transform_country_volumes
from google_trends_etl.transform_search_volumes import transform_search_volumes


class SearchVolumeTransformTests(unittest.TestCase):
    def test_search_volumes_scale_against_reference_term(self):
        frame = pd.DataFrame({"alpha": [50, 100], "google": [100, 100]})

        records = transform_search_volumes(
            [InterestBatch(("alpha",), "google", frame)],
            reference_volume=1_000,
            snapshot_at=datetime(2026, 7, 7, 12, 0, 0),
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].term, "alpha")
        self.assertEqual(records[0].search_volume, 750)
        self.assertIsNotNone(records[0].snapshot_at.tzinfo)

    def test_country_volumes_can_distribute_with_equal_country_weights(self):
        trend_frame = pd.DataFrame({"alpha": [50, 100], "google": [100, 100]})
        country_frame = pd.DataFrame(
            {
                "geoName": ["United States", "Canada"],
                "geoCode": ["US", "CA"],
                "alpha": [75, 25],
            }
        )
        extracted = CountryExtract(
            interest_batches=(
                CountryInterestBatch(("alpha",), "google", trend_frame),
            ),
            country_interest=(CountryInterest("alpha", country_frame),),
        )

        records = transform_country_volumes(
            extracted,
            reference_volume=1_000,
            snapshot_at=datetime(2026, 7, 7, 12, 0, 0),
            country_weights={"US": 1, "CA": 1},
        )

        self.assertEqual(
            {(record.country_code, record.search_volume) for record in records},
            {("US", 562), ("CA", 188)},
        )
        self.assertEqual(sum(record.search_volume for record in records), 750)
        self.assertTrue(
            all(record.volume_date.isoformat() == "2026-07-07" for record in records)
        )

    def test_country_volumes_weight_relative_interest_by_country_size(self):
        trend_frame = pd.DataFrame({"alpha": [100], "google": [100]})
        country_frame = pd.DataFrame(
            {
                "geoName": ["Vanuatu", "United States"],
                "geoCode": ["VU", "US"],
                "alpha": [100, 10],
            }
        )
        extracted = CountryExtract(
            interest_batches=(
                CountryInterestBatch(("alpha",), "google", trend_frame),
            ),
            country_interest=(CountryInterest("alpha", country_frame),),
        )

        records = transform_country_volumes(
            extracted,
            reference_volume=1_000,
            snapshot_at=datetime(2026, 7, 7, 12, 0, 0),
            country_weights={"VU": 320_000, "US": 340_000_000},
        )
        by_code = {record.country_code: record for record in records}

        self.assertEqual(by_code["VU"].search_volume, 9)
        self.assertEqual(by_code["US"].search_volume, 991)
        self.assertEqual(by_code["VU"].country_weight, 320_000)
        self.assertLess(by_code["VU"].search_volume, by_code["US"].search_volume)


if __name__ == "__main__":
    unittest.main()