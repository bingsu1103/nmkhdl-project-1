"""Command-line interface for the shared arXiv pipeline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from .arxiv_client import InMemoryArxivClient
from .checkpoint import JsonCheckpointStore, write_events_jsonl
from .contracts import OwnedPaper, PaperMetadata, StageStatus
from .ids import (
    RangeConvention,
    RangeValidationError,
    expand_ranges,
    owned_papers_sha256,
    ranges_sha256,
    read_assigned_ranges,
    write_owned_papers,
)
from .version_resolver import VersionResolutionError
from .pipeline import DiscoveryPipeline

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_NOT_IMPLEMENTED = 3
EXIT_PARTIAL_FAILURE = 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arxiv-pipeline",
        description="Reproducible pipeline for the Introduction to Data Science arXiv project.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate-ranges",
        help="Validate assigned ranges and optionally expand them.",
    )
    validate.add_argument("--ranges-file", type=Path, required=True)
    validate.add_argument("--output", type=Path)
    validate.add_argument("--allow-partial", action="store_true")
    boundary = validate.add_mutually_exclusive_group()
    boundary.add_argument("--inclusive-end", action="store_true")
    boundary.add_argument("--exclusive-end", action="store_true")
    validate.set_defaults(handler=_validate_ranges)

    fixture = subparsers.add_parser(
        "fixture-discover",
        help="Run discovery end-to-end with local synthetic metadata and no Internet.",
    )
    fixture.add_argument("--owned-papers", type=Path, required=True)
    fixture.add_argument("--metadata-fixture", type=Path, required=True)
    fixture.add_argument("--checkpoint-dir", type=Path, required=True)
    fixture.add_argument("--events-output", type=Path, required=True)
    fixture.add_argument("--resume", action="store_true")
    fixture.set_defaults(handler=_fixture_discover)

    for name in (
        "discover",
        "crawl-sources",
        "crawl-references",
        "build-tables",
        "validate",
        "benchmark",
        "run-all",
    ):
        command = subparsers.add_parser(name, help=f"{name} (implemented in a later PR).")
        command.set_defaults(handler=_not_implemented)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (RangeValidationError, VersionResolutionError) as exc:
        parser.error(str(exc))
    return EXIT_CONFIG_ERROR


def _validate_ranges(args: argparse.Namespace) -> int:
    ranges = read_assigned_ranges(args.ranges_file, allow_partial=args.allow_partial)
    result: dict[str, object] = {
        "range_count": len(ranges),
        "range_sha256": ranges_sha256(ranges),
        "expanded": False,
    }

    inclusive_end: bool | None = None
    if args.inclusive_end:
        inclusive_end = True
    elif args.exclusive_end:
        inclusive_end = False

    if inclusive_end is not None:
        papers = expand_ranges(
            ranges,
            convention=RangeConvention(inclusive_end=inclusive_end),
        )
        result.update(
            {
                "expanded": True,
                "paper_count": len(papers),
                "papers_sha256": owned_papers_sha256(papers),
            }
        )
        if args.output:
            write_owned_papers(args.output, papers)
            result["output"] = str(args.output)
    elif args.output:
        raise RangeValidationError(
            "Choose --inclusive-end or --exclusive-end before writing expanded IDs."
        )

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return EXIT_OK


def _not_implemented(args: argparse.Namespace) -> int:
    print(f"Command '{args.command}' is intentionally not implemented in Phase 1 scaffold.")
    return EXIT_NOT_IMPLEMENTED


def _fixture_discover(args: argparse.Namespace) -> int:
    papers = _read_owned_papers(args.owned_papers)
    metadata = _read_metadata_fixture(args.metadata_fixture)
    context = _fixture_context(args.owned_papers, args.metadata_fixture)
    pipeline = DiscoveryPipeline(
        InMemoryArxivClient(metadata),
        checkpoint_store=JsonCheckpointStore(args.checkpoint_dir),
    )
    result = pipeline.run(
        papers,
        resume=args.resume,
        checkpoint_context=context,
    )
    write_events_jsonl(args.events_output, result.events)
    counts = {status.value: 0 for status in StageStatus}
    for outcome in result.outcomes:
        counts[outcome.status.value] += 1
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "paper_count": len(result.outcomes),
                "status_counts": counts,
                "events_output": str(args.events_output),
                "checkpoint_context": context,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return EXIT_OK if result.succeeded else EXIT_PARTIAL_FAILURE


def _read_owned_papers(path: Path) -> list[OwnedPaper]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != ("member_id", "arxiv_id"):
                raise RangeValidationError(
                    "owned papers CSV must have exactly: member_id,arxiv_id"
                )
            papers = [
                OwnedPaper(
                    member_id=(row["member_id"] or "").strip(),
                    arxiv_id=(row["arxiv_id"] or "").strip(),
                )
                for row in reader
            ]
    except OSError as exc:
        raise RangeValidationError(f"Cannot read owned papers file: {path}") from exc
    if not papers or any(not item.member_id or not item.arxiv_id for item in papers):
        raise RangeValidationError("owned papers CSV contains an empty or invalid row")
    if len({item.arxiv_id for item in papers}) != len(papers):
        raise RangeValidationError("owned papers CSV contains duplicate arXiv IDs")
    return papers


def _read_metadata_fixture(path: Path) -> dict[str, PaperMetadata]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise RangeValidationError("metadata fixture must be a JSON array")
        records = [
            PaperMetadata(
                **{
                    **item,
                    "authors": tuple(item["authors"]),
                    "revised_dates": tuple(item.get("revised_dates", ())),
                }
            )
            for item in payload
        ]
    except OSError as exc:
        raise RangeValidationError(f"Cannot read metadata fixture: {path}") from exc
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RangeValidationError(f"Invalid metadata fixture: {path}") from exc
    indexed = {record.arxiv_id: record for record in records}
    if len(indexed) != len(records):
        raise RangeValidationError("metadata fixture contains duplicate arXiv IDs")
    return indexed


def _fixture_context(*paths: Path) -> str:
    digest = hashlib.sha256()
    digest.update(b"fixture-discovery-contract-v1\0")
    for path in paths:
        try:
            digest.update(path.read_bytes())
        except OSError as exc:
            raise RangeValidationError(f"Cannot checksum fixture input: {path}") from exc
        digest.update(b"\0")
    return digest.hexdigest()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
