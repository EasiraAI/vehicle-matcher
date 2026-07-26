-- Search infrastructure for candidate retrieval.
--
-- search_text is a STORED generated column: computed at write time, cannot drift
-- from the source columns, and is directly inspectable when debugging retrieval.
-- GIN over GiST for the trigram indexes: the workload is read-dominated and we
-- never need distance ordering from the index itself.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

ALTER TABLE vehicle ADD COLUMN IF NOT EXISTS search_text TEXT
  GENERATED ALWAYS AS (lower(make || ' ' || model || ' ' || badge)) STORED;

CREATE INDEX IF NOT EXISTS idx_vehicle_search_trgm
  ON vehicle USING GIN (search_text gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_vehicle_model_trgm
  ON vehicle USING GIN (lower(model) gin_trgm_ops);

-- The make arm of retrieval filters on exact lowercased make.
CREATE INDEX IF NOT EXISTS idx_vehicle_make ON vehicle (lower(make));

-- The model arm also has an exact-equality fast path.
CREATE INDEX IF NOT EXISTS idx_vehicle_model ON vehicle (lower(model));

-- Listing counts are a popularity prior and the README-mandated tie-breaker.
-- Staleness is acceptable for a prior, so we buy read speed with a materialized
-- view instead of counting on the request path.
-- Refresh (out of band, never per-request):
--   REFRESH MATERIALIZED VIEW CONCURRENTLY vehicle_listing_stats;
CREATE MATERIALIZED VIEW IF NOT EXISTS vehicle_listing_stats AS
  SELECT v.id AS vehicle_id, count(l.id) AS listing_count
  FROM vehicle v
  LEFT JOIN listing l ON l.vehicle_id = v.id
  GROUP BY v.id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_vls_vehicle
  ON vehicle_listing_stats (vehicle_id);
