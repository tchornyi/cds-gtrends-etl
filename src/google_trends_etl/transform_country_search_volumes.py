"""Transform per-country interest into approximate daily search volumes."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, tzinfo
from typing import Any
from uuid import UUID, uuid4

from google_trends_etl.country_weights import DEFAULT_COUNTRY_WEIGHTS
from google_trends_etl.extract_country_search_volumes import CountryExtract, InterestBatch

LOGGER = logging.getLogger(__name__)

COUNTRY_CODE_FIELDS = ("geoCode", "geo_code", "country_code", "code", "iso_code", "id")
COUNTRY_NAME_FIELDS = ("geoName", "geo_name", "country_name", "country", "name", "region", "location")
VALUE_FIELDS = ("value", "interest", "extracted_value")


class TransformError(ValueError):
    """Raised when country interest data cannot be transformed."""


@dataclass(frozen=True)
class CountryVolumeRecord:
    snapshot_id: UUID
    snapshot_at: datetime
    volume_date: date
    term: str
    country_code: str
    country_name: str | None
    interest: int
    country_weight: int
    search_volume: int


def transform_country_volumes(
    extracted: CountryExtract,
    *,
    reference_volume: int,
    snapshot_id: UUID | None = None,
    snapshot_at: datetime | None = None,
    local_tz: tzinfo | None = None,
    country_weights: Mapping[str, int] | None = None,
    unknown_country_weight: int = 0,
) -> list[CountryVolumeRecord]:
    snapshot_id = snapshot_id or uuid4()
    snapshot_at = _make_aware(snapshot_at or datetime.now(UTC))
    volume_date = _local_date(snapshot_at, local_tz)
    if country_weights is None:
        country_weights = DEFAULT_COUNTRY_WEIGHTS

    global_volumes = _global_volumes(extracted.interest_batches, reference_volume)

    records: list[CountryVolumeRecord] = []
    seen: set[tuple[str, str]] = set()
    for country_interest in extracted.country_interest:
        term = country_interest.term
        global_volume = global_volumes.get(term)
        if global_volume is None:
            LOGGER.warning("Skipping term %r: no calibrated global volume.", term)
            continue

        try:
            rows = _country_rows(country_interest.frame, term)
        except TransformError:
            LOGGER.exception("Skipping term %r: unusable country interest data.", term)
            continue

        weighted_rows = _weighted_country_rows(
            rows,
            country_weights=country_weights,
            unknown_country_weight=unknown_country_weight,
        )
        total_weighted_interest = sum(row[4] for row in weighted_rows)
        if total_weighted_interest <= 0:
            LOGGER.warning(
                "Skipping term %r: no positive weighted country interest.",
                term,
            )
            continue

        for (
            country_code,
            country_name,
            interest,
            country_weight,
            weighted_interest,
        ) in weighted_rows:
            key = (term, country_code)
            if key in seen:
                continue
            seen.add(key)
            # Distribute the calibrated global volume by interest weighted by a
            # country-size proxy. This keeps high-relative-interest small
            # countries from receiving large absolute-volume estimates.
            search_volume = int(
                round(global_volume * weighted_interest / total_weighted_interest)
            )
            records.append(
                CountryVolumeRecord(
                    snapshot_id=snapshot_id,
                    snapshot_at=snapshot_at,
                    volume_date=volume_date,
                    term=term,
                    country_code=country_code,
                    country_name=country_name,
                    interest=interest,
                    country_weight=country_weight,
                    search_volume=search_volume,
                )
            )

    return records


def _weighted_country_rows(
    rows: Sequence[tuple[str, str | None, int]],
    *,
    country_weights: Mapping[str, int],
    unknown_country_weight: int,
) -> list[tuple[str, str | None, int, int, int]]:
    weighted_rows: list[tuple[str, str | None, int, int, int]] = []
    seen_codes: set[str] = set()
    for country_code, country_name, interest in rows:
        normalized_code = country_code.upper()
        if normalized_code in seen_codes:
            continue
        seen_codes.add(normalized_code)

        normalized_interest = min(max(interest, 0), 100)
        country_weight = country_weights.get(normalized_code, unknown_country_weight)
        if country_weight <= 0:
            LOGGER.debug(
                "Skipping country %s: no positive country weight configured.",
                normalized_code,
            )
            continue

        weighted_interest = normalized_interest * country_weight
        if weighted_interest <= 0:
            continue
        weighted_rows.append(
            (
                normalized_code,
                country_name,
                normalized_interest,
                country_weight,
                weighted_interest,
            )
        )
    return weighted_rows


def _global_volumes(
    batches: Sequence[InterestBatch],
    reference_volume: int,
) -> dict[str, int]:
    volumes: dict[str, int] = {}
    for batch in batches:
        try:
            reference_interest = _mean_interest(batch.frame, batch.reference_term)
        except TransformError:
            LOGGER.exception(
                "Skipping batch %s: reference term %r has no usable interest data.",
                batch.terms,
                batch.reference_term,
            )
            continue
        if reference_interest <= 0:
            LOGGER.warning(
                "Skipping batch %s: reference term %r registered zero interest.",
                batch.terms,
                batch.reference_term,
            )
            continue

        for term in batch.terms:
            if term in volumes:
                continue
            try:
                interest = _mean_interest(batch.frame, term)
            except TransformError:
                LOGGER.exception("Skipping term %r in calibration batch.", term)
                continue
            volumes[term] = int(round(interest / reference_interest * reference_volume))
    return volumes


def _mean_interest(frame: Any, keyword: str) -> float:
    column = _column_for(frame, keyword)
    try:
        value = float(frame[column].mean())
    except (TypeError, ValueError) as exc:
        raise TransformError(f"Interest column {column!r} is not numeric.") from exc
    if math.isnan(value):
        raise TransformError(f"Interest column {column!r} contains no data.")
    if value < 0:
        raise TransformError(f"Interest for {keyword!r} must be non-negative, got {value}.")
    return value


def _column_for(frame: Any, keyword: str) -> Any:
    columns = getattr(frame, "columns", None)
    if columns is None:
        raise TransformError(f"Interest data has no columns; got {type(frame).__name__}.")
    for column in columns:
        if str(column).strip().casefold() == keyword.strip().casefold():
            return column
    raise TransformError(f"No interest column for keyword {keyword!r}.")


def _country_rows(frame: Any, term: str) -> list[tuple[str, str | None, int]]:
    rows: list[tuple[str, str | None, int]] = []
    for raw_row in _frame_rows(frame):
        country_code = _first_text(raw_row, COUNTRY_CODE_FIELDS)
        country_name = _first_text(raw_row, COUNTRY_NAME_FIELDS)
        if country_code is None:
            country_code = country_name
        if country_code is None:
            LOGGER.debug("Skipping row without a country identifier: %r", raw_row)
            continue

        interest = _row_interest(raw_row, term)
        if interest is None or interest <= 0:
            continue
        rows.append((country_code, country_name, interest))
    return rows


def _frame_rows(frame: Any) -> list[Mapping[str, Any]]:
    # trendspy returns a pandas DataFrame (country as index); tolerate plain
    # sequences of mappings so tests don't need pandas fixtures.
    if hasattr(frame, "reset_index"):
        frame = frame.reset_index()
    if hasattr(frame, "to_dict"):
        return list(frame.to_dict(orient="records"))
    if isinstance(frame, Sequence) and not isinstance(frame, (str, bytes)):
        result: list[Mapping[str, Any]] = []
        for row in frame:
            if isinstance(row, Mapping):
                result.append(row)
            else:
                raise TransformError(f"Unsupported country row type {type(row).__name__}.")
        return result
    raise TransformError(f"Unsupported country interest data type {type(frame).__name__}.")


def _first_text(row: Mapping[str, Any], names: Sequence[str]) -> str | None:
    lowered = {str(key).strip().casefold(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.casefold())
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _row_interest(row: Mapping[str, Any], term: str) -> int | None:
    lowered = {str(key).strip().casefold(): value for key, value in row.items()}
    for name in (term.strip().casefold(), *(field.casefold() for field in VALUE_FIELDS)):
        value = lowered.get(name)
        if value is None:
            continue
        try:
            interest = int(float(value))
        except (TypeError, ValueError):
            continue
        return interest
    return None


def _local_date(snapshot_at: datetime, local_tz: tzinfo | None) -> date:
    snapshot_at = _make_aware(snapshot_at)
    if local_tz is None:
        return snapshot_at.astimezone().date()
    return snapshot_at.astimezone(local_tz).date()


def _make_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
