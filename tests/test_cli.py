from __future__ import annotations

import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from src.cli import EXIT_NOT_IMPLEMENTED, main


class CliTests(unittest.TestCase):
    def test_validates_partial_ranges_without_expanding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ranges.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(("member_id", "start_month", "start_id", "end_month", "end_id"))
                writer.writerow(("member-1", "2025-09", "16047", "2025-09", "21046"))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["validate-ranges", "--ranges-file", str(path), "--allow-partial"])
            self.assertEqual(code, 0)
            self.assertIn('"expanded": false', output.getvalue())

    def test_future_command_fails_explicitly(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["discover"])
        self.assertEqual(code, EXIT_NOT_IMPLEMENTED)
        self.assertIn("intentionally not implemented", output.getvalue())

    def test_fixture_discovery_runs_end_to_end_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            owned = root / "owned.csv"
            owned.write_text(
                "member_id,arxiv_id\nmember-1,2509.16047\n",
                encoding="utf-8",
            )
            metadata = root / "metadata.json"
            metadata.write_text(
                json.dumps(
                    [
                        {
                            "arxiv_id": "2509.16047",
                            "latest_versioned_id": "2509.16047v2",
                            "title": "Synthetic paper",
                            "authors": ["Example Author"],
                            "submission_date": "2025-09-01",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            events = root / "events.jsonl"
            output = io.StringIO()
            argv = [
                "fixture-discover",
                "--owned-papers",
                str(owned),
                "--metadata-fixture",
                str(metadata),
                "--checkpoint-dir",
                str(root / "checkpoints"),
                "--events-output",
                str(events),
            ]
            with contextlib.redirect_stdout(output):
                first_code = main(argv)
            with contextlib.redirect_stdout(io.StringIO()):
                resumed_code = main([*argv, "--resume"])

            self.assertEqual(first_code, 0)
            self.assertEqual(resumed_code, 0)
            self.assertIn('"success": 1', output.getvalue())
            resumed_event = json.loads(events.read_text(encoding="utf-8").splitlines()[0])
            self.assertTrue(resumed_event["details"]["resumed"])


if __name__ == "__main__":
    unittest.main()
