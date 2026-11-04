"""
Module s2_client.py: Crawl reference metadata từ Semantic Scholar Graph API (Milestone 1, R08-R10).
Thuộc sở hữu của Member 3 - Semantic Scholar, BibTeX và Reference Dedup.

Luồng: base arXiv ID -> gọi S2 (rate limit + retry) -> lưu TOÀN BỘ raw references cục bộ
-> lọc eligible references (có arXiv ID hợp lệ) cho bảng 'references'.

Nguồn API: https://api.semanticscholar.org/api-docs/graph (endpoint /graph/v1/paper/{paper_id}).
Giới hạn: S2 không phân biệt version arXiv, nên luôn query bằng base ID (không 'vN').
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Tuple

import requests

from src.normalize import (
    normalize_and_deduplicate_references,
    normalize_arxiv_id,
    normalize_authors,
    normalize_iso_date,
    normalize_text,
)

S2_PAPER_URL = "https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}"
# Chỉ dùng field phẳng 'references.<field>'; dạng lồng như 'references.authors.name' bị API từ chối
S2_FIELDS = ",".join([
    "references.paperId",
    "references.title",
    "references.authors",
    "references.year",
    "references.publicationDate",
    "references.externalIds",
])
API_KEY_ENV = "SEMANTIC_SCHOLAR_API_KEY"  # khớp config.py của M1

# Status cuối (terminal) của mỗi citing paper
STATUS_OK = "ok"
STATUS_NOT_FOUND = "not_found"          # 404: S2 chưa index paper
STATUS_RATE_LIMITED = "rate_limited"    # 429 sau khi hết retry
STATUS_SERVER_ERROR = "server_error"    # 5xx sau khi hết retry
STATUS_NETWORK_ERROR = "network_error"  # timeout / mất kết nối sau khi hết retry
STATUS_CLIENT_ERROR = "client_error"    # 4xx khác (vd 400 sai fields), không retry
STATUS_MALFORMED_JSON = "malformed_json"
STATUS_SCHEMA_ERROR = "schema_error"

# Paper đã có kết quả cuối -> rerun không gọi lại API; các status lỗi còn lại sẽ được thử lại
DONE_STATUSES = {STATUS_OK, STATUS_NOT_FOUND}
RETRYABLE_HTTP = {429, 500, 502, 503, 504}
MAX_BACKOFF_SEC = 60.0

# Modern: YYMM.NNNN(N); old-style: archive(.SUBJ)/YYMMNNN, vd 'hep-th/9901001', 'math.GT/0309136'
MODERN_ID_RE = re.compile(r"^\d{4}\.\d{4,5}$")
OLD_ID_RE = re.compile(r"^[a-z][a-z\-]*(\.[A-Z]{2})?/\d{7}$")


class RateLimiter:
    """
    Rate limiter trung tâm cho mọi request S2.
    Mặc định theo policy anonymous: tối đa 1 request/giây và 100 request/5 phút.
    clock/sleep có thể thay bằng fake clock khi test.
    """

    def __init__(
        self,
        min_interval: float = 1.0,
        max_requests: int = 100,
        window_sec: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.min_interval = min_interval
        self.max_requests = max_requests
        self.window_sec = window_sec
        self.clock = clock
        self.sleep = sleep
        self._history: Deque[float] = deque()

    def wait(self) -> None:
        """Chặn cho tới khi được phép gửi request tiếp theo, rồi ghi nhận thời điểm gửi."""
        now = self.clock()
        # Bỏ các request đã ra khỏi cửa sổ 5 phút
        while self._history and now - self._history[0] >= self.window_sec:
            self._history.popleft()

        delay = 0.0
        if self._history:
            delay = self._history[-1] + self.min_interval - now
        if len(self._history) >= self.max_requests:
            delay = max(delay, self._history[0] + self.window_sec - now)
        if delay > 0:
            self.sleep(delay)
        self._history.append(self.clock())


def build_paper_url(arxiv_id: str) -> str:
    """URL S2 cho một citing paper, luôn dùng base ID (bỏ version)."""
    return S2_PAPER_URL.format(arxiv_id=normalize_arxiv_id(arxiv_id))


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Header Retry-After dạng số giây; dạng khác thì bỏ qua và dùng backoff."""
    try:
        return max(0.0, float(value)) if value is not None else None
    except ValueError:
        return None


def fetch_paper_references(
    arxiv_id: str,
    session: Optional[Any] = None,
    limiter: Optional[RateLimiter] = None,
    api_key: Optional[str] = None,
    max_retries: int = 4,
    timeout: float = 30.0,
    backoff_base: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    """
    Gọi S2 cho một citing paper, có retry giới hạn (exponential backoff + jitter, ưu tiên Retry-After).
    Trả về: {status, http_status, attempts, references (list hoặc None), error}.
    API key chỉ nằm trong header, không bao giờ đưa vào kết quả/log.
    """
    session = session or requests.Session()
    limiter = limiter or RateLimiter()
    url = build_paper_url(arxiv_id)
    headers = {"x-api-key": api_key} if api_key else {}
    result: Dict[str, Any] = {
        "status": STATUS_NETWORK_ERROR,
        "http_status": None,
        "attempts": 0,
        "references": None,
        "error": None,
    }

    for attempt in range(1, max_retries + 1):
        result["attempts"] = attempt
        retry_after = None
        limiter.wait()
        try:
            resp = session.get(url, params={"fields": S2_FIELDS}, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            result.update(status=STATUS_NETWORK_ERROR, http_status=None, error=type(e).__name__)
        else:
            code = resp.status_code
            result["http_status"] = code
            if code == 200:
                return _parse_response(resp, result)
            if code == 404:
                result.update(status=STATUS_NOT_FOUND, error="paper not indexed by Semantic Scholar")
                return result
            if code not in RETRYABLE_HTTP:
                result.update(status=STATUS_CLIENT_ERROR, error=f"HTTP {code}")
                return result
            status = STATUS_RATE_LIMITED if code == 429 else STATUS_SERVER_ERROR
            result.update(status=status, error=f"HTTP {code}")
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))

        if attempt < max_retries:
            if retry_after is not None:
                delay = retry_after
            else:
                delay = backoff_base ** (attempt - 1) + random.uniform(0, 1)
            sleep(min(delay, MAX_BACKOFF_SEC))

    return result


def _parse_response(resp: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    """Kiểm tra response 200 một cách phòng vệ trước khi dùng."""
    try:
        payload = resp.json()
    except ValueError:
        result.update(status=STATUS_MALFORMED_JSON, error="response is not valid JSON")
        return result

    if not isinstance(payload, dict):
        result.update(status=STATUS_SCHEMA_ERROR, error="payload is not a JSON object")
        return result

    refs = payload.get("references")
    if refs is None:
        # S2 có thể trả null khi paper không có reference nào
        refs = []
    if not isinstance(refs, list):
        result.update(status=STATUS_SCHEMA_ERROR, error="'references' is not a list")
        return result

    result.update(status=STATUS_OK, references=refs, error=None)
    return result


def is_valid_arxiv_id(arxiv_id: Optional[str]) -> bool:
    """ID đã chuẩn hóa (không version) có đúng format modern hoặc old-style không."""
    if not arxiv_id:
        return False
    return bool(MODERN_ID_RE.match(arxiv_id) or OLD_ID_RE.match(arxiv_id))


def extract_ref_arxiv_id(external_ids: Any) -> Tuple[Optional[str], Optional[str]]:
    """
    Lấy arXiv ID của reference từ externalIds.ArXiv.
    Trả về (raw_value, normalized_id). normalized_id = None nếu thiếu hoặc sai format.
    Không suy đoán ID từ DOI/title.
    """
    if not isinstance(external_ids, dict):
        return None, None
    raw = external_ids.get("ArXiv")
    if not raw:
        return None, None
    normalized = normalize_arxiv_id(raw)
    return str(raw), (normalized if is_valid_arxiv_id(normalized) else None)


def build_raw_records(citing_id: str, references: Iterable[Any]) -> Tuple[List[Dict[str, Any]], int]:
    """
    Tạo raw record cho MỌI reference S2 trả về (kể cả thiếu arXiv ID, title/authors null).
    Giữ nguyên object S2 trong 's2' để provenance. Trả về (records, số item malformed).
    """
    records: List[Dict[str, Any]] = []
    parse_failures = 0
    for idx, ref in enumerate(references):
        if not isinstance(ref, dict):
            parse_failures += 1
            continue
        raw_id, ref_arxiv_id = extract_ref_arxiv_id(ref.get("externalIds"))
        records.append({
            "arxiv_id": citing_id,
            "ref_index": idx,
            "ref_arxiv_id_raw": raw_id,
            "ref_arxiv_id": ref_arxiv_id,
            "s2": ref,
        })
    return records, parse_failures


def to_eligible_records(raw_records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Map raw record có arXiv ID hợp lệ sang 6 field của bảng 'references'.
    ref_submission_date chỉ lấy từ publicationDate; KHÔNG suy từ 'year' (year không phải ngày nộp).
    """
    eligible = []
    for r in raw_records:
        if not r.get("ref_arxiv_id"):
            continue
        s2 = r.get("s2") or {}
        eligible.append({
            "arxiv_id": r["arxiv_id"],
            "ref_arxiv_id": r["ref_arxiv_id"],
            "ref_title": normalize_text(s2.get("title")),
            "ref_authors": normalize_authors(s2.get("authors")),
            "ref_submission_date": normalize_iso_date(s2.get("publicationDate")) or None,
            "ref_s2_id": s2.get("paperId") or None,
        })
    return eligible


def build_references_rows(raw_records: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Rows cuối cho bảng 'references' (dedup theo contract của M4). Trả về (rows, số duplicate)."""
    return normalize_and_deduplicate_references(to_eligible_records(raw_records))


def _cache_path(out_dir: Path, base_id: str) -> Path:
    # Old-style ID có '/', đổi thành '_' để làm tên file
    return out_dir / f"{base_id.replace('/', '_')}.json"


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """Ghi ra file tạm rồi rename, tránh file hỏng nếu bị ngắt giữa chừng."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def crawl_references(
    arxiv_ids: Iterable[str],
    out_dir: Path,
    session: Optional[Any] = None,
    limiter: Optional[RateLimiter] = None,
    api_key: Optional[str] = None,
    **fetch_kwargs: Any,
) -> List[Dict[str, Any]]:
    """
    Crawl references cho danh sách citing papers, mỗi paper lưu 1 file JSON trong out_dir:
    {"status": {...}, "references": [raw records]}.
    Idempotent: paper đã ok/not_found thì dùng lại cache; paper lỗi thì thử lại và ghi đè (không append).
    API key lấy từ tham số hoặc biến môi trường SEMANTIC_SCHOLAR_API_KEY; không có key vẫn chạy anonymous.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if api_key is None:
        api_key = os.environ.get(API_KEY_ENV) or None
    session = session or requests.Session()
    limiter = limiter or RateLimiter()

    statuses: List[Dict[str, Any]] = []
    seen: set = set()
    for raw_id in arxiv_ids:
        base_id = normalize_arxiv_id(raw_id)
        if not base_id or base_id in seen:
            continue
        seen.add(base_id)

        path = _cache_path(out_dir, base_id)
        cached = _load_json(path)
        if cached and cached.get("status", {}).get("status") in DONE_STATUSES:
            statuses.append(cached["status"])
            continue

        res = fetch_paper_references(base_id, session=session, limiter=limiter, api_key=api_key, **fetch_kwargs)
        refs = res["references"]
        records, parse_failures = build_raw_records(base_id, refs or [])
        status = {
            "arxiv_id": base_id,
            "status": res["status"],
            "http_status": res["http_status"],
            "attempts": res["attempts"],
            "error": res["error"],
            "queried_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "response_reference_count": len(refs) if refs is not None else None,
            "raw_reference_count": len(records),
            "parse_failures": parse_failures,
            "eligible_reference_count": sum(1 for r in records if r["ref_arxiv_id"]),
        }
        _atomic_write_json(path, {"status": status, "references": records})
        statuses.append(status)
    return statuses


def load_raw_references(out_dir: Path) -> List[Dict[str, Any]]:
    """Đọc lại toàn bộ raw records đã lưu trong out_dir."""
    records: List[Dict[str, Any]] = []
    for path in sorted(Path(out_dir).glob("*.json")):
        data = _load_json(path)
        if data:
            records.extend(data.get("references", []))
    return records


def summarize_s2_crawl(statuses: List[Dict[str, Any]], raw_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Metrics M1 phần references, mọi tỷ lệ đều kèm numerator/denominator.
    reference_metadata_success_rate (đề xuất, cần chốt với M4/M5) =
        số citing paper S2 trả về reference list thành công / số citing paper đã query.
    """
    attempted = len(statuses)
    succeeded = sum(1 for s in statuses if s["status"] == STATUS_OK)
    not_indexed = sum(1 for s in statuses if s["status"] == STATUS_NOT_FOUND)

    raw_total = len(raw_records)
    with_raw_id = sum(1 for r in raw_records if r.get("ref_arxiv_id_raw"))
    eligible = to_eligible_records(raw_records)
    rows, duplicates = normalize_and_deduplicate_references(eligible)

    return {
        "s2_citing_papers_attempted": attempted,
        "s2_citing_papers_succeeded": succeeded,
        "s2_citing_papers_not_indexed": not_indexed,
        "s2_citing_papers_failed": attempted - succeeded - not_indexed,
        "raw_references_total": raw_total,
        "raw_parse_failures": sum(s.get("parse_failures", 0) for s in statuses),
        "references_missing_arxiv_id": raw_total - with_raw_id,
        "references_invalid_arxiv_id": with_raw_id - len(eligible),
        "eligible_references_before_dedup": len(eligible),
        "duplicate_references": duplicates,
        "eligible_references_final": len(rows),
        "eligible_missing_title": sum(1 for r in rows if not r["ref_title"]),
        "eligible_missing_authors": sum(1 for r in rows if not r["ref_authors"]),
        "eligible_missing_submission_date": sum(1 for r in rows if not r["ref_submission_date"]),
        "avg_all_references_per_paper": round(raw_total / max(1, succeeded), 2),
        "avg_eligible_arxiv_references_per_paper": round(len(rows) / max(1, succeeded), 2),
        "reference_metadata_success_rate": {
            "numerator": succeeded,
            "denominator": attempted,
            "value": round(succeeded / max(1, attempted), 4),
        },
    }


def main(argv: Optional[List[str]] = None) -> None:
    """
    Chạy S2 crawl độc lập (khi chưa có pipeline của M1), vd:
        python -m src.s2_client --ids 1810.04805 1706.03762 --out data/s2_raw
        python -m src.s2_client --ids-file data/expanded_ids.txt --out data/s2_raw
    """
    import argparse

    parser = argparse.ArgumentParser(description="Crawl Semantic Scholar references cho danh sách arXiv ID.")
    parser.add_argument("--ids", nargs="*", default=[], help="Các arXiv ID cách nhau bởi dấu cách")
    parser.add_argument("--ids-file", type=Path, help="File chứa mỗi dòng một arXiv ID")
    parser.add_argument("--out", type=Path, default=Path("data/s2_raw"), help="Thư mục lưu raw JSON")
    parser.add_argument("--max-retries", type=int, default=4)
    args = parser.parse_args(argv)

    ids = list(args.ids)
    if args.ids_file:
        ids += [line.strip() for line in args.ids_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not ids:
        parser.error("cần --ids hoặc --ids-file")

    statuses = crawl_references(ids, args.out, max_retries=args.max_retries)
    for s in statuses:
        print(f"{s['arxiv_id']}\t{s['status']}\traw={s['raw_reference_count']}\teligible={s['eligible_reference_count']}")
    # Chỉ tổng hợp các paper của lần chạy này, không lẫn file cũ khác trong out
    raw_records: List[Dict[str, Any]] = []
    for s in statuses:
        data = _load_json(_cache_path(args.out, s["arxiv_id"])) or {}
        raw_records.extend(data.get("references", []))
    summary = summarize_s2_crawl(statuses, raw_records)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
