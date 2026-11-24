from __future__ import annotations

import json
from pathlib import Path

from src.m3_integration import prepare_manual_label_review, run_matching_pipeline
from src.storage import (
    BIBTEX_SCHEMA,
    PAPERS_SCHEMA,
    REFERENCES_SCHEMA,
    create_table_from_records,
    read_sharded_parquet,
    write_sharded_parquet,
)


def _build_realistic_tables(root: Path) -> list[dict[str, object]]:
    papers = []
    references = []
    bibtex = []
    labels = []
    for pub_idx in range(7):
        aid = f"2509.{16047 + pub_idx:05d}"
        papers.append(
            {
                "arxiv_id": aid,
                "title": f"Citing paper {pub_idx}",
                "authors": ["Example, Alice"],
                "submission_date": "2025-09-01",
                "revised_dates": [],
                "venue": None,
            }
        )
        references.extend(
            [
                {
                    "arxiv_id": aid,
                    "ref_arxiv_id": f"2401.{pub_idx + 1:05d}",
                    "ref_title": f"Exact reference for publication {pub_idx}",
                    "ref_authors": ["Author, Ann"],
                    "ref_submission_date": "2024-01-01",
                    "ref_s2_id": f"s2-{pub_idx}-positive",
                },
                {
                    "arxiv_id": aid,
                    "ref_arxiv_id": f"2301.{pub_idx + 1:05d}",
                    "ref_title": f"Unrelated reference {pub_idx}",
                    "ref_authors": ["Other, Bob"],
                    "ref_submission_date": "2023-01-01",
                    "ref_s2_id": f"s2-{pub_idx}-negative",
                },
            ]
        )
        for entry_idx in range(20):
            key = f"ref-{entry_idx:02d}"
            bibtex.append(
                {
                    "arxiv_id": aid,
                    "citation_key": key,
                    "entry_type": "article",
                    "title": f"Exact reference for publication {pub_idx}",
                    "authors": ["Author, Ann"],
                    "year": 2024,
                    "doi": None,
                    "journal": None,
                    "url": None,
                }
            )
            if pub_idx < 5:
                labels.append(
                    {
                        "arxiv_id": aid,
                        "citation_key": key,
                        "groundtruth_arxiv_id": f"2401.{pub_idx + 1:05d}",
                        "review_status": "reviewed",
                        "notes": "Exact title and author match.",
                    }
                )
    write_sharded_parquet(create_table_from_records(papers, PAPERS_SCHEMA), root / "tables", "papers")
    write_sharded_parquet(
        create_table_from_records(references, REFERENCES_SCHEMA), root / "tables", "references"
    )
    write_sharded_parquet(create_table_from_records(bibtex, BIBTEX_SCHEMA), root / "tables", "bibtex")
    return labels


def test_prepare_review_and_run_matching_pipeline(tmp_path: Path) -> None:
    labels = _build_realistic_tables(tmp_path)
    review_path = tmp_path / "labels/review.jsonl"
    prepared = prepare_manual_label_review(
        data_dir=tmp_path,
        output_path=review_path,
        publication_count=5,
        min_entries=20,
        max_entries=20,
    )
    assert prepared["publication_count"] == 5
    assert prepared["entry_count"] == 100
    assert all(
        json.loads(line)["review_status"] == "pending"
        for line in review_path.read_text(encoding="utf-8").splitlines()
    )

    manual_path = tmp_path / "labels/manual.jsonl"
    manual_path.write_text(
        "".join(json.dumps(row) + "\n" for row in labels), encoding="utf-8"
    )
    report = run_matching_pipeline(
        data_dir=tmp_path,
        manual_labels_path=manual_path,
        assigned_publication_count=7,
        num_members=1,
        random_seed=42,
    )

    assert report["is_success"] is True
    assert report["quota"]["is_valid"] is True
    assert report["split"] == {"train": 3, "valid": 2, "test": 2}
    assert report["final_test"]["mrr"] == 1.0
    predictions = read_sharded_parquet(tmp_path / "tables/predictions")
    assert predictions.num_rows == 140
    assert (tmp_path / "manifests/matching/m3_run_summary.json").is_file()
    assert (tmp_path / "models/matching_model.pkl").is_file()
