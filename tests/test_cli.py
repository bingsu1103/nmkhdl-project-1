from __future__ import annotations

import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.arxiv_client import InMemoryArxivClient
from src.cli import EXIT_NOT_IMPLEMENTED, main
from src.contracts import PaperMetadata


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

    def test_expands_cross_month_range_with_explicit_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ranges.csv"
            path.write_text(
                "member_id,start_month,start_id,end_month,end_id\n"
                "member-1,2025-10,00003,2025-11,00002\n",
                encoding="utf-8",
            )
            output_path = Path(directory) / "owned.csv"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "validate-ranges",
                        "--ranges-file",
                        str(path),
                        "--allow-partial",
                        "--inclusive-end",
                        "--month-ceiling",
                        "2025-10=4",
                        "--output",
                        str(output_path),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(len(output_path.read_text(encoding="utf-8").splitlines()), 5)

    def test_future_commands_fail_explicitly(self) -> None:
        for command in ("benchmark", "run-all"):
            with self.subTest(command=command):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = main([command])
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

    def test_live_discover_command_writes_handoff_using_mock_client(self) -> None:
        metadata = PaperMetadata(
            arxiv_id="2509.16047",
            latest_versioned_id="2509.16047v2",
            title="Synthetic paper",
            authors=("Example Author",),
            submission_date="2025-09-01",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            owned = root / "owned.csv"
            owned.write_text(
                "member_id,arxiv_id\nmember-1,2509.16047\n",
                encoding="utf-8",
            )
            data_dir = root / "external-data"
            output = io.StringIO()
            with mock.patch(
                "src.cli.LiveArxivClient",
                return_value=InMemoryArxivClient({metadata.arxiv_id: metadata}),
            ):
                with contextlib.redirect_stdout(output):
                    code = main(
                        [
                            "discover",
                            "--owned-papers",
                            str(owned),
                            "--data-dir",
                            str(data_dir),
                            "--user-agent",
                            "group-18-test",
                        ]
                    )

            self.assertEqual(code, 0)
            self.assertTrue(
                (data_dir / "manifests" / "discovery" / "discovery_summary.json").exists()
            )
            self.assertIn('"version_task_count": 2', output.getvalue())

    def test_live_discover_rejects_data_dir_inside_repo(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            owned = Path(directory) / "owned.csv"
            owned.write_text(
                "member_id,arxiv_id\nmember-1,2509.16047\n",
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as raised:
                main(
                    [
                        "discover",
                        "--owned-papers",
                        str(owned),
                        "--data-dir",
                        str(Path(directory) / "data"),
                        "--user-agent",
                        "group-18-test",
                    ]
                )
            self.assertEqual(raised.exception.code, 2)

    def test_crawl_references_uses_member_filter_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            owned = root / "owned.csv"
            owned.write_text(
                "member_id,arxiv_id\nmember-1,2509.16047\nmember-2,2509.21047\n",
                encoding="utf-8",
            )
            fake_status = {
                "arxiv_id": "2509.16047",
                "status": "ok",
                "raw_reference_count": 0,
                "parse_failures": 0,
            }
            with mock.patch("src.cli.crawl_references", return_value=[fake_status]) as crawl:
                with mock.patch("src.cli.load_raw_references", return_value=[]):
                    with contextlib.redirect_stdout(io.StringIO()):
                        code = main(
                            [
                                "crawl-references",
                                "--owned-papers",
                                str(owned),
                                "--data-dir",
                                str(root / "data"),
                                "--member",
                                "member-1",
                            ]
                        )
            self.assertEqual(code, 0)
            self.assertEqual(crawl.call_args.args[0], ["2509.16047"])


if __name__ == "__main__":
    unittest.main()
