"""Version-specific arXiv source downloader with audit metadata and safe resume."""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import requests

VERSIONED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*v[1-9][0-9]*$")
RETRYABLE = {429, 500, 502, 503, 504}


class DownloadError(RuntimeError):
    """Base error for source download failures."""


class PermanentDownloadError(DownloadError):
    """Non-retryable HTTP or invalid request."""


class RetryableDownloadError(DownloadError):
    """Transient failure after bounded retries."""


@dataclass(frozen=True, slots=True)
class DownloadResult:
    arxiv_id: str
    versioned_arxiv_id: str
    status: str
    archive_path: str | None
    endpoint: str
    http_status: int | None
    archive_bytes: int
    content_type: str | None
    elapsed_seconds: float
    attempts: int
    sha256: str | None
    started_at_utc: str
    finished_at_utc: str
    error_code: str | None = None
    error_message: str | None = None


class ArxivSourceDownloader:
    """Download one explicit arXiv revision, streaming to an atomic file."""

    def __init__(
        self,
        *,
        output_dir: str | Path,
        user_agent: str,
        delay_seconds: float = 3.0,
        timeout: tuple[float, float] = (10.0, 60.0),
        max_attempts: int = 4,
        max_archive_bytes: int = 100 * 1024 * 1024,
        session: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("A descriptive User-Agent is required.")
        if delay_seconds < 3:
            raise ValueError("arXiv requests must be paced by at least 3 seconds.")
        if max_attempts < 1 or max_archive_bytes < 1:
            raise ValueError("max_attempts and max_archive_bytes must be positive.")
        self.output_dir = Path(output_dir)
        self.user_agent = user_agent.strip()
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.max_archive_bytes = max_archive_bytes
        self.session = session or requests.Session()
        self.clock, self.sleep, self.jitter = clock, sleep, jitter
        self._last_request: float | None = None

    def download(self, arxiv_id: str, versioned_arxiv_id: str, *, resume: bool = True) -> DownloadResult:
        if not VERSIONED_ID.fullmatch(versioned_arxiv_id):
            raise ValueError("Download requires an explicit versioned arXiv ID (e.g. 2509.21047v1).")
        if versioned_arxiv_id.rsplit("v", 1)[0] != arxiv_id:
            raise ValueError("Base and versioned arXiv IDs do not match.")
        endpoint = f"https://export.arxiv.org/src/{quote(versioned_arxiv_id, safe='')}"
        target_dir = self.output_dir / _safe_component(arxiv_id) / _safe_component(versioned_arxiv_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        archive = target_dir / "source.archive"
        status_path = target_dir / "download_status.json"
        if resume and archive.exists() and status_path.exists():
            try:
                old = json.loads(status_path.read_text(encoding="utf-8"))
                digest, size = _hash_file(archive)
                if old.get("status") == "success" and old.get("sha256") == digest and old.get("archive_bytes") == size:
                    return DownloadResult(**old)
            except (OSError, ValueError, TypeError):
                pass

        started = datetime.now(timezone.utc).isoformat()
        begin = self.clock()
        last_status = None
        last_type = None
        attempts = 0
        temp = archive.with_suffix(".archive.part")
        error_code = error_message = None
        try:
            for attempts in range(1, self.max_attempts + 1):
                self._pace()
                try:
                    with self.session.get(
                        endpoint, headers={"User-Agent": self.user_agent},
                        timeout=self.timeout, stream=True,
                    ) as response:
                        last_status = int(response.status_code)
                        last_type = response.headers.get("Content-Type")
                        if last_status == 404:
                            raise PermanentDownloadError("arXiv source does not exist for this version.")
                        if last_status != 200:
                            if last_status not in RETRYABLE:
                                raise PermanentDownloadError(f"arXiv source endpoint returned HTTP {last_status}.")
                            raise RetryableDownloadError(f"arXiv source endpoint returned HTTP {last_status}.")
                        digest = hashlib.sha256()
                        size = 0
                        with temp.open("wb") as handle:
                            for chunk in response.iter_content(chunk_size=1024 * 128):
                                if not chunk:
                                    continue
                                size += len(chunk)
                                if size > self.max_archive_bytes:
                                    raise PermanentDownloadError("Archive exceeds configured compressed-size limit.")
                                digest.update(chunk)
                                handle.write(chunk)
                            handle.flush()
                            import os
                            os.fsync(handle.fileno())
                        if size == 0:
                            raise PermanentDownloadError("Empty source response.")
                        with temp.open("rb") as prefix_handle:
                            prefix = prefix_handle.read(512).lstrip().lower()
                        if prefix.startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
                            raise PermanentDownloadError("HTTP 200 response contains an HTML page, not source data.")
                        temp.replace(archive)
                        result = DownloadResult(
                            arxiv_id=arxiv_id, versioned_arxiv_id=versioned_arxiv_id,
                            status="success", archive_path=str(archive), endpoint=endpoint,
                            http_status=last_status, archive_bytes=size, content_type=last_type,
                            elapsed_seconds=self.clock()-begin, attempts=attempts,
                            sha256=digest.hexdigest(), started_at_utc=started,
                            finished_at_utc=datetime.now(timezone.utc).isoformat(),
                        )
                        _atomic_json(status_path, asdict(result))
                        return result
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as exc:
                    error_code, error_message = "network_error", type(exc).__name__
                    temp.unlink(missing_ok=True)
                    if attempts >= self.max_attempts:
                        raise RetryableDownloadError(f"Download failed after {attempts} attempts ({error_message}).") from exc
                except RetryableDownloadError as exc:
                    error_code, error_message = "http_retryable", str(exc)
                    temp.unlink(missing_ok=True)
                    if attempts >= self.max_attempts:
                        raise
                if attempts < self.max_attempts:
                    self.sleep(2 ** (attempts - 1) + self.jitter())
        except (PermanentDownloadError, RetryableDownloadError) as exc:
            temp.unlink(missing_ok=True)
            status = "http_error" if isinstance(exc, PermanentDownloadError) else "retry_exhausted"
            result = DownloadResult(
                arxiv_id, versioned_arxiv_id, status, None, endpoint, last_status, 0,
                last_type, self.clock()-begin, attempts, None, started,
                datetime.now(timezone.utc).isoformat(),
                "permanent_http_or_payload" if status == "http_error" else (error_code or "retry_exhausted"),
                str(exc),
            )
            _atomic_json(status_path, asdict(result))
            return result
        finally:
            temp.unlink(missing_ok=True)
        raise AssertionError("unreachable")

    def _pace(self) -> None:
        now = self.clock()
        if self._last_request is not None:
            remaining = self.delay_seconds - (now - self._last_request)
            if remaining > 0:
                self.sleep(remaining)
        self._last_request = self.clock()


def _safe_component(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise ValueError(f"Unsafe path component: {value!r}")
    return value


def _hash_file(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
