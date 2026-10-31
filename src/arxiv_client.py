"""Discovery client interface and an in-memory Phase 1 test adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol

from .contracts import PaperMetadata


class DiscoveryError(RuntimeError):
    """Base class for discovery failures."""


class PaperNotFoundError(DiscoveryError):
    """The requested publication was not returned by arXiv."""


class TransientDiscoveryError(DiscoveryError):
    """A timeout, rate limit, or server failure that may succeed on retry."""


class MalformedDiscoveryResponseError(DiscoveryError):
    """arXiv returned a response that cannot satisfy the metadata contract."""


class ArxivDiscoveryClient(Protocol):
    def discover(self, arxiv_id: str) -> PaperMetadata:
        """Resolve one base arXiv ID into normalized metadata."""


class InMemoryArxivClient:
    """Deterministic adapter for unit/integration tests; performs no network I/O."""

    def __init__(self, records: Mapping[str, PaperMetadata]) -> None:
        self._records = dict(records)
        self.calls: list[str] = []

    def discover(self, arxiv_id: str) -> PaperMetadata:
        self.calls.append(arxiv_id)
        try:
            return self._records[arxiv_id]
        except KeyError as exc:
            raise PaperNotFoundError(f"arXiv paper not found: {arxiv_id}") from exc

    def discover_many(self, arxiv_ids: Iterable[str]) -> list[PaperMetadata]:
        return [self.discover(arxiv_id) for arxiv_id in arxiv_ids]
