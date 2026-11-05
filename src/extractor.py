"""Allowlist-only, path-safe extraction of arXiv TeX/BibTeX source files."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any


class ExtractionError(RuntimeError):
    """The archive could not be safely interpreted or extracted."""


@dataclass(frozen=True, slots=True)
class ExtractedFile:
    path: str
    bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    arxiv_id: str
    versioned_arxiv_id: str
    status: str
    archive_bytes: int
    filtered_bytes: int
    files: tuple[ExtractedFile, ...]
    skipped_members: int
    elapsed_seconds: float
    error_code: str | None = None
    error_message: str | None = None


class SafeSourceExtractor:
    """Extract only regular .tex/.bib files into an atomic version directory."""

    def __init__(
        self,
        *,
        output_dir: str | Path,
        max_archive_bytes: int = 100 * 1024 * 1024,
        max_uncompressed_bytes: int = 500 * 1024 * 1024,
        max_member_bytes: int = 50 * 1024 * 1024,
        max_members: int = 20_000,
    ) -> None:
        if min(max_archive_bytes, max_uncompressed_bytes, max_member_bytes, max_members) <= 0:
            raise ValueError("All extraction limits must be positive.")
        self.output_dir = Path(output_dir)
        self.max_archive_bytes = max_archive_bytes
        self.max_uncompressed_bytes = max_uncompressed_bytes
        self.max_member_bytes = max_member_bytes
        self.max_members = max_members

    def extract(self, archive_path: str | Path, *, arxiv_id: str, versioned_arxiv_id: str) -> ExtractionResult:
        start = time.monotonic()
        archive = Path(archive_path)
        destination = self.output_dir / _safe_part(arxiv_id) / _safe_part(versioned_arxiv_id)
        archive_bytes = archive.stat().st_size if archive.exists() else 0
        try:
            if not archive.is_file():
                raise ExtractionError("archive_missing")
            if archive_bytes > self.max_archive_bytes:
                raise ExtractionError("archive_size_limit")
            members = self._read_members(archive)
            total = sum(len(data) for _, data in members)
            if total > self.max_uncompressed_bytes:
                raise ExtractionError("uncompressed_size_limit")
            files: list[ExtractedFile] = []
            skipped = 0
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=f".{destination.name}.", dir=destination.parent) as tmp:
                staging = Path(tmp) / "payload"
                staging.mkdir()
                seen: set[str] = set()
                seen_case: set[str] = set()
                for raw_name, data in members:
                    rel = _validate_member_path(raw_name)
                    if rel is None:
                        skipped += 1
                        continue
                    if rel.suffix.lower() not in {".tex", ".bib"}:
                        skipped += 1
                        continue
                    if len(data) > self.max_member_bytes:
                        raise ExtractionError("member_size_limit")
                    normalized = rel.as_posix()
                    case_key = normalized.casefold()
                    if normalized in seen or case_key in seen_case:
                        raise ExtractionError(f"path_collision:{normalized}")
                    seen.add(normalized)
                    seen_case.add(case_key)
                    target = staging.joinpath(*rel.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as handle:
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                    files.append(ExtractedFile(normalized, len(data), hashlib.sha256(data).hexdigest()))
                backup = destination.with_name(destination.name + ".previous")
                if backup.exists():
                    shutil.rmtree(backup)
                had_previous = destination.exists()
                if had_previous:
                    destination.replace(backup)
                try:
                    staging.replace(destination)
                except Exception:
                    if had_previous and backup.exists():
                        backup.replace(destination)
                    raise
                if backup.exists():
                    shutil.rmtree(backup)
            status = "success" if files else "no_tex_bib"
            result = ExtractionResult(
                arxiv_id, versioned_arxiv_id, status, archive_bytes,
                sum(item.bytes for item in files), tuple(sorted(files, key=lambda x: x.path)),
                skipped, time.monotonic()-start,
            )
        except (OSError, tarfile.TarError, EOFError, gzip.BadGzipFile, ExtractionError, ValueError) as exc:
            message = str(exc)
            code = message.split(":", 1)[0] if message else type(exc).__name__
            result = ExtractionResult(
                arxiv_id, versioned_arxiv_id,
                "invalid_archive" if not isinstance(exc, OSError) or isinstance(exc, ExtractionError) else "io_error",
                archive_bytes, 0, (), 0, time.monotonic()-start, code, message,
            )
        _atomic_json(destination.parent / f"{destination.name}.extract_status.json", asdict(result))
        return result

    def _read_members(self, archive: Path) -> list[tuple[str, bytes]]:
        with archive.open("rb") as handle:
            magic = handle.read(4)
        if magic.startswith(b"\x1f\x8b"):
            try:
                with tarfile.open(archive, mode="r:gz") as tar:
                    return self._members_from_tar(tar)
            except tarfile.ReadError:
                # Some source responses are gzip-compressed single TeX/Bib files.
                raw = _bounded_gzip_read(archive, self.max_uncompressed_bytes)
                inferred = _infer_single_source_name(raw)
                return [(inferred, raw)]
        if tarfile.is_tarfile(archive):
            with tarfile.open(archive, mode="r:*") as tar:
                return self._members_from_tar(tar)
        raise ExtractionError("unsupported_payload")

    def _members_from_tar(self, tar: tarfile.TarFile) -> list[tuple[str, bytes]]:
        result: list[tuple[str, bytes]] = []
        count = 0
        total_uncompressed = 0
        for member in tar:
            count += 1
            if count > self.max_members:
                raise ExtractionError("member_count_limit")
            if not member.isfile():
                # Directories are implicit; links/devices/FIFOs are never followed.
                continue
            if member.size < 0 or member.size > self.max_member_bytes:
                if PurePosixPath(member.name).suffix.lower() in {".tex", ".bib"}:
                    raise ExtractionError("member_size_limit")
                continue
            if PurePosixPath(member.name.replace("\\", "/")).suffix.lower() not in {".tex", ".bib"}:
                continue
            stream = tar.extractfile(member)
            if stream is None:
                raise ExtractionError("member_read_failed")
            data = stream.read(self.max_member_bytes + 1)
            if len(data) != member.size or len(data) > self.max_member_bytes:
                raise ExtractionError("member_truncated_or_oversize")
            total_uncompressed += len(data)
            if total_uncompressed > self.max_uncompressed_bytes:
                raise ExtractionError("uncompressed_size_limit")
            result.append((member.name, data))
        return result


def _validate_member_path(name: str) -> PurePosixPath | None:
    if not isinstance(name, str) or not name or "\x00" in name:
        raise ExtractionError("invalid_member_path")
    # Tar paths are POSIX, but reject Windows absolute/drive/traversal forms too.
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ExtractionError(f"absolute_path:{name}")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ExtractionError(f"unsafe_path_component:{name}")
    path = PurePosixPath(*parts)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ExtractionError(f"path_escape:{name}")
    return path


def _bounded_gzip_read(path: Path, limit: int) -> bytes:
    chunks, size = [], 0
    with gzip.open(path, "rb") as handle:
        while True:
            chunk = handle.read(min(1024 * 128, limit - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ExtractionError("uncompressed_size_limit")
            chunks.append(chunk)
    return b"".join(chunks)


def _infer_single_source_name(raw: bytes) -> str:
    sample = raw[:8192].decode("utf-8", errors="ignore").lower()
    if "\\documentclass" in sample or "\\begin{document}" in sample:
        return "main.tex"
    if "@article" in sample or "@inproceedings" in sample or "@book" in sample:
        return "references.bib"
    raise ExtractionError("gzip_single_source_type_unknown")


def _safe_part(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise ValueError(f"Unsafe ID path component: {value!r}")
    return value


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)
