from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.m2_integration import (
    Milestone2IntegrationError,
    build_m2_tables,
    validate_m2_tables,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def test_build_and_validate_m2_tables(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "parsed/elements.jsonl",
        [
            {
                "element_id": "2509.16047#root",
                "arxiv_id": "2509.16047",
                "kind": "document",
                "content": "root",
            },
            {
                "element_id": "2509.16047#heading",
                "arxiv_id": "2509.16047",
                "kind": "heading",
                "content": "Introduction",
            },
        ],
    )
    _write_jsonl(
        tmp_path / "parsed/hierarchy.jsonl",
        [
            {
                "arxiv_id": "2509.16047",
                "version": 1,
                "element_id": "2509.16047#heading",
                "parent_id": "2509.16047#root",
            }
        ],
    )
    _write_jsonl(tmp_path / "parsed/bibtex.jsonl", [])
    _write_jsonl(
        tmp_path / "manifests/parsing/m2_inputs.jsonl",
        [
            {
                "arxiv_id": "2509.16047",
                "versioned_arxiv_id": "2509.16047v1",
                "version": 1,
            }
        ],
    )
    _write_jsonl(
        tmp_path / "parsed/parse_status.jsonl",
        [
            {
                "arxiv_id": "2509.16047",
                "versioned_arxiv_id": "2509.16047v1",
                "version": 1,
                "status": "success",
            }
        ],
    )

    summary = build_m2_tables(data_dir=tmp_path)
    assert summary["row_counts"] == {"elements": 2, "hierarchy": 1, "bibtex": 0}
    report = validate_m2_tables(data_dir=tmp_path)
    assert report["is_valid"] is True
    assert report["version_coverage"]["unique_publication_versions"] == 1


def test_validate_m2_tables_rejects_missing_version_status(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "parsed/elements.jsonl", [])
    _write_jsonl(tmp_path / "parsed/hierarchy.jsonl", [])
    _write_jsonl(tmp_path / "parsed/bibtex.jsonl", [])
    _write_jsonl(
        tmp_path / "manifests/parsing/m2_inputs.jsonl",
        [
            {
                "arxiv_id": "2509.16047",
                "versioned_arxiv_id": "2509.16047v1",
                "version": 1,
            }
        ],
    )
    _write_jsonl(tmp_path / "parsed/parse_status.jsonl", [])
    build_m2_tables(data_dir=tmp_path)

    report = validate_m2_tables(data_dir=tmp_path)

    assert report["is_valid"] is False
    assert report["version_coverage"]["missing_versioned_arxiv_ids"] == [
        "2509.16047v1"
    ]


def test_build_m2_tables_refuses_missing_bibtex_adapter(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "parsed/elements.jsonl", [])
    _write_jsonl(tmp_path / "parsed/hierarchy.jsonl", [])

    with pytest.raises(Milestone2IntegrationError, match="bibtex"):
        build_m2_tables(data_dir=tmp_path)
