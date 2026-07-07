-- Rebucket historical trend_date values from UTC days into local calendar
-- days. The migration runner sets the session TimeZone (from TRENDS_TIMEZONE,
-- falling back to the host's current UTC offset) before applying this file,
-- so the timestamptz -> date cast below lands on the local day.

-- Dropped first: shifting dates can merge rows from adjacent UTC days into
-- the same local day, which would trip the (term, trend_date) key mid-update.
ALTER TABLE current_trends
    DROP CONSTRAINT current_trends_pkey;

UPDATE current_trends
    SET trend_date = snapshot_at::date;

-- Keep the most recent row per (term, trend_date) among merged duplicates.
DELETE FROM current_trends stale
USING current_trends newer
WHERE stale.term = newer.term
  AND stale.trend_date = newer.trend_date
  AND (newer.snapshot_at, newer.ctid) > (stale.snapshot_at, stale.ctid);

ALTER TABLE current_trends
    ADD PRIMARY KEY (term, trend_date);
