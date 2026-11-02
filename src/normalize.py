"""
Module normalize.py: Chuẩn hóa dữ liệu văn bản, ngày tháng, arXiv ID và khử trùng lặp.
Thuộc sở hữu của Member 4 - Data Quality, Schema và Storage Owner.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple


def normalize_text(text: Optional[str]) -> str:
    """
    Chuẩn hóa chuỗi văn bản: Xóa khoảng trắng thừa đầu cuối, chuẩn hóa newline.
    """
    if text is None:
        return ""
    # Chuyển đổi mọi chuỗi whitespace liên tiếp thành 1 dấu cách duy nhất
    cleaned = re.sub(r"\s+", " ", str(text)).strip()
    return cleaned


def normalize_arxiv_id(raw_id: Optional[str], keep_version: bool = False) -> str:
    """
    Chuẩn hóa arXiv ID:
    - Bỏ tiền tố URL (vd: 'https://export.arxiv.org/abs/2310.12345v2' -> '2310.12345v2')
    - Bỏ đuôi .pdf nếu có
    - Nếu keep_version=False: Bỏ hậu tố phiên bản 'vN' (vd: '2310.12345v2' -> '2310.12345')
    - Hỗ trợ cả new-style (YYMM.NNNNN) và old-style (archive/YYMMNNN, vd: 'hep-th/9901001')
    """
    if not raw_id:
        return ""

    s = str(raw_id).strip()
    # Loại bỏ tiền tố URL (hỗ trợ cả domain arxiv.org và export.arxiv.org mirror)
    s = re.sub(r"^https?://(?:export\.)?arxiv\.org/(abs|pdf|src)/", "", s, flags=re.IGNORECASE)
    # Loại bỏ tiền tố 'arxiv:' nếu có
    s = re.sub(r"^arxiv:\s*", "", s, flags=re.IGNORECASE)
    # Bỏ đuôi .pdf nếu bị dính
    s = re.sub(r"\.pdf$", "", s, flags=re.IGNORECASE)

    if not keep_version:
        # Bỏ hậu tố v1, v2,... ở cuối ID
        s = re.sub(r"v\d+$", "", s, flags=re.IGNORECASE)

    return s.strip()


def normalize_iso_date(raw_date: Optional[Any]) -> str:
    """
    Chuẩn hóa định dạng ngày tháng về chuẩn ISO-8601 (UTC, đuôi Z).
    Hỗ trợ:
    - Đối tượng datetime.datetime (có hoặc không có tzinfo) từ arxiv API.
    - Chuỗi datetime có khoảng trắng: '2023-10-15 12:00:00+00:00'.
    - Chuỗi ISO đầy đủ có microsecond và offset.
    - Các format văn bản RFC / date chuẩn thường gặp.
    """
    if not raw_date:
        return ""

    # 1. Nếu đã là datetime object (từ arxiv API hoặc dateutil)
    if hasattr(raw_date, "strftime"):
        dt = raw_date
        if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        else:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    s = str(raw_date).strip()

    # 2. Chuẩn hóa dấu cách thành 'T' nếu có dạng 'YYYY-MM-DD HH:MM:SS...'
    if re.match(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", s):
        s = s.replace(" ", "T", 1)

    # 3. Khớp chuỗi ISO chuẩn (kể cả có microsecond và offset)
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$", s):
        try:
            # Parse để đưa toàn bộ về chuẩn UTC đuôi Z thống nhất
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return s

    formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y/%m/%d",
        "%Y.%m.%d",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue

    if re.match(r"^\d{4}$", s):
        return f"{s}-01-01T00:00:00Z"
    if re.match(r"^\d{4}-\d{2}$", s):
        return f"{s}-01T00:00:00Z"

    return s


def normalize_authors(authors: Optional[Any]) -> List[str]:
    """
    Chuẩn hóa danh sách tác giả: Đảm bảo là List[str] sạch sẽ, giữ nguyên thứ tự.
    Xử lý an toàn nếu đầu vào là một chuỗi đơn lẻ thay vì list để tránh bị cắt vụn từng ký tự.
    """
    if not authors:
        return []

    # Chống lỗi cắt vụn ký tự nếu crawler truyền vào 1 string đơn lẻ
    if isinstance(authors, str):
        authors = [authors]

    result = []
    for a in authors:
        if isinstance(a, dict):
            # Nếu Semantic Scholar trả về dạng dict {'name': '...'}
            name = a.get("name", "")
        else:
            # Tương thích với đối tượng arxiv.Result hoặc string
            name = getattr(a, "name", str(a))
        cleaned = normalize_text(name)
        if cleaned:
            result.append(cleaned)
    return result


def normalize_paper_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Chuẩn hóa một record bài báo cho bảng 'papers':
    - arxiv_id (bỏ version)
    - title (clean)
    - authors (list of str)
    - submission_date (ISO)
    - revised_dates (list of ISO)
    - venue (clean or None)
    """
    arxiv_id = normalize_arxiv_id(record.get("arxiv_id"))
    title = normalize_text(record.get("title"))
    authors = normalize_authors(record.get("authors"))
    submission_date = normalize_iso_date(record.get("submission_date"))

    # Dùng 'or []' để chống lỗi TypeError nếu record có 'revised_dates': None
    raw_revised = record.get("revised_dates") or []
    if isinstance(raw_revised, str):
        raw_revised = [raw_revised]
    revised_dates = [normalize_iso_date(d) for d in raw_revised if d]

    venue = record.get("venue")
    cleaned_venue = normalize_text(venue) if venue else None

    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "authors": authors,
        "submission_date": submission_date,
        "revised_dates": revised_dates,
        "venue": cleaned_venue,
    }


def normalize_and_deduplicate_references(
    references: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Chuẩn hóa và khử trùng lặp cho các tài liệu tham khảo trong bảng 'references':
    - Chỉ giữ các reference CÓ ref_arxiv_id (eligible arXiv references).
    - Cặp (arxiv_id, ref_arxiv_id) là duy nhất cho mỗi bài báo trích dẫn.
    - Trả về: (danh_sách_references_hợp_lệ, số_lượng_bản_ghi_bị_loại)
    """
    seen_pairs: Set[Tuple[str, str]] = set()
    cleaned_refs: List[Dict[str, Any]] = []
    dropped_count = 0

    for ref in references:
        arxiv_id = normalize_arxiv_id(ref.get("arxiv_id"))

        # Phòng vệ: hỗ trợ cả ref_arxiv_id hoặc externalIds.ArXiv từ Semantic Scholar
        raw_ref_arxiv_id = ref.get("ref_arxiv_id")
        if not raw_ref_arxiv_id and isinstance(ref.get("externalIds"), dict):
            ext_ids = ref["externalIds"]
            raw_ref_arxiv_id = ext_ids.get("ArXiv") or ext_ids.get("arxiv") or ext_ids.get("ARXIV")
        ref_arxiv_id = normalize_arxiv_id(raw_ref_arxiv_id)

        # Điều kiện tiên quyết: Cả 2 ID đều không được rỗng
        if not arxiv_id or not ref_arxiv_id:
            dropped_count += 1
            continue

        pair_key = (arxiv_id, ref_arxiv_id)
        if pair_key in seen_pairs:
            # Trùng lặp tài liệu được trích dẫn trong cùng một bài báo
            dropped_count += 1
            continue

        seen_pairs.add(pair_key)

        # Phòng vệ tên trường: hỗ trợ cả format chuẩn lẫn format thô từ S2 (paperId, publicationDate, title, authors)
        ref_title = normalize_text(ref.get("ref_title") or ref.get("title"))
        ref_authors = normalize_authors(ref.get("ref_authors") or ref.get("authors"))
        raw_date = ref.get("ref_submission_date") or ref.get("publicationDate") or ref.get("year")
        ref_sub_date = normalize_iso_date(raw_date) or None
        ref_s2_id = normalize_text(ref.get("ref_s2_id") or ref.get("paperId")) or None

        cleaned_refs.append({
            "arxiv_id": arxiv_id,
            "ref_arxiv_id": ref_arxiv_id,
            "ref_title": ref_title,
            "ref_authors": ref_authors,
            "ref_submission_date": ref_sub_date,
            "ref_s2_id": ref_s2_id,
        })

    return cleaned_refs, dropped_count
