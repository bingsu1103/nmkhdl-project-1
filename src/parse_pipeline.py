"""Checkpointed M2 parsing orchestration and cross-version element deduplication."""

from __future__ import annotations

import hashlib
import gzip
import io
import json
from collections import Counter
from contextlib import contextmanager
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

    checkpoint_specs: list[tuple[Path, str, bool]] = []
    resumed_count = 0
    for item in inputs:
        checkpoint_fingerprint = _checkpoint_fingerprint(item.source_fingerprint)
        checkpoint = (
            root
            / "checkpoints"
            / "parsing"
            / item.arxiv_id
            / f"{item.versioned_arxiv_id}.json.gz"
        )
        cached = (
            _load_checkpoint_with_legacy_fallback(
                checkpoint, expected_fingerprint=checkpoint_fingerprint
            )
            if resume
            else None
        )
        if cached is not None:
            resumed_count += 1
            was_resumed = True
        else:
            result = _parse_input(root, item.to_dict())
            was_resumed = False
            _write_json_gzip_atomic(
                checkpoint,
                {
                    "parser_schema_version": PARSER_SCHEMA_VERSION,
                    "input_fingerprint": checkpoint_fingerprint,
                    "result": result,
                },
            )
        checkpoint_specs.append((checkpoint, checkpoint_fingerprint, was_resumed))

    out = root / "parsed"
    out.mkdir(parents=True, exist_ok=True)
    assembly = _assemble_checkpoints_streaming(checkpoint_specs, out)
    status_counts = assembly["status_counts"]
    kind_counts = assembly["kind_counts"]
    summary = {
        "parser_schema_version": PARSER_SCHEMA_VERSION,
        "contract_reconciliation": reconciliation,
        "version_count": len(checkpoint_specs),
        "resumed_versions": resumed_count,
        "parsed_success": status_counts["success"],
        "empty_no_tex_bib": status_counts["no_tex_bib"],
        "failed_or_partial": sum(
            count
            for status, count in status_counts.items()
            if status not in {"success", "no_tex_bib"}
        ),
        "status_counts": dict(sorted(status_counts.items())),
        "elements_distinct": assembly["elements_distinct"],
        "hierarchy_edges": assembly["hierarchy_edges"],
        "deduplicated_nodes": assembly["deduplicated_nodes"],
        "kind_counts": dict(sorted(kind_counts.items())),
        "output_dir": "parsed",
    }
    _write_json_atomic(out / "parse_summary.json", summary)
    return summary


def _assemble_checkpoints_streaming(
    checkpoint_specs: list[tuple[Path, str, bool]], out: Path
) -> dict[str, Any]:
    """Assemble gzip JSONL without retaining full checkpoint payloads in RAM."""
    targets = {
        "elements": out / "elements.jsonl.gz",
        "hierarchy": out / "hierarchy.jsonl.gz",
        "status": out / "parse_status.jsonl.gz",
    }
    temporary = {name: path.with_suffix(path.suffix + ".tmp") for name, path in targets.items()}
    seen_elements: set[str] = set()
    status_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    occurrences = 0
    hierarchy_edges = 0
    seen_version_children: set[tuple[str, int, str]] = set()
    status_keys = (
        "member_id", "arxiv_id", "versioned_arxiv_id", "version", "status",
        "input_status", "source_stage_status", "source_fingerprint",
        "reachable_files", "unused_tex_files", "diagnostics",
    )

    with _deterministic_gzip_text_writer(temporary["elements"]) as elements_out, \
         _deterministic_gzip_text_writer(temporary["hierarchy"]) as hierarchy_out, \
         _deterministic_gzip_text_writer(temporary["status"]) as status_out:
        for checkpoint, fingerprint, was_resumed in checkpoint_specs:
            result = _load_checkpoint_with_legacy_fallback(
                checkpoint, expected_fingerprint=fingerprint
            )
            if result is None:
                raise ValueError(f"Missing or invalid parsing checkpoint: {checkpoint}")
            status_counts[result["status"]] += 1
            status_row = {key: result[key] for key in status_keys}
            status_row["resumed"] = was_resumed
            status_out.write(json.dumps(status_row, ensure_ascii=False, sort_keys=True) + "\n")

            local_ids: dict[str, str] = {}
            nodes = [Element(**payload) for payload in result["elements"]]
            for node in nodes:
                occurrences += 1
                final_kind = FINAL_KIND_MAP.get(node.kind, node.kind)
                element_id = _content_element_id(result["arxiv_id"], final_kind, node.content)
                local_ids[node.element_id] = element_id
                if element_id in seen_elements:
                    continue
                seen_elements.add(element_id)
                kind_counts[final_kind] += 1
                elements_out.write(json.dumps({
                    "element_id": element_id,
                    "arxiv_id": result["arxiv_id"],
                    "kind": final_kind,
                    "content": node.content,
                }, ensure_ascii=False, sort_keys=True) + "\n")
            for node in nodes:
                if node.parent_id is None:
                    continue
                child_key = (
                    result["arxiv_id"], int(result["version"]), local_ids[node.element_id]
                )
                if child_key in seen_version_children:
                    continue
                seen_version_children.add(child_key)
                hierarchy_edges += 1
                hierarchy_out.write(json.dumps({
                    "arxiv_id": result["arxiv_id"],
                    "version": int(result["version"]),
                    "element_id": local_ids[node.element_id],
                    "parent_id": local_ids[node.parent_id],
                }, ensure_ascii=False, sort_keys=True) + "\n")

    for name, path in targets.items():
        temporary[name].replace(path)
    return {
        "status_counts": status_counts,
        "kind_counts": kind_counts,
        "elements_distinct": len(seen_elements),
        "hierarchy_edges": hierarchy_edges,
        "deduplicated_nodes": occurrences - len(seen_elements),
    }


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
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, EOFError, json.JSONDecodeError):
        return None
    if (
        payload.get("parser_schema_version") != PARSER_SCHEMA_VERSION
        or payload.get("input_fingerprint") != expected_fingerprint
        or not isinstance(payload.get("result"), dict)
    ):
        return None
    return payload["result"]


def _load_checkpoint_with_legacy_fallback(
    compressed_path: Path, *, expected_fingerprint: str
) -> dict[str, Any] | None:
    cached = _load_checkpoint(
        compressed_path, expected_fingerprint=expected_fingerprint
    )
    if cached is not None:
        return cached
    legacy_path = compressed_path.with_suffix("")
    return _load_checkpoint(legacy_path, expected_fingerprint=expected_fingerprint)


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


def _write_jsonl_gzip_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


@contextmanager
def _deterministic_gzip_text_writer(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8") as handle:
                yield handle


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        handle.flush()
        import os
        os.fsync(handle.fileno())
    temporary.replace(path)


def _write_json_gzip_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
    temporary.replace(path)
