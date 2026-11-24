"""Batch integration for Semantic Scholar reference crawling.

The underlying record normalization remains in ``s2_client`` (Member 3).  This
Member 1 orchestration adapter uses the official ``/paper/batch`` endpoint and
persists the exact same per-paper cache contract, reducing full-shard runtime
without changing downstream artifacts.
"""

from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

from .normalize import normalize_arxiv_id
from .s2_client import (
    API_KEY_ENV,
    DONE_STATUSES,
    MAX_BACKOFF_SEC,
    S2_FIELDS,
    STATUS_CLIENT_ERROR,
    STATUS_MALFORMED_JSON,
    STATUS_NETWORK_ERROR,
    STATUS_NOT_FOUND,
    STATUS_OK,
    STATUS_RATE_LIMITED,
    STATUS_SCHEMA_ERROR,
    STATUS_SERVER_ERROR,
    RateLimiter,
    build_raw_records,
)

S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"


def crawl_references_batch(
    arxiv_ids: Iterable[str],
    out_dir: str | Path,
    *,
    batch_size: int = 10,
    session: Any | None = None,
    limiter: RateLimiter | None = None,
    api_key: str | None = None,
    max_retries: int = 8,
    timeout: float = 60.0,
    sleep: Any = time.sleep,
) -> list[dict[str, Any]]:
    if batch_size <= 0 or batch_size > 500:
        raise ValueError("Semantic Scholar batch_size must be in 1..500")
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    session = session or requests.Session()
    limiter = limiter or RateLimiter()
    api_key = api_key if api_key is not None else os.environ.get(API_KEY_ENV) or None

    ordered_ids: list[str] = []
    seen: set[str] = set()
    statuses: dict[str, dict[str, Any]] = {}
    for raw_id in arxiv_ids:
        aid = normalize_arxiv_id(raw_id)
        if not aid or aid in seen:
            continue
        seen.add(aid)
        ordered_ids.append(aid)
        cached = _load_json(_cache_path(output, aid))
        if cached and cached.get("status", {}).get("status") in DONE_STATUSES:
            statuses[aid] = cached["status"]

    pending = [aid for aid in ordered_ids if aid not in statuses]
    for start in range(0, len(pending), batch_size):
        ids = pending[start : start + batch_size]
        response = _fetch_batch(
            ids,
            session=session,
            limiter=limiter,
            api_key=api_key,
            max_retries=max_retries,
            timeout=timeout,
            sleep=sleep,
        )
        if response["status"] != STATUS_OK:
            for aid in ids:
                status = _status_record(aid, response, references=None)
                _write_json_atomic(_cache_path(output, aid), {"status": status, "references": []})
                statuses[aid] = status
            continue

        papers = response["papers"]
        for aid, paper in zip(ids, papers):
            if paper is None:
                per_paper = {
                    "status": STATUS_NOT_FOUND,
                    "http_status": 200,
                    "attempts": response["attempts"],
                    "error": "paper not indexed by Semantic Scholar",
                }
                refs = None
            elif not isinstance(paper, dict):
                per_paper = {
                    "status": STATUS_SCHEMA_ERROR,
                    "http_status": 200,
                    "attempts": response["attempts"],
                    "error": "batch item is not an object",
                }
                refs = None
            else:
                refs = paper.get("references")
                if refs is None:
                    refs = []
                per_paper = {
                    "status": STATUS_OK if isinstance(refs, list) else STATUS_SCHEMA_ERROR,
                    "http_status": 200,
                    "attempts": response["attempts"],
                    "error": None if isinstance(refs, list) else "'references' is not a list",
                }
                if not isinstance(refs, list):
                    refs = None
            raw_records, parse_failures = build_raw_records(aid, refs or [])
            status = _status_record(
                aid, per_paper, references=refs, parse_failures=parse_failures,
                eligible_count=sum(1 for row in raw_records if row["ref_arxiv_id"]),
            )
            _write_json_atomic(
                _cache_path(output, aid), {"status": status, "references": raw_records}
            )
            statuses[aid] = status
    return [statuses[aid] for aid in ordered_ids]


def _fetch_batch(
    ids: list[str],
    *,
    session: Any,
    limiter: RateLimiter,
    api_key: str | None,
    max_retries: int,
    timeout: float,
    sleep: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": STATUS_NETWORK_ERROR,
        "http_status": None,
        "attempts": 0,
        "error": None,
        "papers": None,
    }
    headers = {"x-api-key": api_key} if api_key else {}
    for attempt in range(1, max_retries + 1):
        result["attempts"] = attempt
        limiter.wait()
        retry_after = None
        try:
            response = session.post(
                S2_BATCH_URL,
                params={"fields": S2_FIELDS},
                json={"ids": [f"ARXIV:{aid}" for aid in ids]},
                headers=headers,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            result.update(status=STATUS_NETWORK_ERROR, error=type(exc).__name__)
        else:
            result["http_status"] = response.status_code
            if response.status_code == 200:
                try:
                    papers = response.json()
                except ValueError:
                    result.update(status=STATUS_MALFORMED_JSON, error="response is not valid JSON")
                else:
                    if isinstance(papers, list) and len(papers) == len(ids):
                        result.update(status=STATUS_OK, error=None, papers=papers)
                        return result
                    result.update(status=STATUS_SCHEMA_ERROR, error="batch response length/type mismatch")
                    return result
            elif response.status_code == 429:
                result.update(status=STATUS_RATE_LIMITED, error="HTTP 429")
                try:
                    retry_after = float(response.headers.get("Retry-After"))
                except (TypeError, ValueError):
                    retry_after = None
            elif response.status_code in {500, 502, 503, 504}:
                result.update(status=STATUS_SERVER_ERROR, error=f"HTTP {response.status_code}")
            else:
                result.update(status=STATUS_CLIENT_ERROR, error=f"HTTP {response.status_code}")
                return result
        if attempt < max_retries:
            delay = retry_after if retry_after is not None else 2 ** (attempt - 1) + random.random()
            sleep(min(delay, MAX_BACKOFF_SEC))
    return result


def _status_record(
    aid: str,
    result: dict[str, Any],
    *,
    references: list[Any] | None,
    parse_failures: int = 0,
    eligible_count: int = 0,
) -> dict[str, Any]:
    return {
        "arxiv_id": aid,
        "status": result["status"],
        "http_status": result.get("http_status"),
        "attempts": result.get("attempts", 0),
        "error": result.get("error"),
        "queried_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "response_reference_count": len(references) if references is not None else None,
        "raw_reference_count": len(references) if references is not None else 0,
        "parse_failures": parse_failures,
        "eligible_reference_count": eligible_count,
    }


def _cache_path(out_dir: Path, aid: str) -> Path:
    return out_dir / f"{aid.replace('/', '_')}.json"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
