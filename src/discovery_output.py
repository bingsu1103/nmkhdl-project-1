"""Persist reproducible Milestone 1 discovery handoff manifests."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .pipeline import DiscoveryRun


def write_discovery_outputs(output_dir: str | Path, run: DiscoveryRun) -> dict[str, Path]:
    """Atomically write metadata, version tasks, statuses, and a run summary."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    papers_path = destination / "papers.jsonl"
    versions_path = destination / "version_tasks.csv"
    statuses_path = destination / "discovery_status.jsonl"
    summary_path = destination / "discovery_summary.json"

    paper_rows = [
        asdict(outcome.metadata)
        for outcome in run.outcomes
        if outcome.metadata is not None
    ]
    status_rows = [
        {
            "member_id": outcome.paper.member_id,
            "arxiv_id": outcome.paper.arxiv_id,
            "status": outcome.status.value,
            "error": outcome.error,
            "expected_versions": len(outcome.version_tasks),
        }
        for outcome in run.outcomes
    ]
    version_rows = [
        {
            **asdict(task),
            "status": task.status.value,
            "run_id": run.run_id,
        }
        for outcome in run.outcomes
        for task in outcome.version_tasks
    ]
    counts = Counter(row["status"] for row in status_rows)

    _write_jsonl_atomic(papers_path, paper_rows)
    _write_jsonl_atomic(statuses_path, status_rows)
    _write_csv_atomic(
        versions_path,
        version_rows,
        fieldnames=(
            "member_id",
            "arxiv_id",
            "versioned_arxiv_id",
            "version",
            "status",
            "run_id",
        ),
    )
    _write_json_atomic(
        summary_path,
        {
            "run_id": run.run_id,
            "assigned_count": len(run.outcomes),
            "metadata_count": len(paper_rows),
            "version_task_count": len(version_rows),
            "status_counts": dict(sorted(counts.items())),
        },
    )
    return {
        "papers": papers_path,
        "version_tasks": versions_path,
        "statuses": statuses_path,
        "summary": summary_path,
    }


def _write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def _write_csv_atomic(
    path: Path,
    rows: Iterable[dict[str, Any]],
    *,
    fieldnames: tuple[str, ...],
) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
