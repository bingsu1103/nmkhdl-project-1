"""Typed configuration with safe defaults and secret redaction."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .ids import RangeConvention, RangeValidationError


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    ranges_file: Path
    data_dir: Path
    user_agent: str
    range_convention: RangeConvention
    arxiv_delay_seconds: float = 3.0
    request_timeout_seconds: float = 30.0
    max_attempts: int = 4
    semantic_scholar_delay_seconds: float = 1.0
    semantic_scholar_timeout_seconds: float = 30.0
    semantic_scholar_max_attempts: int = 4
    log_level: str = "INFO"
    resume: bool = False
    semantic_scholar_key_env: str = "SEMANTIC_SCHOLAR_API_KEY"

    def validate(self, *, repo_root: str | Path) -> None:
        root = Path(repo_root).resolve()
        data = self.data_dir.expanduser().resolve()
        try:
            data.relative_to(root)
        except ValueError:
            pass
        else:
            raise RangeValidationError("data_dir must be outside the tracked repository.")

        if not self.user_agent.strip():
            raise RangeValidationError("A descriptive User-Agent is required.")
        if self.arxiv_delay_seconds < 3.0:
            raise RangeValidationError("arXiv delay must be at least 3 seconds.")
        if self.request_timeout_seconds <= 0:
            raise RangeValidationError("Request timeout must be positive.")
        if self.max_attempts <= 0:
            raise RangeValidationError("max_attempts must be positive.")
        if self.semantic_scholar_delay_seconds < 0:
            raise RangeValidationError("Semantic Scholar delay cannot be negative.")
        if self.semantic_scholar_timeout_seconds <= 0:
            raise RangeValidationError("Semantic Scholar timeout must be positive.")
        if self.semantic_scholar_max_attempts <= 0:
            raise RangeValidationError("Semantic Scholar max attempts must be positive.")
        if self.log_level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise RangeValidationError("Unsupported log level.")
        if not self.semantic_scholar_key_env.strip():
            raise RangeValidationError("Semantic Scholar key environment name is required.")
        self.range_convention.validate()

    def sanitized(self) -> dict[str, object]:
        result = asdict(self)
        result["ranges_file"] = str(self.ranges_file)
        result["data_dir"] = str(self.data_dir)
        # Only the environment variable name is stored, never its value.
        return result
