"""Extract relative interest-over-time for the configured search terms."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Iterable, Protocol, Sequence

from google_trends_etl.config import GoogleTrendsSettings
from google_trends_etl.trendspy_support import (
    RetryOptions,
    build_trends_client,
    call_with_rate_limit_retries,
)

TIMEFRAME = "now 7-d"
# Google Trends compares at most 5 keywords per request; one slot is reserved
# for the calibration reference term that rides along in every batch.
MAX_TERMS_PER_BATCH = 4


class InterestOverTimeClient(Protocol):
    def interest_over_time(self, keywords: Sequence[str], *, timeframe: str) -> Any:
        ...


@dataclass(frozen=True)
class InterestBatch:
    terms: tuple[str, ...]
    reference_term: str
    # pandas DataFrame: one 0-100 interest column per requested keyword.
    frame: Any


def extract_interest(
    terms: Iterable[str],
    reference_term: str,
    *,
    timeframe: str = TIMEFRAME,
    client: InterestOverTimeClient | None = None,
    trends_settings: GoogleTrendsSettings | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[InterestBatch]:
    retry_options = RetryOptions.from_settings(trends_settings)
    trends_client = client or build_trends_client(trends_settings)
    unique_terms = list(dict.fromkeys(terms))

    batches: list[InterestBatch] = []
    for start in range(0, len(unique_terms), MAX_TERMS_PER_BATCH):
        chunk = unique_terms[start : start + MAX_TERMS_PER_BATCH]
        keywords = list(dict.fromkeys([*chunk, reference_term]))
        frame = call_with_rate_limit_retries(
            f"interest_over_time({', '.join(keywords)})",
            lambda keywords=keywords: trends_client.interest_over_time(
                keywords,
                timeframe=timeframe,
            ),
            retry_options=retry_options,
            sleep=sleep,
        )
        batches.append(
            InterestBatch(terms=tuple(chunk), reference_term=reference_term, frame=frame)
        )
    return batches
