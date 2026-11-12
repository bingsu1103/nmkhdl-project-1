"""Command-line interface for the shared arXiv pipeline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import time
from pathlib import Path

from .arxiv_client import DiscoveryError, InMemoryArxivClient, LiveArxivClient
from .checkpoint import JsonCheckpointStore, write_events_jsonl
from .contracts import OwnedPaper, PaperMetadata, StageStatus
from .discovery_output import write_discovery_outputs
from .m1_integration import (
    Milestone1IntegrationError,
    build_m1_tables,
    validate_source_completeness,
    validate_m1_tables,
)
from .metrics import ResourceMonitor, generate_benchmark_summary
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
from .source_pipeline import run_source_pipeline
from .storage import PAPERS_SCHEMA, REFERENCES_SCHEMA, read_sharded_parquet
from .validate import compute_crawl_statistics
from .parse_pipeline import run_parse_pipeline
from .bibtex import run_bibtex_stage
from .m2_contracts import ParsingContractError
from .m2_integration import (
    Milestone2IntegrationError,
    build_m2_tables,
    validate_m2_tables,
)
from .s2_client import (
    DONE_STATUSES,
    crawl_references,
    load_raw_references,
    summarize_s2_crawl,
)

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
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
    validate.add_argument(
        "--month-ceiling",
        action="append",
        default=[],
        metavar="YYYY-MM=NNNNN",
        help="Explicit last valid ID for a non-final month in a cross-month range.",
    )
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

    sources = subparsers.add_parser(
        "crawl-sources",
        help="Download versioned arXiv source and safely extract .tex/.bib files.",
    )
    sources.add_argument("--data-dir", type=Path, required=True)
    sources.add_argument("--user-agent", required=True)
    sources.add_argument("--member")
    sources.add_argument("--paper", action="append", default=[])
    sources.add_argument("--limit", type=int)
    sources.add_argument("--delay-seconds", type=float, default=3.0)
    sources.add_argument("--connect-timeout", type=float, default=10.0)
    sources.add_argument("--read-timeout", type=float, default=60.0)
    sources.add_argument("--max-attempts", type=int, default=4)
    sources.add_argument("--no-resume", action="store_true")
    source_selection = sources.add_mutually_exclusive_group()
    source_selection.add_argument(
        "--missing-only",
        action="store_true",
        help="Process only version tasks without an existing source status record.",
    )
    source_selection.add_argument(
        "--retry-failures-only",
        action="store_true",
        help="Retry only existing source statuses other than success/no_tex_bib.",
    )
    sources.set_defaults(handler=_crawl_sources)

    parse_sources = subparsers.add_parser(
        "parse-sources",
        help="Deprecated alias for the M2 parse command.",
    )
    _add_m2_parse_arguments(parse_sources)
    parse_sources.set_defaults(handler=_parse_sources)

    parse = subparsers.add_parser(
        "parse",
        help="Run reconciled, checkpointed Milestone 2 hierarchical parsing.",
    )
    _add_m2_parse_arguments(parse)
    parse.set_defaults(handler=_parse_sources)

    build_parsing_tables = subparsers.add_parser(
        "build-parsing-tables",
        help="Build elements/hierarchy/bibtex Parquet tables from M2 adapter outputs.",
    )
    build_parsing_tables.add_argument("--data-dir", type=Path, required=True)
    build_parsing_tables.set_defaults(handler=_build_parsing_tables)

    validate_parsing = subparsers.add_parser(
        "validate-parsing",
        help="Validate M2 schemas, hierarchy integrity, deduplication and coverage.",
    )
    validate_parsing.add_argument("--data-dir", type=Path, required=True)
    validate_parsing.set_defaults(handler=_validate_parsing)

    standardize = subparsers.add_parser(
        "standardize",
        help="Extract, normalize and deduplicate BibTeX across parsed versions.",
    )
    standardize.add_argument("--data-dir", type=Path, required=True)
    standardize.set_defaults(handler=_standardize_parsing)

    run_parsing = subparsers.add_parser(
        "run-parsing",
        help="Run M2 parse, standardize, table build and validation gates.",
    )
    _add_m2_parse_arguments(run_parsing)
    run_parsing.set_defaults(handler=_run_parsing)

    benchmark_parsing = subparsers.add_parser(
        "benchmark-parsing",
        help="Benchmark M2 parsing on existing M1 sources with resource monitoring.",
    )
    _add_m2_parse_arguments(benchmark_parsing)
    benchmark_parsing.add_argument("--monitor-interval-seconds", type=float, default=0.5)
    benchmark_parsing.add_argument("--disk-interval-seconds", type=float, default=2.0)
    benchmark_parsing.set_defaults(handler=_benchmark_parsing)

    references = subparsers.add_parser(
        "crawl-references",
        help="Crawl Semantic Scholar references for owned base arXiv IDs.",
    )
    references.add_argument("--owned-papers", type=Path, required=True)
    references.add_argument("--data-dir", type=Path, required=True)
    references.add_argument("--member")
    references.add_argument("--paper", action="append", default=[])
    references.add_argument("--limit", type=int)
    references.add_argument("--max-attempts", type=int, default=4)
    references.add_argument("--timeout-seconds", type=float, default=30.0)
    references.set_defaults(handler=_crawl_references)

    build_tables = subparsers.add_parser(
        "build-tables",
        help="Build M1 papers/references Parquet tables from completed artifacts.",
    )
    build_tables.add_argument("--data-dir", type=Path, required=True)
    build_tables.set_defaults(handler=_build_tables)

    validate = subparsers.add_parser(
        "validate",
        help="Validate M1 tables and reconcile them against the owned manifest.",
    )
    validate.add_argument("--owned-papers", type=Path, required=True)
    validate.add_argument("--data-dir", type=Path, required=True)
    validate.add_argument("--member")
    validate.set_defaults(handler=_validate_m1)

    run_all = subparsers.add_parser(
        "run-all",
        help="Run all Milestone 1 stages with resume and release gates.",
    )
    _add_m1_workflow_arguments(run_all)
    run_all.set_defaults(handler=_run_all, benchmark_mode=False)

    benchmark = subparsers.add_parser(
        "benchmark",
        help="Run Milestone 1 end-to-end in a clean data directory with resource monitoring.",
    )
    _add_m1_workflow_arguments(benchmark)
    benchmark.set_defaults(handler=_run_all, benchmark_mode=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (
        DiscoveryError,
        Milestone1IntegrationError,
        Milestone2IntegrationError,
        ParsingContractError,
        RangeValidationError,
        VersionResolutionError,
        OSError,
        ValueError,
    ) as exc:
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
        monthly_id_ceilings = _parse_month_ceilings(args.month_ceiling)
        papers = expand_ranges(
            ranges,
            convention=RangeConvention(
                inclusive_end=inclusive_end,
                monthly_id_ceilings=monthly_id_ceilings,
            ),
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


def _add_m1_workflow_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--owned-papers", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--member")
    parser.add_argument("--paper", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--delay-seconds", type=float, default=3.0)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--read-timeout", type=float, default=60.0)
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--monitor-interval-seconds", type=float, default=0.5)
    parser.add_argument("--disk-interval-seconds", type=float, default=2.0)


def _add_m2_parse_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--member")
    parser.add_argument("--paper", action="append", default=[])
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore parsing checkpoints and recompute every selected version.",
    )


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
    data_dir = _external_data_dir(args.data_dir)
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


def _crawl_sources(args: argparse.Namespace) -> int:
    data_dir = _external_data_dir(args.data_dir)
    summary = run_source_pipeline(
        version_tasks_csv=data_dir / "manifests" / "discovery" / "version_tasks.csv",
        data_dir=data_dir,
        user_agent=args.user_agent,
        member_id=args.member,
        paper_ids=set(args.paper) if args.paper else None,
        limit=args.limit,
        delay_seconds=args.delay_seconds,
        timeout=(args.connect_timeout, args.read_timeout),
        max_attempts=args.max_attempts,
        resume=not args.no_resume,
        missing_only=args.missing_only,
        retry_failures_only=args.retry_failures_only,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    failed = sum(
        count for status, count in summary["status_counts"].items()
        if status != "success" and status != "no_tex_bib"
    )
    return EXIT_OK if failed == 0 else EXIT_PARTIAL_FAILURE


def _parse_sources(args: argparse.Namespace) -> int:
    data_dir = _external_data_dir(args.data_dir)
    summary = run_parse_pipeline(
        data_dir=data_dir,
        member_id=args.member,
        paper_ids=set(args.paper),
        resume=not args.no_resume,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return EXIT_OK if summary["failed_or_partial"] == 0 else EXIT_PARTIAL_FAILURE


def _build_parsing_tables(args: argparse.Namespace) -> int:
    summary = build_m2_tables(data_dir=_external_data_dir(args.data_dir))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return EXIT_OK


def _standardize_parsing(args: argparse.Namespace) -> int:
    summary = run_bibtex_stage(data_dir=_external_data_dir(args.data_dir))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return EXIT_OK


def _run_parsing(args: argparse.Namespace) -> int:
    data_dir = _external_data_dir(args.data_dir)
    result = _run_m2_stages(
        data_dir=data_dir,
        member=args.member,
        paper_ids=set(args.paper),
        resume=not args.no_resume,
    )
    output = data_dir / "manifests/parsing/m2_run_summary.json"
    _write_json_atomic(output, result)
    print(
        json.dumps(
            {**result, "run_summary": str(output)},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return EXIT_OK if result["is_success"] else EXIT_PARTIAL_FAILURE


def _validate_parsing(args: argparse.Namespace) -> int:
    report = validate_m2_tables(data_dir=_external_data_dir(args.data_dir))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return EXIT_OK if report["is_valid"] else EXIT_PARTIAL_FAILURE


def _benchmark_parsing(args: argparse.Namespace) -> int:
    data_dir = _external_data_dir(args.data_dir)
    monitor = ResourceMonitor(
        data_dir=data_dir,
        interval_sec=args.monitor_interval_seconds,
        disk_interval_sec=args.disk_interval_seconds,
    )
    started = time.monotonic()
    monitor.start()
    try:
        workflow_result = _run_m2_stages(
            data_dir=data_dir,
            member=args.member,
            paper_ids=set(args.paper),
            resume=False,
        )
    finally:
        resources = monitor.stop()
    elapsed = round(time.monotonic() - started, 4)
    publications = len(
        {
            line.get("arxiv_id")
            for line in _read_jsonl_objects(data_dir / "parsed/parse_status.jsonl")
        }
    )
    result = {
        "workflow": workflow_result,
        "performance": {
            **resources,
            "end_to_end_wall_time_sec": elapsed,
            "publication_count": publications,
            "average_time_per_publication_sec": round(
                elapsed / max(1, publications), 4
            ),
        },
    }
    output = data_dir / "metrics/m2_parsing_benchmark.json"
    _write_json_atomic(output, result)
    print(json.dumps({**result, "output": str(output)}, ensure_ascii=False, indent=2, sort_keys=True))
    return EXIT_OK if workflow_result["is_success"] else EXIT_PARTIAL_FAILURE


def _run_m2_stages(
    *,
    data_dir: Path,
    member: str | None,
    paper_ids: set[str],
    resume: bool,
) -> dict[str, object]:
    stage_durations: dict[str, float] = {}
    started = time.monotonic()
    parser_summary = run_parse_pipeline(
        data_dir=data_dir,
        member_id=member,
        paper_ids=paper_ids,
        resume=resume,
    )
    stage_durations["parse_seconds"] = round(time.monotonic() - started, 4)

    stage_started = time.monotonic()
    bibtex_summary = run_bibtex_stage(data_dir=data_dir)
    stage_durations["standardize_seconds"] = round(
        time.monotonic() - stage_started, 4
    )

    stage_started = time.monotonic()
    table_summary = build_m2_tables(data_dir=data_dir)
    validation = validate_m2_tables(data_dir=data_dir)
    stage_durations["tables_and_validation_seconds"] = round(
        time.monotonic() - stage_started, 4
    )
    stage_durations["total_seconds"] = round(time.monotonic() - started, 4)
    return {
        "is_success": parser_summary["failed_or_partial"] == 0
        and bool(validation["is_valid"]),
        "parser": parser_summary,
        "standardization": bibtex_summary,
        "tables": table_summary,
        "validation": validation,
        "stage_durations": stage_durations,
    }


def _crawl_references(args: argparse.Namespace) -> int:
    data_dir = _external_data_dir(args.data_dir)
    if args.limit is not None and args.limit <= 0:
        raise RangeValidationError("--limit must be a positive integer")
    papers = _read_owned_papers(args.owned_papers)
    papers = _filter_owned_papers(
        papers,
        member=args.member,
        selected_ids=set(args.paper),
        limit=args.limit,
    )
    statuses = crawl_references(
        [paper.arxiv_id for paper in papers],
        data_dir / "raw" / "s2",
        max_retries=args.max_attempts,
        timeout=args.timeout_seconds,
    )
    raw_records = load_raw_references(data_dir / "raw" / "s2")
    summary = summarize_s2_crawl(statuses, raw_records)
    summary_path = data_dir / "manifests" / "s2_summary.json"
    _write_json_atomic(summary_path, summary)
    print(json.dumps({**summary, "summary_output": str(summary_path)}, ensure_ascii=False, indent=2))
    return (
        EXIT_OK
        if all(status.get("status") in DONE_STATUSES for status in statuses)
        else EXIT_PARTIAL_FAILURE
    )


def _build_tables(args: argparse.Namespace) -> int:
    data_dir = _external_data_dir(args.data_dir)
    summary = build_m1_tables(
        papers_jsonl=data_dir / "manifests" / "discovery" / "papers.jsonl",
        s2_raw_dir=data_dir / "raw" / "s2",
        output_dir=data_dir / "tables",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return EXIT_OK


def _validate_m1(args: argparse.Namespace) -> int:
    data_dir = _external_data_dir(args.data_dir)
    papers = _filter_owned_papers(
        _read_owned_papers(args.owned_papers),
        member=args.member,
        selected_ids=set(),
        limit=None,
    )
    result = validate_m1_tables(
        tables_dir=data_dir / "tables",
        assigned_ids=[paper.arxiv_id for paper in papers],
        failed_discovery_ids=_failed_discovery_ids(
            data_dir / "manifests" / "discovery" / "discovery_status.jsonl"
        ),
        version_tasks_csv=data_dir / "manifests" / "discovery" / "version_tasks.csv",
        source_status_jsonl=data_dir / "manifests" / "source_status.jsonl",
        member_id=args.member,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return EXIT_OK if result["is_valid"] else EXIT_PARTIAL_FAILURE


def _run_all(args: argparse.Namespace) -> int:
    """Run every Milestone 1 stage and emit auditable metrics and release gates."""

    data_dir = _external_data_dir(args.data_dir)
    selected_papers = _filter_owned_papers(
        _read_owned_papers(args.owned_papers),
        member=args.member,
        selected_ids=set(args.paper),
        limit=args.limit,
    )
    if args.benchmark_mode:
        if args.resume:
            raise RangeValidationError("benchmark requires a clean run; do not use --resume")
        existing = [
            name
            for name in ("raw", "corpus", "manifests", "tables", "metrics", "checkpoints", "events")
            if (data_dir / name).exists()
        ]
        if existing:
            raise RangeValidationError(
                "benchmark requires a clean data directory; existing outputs: "
                + ", ".join(existing)
            )

    monitor = ResourceMonitor(
        data_dir=data_dir,
        interval_sec=args.monitor_interval_seconds,
        disk_interval_sec=args.disk_interval_seconds,
    )
    started = time.monotonic()
    stage_durations: dict[str, float] = {}
    monitor.start()
    discovery_code = EXIT_CONFIG_ERROR
    source_code = EXIT_CONFIG_ERROR
    s2_code = EXIT_CONFIG_ERROR
    source_summary: dict[str, object] = {}
    source_completeness: dict[str, object] = {}
    s2_summary: dict[str, object] = {}
    table_summary: dict[str, object] | None = None
    validation: dict[str, object] | None = None
    crawl_statistics: dict[str, object] | None = None
    try:
        stage_started = time.monotonic()
        discovery_code = _discover(args)
        stage_durations["discovery_seconds"] = round(time.monotonic() - stage_started, 4)

        stage_started = time.monotonic()
        source_summary = run_source_pipeline(
            version_tasks_csv=data_dir / "manifests" / "discovery" / "version_tasks.csv",
            data_dir=data_dir,
            user_agent=args.user_agent,
            member_id=args.member,
            paper_ids=set(args.paper) if args.paper else None,
            limit=None,
            delay_seconds=args.delay_seconds,
            timeout=(args.connect_timeout, args.read_timeout),
            max_attempts=args.max_attempts,
            resume=args.resume,
        )
        stage_durations["source_seconds"] = round(time.monotonic() - stage_started, 4)
        source_failures = sum(
            count
            for status, count in source_summary["status_counts"].items()
            if status not in {"success", "no_tex_bib"}
        )
        source_code = EXIT_OK if source_failures == 0 else EXIT_PARTIAL_FAILURE
        source_completeness = validate_source_completeness(
            version_tasks_csv=data_dir / "manifests" / "discovery" / "version_tasks.csv",
            source_status_jsonl=data_dir / "manifests" / "source_status.jsonl",
            member_id=args.member,
        )

        paper_records = _read_jsonl_objects(
            data_dir / "manifests" / "discovery" / "papers.jsonl"
        )
        successful_ids = [str(row["arxiv_id"]) for row in paper_records]
        if not successful_ids:
            raise Milestone1IntegrationError("Discovery produced no successful papers.")

        stage_started = time.monotonic()
        statuses = crawl_references(
            successful_ids,
            data_dir / "raw" / "s2",
            max_retries=args.max_attempts,
            timeout=args.timeout_seconds,
        )
        raw_records = load_raw_references(data_dir / "raw" / "s2")
        s2_summary = summarize_s2_crawl(statuses, raw_records)
        _write_json_atomic(data_dir / "manifests" / "s2_summary.json", s2_summary)
        stage_durations["semantic_scholar_seconds"] = round(
            time.monotonic() - stage_started, 4
        )
        s2_complete = all(status.get("status") in DONE_STATUSES for status in statuses)
        s2_code = EXIT_OK if s2_complete else EXIT_PARTIAL_FAILURE

        if s2_complete:
            stage_started = time.monotonic()
            table_summary = build_m1_tables(
                papers_jsonl=data_dir / "manifests" / "discovery" / "papers.jsonl",
                s2_raw_dir=data_dir / "raw" / "s2",
                output_dir=data_dir / "tables",
            )
            validation = validate_m1_tables(
                tables_dir=data_dir / "tables",
                assigned_ids=[paper.arxiv_id for paper in selected_papers],
                failed_discovery_ids=_failed_discovery_ids(
                    data_dir / "manifests" / "discovery" / "discovery_status.jsonl"
                ),
                version_tasks_csv=data_dir / "manifests" / "discovery" / "version_tasks.csv",
                source_status_jsonl=data_dir / "manifests" / "source_status.jsonl",
                member_id=args.member,
            )
            papers_table = read_sharded_parquet(data_dir / "tables" / "papers", PAPERS_SCHEMA)
            references_table = read_sharded_parquet(
                data_dir / "tables" / "references", REFERENCES_SCHEMA
            )
            source_rows = _read_jsonl_objects(data_dir / "manifests" / "source_status.jsonl")
            if args.member:
                source_rows = [row for row in source_rows if row.get("member_id") == args.member]
            crawl_statistics = compute_crawl_statistics(
                assigned_ids=[paper.arxiv_id for paper in selected_papers],
                papers_table=papers_table,
                references_table=references_table,
                source_status_records=source_rows,
                s2_attempted_count=int(s2_summary["s2_citing_papers_attempted"]),
                s2_succeeded_count=int(s2_summary["s2_citing_papers_succeeded"]),
                total_raw_references_count=int(s2_summary["raw_references_total"]),
            )
            stage_durations["tables_and_validation_seconds"] = round(
                time.monotonic() - stage_started, 4
            )
    finally:
        resource_metrics = monitor.stop()

    total_seconds = round(time.monotonic() - started, 4)
    performance_metrics: dict[str, object] = {
        **resource_metrics,
        **stage_durations,
        "total_end_to_end_time_sec": total_seconds,
        "avg_time_per_paper_sec": round(total_seconds / max(1, len(selected_papers)), 4),
        "selected_paper_count": len(selected_papers),
        "benchmark_mode": bool(args.benchmark_mode),
    }
    metrics_path = None
    if crawl_statistics is not None:
        metrics_path = data_dir / "metrics" / "summary.json"
        generate_benchmark_summary(
            stats_crawling=crawl_statistics,
            performance_metrics=performance_metrics,
            output_path=metrics_path,
            git_sha=_git_sha(),
        )

    validation_ok = bool(validation and validation.get("is_valid"))
    succeeded = (
        discovery_code == EXIT_OK
        and source_code == EXIT_OK
        and s2_code == EXIT_OK
        and bool(source_completeness.get("is_complete"))
        and validation_ok
    )
    run_summary: dict[str, object] = {
        "mode": "benchmark" if args.benchmark_mode else "run-all",
        "is_success": succeeded,
        "stage_exit_codes": {
            "discovery": discovery_code,
            "sources": source_code,
            "semantic_scholar": s2_code,
        },
        "source": source_summary,
        "source_completeness": source_completeness,
        "semantic_scholar": s2_summary,
        "tables": table_summary,
        "validation": validation,
        "performance": performance_metrics,
        "metrics_summary": str(metrics_path) if metrics_path else None,
    }
    output_path = data_dir / "manifests" / "m1_run_summary.json"
    _write_json_atomic(output_path, run_summary)
    print(json.dumps({**run_summary, "run_summary": str(output_path)}, ensure_ascii=False, indent=2, sort_keys=True))
    return EXIT_OK if succeeded else EXIT_PARTIAL_FAILURE


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


def _filter_owned_papers(
    papers: list[OwnedPaper],
    *,
    member: str | None,
    selected_ids: set[str],
    limit: int | None,
) -> list[OwnedPaper]:
    if member:
        papers = [paper for paper in papers if paper.member_id == member]
    if selected_ids:
        papers = [paper for paper in papers if paper.arxiv_id in selected_ids]
        missing = selected_ids - {paper.arxiv_id for paper in papers}
        if missing:
            raise RangeValidationError(
                f"Requested --paper IDs are not in the owned manifest: {sorted(missing)}"
            )
    if limit is not None:
        papers = papers[:limit]
    if not papers:
        raise RangeValidationError("No owned papers remain after applying filters")
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


def _parse_month_ceilings(values: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        try:
            month, raw_ceiling = value.split("=", 1)
            ceiling = int(raw_ceiling)
        except (ValueError, TypeError) as exc:
            raise RangeValidationError(
                f"Invalid --month-ceiling {value!r}; expected YYYY-MM=NNNNN"
            ) from exc
        if month in result:
            raise RangeValidationError(f"Duplicate --month-ceiling for {month}")
        result[month] = ceiling
    return result


def _read_jsonl_objects(path: Path) -> list[dict[str, object]]:
    try:
        rows: list[dict[str, object]] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise Milestone1IntegrationError(
                    f"JSONL row {line_number} is not an object: {path}"
                )
            rows.append(row)
        return rows
    except OSError as exc:
        raise Milestone1IntegrationError(f"Cannot read JSONL artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise Milestone1IntegrationError(f"Invalid JSONL artifact: {path}") from exc


def _git_sha() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _external_data_dir(path: Path) -> Path:
    data_dir = path.expanduser().resolve()
    try:
        data_dir.relative_to(Path.cwd().resolve())
    except ValueError:
        return data_dir
    raise RangeValidationError("--data-dir must be outside the tracked repository")


def _failed_discovery_ids(path: Path) -> list[str]:
    if not path.exists():
        return []
    failed: list[str] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("status") != StageStatus.SUCCESS.value:
                failed.append(str(row["arxiv_id"]))
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise Milestone1IntegrationError(f"Invalid discovery status artifact: {path}") from exc
    return failed


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
