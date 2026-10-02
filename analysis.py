"""Run business analysis and generate deterministic chart outputs."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from matplotlib.ticker import FuncFormatter

from load_database import get_validation_summary, load_database

SEGMENTS = {
    "Champions",
    "Loyal Customers",
    "Big Spenders",
    "At Risk",
    "Lost",
    "Potential",
}

VALIDATION_WARNING_CHECKS = frozenset(
    {
        "delivered_orders_without_payment",
        "products_without_category_translation",
    }
)
VALIDATION_KNOWN_CHECKS = frozenset(
    {
        "orders_missing_customer",
        "order_items_missing_order",
        "order_items_missing_product",
        "payments_missing_order",
        "reviews_missing_order",
        "order_items_invalid_price",
        "order_items_invalid_freight",
        "payments_invalid_value",
        "delivered_before_purchase",
        "estimated_before_purchase",
        "delivered_orders_without_payment",
        "delivered_orders_without_items",
        "products_without_category_translation",
    }
)

SEGMENT_COLORS = {
    "Champions": "#0072B2",
    "Loyal Customers": "#56B4E9",
    "Big Spenders": "#E69F00",
    "At Risk": "#D55E00",
    "Lost": "#CC79A7",
    "Potential": "#009E73",
}
PAYMENT_COLORS = {
    "boleto": "#E69F00",
    "credit_card": "#0072B2",
    "debit_card": "#009E73",
    "voucher": "#D55E00",
}
BAR_COLOR = "#0072B2"
LABEL_COLOR = "#243447"


class ValidationPolicyError(ValueError):
    """Raised when validation finds a blocking check or an unknown check name."""

    def __init__(
        self,
        validation_summary: list[tuple[str, int]],
        fatal_checks: list[tuple[str, int]],
    ) -> None:
        self.validation_summary = tuple(validation_summary)
        self.fatal_checks = tuple(fatal_checks)
        details = ", ".join(
            f"{check_name} ({violation_count:,} violation(s))"
            for check_name, violation_count in fatal_checks
        )
        super().__init__(f"Blocking data-quality checks: {details}")


def _validation_check_status(check_name: str, violation_count: int) -> str | None:
    """Return warning, fatal, or None according to the documented check policy."""
    if check_name not in VALIDATION_KNOWN_CHECKS:
        return "fatal"
    if violation_count == 0:
        return None
    if check_name in VALIDATION_WARNING_CHECKS:
        return "warning"
    return "fatal"


def _enforce_validation_policy(validation_summary: list[tuple[str, int]]) -> None:
    fatal_checks = [
        (check_name, violation_count)
        for check_name, violation_count in validation_summary
        if _validation_check_status(check_name, violation_count) == "fatal"
    ]
    if fatal_checks:
        raise ValidationPolicyError(validation_summary, fatal_checks)


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
        "review_quality_by_state": _query(
            db_path,
            """
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
            INNER JOIN cleaned_orders AS co ON co.order_id = ors.order_id
            INNER JOIN customers AS c ON c.customer_id = co.customer_id
            GROUP BY c.customer_state
            ORDER BY low_score_rate DESC, reviewed_orders DESC, c.customer_state
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
    ranks = values.rank(method="average", ascending=True)
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
    orders["purchase_month"] = pd.to_datetime(
        orders["order_purchase_timestamp"], errors="coerce"
    ).dt.to_period("M")
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


def _format_brazilian_number(value: float, decimals: int) -> str:
    amount = f"{value:,.{decimals}f}"
    integer, decimal, fraction = amount.partition(".")
    suffix = f",{fraction}" if decimal else ""
    return f"{integer.replace(',', '.')}{suffix}"


def format_brl(value: float, decimals: int = 2) -> str:
    """Format a numeric value as Brazilian reais without scientific notation."""
    return f"R$ {_format_brazilian_number(value, decimals)}"


def format_percent(value: float, decimals: int = 1) -> str:
    """Format a fraction such as 0.25 as a percentage such as 25.0%."""
    return f"{_format_brazilian_number(value * 100, decimals)}%"


def format_integer(value: float) -> str:
    """Format a whole-number count with Brazilian thousands separators."""
    return _format_brazilian_number(value, 0)


def _format_brl_compact(value: float) -> str:
    """Keep chart value labels readable while retaining an explicit BRL unit."""
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f"{format_brl(value / 1_000_000, decimals=1)}M"
    if absolute >= 1_000:
        return f"{format_brl(value / 1_000, decimals=1)}k"
    return format_brl(value)


def _format_brl_tick(value: float) -> str:
    """Use short, localized thousands and millions on chart currency axes."""
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f"{format_brl(value / 1_000_000, decimals=1)}M"
    if absolute >= 1_000:
        return f"{format_brl(value / 1_000, decimals=0)}k"
    return format_brl(value, decimals=0)


def _humanize_label(value: object) -> str:
    """Render raw category values as readable chart labels."""
    label = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}", label):
        return pd.Period(label, freq="M").strftime("%b %Y")
    if re.fullmatch(r"[A-Z]{2}", label):
        return label
    return " + ".join(part.strip().replace("_", " ").title() for part in label.split(","))


def _axis_label(column: str) -> str:
    labels = {
        "average_delivery_days": "Average delivery time (days)",
        "customer_state": "Customer state",
        "customers": "Unique customers",
        "month": "Purchase month",
        "monetary": "Revenue (BRL)",
        "payment_method": "Payment type",
        "revenue": "Revenue (BRL)",
        "segment": "RFM segment",
    }
    return labels.get(column, column.replace("_", " ").title())


def _bar_colors(data: pd.DataFrame, category_column: str) -> list[str]:
    categories = data[category_column].astype(str)
    if category_column == "segment":
        return [SEGMENT_COLORS.get(category, BAR_COLOR) for category in categories]
    if category_column == "payment_method":
        return [
            "#CC79A7" if "," in category else PAYMENT_COLORS.get(category, "#6B7280")
            for category in categories
        ]
    return [BAR_COLOR] * len(categories)


def _bar_value_label(value: float, value_column: str) -> str:
    if value_column in {"revenue", "monetary"}:
        return _format_brl_compact(value)
    if value_column == "average_delivery_days":
        return f"{value:.1f} d"
    return format_integer(value)


def _save_bar(
    data: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    caption: str,
    filename: str,
    output_dir: Path,
    *,
    horizontal: bool = False,
) -> Path:
    fig, axis = plt.subplots(figsize=(9, 5))
    labels = [_humanize_label(value) for value in data[x]]
    values = data[y].astype(float).tolist()
    positions = list(range(len(labels)))
    bars = None
    if horizontal:
        bars = axis.barh(positions, values, color=_bar_colors(data, x))
        axis.set_yticks(positions, labels=labels)
        axis.invert_yaxis()
        axis.set_xlim(0, max(values, default=0) * 1.28 or 1)
        axis.set_xlabel(_axis_label(y))
        axis.set_ylabel(_axis_label(x))
        if y in {"revenue", "monetary"}:
            axis.xaxis.set_major_formatter(
                FuncFormatter(lambda value, _position: _format_brl_tick(value))
            )
        elif y == "customers":
            axis.xaxis.set_major_formatter(
                FuncFormatter(lambda value, _position: format_integer(value))
            )
    else:
        bars = axis.bar(positions, values, color=_bar_colors(data, x))
        axis.set_xticks(positions, labels=labels)
        axis.set_ylim(0, max(values, default=0) * 1.28 or 1)
        axis.set_xlabel(_axis_label(x))
        axis.set_ylabel(_axis_label(y))
        axis.tick_params(axis="x", labelrotation=45)
        for tick_label in axis.get_xticklabels():
            tick_label.set_horizontalalignment("right")
        if y in {"revenue", "monetary"}:
            axis.yaxis.set_major_formatter(
                FuncFormatter(lambda value, _position: _format_brl_tick(value))
            )
    if bars is not None:
        axis.bar_label(
            bars,
            labels=[_bar_value_label(value, y) for value in values],
            padding=3,
            fontsize=7 if not horizontal and len(labels) > 12 else 8,
            color=LABEL_COLOR,
            rotation=90 if not horizontal and len(labels) > 12 else 0,
        )
    axis.set_title(title, loc="left", pad=12, fontweight="bold", color="#1F2937")
    axis.set_axisbelow(True)
    axis.grid(axis="x" if horizontal else "y", color="#DCE3EA", linewidth=0.7)
    fig.text(0.125, 0.012, caption, ha="left", va="bottom", fontsize=8, color="#475569")
    fig.tight_layout(rect=(0, 0.075, 1, 1))
    path = output_dir / filename
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def _write_analysis_bundle(
    business: dict[str, pd.DataFrame],
    rfm: pd.DataFrame,
    retention: pd.DataFrame,
    reconciliation: dict[str, float | int],
    output_dir: Path,
) -> Path:
    """Write stable machine-readable summaries without exporting customer-level RFM rows."""
    rfm_segments = (
        rfm.groupby("segment", as_index=False)
        .agg(customers=("customer_unique_id", "nunique"), revenue=("monetary", "sum"))
        .assign(revenue=lambda frame: frame["revenue"].round(2))
        .sort_values("segment")
    )
    retention_records = retention.assign(cohort_month=retention["cohort_month"].astype(str))
    payload = {
        "schema_version": 1,
        "business_queries": {
            name: json.loads(frame.to_json(orient="records"))
            for name, frame in business.items()
        },
        "rfm_segments": json.loads(rfm_segments.to_json(orient="records")),
        "cohort_retention": json.loads(retention_records.to_json(orient="records")),
        "revenue_reconciliation": reconciliation,
    }
    path = output_dir / "analysis_summary.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def generate_outputs(db_path: str | Path, output_dir: str | Path) -> list[Path]:
    """Generate the planned charts and machine-readable analysis bundle."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid")
    business = run_business_queries(db_path)
    rfm = calculate_rfm(db_path)
    validate_rfm(rfm)
    retention = calculate_cohort_retention(db_path)
    reconciliation = calculate_revenue_reconciliation(db_path)

    written = [
        _save_bar(
            business["monthly_revenue"],
            "month",
            "revenue",
            "Monthly revenue",
            "Order-level payment value for paid delivered orders, grouped by purchase month. "
            "Bar values are abbreviated; see analysis_summary.json for exact totals.",
            "monthly_revenue.png",
            output_dir,
        ),
        _save_bar(
            business["payment_method"],
            "payment_method",
            "revenue",
            "Revenue by payment method",
            "Payment types are combined per order to avoid counting payment rows as orders. "
            "Bar values are abbreviated; see analysis_summary.json for exact totals.",
            "payment_method_revenue.png",
            output_dir,
            horizontal=True,
        ),
        _save_bar(
            business["delivery_by_state"],
            "customer_state",
            "average_delivery_days",
            "Average delivery time by state",
            "Elapsed days use delivered orders with the timestamps needed for this measure.",
            "delivery_by_state.png",
            output_dir,
            horizontal=True,
        ),
        _save_bar(
            rfm["segment"].value_counts().rename_axis("segment").reset_index(name="customers"),
            "segment",
            "customers",
            "Customers by RFM segment",
            "Each unique customer has one segment; tied values receive equal quintile scores.",
            "rfm_segments.png",
            output_dir,
            horizontal=True,
        ),
        _save_bar(
            rfm.groupby("segment", as_index=False)["monetary"]
            .sum()
            .sort_values("monetary", ascending=False),
            "segment",
            "monetary",
            "Revenue contribution by RFM segment",
            "Revenue sums order-level payments for each customer's delivered orders. "
            "Bar values are abbreviated; see analysis_summary.json for exact totals.",
            "rfm_revenue.png",
            output_dir,
            horizontal=True,
        ),
    ]

    pivot = retention.pivot(index="cohort_month", columns="cohort_index", values="retention_rate")
    figure_width = max(10, min(18, 0.65 * len(pivot.columns) + 3))
    figure_height = max(6, min(14, 0.35 * len(pivot.index) + 3))
    annotate = int(pivot.count().sum()) <= 250
    annotations = (
        pivot.apply(
            lambda column: column.map(
                lambda value: format_percent(value, decimals=1) if pd.notna(value) else ""
            )
        )
        if annotate
        else False
    )
    fig, axis = plt.subplots(figsize=(figure_width, figure_height))
    sns.heatmap(
        pivot,
        annot=annotations,
        fmt="",
        mask=pivot.isna(),
        cmap="cividis",
        vmin=0,
        vmax=1,
        ax=axis,
        annot_kws={"fontsize": 7},
        cbar_kws={"label": "Retention rate"},
    )
    if annotate:
        for annotation in axis.texts:
            column = int(annotation.get_position()[0])
            row = int(annotation.get_position()[1])
            value = pivot.iloc[row, column]
            annotation.set_color("#17202A" if value >= 0.45 else "white")
    colorbar = axis.collections[0].colorbar
    colorbar.ax.yaxis.set_major_formatter(
        FuncFormatter(lambda value, _position: format_percent(value, decimals=0))
    )
    axis.set_title("Monthly cohort retention (delivered orders)")
    axis.set_xlabel("Months since first purchase")
    axis.set_ylabel("Cohort month")
    axis.set_yticklabels([_humanize_label(label.get_text()) for label in axis.get_yticklabels()])
    fig.text(
        0.08,
        0.012,
        "Each cell is active customers divided by the original delivered-order cohort; "
        "blanks mean no observed activity.",
        ha="left",
        va="bottom",
        fontsize=8,
        color="#475569",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    heatmap_path = output_dir / "cohort_retention.png"
    fig.savefig(heatmap_path, dpi=160)
    plt.close(fig)
    written.append(heatmap_path)
    written.append(_write_analysis_bundle(business, rfm, retention, reconciliation, output_dir))
    return written


def run_pipeline(
    data_dir: str | Path = "data",
    db_path: str | Path = "olist.db",
    output_dir: str | Path = "outputs",
) -> list[Path]:
    load_database(data_dir, db_path)
    validation_summary = get_validation_summary(db_path)
    _enforce_validation_policy(validation_summary)
    return generate_outputs(db_path, output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--db-path", type=Path, default=Path("olist.db"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    try:
        paths = run_pipeline(args.data_dir, args.db_path, args.output_dir)
    except ValidationPolicyError as error:
        print("Data-quality checks:")
        for check_name, violation_count in error.validation_summary:
            print(f"  {check_name}: {violation_count:,} violation(s)")
        parser.error(str(error))
    print(f"Generated {len(paths)} artifacts in {args.output_dir}")
    for path in paths:
        print(f"  {path.name}")
    print("Data-quality checks:")
    for check_name, violation_count in get_validation_summary(args.db_path):
        print(f"  {check_name}: {violation_count:,} violation(s)")


if __name__ == "__main__":
    main()
