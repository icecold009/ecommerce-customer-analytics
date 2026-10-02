from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

from analysis import (
    _score_quintile,
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


def test_review_quality_by_state_aggregates_reviews_once_per_order(sample_db: Path) -> None:
    with sqlite3.connect(sample_db) as connection:
        connection.execute("UPDATE order_reviews SET review_score = 2 WHERE order_id = 'o2'")

    review_quality = run_business_queries(sample_db)["review_quality_by_state"]

    assert list(review_quality["customer_state"]) == ["SP"]
    assert review_quality.iloc[0]["reviewed_orders"] == 2
    assert review_quality.iloc[0]["average_review_score"] == 3.5
    assert review_quality.iloc[0]["low_score_rate"] == 0.5


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


@pytest.mark.parametrize("higher_is_better", [True, False])
def test_rfm_tied_values_receive_equal_quintile_scores(higher_is_better: bool) -> None:
    values = pd.Series([10, 10, 20, 20], index=["a", "b", "c", "d"])

    scores = _score_quintile(values, higher_is_better=higher_is_better)

    assert scores["a"] == scores["b"]
    assert scores["c"] == scores["d"]


def test_rfm_quintile_score_direction_is_preserved() -> None:
    values = pd.Series([1, 2, 3, 4, 5])

    assert _score_quintile(values, higher_is_better=True).tolist() == [1, 2, 3, 4, 5]
    assert _score_quintile(values, higher_is_better=False).tolist() == [5, 4, 3, 2, 1]


def test_rfm_scores_and_segments_do_not_depend_on_customer_row_order() -> None:
    metrics = pd.DataFrame(
        {
            "recency": [5, 6, 7, 8, 9, 10, 1, 2, 3, 4],
            "frequency": [1, 2, 3, 4, 5, 6, 7, 7, 8, 9],
            "monetary": [1, 2, 3, 4, 7, 8, 5, 6, 9, 10],
        },
        index=[f"customer-{number}" for number in range(1, 11)],
    )

    def score_and_segment(frame: pd.DataFrame) -> pd.DataFrame:
        scored = frame.copy()
        scored["recency_score"] = _score_quintile(scored["recency"], higher_is_better=False)
        scored["frequency_score"] = _score_quintile(scored["frequency"], higher_is_better=True)
        scored["monetary_score"] = _score_quintile(scored["monetary"], higher_is_better=True)
        scored["segment"] = scored.apply(_segment, axis=1)
        return scored[["recency_score", "frequency_score", "monetary_score", "segment"]]

    original = score_and_segment(metrics).sort_index()
    shuffled = score_and_segment(metrics.iloc[[0, 1, 2, 3, 4, 5, 7, 6, 8, 9]]).sort_index()

    pd.testing.assert_frame_equal(original, shuffled)
    assert original.loc["customer-7", "frequency_score"] == original.loc["customer-8", "frequency_score"]
    assert original.loc["customer-7", "segment"] == original.loc["customer-8", "segment"]


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
    assert len(written) == 7
    assert all(path.exists() and path.stat().st_size > 0 for path in written)

    bundle_path = tmp_path / "outputs" / "analysis_summary.json"
    bundle_text = bundle_path.read_text(encoding="utf-8")
    bundle = json.loads(bundle_text)
    assert bundle["schema_version"] == 1
    assert {
        "monthly_revenue",
        "payment_method",
        "delivery_performance",
        "delivery_by_state",
        "review_quality_by_state",
        "revenue_by_category",
    } == set(bundle["business_queries"])
    assert all(set(row) == {"customers", "revenue", "segment"} for row in bundle["rfm_segments"])
    assert sum(row["customers"] for row in bundle["rfm_segments"]) == 2
    assert sum(row["revenue"] for row in bundle["rfm_segments"]) == 51.0
    assert bundle["cohort_retention"][0]["cohort_month"] == "2021-01"
    assert bundle["revenue_reconciliation"]["payment_revenue"] == 51.0

    generate_outputs(sample_db, tmp_path / "outputs")
    assert bundle_path.read_text(encoding="utf-8") == bundle_text


def test_run_pipeline_loads_database_and_writes_all_outputs(
    sample_data_dir: Path, tmp_path: Path
) -> None:
    written = run_pipeline(sample_data_dir, tmp_path / "pipeline.db", tmp_path / "outputs")

    assert len(written) == 7
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

    assert "Generated 7 artifacts" in capsys.readouterr().out
