import unittest

from google_trends_etl.extract_country_search_volumes import (
    RetryOptions,
    extract_country_interest,
)


class _Response:
    status_code = 429


class _RateLimitError(Exception):
    response = _Response()


class _RateLimitedOnceClient:
    def __init__(self):
        self.interest_over_time_calls = 0
        self.interest_by_region_calls = 0

    def interest_over_time(self, keywords, *, timeframe):
        self.interest_over_time_calls += 1
        if self.interest_over_time_calls == 1:
            raise _RateLimitError("429 Client Error")
        return {"keywords": tuple(keywords), "timeframe": timeframe}

    def interest_by_region(self, keyword, *, timeframe, inc_low_vol=False):
        self.interest_by_region_calls += 1
        return {
            "keyword": keyword,
            "timeframe": timeframe,
            "inc_low_vol": inc_low_vol,
        }


class _AlwaysRateLimitedClient:
    def interest_over_time(self, keywords, *, timeframe):
        raise _RateLimitError("429 Client Error")

    def interest_by_region(self, keyword, *, timeframe, inc_low_vol=False):
        raise AssertionError("interest_by_region should not be called")


class CountrySearchVolumeExtractTests(unittest.TestCase):
    def test_retries_rate_limited_interest_over_time_call(self):
        client = _RateLimitedOnceClient()
        sleeps: list[float] = []

        extracted = extract_country_interest(
            ["rain"],
            "google",
            client=client,
            retry_options=RetryOptions(
                max_attempts=3,
                initial_delay_seconds=0.5,
                backoff=2.0,
            ),
            sleep=sleeps.append,
        )

        self.assertEqual(client.interest_over_time_calls, 2)
        self.assertEqual(client.interest_by_region_calls, 1)
        self.assertEqual(sleeps, [0.5])
        self.assertEqual(extracted.interest_batches[0].terms, ("rain",))
        self.assertEqual(extracted.country_interest[0].term, "rain")

    def test_raises_after_retry_attempts_are_exhausted(self):
        sleeps: list[float] = []

        with self.assertRaises(_RateLimitError):
            extract_country_interest(
                ["rain"],
                "google",
                client=_AlwaysRateLimitedClient(),
                retry_options=RetryOptions(
                    max_attempts=2,
                    initial_delay_seconds=1.0,
                    backoff=3.0,
                ),
                sleep=sleeps.append,
            )

        self.assertEqual(sleeps, [1.0])


if __name__ == "__main__":
    unittest.main()
