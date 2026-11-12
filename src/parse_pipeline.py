"""Checkpointed M2 parsing orchestration and cross-version element deduplication."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .latex_parser import Element, parse_latex_version
from .m2_contracts import build_parsing_inputs, write_parsing_contract


PARSER_SCHEMA_VERSION = "m2-parser-v1"
FINAL_KIND_MAP = {
    "block_formula": "formula",
    "list_item": "item",
}


def run_parse_pipeline(
    *,
    data_dir: str | Path,
    member_id: str | None = None,
    paper_ids: set[str] | None = None,
    resume: bool = True,
) -> dict[str, Any]:
    """Parse selected M1 versions with checksum-aware per-version checkpoints."""
    root = Path(data_dir)
    inputs, reconciliation = build_parsing_inputs(
        version_tasks_csv=root / "manifests" / "discovery" / "version_tasks.csv",
        source_status_jsonl=root / "manifests" / "source_status.jsonl",
        data_dir=root,
        member_id=member_id,
        paper_ids=paper_ids,
    )
    parsing_manifest_dir = root / "manifests" / "parsing"
    write_parsing_contract(
        parsing_manifest_dir / "m2_inputs.jsonl", inputs, reconciliation
    )

    version_results: list[dict[str, Any]] = []
    resumed_count = 0
    for item in inputs:
        checkpoint_fingerprint = _checkpoint_fingerprint(item.source_fingerprint)
        checkpoint = (
            root
            / "checkpoints"
            / "parsing"
            / item.arxiv_id
            / f"{item.versioned_arxiv_id}.json"
        )
        cached = (
            _load_checkpoint(checkpoint, expected_fingerprint=checkpoint_fingerprint)
            if resume
            else None
        )
        if cached is not None:
            result = cached
            result["resumed"] = True
            resumed_count += 1
        else:
            result = _parse_input(root, item.to_dict())
            result["resumed"] = False
            _write_json_atomic(
                checkpoint,
                {
                    "parser_schema_version": PARSER_SCHEMA_VERSION,
                    "input_fingerprint": checkpoint_fingerprint,
                    "result": result,
                },
            )
        version_results.append(result)

    elements_rows, hierarchy_rows, deduplicated_nodes = _assemble_tables(
        version_results
    )
    status_rows = [
        {
            key: result[key]
            for key in (
                "member_id",
                "arxiv_id",
                "versioned_arxiv_id",
                "version",
                "status",
                "input_status",
                "source_stage_status",
                "source_fingerprint",
                "reachable_files",
                "unused_tex_files",
                "diagnostics",
                "resumed",
            )
        }
        for result in version_results
    ]

    out = root / "parsed"
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl_atomic(out / "elements.jsonl", elements_rows)
    _write_jsonl_atomic(out / "hierarchy.jsonl", hierarchy_rows)
    _write_jsonl_atomic(out / "parse_status.jsonl", status_rows)

    status_counts = Counter(result["status"] for result in version_results)
    kind_counts = Counter(row["kind"] for row in elements_rows)
    summary = {
        "parser_schema_version": PARSER_SCHEMA_VERSION,
        "contract_reconciliation": reconciliation,
        "version_count": len(version_results),
        "resumed_versions": resumed_count,
        "parsed_success": status_counts["success"],
        "empty_no_tex_bib": status_counts["no_tex_bib"],
        "failed_or_partial": sum(
            count
            for status, count in status_counts.items()
            if status not in {"success", "no_tex_bib"}
        ),
        "status_counts": dict(sorted(status_counts.items())),
        "elements_distinct": len(elements_rows),
        "hierarchy_edges": len(hierarchy_rows),
        "deduplicated_nodes": deduplicated_nodes,
        "kind_counts": dict(sorted(kind_counts.items())),
        "output_dir": "parsed",
    }
    _write_json_atomic(out / "parse_summary.json", summary)
    return summary


def _parse_input(root: Path, item: dict[str, Any]) -> dict[str, Any]:
    common = {
        "member_id": item["member_id"],
        "arxiv_id": item["arxiv_id"],
        "versioned_arxiv_id": item["versioned_arxiv_id"],
        "version": int(item["version"]),
        "input_status": item["input_status"],
        "source_stage_status": item["source_stage_status"],
        "source_fingerprint": item["source_fingerprint"],
    }
    if item["input_status"] == "empty":
        return {
            **common,
            "status": "no_tex_bib",
            "elements": [],
            "reachable_files": [],
            "unused_tex_files": [],
            "diagnostics": [],
        }
    if item["input_status"] == "source_unavailable":
        return {
            **common,
            "status": "source_unavailable",
            "elements": [],
            "reachable_files": [],
            "unused_tex_files": [],
            "diagnostics": [f"source_stage_status:{item['source_stage_status']}"],
        }
    try:
        parsed = parse_latex_version(
            root / str(item["source_dir"]),
            arxiv_id=item["arxiv_id"],
            version=int(item["version"]),
        )
        return {
            **common,
            "status": parsed.status,
            "elements": [asdict(element) for element in parsed.elements],
            "reachable_files": parsed.reachable_files,
            "unused_tex_files": parsed.unused_tex_files,
            "diagnostics": parsed.diagnostics,
        }
    except Exception as exc:  # one bad version must not erase prior work
        return {
            **common,
            "status": "parse_error",
            "elements": [],
            "reachable_files": [],
            "unused_tex_files": [],
            "diagnostics": [f"{type(exc).__name__}:{exc}"],
        }


def _assemble_tables(
    version_results: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, Any]], int]:
    """Assign deterministic content IDs and retain version-specific parent edges."""
    canonical: dict[tuple[str, str, str], str] = {}
    element_payloads: dict[str, dict[str, str]] = {}
    hierarchy: set[tuple[str, int, str, str]] = set()
    occurrences = 0
    for result in version_results:
        local_ids: dict[str, str] = {}
        nodes = [Element(**payload) for payload in result["elements"]]
        for node in nodes:
            occurrences += 1
            final_kind = FINAL_KIND_MAP.get(node.kind, node.kind)
            key = (result["arxiv_id"], final_kind, node.content)
            element_id = canonical.get(key)
            if element_id is None:
                element_id = _content_element_id(*key)
                candidate = {
                    "element_id": element_id,
                    "arxiv_id": result["arxiv_id"],
                    "kind": final_kind,
                    "content": node.content,
                }
                prior = element_payloads.get(element_id)
                if prior is not None and prior != candidate:
                    raise ValueError(f"Deterministic element ID collision: {element_id}")
                canonical[key] = element_id
                element_payloads[element_id] = candidate
            local_ids[node.element_id] = element_id
        for node in nodes:
            if node.parent_id is None:
                continue
            hierarchy.add(
                (
                    result["arxiv_id"],
                    int(result["version"]),
                    local_ids[node.element_id],
                    local_ids[node.parent_id],
                )
            )
    elements = sorted(
        element_payloads.values(), key=lambda row: (row["arxiv_id"], row["element_id"])
    )
    edges = [
        {
            "arxiv_id": arxiv_id,
            "version": version,
            "element_id": element_id,
            "parent_id": parent_id,
        }
        for arxiv_id, version, element_id, parent_id in sorted(hierarchy)
    ]
    return elements, edges, occurrences - len(elements)


def _content_element_id(arxiv_id: str, kind: str, content: str) -> str:
    digest = hashlib.sha256(
        json.dumps([kind, content], ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()[:20]
    return f"{arxiv_id}#{kind[:1]}{digest}"


def _checkpoint_fingerprint(source_fingerprint: str) -> str:
    return hashlib.sha256(
        f"{PARSER_SCHEMA_VERSION}:{source_fingerprint}".encode()
    ).hexdigest()


def _load_checkpoint(
    path: Path, *, expected_fingerprint: str
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        payload.get("parser_schema_version") != PARSER_SCHEMA_VERSION
        or payload.get("input_fingerprint") != expected_fingerprint
        or not isinstance(payload.get("result"), dict)
    ):
        return None
    return payload["result"]


def _write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
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
