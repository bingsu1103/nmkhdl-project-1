"""Resolve latest arXiv metadata into deterministic per-version tasks."""

from __future__ import annotations

import re

from .contracts import PaperMetadata, VersionTask

VERSIONED_ID_PATTERN = re.compile(r"^(?P<base>.+?)v(?P<version>[1-9]\d*)$")


class VersionResolutionError(ValueError):
    """Raised when arXiv metadata cannot safely determine all versions."""


def resolve_version_tasks(metadata: PaperMetadata, *, member_id: str) -> list[VersionTask]:
    match = VERSIONED_ID_PATTERN.fullmatch(metadata.latest_versioned_id)
    if match is None:
        raise VersionResolutionError(
            f"Latest arXiv ID lacks a valid version suffix: {metadata.latest_versioned_id}"
        )
    if match.group("base") != metadata.arxiv_id:
        raise VersionResolutionError(
            "Latest versioned ID does not match the canonical base arXiv ID."
        )

    latest = int(match.group("version"))
    return [
        VersionTask(
            member_id=member_id,
            arxiv_id=metadata.arxiv_id,
            versioned_arxiv_id=f"{metadata.arxiv_id}v{version}",
            version=version,
        )
        for version in range(1, latest + 1)
    ]
