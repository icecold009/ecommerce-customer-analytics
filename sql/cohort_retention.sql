-- The Python implementation calculates the same logic with pandas so it can
-- produce a typed Period cohort index and a heatmap without dialect-specific SQL.
SELECT c.customer_unique_id,
       substr(co.order_purchase_timestamp, 1, 7) AS purchase_month
FROM cleaned_orders AS co
JOIN customers AS c ON c.customer_id = co.customer_id;
