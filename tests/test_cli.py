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
from src.cli import main
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

    def test_run_all_builds_and_validates_complete_m1_release(self) -> None:
        metadata = PaperMetadata(
            arxiv_id="2509.16047",
            latest_versioned_id="2509.16047v1",
            title="Synthetic paper",
            authors=("Example Author",),
            submission_date="2025-09-01",
        )

        class FakeMonitor:
            def __init__(self, **_: object) -> None:
                pass

            def start(self) -> None:
                pass

            def stop(self) -> dict[str, float]:
                return {
                    "peak_ram_mb": 10.0,
                    "avg_ram_mb": 9.0,
                    "time_weighted_ram_mb": 9.5,
                    "max_disk_mb": 1.0,
                    "final_storage_mb": 1.0,
                    "sample_count": 1,
                    "sampling_interval_sec": 0.5,
                }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            owned = root / "owned.csv"
            owned.write_text(
                "member_id,arxiv_id\nmember-1,2509.16047\n",
                encoding="utf-8",
            )
            data_dir = root / "external-data"

            def fake_source_pipeline(**kwargs: object) -> dict[str, object]:
                destination = Path(kwargs["data_dir"]) / "manifests" / "source_status.jsonl"
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(
                    json.dumps(
                        {
                            "member_id": "member-1",
                            "arxiv_id": "2509.16047",
                            "versioned_arxiv_id": "2509.16047v1",
                            "version": 1,
                            "status": "success",
                            "download": {"archive_bytes": 100},
                            "extraction": {"filtered_bytes": 75},
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return {
                    "expected_version_tasks": 1,
                    "terminal_status_records": 1,
                    "manifest_status_records": 1,
                    "status_counts": {"success": 1},
                }

            def fake_crawl(ids: object, out_dir: Path, **_: object) -> list[dict[str, object]]:
                self.assertEqual(list(ids), ["2509.16047"])
                out_dir.mkdir(parents=True, exist_ok=True)
                status = {
                    "arxiv_id": "2509.16047",
                    "status": "ok",
                    "parse_failures": 0,
                }
                (out_dir / "2509.16047.json").write_text(
                    json.dumps({"status": status, "references": []}),
                    encoding="utf-8",
                )
                return [status]

            with mock.patch(
                "src.cli.LiveArxivClient",
                return_value=InMemoryArxivClient({metadata.arxiv_id: metadata}),
            ):
                with mock.patch("src.cli.run_source_pipeline", side_effect=fake_source_pipeline):
                    with mock.patch("src.cli.crawl_references", side_effect=fake_crawl):
                        with mock.patch("src.cli.ResourceMonitor", FakeMonitor):
                            with contextlib.redirect_stdout(io.StringIO()):
                                code = main(
                                    [
                                        "run-all",
                                        "--owned-papers",
                                        str(owned),
                                        "--data-dir",
                                        str(data_dir),
                                        "--user-agent",
                                        "group-18-test",
                                        "--member",
                                        "member-1",
                                    ]
                                )

            self.assertEqual(code, 0)
            run_summary = json.loads(
                (data_dir / "manifests" / "m1_run_summary.json").read_text(
                    encoding="utf-8"
                )
            )
            metrics = json.loads(
                (data_dir / "metrics" / "summary.json").read_text(encoding="utf-8")
            )
            self.assertTrue(run_summary["is_success"])
            self.assertTrue(run_summary["source_completeness"]["is_complete"])
            self.assertTrue(run_summary["validation"]["is_valid"])
            self.assertEqual(metrics["crawl_statistics"]["papers_scraped_successfully"], 1)

    def test_benchmark_rejects_nonempty_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            owned = root / "owned.csv"
            owned.write_text(
                "member_id,arxiv_id\nmember-1,2509.16047\n",
                encoding="utf-8",
            )
            data_dir = root / "external-data"
            (data_dir / "raw").mkdir(parents=True)
            with self.assertRaises(SystemExit) as raised:
                main(
                    [
                        "benchmark",
                        "--owned-papers",
                        str(owned),
                        "--data-dir",
                        str(data_dir),
                        "--user-agent",
                        "group-18-test",
                    ]
                )
            self.assertEqual(raised.exception.code, 2)

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
