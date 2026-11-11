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
    missing_only: bool = False,
    retry_failures_only: bool = False,
) -> dict[str, Any]:
    """Download/extract all selected version tasks; always emit one status per task."""
    if missing_only and retry_failures_only:
        raise ValueError("missing_only and retry_failures_only are mutually exclusive")
    tasks_path, root = Path(version_tasks_csv), Path(data_dir)
    if not tasks_path.is_file():
        raise FileNotFoundError(f"Missing version task manifest: {tasks_path}")
    all_tasks: list[dict[str, str]] = []
    tasks: list[dict[str, str]] = []
    with tasks_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"member_id", "arxiv_id", "versioned_arxiv_id", "version"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"version_tasks.csv must contain columns: {sorted(required)}")
        for row in reader:
            all_tasks.append(row)
            if member_id and row["member_id"] != member_id:
                continue
            if paper_ids and row["arxiv_id"] not in paper_ids:
                continue
            tasks.append(row)
    if not tasks:
        raise ValueError("No version tasks remain after applying filters.")

    manifest = root / "manifests" / "source_status.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    persisted = _load_status_manifest(manifest)
    candidate_task_count = len(tasks)
    if missing_only:
        tasks = [
            task for task in tasks
            if task["versioned_arxiv_id"] not in persisted
        ]
        selection_mode = "missing_only"
    elif retry_failures_only:
        tasks = [
            task for task in tasks
            if task["versioned_arxiv_id"] in persisted
            and persisted[task["versioned_arxiv_id"]].get("status")
            not in {"success", "no_tex_bib"}
        ]
        selection_mode = "retry_failures_only"
    else:
        selection_mode = "all"
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        tasks = tasks[:limit]

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
                persisted[_status_key(statuses[-1])] = statuses[-1]
                _write_status_manifest(manifest, persisted.values())
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
        persisted[_status_key(statuses[-1])] = statuses[-1]
        _write_status_manifest(manifest, persisted.values())
    counts: dict[str, int] = {}
    for row in statuses:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    run_summary = {
        "run_id": run_id, "expected_version_tasks": len(tasks),
        "candidate_version_tasks": candidate_task_count,
        "skipped_version_tasks": candidate_task_count - len(tasks),
        "selection_mode": selection_mode,
        "terminal_status_records": len(statuses), "status_counts": dict(sorted(counts.items())),
        "manifest_status_records": len(persisted),
        "source_status_manifest": str(Path("manifests") / manifest.name),
        "archive_bytes": sum((r.get("download") or {}).get("archive_bytes", 0) for r in statuses),
        "filtered_tex_bib_bytes": sum((r.get("extraction") or {}).get("filtered_bytes", 0) for r in statuses),
    }
    run_summary_path = root / "manifests" / "source_last_run_summary.json"
    _write_json_atomic(run_summary_path, run_summary)

    aggregate_summary = _build_aggregate_summary(
        version_tasks=all_tasks,
        persisted=persisted,
        manifest=manifest,
    )
    summary_path = root / "manifests" / "source_summary.json"
    _write_json_atomic(summary_path, aggregate_summary)
    return run_summary


def _build_aggregate_summary(
    *,
    version_tasks: list[dict[str, str]],
    persisted: dict[str, dict[str, Any]],
    manifest: Path,
) -> dict[str, Any]:
    """Build a deterministic whole-manifest summary, independent of run mode."""
    task_keys = {_status_key(task) for task in version_tasks}
    matched = [persisted[key] for key in sorted(task_keys & persisted.keys())]
    unexpected_keys = sorted(persisted.keys() - task_keys)
    missing_keys = sorted(task_keys - persisted.keys())

    counts: dict[str, int] = {}
    member_tasks: dict[str, int] = {}
    member_rows: dict[str, list[dict[str, Any]]] = {}
    for task in version_tasks:
        member = str(task.get("member_id") or "unknown")
        member_tasks[member] = member_tasks.get(member, 0) + 1
    for row in matched:
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
        member = str(row.get("member_id") or "unknown")
        member_rows.setdefault(member, []).append(row)

    members: dict[str, dict[str, Any]] = {}
    for member in sorted(set(member_tasks) | set(member_rows)):
        rows = member_rows.get(member, [])
        status_counts: dict[str, int] = {}
        for row in rows:
            status = str(row.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        expected = member_tasks.get(member, 0)
        members[member] = {
            "expected_version_tasks": expected,
            "terminal_status_records": len(rows),
            "missing_status_records": max(0, expected - len(rows)),
            "status_counts": dict(sorted(status_counts.items())),
        }

    expected_total = len(version_tasks)
    terminal_total = len(matched)
    return {
        "summary_scope": "entire_version_task_manifest",
        "version_tasks_total": expected_total,
        "terminal_status_records": terminal_total,
        "missing_status_records": len(missing_keys),
        "unexpected_status_records": len(unexpected_keys),
        "coverage_rate": terminal_total / expected_total if expected_total else 1.0,
        "status_counts": dict(sorted(counts.items())),
        "archive_bytes": sum(
            int((row.get("download") or {}).get("archive_bytes") or 0)
            for row in matched
        ),
        "filtered_tex_bib_bytes": sum(
            int((row.get("extraction") or {}).get("filtered_bytes") or 0)
            for row in matched
        ),
        "source_status_manifest": str(Path("manifests") / manifest.name),
        "members": members,
        "missing_versioned_arxiv_ids": missing_keys,
        "unexpected_versioned_arxiv_ids": unexpected_keys,
    }


def _status_key(row: dict[str, Any]) -> str:
    versioned_id = str(row.get("versioned_arxiv_id") or "").strip()
    if not versioned_id:
        raise ValueError("source status is missing versioned_arxiv_id")
    return versioned_id


def _load_status_manifest(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid source status JSONL at line {line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"source status row {line_number} is not an object")
        key = _status_key(row)
        if key in rows:
            raise ValueError(f"duplicate source status for {key}")
        rows[key] = row
    return rows


def _write_status_manifest(path: Path, rows: Any) -> None:
    ordered = sorted(
        rows,
        key=lambda row: (
            str(row.get("member_id") or ""),
            str(row.get("arxiv_id") or ""),
            int(row.get("version") or 0),
        ),
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in ordered:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        import os
        os.fsync(handle.fileno())
    temporary.replace(path)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        handle.flush()
        import os
        os.fsync(handle.fileno())
    temporary.replace(path)
