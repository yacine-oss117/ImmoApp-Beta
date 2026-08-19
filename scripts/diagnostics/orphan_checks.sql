-- Orphan detection queries for operational monitoring.
-- Demandes without active clients
SELECT d.id, d.client_id
FROM demandes d
LEFT JOIN clients c ON c.id = d.client_id
WHERE d.deleted_at IS NULL AND (c.id IS NULL OR c.deleted_at IS NOT NULL);

-- Offers without active listings
SELECT o.id, o.listing_id
FROM offers o
LEFT JOIN listings l ON l.id = o.listing_id
WHERE o.deleted_at IS NULL AND (l.id IS NULL OR l.deleted_at IS NOT NULL);

-- Visits with deleted client or listing
SELECT v.id, v.client_id, v.listing_id
FROM visits v
LEFT JOIN clients c ON c.id = v.client_id
LEFT JOIN listings l ON l.id = v.listing_id
WHERE v.deleted_at IS NULL
  AND v.status = 'scheduled'
  AND (c.deleted_at IS NOT NULL OR l.deleted_at IS NOT NULL);
