from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

from analysis import (
    _segment,
    calculate_cohort_retention,
    calculate_revenue_reconciliation,
    calculate_rfm,
    generate_outputs,
    main,
    run_business_queries,
    run_pipeline,
    validate_rfm,
)


def test_business_queries_use_translated_categories_and_order_level_payments(sample_db: Path) -> None:
    results = run_business_queries(sample_db)
    categories = results["revenue_by_category"]
    assert set(categories["category_name"]) == {"health_beauty", "perfume", "sports_leisure"}
    assert results["monthly_revenue"]["revenue"].sum() == 51
    assert results["payment_method"]["revenue"].sum() == 51
    assert "credit_card,voucher" in set(results["payment_method"]["payment_method"])
    assert results["delivery_performance"].set_index("delivery_status")["orders"].to_dict() == {
        "Late": 1,
        "On time": 2,
    }


def test_rfm_has_one_segment_per_customer_and_reconciles(sample_db: Path) -> None:
    rfm = calculate_rfm(sample_db)
    validate_rfm(rfm)
    assert len(rfm) == 2
    assert rfm["customer_unique_id"].is_unique
    assert rfm["frequency"].sum() == 3
    assert rfm["monetary"].sum() == 51
    assert set(rfm["segment"]) <= {"Champions", "Loyal Customers", "Big Spenders", "At Risk", "Lost", "Potential"}


def test_rfm_accepts_explicit_snapshot_date(sample_db: Path) -> None:
    rfm = calculate_rfm(sample_db, snapshot_date="2021-03-01")

    assert set(rfm["snapshot_date"]) == {"2021-03-01"}
    assert dict(zip(rfm["customer_unique_id"], rfm["recency"])) == {"u1": 28, "u2": 45}


@pytest.mark.parametrize(
    ("scores", "expected"),
    [
        ((4, 4, 4), "Champions"),
        ((3, 4, 3), "Loyal Customers"),
        ((3, 3, 4), "Big Spenders"),
        ((2, 3, 3), "At Risk"),
        ((2, 2, 3), "Lost"),
        ((3, 2, 3), "Potential"),
    ],
)
def test_rfm_segment_precedence(scores: tuple[int, int, int], expected: str) -> None:
    row = pd.Series(
        {
            "recency_score": scores[0],
            "frequency_score": scores[1],
            "monetary_score": scores[2],
        }
    )

    assert _segment(row) == expected


def test_rfm_rejects_empty_paid_orders(sample_db: Path) -> None:
    with sqlite3.connect(sample_db) as connection:
        connection.execute("DELETE FROM order_payments")

    with pytest.raises(ValueError, match="No delivered orders with payments"):
        calculate_rfm(sample_db)


def test_revenue_reconciliation_rejects_empty_paid_orders(sample_db: Path) -> None:
    with sqlite3.connect(sample_db) as connection:
        connection.execute("DELETE FROM order_payments")

    with pytest.raises(ValueError, match="No paid delivered orders"):
        calculate_revenue_reconciliation(sample_db)


def test_revenue_reconciliation_reports_payment_item_variance(sample_db: Path) -> None:
    reconciliation = calculate_revenue_reconciliation(sample_db)
    assert reconciliation == {
        "paid_delivered_orders": 3,
        "payment_revenue": 51.0,
        "item_revenue": 51.0,
        "payment_item_variance": 0.0,
        "untranslated_item_rows": 0,
    }


def test_cohort_retention_uses_delivered_orders(sample_db: Path) -> None:
    retention = calculate_cohort_retention(sample_db)
    jan = retention[retention["cohort_month"] == pd.Period("2021-01", freq="M")]
    month_zero = jan[jan["cohort_index"] == 0].iloc[0]
    month_one = jan[jan["cohort_index"] == 1].iloc[0]
    assert month_zero["active_customers"] == 2
    assert month_zero["retention_rate"] == 1
    assert month_one["active_customers"] == 1
    assert month_one["retention_rate"] == 0.5


def test_cohort_retention_rejects_empty_delivered_orders(sample_db: Path) -> None:
    with sqlite3.connect(sample_db) as connection:
        connection.execute("DELETE FROM orders")

    with pytest.raises(ValueError, match="No delivered orders"):
        calculate_cohort_retention(sample_db)


def test_validate_rfm_rejects_each_contract_violation() -> None:
    valid = pd.DataFrame(
        {
            "customer_unique_id": ["u1", "u2"],
            "recency": [1, 2],
            "frequency": [1, 2],
            "monetary": [10.0, 20.0],
            "segment": ["Potential", "Champions"],
        }
    )
    invalid_cases = [
        (valid.drop(columns=["monetary"]), "missing columns"),
        (pd.concat([valid, valid.iloc[[0]]], ignore_index=True), "exactly one RFM row"),
        (valid.assign(segment=["Potential", "Unknown"]), "unknown segment"),
        (valid.assign(monetary=[-1.0, 20.0]), "cannot be negative"),
    ]

    for frame, message in invalid_cases:
        with pytest.raises(ValueError, match=message):
            validate_rfm(frame)


def test_generate_outputs_writes_expected_charts(sample_db: Path, tmp_path: Path) -> None:
    written = generate_outputs(sample_db, tmp_path / "outputs")
    assert len(written) == 6
    assert all(path.exists() and path.stat().st_size > 0 for path in written)


def test_run_pipeline_loads_database_and_writes_all_outputs(
    sample_data_dir: Path, tmp_path: Path
) -> None:
    written = run_pipeline(sample_data_dir, tmp_path / "pipeline.db", tmp_path / "outputs")

    assert len(written) == 6
    assert all(path.exists() and path.stat().st_size > 0 for path in written)


def test_analysis_main_runs_pipeline(monkeypatch: pytest.MonkeyPatch, sample_data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "cli.db"
    output_dir = tmp_path / "cli-outputs"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "analysis.py",
            "--data-dir",
            str(sample_data_dir),
            "--db-path",
            str(db_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    main()

    assert "Generated 6 charts" in capsys.readouterr().out
