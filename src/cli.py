"""Command-line interface for the shared arXiv pipeline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from .arxiv_client import DiscoveryError, InMemoryArxivClient, LiveArxivClient
from .checkpoint import JsonCheckpointStore, write_events_jsonl
from .contracts import OwnedPaper, PaperMetadata, StageStatus
from .discovery_output import write_discovery_outputs
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

    discover = subparsers.add_parser(
        "discover",
        help="Resolve assigned base IDs through the live arXiv API.",
    )
    discover.add_argument("--owned-papers", type=Path, required=True)
    discover.add_argument("--data-dir", type=Path, required=True)
    discover.add_argument("--user-agent", required=True)
    discover.add_argument("--member")
    discover.add_argument("--paper", action="append", default=[])
    discover.add_argument("--limit", type=int)
    discover.add_argument("--batch-size", type=int, default=100)
    discover.add_argument("--delay-seconds", type=float, default=3.0)
    discover.add_argument("--timeout-seconds", type=float, default=30.0)
    discover.add_argument("--max-attempts", type=int, default=4)
    discover.add_argument("--resume", action="store_true")
    discover.set_defaults(handler=_discover)

    for name in (
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
    except (DiscoveryError, RangeValidationError, VersionResolutionError) as exc:
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


def _discover(args: argparse.Namespace) -> int:
    data_dir = args.data_dir.expanduser().resolve()
    repo_root = Path.cwd().resolve()
    try:
        data_dir.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise RangeValidationError("--data-dir must be outside the tracked repository")
    if args.limit is not None and args.limit <= 0:
        raise RangeValidationError("--limit must be a positive integer")

    papers = _read_owned_papers(args.owned_papers)
    if args.member:
        papers = [paper for paper in papers if paper.member_id == args.member]
    if args.paper:
        selected_ids = set(args.paper)
        papers = [paper for paper in papers if paper.arxiv_id in selected_ids]
        missing = selected_ids - {paper.arxiv_id for paper in papers}
        if missing:
            raise RangeValidationError(
                f"Requested --paper IDs are not in the owned manifest: {sorted(missing)}"
            )
    if args.limit is not None:
        papers = papers[: args.limit]
    if not papers:
        raise RangeValidationError("No owned papers remain after applying filters")

    context = hashlib.sha256(
        json.dumps(
            {
                "contract": "live-discovery-v1",
                "papers_sha256": owned_papers_sha256(papers),
                "batch_size": args.batch_size,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    client = LiveArxivClient(
        user_agent=args.user_agent,
        cache_dir=data_dir / "raw" / "arxiv_api",
        batch_size=args.batch_size,
        delay_seconds=args.delay_seconds,
        timeout_seconds=args.timeout_seconds,
        max_attempts=args.max_attempts,
    )
    pipeline = DiscoveryPipeline(
        client,
        checkpoint_store=JsonCheckpointStore(data_dir / "checkpoints" / "discovery"),
    )
    result = pipeline.run(
        papers,
        resume=args.resume,
        checkpoint_context=context,
    )
    events_path = data_dir / "events" / "discovery.jsonl"
    write_events_jsonl(events_path, result.events)
    outputs = write_discovery_outputs(data_dir / "manifests" / "discovery", result)
    counts = {status.value: 0 for status in StageStatus}
    for outcome in result.outcomes:
        counts[outcome.status.value] += 1
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "paper_count": len(result.outcomes),
                "status_counts": counts,
                "version_task_count": sum(
                    len(outcome.version_tasks) for outcome in result.outcomes
                ),
                "events_output": str(events_path),
                "summary_output": str(outputs["summary"]),
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
