"""Phase 1 discovery orchestration using stable adapter interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from .arxiv_client import (
    ArxivDiscoveryClient,
    DiscoveryError,
    PaperNotFoundError,
    TransientDiscoveryError,
)
from .checkpoint import (
    DiscoveryCheckpoint,
    JsonCheckpointStore,
    checkpoint_fingerprint,
)
from .contracts import OwnedPaper, PaperMetadata, StageEvent, StageStatus, VersionTask
from .version_resolver import VersionResolutionError, resolve_version_tasks


@dataclass(frozen=True, slots=True)
class DiscoveryOutcome:
    paper: OwnedPaper
    metadata: PaperMetadata | None
    version_tasks: tuple[VersionTask, ...]
    status: StageStatus
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryRun:
    run_id: str
    outcomes: tuple[DiscoveryOutcome, ...]
    events: tuple[StageEvent, ...]

    @property
    def succeeded(self) -> bool:
        return all(outcome.status is StageStatus.SUCCESS for outcome in self.outcomes)


class DiscoveryPipeline:
    def __init__(
        self,
        client: ArxivDiscoveryClient,
        *,
        checkpoint_store: JsonCheckpointStore | None = None,
    ) -> None:
        self._client = client
        self._checkpoint_store = checkpoint_store

    def run(
        self,
        papers: list[OwnedPaper],
        *,
        run_id: str | None = None,
        resume: bool = False,
        checkpoint_context: str = "discovery-contract-v1",
    ) -> DiscoveryRun:
        current_run_id = run_id or str(uuid4())
        outcomes: list[DiscoveryOutcome] = []
        events: list[StageEvent] = []
        fingerprints = {
            paper.arxiv_id: checkpoint_fingerprint(
                member_id=paper.member_id,
                arxiv_id=paper.arxiv_id,
                context=checkpoint_context,
            )
            for paper in papers
        }
        cached_by_id: dict[str, DiscoveryCheckpoint] = {}
        if resume and self._checkpoint_store is not None:
            for paper in papers:
                cached = self._checkpoint_store.load(
                    paper.arxiv_id,
                    fingerprint=fingerprints[paper.arxiv_id],
                )
                if cached is not None and cached.status in {
                    StageStatus.SUCCESS,
                    StageStatus.NO_SOURCE,
                }:
                    cached_by_id[paper.arxiv_id] = cached

        pending = [paper for paper in papers if paper.arxiv_id not in cached_by_id]
        batch_records: dict[str, PaperMetadata] | None = None
        batch_error: DiscoveryError | None = None
        discover_many = getattr(self._client, "discover_many", None)
        if pending and callable(discover_many):
            try:
                batch_records = dict(discover_many([paper.arxiv_id for paper in pending]))
            except DiscoveryError as exc:
                batch_error = exc

        for paper in papers:
            fingerprint = fingerprints[paper.arxiv_id]
            cached = cached_by_id.get(paper.arxiv_id)
            if cached is not None:
                outcomes.append(
                    DiscoveryOutcome(
                        paper=paper,
                        metadata=cached.metadata,
                        version_tasks=cached.version_tasks,
                        status=cached.status,
                        error=cached.error,
                    )
                )
                events.append(
                    StageEvent.now(
                        run_id=current_run_id,
                        stage="discovery",
                        subject=paper.arxiv_id,
                        status=cached.status,
                        details={"member_id": paper.member_id, "resumed": True},
                    )
                )
                continue

            events.append(
                StageEvent.now(
                    run_id=current_run_id,
                    stage="discovery",
                    subject=paper.arxiv_id,
                    status=StageStatus.RUNNING,
                    details={"member_id": paper.member_id},
                )
            )
            try:
                if batch_error is not None:
                    raise batch_error
                if batch_records is not None:
                    try:
                        metadata = batch_records[paper.arxiv_id]
                    except KeyError as exc:
                        raise PaperNotFoundError(
                            f"arXiv paper not found: {paper.arxiv_id}"
                        ) from exc
                else:
                    metadata = self._client.discover(paper.arxiv_id)
                tasks = tuple(resolve_version_tasks(metadata, member_id=paper.member_id))
            except (DiscoveryError, VersionResolutionError) as exc:
                if isinstance(exc, PaperNotFoundError):
                    status = StageStatus.NO_SOURCE
                elif isinstance(exc, TransientDiscoveryError):
                    status = StageStatus.RETRYABLE_FAILURE
                else:
                    status = StageStatus.PERMANENT_FAILURE
                outcome = DiscoveryOutcome(
                    paper=paper,
                    metadata=None,
                    version_tasks=(),
                    status=status,
                    error=str(exc),
                )
                outcomes.append(outcome)
                events.append(
                    StageEvent.now(
                        run_id=current_run_id,
                        stage="discovery",
                        subject=paper.arxiv_id,
                        status=status,
                        details={"error": str(exc)},
                    )
                )
                self._save_checkpoint(outcome, fingerprint=fingerprint)
                continue

            outcome = DiscoveryOutcome(
                paper=paper,
                metadata=metadata,
                version_tasks=tasks,
                status=StageStatus.SUCCESS,
            )
            outcomes.append(outcome)
            events.append(
                StageEvent.now(
                    run_id=current_run_id,
                    stage="discovery",
                    subject=paper.arxiv_id,
                    status=StageStatus.SUCCESS,
                    details={"expected_versions": len(tasks)},
                )
            )
            self._save_checkpoint(outcome, fingerprint=fingerprint)

        return DiscoveryRun(
            run_id=current_run_id,
            outcomes=tuple(outcomes),
            events=tuple(events),
        )

    def _save_checkpoint(
        self,
        outcome: DiscoveryOutcome,
        *,
        fingerprint: str,
    ) -> None:
        if self._checkpoint_store is None:
            return
        self._checkpoint_store.save(
            DiscoveryCheckpoint(
                subject=outcome.paper.arxiv_id,
                fingerprint=fingerprint,
                status=outcome.status,
                metadata=outcome.metadata,
                version_tasks=outcome.version_tasks,
                error=outcome.error,
            )
        )
