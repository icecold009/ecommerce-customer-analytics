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

-- Machine-testable data-quality summary. Existing result sets above remain unchanged.
SELECT check_name, violation_count
FROM (
    SELECT 'orders_missing_customer' AS check_name, COUNT(*) AS violation_count
    FROM orders AS o
    LEFT JOIN customers AS c ON c.customer_id = o.customer_id
    WHERE c.customer_id IS NULL

    UNION ALL
    SELECT 'order_items_missing_order', COUNT(*)
    FROM order_items AS oi
    LEFT JOIN orders AS o ON o.order_id = oi.order_id
    WHERE o.order_id IS NULL

    UNION ALL
    SELECT 'order_items_missing_product', COUNT(*)
    FROM order_items AS oi
    LEFT JOIN products AS p ON p.product_id = oi.product_id
    WHERE p.product_id IS NULL

    UNION ALL
    SELECT 'payments_missing_order', COUNT(*)
    FROM order_payments AS op
    LEFT JOIN orders AS o ON o.order_id = op.order_id
    WHERE o.order_id IS NULL

    UNION ALL
    SELECT 'reviews_missing_order', COUNT(*)
    FROM order_reviews AS r
    LEFT JOIN orders AS o ON o.order_id = r.order_id
    WHERE o.order_id IS NULL

    UNION ALL
    SELECT 'order_items_invalid_price', COUNT(*)
    FROM order_items
    WHERE price IS NULL OR price < 0

    UNION ALL
    SELECT 'order_items_invalid_freight', COUNT(*)
    FROM order_items
    WHERE freight_value IS NULL OR freight_value < 0

    UNION ALL
    SELECT 'payments_invalid_value', COUNT(*)
    FROM order_payments
    WHERE payment_value IS NULL OR payment_value < 0

    UNION ALL
    SELECT 'delivered_before_purchase', COUNT(*)
    FROM orders
    WHERE order_delivered_customer_date IS NOT NULL
      AND order_purchase_timestamp IS NOT NULL
      AND datetime(order_delivered_customer_date) < datetime(order_purchase_timestamp)

    UNION ALL
    SELECT 'estimated_before_purchase', COUNT(*)
    FROM orders
    WHERE order_estimated_delivery_date IS NOT NULL
      AND order_purchase_timestamp IS NOT NULL
      AND datetime(order_estimated_delivery_date) < datetime(order_purchase_timestamp)

    UNION ALL
    SELECT 'delivered_orders_without_payment', COUNT(*)
    FROM cleaned_orders AS co
    LEFT JOIN order_payment_totals AS pt ON pt.order_id = co.order_id
    WHERE pt.order_id IS NULL

    UNION ALL
    SELECT 'delivered_orders_without_items', COUNT(*)
    FROM cleaned_orders AS co
    LEFT JOIN (SELECT DISTINCT order_id FROM order_items) AS oi ON oi.order_id = co.order_id
    WHERE oi.order_id IS NULL

    UNION ALL
    SELECT 'products_without_category_translation', COUNT(*)
    FROM products AS p
    LEFT JOIN category_translation AS t
        ON t.product_category_name = p.product_category_name
    WHERE p.product_category_name IS NOT NULL
      AND t.product_category_name IS NULL
)
ORDER BY check_name;
