#!/usr/bin/env python3
"""Milestone 3 Step 2: Automatic heuristic reference labeling (MS3-M4-T02).

Applies `src.label.heuristic_match_publication` to a deterministic sample of
publications outside the manual pool (>= 10% of remaining publications), saves
labels in the same publication/label contract as `manual_labels.json`, and
validates labeling quotas via `src.label.validate_labeling_quota`.

Usage:
    python scripts/auto_label.py --data-dir D:/code/nmkhdl-project-1-data-member-4 --member member-4
    python scripts/auto_label.py --data-dir D:/code/nmkhdl-project-1-data-member-4 --member member-4 --verify-only
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from random import Random
from typing import Any

import pyarrow as pa

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.label import heuristic_match_publication, validate_labeling_quota
from src.normalize import normalize_arxiv_id
from src.storage import BIBTEX_SCHEMA, PAPERS_SCHEMA, REFERENCES_SCHEMA, read_sharded_parquet


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _group_unique_rows(
    rows: list[dict[str, Any]],
    key_field: str,
    *,
    normalize_key: bool,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        aid = normalize_arxiv_id(row.get("arxiv_id"))
        raw_key = row.get(key_field)
        key = normalize_arxiv_id(raw_key) if normalize_key else str(raw_key or "")
        if not aid or not key or (aid, key) in seen:
            continue
        seen.add((aid, key))
        grouped[aid].append(row)
    return grouped


def _count_unique_by_pub(table: pa.Table, key_field: str, *, normalize_key: bool) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    seen: set[tuple[str, str]] = set()
    aids = table["arxiv_id"].to_pylist()
    keys = table[key_field].to_pylist()
    for raw_aid, raw_key in zip(aids, keys):
        aid = normalize_arxiv_id(raw_aid)
        key = normalize_arxiv_id(raw_key) if normalize_key else str(raw_key or "")
        if not aid or not key or (aid, key) in seen:
            continue
        seen.add((aid, key))
        counts[aid] += 1
    return counts


def _filter_table_by_arxiv_ids(table: pa.Table, target_ids: set[str]) -> list[dict[str, Any]]:
    raw_ids = table["arxiv_id"].to_pylist()
    mask = pa.array([normalize_arxiv_id(x) in target_ids for x in raw_ids], type=pa.bool_())
    return table.filter(mask).to_pylist()


def _verify_auto_payload(
    *,
    auto_payload: dict[str, Any],
    manual_payload: dict[str, Any],
    total_papers_count: int,
    bib_by_pub: dict[str, list[dict[str, Any]]],
    ref_by_pub: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    errors: list[str] = []
    manual_pubs = manual_payload.get("publications", [])
    auto_pubs = auto_payload.get("publications", [])
    manual_ids = {normalize_arxiv_id(p.get("arxiv_id")) for p in manual_pubs}
    auto_ids = [normalize_arxiv_id(p.get("arxiv_id")) for p in auto_pubs]

    overlap = manual_ids & set(auto_ids)
    if overlap:
        errors.append(f"Manual/auto overlap detected: {sorted(overlap)[:5]}")

    by_pair = {
        (normalize_arxiv_id(r.get("arxiv_id")), str(r.get("citation_key", ""))): r
        for r in auto_payload.get("labels", [])
    }

    for aid in auto_ids:
        entries = bib_by_pub.get(aid, [])
        if not entries:
            errors.append(f"Auto paper {aid}: missing from tables/bibtex.")
            continue
        valid_refs = {normalize_arxiv_id(r.get("ref_arxiv_id")) for r in ref_by_pub.get(aid, [])}
        missing = 0
        for e in entries:
            ckey = str(e["citation_key"])
            rec = by_pair.get((aid, ckey))
            if rec is None:
                missing += 1
                continue
            raw_gt = rec.get("groundtruth_arxiv_id")
            if raw_gt is not None and str(raw_gt).strip() != "":
                gt = normalize_arxiv_id(raw_gt)
                if not gt or gt not in valid_refs:
                    errors.append(f"Auto paper {aid} key '{ckey}': invalid groundtruth '{raw_gt}'.")
        if missing:
            errors.append(f"Auto paper {aid}: {missing} BibTeX entries unlabeled.")

    quota_all = validate_labeling_quota(
        labeled_publications=[*manual_pubs, *auto_pubs],
        total_assigned_publications_count=total_papers_count,
        num_members=1,
    )
    errors.extend(quota_all["errors"])

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": quota_all["warnings"],
        "quota_report": quota_all,
    }


def run_auto_labeling(
    *,
    data_dir: Path,
    member: str,
    manual_path: Path,
    output_path: Path,
    fraction: float,
    threshold: float,
    seed: int,
    min_entries: int,
    min_refs: int,
    verify_only: bool,
) -> tuple[bool, dict[str, Any]]:
    if not manual_path.is_file():
        return False, {"error": f"Manual labels file not found: {manual_path}"}

    manual_payload = json.loads(manual_path.read_text(encoding="utf-8"))
    if verify_only and not output_path.is_file():
        return False, {"error": f"Auto labels file not found: {output_path}"}

    papers_tbl = read_sharded_parquet(data_dir / "tables" / "papers", PAPERS_SCHEMA)
    papers_ids = {aid for raw in papers_tbl["arxiv_id"].to_pylist() if (aid := normalize_arxiv_id(raw))}

    bib_tbl = read_sharded_parquet(data_dir / "tables" / "bibtex", BIBTEX_SCHEMA)
    ref_tbl = read_sharded_parquet(data_dir / "tables" / "references", REFERENCES_SCHEMA)

    bib_counts = _count_unique_by_pub(bib_tbl, "citation_key", normalize_key=False)
    ref_counts = _count_unique_by_pub(ref_tbl, "ref_arxiv_id", normalize_key=True)
    total_pool_size = max(len(papers_ids), len(bib_counts))

    if verify_only:
        auto_payload = json.loads(output_path.read_text(encoding="utf-8"))
        selected_set = {
            aid
            for aid in (
                *(normalize_arxiv_id(p) for p in (auto_payload.get("selected_papers") or [])),
                *(normalize_arxiv_id(p.get("arxiv_id")) for p in (auto_payload.get("publications") or [])),
                *(normalize_arxiv_id(r.get("arxiv_id")) for r in (auto_payload.get("labels") or [])),
            )
            if aid
        }
        bib_by_pub = _group_unique_rows(
            _filter_table_by_arxiv_ids(bib_tbl, selected_set), "citation_key", normalize_key=False
        )
        ref_by_pub = _group_unique_rows(
            _filter_table_by_arxiv_ids(ref_tbl, selected_set), "ref_arxiv_id", normalize_key=True
        )
        report = _verify_auto_payload(
            auto_payload=auto_payload,
            manual_payload=manual_payload,
            total_papers_count=total_pool_size,
            bib_by_pub=bib_by_pub,
            ref_by_pub=ref_by_pub,
        )
        return report["is_valid"], {
            "output": str(output_path),
            "total_papers": len(papers_ids),
            "bibtex_papers": len(bib_counts),
            "auto_papers": len(auto_payload.get("selected_papers", [])),
            "auto_labels": len(auto_payload.get("labels", [])),
            **report,
        }

    manual_ids = {
        normalize_arxiv_id(p) for p in (manual_payload.get("selected_papers") or []) if normalize_arxiv_id(p)
    }
    manual_ids.update(
        normalize_arxiv_id(r.get("arxiv_id"))
        for r in (manual_payload.get("labels") or [])
        if normalize_arxiv_id(r.get("arxiv_id"))
    )

    remaining_outside_manual = max(0, total_pool_size - len(manual_ids))
    target_count = max(2, math.ceil(fraction * remaining_outside_manual))

    eligible = sorted(
        aid
        for aid, b_cnt in bib_counts.items()
        if aid not in manual_ids and b_cnt >= min_entries and ref_counts.get(aid, 0) >= min_refs
    )
    if len(eligible) < target_count:
        return False, {
            "error": (
                f"Only {len(eligible)} eligible publications outside manual pool "
                f"(need {target_count} for fraction={fraction:.2f} of {remaining_outside_manual})."
            )
        }

    rng = Random(seed)
    selected_ids = sorted(rng.sample(eligible, target_count))
    selected_set = set(selected_ids)

    bib_by_pub = _group_unique_rows(
        _filter_table_by_arxiv_ids(bib_tbl, selected_set), "citation_key", normalize_key=False
    )
    ref_by_pub = _group_unique_rows(
        _filter_table_by_arxiv_ids(ref_tbl, selected_set), "ref_arxiv_id", normalize_key=True
    )

    labeled_by = f"heuristic_baseline@{threshold:.2f}"
    publications: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    total_matched = 0

    for aid in selected_ids:
        entries = sorted(bib_by_pub[aid], key=lambda r: str(r["citation_key"]))
        refs = ref_by_pub.get(aid, [])
        matches = heuristic_match_publication(entries, refs, min_similarity_threshold=threshold)
        matched_in_pub = 0
        for entry in entries:
            ckey = str(entry["citation_key"])
            raw_pred = matches.get(ckey)
            pred = (normalize_arxiv_id(raw_pred) or None) if raw_pred else None
            if pred is not None:
                matched_in_pub += 1
                total_matched += 1
            labels.append({
                "arxiv_id": aid,
                "citation_key": ckey,
                "groundtruth_arxiv_id": pred,
                "method": "automatic",
                "labeled_by": labeled_by,
            })
        publications.append({
            "arxiv_id": aid,
            "method": "automatic",
            "labeled_by": labeled_by,
            "entries_count": len(entries),
            "labeled_count": len(entries),
            "matched_count": matched_in_pub,
        })

    auto_payload = {
        "member_id": member,
        "method": "automatic",
        "labeled_by": labeled_by,
        "threshold": threshold,
        "seed": seed,
        "fraction": fraction,
        "updated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "selected_papers": selected_ids,
        "publications": publications,
        "labels": labels,
    }
    _atomic_write_json(output_path, auto_payload)

    report = _verify_auto_payload(
        auto_payload=auto_payload,
        manual_payload=manual_payload,
        total_papers_count=total_pool_size,
        bib_by_pub=bib_by_pub,
        ref_by_pub=ref_by_pub,
    )
    return report["is_valid"], {
        "output": str(output_path),
        "total_papers": len(papers_ids),
        "bibtex_papers": len(bib_counts),
        "eligible_outside_manual": len(eligible),
        "auto_papers": len(selected_ids),
        "auto_labels": len(labels),
        "auto_matched": total_matched,
        "match_rate": round(total_matched / max(1, len(labels)), 4),
        **report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive-free M3 Step 2 automatic heuristic labeling.")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--member", default="member-4")
    parser.add_argument("--manual-labels", type=Path, help="Default: <data-dir>/matching/manual_labels.json")
    parser.add_argument("--output", type=Path, help="Default: <data-dir>/matching/auto_labels.json")
    parser.add_argument("--fraction", type=float, default=0.12, help="Fraction of remaining papers (>= 0.10, default: 0.12).")
    parser.add_argument("--threshold", type=float, default=0.75, help="Similarity threshold for heuristic_match_entry.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-entries", type=int, default=1)
    parser.add_argument("--min-refs", type=int, default=1)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    if not (0.10 <= args.fraction <= 1.0):
        print(f"[ERROR] --fraction must be in [0.10, 1.0], got {args.fraction}", file=sys.stderr)
        return 2
    if not (0.0 <= args.threshold <= 1.25):
        print(
            f"[ERROR] --threshold must be in [0.0, 1.25] (title[0..1] + author[0.15] + year[0.10]), got {args.threshold}",
            file=sys.stderr,
        )
        return 2
    if args.min_entries < 1 or args.min_refs < 0:
        print(f"[ERROR] Invalid --min-entries/--min-refs.", file=sys.stderr)
        return 2

    data_dir = args.data_dir.expanduser().resolve()
    manual_path = (args.manual_labels or (data_dir / "matching" / "manual_labels.json")).expanduser().resolve()
    output_path = (args.output or (data_dir / "matching" / "auto_labels.json")).expanduser().resolve()

    ok, summary = run_auto_labeling(
        data_dir=data_dir,
        member=args.member,
        manual_path=manual_path,
        output_path=output_path,
        fraction=args.fraction,
        threshold=args.threshold,
        seed=args.seed,
        min_entries=args.min_entries,
        min_refs=args.min_refs,
        verify_only=args.verify_only,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
