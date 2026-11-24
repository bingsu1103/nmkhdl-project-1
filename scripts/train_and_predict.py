#!/usr/bin/env python3
"""Milestone 3 Step 3: Publication Split, Model Comparison, MRR@5 Eval & Predictions Export.

Runs the complete matching ML pipeline:
1. Merges manual + automatic label manifests (`manual_labels.json`, `auto_labels.json`).
2. Performs leakage-free publication split (`create_publication_split`).
3. Builds pairwise training features (`build_pairwise_dataset`) using `src/features.py`.
4. Trains & evaluates HeuristicRanker, LogisticRegression, RandomForest, and HistGradientBoosting
   on Validation and Test sets using MRR@5 (`src/evaluate.py`).
5. Selects the best model on Validation MRR@5, generates Top-5 predictions across all split
   publications, writes `tables/predictions/part-*.parquet`, and validates via
   `validate_predictions_table()`.

Usage:
    python scripts/train_and_predict.py --data-dir D:/code/nmkhdl-project-1-data-member-4 --num-members 1
    python scripts/train_and_predict.py --data-dir D:/code/nmkhdl-project-1-data-member-4 --num-members 1 --eval-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from random import Random
from typing import Any, Sequence

import pyarrow as pa

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluate import compute_mrr_at_k, evaluate_predictions_summary
from src.features import FEATURE_NAMES
from src.label import create_publication_split, export_split_manifest, validate_labeling_quota
from src.model import (
    HeuristicRanker,
    LearnedRanker,
    build_pairwise_dataset,
    predict_top_k_candidates,
)
from src.normalize import normalize_arxiv_id
from src.storage import (
    BIBTEX_SCHEMA,
    PAPERS_SCHEMA,
    PREDICTIONS_SCHEMA,
    REFERENCES_SCHEMA,
    create_table_from_records,
    read_sharded_parquet,
    write_sharded_parquet,
)
from src.validate import validate_predictions_table


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _load_label_manifests(
    paths: list[Path],
    expected_method: str,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], str | None]]:
    pubs_by_id: dict[str, dict[str, Any]] = {}
    gt_by_pair: dict[tuple[str, str], str | None] = {}

    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Label manifest not found: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        for p in payload.get("publications") or []:
            aid = normalize_arxiv_id(p.get("arxiv_id"))
            if not aid:
                continue
            if aid in pubs_by_id:
                raise ValueError(
                    f"Duplicate publication {aid} found across {expected_method} manifests (e.g. {path})."
                )
            item = dict(p)
            item["arxiv_id"] = aid
            item["method"] = expected_method
            pubs_by_id[aid] = item
        for rec in payload.get("labels") or []:
            aid = normalize_arxiv_id(rec.get("arxiv_id"))
            ckey = str(rec.get("citation_key", ""))
            if not aid or not ckey:
                continue
            raw_gt = rec.get("groundtruth_arxiv_id")
            gt = (normalize_arxiv_id(raw_gt) or None) if raw_gt else None
            gt_by_pair[(aid, ckey)] = gt

    return [pubs_by_id[k] for k in sorted(pubs_by_id)], gt_by_pair


def _load_filtered_tables_across_dirs(
    data_dirs: Sequence[Path],
    target_ids: set[str],
    gt_by_pair: dict[tuple[str, str], str | None],
) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]], pa.Table, pa.Table, pa.Table]:
    """Stream-filter papers/bibtex/references across 1..N member data-dirs without holding all shards in RAM."""
    all_papers_ids: set[str] = set()
    papers_rows: list[dict[str, Any]] = []
    seen_papers: set[str] = set()

    all_entries: list[dict[str, Any]] = []
    bib_raw_rows: list[dict[str, Any]] = []
    seen_bib: set[tuple[str, str]] = set()

    all_refs: list[dict[str, Any]] = []
    seen_refs: set[tuple[str, str]] = set()

    for d_dir in data_dirs:
        p_tbl = read_sharded_parquet(d_dir / "tables" / "papers", PAPERS_SCHEMA)
        p_aids = p_tbl["arxiv_id"].to_pylist()
        p_keep: list[bool] = []
        for raw_aid in p_aids:
            aid = normalize_arxiv_id(raw_aid)
            if aid:
                all_papers_ids.add(aid)
            p_keep.append(bool(aid and aid in target_ids and aid not in seen_papers))
        for r in p_tbl.filter(pa.array(p_keep, type=pa.bool_())).to_pylist():
            aid = normalize_arxiv_id(r.get("arxiv_id"))
            if aid and aid not in seen_papers:
                seen_papers.add(aid)
                item = dict(r)
                item["arxiv_id"] = aid
                papers_rows.append(item)
        del p_tbl

        b_tbl = read_sharded_parquet(d_dir / "tables" / "bibtex", BIBTEX_SCHEMA)
        b_mask = pa.array([normalize_arxiv_id(x) in target_ids for x in b_tbl["arxiv_id"].to_pylist()], type=pa.bool_())
        for r in b_tbl.filter(b_mask).to_pylist():
            aid = normalize_arxiv_id(r.get("arxiv_id"))
            ckey = str(r.get("citation_key", ""))
            if not aid or not ckey or (aid, ckey) in seen_bib:
                continue
            seen_bib.add((aid, ckey))
            raw_item = dict(r)
            raw_item["arxiv_id"] = aid
            bib_raw_rows.append(raw_item)
            entry_item = dict(raw_item)
            entry_item["groundtruth_arxiv_id"] = gt_by_pair.get((aid, ckey))
            all_entries.append(entry_item)
        del b_tbl

        r_tbl = read_sharded_parquet(d_dir / "tables" / "references", REFERENCES_SCHEMA)
        r_mask = pa.array([normalize_arxiv_id(x) in target_ids for x in r_tbl["arxiv_id"].to_pylist()], type=pa.bool_())
        for r in r_tbl.filter(r_mask).to_pylist():
            aid = normalize_arxiv_id(r.get("arxiv_id"))
            rid = normalize_arxiv_id(r.get("ref_arxiv_id"))
            if not aid or not rid or (aid, rid) in seen_refs:
                continue
            seen_refs.add((aid, rid))
            ref_item = dict(r)
            ref_item["arxiv_id"] = aid
            ref_item["ref_arxiv_id"] = rid
            all_refs.append(ref_item)
        del r_tbl

    missing_in_bib = sorted(target_ids - {e["arxiv_id"] for e in all_entries})
    if missing_in_bib:
        raise ValueError(
            f"{len(missing_in_bib)} labeled paper(s) not found in tables/bibtex across {len(data_dirs)} data-dir(s): "
            f"{missing_in_bib[:5]}"
        )

    papers_tbl = create_table_from_records(papers_rows, PAPERS_SCHEMA)
    bib_tbl = create_table_from_records(bib_raw_rows, BIBTEX_SCHEMA)
    ref_tbl = create_table_from_records(all_refs, REFERENCES_SCHEMA)
    return len(all_papers_ids), all_entries, all_refs, papers_tbl, bib_tbl, ref_tbl


def _sample_training_entries(
    train_entries: list[dict[str, Any]],
    max_per_pub: int,
    seed: int,
) -> list[dict[str, Any]]:
    if max_per_pub <= 0:
        return train_entries

    by_pub: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in train_entries:
        by_pub[e["arxiv_id"]].append(e)

    rng = Random(seed)
    sampled: list[dict[str, Any]] = []
    for aid in sorted(by_pub):
        entries = by_pub[aid]
        if len(entries) <= max_per_pub:
            sampled.extend(entries)
            continue
        positives = [e for e in entries if e.get("groundtruth_arxiv_id")]
        negatives = [e for e in entries if not e.get("groundtruth_arxiv_id")]
        sampled.extend(positives)
        rem = max(0, max_per_pub - len(positives))
        if rem > 0 and negatives:
            if len(negatives) <= rem:
                sampled.extend(negatives)
            else:
                sampled.extend(rng.sample(negatives, rem))
    return sampled


def _compute_eval_breakdown(
    predictions: list[dict[str, Any]],
    method_by_pub: dict[str, str],
    partition: str,
) -> dict[str, Any]:
    part_rows = [r for r in predictions if r["partition"] == partition]
    all_metrics = compute_mrr_at_k(part_rows, k=5, partition_filter=None)
    matched_rows = [r for r in part_rows if r.get("groundtruth_arxiv_id")]
    matched_metrics = compute_mrr_at_k(matched_rows, k=5, partition_filter=None)

    manual_rows = [r for r in part_rows if method_by_pub.get(r["arxiv_id"]) == "manual"]
    manual_matched = [r for r in manual_rows if r.get("groundtruth_arxiv_id")]
    auto_rows = [r for r in part_rows if method_by_pub.get(r["arxiv_id"]) == "automatic"]
    auto_matched = [r for r in auto_rows if r.get("groundtruth_arxiv_id")]

    return {
        "all_entries": all_metrics,
        "matched_entries_only": matched_metrics,
        "manual_all": compute_mrr_at_k(manual_rows, k=5, partition_filter=None),
        "manual_matched_only": compute_mrr_at_k(manual_matched, k=5, partition_filter=None),
        "auto_all": compute_mrr_at_k(auto_rows, k=5, partition_filter=None),
        "auto_matched_only": compute_mrr_at_k(auto_matched, k=5, partition_filter=None),
    }


def _extract_model_interpretability(model: Any) -> dict[str, Any]:
    if isinstance(model, HeuristicRanker):
        return {"weights": model.weights}
    if isinstance(model, LearnedRanker) and model.is_fitted:
        est = model.model
        if hasattr(est, "coef_"):
            coefs = est.coef_[0]
            return {
                "intercept": round(float(est.intercept_[0]), 4),
                "coefficients": {
                    name: round(float(val), 4)
                    for name, val in sorted(zip(FEATURE_NAMES, coefs), key=lambda x: abs(x[1]), reverse=True)
                },
            }
        if hasattr(est, "feature_importances_"):
            imps = est.feature_importances_
            return {
                "feature_importances": {
                    name: round(float(val), 4)
                    for name, val in sorted(zip(FEATURE_NAMES, imps), key=lambda x: x[1], reverse=True)
                },
            }
    return {}


def run_training_and_prediction(
    *,
    data_dir: Path | Sequence[Path] | None = None,
    data_dirs: Sequence[Path] | None = None,
    manual_paths: list[Path],
    auto_paths: list[Path],
    num_members: int,
    seed: int,
    negative_ratio: int,
    max_train_entries_per_pub: int,
    eval_only: bool,
    output_tables_dir: Path,
    report_output: Path | None,
    split_output: Path | None,
    allow_partial_quota: bool = False,
    preferred_model: str = "auto",
) -> tuple[bool, dict[str, Any]]:
    t0 = time.perf_counter()

    if data_dirs is not None:
        resolved_dirs = [Path(d) for d in data_dirs]
    elif isinstance(data_dir, (list, tuple)):
        resolved_dirs = [Path(d) for d in data_dir]
    elif data_dir is not None:
        resolved_dirs = [Path(data_dir)]
    else:
        raise ValueError("At least one data_dir must be provided.")

    manual_pubs, manual_gt = _load_label_manifests(manual_paths, "manual")
    auto_pubs, auto_gt = _load_label_manifests(auto_paths, "automatic")

    overlap = {p["arxiv_id"] for p in manual_pubs} & {p["arxiv_id"] for p in auto_pubs}
    if overlap:
        raise ValueError(f"Manual and automatic pools overlap on {len(overlap)} paper(s): {sorted(overlap)[:5]}")

    split_info = create_publication_split(
        manual_publications=manual_pubs,
        auto_publications=auto_pubs,
        num_members=num_members,
        random_seed=seed,
    )
    split_map = {s.arxiv_id: s.partition for s in split_info}
    method_by_pub = {s.arxiv_id: s.method for s in split_info}
    target_ids = set(split_map)

    gt_by_pair = {**auto_gt, **manual_gt}

    total_papers_count, all_entries, all_refs, papers_tbl, bib_tbl, ref_tbl = _load_filtered_tables_across_dirs(
        resolved_dirs, target_ids, gt_by_pair
    )

    quota_report = validate_labeling_quota(
        labeled_publications=[*manual_pubs, *auto_pubs],
        total_assigned_publications_count=max(total_papers_count, len(manual_pubs) + len(auto_pubs)),
        num_members=num_members,
    )
    if not quota_report["is_valid"] and not allow_partial_quota:
        raise ValueError(
            f"Labeling quota validation failed for num_members={num_members}: {quota_report['errors']}"
        )

    train_entries = [e for e in all_entries if split_map[e["arxiv_id"]] == "train"]
    valid_entries = [e for e in all_entries if split_map[e["arxiv_id"]] == "valid"]
    test_entries = [e for e in all_entries if split_map[e["arxiv_id"]] == "test"]
    eval_entries = valid_entries + test_entries

    sampled_train_entries = _sample_training_entries(train_entries, max_train_entries_per_pub, seed)
    X_train, y_train, _ = build_pairwise_dataset(
        sampled_train_entries,
        all_refs,
        negative_sample_ratio=negative_ratio,
        seed=seed,
    )
    if len(X_train) == 0 or 1 not in y_train or 0 not in y_train:
        raise RuntimeError(f"Training dataset degenerate: total={len(X_train)}, pos={sum(y_train)}")

    candidates_models: list[tuple[str, Any]] = [
        ("heuristic_ranker", HeuristicRanker()),
        ("logistic_c1.0", LearnedRanker(model_type="logistic", C=1.0, random_state=seed)),
        ("logistic_c0.2", LearnedRanker(model_type="logistic", C=0.2, random_state=seed)),
        ("random_forest", LearnedRanker(model_type="random_forest", n_estimators=150, max_depth=8, random_state=seed)),
        ("hist_gb", LearnedRanker(model_type="hist_gb", max_iter=150, max_depth=6, learning_rate=0.08, random_state=seed)),
    ]

    model_results: list[dict[str, Any]] = []
    trained_models: dict[str, Any] = {}

    for name, model in candidates_models:
        fit_t0 = time.perf_counter()
        if isinstance(model, LearnedRanker):
            model.fit(X_train, y_train)
        fit_sec = round(time.perf_counter() - fit_t0, 3)

        eval_preds = predict_top_k_candidates(eval_entries, all_refs, model=model, split_manifest=split_map, k=5)
        valid_bd = _compute_eval_breakdown(eval_preds, method_by_pub, "valid")
        test_bd = _compute_eval_breakdown(eval_preds, method_by_pub, "test")

        trained_models[name] = model
        model_results.append({
            "model_name": name,
            "fit_seconds": fit_sec,
            "valid": valid_bd,
            "test": test_bd,
            "interpretability": _extract_model_interpretability(model),
        })

    if preferred_model != "auto":
        if preferred_model not in trained_models:
            raise ValueError(f"Unknown --model '{preferred_model}'. Choose from: auto, {sorted(trained_models)}")
        best_name = preferred_model
    else:
        # Choose best model on Valid MRR@5 (preferring LearnedRanker over rule baseline on exact ties)
        best_result = max(
            model_results,
            key=lambda res: (
                res["valid"]["all_entries"]["mrr"],
                res["valid"]["all_entries"]["hit_rate"],
                res["valid"]["matched_entries_only"]["mrr"],
                1 if isinstance(trained_models[res["model_name"]], LearnedRanker) else 0,
            ),
        )
        best_name = best_result["model_name"]
    best_model = trained_models[best_name]

    split_summary = {
        part: {
            "total_pubs": sum(1 for s in split_info if s.partition == part),
            "manual_pubs": sum(1 for s in split_info if s.partition == part and s.method == "manual"),
            "auto_pubs": sum(1 for s in split_info if s.partition == part and s.method == "automatic"),
        }
        for part in ("train", "valid", "test")
    }

    summary: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_dirs": [str(d) for d in resolved_dirs],
        "num_members": num_members,
        "seed": seed,
        "negative_sample_ratio": negative_ratio,
        "max_train_entries_per_pub": max_train_entries_per_pub,
        "total_assigned_papers": total_papers_count,
        "quota_validation": quota_report,
        "split_summary": split_summary,
        "train_dataset": {
            "total_train_entries": len(train_entries),
            "sampled_train_entries": len(sampled_train_entries),
            "pairwise_rows": len(X_train),
            "positive_pairs": sum(y_train),
            "negative_pairs": len(y_train) - sum(y_train),
        },
        "eval_entries": {
            "valid_entries": len(valid_entries),
            "test_entries": len(test_entries),
        },
        "best_model": best_name,
        "model_comparison": model_results,
        "eval_only": eval_only,
    }

    if split_output is not None and not eval_only:
        export_split_manifest(split_info, split_output)
        summary["split_manifest_path"] = str(split_output)

    is_valid = True
    if not eval_only:
        all_preds = predict_top_k_candidates(all_entries, all_refs, model=best_model, split_manifest=split_map, k=5)
        pred_table = create_table_from_records(all_preds, PREDICTIONS_SCHEMA)
        written_shards = write_sharded_parquet(pred_table, output_tables_dir, "predictions")

        val_report = validate_predictions_table(
            pred_table,
            bibtex_table=bib_tbl,
            references_table=ref_tbl,
            papers_table=papers_tbl,
        )
        mrr_summary = evaluate_predictions_summary(pred_table, k=5)
        is_valid = val_report.is_valid
        summary["predictions_output"] = {
            "tables_dir": str(output_tables_dir / "predictions"),
            "shards_count": len(written_shards),
            "total_rows": pred_table.num_rows,
            "is_valid": val_report.is_valid,
            "errors": val_report.errors,
            "warnings": val_report.warnings,
            "stats": val_report.stats,
            "best_model_full_summary": mrr_summary,
        }

    summary["elapsed_seconds"] = round(time.perf_counter() - t0, 2)
    if report_output is not None:
        _atomic_write_json(report_output, summary)
        summary["report_path"] = str(report_output)

    return is_valid, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="M3 Step 3: Train, evaluate MRR@5, and export predictions.")
    parser.add_argument(
        "--data-dir",
        action="append",
        type=Path,
        required=True,
        help="Member data directory (repeatable for multi-member merge).",
    )
    parser.add_argument("--manual-labels", action="append", type=Path, default=[])
    parser.add_argument("--auto-labels", action="append", type=Path, default=[])
    parser.add_argument("--num-members", type=int, default=1, help="1 for single-member shard, 5 for full group.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--negative-ratio", type=int, default=10)
    parser.add_argument(
        "--max-train-entries-per-pub",
        type=int,
        default=300,
        help="Cap negative entries per train pub during fit() (0 = no cap). Never caps Valid/Test or predictions.",
    )
    parser.add_argument(
        "--model",
        default="auto",
        choices=["auto", "heuristic_ranker", "logistic_c1.0", "logistic_c0.2", "random_forest", "hist_gb"],
        help="Model to export predictions with (default: auto = best on Valid MRR@5).",
    )
    parser.add_argument("--allow-partial-quota", action="store_true", help="Allow running even if quota validation fails.")
    parser.add_argument("--eval-only", action="store_true", help="Train & evaluate models only; skip writing Parquet.")
    parser.add_argument("--output-tables-dir", type=Path, help="Default: <first data-dir>/tables")
    parser.add_argument("--report-output", type=Path, help="Default: <first data-dir>/matching/m3_eval_report.json")
    parser.add_argument("--split-output", type=Path, help="Default: <first data-dir>/matching/split_manifest.json")
    args = parser.parse_args()

    if args.num_members < 1:
        print(f"[ERROR] --num-members must be >= 1, got {args.num_members}", file=sys.stderr)
        return 2
    if args.negative_ratio < 1:
        print(f"[ERROR] --negative-ratio must be >= 1, got {args.negative_ratio}", file=sys.stderr)
        return 2
    if args.max_train_entries_per_pub < 0:
        print(
            f"[ERROR] --max-train-entries-per-pub must be >= 0, got {args.max_train_entries_per_pub}",
            file=sys.stderr,
        )
        return 2

    data_dirs = [p.expanduser().resolve() for p in args.data_dir]
    primary_dir = data_dirs[0]
    manual_paths = (
        [p.expanduser().resolve() for p in args.manual_labels]
        or [d / "matching" / "manual_labels.json" for d in data_dirs]
    )
    auto_paths = (
        [p.expanduser().resolve() for p in args.auto_labels]
        or [d / "matching" / "auto_labels.json" for d in data_dirs]
    )
    output_tables_dir = (args.output_tables_dir or (primary_dir / "tables")).expanduser().resolve()
    report_output = (args.report_output or (primary_dir / "matching" / "m3_eval_report.json")).expanduser().resolve()
    split_output = (args.split_output or (primary_dir / "matching" / "split_manifest.json")).expanduser().resolve()

    ok, summary = run_training_and_prediction(
        data_dirs=data_dirs,
        manual_paths=manual_paths,
        auto_paths=auto_paths,
        num_members=args.num_members,
        seed=args.seed,
        negative_ratio=args.negative_ratio,
        max_train_entries_per_pub=args.max_train_entries_per_pub,
        eval_only=args.eval_only,
        output_tables_dir=output_tables_dir,
        report_output=report_output if (not args.eval_only or args.report_output is not None) else None,
        split_output=split_output,
        allow_partial_quota=args.allow_partial_quota,
        preferred_model=args.model,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
