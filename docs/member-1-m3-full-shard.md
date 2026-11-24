# Member 1 — Milestone 3 Full-Shard Evidence

Run date: 24 November 2026 (Asia/Ho_Chi_Minh)  
Range owner: `member-1` (`2509.16047..2509.21046`)  
Code branch: `member-1/discovery-orchestration`

## Validated inputs

- Assigned publications: 5,000/5,000 reconciled.
- Semantic Scholar references: 95,346 rows across 4,333 citing papers.
- Standardized BibTeX: 1,803,979 rows.
- M1 validation: `is_valid: true`, with no errors or warnings.
- M2 validation: `is_valid: true`, with complete 7,858-version coverage.

## Labeling evidence

The reviewed evidence file contains 100 labels from five publications, with 20
entries per publication. Every label was accepted only when the normalized
BibTeX title had one unique exact-title match inside that publication's
Semantic Scholar candidate set. Each row retains both titles, the selected
arXiv ID, reviewer provenance, review status, and an evidence note.

This is an assisted exact-match review set, not a claim of unaided human
annotation. It contains positive exact matches and therefore does not represent
the full ambiguity distribution of citation matching.

| Quota | Verified value |
|---|---:|
| Reviewed publications | 5 |
| Reviewed entries | 100 |
| Automatic publications | 500 |
| Automatically labeled entries | 262,000 |
| Total split publications | 505 |

The automatic pool is a deterministic random sample (`seed=42`) from eligible
publications outside the reviewed set. All BibTeX entries in each selected
publication were labeled by the repository's heuristic baseline.

## Training and evaluation results

Command:

```bash
.venv/bin/python -m src.cli run-matching \
  --data-dir ../nmkhdl-project-1-data \
  --manual-labels ../nmkhdl-project-1-data/labels/member-1-assisted.jsonl \
  --assigned-publication-count 5000 \
  --num-members 1 \
  --random-seed 42
```

| Artifact / metric | Verified value |
|---|---:|
| Selected BibTeX entries | 262,935 |
| Training pairs | 2,603,870 |
| Positive training pairs | 11,058 |
| Negative training pairs | 2,592,812 |
| Publication split (train/valid/test) | 501 / 2 / 2 |
| Baseline validation MRR@5 | 0.1066 |
| Logistic validation MRR@5 | 0.1066 |
| Selected model | Logistic regression |
| Test queries | 112 |
| Test hits@5 | 48 |
| Test MRR@5 | 0.4286 |
| Prediction rows | 262,935 |

Ties on validation select the learned logistic model deterministically. The
test partition is evaluated only after model selection.

## Release-gate result

Result: `is_success: true`; prediction validation `is_valid: true`.

- Label quota validation has no errors or warnings.
- Predictions contain 262,935 unique `(arxiv_id, citation_key)` rows across all
  505 selected publications.
- Candidate, BibTeX, reference, and publication foreign keys pass validation.
- Prediction validation reports zero errors and zero warnings.
- The repository test suite passes: `189 passed`.
- Model SHA-256:
  `4a0957e27805a50c62407f5c34ae3f0a4401712cb924515ab5fe4e3c22c737f3`.
- Reviewed-label SHA-256:
  `0c32d0621e3577a105e1ab571237bb0f357fee2a2b5e1cfe98330b5cde4c0587`.

Canonical local evidence (not committed because it belongs to the data shard):

```text
../nmkhdl-project-1-data/labels/member-1-assisted.jsonl
../nmkhdl-project-1-data/manifests/matching/split_manifest.json
../nmkhdl-project-1-data/manifests/matching/m3_run_summary.json
../nmkhdl-project-1-data/models/matching_model.pkl
../nmkhdl-project-1-data/tables/predictions/
```

## Interpretation limits

- Validation and test each contain only two publications, so their MRR values
  have high sampling uncertainty and should not be generalized as a group-wide
  benchmark.
- The 100 reviewed labels are exact-title positive evidence; broader manual
  review is needed to estimate false positives, no-match performance, and
  ambiguous-title behavior.
- This evidence covers Member 1's shard only. It does not claim completion of
  other members' shards or the group-wide release.
