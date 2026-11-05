from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.m1_integration import build_m1_tables, validate_m1_tables


class Milestone1IntegrationTests(unittest.TestCase):
    def test_builds_and_validates_two_required_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            papers = root / "papers.jsonl"
            papers.write_text(
                json.dumps(
                    {
                        "arxiv_id": "2509.16047",
                        "latest_versioned_id": "2509.16047v1",
                        "title": "Synthetic paper",
                        "authors": ["Example Author"],
                        "submission_date": "2025-09-19",
                        "revised_dates": [],
                        "venue": None,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            s2_dir = root / "s2"
            s2_dir.mkdir()
            (s2_dir / "2509.16047.json").write_text(
                json.dumps(
                    {
                        "status": {"arxiv_id": "2509.16047", "status": "ok"},
                        "references": [
                            {
                                "arxiv_id": "2509.16047",
                                "ref_arxiv_id": "1706.03762",
                                "ref_arxiv_id_raw": "1706.03762",
                                "s2": {
                                    "paperId": "s2-example",
                                    "title": "Attention Is All You Need",
                                    "authors": [{"name": "A. Author"}],
                                    "publicationDate": "2017-06-12",
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            table_summary = build_m1_tables(
                papers_jsonl=papers,
                s2_raw_dir=s2_dir,
                output_dir=root / "tables",
            )
            validation = validate_m1_tables(
                tables_dir=root / "tables",
                assigned_ids=["2509.16047"],
            )

            self.assertEqual(table_summary["papers_rows"], 1)
            self.assertEqual(table_summary["references_rows"], 1)
            self.assertTrue(validation["is_valid"])
            self.assertTrue(validation["reconciliation"]["is_reconciled"])

    def test_refuses_to_build_before_s2_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            papers = root / "papers.jsonl"
            papers.write_text(
                json.dumps(
                    {
                        "arxiv_id": "2509.16047",
                        "latest_versioned_id": "2509.16047v1",
                        "title": "Synthetic paper",
                        "authors": ["Example Author"],
                        "submission_date": "2025-09-19",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            from src.m1_integration import Milestone1IntegrationError

            with self.assertRaisesRegex(Milestone1IntegrationError, "Missing Semantic"):
                build_m1_tables(
                    papers_jsonl=papers,
                    s2_raw_dir=root / "missing-s2",
                    output_dir=root / "tables",
                )


if __name__ == "__main__":
    unittest.main()
