from __future__ import annotations

from pathlib import Path

import pandas as pd

from analysis import (
    calculate_cohort_retention,
    calculate_revenue_reconciliation,
    calculate_rfm,
    generate_outputs,
    run_business_queries,
    validate_rfm,
)


def test_business_queries_use_translated_categories_and_order_level_payments(sample_db: Path) -> None:
    results = run_business_queries(sample_db)
    categories = results["revenue_by_category"]
    assert set(categories["category_name"]) == {"health_beauty", "perfume", "sports_leisure"}
    assert results["monthly_revenue"]["revenue"].sum() == 51
    assert results["payment_method"]["revenue"].sum() == 51
    assert "credit_card,voucher" in set(results["payment_method"]["payment_method"])


def test_rfm_has_one_segment_per_customer_and_reconciles(sample_db: Path) -> None:
    rfm = calculate_rfm(sample_db)
    validate_rfm(rfm)
    assert len(rfm) == 2
    assert rfm["customer_unique_id"].is_unique
    assert rfm["frequency"].sum() == 3
    assert rfm["monetary"].sum() == 51
    assert set(rfm["segment"]) <= {"Champions", "Loyal Customers", "Big Spenders", "At Risk", "Lost", "Potential"}


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


def test_generate_outputs_writes_expected_charts(sample_db: Path, tmp_path: Path) -> None:
    written = generate_outputs(sample_db, tmp_path / "outputs")
    assert len(written) == 6
    assert all(path.exists() and path.stat().st_size > 0 for path in written)
