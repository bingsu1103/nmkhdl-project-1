# Member 1 — Milestone 2 Full-Shard Evidence

Run date: 24 November 2026 (Asia/Ho_Chi_Minh)  
Range owner: `member-1` (`2509.16047..2509.21046`)  
Code branch: `member-1/discovery-orchestration`

## Input reconciliation

- Assigned publications: 5,000.
- Expected source versions: 7,858.
- Parsing input statuses: 7,390 `ready`, 430 `empty`, 38
  `source_unavailable`.
- Missing source status records: 0.

## Parsing and standardization results

| Artifact / metric | Verified value |
|---|---:|
| Parse status records | 7,858 |
| Parse success | 6,824 |
| Partial | 386 |
| Multiple roots | 172 |
| No root | 8 |
| No TeX/Bib | 430 |
| Source unavailable | 38 |
| Distinct elements | 2,097,004 |
| Hierarchy edges | 3,009,610 |
| Raw BibTeX entries | 2,275,446 |
| Unified BibTeX entries | 1,803,979 |
| Entries merged away | 471,467 |
| Renamed citation keys | 35,944 |
| Unresolved citations | 79,947 |

## Release-gate result

Command:

```bash
.venv/bin/python -m src.cli validate-parsing \
  --data-dir ../nmkhdl-project-1-data
```

Result: `is_valid: true`.

- All 7,858 expected publication-version records have exactly one parse status.
- No missing, duplicate, or unexpected version status exists.
- `elements`, `hierarchy`, and `bibtex` match their explicit PyArrow schemas.
- Hierarchy validation reports no multiple-parent, orphan, cycle, or foreign-key
  error after deterministic repeated-content handling.
- BibTeX validation reports no release-blocking error. It records 59,352
  warnings, mainly missing author lists and non-standard entry types. These are
  retained as data-quality limitations rather than silently fabricated.

Canonical local evidence (not committed because it belongs to the data shard):

```text
../nmkhdl-project-1-data/manifests/parsing/m2_input_reconciliation.json
../nmkhdl-project-1-data/manifests/parsing/m2_table_summary.json
../nmkhdl-project-1-data/parsed/bibtex_summary.json
../nmkhdl-project-1-data/tables/m2_validation_report.json
```

This result covers Member 1's shard only. It does not claim that the other four
member shards or the group-wide Hugging Face release are complete.
