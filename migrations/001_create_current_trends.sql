CREATE TABLE current_trends (
    snapshot_id UUID NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL,
    rank SMALLINT NOT NULL CHECK (rank BETWEEN 1 AND 25),
    term TEXT NOT NULL,
    search_volume INTEGER NOT NULL CHECK (search_volume >= 0),
    volume_growth_pct INTEGER NULL,
    trend_started_at TIMESTAMPTZ NULL,
    related_queries JSONB NULL,
    PRIMARY KEY (snapshot_id, rank)
);

CREATE INDEX current_trends_snapshot_at_idx
    ON current_trends (snapshot_at DESC);

CREATE INDEX current_trends_term_idx
    ON current_trends (term);
