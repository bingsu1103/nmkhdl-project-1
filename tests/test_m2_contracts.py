from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.m2_contracts import ParsingContractError, build_parsing_inputs


def _write_tasks(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("member_id", "arxiv_id", "versioned_arxiv_id", "version"),
        )
        writer.writeheader()
        writer.writerows(
            [
                {
                    "member_id": "member-1",
                    "arxiv_id": "2509.16047",
                    "versioned_arxiv_id": "2509.16047v1",
                    "version": 1,
                },
                {
                    "member_id": "member-1",
                    "arxiv_id": "2509.16047",
                    "versioned_arxiv_id": "2509.16047v2",
                    "version": 2,
                },
            ]
        )


def test_contract_reconciles_ready_and_empty_versions(tmp_path: Path) -> None:
    tasks = tmp_path / "manifests/discovery/version_tasks.csv"
    statuses = tmp_path / "manifests/source_status.jsonl"
    _write_tasks(tasks)
    source_dir = tmp_path / "corpus/tex/2509.16047/2509.16047v1"
    source_dir.mkdir(parents=True)
    (source_dir / "main.tex").write_text("source", encoding="utf-8")
    statuses.parent.mkdir(parents=True, exist_ok=True)
    statuses.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {
                    "member_id": "member-1",
                    "arxiv_id": "2509.16047",
                    "versioned_arxiv_id": "2509.16047v1",
                    "version": 1,
                    "status": "success",
                    "download": {"sha256": "archive-one"},
                    "extraction": {
                        "files": [
                            {"path": "main.tex", "sha256": "tex-one", "bytes": 6}
                        ]
                    },
                },
                {
                    "member_id": "member-1",
                    "arxiv_id": "2509.16047",
                    "versioned_arxiv_id": "2509.16047v2",
                    "version": 2,
                    "status": "no_tex_bib",
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    inputs, report = build_parsing_inputs(
        version_tasks_csv=tasks,
        source_status_jsonl=statuses,
        data_dir=tmp_path,
        member_id="member-1",
    )

    assert [item.input_status for item in inputs] == ["ready", "empty"]
    assert [item.version for item in inputs] == [1, 2]
    assert inputs[0].source_dir == "corpus/tex/2509.16047/2509.16047v1"
    assert len(inputs[0].source_fingerprint) == 64
    assert report["is_complete"] is True
    assert report["input_status_counts"] == {"empty": 1, "ready": 1}


def test_contract_rejects_missing_source_status(tmp_path: Path) -> None:
    tasks = tmp_path / "version_tasks.csv"
    statuses = tmp_path / "source_status.jsonl"
    _write_tasks(tasks)
    statuses.write_text(
        json.dumps(
            {
                "member_id": "member-1",
                "arxiv_id": "2509.16047",
                "versioned_arxiv_id": "2509.16047v1",
                "version": 1,
                "status": "no_tex_bib",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ParsingContractError, match="no source status"):
        build_parsing_inputs(
            version_tasks_csv=tasks,
            source_status_jsonl=statuses,
            data_dir=tmp_path,
        )


def test_contract_rejects_version_lineage_mismatch(tmp_path: Path) -> None:
    tasks = tmp_path / "version_tasks.csv"
    statuses = tmp_path / "source_status.jsonl"
    _write_tasks(tasks)
    rows = []
    for version in (1, 2):
        rows.append(
            {
                "member_id": "member-1",
                "arxiv_id": "2509.16047",
                "versioned_arxiv_id": f"2509.16047v{version}",
                "version": 99 if version == 2 else version,
                "status": "no_tex_bib",
            }
        )
    statuses.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )

    with pytest.raises(ParsingContractError, match="lineage mismatch"):
        build_parsing_inputs(
            version_tasks_csv=tasks,
            source_status_jsonl=statuses,
            data_dir=tmp_path,
        )
