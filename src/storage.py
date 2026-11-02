"""
Module storage.py: Quản lý định nghĩa PyArrow Schema và lưu trữ Sharded Parquet.
Thuộc sở hữu của Member 4 - Data Quality, Schema và Storage Owner.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pyarrow as pa
import pyarrow.parquet as pq

# ==============================================================================
# 1. ĐỊNH NGHĨA SCHEMAS CHÍNH THỨC CHO CẢ 3 MILESTONES (EXPLICIT PYARROW SCHEMAS)
# ==============================================================================

# Milestone 1: Bảng thông tin bài báo
PAPERS_SCHEMA = pa.schema([
    pa.field("arxiv_id", pa.string(), nullable=False),
    pa.field("title", pa.string(), nullable=False),
    pa.field("authors", pa.list_(pa.string()), nullable=False),
    pa.field("submission_date", pa.string(), nullable=False),
    pa.field("revised_dates", pa.list_(pa.string()), nullable=False),
    pa.field("venue", pa.string(), nullable=True),
])

# Milestone 1: Bảng trích dẫn (Chỉ chứa tài liệu tham khảo có ArXiv ID)
REFERENCES_SCHEMA = pa.schema([
    pa.field("arxiv_id", pa.string(), nullable=False),
    pa.field("ref_arxiv_id", pa.string(), nullable=False),
    pa.field("ref_title", pa.string(), nullable=False),
    pa.field("ref_authors", pa.list_(pa.string()), nullable=False),
    pa.field("ref_submission_date", pa.string(), nullable=True),
    pa.field("ref_s2_id", pa.string(), nullable=True),
])

# Milestone 2: Bảng các node phân cấp (Deduplicated across versions)
ELEMENTS_SCHEMA = pa.schema([
    pa.field("element_id", pa.string(), nullable=False),
    pa.field("arxiv_id", pa.string(), nullable=False),
    pa.field("kind", pa.string(), nullable=False),
    pa.field("content", pa.string(), nullable=False),
])

# Milestone 2: Bảng quan hệ cây phân cấp (Cạnh cha - con cho từng version)
HIERARCHY_SCHEMA = pa.schema([
    pa.field("arxiv_id", pa.string(), nullable=False),
    pa.field("version", pa.int32(), nullable=False),
    pa.field("element_id", pa.string(), nullable=False),
    pa.field("parent_id", pa.string(), nullable=False),
])

# Milestone 2: Bảng thông tin BibTeX đã deduplicate và union fields
BIBTEX_SCHEMA = pa.schema([
    pa.field("arxiv_id", pa.string(), nullable=False),
    pa.field("citation_key", pa.string(), nullable=False),
    pa.field("entry_type", pa.string(), nullable=False),
    pa.field("title", pa.string(), nullable=False),
    pa.field("authors", pa.list_(pa.string()), nullable=False),
    pa.field("year", pa.int32(), nullable=True),
    pa.field("doi", pa.string(), nullable=True),
    pa.field("journal", pa.string(), nullable=True),
    pa.field("url", pa.string(), nullable=True),
])

# Milestone 3: Bảng dự đoán ranking top-5 candidates
PREDICTIONS_SCHEMA = pa.schema([
    pa.field("arxiv_id", pa.string(), nullable=False),
    pa.field("partition", pa.string(), nullable=False),
    pa.field("citation_key", pa.string(), nullable=False),
    pa.field("groundtruth_arxiv_id", pa.string(), nullable=True),
    pa.field("cand_1", pa.string(), nullable=True),
    pa.field("cand_2", pa.string(), nullable=True),
    pa.field("cand_3", pa.string(), nullable=True),
    pa.field("cand_4", pa.string(), nullable=True),
    pa.field("cand_5", pa.string(), nullable=True),
])

TABLE_SCHEMAS: Dict[str, pa.Schema] = {
    "papers": PAPERS_SCHEMA,
    "references": REFERENCES_SCHEMA,
    "elements": ELEMENTS_SCHEMA,
    "hierarchy": HIERARCHY_SCHEMA,
    "bibtex": BIBTEX_SCHEMA,
    "predictions": PREDICTIONS_SCHEMA,
}


# ==============================================================================
# 2. HÀM CHUYỂN ĐỔI RECORDS -> PYARROW TABLE THEO SCHEMA
# ==============================================================================

def create_table_from_records(records: List[Dict[str, Any]], schema: pa.Schema) -> pa.Table:
    """
    Chuyển đổi danh sách dict records thành PyArrow Table tuân thủ chặt chẽ schema.
    Tránh tình trạng suy luận kiểu tự động (type inference) gây lệch kiểu giữa các shards.
    """
    if not records:
        # Tạo bảng rỗng với schema định sẵn
        arrays = [pa.array([], type=field.type) for field in schema]
        return pa.Table.from_arrays(arrays, schema=schema)

    data_by_col: Dict[str, List[Any]] = {field.name: [] for field in schema}

    for record in records:
        for field in schema:
            col_name = field.name
            val = record.get(col_name)

            # Xử lý list rỗng hoặc null cho các trường kiểu list
            if isinstance(field.type, pa.ListType):
                if val is None:
                    val = [] if not field.nullable else None
                elif not isinstance(val, (list, tuple)):
                    val = [str(val)]
                else:
                    val = [str(x) for x in val]
            elif val is None and not field.nullable:
                raise ValueError(f"Trường non-nullable '{col_name}' bị null trong record: {record}")
            data_by_col[col_name].append(val)

    arrays = []
    for field in schema:
        col_name = field.name
        col_type = field.type
        arrays.append(pa.array(data_by_col[col_name], type=col_type))

    return pa.Table.from_arrays(arrays, schema=schema)


# ==============================================================================
# 3. LƯU TRỮ VÀ ĐỌC SHARDED PARQUET (ATOMIC STAGING)
# ==============================================================================

def write_sharded_parquet(
    table: pa.Table,
    output_dir: Union[str, Path],
    table_name: str,
    max_rows_per_shard: int = 5000,
    compression: str = "snappy"
) -> List[Path]:
    """
    Ghi PyArrow Table thành các file Parquet có phân mảnh (sharded) theo format:
    output_dir / table_name / part-00000.parquet, part-00001.parquet,...
    
    Áp dụng kỹ thuật Atomic Staging: Ghi vào thư mục tạm trước, khi thành công
    mới di chuyển vào output_dir để tránh hỏng dữ liệu nếu bị ngắt tiến trình.
    """
    out_path = Path(output_dir) / table_name
    expected_schema = TABLE_SCHEMAS.get(table_name)
    if expected_schema:
        # Kiểm tra chặt chẽ tập hợp tên cột: không được thừa/thiếu cột
        if set(table.column_names) != set(expected_schema.names):
            raise ValueError(
                f"Các cột của table không khớp với schema chuẩn của '{table_name}': "
                f"hiện có {table.column_names}, mong đợi {expected_schema.names}"
            )
        # Sắp xếp đúng thứ tự cột theo schema chuẩn trước khi cast
        table = table.select(expected_schema.names)
        if not table.schema.equals(expected_schema):
            try:
                table = table.cast(expected_schema)
            except Exception as e:
                raise ValueError(f"Table không khớp với schema chuẩn của '{table_name}': {e}")

    total_rows = table.num_rows
    created_shards: List[Path] = []

    # Sử dụng thư mục tạm để đảm bảo ghi nguyên tử (atomic)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_table_dir = Path(tmp_dir) / table_name
        tmp_table_dir.mkdir(parents=True, exist_ok=True)

        if total_rows == 0:
            # Ghi ít nhất 1 file shard rỗng nếu bảng không có dữ liệu
            shard_file = tmp_table_dir / "part-00000.parquet"
            pq.write_table(table, shard_file, compression=compression)
        else:
            num_shards = (total_rows + max_rows_per_shard - 1) // max_rows_per_shard
            for shard_idx in range(num_shards):
                offset = shard_idx * max_rows_per_shard
                length = min(max_rows_per_shard, total_rows - offset)
                slice_table = table.slice(offset, length)

                shard_file = tmp_table_dir / f"part-{shard_idx:05d}.parquet"
                pq.write_table(slice_table, shard_file, compression=compression)

        # Di chuyển an toàn vào đích và dọn dẹp các shard cũ
        out_path.mkdir(parents=True, exist_ok=True)
        # Xóa các shard parquet cũ nếu có để tránh ghost data khi rerun với ít shard hơn
        for old_shard in out_path.glob("*.parquet"):
            try:
                old_shard.unlink()
            except OSError:
                pass

        for f in tmp_table_dir.glob("*.parquet"):
            dest_file = out_path / f.name
            shutil.copy2(f, dest_file)
            created_shards.append(dest_file)

    return sorted(created_shards)


def read_sharded_parquet(
    table_dir: Union[str, Path],
    expected_schema: Optional[pa.Schema] = None
) -> pa.Table:
    """
    Đọc toàn bộ các file sharded Parquet trong table_dir và gộp thành 1 PyArrow Table duy nhất.
    """
    p = Path(table_dir)
    if not p.exists():
        raise FileNotFoundError(f"Thư mục không tồn tại: {table_dir}")

    parquet_files = sorted(list(p.glob("*.parquet")))
    if not parquet_files:
        raise FileNotFoundError(f"Không tìm thấy file parquet nào trong: {table_dir}")

    # Đọc dataset qua PyArrow
    dataset = pq.ParquetDataset(parquet_files, schema=expected_schema)
    table = dataset.read()

    if expected_schema:
        if set(table.column_names) != set(expected_schema.names):
            raise ValueError(
                f"Dữ liệu đọc lên không đủ cột chuẩn: hiện có {table.column_names}, mong đợi {expected_schema.names}"
            )
        table = table.select(expected_schema.names)
        if not table.schema.equals(expected_schema):
            table = table.cast(expected_schema)

    return table
