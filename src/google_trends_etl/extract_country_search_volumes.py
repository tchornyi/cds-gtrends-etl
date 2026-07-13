"""Extract per-country relative interest for the configured search terms."""

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

TIMEFRAME = "now 1-d"
# Google Trends compares at most 5 keywords per request; one slot is reserved
# for the calibration reference term that rides along in every batch.
MAX_TERMS_PER_BATCH = 4


class CountryTrendsClient(Protocol):
    def interest_over_time(self, keywords: Sequence[str], *, timeframe: str) -> Any:
        ...

    def interest_by_region(
        self,
        keyword: str,
        *,
        timeframe: str,
        inc_low_vol: bool = False,
    ) -> Any:
        ...


@dataclass(frozen=True)
class InterestBatch:
    terms: tuple[str, ...]
    reference_term: str
    # pandas DataFrame: one 0-100 interest column per requested keyword.
    frame: Any


@dataclass(frozen=True)
class CountryInterest:
    term: str
    # pandas DataFrame: 0-100 relative interest per country.
    frame: Any


@dataclass(frozen=True)
class CountryExtract:
    interest_batches: tuple[InterestBatch, ...]
    country_interest: tuple[CountryInterest, ...]


def extract_country_interest(
    terms: Iterable[str],
    reference_term: str,
    *,
    timeframe: str = TIMEFRAME,
    include_low_volume_geos: bool = True,
    client: CountryTrendsClient | None = None,
    trends_settings: GoogleTrendsSettings | None = None,
    retry_options: RetryOptions | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> CountryExtract:
    retry_options = retry_options or RetryOptions.from_settings(trends_settings)
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

    country_interest = tuple(
        CountryInterest(
            term=term,
            frame=call_with_rate_limit_retries(
                f"interest_by_region({term})",
                lambda term=term: trends_client.interest_by_region(
                    term,
                    timeframe=timeframe,
                    inc_low_vol=include_low_volume_geos,
                ),
                retry_options=retry_options,
                sleep=sleep,
            ),
        )
        for term in unique_terms
    )

    return CountryExtract(
        interest_batches=tuple(batches),
        country_interest=country_interest,
    )
