#!/usr/bin/env python3
"""Milestone 3 Step 3: Publication Split, Model Comparison, MRR@5 Eval & Predictions Export.

Runs the complete matching ML pipeline (single-member or multi-member merge):
1. Loads & merges manual + automatic labels (supports both JSON manifests and Member 1 JSONL).
2. Performs leakage-free publication split (`stratified` per member for multi-member runs, or `global`).
3. Builds pointwise & pairwise preference training datasets (`src/features.py`, `src/model.py`)
   with hard-negative mining, manual sample weighting, and unlabeled-entry exclusion.
4. Trains & compares 6 models (HeuristicRanker, Pairwise Logistic, Logistic C=1.0/0.2,
   RandomForest, HistGradientBoosting) using MRR@5 on Validation and Test sets.
5. Exports sharded `tables/predictions`, persists `matching_model.pkl` (+ SHA-256), validates via
   `validate_predictions_table()`, and optionally splits & validates per-member predictions for HF upload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pickle
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
from src.label import (
    create_publication_split,
    create_stratified_publication_split,
    export_split_manifest,
    heuristic_match_publication,
    validate_labeling_quota,
)
from src.model import (
    HeuristicRanker,
    LearnedRanker,
    build_pairwise_dataset,
    build_preference_dataset,
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


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_bytes(path, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _discover_manual_label_path(data_dir: Path) -> Path:
    """Tìm file nhãn thủ công trong thư mục member (hỗ trợ cả JSON của label_tool và JSONL của Member 1)."""
    for rel in (Path("matching") / "manual_labels.json", Path("matching") / "manual_labels.jsonl"):
        cand = data_dir / rel
        if cand.is_file():
            return cand
    labels_dir = data_dir / "labels"
    if labels_dir.is_dir():
        cands = sorted(
            p
            for p in labels_dir.iterdir()
            if p.is_file()
            and p.suffix.lower() in {".jsonl", ".json"}
            and "review" not in p.stem.lower()
            and "pending" not in p.stem.lower()
        )
        if len(cands) == 1:
            return cands[0]
    return data_dir / "matching" / "manual_labels.json"


def _discover_auto_label_path(data_dir: Path) -> Path | None:
    """Tìm file nhãn tự động nếu đã có; trả về None nếu chưa sinh."""
    for rel in (Path("matching") / "auto_labels.json", Path("matching") / "auto_labels.jsonl"):
        cand = data_dir / rel
        if cand.is_file():
            return cand
    return None


def _parse_label_file(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Đọc cả định dạng JSON manifest (label_tool/auto_label) lẫn JSONL phẳng (Member 1)."""
    raw_text = path.read_text(encoding="utf-8").strip()
    if not raw_text:
        return [], []

    is_jsonl = path.suffix.lower() == ".jsonl"
    parsed: Any = None
    if not is_jsonl:
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            is_jsonl = True

    if not is_jsonl and isinstance(parsed, dict):
        return list(parsed.get("publications") or []), list(parsed.get("labels") or [])

    if not is_jsonl and isinstance(parsed, list):
        records = parsed
    else:
        records = []
        for line_no, line in enumerate(raw_text.splitlines(), 1):
            line_s = line.strip()
            if not line_s:
                continue
            try:
                rec = json.loads(line_s)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
            if not isinstance(rec, dict):
                raise ValueError(f"JSONL line {line_no} in {path} is not a JSON object.")
            records.append(rec)

    # Tổng hợp records dạng phẳng (JSONL) thành (publications, labels)
    by_pub: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_pairs: set[tuple[str, str]] = set()
    clean_labels: list[dict[str, Any]] = []
    for idx, rec in enumerate(records, 1):
        status = str(rec.get("review_status") or "").strip().lower()
        if status == "pending":
            raise ValueError(f"Unreviewed pending label at {path}:{idx} — review labels before training.")
        aid = normalize_arxiv_id(rec.get("arxiv_id"))
        ckey = str(rec.get("citation_key") or "").strip()
        if not aid or not ckey:
            continue
        if (aid, ckey) in seen_pairs:
            raise ValueError(f"Duplicate label {(aid, ckey)} inside {path}")
        seen_pairs.add((aid, ckey))
        clean_labels.append(rec)
        by_pub[aid].append(rec)

    pubs: list[dict[str, Any]] = []
    for aid in sorted(by_pub):
        rows = by_pub[aid]
        reviewers = sorted({
            str(r.get("labeled_by") or r.get("reviewed_by") or path.stem).strip()
            for r in rows
            if str(r.get("labeled_by") or r.get("reviewed_by") or path.stem).strip()
        })
        pubs.append({
            "arxiv_id": aid,
            "labeled_by": "+".join(reviewers) if reviewers else path.stem,
            "entries_count": len(rows),
            "labeled_count": len(rows),
            "matched_count": sum(1 for r in rows if normalize_arxiv_id(r.get("groundtruth_arxiv_id"))),
        })
    return pubs, clean_labels


def _load_label_manifests(
    paths: list[Path],
    expected_method: str,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], str | None]]:
    pubs_by_id: dict[str, dict[str, Any]] = {}
    gt_by_pair: dict[tuple[str, str], str | None] = {}

    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Label manifest not found: {path}")
        pub_items, label_items = _parse_label_file(path)
        for p in pub_items:
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
        for rec in label_items:
            aid = normalize_arxiv_id(rec.get("arxiv_id"))
            ckey = str(rec.get("citation_key", ""))
            if not aid or not ckey:
                continue
            raw_gt = rec.get("groundtruth_arxiv_id")
            gt = (normalize_arxiv_id(raw_gt) or None) if raw_gt else None
            gt_by_pair[(aid, ckey)] = gt

    return [pubs_by_id[k] for k in sorted(pubs_by_id)], gt_by_pair


def _scan_shard_paper_owners(
    data_dirs: Sequence[Path],
) -> tuple[dict[str, int], dict[int, int]]:
    """Ánh xạ mỗi arxiv_id -> chỉ số shard data-dir sở hữu nó để chia stratified và tách predictions."""
    owner_by_pub: dict[str, int] = {}
    paper_counts_by_shard: dict[int, int] = {}
    for shard_idx, d_dir in enumerate(data_dirs):
        p_tbl = read_sharded_parquet(d_dir / "tables" / "papers", PAPERS_SCHEMA)
        shard_ids: set[str] = set()
        for raw_aid in p_tbl["arxiv_id"].to_pylist():
            aid = normalize_arxiv_id(raw_aid)
            if not aid:
                continue
            if aid in owner_by_pub and owner_by_pub[aid] != shard_idx:
                raise ValueError(
                    f"Duplicate paper {aid} found in multiple data-dirs: "
                    f"{data_dirs[owner_by_pub[aid]]} and {d_dir}"
                )
            owner_by_pub[aid] = shard_idx
            shard_ids.add(aid)
        paper_counts_by_shard[shard_idx] = len(shard_ids)
        del p_tbl
    return owner_by_pub, paper_counts_by_shard


def _generate_missing_auto_labels_for_shard(
    data_dir: Path,
    shard_idx: int,
    manual_ids: set[str],
    total_shard_papers: int,
    *,
    fraction: float = 0.12,
    threshold: float = 0.75,
    seed: int = 42,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], str | None]]:
    """Sinh automatic labels in-memory cho shard chưa có file auto_labels.json (vd: Member 1)."""
    b_tbl = read_sharded_parquet(data_dir / "tables" / "bibtex", BIBTEX_SCHEMA)
    r_tbl = read_sharded_parquet(data_dir / "tables" / "references", REFERENCES_SCHEMA)

    bib_by_pub: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_bib: set[tuple[str, str]] = set()
    for row in b_tbl.to_pylist():
        aid = normalize_arxiv_id(row.get("arxiv_id"))
        ckey = str(row.get("citation_key", ""))
        if aid and ckey and (aid, ckey) not in seen_bib:
            seen_bib.add((aid, ckey))
            bib_by_pub[aid].append(row)
    del b_tbl

    refs_by_pub: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_ref: set[tuple[str, str]] = set()
    for row in r_tbl.to_pylist():
        aid = normalize_arxiv_id(row.get("arxiv_id"))
        rid = normalize_arxiv_id(row.get("ref_arxiv_id"))
        if aid and rid and (aid, rid) not in seen_ref:
            seen_ref.add((aid, rid))
            refs_by_pub[aid].append(row)
    del r_tbl

    eligible = sorted(aid for aid in (set(bib_by_pub) & set(refs_by_pub)) if aid not in manual_ids)
    remaining_outside_manual = max(0, total_shard_papers - len(manual_ids))
    target_count = min(len(eligible), max(2, math.ceil(fraction * remaining_outside_manual)))
    if target_count < 2:
        raise ValueError(
            f"Shard {data_dir} only has {len(eligible)} eligible publications for auto-labeling; need >= 2."
        )

    selected_ids = sorted(Random(seed + shard_idx).sample(eligible, target_count))
    auto_pubs: list[dict[str, Any]] = []
    auto_gt: dict[tuple[str, str], str | None] = {}
    for aid in selected_ids:
        matches = heuristic_match_publication(
            bib_by_pub[aid], refs_by_pub[aid], min_similarity_threshold=threshold
        )
        matched_count = 0
        for ckey, gt in matches.items():
            norm_gt = normalize_arxiv_id(gt) or None if gt else None
            auto_gt[(aid, ckey)] = norm_gt
            if norm_gt:
                matched_count += 1
        auto_pubs.append({
            "arxiv_id": aid,
            "method": "automatic",
            "labeled_by": f"auto_heuristic_{threshold:.2f}",
            "entries_count": len(matches),
            "labeled_count": len(matches),
            "matched_count": matched_count,
        })
    return auto_pubs, auto_gt


def _load_filtered_tables_across_dirs(
    data_dirs: Sequence[Path],
    target_ids: set[str],
    gt_by_pair: dict[tuple[str, str], str | None],
    method_by_pub: dict[str, str],
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
            pair = (aid, ckey)
            entry_item["is_labeled"] = pair in gt_by_pair
            entry_item["groundtruth_arxiv_id"] = gt_by_pair.get(pair)
            entry_item["label_method"] = method_by_pub.get(aid, "unknown")
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
    labeled_pairs: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    part_rows = [r for r in predictions if r["partition"] == partition]
    if labeled_pairs is not None:
        eval_rows = [r for r in part_rows if (r["arxiv_id"], r["citation_key"]) in labeled_pairs]
        unlabeled_excluded = len(part_rows) - len(eval_rows)
    else:
        eval_rows = part_rows
        unlabeled_excluded = 0

    all_metrics = compute_mrr_at_k(eval_rows, k=5, partition_filter=None)
    matched_rows = [r for r in eval_rows if r.get("groundtruth_arxiv_id")]
    matched_metrics = compute_mrr_at_k(matched_rows, k=5, partition_filter=None)

    manual_rows = [r for r in eval_rows if method_by_pub.get(r["arxiv_id"]) == "manual"]
    manual_matched = [r for r in manual_rows if r.get("groundtruth_arxiv_id")]
    auto_rows = [r for r in eval_rows if method_by_pub.get(r["arxiv_id"]) == "automatic"]
    auto_matched = [r for r in auto_rows if r.get("groundtruth_arxiv_id")]

    return {
        "unlabeled_entries_excluded": unlabeled_excluded,
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
        est = model.get_final_estimator()
        is_standardized = hasattr(model.model, "named_steps") and "scaler" in model.model.named_steps
        if hasattr(est, "coef_"):
            coefs = est.coef_[0]
            intercept = float(est.intercept_[0]) if hasattr(est, "intercept_") and len(est.intercept_) else 0.0
            return {
                "is_standardized": is_standardized,
                "intercept": round(intercept, 4),
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
    hard_negative_fraction: float = 0.5,
    manual_weight: float = 5.0,
    split_strategy: str = "auto",
    generate_missing_auto: bool = False,
    model_output: Path | None = None,
    export_per_member_dir: Path | None = None,
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

    owner_by_pub, paper_counts_by_shard = _scan_shard_paper_owners(resolved_dirs)

    manual_pubs, manual_gt = _load_label_manifests(manual_paths, "manual")
    auto_pubs, auto_gt = _load_label_manifests(auto_paths, "automatic") if auto_paths else ([], {})

    # Nếu bật --generate-missing-auto: tự sinh auto labels in-memory cho bất kỳ shard nào chưa có auto_labels.json
    generated_auto_shards: list[str] = []
    if generate_missing_auto:
        auto_shards_present = {
            owner_by_pub[p["arxiv_id"]]
            for p in auto_pubs
            if p["arxiv_id"] in owner_by_pub
        }
        manual_ids_all = {p["arxiv_id"] for p in manual_pubs}
        for shard_idx, d_dir in enumerate(resolved_dirs):
            if shard_idx in auto_shards_present:
                continue
            shard_manual_ids = {aid for aid in manual_ids_all if owner_by_pub.get(aid) == shard_idx}
            gen_pubs, gen_gt = _generate_missing_auto_labels_for_shard(
                d_dir,
                shard_idx,
                shard_manual_ids,
                paper_counts_by_shard[shard_idx],
                seed=seed,
            )
            auto_pubs.extend(gen_pubs)
            auto_gt.update(gen_gt)
            generated_auto_shards.append(d_dir.name)
        auto_pubs.sort(key=lambda p: p["arxiv_id"])

    overlap = {p["arxiv_id"] for p in manual_pubs} & {p["arxiv_id"] for p in auto_pubs}
    if overlap:
        raise ValueError(f"Manual and automatic pools overlap on {len(overlap)} paper(s): {sorted(overlap)[:5]}")

    unknown_labeled = sorted(
        {p["arxiv_id"] for p in [*manual_pubs, *auto_pubs]} - set(owner_by_pub)
    )
    if unknown_labeled:
        raise ValueError(
            f"{len(unknown_labeled)} labeled paper(s) not found in tables/papers across {len(resolved_dirs)} data-dir(s): "
            f"{unknown_labeled[:5]}"
        )

    use_stratified = (
        split_strategy == "stratified"
        or (split_strategy == "auto" and len(resolved_dirs) == num_members and num_members > 1)
    )
    if use_stratified:
        manual_by_shard: dict[str, list[dict[str, Any]]] = {f"shard_{i:02d}": [] for i in range(len(resolved_dirs))}
        auto_by_shard: dict[str, list[dict[str, Any]]] = {f"shard_{i:02d}": [] for i in range(len(resolved_dirs))}
        for p in manual_pubs:
            manual_by_shard[f"shard_{owner_by_pub[p['arxiv_id']]:02d}"].append(p)
        for p in auto_pubs:
            auto_by_shard[f"shard_{owner_by_pub[p['arxiv_id']]:02d}"].append(p)
        split_info = create_stratified_publication_split(
            manual_by_member=manual_by_shard,
            auto_by_member=auto_by_shard,
            random_seed=seed,
        )
        split_strategy_used = "stratified_per_member"
    else:
        split_info = create_publication_split(
            manual_publications=manual_pubs,
            auto_publications=auto_pubs,
            num_members=num_members,
            random_seed=seed,
        )
        split_strategy_used = "global"

    split_map = {s.arxiv_id: s.partition for s in split_info}
    method_by_pub = {s.arxiv_id: s.method for s in split_info}
    target_ids = set(split_map)

    gt_by_pair = {**auto_gt, **manual_gt}
    labeled_pairs = set(gt_by_pair)

    total_papers_count, all_entries, all_refs, papers_tbl, bib_tbl, ref_tbl = _load_filtered_tables_across_dirs(
        resolved_dirs, target_ids, gt_by_pair, method_by_pub
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
    labeled_train_entries = [e for e in train_entries if e.get("is_labeled", True)]
    unlabeled_train_skipped = len(train_entries) - len(labeled_train_entries)

    valid_entries = [e for e in all_entries if split_map[e["arxiv_id"]] == "valid"]
    test_entries = [e for e in all_entries if split_map[e["arxiv_id"]] == "test"]
    eval_entries = valid_entries + test_entries

    sampled_train_entries = _sample_training_entries(labeled_train_entries, max_train_entries_per_pub, seed)
    X_train, y_train, meta_train = build_pairwise_dataset(
        sampled_train_entries,
        all_refs,
        negative_sample_ratio=negative_ratio,
        seed=seed,
        hard_negative_fraction=hard_negative_fraction,
        skip_unlabeled=True,
    )
    if len(X_train) == 0 or 1 not in y_train or 0 not in y_train:
        raise RuntimeError(f"Training dataset degenerate: total={len(X_train)}, pos={sum(y_train)}")

    sample_weight_train = [
        float(manual_weight) if m.get("label_method") == "manual" else 1.0
        for m in meta_train
    ]

    X_pref, y_pref, w_pref, _ = build_preference_dataset(
        sampled_train_entries,
        all_refs,
        negative_sample_ratio=negative_ratio,
        hard_negative_fraction=hard_negative_fraction,
        seed=seed,
        manual_sample_weight=manual_weight,
        skip_unlabeled=True,
    )

    candidates_models: list[tuple[str, Any]] = [
        ("heuristic_ranker", HeuristicRanker()),
        ("pairwise_logistic", LearnedRanker(model_type="pairwise_logistic", C=1.0, random_state=seed)),
        ("logistic_c1.0", LearnedRanker(model_type="logistic", C=1.0, random_state=seed)),
        ("logistic_c0.2", LearnedRanker(model_type="logistic", C=0.2, random_state=seed)),
        ("random_forest", LearnedRanker(model_type="random_forest", n_estimators=150, max_depth=8, random_state=seed)),
        ("hist_gb", LearnedRanker(model_type="hist_gb", max_iter=150, max_depth=6, learning_rate=0.08, random_state=seed)),
    ]

    model_results: list[dict[str, Any]] = []
    trained_models: dict[str, Any] = {}

    for name, model in candidates_models:
        if isinstance(model, LearnedRanker) and model.model_type == "pairwise_logistic" and not X_pref:
            continue
        fit_t0 = time.perf_counter()
        if isinstance(model, LearnedRanker):
            if model.model_type == "pairwise_logistic":
                model.fit(X_pref, y_pref, sample_weight=w_pref)
            else:
                model.fit(X_train, y_train, sample_weight=sample_weight_train)
        fit_sec = round(time.perf_counter() - fit_t0, 3)

        eval_preds = predict_top_k_candidates(eval_entries, all_refs, model=model, split_manifest=split_map, k=5)
        valid_bd = _compute_eval_breakdown(eval_preds, method_by_pub, "valid", labeled_pairs=labeled_pairs)
        test_bd = _compute_eval_breakdown(eval_preds, method_by_pub, "test", labeled_pairs=labeled_pairs)

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
        # Chọn model tốt nhất trên Valid MRR@5 (ưu tiên pairwise_logistic -> LearnedRanker khác -> rule baseline khi hòa)
        def _model_tie_priority(model_name: str) -> int:
            if model_name == "pairwise_logistic":
                return 2
            return 1 if isinstance(trained_models[model_name], LearnedRanker) else 0

        best_result = max(
            model_results,
            key=lambda res: (
                res["valid"]["all_entries"]["mrr"],
                res["valid"]["all_entries"]["hit_rate"],
                res["valid"]["matched_entries_only"]["mrr"],
                _model_tie_priority(res["model_name"]),
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
        "split_strategy_used": split_strategy_used,
        "generated_auto_shards": generated_auto_shards,
        "negative_sample_ratio": negative_ratio,
        "hard_negative_fraction": hard_negative_fraction,
        "manual_sample_weight": manual_weight,
        "max_train_entries_per_pub": max_train_entries_per_pub,
        "total_assigned_papers": total_papers_count,
        "quota_validation": quota_report,
        "split_summary": split_summary,
        "train_dataset": {
            "total_train_entries": len(train_entries),
            "labeled_train_entries": len(labeled_train_entries),
            "unlabeled_train_entries_skipped": unlabeled_train_skipped,
            "sampled_train_entries": len(sampled_train_entries),
            "pairwise_rows": len(X_train),
            "positive_pairs": sum(y_train),
            "negative_pairs": len(y_train) - sum(y_train),
            "preference_rows": len(X_pref),
        },
        "eval_entries": {
            "valid_entries_total": len(valid_entries),
            "valid_entries_labeled": sum(1 for e in valid_entries if e.get("is_labeled", True)),
            "test_entries_total": len(test_entries),
            "test_entries_labeled": sum(1 for e in test_entries if e.get("is_labeled", True)),
        },
        "best_model": best_name,
        "model_comparison": model_results,
        "eval_only": eval_only,
    }

    if split_output is not None and not eval_only:
        export_split_manifest(split_info, split_output)
        summary["split_manifest_path"] = str(split_output)

    if model_output is not None and not eval_only:
        model_bytes = pickle.dumps(best_model, protocol=pickle.HIGHEST_PROTOCOL)
        _atomic_write_bytes(model_output, model_bytes)
        summary["model_artifact"] = {
            "path": str(model_output),
            "sha256": hashlib.sha256(model_bytes).hexdigest(),
        }

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
        mrr_summary = evaluate_predictions_summary(all_preds, k=5)
        labeled_summary = {
            part: _compute_eval_breakdown(all_preds, method_by_pub, part, labeled_pairs=labeled_pairs)
            for part in ("test", "valid", "train")
        }
        is_valid = val_report.is_valid
        summary["predictions_output"] = {
            "tables_dir": str(output_tables_dir / "predictions"),
            "shards_count": len(written_shards),
            "total_rows": pred_table.num_rows,
            "is_valid": val_report.is_valid,
            "errors": val_report.errors,
            "warnings": val_report.warnings,
            "stats": val_report.stats,
            "labeled_only_summary": labeled_summary,
            "best_model_full_summary": mrr_summary,
        }

        if export_per_member_dir is not None:
            # Gom nhóm dữ liệu theo shard trong đúng 1 lần duyệt O(N)
            preds_by_shard: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for r in all_preds:
                idx = owner_by_pub.get(r["arxiv_id"])
                if idx is not None:
                    preds_by_shard[idx].append(r)

            papers_by_shard: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for r in papers_tbl.to_pylist():
                idx = owner_by_pub.get(r["arxiv_id"])
                if idx is not None:
                    papers_by_shard[idx].append(r)

            bib_by_shard: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for r in bib_tbl.to_pylist():
                idx = owner_by_pub.get(r["arxiv_id"])
                if idx is not None:
                    bib_by_shard[idx].append(r)

            refs_by_shard: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for r in all_refs:
                idx = owner_by_pub.get(r["arxiv_id"])
                if idx is not None:
                    refs_by_shard[idx].append(r)

            split_by_shard: dict[int, list[Any]] = defaultdict(list)
            for s in split_info:
                idx = owner_by_pub.get(s.arxiv_id)
                if idx is not None:
                    split_by_shard[idx].append(s)

            labeled_pubs_by_shard: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for p in [*manual_pubs, *auto_pubs]:
                idx = owner_by_pub.get(p["arxiv_id"])
                if idx is not None:
                    labeled_pubs_by_shard[idx].append(p)

            per_member_exports: dict[str, Any] = {}
            used_names: set[str] = set()

            for shard_idx, d_dir in enumerate(resolved_dirs):
                base_name = d_dir.name or f"shard_{shard_idx + 1}"
                shard_name = base_name if base_name not in used_names else f"{base_name}_{shard_idx + 1}"
                used_names.add(shard_name)

                shard_preds = preds_by_shard[shard_idx]
                shard_split = split_by_shard[shard_idx]
                shard_out_root = export_per_member_dir / shard_name
                shard_pred_tbl = create_table_from_records(shard_preds, PREDICTIONS_SCHEMA)
                shard_written = write_sharded_parquet(shard_pred_tbl, shard_out_root / "tables", "predictions")
                export_split_manifest(shard_split, shard_out_root / "matching" / "split_manifest.json")

                shard_val = validate_predictions_table(
                    shard_pred_tbl,
                    bibtex_table=create_table_from_records(bib_by_shard[shard_idx], BIBTEX_SCHEMA),
                    references_table=create_table_from_records(refs_by_shard[shard_idx], REFERENCES_SCHEMA),
                    papers_table=create_table_from_records(papers_by_shard[shard_idx], PAPERS_SCHEMA),
                )
                shard_quota = validate_labeling_quota(
                    labeled_publications=labeled_pubs_by_shard[shard_idx],
                    total_assigned_publications_count=paper_counts_by_shard[shard_idx],
                    num_members=1,
                )
                if not shard_val.is_valid:
                    is_valid = False

                per_member_exports[shard_name] = {
                    "source_data_dir": str(d_dir),
                    "predictions_dir": str(shard_out_root / "tables" / "predictions"),
                    "split_manifest_path": str(shard_out_root / "matching" / "split_manifest.json"),
                    "shards_count": len(shard_written),
                    "total_rows": shard_pred_tbl.num_rows,
                    "is_valid": shard_val.is_valid,
                    "errors": shard_val.errors,
                    "warnings": shard_val.warnings,
                    "partition_pub_counts": {
                        part: sum(1 for s in shard_split if s.partition == part)
                        for part in ("train", "valid", "test")
                    },
                    "quota_is_valid": shard_quota["is_valid"],
                    "valid_labeled": _compute_eval_breakdown(
                        shard_preds, method_by_pub, "valid", labeled_pairs=labeled_pairs
                    ),
                    "test_labeled": _compute_eval_breakdown(
                        shard_preds, method_by_pub, "test", labeled_pairs=labeled_pairs
                    ),
                }
            summary["per_member_exports"] = per_member_exports

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
        "--hard-negative-fraction",
        type=float,
        default=0.5,
        help="Fraction of sampled negatives selected via hard-negative pre-scoring (0.0..1.0).",
    )
    parser.add_argument(
        "--manual-weight",
        type=float,
        default=5.0,
        help="Sample weight multiplier for manually labeled training pairs (>= 1.0).",
    )
    parser.add_argument(
        "--max-train-entries-per-pub",
        type=int,
        default=300,
        help="Cap negative entries per train pub during fit() (0 = no cap). Never caps Valid/Test or predictions.",
    )
    parser.add_argument(
        "--model",
        default="auto",
        choices=[
            "auto",
            "heuristic_ranker",
            "logistic_c1.0",
            "logistic_c0.2",
            "pairwise_logistic",
            "random_forest",
            "hist_gb",
        ],
        help="Model to export predictions with (default: auto = best on Valid MRR@5).",
    )
    parser.add_argument(
        "--split-strategy",
        default="auto",
        choices=["auto", "stratified", "global"],
        help="Split strategy: 'auto' uses stratified per-member split when len(--data-dir)==--num-members>1.",
    )
    parser.add_argument(
        "--generate-missing-auto",
        action="store_true",
        help="Auto-generate 12%% heuristic automatic labels in-memory for any member shard missing auto_labels.json.",
    )
    parser.add_argument("--allow-partial-quota", action="store_true", help="Allow running even if quota validation fails.")
    parser.add_argument("--eval-only", action="store_true", help="Train & evaluate models only; skip writing Parquet.")
    parser.add_argument("--output-tables-dir", type=Path, help="Default: <first data-dir>/tables")
    parser.add_argument("--report-output", type=Path, help="Default: <first data-dir>/matching/m3_eval_report.json")
    parser.add_argument("--split-output", type=Path, help="Default: <first data-dir>/matching/split_manifest.json")
    parser.add_argument("--model-output", type=Path, help="Default: <first data-dir>/matching/matching_model.pkl")
    parser.add_argument(
        "--export-per-member-dir",
        type=Path,
        help="Optional output directory to split & validate individual tables/predictions per member shard for HF upload.",
    )
    args = parser.parse_args()

    if args.num_members < 1:
        print(f"[ERROR] --num-members must be >= 1, got {args.num_members}", file=sys.stderr)
        return 2
    if args.negative_ratio < 1:
        print(f"[ERROR] --negative-ratio must be >= 1, got {args.negative_ratio}", file=sys.stderr)
        return 2
    if not (0.0 <= args.hard_negative_fraction <= 1.0):
        print(
            f"[ERROR] --hard-negative-fraction must be in [0.0, 1.0], got {args.hard_negative_fraction}",
            file=sys.stderr,
        )
        return 2
    if args.manual_weight < 1.0:
        print(f"[ERROR] --manual-weight must be >= 1.0, got {args.manual_weight}", file=sys.stderr)
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
        or [_discover_manual_label_path(d) for d in data_dirs]
    )
    if args.auto_labels:
        auto_paths = [p.expanduser().resolve() for p in args.auto_labels]
    else:
        discovered_auto = [_discover_auto_label_path(d) for d in data_dirs]
        if args.generate_missing_auto:
            auto_paths = [p for p in discovered_auto if p is not None]
        else:
            auto_paths = [
                p if p is not None else (d / "matching" / "auto_labels.json")
                for d, p in zip(data_dirs, discovered_auto)
            ]

    output_tables_dir = (args.output_tables_dir or (primary_dir / "tables")).expanduser().resolve()
    report_output = (args.report_output or (primary_dir / "matching" / "m3_eval_report.json")).expanduser().resolve()
    split_output = (args.split_output or (primary_dir / "matching" / "split_manifest.json")).expanduser().resolve()
    model_output = (args.model_output or (primary_dir / "matching" / "matching_model.pkl")).expanduser().resolve()
    export_per_member_dir = args.export_per_member_dir.expanduser().resolve() if args.export_per_member_dir else None

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
        hard_negative_fraction=args.hard_negative_fraction,
        manual_weight=args.manual_weight,
        split_strategy=args.split_strategy,
        generate_missing_auto=args.generate_missing_auto,
        model_output=model_output if not args.eval_only else None,
        export_per_member_dir=export_per_member_dir,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
