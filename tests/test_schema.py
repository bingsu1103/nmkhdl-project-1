"""
Test suite cho Schema contracts, Validation, Normalization và Parquet Storage.
Thuộc sở hữu của Member 4 - Data Quality, Schema và Storage Owner.
"""

import tempfile
from pathlib import Path

import pyarrow as pa
import pytest

from src.storage import (
    BIBTEX_SCHEMA,
    ELEMENTS_SCHEMA,
    HIERARCHY_SCHEMA,
    PAPERS_SCHEMA,
    REFERENCES_SCHEMA,
    create_table_from_records,
    read_sharded_parquet,
    write_sharded_parquet,
)
from src.normalize import (
    normalize_arxiv_id,
    normalize_authors,
    normalize_iso_date,
    normalize_paper_record,
    normalize_and_deduplicate_references,
)
from src.validate import (
    compute_crawl_statistics,
    load_manifest_assigned_ids,
    reconcile_crawling_counts,
    validate_bibtex_table,
    validate_elements_table,
    validate_hierarchy_table,
    validate_papers_table,
    validate_references_table,
)


def test_papers_schema_valid_and_roundtrip():
    """Kiểm tra tạo bảng papers hợp lệ, xác thực và ghi/đọc Parquet sharding."""
    raw_records = [
        {
            "arxiv_id": "2310.12345v2",
            "title": "Attention Is All You Need",
            "authors": ["Ashish Vaswani", "Noam Shazeer"],
            "submission_date": "2023-10-15T10:00:00Z",
            "revised_dates": ["2023-11-01T12:00:00Z"],
            "venue": "NeurIPS",
        },
        {
            "arxiv_id": "math/0306123",
            "title": "On the Ricci flow",
            "authors": ["Grisha Perelman"],
            "submission_date": "2003-06-01",
            "revised_dates": None,  # Kiểm tra trường hợp revised_dates là None
            "venue": None,
        },
    ]

    # Chuẩn hóa records
    normalized_records = [normalize_paper_record(r) for r in raw_records]
    assert normalized_records[0]["arxiv_id"] == "2310.12345"  # Đã loại bỏ version
    assert normalized_records[1]["submission_date"] == "2003-06-01T00:00:00Z"

    # Chuyển thành PyArrow Table
    table = create_table_from_records(normalized_records, PAPERS_SCHEMA)
    assert table.num_rows == 2

    # Chạy validation
    report = validate_papers_table(table)
    assert report.is_valid, f"Validation thất bại: {report.errors}"
    assert report.stats["unique_papers"] == 2

    # Ghi ra Parquet sharded trong thư mục tạm
    with tempfile.TemporaryDirectory() as tmp_dir:
        shards = write_sharded_parquet(table, tmp_dir, "papers", max_rows_per_shard=1)
        assert len(shards) == 2  # Phân thành 2 shards vì max_rows_per_shard=1

        # Đọc lại và so sánh
        loaded_table = read_sharded_parquet(Path(tmp_dir) / "papers", PAPERS_SCHEMA)
        assert loaded_table.num_rows == 2
        assert loaded_table.schema.equals(PAPERS_SCHEMA)
        assert loaded_table.column("arxiv_id").to_pylist() == ["2310.12345", "math/0306123"]


def test_papers_validation_fails_on_duplicate_and_missing_title():
    """Kiểm tra validator bắt đúng lỗi trùng ID và thiếu tiêu đề."""
    invalid_records = [
        {
            "arxiv_id": "2310.12345",
            "title": "",  # Lỗi: Tiêu đề rỗng
            "authors": ["Author A"],
            "submission_date": "2023-10-15T10:00:00Z",
            "revised_dates": [],
            "venue": None,
        },
        {
            "arxiv_id": "2310.12345",  # Lỗi: Trùng lặp arxiv_id
            "title": "Duplicate Paper",
            "authors": ["Author B"],
            "submission_date": "2023-10-16T10:00:00Z",
            "revised_dates": [],
            "venue": None,
        },
    ]

    table = create_table_from_records(invalid_records, PAPERS_SCHEMA)
    report = validate_papers_table(table)

    assert not report.is_valid
    assert any("tiêu đề" in err.lower() or "title" in err.lower() for err in report.errors)
    assert any("trùng lặp" in err.lower() or "duplicate" in err.lower() for err in report.errors)


def test_references_normalization_and_deduplication():
    """Kiểm tra lọc eligible reference và khử trùng lặp cặp (arxiv_id, ref_arxiv_id)."""
    raw_refs = [
        # Hợp lệ 1
        {
            "arxiv_id": "2310.12345",
            "ref_arxiv_id": "1706.03762",
            "ref_title": "Attention Is All You Need",
            "ref_authors": ["Vaswani et al."],
            "ref_submission_date": "2017-06-12",
            "ref_s2_id": "s2-12345",
        },
        # Bị loại do không có ref_arxiv_id (chỉ có trích dẫn sách/journal không trên arXiv)
        {
            "arxiv_id": "2310.12345",
            "ref_arxiv_id": None,
            "ref_title": "Non-arXiv Book",
            "ref_authors": ["Some Author"],
            "ref_submission_date": "2000-01-01",
            "ref_s2_id": "s2-99999",
        },
        # Bị loại do trùng lặp cặp (2310.12345, 1706.03762)
        {
            "arxiv_id": "2310.12345",
            "ref_arxiv_id": "1706.03762v5",  # Bản version khác của cùng tài liệu
            "ref_title": "Attention Is All You Need (v5)",
            "ref_authors": ["Vaswani et al."],
            "ref_submission_date": "2017-06-12",
            "ref_s2_id": "s2-12345",
        },
        # Hợp lệ 2
        {
            "arxiv_id": "2310.12345",
            "ref_arxiv_id": "1810.04805",
            "ref_title": "BERT: Pre-training of Deep Bidirectional Transformers",
            "ref_authors": ["Jacob Devlin"],
            "ref_submission_date": "2018-10-11",
            "ref_s2_id": "s2-67890",
        },
    ]

    cleaned_refs, dropped_count = normalize_and_deduplicate_references(raw_refs)
    assert len(cleaned_refs) == 2
    assert dropped_count == 2

    table = create_table_from_records(cleaned_refs, REFERENCES_SCHEMA)
    report = validate_references_table(table)
    assert report.is_valid, f"Validation thất bại: {report.errors}"


def test_references_foreign_key_integrity():
    """Kiểm tra phát hiện vi phạm khóa ngoại (citing paper không có trong bảng papers)."""
    paper_records = [
        {
            "arxiv_id": "2310.12345",
            "title": "Known Paper",
            "authors": ["Author A"],
            "submission_date": "2023-10-15T10:00:00Z",
            "revised_dates": [],
            "venue": None,
        }
    ]
    papers_table = create_table_from_records(paper_records, PAPERS_SCHEMA)

    ref_records = [
        # Trích dẫn từ bài lạ không có trong papers_table
        {
            "arxiv_id": "9999.99999",
            "ref_arxiv_id": "1706.03762",
            "ref_title": "Reference",
            "ref_authors": ["Author B"],
            "ref_submission_date": "2017-06-12T00:00:00Z",
            "ref_s2_id": "s2-111",
        }
    ]
    refs_table = create_table_from_records(ref_records, REFERENCES_SCHEMA)

    report = validate_references_table(refs_table, papers_table=papers_table)
    assert not report.is_valid
    assert any("khóa ngoại" in err.lower() or "fk violation" in err.lower() for err in report.errors)


def test_reconciliation_logic():
    """Kiểm tra logic đối soát số lượng ID được giao vs kết quả cào."""
    assigned_ids = ["2310.00001", "2310.00002", "2310.00003"]
    
    # 2 bài thành công
    success_records = [
        {
            "arxiv_id": "2310.00001",
            "title": "Paper 1",
            "authors": ["A"],
            "submission_date": "2023-10-01T00:00:00Z",
            "revised_dates": [],
            "venue": None,
        },
        {
            "arxiv_id": "2310.00002",
            "title": "Paper 2",
            "authors": ["B"],
            "submission_date": "2023-10-02T00:00:00Z",
            "revised_dates": [],
            "venue": None,
        },
    ]
    papers_table = create_table_from_records(success_records, PAPERS_SCHEMA)

    # 1 bài ghi nhận thất bại rõ ràng (404 / deleted)
    failed_discovery_ids = ["2310.00003"]

    result = reconcile_crawling_counts(assigned_ids, papers_table, failed_discovery_ids)
    assert result["is_reconciled"] is True
    assert result["unaccounted_count"] == 0
    assert result["success_rate"] == pytest.approx(2 / 3)


def test_ghost_shards_prevention():
    """Kiểm tra rerun với ít shard hơn không để lại ghost shards cũ."""
    records_large = [
        {
            "arxiv_id": f"2310.{i:05d}",
            "title": f"Paper {i}",
            "authors": [f"Author {i}"],
            "submission_date": "2023-10-01T00:00:00Z",
            "revised_dates": [],
            "venue": None,
        }
        for i in range(5)
    ]
    table_large = create_table_from_records(records_large, PAPERS_SCHEMA)

    with tempfile.TemporaryDirectory() as tmp_dir:
        # Lần 1: 5 dòng, max_rows_per_shard=1 => sinh 5 shards (part-00000 đến part-00004)
        shards_1 = write_sharded_parquet(table_large, tmp_dir, "papers", max_rows_per_shard=1)
        assert len(shards_1) == 5

        # Lần 2: Chỉ còn 2 dòng, max_rows_per_shard=1 => chỉ được sinh 2 shards
        records_small = records_large[:2]
        table_small = create_table_from_records(records_small, PAPERS_SCHEMA)
        shards_2 = write_sharded_parquet(table_small, tmp_dir, "papers", max_rows_per_shard=1)
        assert len(shards_2) == 2

        # Kiểm tra thư mục đích chỉ chứa đúng 2 shards, không còn 3 shards cũ
        loaded_table = read_sharded_parquet(Path(tmp_dir) / "papers", PAPERS_SCHEMA)
        assert loaded_table.num_rows == 2


def test_validate_missing_columns_does_not_crash():
    """Kiểm tra validator báo lỗi và dừng an toàn mà không văng Exception khi bảng thiếu cột."""
    incomplete_schema = pa.schema([
        pa.field("random_column", pa.string())
    ])
    incomplete_table = pa.Table.from_arrays([pa.array(["abc"])], schema=incomplete_schema)

    # validate_papers_table không được ném KeyError
    report_papers = validate_papers_table(incomplete_table)
    assert not report_papers.is_valid
    assert any("thiếu cột" in err.lower() for err in report_papers.errors)

    # validate_references_table cũng không được ném KeyError
    report_refs = validate_references_table(incomplete_table)
    assert not report_refs.is_valid
    assert any("thiếu cột" in err.lower() for err in report_refs.errors)


def test_normalize_authors_and_export_mirror():
    """Kiểm tra normalize_authors với single string và normalize_arxiv_id với export domain / pdf."""
    # Test normalize_authors không bị cắt vụn ký tự
    authors = normalize_authors("Vaswani, Ashish")
    assert authors == ["Vaswani, Ashish"]

    # Test object có attribute 'name' (như arxiv.Result)
    class DummyAuthor:
        def __init__(self, name):
            self.name = name

    authors_obj = normalize_authors([DummyAuthor("Noam Shazeer")])
    assert authors_obj == ["Noam Shazeer"]

    # Test normalize_arxiv_id với export.arxiv.org và .pdf
    assert normalize_arxiv_id("https://export.arxiv.org/abs/2310.12345v2") == "2310.12345"
    assert normalize_arxiv_id("https://export.arxiv.org/pdf/2310.12345v1.pdf") == "2310.12345"
    assert normalize_arxiv_id("arxiv:2310.12345v3") == "2310.12345"


def test_compute_crawl_statistics():
    """Kiểm tra hàm compute_crawl_statistics tính toán đầy đủ các chỉ số thống kê."""
    assigned_ids = ["2310.00001", "2310.00002", "2310.00003"]
    papers_table = create_table_from_records([
        {
            "arxiv_id": "2310.00001",
            "title": "Paper 1",
            "authors": ["A"],
            "submission_date": "2023-10-01T00:00:00Z",
            "revised_dates": [],
            "venue": None,
        },
        {
            "arxiv_id": "2310.00002",
            "title": "Paper 2",
            "authors": ["B"],
            "submission_date": "2023-10-02T00:00:00Z",
            "revised_dates": [],
            "venue": None,
        },
    ], PAPERS_SCHEMA)

    refs_table = create_table_from_records([
        {
            "arxiv_id": "2310.00001",
            "ref_arxiv_id": "1706.03762",
            "ref_title": "Ref 1",
            "ref_authors": ["Auth 1"],
            "ref_submission_date": "2017-06-12",
            "ref_s2_id": "s2-1",
        },
        {
            "arxiv_id": "2310.00001",
            "ref_arxiv_id": "1810.04805",
            "ref_title": "Ref 2",
            "ref_authors": ["Auth 2"],
            "ref_submission_date": "2018-10-11",
            "ref_s2_id": "s2-2",
        },
    ], REFERENCES_SCHEMA)

    stats = compute_crawl_statistics(
        assigned_ids=assigned_ids,
        papers_table=papers_table,
        references_table=refs_table,
        source_status_records=[
            {
                "arxiv_id": "2310.00001",
                "download": {"archive_bytes": 1000},
                "extraction": {"filtered_bytes": 300},
            },
            {
                "arxiv_id": "2310.00001",
                "download": {"archive_bytes": 500},
                "extraction": {"filtered_bytes": 200},
            },
            {
                "arxiv_id": "2310.00002",
                "download": {"archive_bytes": 2000},
                "extraction": {"filtered_bytes": 700},
            },
        ],
        s2_attempted_count=2,
        s2_succeeded_count=2,
        total_raw_references_count=6,  # 6 trích dẫn thô từ S2, trong đó có 2 bài hợp lệ
    )

    assert stats["total_assigned"] == 3
    assert stats["papers_scraped_successfully"] == 2
    assert stats["paper_success_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert stats["avg_original_source_bytes"] == 1750.0
    assert stats["avg_filtered_source_bytes"] == 600.0
    assert stats["source_size_denominator_papers"] == 2
    assert stats["reduction_rate"] == pytest.approx(0.6571, abs=1e-3)
    assert stats["avg_all_references_per_paper"] == 3.0  # 6 / 2 = 3.0
    assert stats["avg_eligible_arxiv_references_per_paper"] == 1.0  # 2 / 2 = 1.0
    # Paper 2 có thể có zero eligible arXiv reference nhưng S2 request vẫn thành công.
    assert stats["reference_metadata_success_rate"] == 1.0
    assert stats["reference_metadata_success_numerator"] == 2
    assert stats["reference_metadata_success_denominator"] == 2


def test_normalize_iso_date_datetime_and_offset():
    """Kiểm tra normalize_iso_date với datetime object và chuỗi có offset / space."""
    from datetime import datetime, timezone

    # 1. Datetime object
    dt = datetime(2023, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert normalize_iso_date(dt) == "2023-10-15T12:00:00Z"

    # 2. String có dấu cách và timezone offset (kiểu str(paper.published) từ arxiv.py)
    s_space = "2023-10-15 12:00:00+00:00"
    assert normalize_iso_date(s_space) == "2023-10-15T12:00:00Z"

    # 3. String ISO có offset khác UTC (chuyển đổi về UTC đuôi Z)
    s_offset = "2023-10-15T19:00:00+07:00"
    assert normalize_iso_date(s_offset) == "2023-10-15T12:00:00Z"


def test_storage_column_swap_prevention():
    """Kiểm tra write_sharded_parquet và read_sharded_parquet không tráo đổi cột khi thứ tự cột bị đảo."""
    # Tạo bảng có các cột bị đảo ngược thứ tự hoàn toàn so với PAPERS_SCHEMA
    reversed_names = list(reversed(PAPERS_SCHEMA.names))
    record = {
        "arxiv_id": "2310.12345",
        "title": "Attention Is All You Need",
        "authors": ["Vaswani"],
        "submission_date": "2023-10-15T10:00:00Z",
        "revised_dates": [],
        "venue": "NeurIPS",
    }
    arrays = []
    fields = []
    for col in reversed_names:
        f = PAPERS_SCHEMA.field(col)
        fields.append(f)
        val = record[col]
        arrays.append(pa.array([val], type=f.type))

    unordered_table = pa.Table.from_arrays(arrays, schema=pa.schema(fields))
    assert unordered_table.column_names != PAPERS_SCHEMA.names

    with tempfile.TemporaryDirectory() as tmp_dir:
        write_sharded_parquet(unordered_table, tmp_dir, "papers")
        loaded_table = read_sharded_parquet(Path(tmp_dir) / "papers", PAPERS_SCHEMA)

        assert loaded_table.schema.names == PAPERS_SCHEMA.names
        assert loaded_table.column("arxiv_id").to_pylist() == ["2310.12345"]
        assert loaded_table.column("title").to_pylist() == ["Attention Is All You Need"]
        assert loaded_table.column("venue").to_pylist() == ["NeurIPS"]


def test_storage_strict_column_check():
    """Kiểm tra write_sharded_parquet và read_sharded_parquet ném ValueError nếu thiếu hoặc thừa cột."""
    bad_table = pa.Table.from_arrays([pa.array(["123"])], names=["wrong_column"])
    with tempfile.TemporaryDirectory() as tmp_dir:
        with pytest.raises(ValueError, match="không khớp với schema chuẩn"):
            write_sharded_parquet(bad_table, tmp_dir, "papers")


def test_references_semantic_scholar_raw_format_fallback():
    """Kiểm tra fallback khi Member 3 truyền dictionary gốc từ Semantic Scholar API."""
    raw_s2_data = [
        {
            "arxiv_id": "2310.12345",
            "paperId": "s2-raw-id-123",
            "title": "Attention Is All You Need",
            "authors": [{"name": "Ashish Vaswani"}],
            "publicationDate": "2017-06-12",
            "externalIds": {"ArXiv": "1706.03762"},
        }
    ]
    cleaned_refs, dropped_count = normalize_and_deduplicate_references(raw_s2_data)
    assert len(cleaned_refs) == 1
    assert dropped_count == 0
    ref = cleaned_refs[0]
    assert ref["ref_arxiv_id"] == "1706.03762"
    assert ref["ref_title"] == "Attention Is All You Need"
    assert ref["ref_authors"] == ["Ashish Vaswani"]
    assert ref["ref_s2_id"] == "s2-raw-id-123"
    assert ref["ref_submission_date"] == "2017-06-12T00:00:00Z"


def test_load_manifest_assigned_ids_defensive():
    """Kiểm tra đọc manifest phòng vệ với các tên cột khác nhau: arxiv_id, paper_id, id, v.v."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # 1. Trường hợp có cả member_id và arxiv_id -> phải ưu tiên arxiv_id
        csv1 = Path(tmp_dir) / "manifest1.csv"
        csv1.write_text("member_id,arxiv_id,status\nm1,2310.00001,ok\nm1,2310.00002,ok\n", encoding="utf-8")
        ids1 = load_manifest_assigned_ids(csv1)
        assert ids1 == ["2310.00001", "2310.00002"]

        # 2. Trường hợp tên cột là paper_id
        csv2 = Path(tmp_dir) / "manifest2.csv"
        csv2.write_text("paper_id,extra\n2310.00003,info\n", encoding="utf-8")
        ids2 = load_manifest_assigned_ids(csv2)
        assert ids2 == ["2310.00003"]

        # 3. Trường hợp tên cột là id (hoặc hoa ID)
        csv3 = Path(tmp_dir) / "manifest3.csv"
        csv3.write_text("ID,note\n 2310.00004 \n", encoding="utf-8")
        ids3 = load_manifest_assigned_ids(csv3)
        assert ids3 == ["2310.00004"]  # Tự động strip whitespace

        # 4. Trường hợp cột bất kỳ chứa 'id'
        csv4 = Path(tmp_dir) / "manifest4.csv"
        csv4.write_text("publication_id\n2310.00005\n", encoding="utf-8")
        ids4 = load_manifest_assigned_ids(csv4)
        assert ids4 == ["2310.00005"]

        # 5. Trường hợp fallback cột đầu tiên
        csv5 = Path(tmp_dir) / "manifest5.csv"
        csv5.write_text("code,title\n2310.00006,test\n", encoding="utf-8")
        ids5 = load_manifest_assigned_ids(csv5)
        assert ids5 == ["2310.00006"]

        # 6. File không tồn tại -> trả về rỗng không crash
        ids_nonexistent = load_manifest_assigned_ids(Path(tmp_dir) / "not_found.csv")
        assert ids_nonexistent == []

        # 7. Trường hợp có member_id, start_id, end_id và raw_id -> không được đọc nhầm member_id
        csv7 = Path(tmp_dir) / "manifest7.csv"
        csv7.write_text("member_id,start_id,end_id,raw_id\nm-1,100,200,2310.00007\n", encoding="utf-8")
        ids7 = load_manifest_assigned_ids(csv7)
        assert ids7 == ["2310.00007"]


def test_validation_fails_on_unexpected_columns():
    """Kiểm tra validator phát hiện và từ chối các cột thừa không thuộc schema."""
    # Bảng papers có thừa cột
    data_papers = {
        "arxiv_id": ["2310.12345"],
        "title": ["Sample Paper"],
        "authors": [["Author A"]],
        "submission_date": ["2023-10-15T00:00:00Z"],
        "revised_dates": [["2023-10-16T00:00:00Z"]],
        "venue": ["ArXiv"],
        "extra_column": ["unwanted_data"],
    }
    table_papers = pa.Table.from_pydict(data_papers)
    report_papers = validate_papers_table(table_papers)
    assert not report_papers.is_valid
    assert any("cột thừa không thuộc schema 'papers'" in err for err in report_papers.errors)

    # Bảng references có thừa cột
    data_refs = {
        "arxiv_id": ["2310.12345"],
        "ref_arxiv_id": ["1706.03762"],
        "ref_title": ["Attention Is All You Need"],
        "ref_authors": [["Ashish Vaswani"]],
        "ref_submission_date": ["2017-06-12T00:00:00Z"],
        "ref_s2_id": ["s2-123"],
        "ghost_column": [123],
    }
    table_refs = pa.Table.from_pydict(data_refs)
    report_refs = validate_references_table(table_refs)
    assert not report_refs.is_valid
    assert any("cột thừa không thuộc schema 'references'" in err for err in report_refs.errors)


def test_elements_validation_and_deduplication():
    """Kiểm tra validate_elements_table: kiểm tra schema, deduplication và kind taxonomy."""
    # 1. Bảng hợp lệ (tuân thủ deduplication: câu s1 dùng chung cho cả 2 version)
    records = [
        {"element_id": "2310-12345#root1", "arxiv_id": "2310.12345", "kind": "document", "content": "Version 1 root"},
        {"element_id": "2310-12345#root2", "arxiv_id": "2310.12345", "kind": "document", "content": "Version 2 root"},
        {"element_id": "2310-12345#h1", "arxiv_id": "2310.12345", "kind": "heading", "content": "Introduction"},
        {"element_id": "2310-12345#h2", "arxiv_id": "2310.12345", "kind": "heading", "content": "Background and model"},
        {"element_id": "2310-12345#s1", "arxiv_id": "2310.12345", "kind": "sentence", "content": "We study the citation matching problem"},
    ]
    table = create_table_from_records(records, ELEMENTS_SCHEMA)
    report = validate_elements_table(table)
    assert report.is_valid, f"Validation lỗi: {report.errors}"
    assert report.stats["unique_elements"] == 5
    assert report.stats["kind_counts"]["document"] == 2
    assert report.stats["kind_counts"]["heading"] == 2
    assert report.stats["kind_counts"]["sentence"] == 1

    # Roundtrip Parquet sharding
    with tempfile.TemporaryDirectory() as tmp_dir:
        shards = write_sharded_parquet(table, tmp_dir, "elements", max_rows_per_shard=2)
        assert len(shards) == 3
        loaded = read_sharded_parquet(Path(tmp_dir) / "elements", ELEMENTS_SCHEMA)
        assert loaded.num_rows == 5

    # 2. Kiểm tra vi phạm deduplication: 2 element khác ID nhưng trùng (arxiv_id, kind, content)
    records_duplicate_content = list(records) + [
        {"element_id": "2310-12345#s2", "arxiv_id": "2310.12345", "kind": "sentence", "content": "We study the citation matching problem"}
    ]
    table_dup = create_table_from_records(records_duplicate_content, ELEMENTS_SCHEMA)
    report_dup = validate_elements_table(table_dup)
    assert not report_dup.is_valid
    assert any("khử trùng lặp" in err.lower() or "deduplication" in err.lower() for err in report_dup.errors)

    # 3. Kiểm tra kind không hợp lệ
    records_invalid_kind = [
        {"element_id": "2310-12345#x1", "arxiv_id": "2310.12345", "kind": "invalid_kind_123", "content": "Content"}
    ]
    table_bad_kind = create_table_from_records(records_invalid_kind, ELEMENTS_SCHEMA)
    report_bad_kind = validate_elements_table(table_bad_kind)
    assert not report_bad_kind.is_valid
    assert any("không hợp lệ" in err.lower() for err in report_bad_kind.errors)


def test_hierarchy_validation_tree_integrity():
    """Kiểm tra validate_hierarchy_table: cây phân cấp hợp lệ, phát hiện chu trình, nhiều root, self-parent."""
    # Chuẩn bị elements table chuẩn cho 2 version
    elements_records = [
        {"element_id": "2310-12345#root1", "arxiv_id": "2310.12345", "kind": "document", "content": "Version 1 root"},
        {"element_id": "2310-12345#root2", "arxiv_id": "2310.12345", "kind": "document", "content": "Version 2 root"},
        {"element_id": "2310-12345#h1", "arxiv_id": "2310.12345", "kind": "heading", "content": "Introduction"},
        {"element_id": "2310-12345#h2", "arxiv_id": "2310.12345", "kind": "heading", "content": "Background and model"},
        {"element_id": "2310-12345#s1", "arxiv_id": "2310.12345", "kind": "sentence", "content": "We study the citation matching problem"},
    ]
    elements_table = create_table_from_records(elements_records, ELEMENTS_SCHEMA)

    # 1. Cây hợp lệ cho cả v1 và v2 (s1 xuất hiện ở cả 2 version với cha khác nhau)
    hierarchy_records = [
        {"arxiv_id": "2310.12345", "version": 1, "element_id": "2310-12345#h1", "parent_id": "2310-12345#root1"},
        {"arxiv_id": "2310.12345", "version": 1, "element_id": "2310-12345#s1", "parent_id": "2310-12345#h1"},
        {"arxiv_id": "2310.12345", "version": 2, "element_id": "2310-12345#h2", "parent_id": "2310-12345#root2"},
        {"arxiv_id": "2310.12345", "version": 2, "element_id": "2310-12345#s1", "parent_id": "2310-12345#h2"},
    ]
    hierarchy_table = create_table_from_records(hierarchy_records, HIERARCHY_SCHEMA)
    report = validate_hierarchy_table(hierarchy_table, elements_table=elements_table)
    assert report.is_valid, f"Validation thất bại: {report.errors}"
    assert report.stats["unique_trees"] == 2
    assert report.stats["total_edges"] == 4

    # 2. Bắt lỗi cạnh tự trỏ chính mình
    bad_self_parent = [
        {"arxiv_id": "2310.12345", "version": 1, "element_id": "2310-12345#s1", "parent_id": "2310-12345#s1"}
    ]
    rep_self = validate_hierarchy_table(create_table_from_records(bad_self_parent, HIERARCHY_SCHEMA))
    assert not rep_self.is_valid
    assert any("tự trỏ" in err.lower() for err in rep_self.errors)

    # 3. Bắt lỗi một nút con có nhiều cha trong cùng 1 version
    bad_multi_parents = [
        {"arxiv_id": "2310.12345", "version": 1, "element_id": "2310-12345#h1", "parent_id": "2310-12345#root1"},
        {"arxiv_id": "2310.12345", "version": 1, "element_id": "2310-12345#s1", "parent_id": "2310-12345#h1"},
        {"arxiv_id": "2310.12345", "version": 1, "element_id": "2310-12345#s1", "parent_id": "2310-12345#root1"},
    ]
    rep_multi = validate_hierarchy_table(create_table_from_records(bad_multi_parents, HIERARCHY_SCHEMA))
    assert not rep_multi.is_valid
    assert any("nhiều cha khác nhau" in err.lower() for err in rep_multi.errors)

    # 4. Bắt lỗi có nhiều hơn 1 Document Root trong cùng 1 version
    bad_multi_roots = [
        {"arxiv_id": "2310.12345", "version": 1, "element_id": "2310-12345#h1", "parent_id": "2310-12345#root1"},
        {"arxiv_id": "2310.12345", "version": 1, "element_id": "2310-12345#h2", "parent_id": "2310-12345#root2"},
    ]
    rep_roots = validate_hierarchy_table(create_table_from_records(bad_multi_roots, HIERARCHY_SCHEMA))
    assert not rep_roots.is_valid
    assert any("nút root" in err.lower() for err in rep_roots.errors)

    # 5. Bắt lỗi chu trình (cycle detection)
    bad_cycle = [
        {"arxiv_id": "2310.12345", "version": 1, "element_id": "node_a", "parent_id": "node_b"},
        {"arxiv_id": "2310.12345", "version": 1, "element_id": "node_b", "parent_id": "node_c"},
        {"arxiv_id": "2310.12345", "version": 1, "element_id": "node_c", "parent_id": "node_a"},
    ]
    rep_cycle = validate_hierarchy_table(create_table_from_records(bad_cycle, HIERARCHY_SCHEMA))
    assert not rep_cycle.is_valid
    assert any("chu trình" in err.lower() or "root" in err.lower() for err in rep_cycle.errors)

    # 6. Bắt lỗi khóa ngoại sang elements_table (nút không có trong elements)
    bad_fk = [
        {"arxiv_id": "2310.12345", "version": 1, "element_id": "ghost_node", "parent_id": "2310-12345#root1"}
    ]
    rep_fk = validate_hierarchy_table(
        create_table_from_records(bad_fk, HIERARCHY_SCHEMA),
        elements_table=elements_table
    )
    assert not rep_fk.is_valid
    assert any("khóa ngoại" in err.lower() or "không tồn tại trong 'elements'" in err.lower() for err in rep_fk.errors)


def test_bibtex_validation():
    """Kiểm tra validate_bibtex_table: schema, primary key uniqueness, year bounds, entry types."""
    # 1. Bảng hợp lệ
    bib_records = [
        {
            "arxiv_id": "2310.12345",
            "citation_key": "vaswani2017",
            "entry_type": "article",
            "title": "Attention Is All You Need",
            "authors": ["Ashish Vaswani", "Noam Shazeer"],
            "year": 2017,
            "doi": "10.1000/182",
            "journal": "NeurIPS",
            "url": "https://arxiv.org/abs/1706.03762",
        },
        {
            "arxiv_id": "2310.12345",
            "citation_key": "devlin2018bert",
            "entry_type": "inproceedings",
            "title": "BERT: Pre-training of Deep Bidirectional Transformers",
            "authors": ["Jacob Devlin"],
            "year": 2018,
            "doi": None,
            "journal": "NAACL",
            "url": None,
        },
    ]
    table = create_table_from_records(bib_records, BIBTEX_SCHEMA)
    report = validate_bibtex_table(table)
    assert report.is_valid, f"Validation thất bại: {report.errors}"
    assert report.stats["unique_entries"] == 2
    assert report.stats["entries_with_year"] == 2

    # Roundtrip Parquet
    with tempfile.TemporaryDirectory() as tmp_dir:
        write_sharded_parquet(table, tmp_dir, "bibtex")
        loaded = read_sharded_parquet(Path(tmp_dir) / "bibtex", BIBTEX_SCHEMA)
        assert loaded.num_rows == 2

    # 2. Bắt lỗi trùng khóa citation_key trong cùng bài báo
    dup_records = list(bib_records) + [
        {
            "arxiv_id": "2310.12345",
            "citation_key": "vaswani2017",  # Trùng lặp
            "entry_type": "article",
            "title": "Attention Is All You Need (Dup)",
            "authors": ["A. Vaswani"],
            "year": 2017,
            "doi": None,
            "journal": None,
            "url": None,
        }
    ]
    rep_dup = validate_bibtex_table(create_table_from_records(dup_records, BIBTEX_SCHEMA))
    assert not rep_dup.is_valid
    assert any("trùng lặp" in err.lower() for err in rep_dup.errors)

    # 3. Bắt lỗi năm không hợp lệ
    bad_year_records = [
        {
            "arxiv_id": "2310.12345",
            "citation_key": "ancient_cite",
            "entry_type": "book",
            "title": "Old Book",
            "authors": ["Author"],
            "year": 1200,  # Năm quá cũ (< 1800)
            "doi": None,
            "journal": None,
            "url": None,
        }
    ]
    rep_year = validate_bibtex_table(create_table_from_records(bad_year_records, BIBTEX_SCHEMA))
    assert not rep_year.is_valid
    assert any("year" in err.lower() for err in rep_year.errors)

    # 4. Bắt lỗi tiêu đề rỗng
    empty_title_records = [
        {
            "arxiv_id": "2310.12345",
            "citation_key": "no_title",
            "entry_type": "misc",
            "title": "",  # Lỗi tiêu đề rỗng
            "authors": ["Author"],
            "year": 2020,
            "doi": None,
            "journal": None,
            "url": None,
        }
    ]
    rep_title = validate_bibtex_table(create_table_from_records(empty_title_records, BIBTEX_SCHEMA))
    assert not rep_title.is_valid
    assert any("title" in err.lower() for err in rep_title.errors)







