"""Build and validate the three Milestone 2 tables from parser adapters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .storage import (
    BIBTEX_SCHEMA,
    ELEMENTS_SCHEMA,
    HIERARCHY_SCHEMA,
    PAPERS_SCHEMA,
    create_table_from_records,
    read_sharded_parquet,
    write_sharded_parquet,
)
from .validate import (
    validate_bibtex_table,
    validate_elements_table,
    validate_hierarchy_table,
)


class Milestone2IntegrationError(RuntimeError):
    """M2 adapter output is missing or fails an integration gate."""


def build_m2_tables(*, data_dir: str | Path) -> dict[str, Any]:
    root = Path(data_dir)
    parsed = root / "parsed"
    required = {
        "elements": parsed / "elements.jsonl",
        "hierarchy": parsed / "hierarchy.jsonl",
        "bibtex": parsed / "bibtex.jsonl",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        raise Milestone2IntegrationError(
            "M2 table build is blocked by missing adapter output(s): "
            + ", ".join(missing)
            + ". The bibtex adapter belongs to Member 3; do not create placeholder rows."
        )

    schemas = {
        "elements": ELEMENTS_SCHEMA,
        "hierarchy": HIERARCHY_SCHEMA,
        "bibtex": BIBTEX_SCHEMA,
    }
    counts: dict[str, int] = {}
    shards: dict[str, list[str]] = {}
    for name, path in required.items():
        records = _read_jsonl(path)
        table = create_table_from_records(records, schemas[name])
        outputs = write_sharded_parquet(table, root / "tables", name)
        counts[name] = table.num_rows
        shards[name] = [str(output.relative_to(root)) for output in outputs]
    summary = {"row_counts": counts, "shards": shards}
    _write_json_atomic(root / "manifests/parsing/m2_table_summary.json", summary)
    return summary


def validate_m2_tables(*, data_dir: str | Path) -> dict[str, Any]:
    root = Path(data_dir)
    elements = read_sharded_parquet(root / "tables/elements", ELEMENTS_SCHEMA)
    hierarchy = read_sharded_parquet(root / "tables/hierarchy", HIERARCHY_SCHEMA)
    bibtex = read_sharded_parquet(root / "tables/bibtex", BIBTEX_SCHEMA)
    papers = None
    if (root / "tables/papers").is_dir():
        papers = read_sharded_parquet(root / "tables/papers", PAPERS_SCHEMA)

    reports = [
        validate_elements_table(elements, papers_table=papers),
        validate_hierarchy_table(
            hierarchy, elements_table=elements, papers_table=papers
        ),
        validate_bibtex_table(bibtex, papers_table=papers),
    ]
    parse_status = _read_jsonl(root / "parsed/parse_status.jsonl")
    version_keys = {
        (str(row["arxiv_id"]), int(row["version"])) for row in parse_status
    }
    duplicate_statuses = len(parse_status) - len(version_keys)
    result = {
        "is_valid": all(report.is_valid for report in reports)
        and duplicate_statuses == 0,
        "table_reports": {
            report.table_name: report.to_dict() for report in reports
        },
        "version_coverage": {
            "parse_status_records": len(parse_status),
            "unique_publication_versions": len(version_keys),
            "duplicate_status_records": duplicate_statuses,
        },
    }
    _write_json_atomic(root / "tables/m2_validation_report.json", result)
    return result


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing M2 artifact: {path}")
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise Milestone2IntegrationError(
                f"Invalid JSONL in {path} at line {line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise Milestone2IntegrationError(
                f"M2 JSONL row is not an object: {path}:{line_number}"
            )
        rows.append(row)
    return rows


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        handle.flush()
        import os
        os.fsync(handle.fileno())
    temporary.replace(path)
