"""Extract current Google Trending Now entries."""

from __future__ import annotations

from typing import Any, Iterable, Protocol

from trendspy import Trends


class TrendingNowClient(Protocol):
    def trending_now(self, *, geo: str) -> Iterable[Any]:
        ...


def extract_trends(geo: str, *, client: TrendingNowClient | None = None) -> list[Any]:
    trends_client = client or Trends()
    return list(trends_client.trending_now(geo=geo))
