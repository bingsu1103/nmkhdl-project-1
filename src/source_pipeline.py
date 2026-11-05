"""Orchestrate per-version source download and allowlist extraction."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from .downloader import ArxivSourceDownloader
from .extractor import SafeSourceExtractor


def run_source_pipeline(
    *,
    version_tasks_csv: str | Path,
    data_dir: str | Path,
    user_agent: str,
    member_id: str | None = None,
    paper_ids: set[str] | None = None,
    limit: int | None = None,
    delay_seconds: float = 3.0,
    timeout: tuple[float, float] = (10.0, 60.0),
    max_attempts: int = 4,
    resume: bool = True,
) -> dict[str, Any]:
    """Download/extract all selected version tasks; always emit one status per task."""
    tasks_path, root = Path(version_tasks_csv), Path(data_dir)
    if not tasks_path.is_file():
        raise FileNotFoundError(f"Missing version task manifest: {tasks_path}")
    tasks: list[dict[str, str]] = []
    with tasks_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"member_id", "arxiv_id", "versioned_arxiv_id", "version"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"version_tasks.csv must contain columns: {sorted(required)}")
        for row in reader:
            if member_id and row["member_id"] != member_id:
                continue
            if paper_ids and row["arxiv_id"] not in paper_ids:
                continue
            tasks.append(row)
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        tasks = tasks[:limit]
    if not tasks:
        raise ValueError("No version tasks remain after applying filters.")

    raw_dir = root / "raw" / "arxiv_sources"
    extracted_dir = root / "corpus" / "tex"
    downloader = ArxivSourceDownloader(
        output_dir=raw_dir, user_agent=user_agent, delay_seconds=delay_seconds,
        timeout=timeout, max_attempts=max_attempts,
    )
    extractor = SafeSourceExtractor(output_dir=extracted_dir)
    run_id = str(uuid4())
    statuses: list[dict[str, Any]] = []
    for task in tasks:
        arxiv_id, versioned_id = task["arxiv_id"], task["versioned_arxiv_id"]
        try:
            download = downloader.download(arxiv_id, versioned_id, resume=resume)
            if download.status != "success":
                statuses.append({
                    "run_id": run_id, "member_id": task["member_id"],
                    "arxiv_id": arxiv_id, "versioned_arxiv_id": versioned_id,
                    "version": int(task["version"]), "status": download.status,
                    "download": asdict(download), "extraction": None,
                })
                continue
            extracted = extractor.extract(
                download.archive_path, arxiv_id=arxiv_id, versioned_arxiv_id=versioned_id,
            )
            statuses.append({
                "run_id": run_id, "member_id": task["member_id"],
                "arxiv_id": arxiv_id, "versioned_arxiv_id": versioned_id,
                "version": int(task["version"]), "status": extracted.status,
                "download": asdict(download), "extraction": asdict(extracted),
            })
        except Exception as exc:  # isolate failures; every expected task gets an audit row
            statuses.append({
                "run_id": run_id, "member_id": task["member_id"],
                "arxiv_id": arxiv_id, "versioned_arxiv_id": versioned_id,
                "version": int(task["version"]), "status": "pipeline_error",
                "error_code": type(exc).__name__, "error_message": str(exc),
                "download": None, "extraction": None,
            })

    manifest = root / "manifests" / "source_status.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for status in statuses:
            handle.write(json.dumps(status, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(manifest)
    counts: dict[str, int] = {}
    for row in statuses:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    summary = {
        "run_id": run_id, "expected_version_tasks": len(tasks),
        "terminal_status_records": len(statuses), "status_counts": dict(sorted(counts.items())),
        "source_status_manifest": str(manifest),
        "archive_bytes": sum((r.get("download") or {}).get("archive_bytes", 0) for r in statuses),
        "filtered_tex_bib_bytes": sum((r.get("extraction") or {}).get("filtered_bytes", 0) for r in statuses),
    }
    summary_path = root / "manifests" / "source_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return summary
