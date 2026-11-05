"""Batch parsing of extracted version sources and cross-version element deduplication."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .latex_parser import Element, parse_latex_version


def run_parse_pipeline(*, data_dir: str | Path, member_id: str | None = None) -> dict[str, Any]:
    root = Path(data_dir)
    source_manifest = root / "manifests" / "source_status.jsonl"
    if not source_manifest.is_file():
        raise FileNotFoundError(f"Missing source status manifest: {source_manifest}")
    records = []
    for line in source_manifest.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if member_id is None or row.get("member_id") == member_id:
                records.append(row)
    if not records:
        raise ValueError("No source status records selected.")

    version_results = []
    for row in records:
        arxiv_id, version = row["arxiv_id"], int(row["version"])
        extraction_status = row["status"]
        if extraction_status == "no_tex_bib":
            version_results.append({
                "arxiv_id": arxiv_id, "version": version, "status": "no_tex_bib",
                "elements": [], "reachable_files": [], "unused_tex_files": [], "diagnostics": [],
            })
        elif extraction_status != "success":
            version_results.append({
                "arxiv_id": arxiv_id, "version": version, "status": "source_unavailable",
                "elements": [], "reachable_files": [], "unused_tex_files": [],
                "diagnostics": [f"source_stage_status:{extraction_status}"],
            })
        else:
            source_dir = root / "corpus" / "tex" / arxiv_id / row["versioned_arxiv_id"]
            parsed = parse_latex_version(source_dir, arxiv_id=arxiv_id, version=version)
            version_results.append({
                "arxiv_id": arxiv_id, "version": version, "status": parsed.status,
                "elements": parsed.elements, "reachable_files": parsed.reachable_files,
                "unused_tex_files": parsed.unused_tex_files, "diagnostics": parsed.diagnostics,
            })

    # Shared element store per publication; hierarchy edges remain version-specific.
    shared: dict[tuple[str, str, str], list[tuple[int, str]]] = {}
    elements_rows: dict[str, dict[str, str]] = {}
    hierarchy_rows: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    next_element_number = 0
    for result in version_results:
        arxiv_id, version = result["arxiv_id"], result["version"]
        status_rows.append({k: result[k] for k in ("arxiv_id", "version", "status", "reachable_files", "unused_tex_files", "diagnostics")})
        nodes: list[Element] = result["elements"]
        local_ids: dict[str, str] = {}
        used_shared_keys: set[tuple[str, str]] = set()
        for node in nodes:
            key = (arxiv_id, node.kind, node.content)
            prior = next((element_id for prior_version, element_id in shared.get(key, []) if prior_version != version), None)
            if prior is not None and key not in used_shared_keys:
                element_id = prior
                used_shared_keys.add(key)
                counters["deduplicated_nodes"] += 1
            else:
                next_element_number += 1
                counters[node.kind] += 1
                element_id = f"{arxiv_id}#e{next_element_number}"
                shared.setdefault(key, []).append((version, element_id))
                elements_rows[element_id] = {
                    "element_id": element_id, "arxiv_id": arxiv_id,
                    "kind": node.kind, "content": node.content,
                }
            local_ids[node.element_id] = element_id
        for node in nodes:
            if node.parent_id is None:
                continue
            hierarchy_rows.append({
                "arxiv_id": arxiv_id, "version": version,
                "element_id": local_ids[node.element_id],
                "parent_id": local_ids[node.parent_id],
            })

    out = root / "parsed"
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out / "elements.jsonl", list(elements_rows.values()))
    _write_jsonl(out / "hierarchy.jsonl", hierarchy_rows)
    _write_jsonl(out / "parse_status.jsonl", status_rows)
    summary = {
        "version_count": len(version_results),
        "parsed_success": sum(r["status"] == "success" for r in version_results),
        "empty_no_tex_bib": sum(r["status"] == "no_tex_bib" for r in version_results),
        "failed_or_partial": sum(r["status"] not in {"success", "no_tex_bib"} for r in version_results),
        "elements_distinct": len(elements_rows),
        "hierarchy_edges": len(hierarchy_rows),
        "deduplicated_nodes": counters["deduplicated_nodes"],
        "kind_counts": {k: v for k, v in counters.items() if k != "deduplicated_nodes"},
        "output_dir": str(out),
    }
    (out / "parse_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return summary


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)
