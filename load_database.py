"""Load the Olist CSV extracts into SQLite and create analytical views."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Mapping

import pandas as pd


REQUIRED_FILES: Mapping[str, str] = {
    "customers": "olist_customers_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

REQUIRED_COLUMNS: Mapping[str, set[str]] = {
    "customers": {"customer_id", "customer_unique_id"},
    "orders": {"order_id", "customer_id", "order_status", "order_purchase_timestamp"},
    "order_items": {"order_id", "product_id", "price", "freight_value"},
    "order_payments": {"order_id", "payment_type", "payment_value"},
    "order_reviews": {"review_id", "order_id", "review_score"},
    "products": {"product_id", "product_category_name"},
    "category_translation": {"product_category_name", "product_category_name_english"},
}

PRIMARY_KEYS: Mapping[str, tuple[str, ...]] = {
    "customers": ("customer_id",),
    "orders": ("order_id",),
    "order_items": ("order_id", "order_item_id"),
    "order_payments": ("order_id", "payment_sequential"),
    # The public Olist extract repeats review_id values, but review_id + order_id
    # remains unique and preserves every source row.
    "order_reviews": ("review_id", "order_id"),
    "products": ("product_id",),
    "category_translation": ("product_category_name",),
}

REQUIRED_TIMESTAMP_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "orders": ("order_purchase_timestamp",),
}

VALIDATION_SUMMARY_MARKER = "-- Machine-testable data-quality summary. Existing result sets above remain unchanged."


def _validate_required_values(table_name: str, frame: pd.DataFrame) -> None:
    """Reject missing identifiers and invalid timestamps before any DB writes."""
    missing_identifiers = [
        column for column in PRIMARY_KEYS[table_name] if frame[column].isna().any()
    ]
    if missing_identifiers:
        columns = ", ".join(missing_identifiers)
        raise ValueError(
            f"Found null value(s) in required identifier column(s) for {table_name}: {columns}"
        )

    for column in REQUIRED_TIMESTAMP_COLUMNS.get(table_name, ()):
        values = frame[column]
        parsed = pd.to_datetime(values, errors="coerce", format="mixed")
        invalid = values.isna() | parsed.isna()
        if invalid.any():
            raise ValueError(
                f"Found null or invalid timestamp value(s) in {table_name}.{column}"
            )


def _read_required_tables(data_dir: Path) -> dict[str, pd.DataFrame]:
    missing = [filename for filename in REQUIRED_FILES.values() if not (data_dir / filename).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Missing required CSV file(s) in {data_dir}: {', '.join(sorted(missing))}"
        )

    tables: dict[str, pd.DataFrame] = {}
    for table_name, filename in REQUIRED_FILES.items():
        frame = pd.read_csv(data_dir / filename)
        missing_columns = REQUIRED_COLUMNS[table_name] - set(frame.columns)
        if missing_columns:
            raise ValueError(
                f"{filename} is missing required column(s): {', '.join(sorted(missing_columns))}"
            )
        _validate_required_values(table_name, frame)
        key_columns = PRIMARY_KEYS[table_name]
        duplicate_count = int(frame.duplicated(list(key_columns)).sum())
        if duplicate_count:
            raise ValueError(
                f"Found {duplicate_count} duplicate key values in {table_name} for {', '.join(key_columns)}"
            )
        tables[table_name] = frame
    return tables


def _create_views(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DROP VIEW IF EXISTS cleaned_order_items;
        DROP VIEW IF EXISTS order_payment_totals;
        DROP VIEW IF EXISTS cleaned_orders;

        CREATE VIEW cleaned_orders AS
        SELECT
            order_id,
            customer_id,
            order_status,
            order_purchase_timestamp,
            order_delivered_customer_date,
            order_estimated_delivery_date,
            CAST(
                julianday(order_delivered_customer_date)
                - julianday(order_purchase_timestamp)
                AS REAL
            ) AS delivery_days,
            CASE
                WHEN date(order_delivered_customer_date) <= date(order_estimated_delivery_date)
                    THEN 'On time'
                ELSE 'Late'
            END AS delivery_status
        FROM orders
        WHERE order_status = 'delivered'
          AND order_purchase_timestamp IS NOT NULL
          AND order_delivered_customer_date IS NOT NULL
          AND order_estimated_delivery_date IS NOT NULL;

        CREATE VIEW order_payment_totals AS
        SELECT
            op.order_id,
            ROUND(SUM(op.payment_value), 2) AS payment_value,
            (
                SELECT GROUP_CONCAT(payment_type)
                FROM (
                    SELECT DISTINCT payment_type
                    FROM order_payments AS op2
                    WHERE op2.order_id = op.order_id
                    ORDER BY payment_type
                )
            ) AS payment_method
        FROM order_payments AS op
        GROUP BY op.order_id;

        CREATE VIEW cleaned_order_items AS
        SELECT
            co.order_id,
            co.customer_id,
            co.order_purchase_timestamp,
            co.delivery_days,
            co.delivery_status,
            oi.order_item_id,
            oi.product_id,
            oi.price,
            oi.freight_value,
            p.product_category_name,
            COALESCE(t.product_category_name_english, p.product_category_name, 'Unknown') AS category_name,
            ROUND(oi.price + oi.freight_value, 2) AS item_revenue
        FROM cleaned_orders AS co
        INNER JOIN order_items AS oi ON oi.order_id = co.order_id
        LEFT JOIN products AS p ON p.product_id = oi.product_id
        LEFT JOIN category_translation AS t
            ON t.product_category_name = p.product_category_name;
        """
    )


def _create_indexes(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_orders_order_id ON orders(order_id);
        CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);
        CREATE INDEX IF NOT EXISTS idx_orders_purchase_timestamp ON orders(order_purchase_timestamp);
        CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
        CREATE INDEX IF NOT EXISTS idx_order_items_product_id ON order_items(product_id);
        CREATE INDEX IF NOT EXISTS idx_order_payments_order_id ON order_payments(order_id);
        CREATE INDEX IF NOT EXISTS idx_customers_unique_id ON customers(customer_unique_id);
        """
    )


def load_database(data_dir: str | Path, db_path: str | Path) -> dict[str, int]:
    """Load all required CSVs and return loaded row counts.

    Raw tables are replaced on each run so the pipeline is deterministic. The
    analytical views centralize delivered-order and payment aggregation rules.
    """
    data_dir = Path(data_dir)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tables = _read_required_tables(data_dir)

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for table_name, frame in tables.items():
            frame.to_sql(table_name, connection, if_exists="replace", index=False)
        _create_indexes(connection)
        _create_views(connection)
        connection.commit()

    return {table_name: len(frame) for table_name, frame in tables.items()}


def get_validation_summary(db_path: str | Path) -> list[tuple[str, int]]:
    """Return the existing SQL data-quality summary in its deterministic order."""
    validation_sql_path = Path(__file__).resolve().parent / "sql" / "validation.sql"
    validation_sql = validation_sql_path.read_text(encoding="utf-8")
    _, marker, summary_sql = validation_sql.partition(VALIDATION_SUMMARY_MARKER)
    if not marker:
        raise ValueError(f"Validation summary marker not found in {validation_sql_path}")

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(summary_sql).fetchall()
    return [(str(check_name), int(violation_count)) for check_name, violation_count in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--db-path", type=Path, default=Path("olist.db"))
    args = parser.parse_args()
    counts = load_database(args.data_dir, args.db_path)
    print(f"Loaded {len(counts)} tables into {args.db_path}")
    for table_name, row_count in counts.items():
        print(f"  {table_name}: {row_count:,} rows")


if __name__ == "__main__":
    main()
