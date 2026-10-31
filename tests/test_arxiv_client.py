from __future__ import annotations

import unittest

from src.arxiv_client import InMemoryArxivClient, PaperNotFoundError
from src.contracts import PaperMetadata


class InMemoryArxivClientTests(unittest.TestCase):
    def test_returns_unicode_metadata_without_reordering_authors(self) -> None:
        metadata = PaperMetadata(
            arxiv_id="2509.16047",
            latest_versioned_id="2509.16047v1",
            title="Dữ liệu thử nghiệm",
            authors=("Ngô Gia An", "Example Author"),
            submission_date="2025-09-01",
        )
        client = InMemoryArxivClient({metadata.arxiv_id: metadata})

        actual = client.discover(metadata.arxiv_id)

        self.assertEqual(actual, metadata)
        self.assertEqual(actual.authors, ("Ngô Gia An", "Example Author"))
        self.assertEqual(client.calls, [metadata.arxiv_id])

    def test_missing_record_is_explicit_not_found(self) -> None:
        client = InMemoryArxivClient({})
        with self.assertRaisesRegex(PaperNotFoundError, "not found"):
            client.discover("2509.99999")


if __name__ == "__main__":
    unittest.main()
