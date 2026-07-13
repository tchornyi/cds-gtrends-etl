"""Shared trendspy client and retry helpers."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from trendspy import Trends

from google_trends_etl.config import GoogleTrendsSettings

LOGGER = logging.getLogger(__name__)

DEFAULT_GOOGLE_TRENDS_REQUEST_DELAY_SECONDS = 5.0
DEFAULT_GOOGLE_TRENDS_MAX_ATTEMPTS = 5
DEFAULT_GOOGLE_TRENDS_RETRY_BACKOFF_SECONDS = 60.0
DEFAULT_GOOGLE_TRENDS_RETRY_BACKOFF_MULTIPLIER = 2.0


@dataclass(frozen=True)
class RetryOptions:
    max_attempts: int = DEFAULT_GOOGLE_TRENDS_MAX_ATTEMPTS
    initial_delay_seconds: float = DEFAULT_GOOGLE_TRENDS_RETRY_BACKOFF_SECONDS
    backoff: float = DEFAULT_GOOGLE_TRENDS_RETRY_BACKOFF_MULTIPLIER

    @classmethod
    def from_settings(
        cls,
        settings: GoogleTrendsSettings | None,
    ) -> "RetryOptions":
        if settings is None:
            return cls()
        return cls(
            max_attempts=settings.max_retries,
            initial_delay_seconds=settings.retry_backoff_seconds,
            backoff=settings.retry_backoff_multiplier,
        )

    def delay_for_attempt(self, attempt_number: int) -> float:
        return self.initial_delay_seconds * (self.backoff ** (attempt_number - 1))


def build_trends_client(settings: GoogleTrendsSettings | None = None) -> Trends:
    request_delay = DEFAULT_GOOGLE_TRENDS_REQUEST_DELAY_SECONDS
    max_retries = DEFAULT_GOOGLE_TRENDS_MAX_ATTEMPTS
    if settings is not None:
        request_delay = settings.request_delay_seconds
        max_retries = settings.max_retries

    try:
        return Trends(request_delay=request_delay, max_retries=max_retries)
    except TypeError:
        try:
            return Trends(request_delay=request_delay)
        except TypeError:
            LOGGER.warning(
                "Installed trendspy does not support request_delay; using default client."
            )
            return Trends()


def call_with_rate_limit_retries(
    operation: str,
    func: Callable[[], Any],
    *,
    retry_options: RetryOptions,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    for attempt in range(1, retry_options.max_attempts + 1):
        try:
            return func()
        except Exception as exc:
            if not is_rate_limit_error(exc) or attempt == retry_options.max_attempts:
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


def is_rate_limit_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        response = getattr(current, "response", None)
        status_code = getattr(response, "status_code", None)
        current_message = str(current)
        response_message = str(response) if response is not None else ""
        if status_code == 429:
            return True
        if "429" in current_message or "429" in response_message:
            return True
        if "USER_TYPE_EMBED_OVER_QUOTA" in current_message:
            return True
        current = current.__cause__ or current.__context__
    return False
