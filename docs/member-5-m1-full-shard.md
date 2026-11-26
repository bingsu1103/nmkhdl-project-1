# Member 5 — Milestone 1 Full-Shard Evidence

Evidence preparation date: 26 November 2026 (Asia/Ho_Chi_Minh)  
Range owner: `member-5` (`2510.24401..2510.27692`, `2511.00001..2511.01708`)  
Code branch: `member-5/book-poster`

## Validated inputs

- Assigned publications: 5,000/5,000 reconciled.
- Discovery: 5,000 successful publications and 7,806 version tasks.
- Source crawling: all 7,806 version tasks have terminal status records.
- Semantic Scholar references: 198,107 raw reference rows; 92,563 eligible arXiv references.
- M1 validation: `is_valid: true`, with no errors or warnings.

## Discovery evidence

Discovery summary reports run ID `7b4d2b77-81c5-4a4e-8546-176d9d1d00b1`.

| Metric | Verified value |
|---|---:|
| Assigned publications | 5,000 |
| Metadata records | 5,000 |
| Successful discovery records | 5,000 |
| Version tasks | 7,806 |
| Discovery success rate | 100% |

## Source-crawling evidence

| Terminal status | Count |
|---|---:|
| `success` | 7,217 |
| `no_tex_bib` | 543 |
| `http_error` | 41 |
| `invalid_archive` | 5 |
| **Total** | **7,806** |

| Metric | Verified value |
|---|---:|
| Expected version tasks | 7,806 |
| Terminal status records | 7,806 |
| Missing status records | 0 |
| Unexpected status records | 0 |
| Coverage rate | 100% |
| Downloaded archive bytes | 30,901,471,478 |
| Filtered TeX/Bib bytes | 1,645,848,429 |

Every version task has a terminal status. The 100% coverage rate represents task-status accounting, not successful archive downloads. There were 46 tasks with `http_error` or `invalid_archive` status.

## Semantic Scholar reference evidence

| Metric | Verified value |
|---|---:|
| Attempted publications | 5,000 |
| Successfully indexed (`ok`) | 4,994 |
| Not indexed (`not_found`) | 6 |
| Failed requests | 0 |
| Metadata success rate | 99.88% |
| Raw references | 198,107 |
| References missing arXiv ID | 105,544 |
| Invalid arXiv IDs | 0 |
| Eligible references before deduplication | 92,563 |
| Duplicate references removed | 0 |
| Final eligible references | 92,563 |
| Eligible references missing title | 0 |
| Eligible references missing authors | 0 |
| Eligible references missing submission date | 234 |
| Average raw references per paper | 39.67 |
| Average eligible arXiv references per paper | 18.53 |

The six `not_found` outcomes are distinct from failed requests. No Semantic Scholar request failures were recorded.

## Table-building and validation results

| Artifact / metric | Verified value |
|---|---:|
| Papers rows | 5,000 |
| Raw reference rows | 198,107 |
| Standardized reference rows | 92,563 |
| Reference Parquet shards | 19 |
| Duplicate references removed | 0 |
| Validation result | `is_valid: true` |
| Validation errors | 0 |
| Validation warnings | 0 |

Reconciliation confirms 5,000 assigned publications, 5,000 successful discovery records, zero failed discovery records, zero unaccounted publications, and zero unexpected publications.

Source completeness confirms 7,806 expected version tasks and 7,806 observed terminal status records, with no missing, non-terminal, duplicate, or unexpected records.

Reference validation reports 92,563 rows, 4,272 unique citing papers, and 68,929 unique referenced papers, with zero errors and zero warnings.

## Execution metadata

| Item | Verified value |
|---|---|
| Code branch | `member-5/book-poster` |
| Git HEAD at evidence preparation | `3abd030a4e8f8024be902c5d61c7d4e47c72eeef` |
| Latest commit date | `2026-11-26T20:49:05+07:00` |
| Python | `3.14.7` |
| Operating system | Windows 11 (`10.0.26200`) |
| pandas | `3.1.1` |
| pyarrow | `26.0.1` |
| requests | `2.34.2` |
| Pipeline execution start/end | Not recorded in the available summary manifests |

The Git working tree contained uncommitted modifications and untracked files when this evidence was prepared. The SHA above identifies the observed `HEAD` revision; it does not identify a commit containing the current uncommitted report files.

## Canonical local evidence

The following evidence belongs to the Member 5 data shard and should remain outside the Git repository:

```text
../nmkhdl-project-1-data-member-5/local/expanded_ids.csv
../nmkhdl-project-1-data-member-5/manifests/discovery/discovery_summary.json
../nmkhdl-project-1-data-member-5/manifests/discovery/discovery_status.jsonl
../nmkhdl-project-1-data-member-5/manifests/discovery/papers.jsonl
../nmkhdl-project-1-data-member-5/manifests/discovery/version_tasks.csv
../nmkhdl-project-1-data-member-5/manifests/source_status.jsonl
../nmkhdl-project-1-data-member-5/manifests/source_summary.json
../nmkhdl-project-1-data-member-5/manifests/s2_summary.json
../nmkhdl-project-1-data-member-5/tables/papers/
../nmkhdl-project-1-data-member-5/tables/references/
../nmkhdl-project-1-data-member-5/tables/m1_validation_report.json
```

## Interpretation limits

- This evidence covers Member 5's 5,000-publication shard only. It does not establish completion of other members' shards or the group-wide release.
- All 7,806 source tasks have terminal statuses, but 46 ended with `http_error` or `invalid_archive`.
- `no_tex_bib` is an explicit terminal outcome, not a successful source extraction.
- The six Semantic Scholar `not_found` outcomes are not request failures.
- The 92,563 eligible references are the filtered arXiv-reference dataset, not the total number of raw references.
- The available summary manifests do not establish exact pipeline start and end times.
