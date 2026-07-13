import unittest

from google_trends_etl.config import GoogleTrendsSettings
from google_trends_etl.extract import extract_trends
from google_trends_etl.extract_search_volumes import extract_interest


class _Response:
    status_code = 429


class _RateLimitError(Exception):
    response = _Response()


class _RateLimitedSearchClient:
    def __init__(self):
        self.calls = 0

    def interest_over_time(self, keywords, *, timeframe):
        self.calls += 1
        if self.calls == 1:
            raise _RateLimitError("429 Client Error")
        return {"keywords": tuple(keywords), "timeframe": timeframe}


class _RateLimitedTrendingClient:
    def __init__(self):
        self.calls = 0

    def trending_now(self, *, geo):
        self.calls += 1
        if self.calls == 1:
            raise _RateLimitError("429 Client Error")
        return ({"geo": geo},)


class GoogleTrendsExtractTests(unittest.TestCase):
    def test_search_volume_extract_retries_rate_limit(self):
        client = _RateLimitedSearchClient()
        sleeps: list[float] = []

        batches = extract_interest(
            ["rain"],
            "google",
            client=client,
            trends_settings=_retry_settings(),
            sleep=sleeps.append,
        )

        self.assertEqual(client.calls, 2)
        self.assertEqual(sleeps, [0.5])
        self.assertEqual(batches[0].terms, ("rain",))
        self.assertEqual(batches[0].frame["keywords"], ("rain", "google"))

    def test_current_trends_extract_retries_rate_limit(self):
        client = _RateLimitedTrendingClient()
        sleeps: list[float] = []

        entries = extract_trends(
            "US",
            client=client,
            trends_settings=_retry_settings(),
            sleep=sleeps.append,
        )

        self.assertEqual(client.calls, 2)
        self.assertEqual(sleeps, [0.5])
        self.assertEqual(entries, [{"geo": "US"}])


def _retry_settings() -> GoogleTrendsSettings:
    return GoogleTrendsSettings(
        request_delay_seconds=0,
        max_retries=3,
        retry_backoff_seconds=0.5,
        retry_backoff_multiplier=2,
    )


if __name__ == "__main__":
    unittest.main()
