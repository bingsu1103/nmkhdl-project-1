from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from src.config import PipelineConfig
from src.ids import RangeConvention, RangeValidationError


class PipelineConfigTests(unittest.TestCase):
    def test_accepts_external_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as data:
            config = self._config(Path(data))
            config.validate(repo_root=repo)

    def test_rejects_data_directory_inside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as repo:
            config = self._config(Path(repo) / "data")
            with self.assertRaisesRegex(RangeValidationError, "outside"):
                config.validate(repo_root=repo)

    def test_rejects_fast_arxiv_delay(self) -> None:
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as data:
            config = PipelineConfig(
                ranges_file=Path("ranges.csv"),
                data_dir=Path(data),
                user_agent="group-18-arxiv-project/0.1",
                range_convention=RangeConvention(inclusive_end=True),
                arxiv_delay_seconds=2.9,
            )
            with self.assertRaisesRegex(RangeValidationError, "at least 3"):
                config.validate(repo_root=repo)

    def test_rejects_missing_user_agent(self) -> None:
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as data:
            config = PipelineConfig(
                ranges_file=Path("ranges.csv"),
                data_dir=Path(data),
                user_agent="  ",
                range_convention=RangeConvention(inclusive_end=True),
            )
            with self.assertRaisesRegex(RangeValidationError, "User-Agent"):
                config.validate(repo_root=repo)

    def test_rejects_invalid_timeouts_and_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as data:
            timeout = replace(self._config(Path(data)), request_timeout_seconds=0)
            with self.assertRaisesRegex(RangeValidationError, "timeout"):
                timeout.validate(repo_root=repo)

            attempts = replace(self._config(Path(data)), max_attempts=0)
            with self.assertRaisesRegex(RangeValidationError, "max_attempts"):
                attempts.validate(repo_root=repo)

    def test_sanitized_config_contains_only_key_environment_name(self) -> None:
        config = self._config(Path("../external-data"))
        sanitized = config.sanitized()
        self.assertEqual(sanitized["semantic_scholar_key_env"], "SEMANTIC_SCHOLAR_API_KEY")
        self.assertNotIn("api_key", sanitized)

    def _config(self, data_dir: Path) -> PipelineConfig:
        return PipelineConfig(
            ranges_file=Path("ranges.csv"),
            data_dir=data_dir,
            user_agent="group-18-arxiv-project/0.1 (+https://github.com/bingsu1103/nmkhdl-project-1)",
            range_convention=RangeConvention(inclusive_end=True),
        )


if __name__ == "__main__":
    unittest.main()
