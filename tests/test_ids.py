from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from src.contracts import AssignedRange
from src.ids import (
    RangeConvention,
    RangeValidationError,
    expand_ranges,
    owned_papers_sha256,
    ranges_sha256,
    read_assigned_ranges,
    validate_ranges,
)


class AssignedRangeTests(unittest.TestCase):
    def test_reads_partial_range_as_strings(self) -> None:
        path = self._csv(
            [["member-1", "2025-09", "00001", "2025-09", "00003"]]
        )
        rows = read_assigned_ranges(path, allow_partial=True)
        self.assertEqual(rows[0].start_id, "00001")

    def test_requires_all_five_members_by_default(self) -> None:
        path = self._csv([["member-1", "2025-09", "16047", "2025-09", "21046"]])
        with self.assertRaisesRegex(RangeValidationError, "Missing assigned ranges"):
            read_assigned_ranges(path)

    def test_rejects_wrong_headers(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "ranges.csv"
        path.write_text("member_id,start_month\nmember-1,2025-09\n", encoding="utf-8")
        with self.assertRaisesRegex(RangeValidationError, "exactly these columns"):
            read_assigned_ranges(path, allow_partial=True)

    def test_rejects_reversed_range(self) -> None:
        rows = [AssignedRange("member-1", "2025-09", "21046", "2025-09", "16047")]
        with self.assertRaisesRegex(RangeValidationError, "reversed"):
            validate_ranges(rows, expected_member_ids=("member-1",))

    def test_rejects_invalid_month(self) -> None:
        rows = [AssignedRange("member-1", "2025-13", "16047", "2025-13", "21046")]
        with self.assertRaisesRegex(RangeValidationError, "YYYY-MM"):
            validate_ranges(rows, expected_member_ids=("member-1",))

    def test_rejects_overlap(self) -> None:
        rows = [
            AssignedRange("member-1", "2025-09", "00001", "2025-09", "00010"),
            AssignedRange("member-2", "2025-09", "00010", "2025-09", "00020"),
        ]
        with self.assertRaisesRegex(RangeValidationError, "Overlapping"):
            validate_ranges(rows, expected_member_ids=("member-1", "member-2"))

    def test_requires_explicit_boundary_convention(self) -> None:
        rows = [AssignedRange("member-1", "2025-09", "00001", "2025-09", "00003")]
        with self.assertRaisesRegex(RangeValidationError, "confirm whether end_id is inclusive"):
            expand_ranges(rows, convention=RangeConvention())

    def test_expands_inclusive_same_month_range(self) -> None:
        rows = [AssignedRange("member-1", "2025-09", "00001", "2025-09", "00003")]
        papers = expand_ranges(rows, convention=RangeConvention(inclusive_end=True))
        self.assertEqual(
            [paper.arxiv_id for paper in papers],
            ["2509.00001", "2509.00002", "2509.00003"],
        )

    def test_rejects_cross_month_without_lab_ceiling(self) -> None:
        rows = [AssignedRange("member-1", "2025-09", "00001", "2025-10", "00003")]
        with self.assertRaisesRegex(RangeValidationError, "Cross-month"):
            expand_ranges(rows, convention=RangeConvention(inclusive_end=True))

    def test_expands_cross_month_with_explicit_ceiling(self) -> None:
        rows = [AssignedRange("member-1", "2025-10", "00003", "2025-11", "00002")]
        papers = expand_ranges(
            rows,
            convention=RangeConvention(
                inclusive_end=True,
                monthly_id_ceilings={"2025-10": 4},
            ),
        )
        self.assertEqual(
            [paper.arxiv_id for paper in papers],
            ["2510.00003", "2510.00004", "2511.00001", "2511.00002"],
        )

    def test_rejects_cross_member_overlap_after_expansion(self) -> None:
        rows = [
            AssignedRange("member-1", "2025-10", "00003", "2025-11", "00002"),
            AssignedRange("member-2", "2025-11", "00002", "2025-11", "00003"),
        ]
        with self.assertRaisesRegex(RangeValidationError, "overlap at 2511.00002"):
            expand_ranges(
                rows,
                convention=RangeConvention(
                    inclusive_end=True,
                    monthly_id_ceilings={"2025-10": 4},
                ),
            )

    def test_checksums_are_deterministic(self) -> None:
        first = AssignedRange("member-1", "2025-09", "00001", "2025-09", "00002")
        second = AssignedRange("member-2", "2025-10", "00003", "2025-10", "00004")
        self.assertEqual(ranges_sha256([first, second]), ranges_sha256([second, first]))
        papers = expand_ranges([first], convention=RangeConvention(inclusive_end=True))
        self.assertEqual(owned_papers_sha256(papers), owned_papers_sha256(papers))

    def _csv(self, rows: list[list[str]]) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "ranges.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("member_id", "start_month", "start_id", "end_month", "end_id"))
            writer.writerows(rows)
        return path


if __name__ == "__main__":
    unittest.main()
