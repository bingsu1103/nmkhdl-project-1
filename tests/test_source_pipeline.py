from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import pytest

from src.source_pipeline import run_source_pipeline


@dataclass(frozen=True)
class FakeDownload:
    status: str
    archive_path: str | None
    archive_bytes: int = 10


@dataclass(frozen=True)
class FakeExtraction:
    status: str
    filtered_bytes: int = 7


def write_tasks(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "member_id",
                "arxiv_id",
                "versioned_arxiv_id",
                "version",
                "status",
                "run_id",
            ),
        )
        writer.writeheader()
        writer.writerows(
            (
                {
                    "member_id": "member-1",
                    "arxiv_id": "2509.16047",
                    "versioned_arxiv_id": "2509.16047v1",
                    "version": "1",
                    "status": "pending",
                    "run_id": "discovery-run",
                },
                {
                    "member_id": "member-2",
                    "arxiv_id": "2509.21047",
                    "versioned_arxiv_id": "2509.21047v1",
                    "version": "1",
                    "status": "pending",
                    "run_id": "discovery-run",
                },
            )
        )


def test_filters_member_and_writes_terminal_handoff(tmp_path: Path) -> None:
    tasks = tmp_path / "version_tasks.csv"
    write_tasks(tasks)
    downloader = mock.Mock()
    downloader.download.return_value = FakeDownload("success", str(tmp_path / "source.archive"))
    extractor = mock.Mock()
    extractor.extract.return_value = FakeExtraction("success")

    with mock.patch("src.source_pipeline.ArxivSourceDownloader", return_value=downloader):
        with mock.patch("src.source_pipeline.SafeSourceExtractor", return_value=extractor):
            summary = run_source_pipeline(
                version_tasks_csv=tasks,
                data_dir=tmp_path / "data",
                user_agent="group-18-test",
                member_id="member-1",
            )

    assert summary["expected_version_tasks"] == 1
    assert summary["terminal_status_records"] == 1
    assert summary["status_counts"] == {"success": 1}
    assert summary["manifest_status_records"] == 1
    assert summary["archive_bytes"] == 10
    assert summary["filtered_tex_bib_bytes"] == 7
    downloader.download.assert_called_once_with("2509.16047", "2509.16047v1", resume=True)
    rows = [
        json.loads(line)
        for line in (tmp_path / "data/manifests/source_status.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["member_id"] == "member-1"
    assert rows[0]["versioned_arxiv_id"] == "2509.16047v1"


def test_isolates_per_version_failure_and_keeps_next_task(tmp_path: Path) -> None:
    tasks = tmp_path / "version_tasks.csv"
    write_tasks(tasks)
    downloader = mock.Mock()
    downloader.download.side_effect = (
        RuntimeError("synthetic failure"),
        FakeDownload("success", str(tmp_path / "source.archive")),
    )
    extractor = mock.Mock()
    extractor.extract.return_value = FakeExtraction("no_tex_bib", filtered_bytes=0)

    with mock.patch("src.source_pipeline.ArxivSourceDownloader", return_value=downloader):
        with mock.patch("src.source_pipeline.SafeSourceExtractor", return_value=extractor):
            summary = run_source_pipeline(
                version_tasks_csv=tasks,
                data_dir=tmp_path / "data",
                user_agent="group-18-test",
            )

    assert summary["terminal_status_records"] == 2
    assert summary["status_counts"] == {"no_tex_bib": 1, "pipeline_error": 1}
    rows = [
        json.loads(line)
        for line in (tmp_path / "data/manifests/source_status.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert rows[0]["error_code"] == "RuntimeError"
    assert rows[1]["status"] == "no_tex_bib"


def test_incrementally_preserves_prior_member_status(tmp_path: Path) -> None:
    tasks = tmp_path / "version_tasks.csv"
    write_tasks(tasks)
    data = tmp_path / "data"
    manifest = data / "manifests/source_status.jsonl"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "member_id": "member-2",
                "arxiv_id": "2509.21047",
                "versioned_arxiv_id": "2509.21047v1",
                "version": 1,
                "status": "success",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    downloader = mock.Mock()
    downloader.download.return_value = FakeDownload("success", str(tmp_path / "source.archive"))
    extractor = mock.Mock()
    extractor.extract.return_value = FakeExtraction("success")

    with mock.patch("src.source_pipeline.ArxivSourceDownloader", return_value=downloader):
        with mock.patch("src.source_pipeline.SafeSourceExtractor", return_value=extractor):
            summary = run_source_pipeline(
                version_tasks_csv=tasks,
                data_dir=data,
                user_agent="group-18-test",
                member_id="member-1",
            )

    assert summary["manifest_status_records"] == 2
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    assert [row["member_id"] for row in rows] == ["member-1", "member-2"]


def test_rejects_manifest_without_version_contract(tmp_path: Path) -> None:
    tasks = tmp_path / "version_tasks.csv"
    tasks.write_text("arxiv_id\n2509.16047\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must contain columns"):
        run_source_pipeline(
            version_tasks_csv=tasks,
            data_dir=tmp_path / "data",
            user_agent="group-18-test",
        )
