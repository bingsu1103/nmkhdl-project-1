"""Offline and live adapters for targeted arXiv metadata discovery."""

from __future__ import annotations

import hashlib
import random
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol

import requests

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


ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
VERSION_SUFFIX = re.compile(r"v[1-9]\d*$")
RETRYABLE_HTTP = {429, 500, 502, 503, 504}


class LiveArxivClient:
    """Targeted, paced arXiv Atom API client with bounded retries and raw cache."""

    def __init__(
        self,
        *,
        user_agent: str,
        cache_dir: str | Path,
        batch_size: int = 100,
        delay_seconds: float = 3.0,
        timeout_seconds: float = 30.0,
        max_attempts: int = 4,
        session: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("A descriptive arXiv User-Agent is required.")
        if not 1 <= batch_size <= 100:
            raise ValueError("arXiv batch_size must be between 1 and 100.")
        if delay_seconds < 3.0:
            raise ValueError("arXiv delay must be at least 3 seconds.")
        if timeout_seconds <= 0 or max_attempts <= 0:
            raise ValueError("arXiv timeout and max_attempts must be positive.")
        self.user_agent = user_agent.strip()
        self.cache_dir = Path(cache_dir)
        self.batch_size = batch_size
        self.delay_seconds = delay_seconds
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self._session = session or requests.Session()
        self._clock = clock
        self._sleep = sleep
        self._jitter = jitter
        self._last_request_at: float | None = None

    def discover(self, arxiv_id: str) -> PaperMetadata:
        records = self.discover_many([arxiv_id])
        try:
            return records[arxiv_id]
        except KeyError as exc:
            raise PaperNotFoundError(f"arXiv paper not found: {arxiv_id}") from exc

    def discover_many(self, arxiv_ids: Sequence[str]) -> dict[str, PaperMetadata]:
        ordered = list(dict.fromkeys(arxiv_ids))
        if not ordered:
            return {}
        records: dict[str, PaperMetadata] = {}
        for offset in range(0, len(ordered), self.batch_size):
            batch = ordered[offset : offset + self.batch_size]
            raw_xml = self._load_or_fetch(batch)
            parsed = self._parse_feed(raw_xml, requested=set(batch))
            duplicate = records.keys() & parsed.keys()
            if duplicate:
                raise MalformedDiscoveryResponseError(
                    f"Duplicate arXiv entries across batches: {sorted(duplicate)}"
                )
            records.update(parsed)
        return records

    def _load_or_fetch(self, arxiv_ids: list[str]) -> bytes:
        cache_path = self._cache_path(arxiv_ids)
        if cache_path.exists():
            try:
                return cache_path.read_bytes()
            except OSError as exc:
                raise DiscoveryError(f"Cannot read arXiv cache: {cache_path}") from exc

        response_content = self._request_batch(arxiv_ids)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(".xml.tmp")
        try:
            temporary.write_bytes(response_content)
            temporary.replace(cache_path)
        except OSError as exc:
            raise DiscoveryError(f"Cannot write arXiv cache: {cache_path}") from exc
        return response_content

    def _request_batch(self, arxiv_ids: list[str]) -> bytes:
        params = {
            "id_list": ",".join(arxiv_ids),
            "max_results": str(len(arxiv_ids)),
        }
        headers = {"User-Agent": self.user_agent}
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._pace()
            try:
                response = self._session.get(
                    ARXIV_API_URL,
                    params=params,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                last_error = exc
            else:
                status = int(response.status_code)
                if status == 200:
                    return bytes(response.content)
                if status not in RETRYABLE_HTTP:
                    raise DiscoveryError(f"arXiv API returned permanent HTTP {status}.")
                last_error = TransientDiscoveryError(
                    f"arXiv API returned retryable HTTP {status}."
                )
                if attempt < self.max_attempts:
                    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                    self._sleep(retry_after if retry_after is not None else 2 ** (attempt - 1) + self._jitter())
                    continue
            if attempt < self.max_attempts:
                self._sleep(2 ** (attempt - 1) + self._jitter())

        raise TransientDiscoveryError(
            f"arXiv request failed after {self.max_attempts} attempts: "
            f"{type(last_error).__name__ if last_error else 'unknown error'}"
        ) from last_error

    def _pace(self) -> None:
        now = self._clock()
        if self._last_request_at is not None:
            remaining = self.delay_seconds - (now - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._clock()

    def _cache_path(self, arxiv_ids: list[str]) -> Path:
        payload = "\n".join(arxiv_ids).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        return self.cache_dir / f"batch-{digest}.xml"

    @staticmethod
    def _parse_feed(raw_xml: bytes, *, requested: set[str]) -> dict[str, PaperMetadata]:
        try:
            root = ET.fromstring(raw_xml)
        except ET.ParseError as exc:
            raise MalformedDiscoveryResponseError("arXiv response is not valid Atom XML.") from exc

        records: dict[str, PaperMetadata] = {}
        for entry in root.findall(f"{ATOM}entry"):
            latest_id = _required_text(entry, f"{ATOM}id").rsplit("/abs/", 1)[-1]
            base_id = VERSION_SUFFIX.sub("", latest_id)
            if base_id not in requested:
                raise MalformedDiscoveryResponseError(
                    f"arXiv returned unexpected ID {latest_id}."
                )
            if base_id in records:
                raise MalformedDiscoveryResponseError(f"arXiv returned duplicate ID {base_id}.")
            published = _parse_datetime(_required_text(entry, f"{ATOM}published"))
            updated = _parse_datetime(_required_text(entry, f"{ATOM}updated"))
            authors = tuple(
                _required_text(author, f"{ATOM}name")
                for author in entry.findall(f"{ATOM}author")
            )
            if not authors:
                raise MalformedDiscoveryResponseError(f"arXiv entry {base_id} has no authors.")
            revised_dates = ()
            if updated != published:
                revised_dates = (updated.date().isoformat(),)
            venue_node = entry.find(f"{ARXIV}journal_ref")
            venue = None if venue_node is None or not venue_node.text else venue_node.text.strip()
            records[base_id] = PaperMetadata(
                arxiv_id=base_id,
                latest_versioned_id=latest_id,
                title=" ".join(_required_text(entry, f"{ATOM}title").split()),
                authors=authors,
                submission_date=published.date().isoformat(),
                revised_dates=revised_dates,
                venue=venue,
            )
        return records


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

def _required_text(node: ET.Element, path: str) -> str:
    child = node.find(path)
    if child is None or not child.text or not child.text.strip():
        raise MalformedDiscoveryResponseError(f"Missing required Atom field: {path}")
    return child.text.strip()


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MalformedDiscoveryResponseError(f"Invalid arXiv datetime: {value}") from exc


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
