from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

from analysis import VALIDATION_KNOWN_CHECKS
from load_database import REQUIRED_FILES, get_validation_summary, load_database, main


def test_missing_required_csv_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="olist_orders_dataset.csv"):
        load_database(tmp_path / "data", tmp_path / "olist.db")


def test_missing_required_column_fails_before_writing(sample_data_dir: Path, tmp_path: Path) -> None:
    orders_path = sample_data_dir / "olist_orders_dataset.csv"
    orders = pd.read_csv(orders_path).drop(columns=["order_status"])
    orders.to_csv(orders_path, index=False)
    db_path = tmp_path / "olist.db"

    with pytest.raises(ValueError, match="missing required column.*order_status"):
        load_database(sample_data_dir, db_path)

    assert not db_path.exists()


def test_load_creates_tables_indexes_and_clean_views(sample_db: Path) -> None:
    with sqlite3.connect(sample_db) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        views = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'view'")}
        assert set(REQUIRED_FILES) <= tables
        assert {"cleaned_orders", "order_payment_totals", "cleaned_order_items"} <= views
        assert connection.execute("SELECT COUNT(*) FROM cleaned_orders").fetchone()[0] == 3
        assert (
            connection.execute(
                "SELECT payment_value FROM order_payment_totals WHERE order_id = 'o1'"
            ).fetchone()[0]
            == 12
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_%'"
            ).fetchone()[0]
            >= 4
        )


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


def test_load_database_main_reports_counts(
    monkeypatch: pytest.MonkeyPatch, sample_data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "cli.db"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "load_database.py",
            "--data-dir",
            str(sample_data_dir),
            "--db-path",
            str(db_path),
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "Loaded 7 tables" in output
    assert db_path.exists()


def _validation_summary(db_path: Path) -> dict[str, int]:
    return dict(get_validation_summary(db_path))


def test_validation_summary_reports_no_violations_for_clean_fixture(sample_db: Path) -> None:
    rows = get_validation_summary(sample_db)
    summary = dict(rows)

    assert summary
    assert [check_name for check_name, _ in rows] == sorted(summary)
    assert set(summary) == VALIDATION_KNOWN_CHECKS
    assert all(violation_count == 0 for violation_count in summary.values())


def test_validation_summary_requires_the_sql_marker(
    sample_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("load_database.VALIDATION_SUMMARY_MARKER", "-- marker not present")

    with pytest.raises(ValueError, match="Validation summary marker not found"):
        get_validation_summary(sample_db)


def test_validation_summary_surfaces_injected_relational_defects(sample_db: Path) -> None:
    with sqlite3.connect(sample_db) as connection:
        connection.executescript(
            """
            UPDATE orders
            SET customer_id = 'missing-customer',
                order_delivered_customer_date = '2020-12-31 10:00:00'
            WHERE order_id = 'o1';
            UPDATE order_items
            SET order_id = 'missing-order', product_id = 'missing-product', price = -1, freight_value = NULL
            WHERE order_id = 'o1';
            UPDATE order_payments
            SET order_id = 'missing-order', payment_value = -1
            WHERE order_id = 'o1';
            UPDATE order_reviews
            SET order_id = 'missing-order'
            WHERE order_id = 'o1';
            UPDATE products
            SET product_category_name = 'untranslated'
            WHERE product_id = 'p1';
            """
        )

    summary = _validation_summary(sample_db)

    assert summary["orders_missing_customer"] == 1
    assert summary["order_items_missing_order"] == 1
    assert summary["order_items_missing_product"] == 1
    assert summary["payments_missing_order"] == 2
    assert summary["reviews_missing_order"] == 1
    assert summary["order_items_invalid_price"] == 1
    assert summary["order_items_invalid_freight"] == 1
    assert summary["payments_invalid_value"] == 2
    assert summary["delivered_before_purchase"] == 1
    assert summary["delivered_orders_without_payment"] == 1
    assert summary["delivered_orders_without_items"] == 1
    assert summary["products_without_category_translation"] == 1


def test_null_order_identifier_fails_before_writing(sample_data_dir: Path, tmp_path: Path) -> None:
    orders_path = sample_data_dir / "olist_orders_dataset.csv"
    orders = pd.read_csv(orders_path)
    orders.loc[0, "order_id"] = pd.NA
    orders.to_csv(orders_path, index=False)
    db_path = tmp_path / "olist.db"

    with pytest.raises(ValueError, match="required identifier.*orders: order_id"):
        load_database(sample_data_dir, db_path)

    assert not db_path.exists()


def test_invalid_order_purchase_timestamp_fails_before_writing(
    sample_data_dir: Path, tmp_path: Path
) -> None:
    orders_path = sample_data_dir / "olist_orders_dataset.csv"
    orders = pd.read_csv(orders_path)
    orders.loc[0, "order_purchase_timestamp"] = "not-a-timestamp"
    orders.to_csv(orders_path, index=False)
    db_path = tmp_path / "olist.db"

    with pytest.raises(ValueError, match="invalid timestamp.*orders.order_purchase_timestamp"):
        load_database(sample_data_dir, db_path)

    assert not db_path.exists()
