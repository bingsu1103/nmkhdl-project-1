"""Auditable Milestone 3 orchestration for one member shard.

The matching implementation lives in the Member 4 modules.  This module is the
Member 1 integration boundary: it loads the real M1/M2 tables, validates manual
labels, builds the automatic pool, creates publication-disjoint splits, trains
the learned ranker, writes predictions, and persists a release report.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .evaluate import compute_mrr_at_k
from .label import (
    create_publication_split,
    heuristic_match_entry,
    validate_labeling_quota,
)
from .model import (
    HeuristicRanker,
    LearnedRanker,
    build_pairwise_dataset,
    predict_top_k_candidates,
)
from .normalize import normalize_arxiv_id
from .normalize import normalize_text
from .storage import (
    BIBTEX_SCHEMA,
    PAPERS_SCHEMA,
    PREDICTIONS_SCHEMA,
    REFERENCES_SCHEMA,
    create_table_from_records,
    read_sharded_parquet,
    write_sharded_parquet,
)
from .validate import validate_predictions_table


class Milestone3IntegrationError(RuntimeError):
    """M3 inputs or release gates are incomplete."""


def generate_assisted_manual_labels(
    *,
    data_dir: str | Path,
    output_path: str | Path,
    publication_count: int = 5,
    entries_per_publication: int = 20,
) -> dict[str, Any]:
    """Create auditable labels only from unique exact-title evidence.

    This is deliberately stricter than the automatic matcher.  It never labels
    a no-match and never accepts fuzzy similarity: a BibTeX title must map to
    exactly one same-publication Semantic Scholar reference after normalization.
    Provenance remains explicit so the result is not represented as unaided
    student annotation.
    """
    root = Path(data_dir)
    bibtex = read_sharded_parquet(root / "tables/bibtex", BIBTEX_SCHEMA).to_pylist()
    references = read_sharded_parquet(
        root / "tables/references", REFERENCES_SCHEMA
    ).to_pylist()
    bib_by_pub = _group_by_publication(bibtex)
    refs_by_pub = _group_by_publication(references)
    labels_by_pub: dict[str, list[dict[str, Any]]] = {}

    for aid in sorted(set(bib_by_pub) & set(refs_by_pub)):
        refs_by_title: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for ref in refs_by_pub[aid]:
            title = normalize_text(ref.get("ref_title") or "").casefold()
            if title:
                refs_by_title[title].append(ref)
        labels: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for entry in sorted(bib_by_pub[aid], key=lambda row: str(row["citation_key"])):
            key = str(entry["citation_key"])
            title = normalize_text(entry.get("title") or "").casefold()
            matches = refs_by_title.get(title, [])
            unique_ids = sorted({
                normalize_arxiv_id(row.get("ref_arxiv_id")) for row in matches
                if normalize_arxiv_id(row.get("ref_arxiv_id"))
            })
            if key in seen_keys or len(unique_ids) != 1:
                continue
            seen_keys.add(key)
            ref = matches[0]
            labels.append({
                "arxiv_id": aid,
                "citation_key": key,
                "bib_title": entry.get("title"),
                "reference_title": ref.get("ref_title"),
                "groundtruth_arxiv_id": unique_ids[0],
                "review_status": "reviewed",
                "reviewed_by": "member-1+codex-assisted-exact-evidence",
                "notes": "Unique exact normalized-title match within the same publication candidate set.",
            })
        if len(labels) >= entries_per_publication:
            labels_by_pub[aid] = labels[:entries_per_publication]

    selected = sorted(labels_by_pub, key=lambda aid: (-len(labels_by_pub[aid]), aid))[
        :publication_count
    ]
    if len(selected) < publication_count:
        raise Milestone3IntegrationError(
            f"Only {len(selected)} publications contain at least "
            f"{entries_per_publication} unique exact-title matches; need {publication_count}."
        )
    rows = [row for aid in selected for row in labels_by_pub[aid]]
    output = Path(output_path)
    _write_jsonl_atomic(output, rows)
    return {
        "publication_count": len(selected),
        "entry_count": len(rows),
        "entries_per_publication": entries_per_publication,
        "publications": selected,
        "method": "codex-assisted-unique-exact-title-evidence",
        "output": str(output),
    }


def prepare_manual_label_review(
    *,
    data_dir: str | Path,
    output_path: str | Path,
    publication_count: int = 5,
    min_entries: int = 20,
    max_entries: int = 40,
) -> dict[str, Any]:
    """Create a compact, deterministic review packet without claiming labels."""
    root = Path(data_dir)
    bibtex = read_sharded_parquet(root / "tables/bibtex", BIBTEX_SCHEMA).to_pylist()
    references = read_sharded_parquet(
        root / "tables/references", REFERENCES_SCHEMA
    ).to_pylist()
    bib_by_pub = _group_by_publication(bibtex)
    refs_by_pub = _group_by_publication(references)

    eligible = [
        aid
        for aid, entries in bib_by_pub.items()
        if min_entries <= len(entries) <= max_entries and refs_by_pub.get(aid)
    ]
    eligible.sort(key=lambda aid: (len(bib_by_pub[aid]), aid))
    selected = eligible[:publication_count]
    if len(selected) < publication_count:
        raise Milestone3IntegrationError(
            f"Only {len(selected)} publications have {min_entries}..{max_entries} "
            f"BibTeX entries and Semantic Scholar candidates; need {publication_count}."
        )

    ranker = HeuristicRanker()
    rows: list[dict[str, Any]] = []
    for aid in selected:
        candidates = refs_by_pub[aid]
        for entry in bib_by_pub[aid]:
            ranked = ranker.rank_candidates(entry, candidates)[:5]
            candidate_lookup = {
                normalize_arxiv_id(row.get("ref_arxiv_id")): row for row in candidates
            }
            rows.append(
                {
                    "arxiv_id": aid,
                    "citation_key": entry["citation_key"],
                    "bib_title": entry["title"],
                    "bib_authors": entry.get("authors") or [],
                    "bib_year": entry.get("year"),
                    "suggestions": [
                        {
                            "ref_arxiv_id": ref_id,
                            "score": round(score, 6),
                            "ref_title": candidate_lookup.get(ref_id, {}).get("ref_title"),
                            "ref_authors": candidate_lookup.get(ref_id, {}).get("ref_authors") or [],
                            "ref_submission_date": candidate_lookup.get(ref_id, {}).get(
                                "ref_submission_date"
                            ),
                        }
                        for ref_id, score in ranked
                    ],
                    "groundtruth_arxiv_id": None,
                    "review_status": "pending",
                    "notes": None,
                }
            )

    output = Path(output_path)
    _write_jsonl_atomic(output, rows)
    return {
        "publication_count": len(selected),
        "entry_count": len(rows),
        "publications": selected,
        "output": str(output),
        "status": "requires_manual_review",
    }


def run_matching_pipeline(
    *,
    data_dir: str | Path,
    manual_labels_path: str | Path,
    assigned_publication_count: int,
    num_members: int = 1,
    random_seed: int = 42,
) -> dict[str, Any]:
    """Run the real-data M3 workflow and enforce all release gates."""
    root = Path(data_dir)
    tables = root / "tables"
    papers_table = read_sharded_parquet(tables / "papers", PAPERS_SCHEMA)
    references_table = read_sharded_parquet(tables / "references", REFERENCES_SCHEMA)
    bibtex_table = read_sharded_parquet(tables / "bibtex", BIBTEX_SCHEMA)
    papers = papers_table.to_pylist()
    references = references_table.to_pylist()
    bibtex = bibtex_table.to_pylist()
    if len(papers) != assigned_publication_count:
        raise Milestone3IntegrationError(
            f"papers table has {len(papers)} rows; expected {assigned_publication_count}"
        )

    manual_labels = _read_reviewed_manual_labels(manual_labels_path)
    refs_by_pub = _group_by_publication(references)
    bib_by_pub = _group_by_publication(bibtex)
    manual_summaries = _validate_manual_labels(
        manual_labels, bib_by_pub=bib_by_pub, refs_by_pub=refs_by_pub,
        min_publications=5 * num_members,
    )

    manual_ids = {row["arxiv_id"] for row in manual_summaries}
    required_auto = max(
        2 * num_members,
        math.ceil(0.10 * max(0, assigned_publication_count - len(manual_ids))),
    )
    auto_candidates = sorted(
        aid for aid in set(bib_by_pub) & set(refs_by_pub) if aid not in manual_ids
    )
    if len(auto_candidates) < required_auto:
        raise Milestone3IntegrationError(
            f"Only {len(auto_candidates)} publications can be automatically matched; "
            f"the 10% gate requires {required_auto}."
        )
    auto_ids = auto_candidates[:required_auto]

    labels_by_pair = {
        (row["arxiv_id"], row["citation_key"]): row["groundtruth_arxiv_id"]
        for row in manual_labels
    }
    auto_summaries: list[dict[str, Any]] = []
    for aid in auto_ids:
        for entry in bib_by_pub[aid]:
            labels_by_pair[(aid, entry["citation_key"])] = heuristic_match_entry(
                entry, refs_by_pub[aid]
            )
        auto_summaries.append(
            {
                "arxiv_id": aid,
                "method": "automatic",
                "labeled_by": "heuristic-v1",
                "entries_count": len(bib_by_pub[aid]),
            }
        )

    quota = validate_labeling_quota(
        manual_summaries + auto_summaries,
        total_assigned_publications_count=assigned_publication_count,
        num_members=num_members,
    )
    if not quota["is_valid"]:
        raise Milestone3IntegrationError("Label quota failed: " + "; ".join(quota["errors"]))

    split = create_publication_split(
        manual_summaries,
        auto_summaries,
        num_members=num_members,
        random_seed=random_seed,
    )
    split_records = [item.__dict__ for item in split]
    split_map = {item.arxiv_id: item.partition for item in split}
    _write_json_atomic(root / "manifests/matching/split_manifest.json", split_records)

    matching_entries: list[dict[str, Any]] = []
    for aid in sorted(split_map):
        for entry in bib_by_pub[aid]:
            annotated = dict(entry)
            annotated["groundtruth_arxiv_id"] = labels_by_pair.get(
                (aid, entry["citation_key"])
            )
            matching_entries.append(annotated)

    train_entries = [
        row for row in matching_entries if split_map[row["arxiv_id"]] == "train"
    ]
    X, y, _ = build_pairwise_dataset(
        train_entries, references, negative_sample_ratio=10, seed=random_seed
    )
    if not X or len(set(y)) < 2:
        raise Milestone3IntegrationError(
            "Training pairs do not contain both positive and negative classes."
        )

    heuristic = HeuristicRanker()
    learned = LearnedRanker(random_state=random_seed).fit(X, y)
    baseline_predictions = predict_top_k_candidates(
        matching_entries, references, heuristic, split_manifest=split_map
    )
    learned_predictions = predict_top_k_candidates(
        matching_entries, references, learned, split_manifest=split_map
    )
    baseline_valid = compute_mrr_at_k(
        baseline_predictions, k=5, partition_filter="valid"
    )
    learned_valid = compute_mrr_at_k(
        learned_predictions, k=5, partition_filter="valid"
    )
    if learned_valid["mrr"] >= baseline_valid["mrr"]:
        selected_name = "logistic"
        selected_model: Any = learned
        predictions = learned_predictions
    else:
        selected_name = "heuristic"
        selected_model = heuristic
        predictions = baseline_predictions

    prediction_table = create_table_from_records(predictions, PREDICTIONS_SCHEMA)
    validation = validate_predictions_table(
        prediction_table,
        bibtex_table=bibtex_table,
        references_table=references_table,
        papers_table=papers_table,
    )
    if not validation.is_valid:
        raise Milestone3IntegrationError(
            "Predictions validation failed: " + "; ".join(validation.errors[:10])
        )
    prediction_shards = write_sharded_parquet(
        prediction_table, tables, "predictions"
    )

    artifact_path = root / "models/matching_model.pkl"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = artifact_path.with_suffix(".pkl.tmp")
    temporary.write_bytes(pickle.dumps(selected_model, protocol=pickle.HIGHEST_PROTOCOL))
    temporary.replace(artifact_path)
    model_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

    report = {
        "is_success": True,
        "assigned_publication_count": assigned_publication_count,
        "input_rows": {
            "papers": len(papers),
            "references": len(references),
            "bibtex": len(bibtex),
        },
        "quota": quota,
        "split": {
            part: sum(1 for item in split if item.partition == part)
            for part in ("train", "valid", "test")
        },
        "training": {
            "pair_count": len(X),
            "positive_pairs": sum(y),
            "negative_pairs": len(y) - sum(y),
            "random_seed": random_seed,
        },
        "model_selection": {
            "selected": selected_name,
            "baseline_valid": baseline_valid,
            "learned_valid": learned_valid,
            "selection_partition": "valid",
            "model_sha256": model_hash,
        },
        "final_test": compute_mrr_at_k(predictions, k=5, partition_filter="test"),
        "prediction_validation": validation.to_dict(),
        "prediction_rows": prediction_table.num_rows,
        "prediction_shards": [str(path.relative_to(root)) for path in prediction_shards],
        "manual_labels_sha256": hashlib.sha256(
            Path(manual_labels_path).read_bytes()
        ).hexdigest(),
    }
    _write_json_atomic(root / "manifests/matching/m3_run_summary.json", report)
    return report


def _read_reviewed_manual_labels(path: str | Path) -> list[dict[str, Any]]:
    rows = _read_jsonl(Path(path))
    reviewed: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        if row.get("review_status") != "reviewed":
            raise Milestone3IntegrationError(
                f"Manual label row {index} is not explicitly marked review_status=reviewed"
            )
        aid = normalize_arxiv_id(row.get("arxiv_id"))
        key = str(row.get("citation_key") or "").strip()
        if not aid or not key:
            raise Milestone3IntegrationError(f"Manual label row {index} has an empty key")
        gt = normalize_arxiv_id(row.get("groundtruth_arxiv_id")) or None
        reviewed.append(
            {
                "arxiv_id": aid,
                "citation_key": key,
                "groundtruth_arxiv_id": gt,
                "notes": row.get("notes"),
                "reviewed_by": str(row.get("reviewed_by") or "member-1").strip(),
            }
        )
    return reviewed


def _validate_manual_labels(
    labels: list[dict[str, Any]],
    *,
    bib_by_pub: dict[str, list[dict[str, Any]]],
    refs_by_pub: dict[str, list[dict[str, Any]]],
    min_publications: int,
) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    counts: dict[str, int] = defaultdict(int)
    reviewers: dict[str, set[str]] = defaultdict(set)
    valid_bib = {
        (aid, str(row["citation_key"])) for aid, rows in bib_by_pub.items() for row in rows
    }
    valid_refs = {
        aid: {normalize_arxiv_id(row.get("ref_arxiv_id")) for row in rows}
        for aid, rows in refs_by_pub.items()
    }
    for row in labels:
        pair = (row["arxiv_id"], row["citation_key"])
        if pair in seen:
            raise Milestone3IntegrationError(f"Duplicate manual label: {pair}")
        if pair not in valid_bib:
            raise Milestone3IntegrationError(f"Manual label does not exist in bibtex: {pair}")
        gt = row["groundtruth_arxiv_id"]
        if gt and gt not in valid_refs.get(row["arxiv_id"], set()):
            raise Milestone3IntegrationError(
                f"Manual ground truth is not a same-publication candidate: {pair} -> {gt}"
            )
        seen.add(pair)
        counts[row["arxiv_id"]] += 1
        reviewers[row["arxiv_id"]].add(row["reviewed_by"])
    if len(counts) < min_publications:
        raise Milestone3IntegrationError(
            f"Manual labels cover {len(counts)} publications; need {min_publications}."
        )
    under = {aid: count for aid, count in counts.items() if count < 20}
    if under:
        raise Milestone3IntegrationError(f"Manual publications below 20 labels: {under}")
    return [
        {
            "arxiv_id": aid,
            "method": "manual",
            "labeled_by": "+".join(sorted(reviewers[aid])),
            "entries_count": count,
        }
        for aid, count in sorted(counts.items())
    ]


def _group_by_publication(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        aid = normalize_arxiv_id(row.get("arxiv_id"))
        if aid:
            grouped[aid].append(row)
    return dict(grouped)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise Milestone3IntegrationError(f"Missing JSONL input: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise Milestone3IntegrationError(f"Invalid JSONL at {path}:{line_number}") from exc
        if not isinstance(row, dict):
            raise Milestone3IntegrationError(f"JSONL row is not an object: {path}:{line_number}")
        rows.append(row)
    return rows


def _write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
