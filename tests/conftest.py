from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def sample_data_dir(tmp_path: Path) -> Path:
    """Create a small but relationally complete Olist-style dataset."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    tables = {
        "olist_customers_dataset.csv": pd.DataFrame(
            [
                ["c1", "u1", 1000, "Sao Paulo", "SP"],
                ["c2", "u1", 1001, "Campinas", "SP"],
                ["c3", "u2", 2000, "Rio", "RJ"],
            ],
            columns=["customer_id", "customer_unique_id", "customer_zip_code_prefix", "customer_city", "customer_state"],
        ),
        "olist_orders_dataset.csv": pd.DataFrame(
            [
                ["o1", "c1", "delivered", "2021-01-01 10:00:00", "2021-01-01 10:05:00", "2021-01-05 10:00:00", "2021-01-10 10:00:00"],
                ["o2", "c2", "delivered", "2021-02-01 10:00:00", "2021-02-01 10:05:00", "2021-02-09 10:00:00", "2021-02-08 10:00:00"],
                ["o3", "c3", "delivered", "2021-01-15 10:00:00", "2021-01-15 10:05:00", "2021-01-20 10:00:00", "2021-01-25 10:00:00"],
                ["o4", "c3", "canceled", "2021-03-01 10:00:00", "", "", ""],
            ],
            columns=["order_id", "customer_id", "order_status", "order_purchase_timestamp", "order_approved_at", "order_delivered_customer_date", "order_estimated_delivery_date"],
        ),
        "olist_order_items_dataset.csv": pd.DataFrame(
            [["o1", 1, "p1", "seller1", "2021-01-01 10:00:00", 10.0, 2.0], ["o2", 1, "p2", "seller1", "2021-02-01 10:00:00", 20.0, 3.0], ["o3", 1, "p3", "seller2", "2021-01-15 10:00:00", 15.0, 1.0]],
            columns=["order_id", "order_item_id", "product_id", "seller_id", "shipping_limit_date", "price", "freight_value"],
        ),
        "olist_order_payments_dataset.csv": pd.DataFrame(
            [["o1", 1, "credit_card", 1, 10.0], ["o1", 2, "voucher", 1, 2.0], ["o2", 1, "boleto", 1, 23.0], ["o3", 1, "credit_card", 1, 16.0]],
            columns=["order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value"],
        ),
        "olist_order_reviews_dataset.csv": pd.DataFrame(
            [["r1", "o1", 5, "great", "", "2021-01-06", "2021-01-07"], ["r2", "o2", 3, "ok", "", "2021-02-10", "2021-02-11"]],
            columns=["review_id", "order_id", "review_score", "review_comment_title", "review_comment_message", "review_creation_date", "review_answer_timestamp"],
        ),
        "olist_products_dataset.csv": pd.DataFrame(
            [["p1", "perfumaria", 10, 10, 10, 10, 10, 10, 10], ["p2", "beleza_saude", 10, 10, 10, 10, 10, 10, 10], ["p3", "esporte_lazer", 10, 10, 10, 10, 10, 10, 10]],
            columns=["product_id", "product_category_name", "product_name_lenght", "product_description_lenght", "product_photos_qty", "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm"],
        ),
        "product_category_name_translation.csv": pd.DataFrame(
            [["perfumaria", "perfume"], ["beleza_saude", "health_beauty"], ["esporte_lazer", "sports_leisure"]],
            columns=["product_category_name", "product_category_name_english"],
        ),
    }
    for filename, frame in tables.items():
        frame.to_csv(data_dir / filename, index=False)
    return data_dir


@pytest.fixture
def sample_db(sample_data_dir: Path, tmp_path: Path) -> Path:
    from load_database import load_database

    db_path = tmp_path / "olist.db"
    load_database(sample_data_dir, db_path)
    return db_path
