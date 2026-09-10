-- Order-level revenue: payment rows are aggregated once in order_payment_totals.
SELECT substr(co.order_purchase_timestamp, 1, 7) AS month,
       ROUND(SUM(pt.payment_value), 2) AS revenue
FROM cleaned_orders AS co
JOIN order_payment_totals AS pt ON pt.order_id = co.order_id
GROUP BY month
ORDER BY month;

-- Category revenue: category translation is joined through products, not product IDs.
SELECT category_name, ROUND(SUM(item_revenue), 2) AS revenue
FROM cleaned_order_items
GROUP BY category_name
ORDER BY revenue DESC;

-- Delivery status is derived once in cleaned_orders.
SELECT delivery_status, COUNT(*) AS orders
FROM cleaned_orders
GROUP BY delivery_status;
