"""Stable data contracts shared across the three project milestones."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class StageStatus(StrEnum):
    """Terminal and non-terminal states emitted by pipeline stages."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    NO_SOURCE = "no_source"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"


@dataclass(frozen=True, slots=True)
class AssignedRange:
    """One member's raw range exactly as assigned by the lab sheet."""

    member_id: str
    start_month: str
    start_id: str
    end_month: str
    end_id: str


@dataclass(frozen=True, slots=True)
class OwnedPaper:
    """A canonical publication ID and the member responsible for it."""

    member_id: str
    arxiv_id: str


@dataclass(frozen=True, slots=True)
class PaperMetadata:
    """Milestone 1 metadata needed for discovery and the papers table."""

    arxiv_id: str
    latest_versioned_id: str
    title: str
    authors: tuple[str, ...]
    submission_date: str
    revised_dates: tuple[str, ...] = ()
    venue: str | None = None


@dataclass(frozen=True, slots=True)
class VersionTask:
    """A deterministic unit of source-download work for Member 2."""

    member_id: str
    arxiv_id: str
    versioned_arxiv_id: str
    version: int
    status: StageStatus = StageStatus.PENDING


@dataclass(frozen=True, slots=True)
class StageEvent:
    """Machine-readable event consumed by metrics and audit tooling."""

    run_id: str
    stage: str
    subject: str
    status: StageStatus
    timestamp_utc: str
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def now(
        cls,
        *,
        run_id: str,
        stage: str,
        subject: str,
        status: StageStatus,
        details: dict[str, Any] | None = None,
    ) -> "StageEvent":
        return cls(
            run_id=run_id,
            stage=stage,
            subject=subject,
            status=status,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            details=details or {},
        )


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Reproducibility metadata for one pipeline run."""

    run_id: str
    started_at_utc: str
    git_sha: str
    input_sha256: str
    config: dict[str, Any]
    package_versions: dict[str, str] = field(default_factory=dict)
