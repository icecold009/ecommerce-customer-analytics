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

-- Review quality is aggregated per order before joining to customer state.
WITH order_review_scores AS (
    SELECT
        order_id,
        AVG(review_score) AS average_review_score,
        MAX(CASE WHEN review_score IN (1, 2) THEN 1.0 ELSE 0.0 END) AS low_score_order
    FROM order_reviews
    GROUP BY order_id
)
SELECT
    c.customer_state,
    COUNT(*) AS reviewed_orders,
    ROUND(AVG(ors.average_review_score), 2) AS average_review_score,
    ROUND(AVG(ors.low_score_order), 4) AS low_score_rate
FROM order_review_scores AS ors
JOIN cleaned_orders AS co ON co.order_id = ors.order_id
JOIN customers AS c ON c.customer_id = co.customer_id
GROUP BY c.customer_state
ORDER BY low_score_rate DESC, reviewed_orders DESC, c.customer_state;
