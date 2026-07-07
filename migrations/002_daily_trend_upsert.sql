-- Switch from append-only snapshots to one row per (term, UTC day):
-- reruns within the same day update the existing row, the first appearance
-- on a new day inserts a fresh one.
ALTER TABLE current_trends
    ADD COLUMN trend_date DATE;

UPDATE current_trends
    SET trend_date = (snapshot_at AT TIME ZONE 'UTC')::date;

ALTER TABLE current_trends
    ALTER COLUMN trend_date SET NOT NULL;

-- Collapse duplicates left over from the append-only era: keep the most
-- recent row per (term, trend_date).
DELETE FROM current_trends stale
USING current_trends newer
WHERE stale.term = newer.term
  AND stale.trend_date = newer.trend_date
  AND (newer.snapshot_at, newer.ctid) > (stale.snapshot_at, stale.ctid);

ALTER TABLE current_trends
    DROP CONSTRAINT current_trends_pkey;

ALTER TABLE current_trends
    ADD PRIMARY KEY (term, trend_date);

-- Redundant now: the new primary key already leads with term.
DROP INDEX current_trends_term_idx;
