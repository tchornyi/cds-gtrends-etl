"""Extract per-country relative interest for the configured search terms."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Iterable, Protocol, Sequence

from trendspy import Trends

LOGGER = logging.getLogger(__name__)

TIMEFRAME = "now 1-d"
# Google Trends compares at most 5 keywords per request; one slot is reserved
# for the calibration reference term that rides along in every batch.
MAX_TERMS_PER_BATCH = 4
DEFAULT_TRENDS_REQUEST_DELAY_SECONDS = 2.0
DEFAULT_RATE_LIMIT_ATTEMPTS = 4
DEFAULT_RATE_LIMIT_INITIAL_DELAY_SECONDS = 15.0
DEFAULT_RATE_LIMIT_BACKOFF = 2.0


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
class RetryOptions:
    max_attempts: int = DEFAULT_RATE_LIMIT_ATTEMPTS
    initial_delay_seconds: float = DEFAULT_RATE_LIMIT_INITIAL_DELAY_SECONDS
    backoff: float = DEFAULT_RATE_LIMIT_BACKOFF

    @classmethod
    def from_env(cls) -> "RetryOptions":
        return cls(
            max_attempts=_parse_positive_int_env(
                "TRENDS_429_RETRY_ATTEMPTS",
                DEFAULT_RATE_LIMIT_ATTEMPTS,
            ),
            initial_delay_seconds=_parse_non_negative_float_env(
                "TRENDS_429_RETRY_INITIAL_DELAY_SECONDS",
                DEFAULT_RATE_LIMIT_INITIAL_DELAY_SECONDS,
            ),
            backoff=_parse_positive_float_env(
                "TRENDS_429_RETRY_BACKOFF",
                DEFAULT_RATE_LIMIT_BACKOFF,
            ),
        )

    def delay_for_attempt(self, attempt_number: int) -> float:
        return self.initial_delay_seconds * (self.backoff ** (attempt_number - 1))


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
    retry_options: RetryOptions | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> CountryExtract:
    retry_options = retry_options or RetryOptions.from_env()
    trends_client = client or _build_trends_client()
    unique_terms = list(dict.fromkeys(terms))

    batches: list[InterestBatch] = []
    for start in range(0, len(unique_terms), MAX_TERMS_PER_BATCH):
        chunk = unique_terms[start : start + MAX_TERMS_PER_BATCH]
        keywords = list(dict.fromkeys([*chunk, reference_term]))
        frame = _call_with_rate_limit_retries(
            f"interest_over_time({', '.join(keywords)})",
            lambda: trends_client.interest_over_time(keywords, timeframe=timeframe),
            retry_options=retry_options,
            sleep=sleep,
        )
        batches.append(
            InterestBatch(terms=tuple(chunk), reference_term=reference_term, frame=frame)
        )

    country_interest = tuple(
        CountryInterest(
            term=term,
            frame=_call_with_rate_limit_retries(
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


def _build_trends_client() -> Trends:
    request_delay = _parse_non_negative_float_env(
        "TRENDS_REQUEST_DELAY_SECONDS",
        DEFAULT_TRENDS_REQUEST_DELAY_SECONDS,
    )
    try:
        return Trends(request_delay=request_delay)
    except TypeError:
        LOGGER.warning(
            "Installed trendspy does not support request_delay; using default client."
        )
        return Trends()


def _call_with_rate_limit_retries(
    operation: str,
    func: Callable[[], Any],
    *,
    retry_options: RetryOptions,
    sleep: Callable[[float], None],
) -> Any:
    for attempt in range(1, retry_options.max_attempts + 1):
        try:
            return func()
        except Exception as exc:
            if not _is_rate_limit_error(exc) or attempt == retry_options.max_attempts:
                raise

            delay = retry_options.delay_for_attempt(attempt)
            LOGGER.warning(
                "Google Trends rate limited %s on attempt %s/%s; retrying in %.1fs.",
                operation,
                attempt,
                retry_options.max_attempts,
                delay,
            )
            sleep(delay)

    raise RuntimeError(f"Retry loop exhausted unexpectedly for {operation}.")


def _is_rate_limit_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        response = getattr(current, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code == 429:
            return True
        if "429" in str(current):
            return True
        current = current.__cause__ or current.__context__
    return False


def _parse_positive_int_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError:
        LOGGER.warning("%s must be an integer; using default %s.", name, default)
        return default
    if value <= 0:
        LOGGER.warning("%s must be greater than zero; using default %s.", name, default)
        return default
    return value


def _parse_positive_float_env(name: str, default: float) -> float:
    value = _parse_float_env(name, default)
    if value <= 0:
        LOGGER.warning("%s must be greater than zero; using default %s.", name, default)
        return default
    return value


def _parse_non_negative_float_env(name: str, default: float) -> float:
    value = _parse_float_env(name, default)
    if value < 0:
        LOGGER.warning("%s must be zero or greater; using default %s.", name, default)
        return default
    return value


def _parse_float_env(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return float(raw_value)
    except ValueError:
        LOGGER.warning("%s must be a number; using default %s.", name, default)
        return default
