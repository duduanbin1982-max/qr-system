SELECT id, production_month, version, status, row_version,
       supersedes_batch_id, superseded_by_batch_id,
       prepared_by, approved_by
FROM performance_batches
WHERE production_month BETWEEN '2026-06' AND '2026-07'
ORDER BY production_month, version, id;

SELECT COUNT(*) AS reviews
FROM performance_reviews_v2;
