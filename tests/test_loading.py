from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from load_database import REQUIRED_FILES, load_database


def test_missing_required_csv_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="olist_orders_dataset.csv"):
        load_database(tmp_path / "data", tmp_path / "olist.db")


def test_load_creates_tables_indexes_and_clean_views(sample_db: Path) -> None:
    with sqlite3.connect(sample_db) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        views = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'view'")}
        assert set(REQUIRED_FILES) <= tables
        assert {"cleaned_orders", "order_payment_totals", "cleaned_order_items"} <= views
        assert connection.execute("SELECT COUNT(*) FROM cleaned_orders").fetchone()[0] == 3
        assert connection.execute("SELECT payment_value FROM order_payment_totals WHERE order_id = 'o1'").fetchone()[0] == 12
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_%'").fetchone()[0] >= 4


def test_database_load_is_repeatable(sample_data_dir: Path, tmp_path: Path) -> None:
    db_path = tmp_path / "olist.db"
    load_database(sample_data_dir, db_path)
    load_database(sample_data_dir, db_path)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 4


def test_duplicate_order_ids_fail_before_writing(sample_data_dir: Path, tmp_path: Path) -> None:
    orders_path = sample_data_dir / "olist_orders_dataset.csv"
    orders = pd.read_csv(orders_path)
    pd.concat([orders, orders.iloc[[0]]], ignore_index=True).to_csv(orders_path, index=False)

    with pytest.raises(ValueError, match="duplicate key values.*orders"):
        load_database(sample_data_dir, tmp_path / "olist.db")
