"""
Module label.py: Quản lý gán nhãn Ground Truth và Phân chia tập dữ liệu (Data Split).
Thuộc sở hữu của Member 4 - Data Quality, Schema và ML Owner.
"""

from __future__ import annotations

import json
import math
import random
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from src.normalize import normalize_arxiv_id, normalize_text


@dataclass
class LabelRecord:
    """Bản ghi gán nhãn cho một mục BibTeX."""
    arxiv_id: str
    citation_key: str
    groundtruth_arxiv_id: Optional[str]  # None nếu trích dẫn không có trên arXiv
    method: str  # 'manual' hoặc 'automatic'
    labeled_by: str  # Tên/Mã thành viên hoặc matcher
    notes: Optional[str] = None


@dataclass
class PublicationSplitInfo:
    """Thông tin phân chia partition cho một bài báo."""
    arxiv_id: str
    partition: str  # 'train', 'valid', 'test'
    method: str  # 'manual' hoặc 'automatic'
    labeled_by: str
    entries_count: int


# ==============================================================================
# 1. KIỂM ĐỊNH QUOTA GÁN NHÃN (LABELING QUOTA VALIDATOR)
# ==============================================================================

def validate_labeling_quota(
    labeled_publications: List[Dict[str, Any]],
    total_assigned_publications_count: int,
    num_members: int = 5,
) -> Dict[str, Any]:
    """
    Kiểm tra tính tuân thủ quota gán nhãn theo quy định đề bài (Nhóm k thành viên):
    - Thủ công (Manual pool):
      * Tối thiểu 5 * k bài báo (k=5 => 25 bài).
      * Mỗi bài báo thủ công phải có ít nhất 20 mục trích dẫn được gán nhãn (Q >= 20).
      * Mỗi thành viên gán nhãn >= 5 bài và tổng >= 100 mục trích dẫn (nhóm >= 500 mục).
    - Tự động (Automatic pool):
      * Tối thiểu 2 * k bài báo (k=5 => 10 bài).
      * Chiếm ít nhất 10% tổng số bài báo ngoài tập manual.
      * Gán nhãn cho toàn bộ các mục BibTeX của các bài báo được chọn.
    """
    manual_pubs = [p for p in labeled_publications if p.get("method") == "manual"]
    auto_pubs = [p for p in labeled_publications if p.get("method") == "automatic"]

    errors: List[str] = []
    warnings: List[str] = []

    # 1. Kiểm tra Manual pool
    min_manual_pubs = 5 * num_members
    min_manual_entries = 100 * num_members

    if len(manual_pubs) < min_manual_pubs:
        errors.append(
            f"Manual pool có {len(manual_pubs)} bài, không đạt mức tối thiểu {min_manual_pubs} bài cho {num_members} thành viên."
        )

    # Kiểm tra Q >= 20 cho từng bài manual
    manual_total_entries = 0
    pubs_under_20_entries: List[str] = []
    member_manual_stats: Dict[str, Dict[str, int]] = {}

    for p in manual_pubs:
        aid = p.get("arxiv_id", "unknown")
        count = p.get("entries_count", 0)
        member = p.get("labeled_by", "unassigned")

        manual_total_entries += count
        if count < 20:
            pubs_under_20_entries.append(f"{aid} ({count} entries)")

        if member not in member_manual_stats:
            member_manual_stats[member] = {"pubs": 0, "entries": 0}
        member_manual_stats[member]["pubs"] += 1
        member_manual_stats[member]["entries"] += count

    if pubs_under_20_entries:
        errors.append(
            f"Có {len(pubs_under_20_entries)} bài gán nhãn thủ công có ít hơn 20 entries (yêu cầu Q >= 20): "
            f"{pubs_under_20_entries[:5]}"
        )

    if manual_total_entries < min_manual_entries:
        errors.append(
            f"Tổng số entries gán nhãn thủ công ({manual_total_entries}) chưa đạt mức tối thiểu {min_manual_entries}."
        )

    # Kiểm tra từng thành viên đạt >= 5 bài và >= 100 entries
    for member, stats in member_manual_stats.items():
        if stats["pubs"] < 5:
            warnings.append(f"Thành viên '{member}' chỉ mới gán nhãn {stats['pubs']} bài (yêu cầu >= 5 bài).")
        if stats["entries"] < 100:
            warnings.append(f"Thành viên '{member}' chỉ mới gán nhãn {stats['entries']} entries (yêu cầu >= 100 entries).")

    # 2. Kiểm tra Automatic pool
    min_auto_pubs = 2 * num_members
    remaining_pubs_outside_manual = max(0, total_assigned_publications_count - len(manual_pubs))
    required_auto_pct_pubs = math.ceil(0.10 * remaining_pubs_outside_manual)
    required_auto_pubs = max(min_auto_pubs, required_auto_pct_pubs)

    if len(auto_pubs) < min_auto_pubs:
        errors.append(
            f"Automatic pool có {len(auto_pubs)} bài, không đạt mức tối thiểu {min_auto_pubs} bài (2 * k)."
        )
    if len(auto_pubs) < required_auto_pubs:
        errors.append(
            f"Automatic pool có {len(auto_pubs)} bài, chưa đạt mức 10% các bài ngoài manual pool ({required_auto_pubs} bài)."
        )

    auto_total_entries = sum(p.get("entries_count", 0) for p in auto_pubs)

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "manual_stats": {
            "publications_count": len(manual_pubs),
            "total_entries": manual_total_entries,
            "min_required_publications": min_manual_pubs,
            "min_required_entries": min_manual_entries,
            "by_member": member_manual_stats,
        },
        "automatic_stats": {
            "publications_count": len(auto_pubs),
            "total_entries": auto_total_entries,
            "min_required_publications": required_auto_pubs,
        },
    }


# ==============================================================================
# 2. PHÂN CHIA TẬP DỮ LIỆU CẤP BÀI BÁO (PUBLICATION-DISJOINT SPLIT)
# ==============================================================================

def create_publication_split(
    manual_publications: Sequence[Dict[str, Any]],
    auto_publications: Sequence[Dict[str, Any]],
    num_members: int = 5,
    random_seed: int = 42,
) -> List[PublicationSplitInfo]:
    """
    Phân chia dữ liệu theo cấp bài báo (Publication-level Split) để chống rò rỉ dữ liệu:
    - Test Set: k bài manual + k bài automatic.
    - Validation Set: k bài manual + k bài automatic.
    - Train Set: Toàn bộ bài manual và automatic còn lại.
    """
    k = num_members
    if len(manual_publications) < 2 * k:
        raise ValueError(f"Manual publications ({len(manual_publications)}) không đủ để chia Test ({k}) và Valid ({k}).")
    if len(auto_publications) < 2 * k:
        raise ValueError(f"Auto publications ({len(auto_publications)}) không đủ để chia Test ({k}) và Valid ({k}).")

    rng = random.Random(random_seed)
    sorted_manual = sorted(list(manual_publications), key=lambda x: str(x["arxiv_id"]))
    sorted_auto = sorted(list(auto_publications), key=lambda x: str(x["arxiv_id"]))

    rng.shuffle(sorted_manual)
    rng.shuffle(sorted_auto)

    # 1. Phân bổ cho Test Set
    test_manual = sorted_manual[:k]
    test_auto = sorted_auto[:k]

    # 2. Phân bổ cho Validation Set
    valid_manual = sorted_manual[k : 2 * k]
    valid_auto = sorted_auto[k : 2 * k]

    # 3. Phân bổ cho Training Set
    train_manual = sorted_manual[2 * k :]
    train_auto = sorted_auto[2 * k :]

    split_results: List[PublicationSplitInfo] = []

    def _add_partition(items: List[Dict[str, Any]], part: str, method: str) -> None:
        for p in items:
            split_results.append(
                PublicationSplitInfo(
                    arxiv_id=normalize_arxiv_id(p["arxiv_id"]),
                    partition=part,
                    method=method,
                    labeled_by=p.get("labeled_by", "unknown"),
                    entries_count=p.get("entries_count", 0),
                )
            )

    _add_partition(test_manual, "test", "manual")
    _add_partition(test_auto, "test", "automatic")
    _add_partition(valid_manual, "valid", "manual")
    _add_partition(valid_auto, "valid", "automatic")
    _add_partition(train_manual, "train", "manual")
    _add_partition(train_auto, "train", "automatic")

    # Kiểm tra rò rỉ (Assert publication-disjoint)
    all_aids = [s.arxiv_id for s in split_results]
    assert len(all_aids) == len(set(all_aids)), "LỖI RÒ RỈ: Có bài báo xuất hiện ở nhiều partition khác nhau!"

    return sorted(split_results, key=lambda x: (x.partition, x.arxiv_id))


def export_split_manifest(split_info: List[PublicationSplitInfo], output_path: Union[str, Path]) -> None:
    """Lưu trữ manifest phân chia train/valid/test ra file JSON ngoài git."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    records = [asdict(s) for s in split_info]
    with open(out, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def load_split_manifest(input_path: Union[str, Path]) -> Dict[str, str]:
    """Đọc file manifest và trả về từ điển ánh xạ: arxiv_id -> partition ('train'/'valid'/'test')."""
    inp = Path(input_path)
    if not inp.exists():
        return {}
    with open(inp, "r", encoding="utf-8") as f:
        records = json.load(f)
    return {normalize_arxiv_id(r["arxiv_id"]): str(r["partition"]).lower() for r in records}


# ==============================================================================
# 3. AUTOMATIC MATCHER BASELINE HEURISTIC (CLASSIC STRING SIMILARITY)
# ==============================================================================

def _title_tokens(title: str) -> Set[str]:
    """Tách từ chuẩn hóa cho tiêu đề để so khớp token overlap."""
    clean = re.sub(r"[^\w\s]", " ", title.lower())
    words = clean.split()
    # Loại bỏ các stopwords tiếng Anh phổ biến
    stopwords = {"a", "an", "the", "in", "on", "of", "for", "to", "and", "with", "is", "by", "from"}
    return {w for w in words if len(w) > 2 and w not in stopwords}


def heuristic_match_entry(
    bib_entry: Dict[str, Any],
    crawled_references: List[Dict[str, Any]],
    min_similarity_threshold: float = 0.65,
) -> Optional[str]:
    """
    Công cụ gán nhãn tự động cơ sở (Automatic Matcher Baseline):
    Sử dụng heuristic so khớp chuỗi (title Jaccard, author overlap, year) để tìm mã arXiv tương ứng.
    Trả về ref_arxiv_id tốt nhất nếu độ tương đồng >= min_similarity_threshold, ngược lại trả về None.
    """
    bib_title = normalize_text(bib_entry.get("title", ""))
    bib_tokens = _title_tokens(bib_title)
    if not bib_tokens:
        return None

    bib_authors = []
    for a in (bib_entry.get("authors") or []):
        if not a:
            continue
        name = a.get("name", "") if isinstance(a, dict) else str(a)
        tokens = name.strip().lower().split()
        if tokens:
            bib_authors.append(tokens[-1])
    bib_year = bib_entry.get("year")

    best_match_arxiv_id: Optional[str] = None
    best_score = 0.0

    for ref in crawled_references:
        ref_arxiv_id = normalize_arxiv_id(ref.get("ref_arxiv_id") or ref.get("externalIds", {}).get("ArXiv"))
        if not ref_arxiv_id:
            continue

        ref_title = normalize_text(ref.get("ref_title") or ref.get("title", ""))
        ref_tokens = _title_tokens(ref_title)
        if not ref_tokens:
            continue

        # 1. Jaccard similarity trên tiêu đề
        intersection = bib_tokens.intersection(ref_tokens)
        union = bib_tokens.union(ref_tokens)
        title_score = len(intersection) / len(union) if union else 0.0

        # Nếu tiêu đề khớp hoàn toàn
        if bib_title.lower() == ref_title.lower():
            title_score = 1.0

        # 2. Author overlap (xử lý an toàn cả string lẫn dict từ Semantic Scholar)
        ref_authors = []
        for a in (ref.get("ref_authors") or ref.get("authors") or []):
            if not a:
                continue
            name = a.get("name", "") if isinstance(a, dict) else str(a)
            tokens = name.strip().lower().split()
            if tokens:
                ref_authors.append(tokens[-1])

        author_match = any(a in ref_authors for a in bib_authors) if bib_authors and ref_authors else False
        author_bonus = 0.15 if author_match else 0.0

        # 3. Year match
        ref_date = str(ref.get("ref_submission_date") or ref.get("publicationDate") or ref.get("year") or ref.get("ref_year") or "")
        year_match = (str(bib_year) in ref_date) if bib_year and ref_date else False
        year_bonus = 0.10 if year_match else 0.0

        total_score = title_score + author_bonus + year_bonus

        if total_score > best_score:
            best_score = total_score
            best_match_arxiv_id = ref_arxiv_id

    if best_score >= min_similarity_threshold:
        return best_match_arxiv_id

    return None
