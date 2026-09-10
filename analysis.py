"""Run business analysis and generate deterministic chart outputs."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from load_database import load_database


SEGMENTS = {
    "Champions",
    "Loyal Customers",
    "Big Spenders",
    "At Risk",
    "Lost",
    "Potential",
}


def _query(db_path: str | Path, sql: str) -> pd.DataFrame:
    with sqlite3.connect(db_path) as connection:
        return pd.read_sql_query(sql, connection)


def run_business_queries(db_path: str | Path) -> dict[str, pd.DataFrame]:
    """Return the core business outputs with order-level revenue preserved."""
    return {
        "monthly_revenue": _query(
            db_path,
            """
            SELECT substr(co.order_purchase_timestamp, 1, 7) AS month,
                   ROUND(SUM(pt.payment_value), 2) AS revenue
            FROM cleaned_orders AS co
            INNER JOIN order_payment_totals AS pt ON pt.order_id = co.order_id
            GROUP BY month
            ORDER BY month
            """,
        ),
        "payment_method": _query(
            db_path,
            """
            SELECT payment_method,
                   COUNT(*) AS orders,
                   ROUND(SUM(payment_value), 2) AS revenue
            FROM order_payment_totals AS pt
            INNER JOIN cleaned_orders AS co ON co.order_id = pt.order_id
            GROUP BY payment_method
            ORDER BY revenue DESC
            """,
        ),
        "delivery_performance": _query(
            db_path,
            """
            SELECT delivery_status, COUNT(*) AS orders
            FROM cleaned_orders
            GROUP BY delivery_status
            ORDER BY delivery_status
            """,
        ),
        "delivery_by_state": _query(
            db_path,
            """
            SELECT c.customer_state,
                   ROUND(AVG(co.delivery_days), 2) AS average_delivery_days
            FROM cleaned_orders AS co
            INNER JOIN customers AS c ON c.customer_id = co.customer_id
            GROUP BY c.customer_state
            ORDER BY average_delivery_days DESC
            """,
        ),
        "revenue_by_category": _query(
            db_path,
            """
            SELECT category_name,
                   ROUND(SUM(item_revenue), 2) AS revenue
            FROM cleaned_order_items
            GROUP BY category_name
            ORDER BY revenue DESC
            """,
        ),
    }


def calculate_revenue_reconciliation(db_path: str | Path) -> dict[str, float | int]:
    """Compare payment totals with item plus freight totals for paid deliveries."""
    totals = _query(
        db_path,
        """
        WITH item_totals AS (
            SELECT order_id, ROUND(SUM(item_revenue), 2) AS item_revenue
            FROM cleaned_order_items
            GROUP BY order_id
        )
        SELECT
            COUNT(*) AS paid_delivered_orders,
            ROUND(SUM(pt.payment_value), 2) AS payment_revenue,
            ROUND(SUM(it.item_revenue), 2) AS item_revenue,
            ROUND(SUM(pt.payment_value) - SUM(it.item_revenue), 2) AS payment_item_variance
        FROM order_payment_totals AS pt
        INNER JOIN cleaned_orders AS co ON co.order_id = pt.order_id
        INNER JOIN item_totals AS it ON it.order_id = pt.order_id
        """,
    ).iloc[0]
    untranslated = _query(
        db_path,
        """
        SELECT COUNT(*) AS untranslated_item_rows
        FROM cleaned_order_items
        WHERE product_category_name IS NOT NULL
          AND product_category_name = category_name
        """,
    ).iloc[0]
    if pd.isna(totals["payment_revenue"]):
        raise ValueError("No paid delivered orders are available for revenue reconciliation")
    return {
        "paid_delivered_orders": int(totals["paid_delivered_orders"]),
        "payment_revenue": float(totals["payment_revenue"]),
        "item_revenue": float(totals["item_revenue"]),
        "payment_item_variance": float(totals["payment_item_variance"]),
        "untranslated_item_rows": int(untranslated["untranslated_item_rows"]),
    }


def _score_quintile(values: pd.Series, *, higher_is_better: bool) -> pd.Series:
    ranks = values.rank(method="first", ascending=True)
    base_score = ((ranks / len(values)) * 5).clip(lower=1, upper=5).astype(int)
    return base_score if higher_is_better else 6 - base_score


def _segment(row: pd.Series) -> str:
    """Apply the documented precedence from strongest to weakest."""
    if row.recency_score >= 4 and row.frequency_score >= 4 and row.monetary_score >= 4:
        return "Champions"
    if row.recency_score >= 3 and row.frequency_score >= 4:
        return "Loyal Customers"
    if row.monetary_score >= 4:
        return "Big Spenders"
    if row.recency_score <= 2 and row.frequency_score >= 3:
        return "At Risk"
    if row.recency_score <= 2 and row.frequency_score <= 2:
        return "Lost"
    return "Potential"


def calculate_rfm(db_path: str | Path, snapshot_date: str | pd.Timestamp | None = None) -> pd.DataFrame:
    """Calculate RFM metrics per real customer, using delivered orders only."""
    orders = _query(
        db_path,
        """
        SELECT c.customer_unique_id,
               co.order_id,
               co.order_purchase_timestamp,
               pt.payment_value
        FROM cleaned_orders AS co
        INNER JOIN customers AS c ON c.customer_id = co.customer_id
        INNER JOIN order_payment_totals AS pt ON pt.order_id = co.order_id
        """,
    )
    orders["order_purchase_timestamp"] = pd.to_datetime(orders["order_purchase_timestamp"], errors="coerce")
    if orders.empty:
        raise ValueError("No delivered orders with payments are available for RFM analysis")

    if snapshot_date is None:
        snapshot = orders["order_purchase_timestamp"].max().normalize() + pd.Timedelta(days=1)
    else:
        snapshot = pd.Timestamp(snapshot_date).normalize()

    rfm = (
        orders.groupby("customer_unique_id", as_index=False)
        .agg(
            last_purchase=("order_purchase_timestamp", "max"),
            frequency=("order_id", "nunique"),
            monetary=("payment_value", "sum"),
        )
        .assign(
            recency=lambda frame: (snapshot - frame["last_purchase"].dt.normalize()).dt.days,
            monetary=lambda frame: frame["monetary"].round(2),
        )
    )
    rfm["recency_score"] = _score_quintile(rfm["recency"], higher_is_better=False)
    rfm["frequency_score"] = _score_quintile(rfm["frequency"], higher_is_better=True)
    rfm["monetary_score"] = _score_quintile(rfm["monetary"], higher_is_better=True)
    rfm["segment"] = rfm.apply(_segment, axis=1)
    rfm["snapshot_date"] = snapshot.date().isoformat()
    return rfm.sort_values(["segment", "monetary"], ascending=[True, False]).reset_index(drop=True)


def validate_rfm(rfm: pd.DataFrame) -> None:
    """Raise when RFM output violates its reconciliation contract."""
    required = {"customer_unique_id", "recency", "frequency", "monetary", "segment"}
    missing = required - set(rfm.columns)
    if missing:
        raise ValueError(f"RFM output is missing columns: {', '.join(sorted(missing))}")
    if not rfm["customer_unique_id"].is_unique:
        raise ValueError("Each customer must receive exactly one RFM row")
    if not rfm["segment"].isin(SEGMENTS).all():
        raise ValueError("RFM output contains an unknown segment")
    if (rfm[["recency", "frequency", "monetary"]] < 0).any().any():
        raise ValueError("RFM metrics cannot be negative")


def calculate_cohort_retention(db_path: str | Path) -> pd.DataFrame:
    """Calculate monthly retention based on subsequent delivered orders."""
    orders = _query(
        db_path,
        """
        SELECT c.customer_unique_id, co.order_purchase_timestamp
        FROM cleaned_orders AS co
        INNER JOIN customers AS c ON c.customer_id = co.customer_id
        """,
    )
    orders["purchase_month"] = pd.to_datetime(orders["order_purchase_timestamp"], errors="coerce").dt.to_period("M")
    orders = orders.dropna(subset=["customer_unique_id", "purchase_month"]).drop_duplicates(
        ["customer_unique_id", "purchase_month"]
    )
    if orders.empty:
        raise ValueError("No delivered orders are available for cohort analysis")

    first_month = orders.groupby("customer_unique_id")["purchase_month"].min().rename("cohort_month")
    activity = orders.join(first_month, on="customer_unique_id")
    activity["cohort_index"] = (
        (activity["purchase_month"].dt.year - activity["cohort_month"].dt.year) * 12
        + activity["purchase_month"].dt.month
        - activity["cohort_month"].dt.month
    )
    cohort_sizes = activity.groupby("cohort_month")["customer_unique_id"].nunique().rename("cohort_customers")
    retention = (
        activity.groupby(["cohort_month", "cohort_index"])["customer_unique_id"]
        .nunique()
        .rename("active_customers")
        .reset_index()
        .merge(cohort_sizes.reset_index(), on="cohort_month")
    )
    retention["retention_rate"] = (
        retention["active_customers"] / retention["cohort_customers"]
    ).round(4)
    return retention.sort_values(["cohort_month", "cohort_index"]).reset_index(drop=True)


def _save_bar(data: pd.DataFrame, x: str, y: str, title: str, filename: str, output_dir: Path, *, horizontal: bool = False) -> Path:
    fig, axis = plt.subplots(figsize=(9, 5))
    if horizontal:
        sns.barplot(data=data, x=y, y=x, ax=axis, color="#2563eb")
    else:
        sns.barplot(data=data, x=x, y=y, ax=axis, color="#2563eb")
    axis.set_title(title)
    axis.set_xlabel(axis.get_xlabel().replace("_", " ").title())
    axis.set_ylabel(axis.get_ylabel().replace("_", " ").title())
    if not horizontal:
        axis.tick_params(axis="x", labelrotation=45)
        for label in axis.get_xticklabels():
            label.set_horizontalalignment("right")
    fig.tight_layout()
    path = output_dir / filename
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def generate_outputs(db_path: str | Path, output_dir: str | Path) -> list[Path]:
    """Generate the six planned charts and return their paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid")
    business = run_business_queries(db_path)
    rfm = calculate_rfm(db_path)
    validate_rfm(rfm)
    retention = calculate_cohort_retention(db_path)

    written = [
        _save_bar(business["monthly_revenue"], "month", "revenue", "Monthly revenue", "monthly_revenue.png", output_dir),
        _save_bar(business["payment_method"], "payment_method", "revenue", "Revenue by payment method", "payment_method_revenue.png", output_dir, horizontal=True),
        _save_bar(business["delivery_by_state"], "customer_state", "average_delivery_days", "Average delivery time by state", "delivery_by_state.png", output_dir, horizontal=True),
        _save_bar(rfm["segment"].value_counts().rename_axis("segment").reset_index(name="customers"), "segment", "customers", "Customers by RFM segment", "rfm_segments.png", output_dir, horizontal=True),
        _save_bar(rfm.groupby("segment", as_index=False)["monetary"].sum().sort_values("monetary", ascending=False), "segment", "monetary", "Revenue contribution by RFM segment", "rfm_revenue.png", output_dir, horizontal=True),
    ]

    pivot = retention.pivot(index="cohort_month", columns="cohort_index", values="retention_rate")
    figure_width = max(10, min(18, 0.65 * len(pivot.columns) + 3))
    figure_height = max(6, min(14, 0.35 * len(pivot.index) + 3))
    annotate = pivot.size <= 100
    fig, axis = plt.subplots(figsize=(figure_width, figure_height))
    sns.heatmap(
        pivot,
        annot=annotate,
        fmt=".0%" if annotate else "",
        cmap="Blues",
        vmin=0,
        vmax=1,
        ax=axis,
        cbar_kws={"label": "Retention rate"},
    )
    axis.set_title("Monthly cohort retention (delivered orders)")
    axis.set_xlabel("Months since first purchase")
    axis.set_ylabel("Cohort month")
    fig.tight_layout()
    heatmap_path = output_dir / "cohort_retention.png"
    fig.savefig(heatmap_path, dpi=160)
    plt.close(fig)
    written.append(heatmap_path)
    return written


def run_pipeline(data_dir: str | Path = "data", db_path: str | Path = "olist.db", output_dir: str | Path = "outputs") -> list[Path]:
    load_database(data_dir, db_path)
    return generate_outputs(db_path, output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--db-path", type=Path, default=Path("olist.db"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    paths = run_pipeline(args.data_dir, args.db_path, args.output_dir)
    print(f"Generated {len(paths)} charts in {args.output_dir}")
    for path in paths:
        print(f"  {path.name}")


if __name__ == "__main__":
    main()
