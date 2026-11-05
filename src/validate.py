"""
Module validate.py: Hệ thống Quality Gate và kiểm thử toàn vẹn dữ liệu cho đồ án.
Thuộc sở hữu của Member 4 - Data Quality, Schema và Storage Owner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union, Tuple

import pyarrow as pa
from src.storage import (
    BIBTEX_SCHEMA,
    ELEMENTS_SCHEMA,
    HIERARCHY_SCHEMA,
    PAPERS_SCHEMA,
    PREDICTIONS_SCHEMA,
    REFERENCES_SCHEMA,
)
from src.normalize import normalize_arxiv_id


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

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

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


# ==============================================================================
# TAXONOMY CHUẨN CHO MILESTONE 2
# ==============================================================================

VALID_ELEMENT_KINDS: Set[str] = {
    "document",
    "heading",
    "section",
    "subsection",
    "subsubsection",
    "chapter",
    "paragraph",
    "list",
    "item",
    "sentence",
    "formula",
    "figure",
    "table",
}

STANDARD_BIBTEX_ENTRY_TYPES: Set[str] = {
    "article",
    "book",
    "booklet",
    "conference",
    "inbook",
    "incollection",
    "inproceedings",
    "manual",
    "mastersthesis",
    "misc",
    "phdthesis",
    "proceedings",
    "techreport",
    "unpublished",
    "online",
    "software",
    "dataset",
}


# ==============================================================================
# VALIDATION FUNCTIONS CHO MILESTONE 2 (PARSING & STANDARDIZATION)
# ==============================================================================

def validate_elements_table(
    table: pa.Table,
    papers_table: Optional[pa.Table] = None,
) -> ValidationReport:
    """
    Kiểm tra chất lượng và tính toàn vẹn cho bảng 'elements' (Milestone 2):
    - Khớp Schema (types, nullability) với ELEMENTS_SCHEMA.
    - 'element_id' là duy nhất toàn cục và không null/rỗng.
    - 'arxiv_id' không null/rỗng.
    - 'kind' thuộc danh mục taxonomy hợp lệ (VALID_ELEMENT_KINDS).
    - 'content' không null.
    - Deduplication: Trong cùng một bài báo (arxiv_id), không được tồn tại hai bản ghi có cùng (kind, content).
      Nội dung giống hệt nhau sau khi cleanup bắt buộc phải được tái sử dụng cùng một element_id.
    - Khóa ngoại (nếu có papers_table): 'arxiv_id' phải tồn tại trong papers_table.
    """
    report = ValidationReport(table_name="elements")
    report.stats["total_rows"] = table.num_rows

    # 1. Kiểm tra Schema
    if not table.schema.equals(ELEMENTS_SCHEMA):
        for expected_field in ELEMENTS_SCHEMA:
            field_name = expected_field.name
            if field_name not in table.column_names:
                report.add_error(f"Thiếu cột bắt buộc '{field_name}'")
            else:
                actual_field = table.field(field_name)
                if actual_field.type != expected_field.type:
                    report.add_error(
                        f"Sai kiểu dữ liệu cột '{field_name}': mong đợi {expected_field.type}, thực tế {actual_field.type}"
                    )
        unexpected_cols = set(table.column_names) - set(ELEMENTS_SCHEMA.names)
        if unexpected_cols:
            report.add_error(f"Phát hiện các cột thừa không thuộc schema 'elements': {sorted(list(unexpected_cols))}")

    if not report.is_valid:
        return report

    if table.num_rows == 0:
        report.add_warning("Bảng 'elements' không có dữ liệu nào.")
        return report

    element_ids = table.column("element_id").to_pylist()
    arxiv_ids = table.column("arxiv_id").to_pylist()
    kinds = table.column("kind").to_pylist()
    contents = table.column("content").to_pylist()

    seen_element_ids: Set[str] = set()
    duplicate_element_ids: Set[str] = set()

    # Kiểm tra deduplication: (arxiv_id, kind, content) không được trùng
    seen_content_by_paper: Set[Tuple[str, str, str]] = set()
    dedup_violations: List[str] = []

    kind_counts: Dict[str, int] = {}

    for idx, (eid, aid, kind, content) in enumerate(zip(element_ids, arxiv_ids, kinds, contents)):
        row_num = idx + 1

        if eid is None or str(eid).strip() == "":
            report.add_error(f"Dòng {row_num}: 'element_id' bị null hoặc rỗng.")
            continue

        eid_str = str(eid).strip()
        if eid_str in seen_element_ids:
            duplicate_element_ids.add(eid_str)
        seen_element_ids.add(eid_str)

        if aid is None or str(aid).strip() == "":
            report.add_error(f"Dòng {row_num} (ID: {eid_str}): 'arxiv_id' bị null hoặc rỗng.")
            aid_str = ""
        else:
            aid_str = str(aid).strip()

        if kind is None or str(kind).strip() == "":
            report.add_error(f"Dòng {row_num} (ID: {eid_str}): 'kind' bị null hoặc rỗng.")
        else:
            kind_clean = str(kind).strip().lower()
            kind_counts[kind_clean] = kind_counts.get(kind_clean, 0) + 1
            if kind_clean not in VALID_ELEMENT_KINDS:
                report.add_error(
                    f"Dòng {row_num} (ID: {eid_str}): 'kind' không hợp lệ ('{kind}'). "
                    f"Danh mục cho phép: {sorted(list(VALID_ELEMENT_KINDS))}"
                )

        if content is None:
            report.add_error(f"Dòng {row_num} (ID: {eid_str}): 'content' bị null.")
        else:
            content_str = str(content)
            if aid_str and kind is not None:
                dedup_key = (aid_str, str(kind).strip().lower(), content_str.strip())
                if dedup_key in seen_content_by_paper:
                    dedup_violations.append(eid_str)
                seen_content_by_paper.add(dedup_key)

    if duplicate_element_ids:
        report.add_error(
            f"Phát hiện {len(duplicate_element_ids)} 'element_id' bị trùng lặp: {sorted(list(duplicate_element_ids))[:10]}"
        )

    if dedup_violations:
        report.add_error(
            f"Vi phạm khử trùng lặp (Deduplication violation): Có {len(dedup_violations)} elements trong cùng một bài báo "
            f"có 'kind' và 'content' giống hệt nhau nhưng bị tạo nhiều element_id khác nhau. "
            f"Các element vi phạm: {dedup_violations[:10]}"
        )

    if papers_table is not None:
        valid_paper_ids = set(str(x).strip() for x in papers_table.column("arxiv_id").to_pylist() if x)
        orphan_papers = set(str(aid).strip() for aid in arxiv_ids if aid and str(aid).strip() not in valid_paper_ids)
        if orphan_papers:
            report.add_error(
                f"Vi phạm khóa ngoại (FK violation): Có {len(orphan_papers)} bài báo trong 'elements' "
                f"không tồn tại trong 'papers': {sorted(list(orphan_papers))[:10]}"
            )

    report.stats["unique_elements"] = len(seen_element_ids)
    report.stats["unique_papers"] = len(set(str(a).strip() for a in arxiv_ids if a))
    report.stats["kind_counts"] = kind_counts
    return report


def validate_hierarchy_table(
    table: pa.Table,
    elements_table: Optional[pa.Table] = None,
    papers_table: Optional[pa.Table] = None,
) -> ValidationReport:
    """
    Kiểm tra chất lượng và tính toàn vẹn cấu trúc cây cho bảng 'hierarchy' (Milestone 2):
    - Khớp Schema với HIERARCHY_SCHEMA.
    - 'arxiv_id', 'version', 'element_id', 'parent_id' không null/rỗng.
    - 'version' là số nguyên dương (>= 1).
    - Cạnh tự trỏ chính mình: 'element_id' == 'parent_id' là lỗi.
    - Cạnh trùng lặp: trong cùng 1 version, không lặp lại cặp (element_id, parent_id).
    - Single Parent: trong cùng 1 version, mỗi 'element_id' chỉ có đúng 1 'parent_id'.
    - Tree Integrity cho từng (arxiv_id, version):
      * Có duy nhất 1 Root Node (node xuất hiện ở parent_id nhưng không xuất hiện ở element_id).
      * Không có chu trình (cycle-free).
      * Mọi nút con đều kết nối về Root Node.
    - Khóa ngoại:
      * Nếu có elements_table: mọi element_id và parent_id phải tồn tại trong elements_table của cùng arxiv_id.
        Đồng thời nút Root được phát hiện phải có kind == 'document'.
      * Nếu có papers_table: mọi arxiv_id phải tồn tại trong papers_table.
    """
    report = ValidationReport(table_name="hierarchy")
    report.stats["total_rows"] = table.num_rows

    # 1. Kiểm tra Schema
    if not table.schema.equals(HIERARCHY_SCHEMA):
        for expected_field in HIERARCHY_SCHEMA:
            field_name = expected_field.name
            if field_name not in table.column_names:
                report.add_error(f"Thiếu cột bắt buộc '{field_name}'")
            else:
                actual_field = table.field(field_name)
                if actual_field.type != expected_field.type:
                    report.add_error(
                        f"Sai kiểu dữ liệu cột '{field_name}': mong đợi {expected_field.type}, thực tế {actual_field.type}"
                    )
        unexpected_cols = set(table.column_names) - set(HIERARCHY_SCHEMA.names)
        if unexpected_cols:
            report.add_error(f"Phát hiện các cột thừa không thuộc schema 'hierarchy': {sorted(list(unexpected_cols))}")

    if not report.is_valid:
        return report

    if table.num_rows == 0:
        report.add_warning("Bảng 'hierarchy' không có dữ liệu nào.")
        return report

    arxiv_ids = table.column("arxiv_id").to_pylist()
    versions = table.column("version").to_pylist()
    element_ids = table.column("element_id").to_pylist()
    parent_ids = table.column("parent_id").to_pylist()

    # Nhóm các cạnh theo từng (arxiv_id, version) để kiểm tra tính toàn vẹn cây
    tree_edges: Dict[Tuple[str, int], List[Tuple[str, str]]] = {}
    all_elements_in_hierarchy: Set[Tuple[str, str]] = set()

    for idx, (aid, ver, eid, pid) in enumerate(zip(arxiv_ids, versions, element_ids, parent_ids)):
        row_num = idx + 1
        if aid is None or str(aid).strip() == "":
            report.add_error(f"Dòng {row_num}: 'arxiv_id' bị null hoặc rỗng.")
            continue
        aid_str = str(aid).strip()

        if ver is None:
            report.add_error(f"Dòng {row_num} (Bài: {aid_str}): 'version' bị null.")
            continue
        try:
            ver_int = int(ver)
            if ver_int < 1:
                report.add_error(f"Dòng {row_num} (Bài: {aid_str}): 'version' phải là số nguyên >= 1 (thực tế: {ver_int}).")
        except (ValueError, TypeError):
            report.add_error(f"Dòng {row_num} (Bài: {aid_str}): 'version' không hợp lệ ('{ver}').")
            continue

        if eid is None or str(eid).strip() == "":
            report.add_error(f"Dòng {row_num} (Bài: {aid_str}, v{ver_int}): 'element_id' bị null hoặc rỗng.")
            continue
        eid_str = str(eid).strip()

        if pid is None or str(pid).strip() == "":
            report.add_error(f"Dòng {row_num} (Bài: {aid_str}, v{ver_int}): 'parent_id' bị null hoặc rỗng.")
            continue
        pid_str = str(pid).strip()

        # Kiểm tra tự trỏ chính mình
        if eid_str == pid_str:
            report.add_error(f"Dòng {row_num} (Bài: {aid_str}, v{ver_int}): Cạnh tự trỏ chính mình (element_id == parent_id == '{eid_str}').")

        tree_key = (aid_str, ver_int)
        tree_edges.setdefault(tree_key, []).append((eid_str, pid_str))
        all_elements_in_hierarchy.add((aid_str, eid_str))
        all_elements_in_hierarchy.add((aid_str, pid_str))

    # Xây dựng lookup cho elements_table nếu được cung cấp
    elements_lookup: Optional[Dict[Tuple[str, str], str]] = None
    if elements_table is not None:
        e_arxiv_ids = elements_table.column("arxiv_id").to_pylist()
        e_element_ids = elements_table.column("element_id").to_pylist()
        e_kinds = elements_table.column("kind").to_pylist()
        elements_lookup = {
            (str(a).strip(), str(e).strip()): str(k).strip().lower()
            for a, e, k in zip(e_arxiv_ids, e_element_ids, e_kinds)
            if a and e
        }

    # 2. Kiểm tra cấu trúc cây cho từng (arxiv_id, version)
    for (aid_str, ver_int), edges in tree_edges.items():
        parent_map: Dict[str, str] = {}
        seen_edges_in_version: Set[Tuple[str, str]] = set()

        for eid_str, pid_str in edges:
            edge_tuple = (eid_str, pid_str)
            if edge_tuple in seen_edges_in_version:
                report.add_error(
                    f"Bài {aid_str} v{ver_int}: Cạnh trùng lặp ({eid_str} -> {pid_str})."
                )
            seen_edges_in_version.add(edge_tuple)

            if eid_str in parent_map and parent_map[eid_str] != pid_str:
                report.add_error(
                    f"Bài {aid_str} v{ver_int}: Nút '{eid_str}' có nhiều cha khác nhau trong cùng một version "
                    f"('{parent_map[eid_str]}' và '{pid_str}')."
                )
            parent_map[eid_str] = pid_str

        children = set(parent_map.keys())
        parents = set(parent_map.values())
        root_candidates = parents - children

        if len(root_candidates) == 0:
            report.add_error(
                f"Bài {aid_str} v{ver_int}: Không tìm thấy nút Root (phát hiện chu trình hoặc cây rỗng)."
            )
            continue
        elif len(root_candidates) > 1:
            report.add_error(
                f"Bài {aid_str} v{ver_int}: Phát hiện {len(root_candidates)} nút Root ({sorted(list(root_candidates))}). "
                f"Đề bài yêu cầu mỗi version chỉ có đúng 1 document root."
            )
            continue

        root_node = next(iter(root_candidates))

        # Kiểm tra kind của root node nếu có elements_table
        if elements_lookup is not None:
            root_kind = elements_lookup.get((aid_str, root_node))
            if root_kind is not None and root_kind != "document":
                report.add_error(
                    f"Bài {aid_str} v{ver_int}: Nút Root '{root_node}' có kind là '{root_kind}', mong đợi là 'document'."
                )

        # Phát hiện chu trình (cycle detection) & Kết nối về Root
        for child in children:
            curr = child
            visited_in_path: Set[str] = {curr}
            path: List[str] = [curr]
            has_cycle = False

            while curr in parent_map:
                parent = parent_map[curr]
                if parent in visited_in_path:
                    cycle_start = path.index(parent)
                    cycle_nodes = path[cycle_start:] + [parent]
                    report.add_error(
                        f"Bài {aid_str} v{ver_int}: Phát hiện chu trình (cycle): {' -> '.join(cycle_nodes)}"
                    )
                    has_cycle = True
                    break
                visited_in_path.add(parent)
                path.append(parent)
                curr = parent

            if not has_cycle and curr != root_node:
                report.add_error(
                    f"Bài {aid_str} v{ver_int}: Nút '{child}' không kết nối về nút Root '{root_node}'."
                )

    # 3. Kiểm tra khóa ngoại sang elements_table
    if elements_lookup is not None:
        missing_in_elements = [
            f"({a}, {e})" for (a, e) in all_elements_in_hierarchy if (a, e) not in elements_lookup
        ]
        if missing_in_elements:
            report.add_error(
                f"Vi phạm khóa ngoại (FK violation): Có {len(missing_in_elements)} nút trong 'hierarchy' "
                f"không tồn tại trong 'elements' của cùng bài báo: {missing_in_elements[:10]}"
            )

    # 4. Kiểm tra khóa ngoại sang papers_table
    if papers_table is not None:
        valid_paper_ids = set(str(x).strip() for x in papers_table.column("arxiv_id").to_pylist() if x)
        orphan_papers = set(str(aid).strip() for aid in arxiv_ids if aid and str(aid).strip() not in valid_paper_ids)
        if orphan_papers:
            report.add_error(
                f"Vi phạm khóa ngoại (FK violation): Có {len(orphan_papers)} bài báo trong 'hierarchy' "
                f"không tồn tại trong 'papers': {sorted(list(orphan_papers))[:10]}"
            )

    report.stats["total_edges"] = table.num_rows
    report.stats["unique_trees"] = len(tree_edges)
    report.stats["unique_nodes"] = len(all_elements_in_hierarchy)
    return report


def validate_bibtex_table(
    table: pa.Table,
    papers_table: Optional[pa.Table] = None,
) -> ValidationReport:
    """
    Kiểm tra chất lượng và tính toàn vẹn cho bảng 'bibtex' (Milestone 2):
    - Khớp Schema với BIBTEX_SCHEMA.
    - 'arxiv_id', 'citation_key', 'entry_type', 'title' không được null hoặc rỗng.
    - 'authors' là danh sách chuỗi không rỗng.
    - Tính duy nhất: Cặp (arxiv_id, citation_key) là duy nhất cho mỗi tài liệu tham khảo trong một bài báo.
    - 'year': Nếu có giá trị, phải là số nguyên hợp lệ trong khoảng 1800 đến 2050.
    - 'entry_type': Cảnh báo nếu không thuộc danh mục BibTeX chuẩn.
    - Khóa ngoại (nếu có papers_table): mọi 'arxiv_id' phải tồn tại trong papers_table.
    """
    report = ValidationReport(table_name="bibtex")
    report.stats["total_rows"] = table.num_rows

    # 1. Kiểm tra Schema
    if not table.schema.equals(BIBTEX_SCHEMA):
        for expected_field in BIBTEX_SCHEMA:
            field_name = expected_field.name
            if field_name not in table.column_names:
                report.add_error(f"Thiếu cột bắt buộc '{field_name}'")
            else:
                actual_field = table.field(field_name)
                if actual_field.type != expected_field.type:
                    report.add_error(
                        f"Sai kiểu dữ liệu cột '{field_name}': mong đợi {expected_field.type}, thực tế {actual_field.type}"
                    )
        unexpected_cols = set(table.column_names) - set(BIBTEX_SCHEMA.names)
        if unexpected_cols:
            report.add_error(f"Phát hiện các cột thừa không thuộc schema 'bibtex': {sorted(list(unexpected_cols))}")

    if not report.is_valid:
        return report

    if table.num_rows == 0:
        report.add_warning("Bảng 'bibtex' không có dữ liệu nào.")
        return report

    arxiv_ids = table.column("arxiv_id").to_pylist()
    citation_keys = table.column("citation_key").to_pylist()
    entry_types = table.column("entry_type").to_pylist()
    titles = table.column("title").to_pylist()
    authors_list = table.column("authors").to_pylist()
    years = table.column("year").to_pylist()

    seen_keys: Set[Tuple[str, str]] = set()
    dup_keys: List[str] = []
    entry_type_counts: Dict[str, int] = {}
    years_count = 0

    for idx, (aid, ckey, etype, title, auths, year) in enumerate(
        zip(arxiv_ids, citation_keys, entry_types, titles, authors_list, years)
    ):
        row_num = idx + 1

        if aid is None or str(aid).strip() == "":
            report.add_error(f"Dòng {row_num}: 'arxiv_id' bị null hoặc rỗng.")
            aid_str = ""
        else:
            aid_str = str(aid).strip()

        if ckey is None or str(ckey).strip() == "":
            report.add_error(f"Dòng {row_num} (Bài: {aid_str}): 'citation_key' bị null hoặc rỗng.")
            ckey_str = ""
        else:
            ckey_str = str(ckey).strip()

        if aid_str and ckey_str:
            key_pair = (aid_str, ckey_str)
            if key_pair in seen_keys:
                dup_keys.append(f"{aid_str}#{ckey_str}")
            seen_keys.add(key_pair)

        if etype is None or str(etype).strip() == "":
            report.add_error(f"Dòng {row_num} (Key: {ckey_str}): 'entry_type' bị null hoặc rỗng.")
        else:
            etype_clean = str(etype).strip().lower()
            entry_type_counts[etype_clean] = entry_type_counts.get(etype_clean, 0) + 1
            if etype_clean not in STANDARD_BIBTEX_ENTRY_TYPES:
                report.add_warning(
                    f"Dòng {row_num} (Key: {ckey_str}): 'entry_type' không thuộc chuẩn BibTeX thông dụng ('{etype}')."
                )

        if title is None or str(title).strip() == "":
            report.add_error(f"Dòng {row_num} (Key: {ckey_str}): 'title' bị null hoặc rỗng.")

        if not auths or len(auths) == 0:
            report.add_warning(f"Dòng {row_num} (Key: {ckey_str}): danh sách 'authors' rỗng.")

        if year is not None:
            years_count += 1
            try:
                yr_val = int(year)
                if yr_val < 1800 or yr_val > 2050:
                    report.add_error(
                        f"Dòng {row_num} (Key: {ckey_str}): 'year' không hợp lệ ({yr_val}). Mong đợi từ 1800 đến 2050."
                    )
            except (ValueError, TypeError):
                report.add_error(f"Dòng {row_num} (Key: {ckey_str}): 'year' không phải số nguyên ('{year}').")

    if dup_keys:
        report.add_error(
            f"Phát hiện {len(dup_keys)} cặp (arxiv_id, citation_key) bị trùng lặp: {dup_keys[:10]}"
        )

    # Kiểm tra Foreign Key sang papers_table nếu có
    if papers_table is not None:
        valid_paper_ids = set(str(x).strip() for x in papers_table.column("arxiv_id").to_pylist() if x)
        orphan_papers = set(str(aid).strip() for aid in arxiv_ids if aid and str(aid).strip() not in valid_paper_ids)
        if orphan_papers:
            report.add_error(
                f"Vi phạm khóa ngoại (FK violation): Có {len(orphan_papers)} bài báo trong 'bibtex' "
                f"không tồn tại trong 'papers': {sorted(list(orphan_papers))[:10]}"
            )

    report.stats["unique_entries"] = len(seen_keys)
    report.stats["unique_papers"] = len(set(str(a).strip() for a in arxiv_ids if a))
    report.stats["entry_type_counts"] = entry_type_counts
    report.stats["entries_with_year"] = years_count
    return report


# ==============================================================================
# VALIDATION FUNCTIONS CHO MILESTONE 3 (REFERENCE MATCHING PIPELINE)
# ==============================================================================

VALID_PARTITIONS: Set[str] = {"train", "valid", "test"}


def validate_predictions_table(
    table: pa.Table,
    bibtex_table: Optional[pa.Table] = None,
    references_table: Optional[pa.Table] = None,
    papers_table: Optional[pa.Table] = None,
) -> ValidationReport:
    """
    Kiểm tra chất lượng và tính toàn vẹn cho bảng 'predictions' (Milestone 3):
    - Khớp Schema với PREDICTIONS_SCHEMA:
      (arxiv_id, partition, citation_key, groundtruth_arxiv_id, cand_1..cand_5).
    - 'arxiv_id', 'partition', 'citation_key' không được null hoặc rỗng.
    - 'partition' chỉ được nhận 1 trong 3 giá trị: 'train', 'valid', 'test'.
    - Tính duy nhất: Cặp (arxiv_id, citation_key) là duy nhất cho mỗi dòng dự đoán.
    - Không trùng lặp ứng viên trong cùng 1 dòng: Các ứng viên từ cand_1 đến cand_5 không được trùng nhau.
    - Khóa ngoại:
      * Nếu có bibtex_table: Mọi cặp (arxiv_id, citation_key) phải tồn tại trong bibtex_table.
      * Nếu có references_table: Các ứng viên cand_1..cand_5 và groundtruth_arxiv_id (nếu không null)
        phải tồn tại trong references của cùng bài báo (arxiv_id).
      * Nếu có papers_table: Mọi arxiv_id phải tồn tại trong papers_table.
    """
    report = ValidationReport(table_name="predictions")
    report.stats["total_rows"] = table.num_rows

    # 1. Kiểm tra Schema
    if not table.schema.equals(PREDICTIONS_SCHEMA):
        for expected_field in PREDICTIONS_SCHEMA:
            field_name = expected_field.name
            if field_name not in table.column_names:
                report.add_error(f"Thiếu cột bắt buộc '{field_name}'")
            else:
                actual_field = table.field(field_name)
                if actual_field.type != expected_field.type:
                    report.add_error(
                        f"Sai kiểu dữ liệu cột '{field_name}': mong đợi {expected_field.type}, thực tế {actual_field.type}"
                    )
        unexpected_cols = set(table.column_names) - set(PREDICTIONS_SCHEMA.names)
        if unexpected_cols:
            report.add_error(f"Phát hiện các cột thừa không thuộc schema 'predictions': {sorted(list(unexpected_cols))}")

    if not report.is_valid:
        return report

    if table.num_rows == 0:
        report.add_warning("Bảng 'predictions' không có dữ liệu nào.")
        return report

    arxiv_ids = table.column("arxiv_id").to_pylist()
    partitions = table.column("partition").to_pylist()
    citation_keys = table.column("citation_key").to_pylist()
    groundtruths = table.column("groundtruth_arxiv_id").to_pylist()
    cand1_list = table.column("cand_1").to_pylist()
    cand2_list = table.column("cand_2").to_pylist()
    cand3_list = table.column("cand_3").to_pylist()
    cand4_list = table.column("cand_4").to_pylist()
    cand5_list = table.column("cand_5").to_pylist()

    seen_pairs: Set[Tuple[str, str]] = set()
    dup_pairs: List[str] = []
    partition_counts: Dict[str, int] = {}
    with_gt_count = 0
    with_cand1_count = 0

    # Tự động nhận diện và bảo vệ nếu người dùng đảo vị trí bibtex_table và references_table
    if bibtex_table is not None and "ref_arxiv_id" in bibtex_table.column_names and "citation_key" not in bibtex_table.column_names:
        if references_table is not None and "citation_key" in references_table.column_names and "ref_arxiv_id" not in references_table.column_names:
            bibtex_table, references_table = references_table, bibtex_table

    # Chuẩn bị lookup cho references nếu có
    refs_by_paper: Optional[Dict[str, Set[str]]] = None
    if references_table is not None:
        if "ref_arxiv_id" not in references_table.column_names:
            report.add_error("Bảng references_table truyền vào không chứa cột bắt buộc 'ref_arxiv_id'.")
        else:
            refs_by_paper = {}
            r_citing_ids = references_table.column("arxiv_id").to_pylist()
            r_ref_ids = references_table.column("ref_arxiv_id").to_pylist()
            for cid, rid in zip(r_citing_ids, r_ref_ids):
                if cid and rid:
                    cid_clean = str(cid).strip()
                    rid_norm = normalize_arxiv_id(rid)
                    if rid_norm:
                        refs_by_paper.setdefault(cid_clean, set()).add(rid_norm)

    # Chuẩn bị lookup cho bibtex nếu có
    bibtex_pairs: Optional[Set[Tuple[str, str]]] = None
    if bibtex_table is not None:
        if "citation_key" not in bibtex_table.column_names:
            report.add_error("Bảng bibtex_table truyền vào không chứa cột bắt buộc 'citation_key'.")
        else:
            b_aids = bibtex_table.column("arxiv_id").to_pylist()
            b_keys = bibtex_table.column("citation_key").to_pylist()
            bibtex_pairs = {(str(a).strip(), str(k).strip()) for a, k in zip(b_aids, b_keys) if a and k}

    for idx in range(table.num_rows):
        row_num = idx + 1
        aid = arxiv_ids[idx]
        part = partitions[idx]
        ckey = citation_keys[idx]
        gt = groundtruths[idx]

        if aid is None or str(aid).strip() == "":
            report.add_error(f"Dòng {row_num}: 'arxiv_id' bị null hoặc rỗng.")
            aid_str = ""
        else:
            aid_str = str(aid).strip()

        if ckey is None or str(ckey).strip() == "":
            report.add_error(f"Dòng {row_num} (Bài: {aid_str}): 'citation_key' bị null hoặc rỗng.")
            ckey_str = ""
        else:
            ckey_str = str(ckey).strip()

        if aid_str and ckey_str:
            pair = (aid_str, ckey_str)
            if pair in seen_pairs:
                dup_pairs.append(f"{aid_str}#{ckey_str}")
            seen_pairs.add(pair)

            if bibtex_pairs is not None and pair not in bibtex_pairs:
                report.add_error(
                    f"Dòng {row_num}: Cặp (arxiv_id='{aid_str}', citation_key='{ckey_str}') "
                    f"không tồn tại trong bảng 'bibtex'."
                )

        if part is None or str(part).strip() == "":
            report.add_error(f"Dòng {row_num} (Bài: {aid_str}): 'partition' bị null hoặc rỗng.")
        else:
            part_clean = str(part).strip().lower()
            partition_counts[part_clean] = partition_counts.get(part_clean, 0) + 1
            if part_clean not in VALID_PARTITIONS:
                report.add_error(
                    f"Dòng {row_num} (Bài: {aid_str}): 'partition' không hợp lệ ('{part}'). "
                    f"Chỉ cho phép: {sorted(list(VALID_PARTITIONS))}"
                )

        if gt is not None and str(gt).strip() != "":
            with_gt_count += 1
            gt_str = str(gt).strip()
            if refs_by_paper is not None and aid_str in refs_by_paper:
                gt_norm = normalize_arxiv_id(gt_str)
                if gt_norm not in refs_by_paper[aid_str]:
                    report.add_warning(
                        f"Dòng {row_num} (Bài: {aid_str}, Key: {ckey_str}): 'groundtruth_arxiv_id' ('{gt_str}') "
                        f"không có trong danh sách references của bài báo."
                    )

        # Lấy danh sách ứng viên cand_1..cand_5
        cands_raw = [cand1_list[idx], cand2_list[idx], cand3_list[idx], cand4_list[idx], cand5_list[idx]]
        cands_clean = [str(c).strip() for c in cands_raw if c is not None and str(c).strip() != ""]

        if cand1_list[idx] is not None and str(cand1_list[idx]).strip() != "":
            with_cand1_count += 1

        # Kiểm tra trùng lặp candidate trong top-5
        if len(cands_clean) != len(set(cands_clean)):
            report.add_error(
                f"Dòng {row_num} (Bài: {aid_str}, Key: {ckey_str}): Trùng lặp candidate trong top-5 ({cands_clean})."
            )

        # Kiểm tra candidates có thuộc references của cùng bài báo không
        if refs_by_paper is not None and aid_str in refs_by_paper:
            valid_refs = refs_by_paper[aid_str]
            for rank_idx, cand_id in enumerate(cands_clean, start=1):
                cand_norm = normalize_arxiv_id(cand_id)
                if cand_norm not in valid_refs:
                    report.add_error(
                        f"Dòng {row_num} (Bài: {aid_str}, Key: {ckey_str}): Ứng viên cand_{rank_idx} ('{cand_id}') "
                        f"không tồn tại trong bảng 'references' của bài báo này."
                    )

    if dup_pairs:
        report.add_error(
            f"Phát hiện {len(dup_pairs)} cặp (arxiv_id, citation_key) bị trùng lặp trong 'predictions': {dup_pairs[:10]}"
        )

    if papers_table is not None:
        valid_paper_ids = set(str(x).strip() for x in papers_table.column("arxiv_id").to_pylist() if x)
        orphan_papers = set(str(aid).strip() for aid in arxiv_ids if aid and str(aid).strip() not in valid_paper_ids)
        if orphan_papers:
            report.add_error(
                f"Vi phạm khóa ngoại (FK violation): Có {len(orphan_papers)} bài báo trong 'predictions' "
                f"không tồn tại trong 'papers': {sorted(list(orphan_papers))[:10]}"
            )

    report.stats["unique_predictions"] = len(seen_pairs)
    report.stats["unique_papers"] = len(set(str(a).strip() for a in arxiv_ids if a))
    report.stats["partition_counts"] = partition_counts
    report.stats["entries_with_groundtruth"] = with_gt_count
    report.stats["entries_with_candidates"] = with_cand1_count
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
    s2_succeeded_count: Optional[int] = None,
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

    # Thống kê dung lượng theo publication: cộng mọi version của cùng paper trước,
    # sau đó mới lấy trung bình để denominator đúng với yêu cầu "average paper size".
    avg_orig = 0.0
    avg_filt = 0.0
    source_papers_measured = 0
    if source_status_records:
        per_paper: Dict[str, Dict[str, int]] = {}
        for record in source_status_records:
            arxiv_id = str(record.get("arxiv_id") or "").strip()
            if not arxiv_id:
                continue
            download = record.get("download") or {}
            extraction = record.get("extraction") or {}
            archive_bytes = record.get("archive_bytes", download.get("archive_bytes", 0))
            filtered_bytes = record.get("filtered_bytes", extraction.get("filtered_bytes", 0))
            totals = per_paper.setdefault(arxiv_id, {"archive": 0, "filtered": 0})
            totals["archive"] += int(archive_bytes or 0)
            totals["filtered"] += int(filtered_bytes or 0)
        source_papers_measured = len(per_paper)
        avg_orig = sum(item["archive"] for item in per_paper.values()) / max(1, source_papers_measured)
        avg_filt = sum(item["filtered"] for item in per_paper.values()) / max(1, source_papers_measured)

    reduction_rate = round((avg_orig - avg_filt) / max(1.0, avg_orig), 4) if avg_orig > 0 else 0.0

    # Thống kê references: Tách biệt All References vs Eligible arXiv References
    eligible_refs_count = references_table.num_rows
    avg_eligible_refs = round(eligible_refs_count / max(1, success_papers), 2)

    raw_refs_count = total_raw_references_count if total_raw_references_count is not None else eligible_refs_count
    avg_all_refs = round(raw_refs_count / max(1, success_papers), 2)

    s2_attempted = s2_attempted_count if s2_attempted_count is not None else success_papers
    if s2_succeeded_count is None:
        # Backward-compatible fallback only. Callers with S2 statuses must pass the
        # actual count of `ok` responses so papers with zero eligible references
        # are not incorrectly classified as failures.
        s2_succeeded = (
            len(set(references_table.column("arxiv_id").to_pylist()))
            if references_table.num_rows > 0
            else 0
        )
    else:
        s2_succeeded = s2_succeeded_count
    ref_success_rate = round(s2_succeeded / max(1, s2_attempted), 4)

    return {
        "total_assigned": total_assigned,
        "papers_scraped_successfully": success_papers,
        "paper_success_rate": paper_success_rate,
        "avg_original_source_bytes": round(avg_orig, 2),
        "avg_filtered_source_bytes": round(avg_filt, 2),
        "source_size_denominator_papers": source_papers_measured,
        "reduction_rate": reduction_rate,
        "avg_all_references_per_paper": avg_all_refs,
        "avg_eligible_arxiv_references_per_paper": avg_eligible_refs,
        "reference_metadata_success_rate": ref_success_rate,
        "reference_metadata_success_numerator": s2_succeeded,
        "reference_metadata_success_denominator": s2_attempted,
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


