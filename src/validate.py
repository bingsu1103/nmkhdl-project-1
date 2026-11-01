"""
Module validate.py: Hệ thống Quality Gate và kiểm thử toàn vẹn dữ liệu cho đồ án.
Thuộc sở hữu của Member 4 - Data Quality, Schema và Storage Owner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

import pyarrow as pa
from src.storage import PAPERS_SCHEMA, REFERENCES_SCHEMA


@dataclass
class ValidationReport:
    """Báo cáo kết quả kiểm thử chất lượng dữ liệu."""
    table_name: str
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.is_valid = False

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table_name": self.table_name,
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": self.errors,
            "warnings": self.warnings,
            "stats": self.stats,
        }


def _is_valid_iso_date(date_str: str) -> bool:
    """Kiểm tra chuỗi có tuân theo định dạng ISO-8601 cơ bản không."""
    if not isinstance(date_str, str):
        return False
    # Cho phép YYYY-MM-DD hoặc ISO datetime đầy đủ
    iso_pattern = r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?)?$"
    return bool(re.match(iso_pattern, date_str.strip()))


def validate_papers_table(table: pa.Table) -> ValidationReport:
    """
    Kiểm tra chất lượng và tính toàn vẹn cho bảng 'papers':
    - Khớp Schema (types, nullability).
    - Khóa chính 'arxiv_id' là duy nhất và không null.
    - Tiêu đề không rỗng.
    - Danh sách tác giả không rỗng và chứa các chuỗi hợp lệ.
    - Định dạng ngày 'submission_date' và 'revised_dates' chuẩn ISO.
    """
    report = ValidationReport(table_name="papers")
    report.stats["total_rows"] = table.num_rows

    # 1. Kiểm tra Schema
    if not table.schema.equals(PAPERS_SCHEMA):
        # Kiểm tra chi tiết từng cột
        for expected_field in PAPERS_SCHEMA:
            field_name = expected_field.name
            if field_name not in table.column_names:
                report.add_error(f"Thiếu cột bắt buộc '{field_name}'")
            else:
                actual_field = table.field(field_name)
                if actual_field.type != expected_field.type:
                    report.add_error(
                        f"Sai kiểu dữ liệu cột '{field_name}': mong đợi {expected_field.type}, thực tế {actual_field.type}"
                    )
        # Kiểm tra cột thừa không hợp lệ
        unexpected_cols = set(table.column_names) - set(PAPERS_SCHEMA.names)
        if unexpected_cols:
            report.add_error(f"Phát hiện các cột thừa không thuộc schema 'papers': {sorted(list(unexpected_cols))}")

    # NẾU SCHEMA LỖI HOẶC BẢNG RỖNG: Dừng kiểm tra chi tiết để tránh crash truy cập cột!
    if not report.is_valid:
        return report

    if table.num_rows == 0:
        report.add_warning("Bảng 'papers' không có dữ liệu nào.")
        return report

    # 2. Chuyển đổi sang Python list để kiểm tra từng dòng
    arxiv_ids = table.column("arxiv_id").to_pylist()
    titles = table.column("title").to_pylist()
    authors_list = table.column("authors").to_pylist()
    sub_dates = table.column("submission_date").to_pylist()
    rev_dates_list = table.column("revised_dates").to_pylist()

    # 3. Kiểm tra tính duy nhất và không null của Primary Key (arxiv_id)
    seen_ids: Set[str] = set()
    duplicate_ids: Set[str] = set()

    for idx, aid in enumerate(arxiv_ids):
        row_num = idx + 1
        if aid is None or str(aid).strip() == "":
            report.add_error(f"Dòng {row_num}: 'arxiv_id' bị null hoặc rỗng.")
            continue

        aid_str = str(aid).strip()
        if aid_str in seen_ids:
            duplicate_ids.add(aid_str)
        seen_ids.add(aid_str)

        # Kiểm tra title
        title = titles[idx]
        if title is None or str(title).strip() == "":
            report.add_error(f"Dòng {row_num} (ID: {aid_str}): 'title' bị null hoặc rỗng.")

        # Kiểm tra authors
        auths = authors_list[idx]
        if not auths or len(auths) == 0:
            report.add_warning(f"Dòng {row_num} (ID: {aid_str}): danh sách 'authors' rỗng.")

        # Kiểm tra submission_date
        sdate = sub_dates[idx]
        if not sdate or not _is_valid_iso_date(str(sdate)):
            report.add_error(f"Dòng {row_num} (ID: {aid_str}): 'submission_date' không đúng chuẩn ISO ('{sdate}').")

        # Kiểm tra revised_dates
        rdates = rev_dates_list[idx] or []
        for rdate in rdates:
            if not _is_valid_iso_date(str(rdate)):
                report.add_error(f"Dòng {row_num} (ID: {aid_str}): 'revised_dates' chứa ngày không chuẩn ISO ('{rdate}').")

    if duplicate_ids:
        report.add_error(f"Phát hiện {len(duplicate_ids)} arxiv_id bị trùng lặp: {sorted(list(duplicate_ids))[:10]}")

    report.stats["unique_papers"] = len(seen_ids)
    return report


def validate_references_table(
    table: pa.Table,
    papers_table: Optional[pa.Table] = None
) -> ValidationReport:
    """
    Kiểm tra chất lượng và tính toàn vẹn cho bảng 'references':
    - Khớp Schema.
    - 'arxiv_id' và 'ref_arxiv_id' không null.
    - Cặp (arxiv_id, ref_arxiv_id) là duy nhất.
    - Khóa ngoại (Foreign Key): Mọi 'arxiv_id' của tài liệu trích dẫn phải tồn tại trong 'papers_table'.
    """
    report = ValidationReport(table_name="references")
    report.stats["total_rows"] = table.num_rows

    # 1. Kiểm tra Schema
    if not table.schema.equals(REFERENCES_SCHEMA):
        for expected_field in REFERENCES_SCHEMA:
            field_name = expected_field.name
            if field_name not in table.column_names:
                report.add_error(f"Thiếu cột bắt buộc '{field_name}'")
            else:
                actual_field = table.field(field_name)
                if actual_field.type != expected_field.type:
                    report.add_error(
                        f"Sai kiểu dữ liệu cột '{field_name}': mong đợi {expected_field.type}, thực tế {actual_field.type}"
                    )
        # Kiểm tra cột thừa không hợp lệ
        unexpected_cols = set(table.column_names) - set(REFERENCES_SCHEMA.names)
        if unexpected_cols:
            report.add_error(f"Phát hiện các cột thừa không thuộc schema 'references': {sorted(list(unexpected_cols))}")

    # NẾU SCHEMA LỖI HOẶC BẢNG RỖNG: Dừng kiểm tra chi tiết để tránh crash!
    if not report.is_valid:
        return report

    if table.num_rows == 0:
        report.add_warning("Bảng 'references' không có dữ liệu nào.")
        return report

    citing_ids = table.column("arxiv_id").to_pylist()
    ref_ids = table.column("ref_arxiv_id").to_pylist()

    # 2. Kiểm tra trùng lặp cặp (arxiv_id, ref_arxiv_id)
    seen_pairs: Set[tuple[str, str]] = set()
    dup_pairs = 0

    for idx, (cid, rid) in enumerate(zip(citing_ids, ref_ids)):
        row_num = idx + 1
        if cid is None or str(cid).strip() == "":
            report.add_error(f"Dòng {row_num}: 'arxiv_id' bị null.")
        if rid is None or str(rid).strip() == "":
            report.add_error(f"Dòng {row_num}: 'ref_arxiv_id' bị null.")

        if cid and rid:
            pair = (str(cid).strip(), str(rid).strip())
            if pair in seen_pairs:
                dup_pairs += 1
            seen_pairs.add(pair)

    if dup_pairs > 0:
        report.add_error(f"Phát hiện {dup_pairs} cặp (arxiv_id, ref_arxiv_id) bị trùng lặp.")

    # 3. Kiểm tra Foreign Key (nếu có bảng papers đi kèm)
    if papers_table is not None:
        valid_paper_ids = set(str(x).strip() for x in papers_table.column("arxiv_id").to_pylist() if x)
        orphan_ids = set(str(cid).strip() for cid in citing_ids if cid and str(cid).strip() not in valid_paper_ids)
        if orphan_ids:
            report.add_error(
                f"Vi phạm khóa ngoại (FK violation): Có {len(orphan_ids)} bài báo trong 'references' "
                f"không tồn tại trong 'papers': {sorted(list(orphan_ids))[:10]}"
            )

    report.stats["unique_citing_papers"] = len(set(citing_ids))
    report.stats["unique_referenced_papers"] = len(set(ref_ids))
    return report


def reconcile_crawling_counts(
    assigned_ids: List[str],
    papers_table: pa.Table,
    failed_discovery_ids: List[str],
) -> Dict[str, Any]:
    """
    Đối soát (Reconciliation) số lượng paper cào được so với số lượng được giao:
    assigned_ids == successful_ids + failed_ids (không được thất thoát ID nào).
    """
    assigned_set = set(str(x).strip() for x in assigned_ids)
    success_set = set(str(x).strip() for x in papers_table.column("arxiv_id").to_pylist())
    failed_set = set(str(x).strip() for x in failed_discovery_ids)

    accounted_set = success_set.union(failed_set)
    unaccounted_ids = assigned_set - accounted_set
    unexpected_ids = success_set - assigned_set

    is_reconciled = len(unaccounted_ids) == 0 and len(unexpected_ids) == 0

    return {
        "is_reconciled": is_reconciled,
        "assigned_count": len(assigned_set),
        "success_count": len(success_set),
        "failed_discovery_count": len(failed_set),
        "unaccounted_count": len(unaccounted_ids),
        "unaccounted_ids": sorted(list(unaccounted_ids)),
        "unexpected_count": len(unexpected_ids),
        "unexpected_ids": sorted(list(unexpected_ids)),
        "success_rate": len(success_set) / max(1, len(assigned_set)),
    }


def compute_crawl_statistics(
    assigned_ids: List[str],
    papers_table: pa.Table,
    references_table: pa.Table,
    source_status_records: Optional[List[Dict[str, Any]]] = None,
    s2_attempted_count: Optional[int] = None,
    total_raw_references_count: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Tổng hợp đầy đủ các chỉ số thống kê M1 cho summary.json theo hợp đồng với Member 5:
    - Tỷ lệ thành công bài báo (paper_success_rate).
    - Dung lượng trước/sau khi lọc hình ảnh (avg_orig, avg_filt, reduction_rate).
    - Tách biệt rõ:
      * avg_all_references_per_paper (tổng trích dẫn từ S2, bao gồm non-arXiv).
      * avg_eligible_arxiv_references_per_paper (chỉ trích dẫn có mã arXiv).
    - Tỷ lệ thành công trích dẫn (reference_metadata_success_rate).
    """
    total_assigned = len(set(assigned_ids))
    success_papers = papers_table.num_rows
    paper_success_rate = round(success_papers / max(1, total_assigned), 4)

    # Thống kê dung lượng từ source status của M2 (nếu có)
    avg_orig = 0.0
    avg_filt = 0.0
    if source_status_records:
        orig_bytes = [r.get("archive_bytes", 0) for r in source_status_records]
        filt_bytes = [r.get("filtered_bytes", 0) for r in source_status_records]
        avg_orig = sum(orig_bytes) / max(1, len(orig_bytes))
        avg_filt = sum(filt_bytes) / max(1, len(filt_bytes))

    reduction_rate = round((avg_orig - avg_filt) / max(1.0, avg_orig), 4) if avg_orig > 0 else 0.0

    # Thống kê references: Tách biệt All References vs Eligible arXiv References
    eligible_refs_count = references_table.num_rows
    avg_eligible_refs = round(eligible_refs_count / max(1, success_papers), 2)

    raw_refs_count = total_raw_references_count if total_raw_references_count is not None else eligible_refs_count
    avg_all_refs = round(raw_refs_count / max(1, success_papers), 2)

    s2_attempted = s2_attempted_count or success_papers
    unique_citing_papers = len(set(references_table.column("arxiv_id").to_pylist())) if references_table.num_rows > 0 else 0
    ref_success_rate = round(unique_citing_papers / max(1, s2_attempted), 4)

    return {
        "total_assigned": total_assigned,
        "papers_scraped_successfully": success_papers,
        "paper_success_rate": paper_success_rate,
        "avg_original_source_bytes": round(avg_orig, 2),
        "avg_filtered_source_bytes": round(avg_filt, 2),
        "reduction_rate": reduction_rate,
        "avg_all_references_per_paper": avg_all_refs,
        "avg_eligible_arxiv_references_per_paper": avg_eligible_refs,
        "reference_metadata_success_rate": ref_success_rate,
    }


def load_manifest_assigned_ids(file_path: Union[str, Path]) -> List[str]:
    """
    Đọc danh sách arxiv_id được giao từ file CSV/manifest (ví dụ expanded_ids.csv).
    Phòng vệ linh hoạt với tên cột ID khác nhau:
    - Ưu tiên chính xác: 'arxiv_id', 'paper_id', 'id' (không phân biệt hoa thường)
    - Nếu không khớp, tìm cột đầu tiên chứa 'id' (case-insensitive)
    - Nếu không có, fallback lấy cột đầu tiên (cột index 0).
    """
    path = Path(file_path)
    if not path.exists():
        return []

    import pandas as pd

    df = pd.read_csv(path)
    if df.empty or len(df.columns) == 0:
        return []

    candidate_priorities = ["arxiv_id", "paper_id", "id"]
    id_col = next((c for p in candidate_priorities for c in df.columns if c.strip().lower() == p), None)
    if id_col is None:
        # Loại trừ member_id, start_id, end_id để không đọc nhầm ID thành viên
        id_col = next(
            (c for c in df.columns if "id" in c.lower() and not any(k in c.lower() for k in ["member", "start", "end"])),
            None
        )
    if id_col is None:
        id_col = df.columns[0]

    return df[id_col].dropna().astype(str).str.strip().tolist()


