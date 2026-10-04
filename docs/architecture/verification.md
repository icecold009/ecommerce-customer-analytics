# Documentation verification record

Snapshot: `3609c9a80a117dbf0ed00d27b075a9aad09e9550`. Checks observed on 2026-10-03 in this isolated feature-branch copy.

| Acceptance check | Observed evidence |
| --- | --- |
| Source and diagram links | 19 case-study/diagram references resolve; 8 root-embedded diagram click targets checked. |
| Root diagram fidelity | Embedded Mermaid equals overview.mmd after adapting relative source URLs to the root README location. |
| Tracked-file accounting | 15 snapshot paths assigned exactly once; no missing or duplicate paths. |
| Detail graph structure | 4 functional groups have diagram nodes; no dangling endpoints. |
| Preview rendering | Overview and detail Mermaid rendered successfully; separate output PNG previews inspected previously. No new PNG is proposed for this repository. |
| Previously truncated source | 2 contiguous redacted fragments cover all lines of 1 previously truncated files; each was sent in a successful Jev helper call. |
| Application behavior | Application runtime was not exercised in this documentation task. |

These checks verify documentation structure and recorded review coverage. Inventory accounting does not establish every execution path, source conformance or hosted behavior. Fragment reviews retain their individual uncertainty; successful transmission is not approval. Jev thresholds remain unchanged. Integration remains pending unresolved warnings. No application code, dependency, schema, deployment or user data is changed.

## Reproduce structural checks

With Node.js and Git installed, run from the repository root:

```sh
node docs/architecture/verify.mjs --self-test
```

The checker reads the explicitly pinned source snapshot, not the current HEAD, so a later documentation commit does not invalidate inventory accounting. It checks source paths, snapshot pinning, inventory equality, graph endpoints, Mermaid embed consistency and documentation links. Seven base structural failure cases cover inventory, paths, embeds, links and snapshot identity. The current checker has 12 intended-failure cases in total, including source-map checks; each must fail at its intended check. No files are changed by the checker. Node is an optional documentation-checking tool; this adds no application dependency.

This checker does not parse the full Mermaid language, verify arrow semantics, access hosted services or prove all application behavior. Rendering was checked separately. A passing structural check does not replace source-conformance review.

## Bounded source-claim review

On 2026-10-04, jev-1.13.0 evaluated four critical source-behavior claims against selected implementation files or exact contiguous source fragments from this snapshot. Observed call usage: 7768 input tokens and 179 output tokens. All four typed results selected supported.

| Claim | Typed result | Confidence |
| --- | --- | ---: |
| The committed RFM calculation uses rank(method="first"), rather than the later uncommitted average-tie correction. | supported | 0.82 |
| The loader populates SQLite tables from CSV data. | supported | 1 |
| The supplied load_database.py does not execute sql/validation.sql as a pipeline gate. | supported | 0.97 |
| The analysis code writes chart artifacts and an analysis_summary.json file. | supported | 1 |

Source evidence: [load_database.py](../../load_database.py), [analysis.py](../../analysis.py), [sql/validation.sql](../../sql/validation.sql). Long-file fragments were reviewed with their original source path, commit and line ranges; this is bounded evidence, not a claim that every source file was supplied in one call.

These semantic checks supplement the structural checker. They cover only the four claims listed, not every diagram arrow or execution path, and do not replace the complete-diff or plan approval gates. Integration remains blocked while those required gates are unresolved.

## Complete diagram relationship source map

Observed 2026-10-04: all **17 arrows** have latest supported Jev judgments (confidence 0.37–1.00). Sixteen relationships use pinned source at 3609c9a80a117dbf0ed00d27b075a9aad09e9550; one dotted DRIFT relationship uses the separately labelled original working-tree observation below. Five bounded calls used jev-1.13.0 and 21081 input/754 output tokens. Each supplied at most six redacted excerpts of at most 10,000 characters. These judgments do not approve the whole diff, prove every execution path or waive required gates.

The SQL reference arrow now targets DB: those separately runnable queries inspect SQLite tables/views, rather than invoking Python CSV loading. The original checkout's average-rank RFM and validation enforcement remain uncommitted and excluded from the proposed runtime behavior. Original files and data were not changed.

### Source keys

- [S1](../../analysis.py)
- [S2](../../load_database.py)
- [S3](../../sql/validation.sql)
- [S4](../../sql/business_queries.sql)
- [S5](../../tests/test_loading.py)
- [S6](../../pyproject.toml)

O/D mean overview/detail; labels remain in the diagrams. S ranges are inclusive pinned Git source lines. W1 refers only to the frozen, non-pinned observation below.

| Arrow | Source ranges | Supported confidence |
| --- | --- | ---: |
| O I --> L | S1:373-392, S2:13-21 | 0.98 |
| O L --> R | S2:74-97, S2:181-206 | 1 |
| O R --> C | S2:100-165 | 1 |
| O C --> Q | S1:31-116 | 1 |
| O C --> M | S1:179-221, S1:236-272 | 1 |
| O R -.-> V | S3:1-38, S1:373-392 | 0.84 |
| O Q --> O | S1:294-325, S1:327-371 | 0.98 |
| O M --> O | S1:294-325, S1:327-371 | 1 |
| D DATA --> LOAD | S2:13-21, S2:74-97 | 0.99 |
| D LOAD --> ANALYZE | S1:373-377 | 1 |
| D SQL .-> DB | S4:1-39, S3:1-38 | 0.93 |
| D ANALYZE --> DATA | S1:327-371 | 0.84 |
| D LOAD --> DB | S2:181-206 | 1 |
| D DB --> ANALYZE | S1:31-48 | 1 |
| D ANALYZE --> REPORT | S1:294-325, S1:327-371 | 0.96 |
| D DRIFT .-> ANALYZE | W1:90-108, W1:235-243, W1:667-676 | 0.6 |
| D SUPPORT .-> LOAD | S5:1-52, S6:1-13 | 0.37 |

### Local working-tree observation

W1 is original analysis.py, observed 2026-10-04, SHA-256 3a57b91416591490aa2a721363f363b071a7fa50cd8983bdaa72bb4abeb6b0a2. It is outside the pinned snapshot and not a proposed application change. Numbered redacted excerpts were compared with the current original bytes before recording. This reproduces observation references without presenting uncommitted behavior as released.

```text
90: def _validation_check_status(check_name: str, violation_count: int) -> str | None:
91:     """Return warning, fatal, or None according to the documented check policy."""
92:     if check_name not in VALIDATION_KNOWN_CHECKS:
93:         return "fatal"
94:     if violation_count == 0:
95:         return None
96:     if check_name in VALIDATION_WARNING_CHECKS:
97:         return "warning"
98:     return "fatal"
99:
100:
101: def _enforce_validation_policy(validation_summary: list[tuple[str, int]]) -> None:
102:     fatal_checks = [
103:         (check_name, violation_count)
104:         for check_name, violation_count in validation_summary
105:         if _validation_check_status(check_name, violation_count) == "fatal"
106:     ]
107:     if fatal_checks:
108:         raise ValidationPolicyError(validation_summary, fatal_checks)
235:     }
236:
237:
238: def _score_quintile(values: pd.Series, *, higher_is_better: bool) -> pd.Series:
239:     ranks = values.rank(method="average", ascending=True)
240:     base_score = ((ranks / len(values)) * 5).clip(lower=1, upper=5).astype(int)
241:     return base_score if higher_is_better else 6 - base_score
242:
243:
667:     data_dir: str | Path = "data",
668:     db_path: str | Path = "olist.db",
669:     output_dir: str | Path = "outputs",
670: ) -> list[Path]:
671:     load_database(data_dir, db_path)
672:     validation_summary = get_validation_summary(db_path)
673:     _enforce_validation_policy(validation_summary)
674:     return generate_outputs(db_path, output_dir)
675:
676:
```

The updated checker passes twelve intended-failure cases, including missing arrow mapping, unknown source key, invalid pinned range, unavailable observed line and uncommitted evidence substituted for a pinned relationship. Frozen W1 ranges are valid only for the explicitly dotted LOCAL ONLY DRIFT relationship; they are never used to validate committed behavior. This checks evidence references, not source semantics.
