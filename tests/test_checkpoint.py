from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.checkpoint import write_events_jsonl
from src.contracts import StageEvent, StageStatus


class CheckpointOutputTests(unittest.TestCase):
    def test_writes_machine_readable_events_atomically(self) -> None:
        event = StageEvent.now(
            run_id="fixture-run",
            stage="discovery",
            subject="2509.16047",
            status=StageStatus.SUCCESS,
            details={"expected_versions": 2},
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            write_events_jsonl(path, (event,))

            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["run_id"], "fixture-run")
            self.assertEqual(rows[0]["status"], "success")
            self.assertFalse(path.with_suffix(".jsonl.tmp").exists())


if __name__ == "__main__":
    unittest.main()
