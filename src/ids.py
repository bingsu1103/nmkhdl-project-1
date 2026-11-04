"""Read, validate, expand, and checksum assigned arXiv ranges."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .contracts import AssignedRange, OwnedPaper

EXPECTED_COLUMNS = (
    "member_id",
    "start_month",
    "start_id",
    "end_month",
    "end_id",
)
DEFAULT_MEMBER_IDS = tuple(f"member-{index}" for index in range(1, 6))
MONTH_PATTERN = re.compile(r"^(?P<year>\d{4})-(?P<month>0[1-9]|1[0-2])$")


class RangeValidationError(ValueError):
    """Raised when an assigned-range file is invalid or ambiguous."""


@dataclass(frozen=True, slots=True)
class RangeConvention:
    """Lab-specific rules that must be explicit before range expansion."""

    inclusive_end: bool | None = None
    id_width: int = 5

    def validate(self) -> None:
        if self.inclusive_end is None:
            raise RangeValidationError(
                "Range convention is incomplete: confirm whether end_id is inclusive."
            )
        if self.id_width <= 0:
            raise RangeValidationError("id_width must be a positive integer.")


def read_assigned_ranges(
    path: str | Path,
    *,
    expected_member_ids: Sequence[str] = DEFAULT_MEMBER_IDS,
    allow_partial: bool = False,
) -> list[AssignedRange]:
    """Read range rows as strings so leading zeroes are never discarded."""

    source = Path(path)
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
                raise RangeValidationError(
                    "assigned range CSV must have exactly these columns in order: "
                    + ",".join(EXPECTED_COLUMNS)
                )
            rows = [
                AssignedRange(**{column: (row[column] or "").strip() for column in EXPECTED_COLUMNS})
                for row in reader
            ]
    except OSError as exc:
        raise RangeValidationError(f"Cannot read assigned range file: {source}") from exc

    validate_ranges(
        rows,
        expected_member_ids=expected_member_ids,
        allow_partial=allow_partial,
    )
    return rows


def validate_ranges(
    ranges: Sequence[AssignedRange],
    *,
    expected_member_ids: Sequence[str] = DEFAULT_MEMBER_IDS,
    allow_partial: bool = False,
) -> None:
    if not ranges:
        raise RangeValidationError("Assigned range file is empty.")

    members = [item.member_id for item in ranges]
    if len(set(members)) != len(members):
        raise RangeValidationError("Each member_id must appear exactly once.")

    expected = set(expected_member_ids)
    actual = set(members)
    unknown = actual - expected
    if unknown:
        raise RangeValidationError(f"Unknown member IDs: {sorted(unknown)}")
    if not allow_partial and actual != expected:
        missing = expected - actual
        raise RangeValidationError(f"Missing assigned ranges for: {sorted(missing)}")

    for item in ranges:
        _validate_month(item.start_month, field="start_month", member=item.member_id)
        _validate_month(item.end_month, field="end_month", member=item.member_id)
        _validate_numeric_id(item.start_id, field="start_id", member=item.member_id)
        _validate_numeric_id(item.end_id, field="end_id", member=item.member_id)
        if (item.start_month, int(item.start_id)) > (
            item.end_month,
            int(item.end_id),
        ):
            raise RangeValidationError(f"Range is reversed for {item.member_id}.")

    _validate_same_month_overlaps(ranges)


def expand_ranges(
    ranges: Sequence[AssignedRange],
    *,
    convention: RangeConvention,
) -> list[OwnedPaper]:
    """Expand same-month ranges after the lab's boundary rule is explicit.

    Cross-month expansion is deliberately rejected until the lab specifies the
    valid ID ceiling for each month. Failing is safer than inventing IDs.
    """

    convention.validate()
    validate_ranges(ranges, expected_member_ids=tuple(r.member_id for r in ranges))

    owned: list[OwnedPaper] = []
    for item in sorted(ranges, key=lambda value: value.member_id):
        if item.start_month != item.end_month:
            raise RangeValidationError(
                f"Cross-month range for {item.member_id} needs a lab-approved "
                "monthly ID ceiling before it can be expanded."
            )
        if len(item.start_id) != convention.id_width or len(item.end_id) != convention.id_width:
            raise RangeValidationError(
                f"{item.member_id} IDs must contain exactly {convention.id_width} digits."
            )

        stop = int(item.end_id) + (1 if convention.inclusive_end else 0)
        prefix = _arxiv_month_prefix(item.start_month)
        for numeric_id in range(int(item.start_id), stop):
            owned.append(
                OwnedPaper(
                    member_id=item.member_id,
                    arxiv_id=f"{prefix}.{numeric_id:0{convention.id_width}d}",
                )
            )
    return owned


def ranges_sha256(ranges: Iterable[AssignedRange]) -> str:
    canonical = [asdict(item) for item in sorted(ranges, key=lambda value: value.member_id)]
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def owned_papers_sha256(papers: Iterable[OwnedPaper]) -> str:
    canonical = [asdict(item) for item in papers]
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_owned_papers(path: str | Path, papers: Sequence[OwnedPaper]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("member_id", "arxiv_id"))
        writer.writeheader()
        for item in papers:
            writer.writerow(asdict(item))
    temporary.replace(destination)


def _validate_month(value: str, *, field: str, member: str) -> None:
    if not MONTH_PATTERN.fullmatch(value):
        raise RangeValidationError(
            f"{field} for {member} must use YYYY-MM with a valid month."
        )


def _validate_numeric_id(value: str, *, field: str, member: str) -> None:
    if not value or not value.isascii() or not value.isdigit():
        raise RangeValidationError(f"{field} for {member} must contain ASCII digits only.")


def _validate_same_month_overlaps(ranges: Sequence[AssignedRange]) -> None:
    by_month: dict[str, list[tuple[int, int, str]]] = {}
    for item in ranges:
        if item.start_month == item.end_month:
            by_month.setdefault(item.start_month, []).append(
                (int(item.start_id), int(item.end_id), item.member_id)
            )
    for month, intervals in by_month.items():
        ordered = sorted(intervals)
        for previous, current in zip(ordered, ordered[1:]):
            if current[0] <= previous[1]:
                raise RangeValidationError(
                    f"Overlapping ranges in {month}: {previous[2]} and {current[2]}."
                )


def _arxiv_month_prefix(value: str) -> str:
    match = MONTH_PATTERN.fullmatch(value)
    if match is None:  # Defensive; callers normally validate first.
        raise RangeValidationError(f"Invalid month: {value}")
    return f"{match.group('year')[-2:]}{match.group('month')}"
