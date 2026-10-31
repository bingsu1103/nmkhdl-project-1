from __future__ import annotations

import unittest

from src.contracts import PaperMetadata
from src.version_resolver import VersionResolutionError, resolve_version_tasks


class VersionResolverTests(unittest.TestCase):
    def test_enumerates_every_version(self) -> None:
        metadata = self._metadata("2509.16047", "2509.16047v3")
        tasks = resolve_version_tasks(metadata, member_id="member-1")
        self.assertEqual([task.version for task in tasks], [1, 2, 3])
        self.assertEqual(tasks[-1].versioned_arxiv_id, "2509.16047v3")

    def test_supports_old_style_id(self) -> None:
        metadata = self._metadata("hep-th/9901001", "hep-th/9901001v2")
        tasks = resolve_version_tasks(metadata, member_id="member-1")
        self.assertEqual(len(tasks), 2)

    def test_rejects_missing_suffix(self) -> None:
        metadata = self._metadata("2509.16047", "2509.16047")
        with self.assertRaisesRegex(VersionResolutionError, "version suffix"):
            resolve_version_tasks(metadata, member_id="member-1")

    def test_rejects_base_mismatch(self) -> None:
        metadata = self._metadata("2509.16047", "2509.99999v2")
        with self.assertRaisesRegex(VersionResolutionError, "does not match"):
            resolve_version_tasks(metadata, member_id="member-1")

    @staticmethod
    def _metadata(base: str, latest: str) -> PaperMetadata:
        return PaperMetadata(
            arxiv_id=base,
            latest_versioned_id=latest,
            title="Synthetic paper",
            authors=("Example Author",),
            submission_date="2025-09-01",
        )


if __name__ == "__main__":
    unittest.main()
