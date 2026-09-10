# E-commerce Customer Analytics

A reproducible, local-first analytics pipeline for the public Olist Brazilian e-commerce dataset. The project keeps raw CSV extracts in an ignored `data/` directory, loads them into SQLite, creates a documented analytical cleaning layer, and generates business analysis and charts.

## What this project answers

- How does delivered-order revenue change by month?
- Which payment methods and product categories contribute revenue?
- Which customer states have the longest average delivery times?
- How are customers distributed across RFM segments?
- How many customers return in each month after their first delivered order?

## Repository layout

```text
ecommerce-customer-analytics/
├── data/                  # ignored Olist CSV files
├── outputs/               # ignored generated charts
├── sql/                   # validation and reference SQL
├── tests/                 # loader, analysis, and pipeline tests
├── load_database.py       # raw-table loading and analytical views
├── analysis.py            # business queries, RFM, cohorts, charts
├── requirements.txt
└── requirements-dev.txt
```

## Dataset

Download the seven required Olist extracts from the dataset source and place them directly in `data/`:

```text
olist_customers_dataset.csv
olist_orders_dataset.csv
olist_order_items_dataset.csv
olist_order_payments_dataset.csv
olist_order_reviews_dataset.csv
olist_products_dataset.csv
product_category_name_translation.csv
```

The raw CSVs, SQLite database, and generated charts are intentionally excluded from Git. This keeps the repository small and makes the data boundary explicit. Confirm the dataset's current license and terms at the source before redistribution.

## Data model and cleaning contract

The loader preserves each CSV as a raw SQLite table. It also creates:

- `cleaned_orders`: delivered orders with purchase, delivered, and estimated-delivery timestamps; it adds delivery duration and on-time/late status.
- `order_payment_totals`: one row per order with payment values summed once, preventing payment-row duplication in order-level revenue.
- `cleaned_order_items`: delivered order items joined through `products` and then `category_translation`; category translations are never joined directly to product IDs.

The cleaned views are used for delivery and cohort analysis. Payment-based revenue and RFM use the intersection of `cleaned_orders` and `order_payment_totals`. The canonical extract contains one delivered order (`bfbd0f9bdef84302105ad712db648a6c`) without a payment row; the validation query surfaces it and payment-based analyses intentionally exclude it. Category analysis retains untranslated categories through a fallback to the Portuguese name. Raw tables remain available for validation and future analyses. Orders removed from `cleaned_orders` are not delivered or lack one of the timestamps required for delivery analysis.

## RFM definitions

RFM is calculated per `customer_unique_id` over delivered orders:

- Recency: days from the last delivered purchase to one day after the latest valid purchase in the dataset.
- Frequency: distinct delivered orders.
- Monetary: summed order payment value from `order_payment_totals`.

Scores use deterministic rank-based quintiles. Segment precedence is explicit: Champions, Loyal Customers, Big Spenders, At Risk, Lost, then Potential. `analysis.py` validates that every customer has exactly one valid segment and that metrics are non-negative.

## Cohort definition

Each customer is assigned to the month of their first delivered order. Retention means the customer has at least one delivered order in a later calendar month. The heatmap reports active customers divided by the original cohort size.

## Reproduce locally in PowerShell

```powershell
Set-Location "C:\path\to\ecommerce-customer-analytics"
New-Item -ItemType Directory -Force data, outputs | Out-Null

py -3.11 -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt

# Place the seven CSV files in .\data first.
python .\analysis.py --data-dir .\data --db-path .\olist.db --output-dir .\outputs
python -m pytest
```

If a Windows-managed temp directory denies pytest access, keep the temporary
test files inside the checkout instead:

```powershell
python -m pytest --basetemp .pytest-tmp
```

The runtime prints loaded row counts and generates six deterministic PNGs: monthly revenue, payment-method revenue, delivery time by state, RFM segment counts, RFM revenue contribution, and cohort retention.

## Findings and recommendations

The current run used the canonical Olist extract downloaded on 2026-09-10. It included 96,470 delivered orders, of which 96,469 had payment rows used for payment-based analysis, plus 93,349 unique customers and 22 purchase months. Paid delivered orders totalled R$15,421,082.85 in order-level payment value. Item plus freight totals for those same orders were R$15,418,251.37, a measured variance of R$2,831.48 that should not be silently treated as a data error because payment and item measures represent different business concepts. There were 7,495 item rows without an English translation; these remained in category analysis under their Portuguese category name. The largest translated product categories by item value were health_beauty (R$1,412,089.53), watches_gifts (R$1,264,016.98), and bed_bath_table (R$1,225,209.26). Credit-card-only orders contributed R$11,961,042.50; mixed credit-card/voucher orders were canonicalized into one R$324,442.66 category.

Delivery duration was longest in RR (29.39 days), AP (27.19), and AM (26.43). RFM produced 48,447 Potential customers, 14,926 Big Spenders, 12,188 Loyal Customers, 9,127 Lost customers, 5,827 At Risk customers, and 2,834 Champions. Big Spenders contributed the largest segment revenue at R$6,605,562.21, followed by Potential at R$4,650,478.02.

For cohorts with at least 100 customers, month-one delivered-order retention ranged from 0.18% to 0.72%, with a 0.49% median. The one-customer 2016-12 cohort is excluded from that comparison because its 100% rate is not representative.

Recommended actions are to investigate delivery capacity in the northern outlier states, test category-specific retention offers for high-value customers, and treat the very low repeat-order rate as a retention problem to validate with campaign and marketplace data. These are directional recommendations from historical marketplace data, not causal conclusions. Limitations include the 2016–2018 coverage window, missing customer demographics, anonymized records, and the difference between delivered order payment value and recognized accounting revenue.

## Verification

The automated suite uses a small relational fixture and checks missing-input failures, repeatable loading, table/view/index creation, payment aggregation, category joins, RFM reconciliation, cohort retention, and all chart artifacts. A full-dataset run is required before making claims about actual business performance.
