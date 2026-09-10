-- Run after load_database.py. These checks intentionally inspect the raw and cleaned layers separately.
SELECT 'customers' AS table_name, COUNT(*) AS row_count FROM customers
UNION ALL SELECT 'orders', COUNT(*) FROM orders
UNION ALL SELECT 'order_items', COUNT(*) FROM order_items
UNION ALL SELECT 'order_payments', COUNT(*) FROM order_payments
UNION ALL SELECT 'order_reviews', COUNT(*) FROM order_reviews
UNION ALL SELECT 'products', COUNT(*) FROM products
UNION ALL SELECT 'category_translation', COUNT(*) FROM category_translation;

SELECT order_id, COUNT(*) AS duplicate_rows
FROM orders
GROUP BY order_id
HAVING COUNT(*) > 1;

SELECT COUNT(*) AS delivered_orders_without_payment
FROM cleaned_orders AS co
LEFT JOIN order_payment_totals AS pt ON pt.order_id = co.order_id
WHERE pt.order_id IS NULL;
