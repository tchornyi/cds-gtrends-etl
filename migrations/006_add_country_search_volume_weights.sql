ALTER TABLE country_search_volumes
    ADD COLUMN country_weight BIGINT NOT NULL DEFAULT 0 CHECK (country_weight >= 0);

COMMENT ON COLUMN country_search_volumes.country_weight IS
    'Country-size proxy used to convert relative Google Trends country interest into approximate absolute volume.';