"""Extract current Google Trending Now entries."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Iterable, Protocol

from google_trends_etl.config import GoogleTrendsSettings
from google_trends_etl.trendspy_support import (
    RetryOptions,
    build_trends_client,
    call_with_rate_limit_retries,
)


class TrendingNowClient(Protocol):
    def trending_now(self, *, geo: str) -> Iterable[Any]:
        ...


def extract_trends(
    geo: str,
    *,
    client: TrendingNowClient | None = None,
    trends_settings: GoogleTrendsSettings | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Any]:
    retry_options = RetryOptions.from_settings(trends_settings)
    trends_client = client or build_trends_client(trends_settings)
    return list(
        call_with_rate_limit_retries(
            f"trending_now({geo})",
            lambda: trends_client.trending_now(geo=geo),
            retry_options=retry_options,
            sleep=sleep,
        )
    )
