"""
Module features.py: Feature Engineering cho Reference Matching Pipeline (Milestone 3).
Thuộc sở hữu của Member 4 - Data Quality, Matching Model và Evaluation.

Nhiệm vụ:
- Trích xuất các đặc trưng tương đồng văn bản, tác giả, thời gian, định danh giữa BibTeX entry và Candidate reference.
- Phục vụ cho cả Heuristic Weighted Ranker và Machine Learning Models (Logistic Regression / LightGBM).
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from src.normalize import normalize_arxiv_id, normalize_text

# ==============================================================================
# HẰNG SỐ VÀ DANH SÁCH ĐẶC TRƯNG CHUẨN
# ==============================================================================

STOPWORDS: Set[str] = {
    "a", "an", "the", "in", "on", "of", "for", "to", "and", "with", "is", "by",
    "from", "at", "as", "into", "through", "during", "using", "via", "based",
}

FEATURE_NAMES: List[str] = [
    "title_token_jaccard",
    "title_token_overlap",
    "title_edit_ratio",
    "first_author_match",
    "author_set_overlap",
    "year_diff",
    "year_exact_match",
    "year_proximity",
    "doi_match",
    "arxiv_id_match",
    "venue_token_overlap",
]


# ==============================================================================
# 1. CÁC HÀM TIỀN XỬ LÝ VÀ CHUẨN HÓA TRƯỜNG THUỘC TÍNH
# ==============================================================================

def clean_tokens(text: Optional[str]) -> Set[str]:
    """
    Tách từ chuẩn hóa cho tiêu đề hoặc venue:
    Chuyển về chữ thường, bỏ dấu câu và loại bỏ stop-words tiếng Anh phổ biến.
    """
    if not text:
        return set()
    clean = re.sub(r"[^\w\s]", " ", str(text).lower())
    words = clean.split()
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def extract_author_tokens(raw_authors: Any) -> Tuple[Optional[str], Set[str]]:
    """
    Trích xuất họ của tác giả đầu tiên và tập hợp họ của tất cả tác giả.
    Hỗ trợ xử lý an toàn:
    - Danh sách chuỗi: ["Ashish Vaswani", "Noam Shazeer"]
    - Danh sách dictionary từ Semantic Scholar: [{"name": "Ashish Vaswani"}]
    - Chuỗi BibTeX chuẩn: "Vaswani, Ashish and Shazeer, Noam"
    """
    if not raw_authors:
        return None, set()

    author_names: List[str] = []
    if isinstance(raw_authors, list):
        for a in raw_authors:
            if not a:
                continue
            name = a.get("name", "") if isinstance(a, dict) else str(a)
            name = name.strip()
            if name:
                author_names.append(name)
    elif isinstance(raw_authors, str):
        parts = re.split(r"\s+and\s+|;", raw_authors, flags=re.IGNORECASE)
        author_names = [p.strip() for p in parts if p.strip()]

    last_names: List[str] = []
    for full_name in author_names:
        # Nếu định dạng BibTeX "Họ, Tên"
        if "," in full_name:
            last = full_name.split(",")[0].strip().lower()
        else:
            tokens = full_name.strip().lower().split()
            last = tokens[-1] if tokens else ""
        # Loại bỏ ký tự đặc biệt khỏi họ
        last = re.sub(r"[^\w]", "", last)
        if last:
            last_names.append(last)

    first_author_last = last_names[0] if last_names else None
    return first_author_last, set(last_names)


def extract_year(raw_year: Any) -> Optional[int]:
    """
    Trích xuất năm xuất bản hợp lệ trong khoảng 1800 - 2050.
    Hỗ trợ cả số nguyên lẫn chuỗi có chứa năm.
    """
    if raw_year is None:
        return None
    try:
        y = int(str(raw_year).strip())
        if 1800 <= y <= 2050:
            return y
    except (ValueError, TypeError):
        pass

    # Tìm 4 chữ số liên tiếp
    m = re.search(r"\b(19\d{2}|20\d{2})\b", str(raw_year))
    if m:
        return int(m.group(1))
    return None


def normalize_doi(raw_doi: Optional[str]) -> str:
    """
    Chuẩn hóa DOI: Loại bỏ URL prefix và đưa về dạng chữ thường.
    Ví dụ: 'https://doi.org/10.1145/1234' -> '10.1145/1234'
    """
    if not raw_doi:
        return ""
    s = str(raw_doi).strip().lower()
    s = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", s)
    s = re.sub(r"^doi:\s*", "", s)
    return s.strip()


# ==============================================================================
# 2. TRÍCH XUẤT ĐẶC TRƯNG CHO MỘT CẶP (BIBTEX, CANDIDATE)
# ==============================================================================

def extract_pair_features(
    bib_entry: Dict[str, Any],
    candidate_ref: Dict[str, Any],
) -> Dict[str, float]:
    """
    Trích xuất toàn bộ 11 đặc trưng số học cho một cặp (BibTeX entry, Candidate reference).
    Tất cả các giá trị trả về đều là kiểu số thực (float), an toàn trước null/None.
    """
    # --------------------------------------------------------------------------
    # A. Title Similarities
    # --------------------------------------------------------------------------
    bib_title = normalize_text(bib_entry.get("title", ""))
    ref_title = normalize_text(candidate_ref.get("ref_title") or candidate_ref.get("title", ""))

    bib_tokens = clean_tokens(bib_title)
    ref_tokens = clean_tokens(ref_title)

    if bib_tokens and ref_tokens:
        inter = bib_tokens.intersection(ref_tokens)
        union = bib_tokens.union(ref_tokens)
        title_token_jaccard = len(inter) / len(union) if union else 0.0
        min_len = min(len(bib_tokens), len(ref_tokens))
        title_token_overlap = len(inter) / min_len if min_len > 0 else 0.0
    else:
        title_token_jaccard = 0.0
        title_token_overlap = 0.0

    # Character-level Levenshtein edit ratio
    clean_bt = re.sub(r"[^\w\s]", "", bib_title.lower()).strip()
    clean_rt = re.sub(r"[^\w\s]", "", ref_title.lower()).strip()
    if clean_bt and clean_rt:
        title_edit_ratio = difflib.SequenceMatcher(None, clean_bt, clean_rt).ratio()
    else:
        title_edit_ratio = 0.0

    # --------------------------------------------------------------------------
    # B. Author Matching
    # --------------------------------------------------------------------------
    bib_first, bib_authors = extract_author_tokens(bib_entry.get("authors"))
    ref_first, ref_authors = extract_author_tokens(candidate_ref.get("ref_authors") or candidate_ref.get("authors"))

    first_author_match = 1.0 if (bib_first and ref_first and bib_first == ref_first) else 0.0

    if bib_authors and ref_authors:
        author_inter = bib_authors.intersection(ref_authors)
        author_union = bib_authors.union(ref_authors)
        author_set_overlap = len(author_inter) / len(author_union) if author_union else 0.0
    else:
        author_set_overlap = 0.0

    # --------------------------------------------------------------------------
    # C. Year Features (Hỗ trợ đọc cả ref_submission_date từ M1)
    # --------------------------------------------------------------------------
    bib_y = extract_year(bib_entry.get("year"))
    ref_y = extract_year(
        candidate_ref.get("ref_year")
        or candidate_ref.get("year")
        or candidate_ref.get("ref_submission_date")
        or candidate_ref.get("publicationDate")
    )

    if bib_y is not None and ref_y is not None:
        diff = float(abs(bib_y - ref_y))
        year_diff = diff
        year_exact_match = 1.0 if diff == 0.0 else 0.0
        year_proximity = max(0.0, 1.0 - (diff / 5.0))
    else:
        year_diff = 5.0  # Giá trị mặc định khi thiếu năm
        year_exact_match = 0.0
        year_proximity = 0.0

    # --------------------------------------------------------------------------
    # D. Identifiers Matching (DOI & arXiv ID)
    # --------------------------------------------------------------------------
    ext_ids = candidate_ref.get("externalIds") if isinstance(candidate_ref.get("externalIds"), dict) else {}
    bib_doi = normalize_doi(bib_entry.get("doi"))
    ref_doi = normalize_doi(candidate_ref.get("doi") or ext_ids.get("DOI"))
    doi_match = 1.0 if (bib_doi and ref_doi and bib_doi == ref_doi) else 0.0

    # Chỉ tìm arXiv ID của bài được trích dẫn (không lấy bib_entry['arxiv_id'] vì đó là bài mẹ)
    bib_eprint = normalize_arxiv_id(bib_entry.get("eprint"))
    if not bib_eprint and "arxiv" in str(bib_entry.get("url", "")).lower():
        bib_eprint = normalize_arxiv_id(bib_entry.get("url"))
    if not bib_eprint and "arxiv" in str(bib_entry.get("journal", "")).lower():
        m = re.search(r"\b(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[a-z]{2})?/\d{7})\b", str(bib_entry.get("journal")), re.I)
        if m:
            bib_eprint = normalize_arxiv_id(m.group(1))

    cand_aid = normalize_arxiv_id(candidate_ref.get("ref_arxiv_id") or ext_ids.get("ArXiv"))
    arxiv_id_match = 1.0 if (bib_eprint and cand_aid and bib_eprint == cand_aid) else 0.0

    # --------------------------------------------------------------------------
    # E. Venue / Journal Overlap (Tách biến an toàn độ ưu tiên toán tử)
    # --------------------------------------------------------------------------
    bib_venue = str(bib_entry.get("journal") or bib_entry.get("booktitle") or bib_entry.get("venue") or "")
    
    ref_j = candidate_ref.get("journal")
    ref_j_name = ref_j.get("name", "") if isinstance(ref_j, dict) else str(ref_j or "")
    ref_venue = str(candidate_ref.get("venue") or ref_j_name or "")

    v_bib_tokens = clean_tokens(bib_venue)
    v_ref_tokens = clean_tokens(ref_venue)
    if v_bib_tokens and v_ref_tokens:
        v_inter = v_bib_tokens.intersection(v_ref_tokens)
        venue_token_overlap = len(v_inter) / min(len(v_bib_tokens), len(v_ref_tokens))
    else:
        venue_token_overlap = 0.0

    return {
        "title_token_jaccard": round(title_token_jaccard, 4),
        "title_token_overlap": round(title_token_overlap, 4),
        "title_edit_ratio": round(title_edit_ratio, 4),
        "first_author_match": float(first_author_match),
        "author_set_overlap": round(author_set_overlap, 4),
        "year_diff": float(year_diff),
        "year_exact_match": float(year_exact_match),
        "year_proximity": round(year_proximity, 4),
        "doi_match": float(doi_match),
        "arxiv_id_match": float(arxiv_id_match),
        "venue_token_overlap": round(venue_token_overlap, 4),
    }


def extract_feature_vector(
    bib_entry: Dict[str, Any],
    candidate_ref: Dict[str, Any],
) -> List[float]:
    """
    Trích xuất vector đặc trưng dưới dạng danh sách float theo thứ tự cố định FEATURE_NAMES.
    """
    f_dict = extract_pair_features(bib_entry, candidate_ref)
    return [f_dict[name] for name in FEATURE_NAMES]


def extract_candidate_feature_matrix(
    bib_entries: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
) -> Tuple[List[List[float]], List[Dict[str, Any]]]:
    """
    Trích xuất ma trận đặc trưng cho các cặp (BibTeX, Candidate) thuộc cùng publication.
    Trả về:
    - X: Ma trận đặc trưng 2 chiều (N x len(FEATURE_NAMES)).
    - metadata: Danh sách metadata tương ứng cho mỗi hàng (arxiv_id, citation_key, ref_arxiv_id).
    """
    # Gom nhóm candidates theo publication arxiv_id
    cand_by_pub: Dict[str, List[Dict[str, Any]]] = {}
    for c in candidates:
        aid = normalize_arxiv_id(c.get("arxiv_id"))
        if aid:
            cand_by_pub.setdefault(aid, []).append(c)

    X: List[List[float]] = []
    meta: List[Dict[str, Any]] = []

    for entry in bib_entries:
        pub_id = normalize_arxiv_id(entry.get("arxiv_id"))
        ckey = str(entry.get("citation_key", ""))
        cands = cand_by_pub.get(pub_id, [])

        for c in cands:
            c_aid = normalize_arxiv_id(c.get("ref_arxiv_id"))
            if not c_aid:
                continue
            features = extract_feature_vector(entry, c)
            X.append(features)
            meta.append({
                "arxiv_id": pub_id,
                "citation_key": ckey,
                "ref_arxiv_id": c_aid,
            })

    return X, meta
