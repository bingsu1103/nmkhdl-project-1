"""
Module features.py: Feature Engineering cho Reference Matching Pipeline (Milestone 3).
Thuộc sở hữu của Member 4 - Data Quality, Matching Model và Evaluation.

Nhiệm vụ:
- Trích xuất các đặc trưng tương đồng văn bản, tác giả, thời gian, định danh giữa BibTeX entry và Candidate reference.
- Phục vụ cho cả Heuristic Weighted Ranker và Machine Learning Models (Logistic Regression / LightGBM).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from rapidfuzz.distance import Levenshtein

from src.normalize import normalize_arxiv_id, normalize_text

# ==============================================================================
# HẰNG SỐ VÀ DANH SÁCH ĐẶC TRƯNG CHUẨN
# ==============================================================================

STOPWORDS: Set[str] = {
    "a", "an", "the", "in", "on", "of", "for", "to", "and", "with", "is", "by",
    "from", "at", "as", "into", "through", "during", "using", "via", "based",
}

IGNORED_AUTHOR_TOKENS: Set[str] = {"others", "etal", "al"}

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


def _normalize_author_name(name: str) -> str:
    s = normalize_text(name)
    s = re.sub(r'\\["\'`^~=.uvHcbtkd]\s*\{?([a-zA-Z])\}?', r"\1", s)
    s = s.replace("{", "").replace("}", "")
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


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
        clean_name = _normalize_author_name(full_name)
        # Nếu định dạng BibTeX "Họ, Tên"
        if "," in clean_name:
            last = clean_name.split(",")[0].strip().lower()
        else:
            tokens = clean_name.strip().lower().split()
            last = tokens[-1] if tokens else ""
        # Loại bỏ ký tự đặc biệt khỏi họ và lọc từ khóa giữ chỗ BibTeX (others / et al.)
        last = re.sub(r"[^\w]", "", last)
        if last and last not in IGNORED_AUTHOR_TOKENS:
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

def _prepare_bib_entry(bib_entry: Dict[str, Any]) -> Dict[str, Any]:
    bib_title = normalize_text(bib_entry.get("title") or "")
    bib_tokens = clean_tokens(bib_title)
    clean_bt = re.sub(r"[^\w\s]", "", bib_title.lower()).strip()
    bib_first, bib_authors = extract_author_tokens(bib_entry.get("authors"))
    bib_y = extract_year(bib_entry.get("year"))
    bib_doi = normalize_doi(bib_entry.get("doi"))

    bib_eprint = normalize_arxiv_id(bib_entry.get("eprint"))
    if not bib_eprint and "arxiv" in str(bib_entry.get("url") or "").lower():
        bib_eprint = normalize_arxiv_id(bib_entry.get("url"))
    if not bib_eprint:
        extra_text = " ".join(str(bib_entry.get(k) or "") for k in ("journal", "booktitle", "note"))
        if "arxiv" in extra_text.lower():
            m = re.search(r"\b(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[a-z]{2})?/\d{7})\b", extra_text, re.I)
            if m:
                bib_eprint = normalize_arxiv_id(m.group(1))

    bib_venue = str(bib_entry.get("journal") or bib_entry.get("booktitle") or bib_entry.get("venue") or "")
    v_bib_tokens = clean_tokens(bib_venue)
    return {
        "tokens": bib_tokens,
        "clean_title": clean_bt,
        "first_author": bib_first,
        "authors": bib_authors,
        "year": bib_y,
        "doi": bib_doi,
        "eprint": bib_eprint,
        "venue_tokens": v_bib_tokens,
    }


def _prepare_candidate_ref(candidate_ref: Dict[str, Any]) -> Dict[str, Any]:
    ref_title = normalize_text(candidate_ref.get("ref_title") or candidate_ref.get("title") or "")
    ref_tokens = clean_tokens(ref_title)
    clean_rt = re.sub(r"[^\w\s]", "", ref_title.lower()).strip()
    ref_first, ref_authors = extract_author_tokens(candidate_ref.get("ref_authors") or candidate_ref.get("authors"))
    ref_y = extract_year(
        candidate_ref.get("ref_year")
        or candidate_ref.get("year")
        or candidate_ref.get("ref_submission_date")
        or candidate_ref.get("publicationDate")
    )
    ext_ids = candidate_ref.get("externalIds") if isinstance(candidate_ref.get("externalIds"), dict) else {}
    ref_doi = normalize_doi(candidate_ref.get("doi") or ext_ids.get("DOI"))
    cand_aid = normalize_arxiv_id(candidate_ref.get("ref_arxiv_id") or ext_ids.get("ArXiv"))

    ref_j = candidate_ref.get("journal")
    ref_j_name = ref_j.get("name", "") if isinstance(ref_j, dict) else str(ref_j or "")
    ref_venue = str(candidate_ref.get("venue") or ref_j_name or "")
    v_ref_tokens = clean_tokens(ref_venue)
    return {
        "tokens": ref_tokens,
        "clean_title": clean_rt,
        "first_author": ref_first,
        "authors": ref_authors,
        "year": ref_y,
        "doi": ref_doi,
        "arxiv_id": cand_aid,
        "venue_tokens": v_ref_tokens,
    }


def _score_prepared_pair(prep_bib: Dict[str, Any], prep_cand: Dict[str, Any]) -> Dict[str, float]:
    bib_tokens = prep_bib["tokens"]
    ref_tokens = prep_cand["tokens"]
    if bib_tokens and ref_tokens:
        inter_len = len(bib_tokens.intersection(ref_tokens))
        union_len = len(bib_tokens) + len(ref_tokens) - inter_len
        title_token_jaccard = inter_len / union_len if union_len else 0.0
        min_len = min(len(bib_tokens), len(ref_tokens))
        title_token_overlap = inter_len / min_len if min_len > 0 else 0.0
    else:
        title_token_jaccard = 0.0
        title_token_overlap = 0.0

    clean_bt = prep_bib["clean_title"]
    clean_rt = prep_cand["clean_title"]
    if clean_bt and clean_rt:
        if clean_bt == clean_rt:
            title_edit_ratio = 1.0
        else:
            title_edit_ratio = Levenshtein.normalized_similarity(clean_bt, clean_rt)
    else:
        title_edit_ratio = 0.0

    bib_first = prep_bib["first_author"]
    ref_first = prep_cand["first_author"]
    first_author_match = 1.0 if (bib_first and ref_first and bib_first == ref_first) else 0.0

    bib_authors = prep_bib["authors"]
    ref_authors = prep_cand["authors"]
    if bib_authors and ref_authors:
        a_inter_len = len(bib_authors.intersection(ref_authors))
        a_union_len = len(bib_authors) + len(ref_authors) - a_inter_len
        author_set_overlap = a_inter_len / a_union_len if a_union_len else 0.0
    else:
        author_set_overlap = 0.0

    bib_y = prep_bib["year"]
    ref_y = prep_cand["year"]
    if bib_y is not None and ref_y is not None:
        diff = float(abs(bib_y - ref_y))
        year_diff = diff
        year_exact_match = 1.0 if diff == 0.0 else 0.0
        year_proximity = max(0.0, 1.0 - (diff / 5.0))
    else:
        year_diff = 5.0
        year_exact_match = 0.0
        year_proximity = 0.0

    bib_doi = prep_bib["doi"]
    ref_doi = prep_cand["doi"]
    doi_match = 1.0 if (bib_doi and ref_doi and bib_doi == ref_doi) else 0.0

    bib_eprint = prep_bib["eprint"]
    cand_aid = prep_cand["arxiv_id"]
    arxiv_id_match = 1.0 if (bib_eprint and cand_aid and bib_eprint == cand_aid) else 0.0

    v_bib_tokens = prep_bib["venue_tokens"]
    v_ref_tokens = prep_cand["venue_tokens"]
    if v_bib_tokens and v_ref_tokens:
        v_inter = len(v_bib_tokens.intersection(v_ref_tokens))
        venue_token_overlap = v_inter / min(len(v_bib_tokens), len(v_ref_tokens))
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


def _score_prepared_vector(prep_bib: Dict[str, Any], prep_cand: Dict[str, Any]) -> List[float]:
    f_dict = _score_prepared_pair(prep_bib, prep_cand)
    return [f_dict[name] for name in FEATURE_NAMES]


def extract_pair_features(
    bib_entry: Dict[str, Any],
    candidate_ref: Dict[str, Any],
) -> Dict[str, float]:
    """
    Trích xuất toàn bộ 11 đặc trưng số học cho một cặp (BibTeX entry, Candidate reference).
    Tất cả các giá trị trả về đều là kiểu số thực (float), an toàn trước null/None.
    """
    return _score_prepared_pair(_prepare_bib_entry(bib_entry), _prepare_candidate_ref(candidate_ref))


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
    # Gom nhóm candidates theo publication arxiv_id và precompute features một lần
    cand_by_pub: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
    seen_pairs: Set[Tuple[str, str]] = set()
    for c in candidates:
        aid = normalize_arxiv_id(c.get("arxiv_id"))
        ext_ids = c.get("externalIds") if isinstance(c.get("externalIds"), dict) else {}
        c_aid = normalize_arxiv_id(c.get("ref_arxiv_id") or ext_ids.get("ArXiv"))
        if aid and c_aid and (aid, c_aid) not in seen_pairs:
            seen_pairs.add((aid, c_aid))
            cand_by_pub.setdefault(aid, []).append((c_aid, _prepare_candidate_ref(c)))

    X: List[List[float]] = []
    meta: List[Dict[str, Any]] = []

    for entry in bib_entries:
        pub_id = normalize_arxiv_id(entry.get("arxiv_id"))
        ckey = str(entry.get("citation_key", ""))
        cands = cand_by_pub.get(pub_id, [])
        if not cands:
            continue
        prep_bib = _prepare_bib_entry(entry)

        for c_aid, prep_c in cands:
            X.append(_score_prepared_vector(prep_bib, prep_c))
            meta.append({
                "arxiv_id": pub_id,
                "citation_key": ckey,
                "ref_arxiv_id": c_aid,
            })

    return X, meta
