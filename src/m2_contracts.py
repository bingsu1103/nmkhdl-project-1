"""Typed and reconciled handoff from Milestone 1 sources to Milestone 2 parsing."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any


PARSER_CONTRACT_VERSION = "m2-input-v1"
EMPTY_SOURCE_STATUSES = {"no_tex_bib"}


class ParsingContractError(ValueError):
    """M1 artifacts cannot be reconciled into a complete M2 input manifest."""


@dataclass(frozen=True, slots=True)
class ParsingInput:
    member_id: str
    arxiv_id: str
    versioned_arxiv_id: str
    version: int
    input_status: str
    source_stage_status: str
    source_dir: str | None
    source_fingerprint: str
    encoding_hint: str = "utf-8-errors-replace"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_parsing_inputs(
    *,
    version_tasks_csv: str | Path,
    source_status_jsonl: str | Path,
    data_dir: str | Path,
    member_id: str | None = None,
    paper_ids: set[str] | None = None,
) -> tuple[list[ParsingInput], dict[str, Any]]:
    """Reconcile every selected version task to exactly one explicit M2 input."""
    root = Path(data_dir)
    tasks = _read_tasks(Path(version_tasks_csv))
    statuses = _read_statuses(Path(source_status_jsonl))
    selected = [
        task
        for task in tasks
        if (member_id is None or task["member_id"] == member_id)
        and (not paper_ids or task["arxiv_id"] in paper_ids)
    ]
    if not selected:
        raise ParsingContractError("No version tasks remain after applying M2 filters.")

    selected_keys = {task["versioned_arxiv_id"] for task in selected}
    missing = sorted(selected_keys - statuses.keys())
    if missing:
        raise ParsingContractError(
            f"M1→M2 handoff is incomplete: {len(missing)} version tasks have no source status; "
            f"examples: {missing[:10]}"
        )

    inputs: list[ParsingInput] = []
    counts: dict[str, int] = {}
    for task in selected:
        status = statuses[task["versioned_arxiv_id"]]
        _assert_same_lineage(task, status)
        source_status = str(status.get("status") or "pipeline_error")
        if source_status == "success":
            input_status = "ready"
            source_dir = str(
                Path("corpus")
                / "tex"
                / task["arxiv_id"]
                / task["versioned_arxiv_id"]
            )
            absolute_source_dir = root / source_dir
            if not absolute_source_dir.is_dir():
                raise ParsingContractError(
                    f"Successful source status has no extracted directory: {source_dir}"
                )
        elif source_status in EMPTY_SOURCE_STATUSES:
            input_status = "empty"
            source_dir = None
        else:
            input_status = "source_unavailable"
            source_dir = None
        counts[input_status] = counts.get(input_status, 0) + 1
        inputs.append(
            ParsingInput(
                member_id=task["member_id"],
                arxiv_id=task["arxiv_id"],
                versioned_arxiv_id=task["versioned_arxiv_id"],
                version=int(task["version"]),
                input_status=input_status,
                source_stage_status=source_status,
                source_dir=source_dir,
                source_fingerprint=_source_fingerprint(status),
            )
        )

    inputs.sort(key=lambda item: (item.member_id, item.arxiv_id, item.version))
    report = {
        "contract_version": PARSER_CONTRACT_VERSION,
        "selected_version_tasks": len(selected),
        "parsing_inputs": len(inputs),
        "missing_source_statuses": 0,
        "input_status_counts": dict(sorted(counts.items())),
        "is_complete": len(inputs) == len(selected),
    }
    return inputs, report


def write_parsing_contract(
    path: str | Path,
    inputs: list[ParsingInput],
    report: dict[str, Any],
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl_atomic(target, [item.to_dict() for item in inputs])
    _write_json_atomic(target.with_name("m2_input_reconciliation.json"), report)


def _read_tasks(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing version task manifest: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"member_id", "arxiv_id", "versioned_arxiv_id", "version"}
        if not required.issubset(reader.fieldnames or []):
            raise ParsingContractError(
                f"version_tasks.csv must contain columns: {sorted(required)}"
            )
        rows = list(reader)
    keys = [row["versioned_arxiv_id"] for row in rows]
    if len(keys) != len(set(keys)):
        raise ParsingContractError("version_tasks.csv contains duplicate versioned IDs")
    return rows


def _read_statuses(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing source status manifest: {path}")
    rows: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ParsingContractError(
                f"Invalid source status JSONL at line {line_number}"
            ) from exc
        key = str(row.get("versioned_arxiv_id") or "")
        if not key:
            raise ParsingContractError(f"Source status line {line_number} has no versioned ID")
        if key in rows:
            raise ParsingContractError(f"Duplicate source status for {key}")
        rows[key] = row
    return rows


def _assert_same_lineage(task: dict[str, str], status: dict[str, Any]) -> None:
    expected = (
        task["member_id"],
        task["arxiv_id"],
        task["versioned_arxiv_id"],
        int(task["version"]),
    )
    actual = (
        str(status.get("member_id") or ""),
        str(status.get("arxiv_id") or ""),
        str(status.get("versioned_arxiv_id") or ""),
        int(status.get("version") or 0),
    )
    if expected != actual:
        raise ParsingContractError(
            f"Version lineage mismatch for {task['versioned_arxiv_id']}: "
            f"task={expected}, source_status={actual}"
        )


def _source_fingerprint(status: dict[str, Any]) -> str:
    extraction = status.get("extraction") or {}
    files = []
    for item in extraction.get("files") or []:
        relative = str(item.get("path") or "")
        posix = PurePosixPath(relative)
        if not relative or posix.is_absolute() or ".." in posix.parts:
            raise ParsingContractError(f"Unsafe extracted source path in manifest: {relative}")
        files.append(
            {
                "path": relative,
                "sha256": str(item.get("sha256") or ""),
                "bytes": int(item.get("bytes") or 0),
            }
        )
    payload = {
        "contract_version": PARSER_CONTRACT_VERSION,
        "versioned_arxiv_id": status.get("versioned_arxiv_id"),
        "status": status.get("status"),
        "archive_sha256": (status.get("download") or {}).get("sha256"),
        "files": sorted(files, key=lambda item: item["path"]),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        import os
        os.fsync(handle.fileno())
    temporary.replace(path)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        handle.flush()
        import os
        os.fsync(handle.fileno())
    temporary.replace(path)
