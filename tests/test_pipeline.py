from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from src.arxiv_client import InMemoryArxivClient, TransientDiscoveryError
from src.checkpoint import JsonCheckpointStore
from src.contracts import OwnedPaper, PaperMetadata, StageStatus
from src.pipeline import DiscoveryPipeline


class DiscoveryPipelineTests(unittest.TestCase):
    def test_continues_after_missing_paper(self) -> None:
        metadata = PaperMetadata(
            arxiv_id="2509.16047",
            latest_versioned_id="2509.16047v2",
            title="Synthetic paper",
            authors=("Example Author",),
            submission_date="2025-09-01",
        )
        client = InMemoryArxivClient({metadata.arxiv_id: metadata})
        pipeline = DiscoveryPipeline(client)
        result = pipeline.run(
            [
                OwnedPaper("member-1", "2509.99999"),
                OwnedPaper("member-1", "2509.16047"),
            ],
            run_id="test-run",
        )

        self.assertFalse(result.succeeded)
        self.assertEqual(result.outcomes[0].status, StageStatus.NO_SOURCE)
        self.assertEqual(result.outcomes[1].status, StageStatus.SUCCESS)
        self.assertEqual(len(result.outcomes[1].version_tasks), 2)
        self.assertEqual(len(result.events), 4)

    def test_classifies_transient_failures_as_retryable(self) -> None:
        class TimeoutClient:
            def discover(self, arxiv_id: str) -> PaperMetadata:
                raise TransientDiscoveryError("synthetic timeout")

        result = DiscoveryPipeline(TimeoutClient()).run(
            [OwnedPaper("member-1", "2509.16047")]
        )
        self.assertEqual(result.outcomes[0].status, StageStatus.RETRYABLE_FAILURE)

    def test_crash_then_resume_does_not_repeat_completed_paper(self) -> None:
        first = self._metadata("2509.16047")
        second = self._metadata("2509.16048")

        class CrashOnSecondClient(InMemoryArxivClient):
            def discover(self, arxiv_id: str) -> PaperMetadata:
                if arxiv_id == second.arxiv_id:
                    raise KeyboardInterrupt("synthetic crash")
                return super().discover(arxiv_id)

        with tempfile.TemporaryDirectory() as directory:
            store = JsonCheckpointStore(Path(directory))
            crashing = CrashOnSecondClient({first.arxiv_id: first, second.arxiv_id: second})
            pipeline = DiscoveryPipeline(crashing, checkpoint_store=store)
            papers = [
                OwnedPaper("member-1", first.arxiv_id),
                OwnedPaper("member-1", second.arxiv_id),
            ]
            with self.assertRaises(KeyboardInterrupt):
                pipeline.run(papers, checkpoint_context="fixture-v1")

            resumed_client = InMemoryArxivClient(
                {first.arxiv_id: first, second.arxiv_id: second}
            )
            resumed = DiscoveryPipeline(
                resumed_client,
                checkpoint_store=store,
            ).run(
                papers,
                resume=True,
                checkpoint_context="fixture-v1",
            )

            self.assertEqual(resumed_client.calls, [second.arxiv_id])
            self.assertTrue(resumed.succeeded)
            self.assertTrue(resumed.events[0].details["resumed"])

    def test_changed_context_does_not_reuse_old_checkpoint(self) -> None:
        metadata = self._metadata("2509.16047")
        with tempfile.TemporaryDirectory() as directory:
            store = JsonCheckpointStore(Path(directory))
            initial = InMemoryArxivClient({metadata.arxiv_id: metadata})
            papers = [OwnedPaper("member-1", metadata.arxiv_id)]
            DiscoveryPipeline(initial, checkpoint_store=store).run(
                papers,
                checkpoint_context="input-a",
            )

            changed = InMemoryArxivClient({metadata.arxiv_id: metadata})
            DiscoveryPipeline(changed, checkpoint_store=store).run(
                papers,
                resume=True,
                checkpoint_context="input-b",
            )
            self.assertEqual(changed.calls, [metadata.arxiv_id])

    def test_uses_batch_discovery_and_preserves_input_order(self) -> None:
        first = self._metadata("2509.16047")

        class BatchClient:
            def __init__(self) -> None:
                self.calls = []

            def discover(self, arxiv_id: str) -> PaperMetadata:
                raise AssertionError("single discovery must not be used")

            def discover_many(self, arxiv_ids):
                self.calls.append(list(arxiv_ids))
                return {first.arxiv_id: first}

        client = BatchClient()
        papers = [
            OwnedPaper("member-1", first.arxiv_id),
            OwnedPaper("member-1", "2509.99999"),
        ]
        result = DiscoveryPipeline(client).run(papers)

        self.assertEqual(client.calls, [[first.arxiv_id, "2509.99999"]])
        self.assertEqual(result.outcomes[0].status, StageStatus.SUCCESS)
        self.assertEqual(result.outcomes[1].status, StageStatus.NO_SOURCE)

    @staticmethod
    def _metadata(arxiv_id: str) -> PaperMetadata:
        return PaperMetadata(
            arxiv_id=arxiv_id,
            latest_versioned_id=f"{arxiv_id}v2",
            title="Synthetic paper",
            authors=("Example Author",),
            submission_date="2025-09-01",
        )


if __name__ == "__main__":
    unittest.main()
