"""Atomic discovery checkpoints and structured event output."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .contracts import PaperMetadata, StageEvent, StageStatus, VersionTask


class CheckpointError(RuntimeError):
    """A checkpoint exists but is unreadable or violates its contract."""


@dataclass(frozen=True, slots=True)
class DiscoveryCheckpoint:
    subject: str
    fingerprint: str
    status: StageStatus
    metadata: PaperMetadata | None
    version_tasks: tuple[VersionTask, ...]
    error: str | None = None


class JsonCheckpointStore:
    """One atomic JSON checkpoint per arXiv publication."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def load(self, subject: str, *, fingerprint: str) -> DiscoveryCheckpoint | None:
        path = self._path(subject)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload["subject"] != subject or payload["fingerprint"] != fingerprint:
                return None
            metadata_payload = payload.get("metadata")
            metadata = None
            if metadata_payload is not None:
                metadata = PaperMetadata(
                    **{
                        **metadata_payload,
                        "authors": tuple(metadata_payload["authors"]),
                        "revised_dates": tuple(metadata_payload.get("revised_dates", ())),
                    }
                )
            tasks = tuple(
                VersionTask(
                    **{
                        **task,
                        "status": StageStatus(task["status"]),
                    }
                )
                for task in payload.get("version_tasks", ())
            )
            return DiscoveryCheckpoint(
                subject=subject,
                fingerprint=fingerprint,
                status=StageStatus(payload["status"]),
                metadata=metadata,
                version_tasks=tasks,
                error=payload.get("error"),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CheckpointError(f"Invalid checkpoint: {path}") from exc

    def save(self, checkpoint: DiscoveryCheckpoint) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = asdict(checkpoint)
        self._write_json_atomic(self._path(checkpoint.subject), payload)

    def _path(self, subject: str) -> Path:
        safe_name = hashlib.sha256(subject.encode("utf-8")).hexdigest()
        return self.directory / f"{safe_name}.json"

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)


def checkpoint_fingerprint(*, member_id: str, arxiv_id: str, context: str) -> str:
    payload = json.dumps(
        {"arxiv_id": arxiv_id, "context": context, "member_id": member_id},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_events_jsonl(path: str | Path, events: tuple[StageEvent, ...]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(asdict(event), ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(destination)
