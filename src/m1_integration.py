"""Milestone 1 integration over Member 1, 3, and 4 public interfaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .normalize import normalize_paper_record
from .s2_client import DONE_STATUSES, build_references_rows, load_raw_references
from .storage import (
    PAPERS_SCHEMA,
    REFERENCES_SCHEMA,
    create_table_from_records,
    read_sharded_parquet,
    write_sharded_parquet,
)
from .validate import (
    reconcile_crawling_counts,
    validate_papers_table,
    validate_references_table,
)


class Milestone1IntegrationError(RuntimeError):
    """A required upstream artifact is absent or invalid."""


def build_m1_tables(
    *,
    papers_jsonl: str | Path,
    s2_raw_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Build the two required M1 Parquet tables from completed upstream outputs."""

    paper_records = [normalize_paper_record(row) for row in _read_jsonl(papers_jsonl)]
    if not paper_records:
        raise Milestone1IntegrationError("Discovery papers manifest is empty.")
    s2_root = Path(s2_raw_dir)
    _require_complete_s2_statuses(
        s2_root,
        expected_ids={str(row["arxiv_id"]) for row in paper_records},
    )
    raw_references = load_raw_references(s2_root)
    reference_rows, duplicate_count = build_references_rows(raw_references)

    papers_table = create_table_from_records(paper_records, PAPERS_SCHEMA)
    references_table = create_table_from_records(reference_rows, REFERENCES_SCHEMA)
    paper_shards = write_sharded_parquet(papers_table, output_dir, "papers")
    reference_shards = write_sharded_parquet(references_table, output_dir, "references")
    summary = {
        "papers_rows": papers_table.num_rows,
        "raw_references_rows": len(raw_references),
        "references_rows": references_table.num_rows,
        "duplicate_references_removed": duplicate_count,
        "paper_shards": [str(path) for path in paper_shards],
        "reference_shards": [str(path) for path in reference_shards],
    }
    _write_json_atomic(Path(output_dir) / "m1_tables_summary.json", summary)
    return summary


def validate_m1_tables(
    *,
    tables_dir: str | Path,
    assigned_ids: list[str],
    failed_discovery_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Run schema, FK, and assigned-ID reconciliation gates for M1 tables."""

    root = Path(tables_dir)
    papers = read_sharded_parquet(root / "papers", PAPERS_SCHEMA)
    references = read_sharded_parquet(root / "references", REFERENCES_SCHEMA)
    papers_report = validate_papers_table(papers)
    references_report = validate_references_table(references, papers_table=papers)
    reconciliation = reconcile_crawling_counts(
        assigned_ids,
        papers,
        failed_discovery_ids or [],
    )
    result = {
        "is_valid": (
            papers_report.is_valid
            and references_report.is_valid
            and reconciliation["is_reconciled"]
        ),
        "papers": papers_report.to_dict(),
        "references": references_report.to_dict(),
        "reconciliation": reconciliation,
    }
    _write_json_atomic(root / "m1_validation_report.json", result)
    return result


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        raise Milestone1IntegrationError(f"Missing JSONL artifact: {source}")
    rows: list[dict[str, Any]] = []
    try:
        for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise Milestone1IntegrationError(
                    f"JSONL row {line_number} is not an object: {source}"
                )
            rows.append(row)
    except json.JSONDecodeError as exc:
        raise Milestone1IntegrationError(f"Invalid JSONL artifact: {source}") from exc
    return rows


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _require_complete_s2_statuses(root: Path, *, expected_ids: set[str]) -> None:
    if not root.exists():
        raise Milestone1IntegrationError(f"Missing Semantic Scholar raw directory: {root}")
    observed: set[str] = set()
    incomplete: list[str] = []
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            status = payload["status"]
            arxiv_id = str(status["arxiv_id"])
            state = str(status["status"])
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise Milestone1IntegrationError(f"Invalid S2 cache artifact: {path}") from exc
        observed.add(arxiv_id)
        if state not in DONE_STATUSES:
            incomplete.append(arxiv_id)
    missing = expected_ids - observed
    unexpected = observed - expected_ids
    if missing or unexpected or incomplete:
        raise Milestone1IntegrationError(
            "Semantic Scholar artifacts are incomplete: "
            f"missing={len(missing)}, unexpected={len(unexpected)}, "
            f"non_terminal={len(incomplete)}"
        )
