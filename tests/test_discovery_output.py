from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.arxiv_client import InMemoryArxivClient
from src.contracts import OwnedPaper, PaperMetadata
from src.discovery_output import write_discovery_outputs
from src.pipeline import DiscoveryPipeline


class DiscoveryOutputTests(unittest.TestCase):
    def test_writes_complete_atomic_handoff(self) -> None:
        metadata = PaperMetadata(
            arxiv_id="2509.16047",
            latest_versioned_id="2509.16047v2",
            title="Synthetic paper",
            authors=("Ngô Gia An",),
            submission_date="2025-09-01",
        )
        run = DiscoveryPipeline(InMemoryArxivClient({metadata.arxiv_id: metadata})).run(
            [
                OwnedPaper("member-1", metadata.arxiv_id),
                OwnedPaper("member-1", "2509.99999"),
            ],
            run_id="run-output-test",
        )

        with tempfile.TemporaryDirectory() as directory:
            paths = write_discovery_outputs(directory, run)
            summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
            statuses = [
                json.loads(line)
                for line in paths["statuses"].read_text(encoding="utf-8").splitlines()
            ]
            with paths["version_tasks"].open(encoding="utf-8", newline="") as handle:
                tasks = list(csv.DictReader(handle))

            self.assertEqual(summary["assigned_count"], 2)
            self.assertEqual(summary["metadata_count"], 1)
            self.assertEqual(summary["version_task_count"], 2)
            self.assertEqual(summary["status_counts"], {"no_source": 1, "success": 1})
            self.assertEqual(statuses[1]["arxiv_id"], "2509.99999")
            self.assertEqual(tasks[-1]["versioned_arxiv_id"], "2509.16047v2")
            self.assertFalse(list(Path(directory).glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
