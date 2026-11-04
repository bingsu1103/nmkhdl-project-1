"""
Test suite cho Milestone 3: Reference Matching Pipeline (evaluate.py, label.py, validate_predictions_table).
Thuộc sở hữu của Member 4 - Data Quality, Schema và ML Owner.
"""

import tempfile
from pathlib import Path

import pyarrow as pa
import pytest

from src.evaluate import (
    compute_mrr_at_k,
    compute_reciprocal_rank_at_k,
    evaluate_predictions_summary,
)
from src.label import (
    create_publication_split,
    export_split_manifest,
    heuristic_match_entry,
    load_split_manifest,
    validate_labeling_quota,
)
from src.storage import (
    BIBTEX_SCHEMA,
    PREDICTIONS_SCHEMA,
    REFERENCES_SCHEMA,
    create_table_from_records,
)
from src.validate import validate_predictions_table

from src.features import extract_pair_features
from src.model import (
    HeuristicRanker,
    LearnedRanker,
    build_pairwise_dataset,
    predict_top_k_candidates,
    generate_mock_matching_dataset,
)


def test_reciprocal_rank_positions():
    """Kiểm tra tính điểm Reciprocal Rank @ 5 cho các vị trí từ 1 đến 5 và ngoài top 5."""
    candidates = ["2310.00001", "2310.00002", "2310.00003", "2310.00004", "2310.00005", "2310.00006"]

    # Rank 1 -> RR = 1.0
    rr1, pos1 = compute_reciprocal_rank_at_k("2310.00001", candidates, k=5)
    assert rr1 == 1.0 and pos1 == 1

    # Rank 2 -> RR = 0.5
    rr2, pos2 = compute_reciprocal_rank_at_k("2310.00002", candidates, k=5)
    assert rr2 == 0.5 and pos2 == 2

    # Rank 3 -> RR = 1/3 (giữ nguyên float precision thuần túy)
    rr3, pos3 = compute_reciprocal_rank_at_k("2310.00003", candidates, k=5)
    assert rr3 == (1.0 / 3) and pos3 == 3

    # Rank 4 -> RR = 0.25
    rr4, pos4 = compute_reciprocal_rank_at_k("2310.00004", candidates, k=5)
    assert rr4 == 0.25 and pos4 == 4

    # Rank 5 -> RR = 0.2
    rr5, pos5 = compute_reciprocal_rank_at_k("2310.00005", candidates, k=5)
    assert rr5 == 0.2 and pos5 == 5

    # Vị trí thứ 6 (ngoài top 5) -> Điểm 0 theo quy định đề bài
    rr6, pos6 = compute_reciprocal_rank_at_k("2310.00006", candidates, k=5)
    assert rr6 == 0.0 and pos6 is None

    # Không nằm trong ứng viên -> Điểm 0
    rr_none, pos_none = compute_reciprocal_rank_at_k("9999.99999", candidates, k=5)
    assert rr_none == 0.0 and pos_none is None

    # Ground truth là None (không có trên arXiv) -> Điểm 0
    rr_null, pos_null = compute_reciprocal_rank_at_k(None, candidates, k=5)
    assert rr_null == 0.0 and pos_null is None


def test_compute_mrr_at_k_calculation():
    """Kiểm tra tính MRR@5 trên tập hợp các dòng dự đoán."""
    sample_records = [
        # Query 1: Đúng ở Rank 1 (RR = 1.0)
        {
            "arxiv_id": "2310.12345",
            "partition": "test",
            "citation_key": "k1",
            "groundtruth_arxiv_id": "1706.03762",
            "cand_1": "1706.03762",
            "cand_2": "1810.04805",
        },
        # Query 2: Đúng ở Rank 2 (RR = 0.5)
        {
            "arxiv_id": "2310.12345",
            "partition": "test",
            "citation_key": "k2",
            "groundtruth_arxiv_id": "1810.04805",
            "cand_1": "1706.03762",
            "cand_2": "1810.04805",
        },
        # Query 3: Đúng ở Rank 4 (RR = 0.25)
        {
            "arxiv_id": "2310.12345",
            "partition": "test",
            "citation_key": "k3",
            "groundtruth_arxiv_id": "2005.14165",
            "cand_1": "1111.00001",
            "cand_2": "1111.00002",
            "cand_3": "1111.00003",
            "cand_4": "2005.14165",
        },
        # Query 4: Không tìm thấy trong top-5 (RR = 0.0)
        {
            "arxiv_id": "2310.12345",
            "partition": "test",
            "citation_key": "k4",
            "groundtruth_arxiv_id": "9999.00000",
            "cand_1": "1111.00001",
            "cand_2": "1111.00002",
        },
        # Dòng thuộc tập train (không được tính khi lọc partition='test')
        {
            "arxiv_id": "2310.12345",
            "partition": "train",
            "citation_key": "k5",
            "groundtruth_arxiv_id": "1706.03762",
            "cand_1": "1706.03762",
        },
    ]

    metrics = compute_mrr_at_k(sample_records, k=5, partition_filter="test")
    # MRR = (1.0 + 0.5 + 0.25 + 0.0) / 4 = 1.75 / 4 = 0.4375
    assert metrics["total_queries"] == 4
    assert metrics["mrr"] == 0.4375
    assert metrics["hits_at_k"] == 3
    assert metrics["hit_rate"] == 0.75
    assert metrics["rank_distribution"]["rank_1"] == 1
    assert metrics["rank_distribution"]["rank_2"] == 1
    assert metrics["rank_distribution"]["rank_4"] == 1
    assert metrics["unranked_count"] == 1


def test_validate_predictions_table():
    """Kiểm tra validator cho bảng predictions (Schema, Partition, Uniqueness, FK checks)."""
    bibtex_records = [
        {
            "arxiv_id": "2310.12345",
            "citation_key": "vaswani2017",
            "entry_type": "article",
            "title": "Attention",
            "authors": ["Vaswani"],
            "year": 2017,
            "doi": None,
            "journal": None,
            "url": None,
        }
    ]
    bibtex_table = create_table_from_records(bibtex_records, BIBTEX_SCHEMA)

    refs_records = [
        {
            "arxiv_id": "2310.12345",
            "ref_arxiv_id": "1706.03762",
            "ref_title": "Attention",
            "ref_authors": ["Vaswani"],
            "ref_submission_date": "2017-06-12",
            "ref_s2_id": "s2-1",
        },
        {
            "arxiv_id": "2310.12345",
            "ref_arxiv_id": "1810.04805",
            "ref_title": "BERT",
            "ref_authors": ["Devlin"],
            "ref_submission_date": "2018-10-11",
            "ref_s2_id": "s2-2",
        },
    ]
    refs_table = create_table_from_records(refs_records, REFERENCES_SCHEMA)

    # 1. Bảng predictions hợp lệ (hỗ trợ cand_1 có hậu tố version v2 tự động chuẩn hóa)
    valid_predictions = [
        {
            "arxiv_id": "2310.12345",
            "partition": "test",
            "citation_key": "vaswani2017",
            "groundtruth_arxiv_id": "1706.03762",
            "cand_1": "1706.03762v2",  # Có version suffix v2
            "cand_2": "1810.04805",
            "cand_3": None,
            "cand_4": None,
            "cand_5": None,
        }
    ]
    table_pred = create_table_from_records(valid_predictions, PREDICTIONS_SCHEMA)
    report = validate_predictions_table(table_pred, bibtex_table=bibtex_table, references_table=refs_table)
    assert report.is_valid, f"Validation lỗi: {report.errors}"
    assert report.stats["partition_counts"]["test"] == 1

    # 2. Bắt lỗi candidate trùng lặp trong top-5
    dup_cand_records = [
        {
            "arxiv_id": "2310.12345",
            "partition": "test",
            "citation_key": "vaswani2017",
            "groundtruth_arxiv_id": "1706.03762",
            "cand_1": "1706.03762",
            "cand_2": "1706.03762",  # Trùng lặp candidate
            "cand_3": None,
            "cand_4": None,
            "cand_5": None,
        }
    ]
    rep_dup_cand = validate_predictions_table(create_table_from_records(dup_cand_records, PREDICTIONS_SCHEMA))
    assert not rep_dup_cand.is_valid
    assert any("trùng lặp candidate" in err.lower() for err in rep_dup_cand.errors)

    # 3. Bắt lỗi partition không hợp lệ
    bad_part_records = [
        {
            "arxiv_id": "2310.12345",
            "partition": "development",  # Sai giá trị partition
            "citation_key": "vaswani2017",
            "groundtruth_arxiv_id": None,
            "cand_1": None,
            "cand_2": None,
            "cand_3": None,
            "cand_4": None,
            "cand_5": None,
        }
    ]
    rep_bad_part = validate_predictions_table(create_table_from_records(bad_part_records, PREDICTIONS_SCHEMA))
    assert not rep_bad_part.is_valid
    assert any("partition" in err.lower() for err in rep_bad_part.errors)

    # 4. Bắt lỗi candidate không tồn tại trong references_table của bài báo
    alien_cand_records = [
        {
            "arxiv_id": "2310.12345",
            "partition": "test",
            "citation_key": "vaswani2017",
            "groundtruth_arxiv_id": None,
            "cand_1": "9999.88888",  # Không có trong refs_table
            "cand_2": None,
            "cand_3": None,
            "cand_4": None,
            "cand_5": None,
        }
    ]
    rep_alien = validate_predictions_table(
        create_table_from_records(alien_cand_records, PREDICTIONS_SCHEMA),
        references_table=refs_table,
    )
    assert not rep_alien.is_valid
    assert any("không tồn tại trong bảng 'references'" in err.lower() for err in rep_alien.errors)


def test_create_publication_split_and_no_leakage():
    """Kiểm tra chia tập dữ liệu cấp bài báo: Đúng quota, không rò rỉ dữ liệu."""
    # Tạo 25 bài manual và 15 bài auto
    manual_pubs = [
        {"arxiv_id": f"2310.{i:05d}", "method": "manual", "labeled_by": f"member-{i%5 + 1}", "entries_count": 25}
        for i in range(1, 26)
    ]
    auto_pubs = [
        {"arxiv_id": f"2310.{i:05d}", "method": "automatic", "labeled_by": "matcher-v1", "entries_count": 22}
        for i in range(26, 41)
    ]

    split_info = create_publication_split(manual_pubs, auto_pubs, num_members=5, random_seed=123)

    test_pubs = [s for s in split_info if s.partition == "test"]
    valid_pubs = [s for s in split_info if s.partition == "valid"]
    train_pubs = [s for s in split_info if s.partition == "train"]

    # Test: 5 manual + 5 auto = 10 bài
    assert len(test_pubs) == 10
    assert sum(1 for s in test_pubs if s.method == "manual") == 5
    assert sum(1 for s in test_pubs if s.method == "automatic") == 5

    # Valid: 5 manual + 5 auto = 10 bài
    assert len(valid_pubs) == 10
    assert sum(1 for s in valid_pubs if s.method == "manual") == 5
    assert sum(1 for s in valid_pubs if s.method == "automatic") == 5

    # Train: 15 manual + 5 auto = 20 bài
    assert len(train_pubs) == 20
    assert sum(1 for s in train_pubs if s.method == "manual") == 15
    assert sum(1 for s in train_pubs if s.method == "automatic") == 5

    # Kiểm tra giao cắt rỗng giữa các tập (No Data Leakage)
    test_ids = {s.arxiv_id for s in test_pubs}
    valid_ids = {s.arxiv_id for s in valid_pubs}
    train_ids = {s.arxiv_id for s in train_pubs}

    assert len(test_ids.intersection(valid_ids)) == 0
    assert len(test_ids.intersection(train_ids)) == 0
    assert len(valid_ids.intersection(train_ids)) == 0

    # Kiểm tra export và load manifest
    with tempfile.TemporaryDirectory() as tmp_dir:
        manifest_file = Path(tmp_dir) / "split_manifest.json"
        export_split_manifest(split_info, manifest_file)
        assert manifest_file.exists()

        loaded_map = load_split_manifest(manifest_file)
        assert len(loaded_map) == 40
        for s in split_info:
            assert loaded_map[s.arxiv_id] == s.partition


def test_validate_labeling_quota():
    """Kiểm tra hàm validate_labeling_quota bắt lỗi thiếu quota bài báo, Q < 20 và math.ceil 10%."""
    # 1. Trường hợp thỏa mãn đầy đủ (25 bài manual, mỗi bài 25 entries, 15 bài auto)
    manual_good = [
        {"arxiv_id": f"2310.{i:05d}", "method": "manual", "labeled_by": f"member-{i%5 + 1}", "entries_count": 25}
        for i in range(1, 26)
    ]
    auto_good = [
        {"arxiv_id": f"2310.{i:05d}", "method": "automatic", "labeled_by": "auto", "entries_count": 20}
        for i in range(26, 41)
    ]
    res_good = validate_labeling_quota(manual_good + auto_good, total_assigned_publications_count=100, num_members=5)
    assert res_good["is_valid"] is True

    # 2. Trường hợp có bài thủ công ít hơn 20 entries (vi phạm Q >= 20)
    manual_bad_q = list(manual_good)
    manual_bad_q[0]["entries_count"] = 15  # Chỉ có 15 entries
    res_bad_q = validate_labeling_quota(manual_bad_q + auto_good, total_assigned_publications_count=100, num_members=5)
    assert res_bad_q["is_valid"] is False
    assert any("Q >= 20" in err for err in res_bad_q["errors"])

    # 3. Kiểm tra math.ceil bảo đảm tối thiểu 10% (ví dụ: ngoài manual còn 75 bài, 10% = 7.5 -> yêu cầu math.ceil là 8 bài)
    auto_only_7 = auto_good[:7]  # Chỉ có 7 bài (thiếu so với 8)
    res_ceil = validate_labeling_quota(manual_good + auto_only_7, total_assigned_publications_count=100, num_members=5)
    assert res_ceil["is_valid"] is False
    assert any("chưa đạt mức 10%" in err for err in res_ceil["errors"])


def test_heuristic_match_entry():
    """Kiểm tra automatic matcher baseline so khớp heuristic tiêu đề và tác giả (hỗ trợ cả tác giả dạng dict)."""
    # 1. Tác giả là list các string
    bib_entry = {
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer"],
        "year": 2017,
    }
    crawled_refs = [
        {
            "ref_arxiv_id": "1810.04805",
            "ref_title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
            "ref_authors": ["Jacob Devlin"],
            "ref_submission_date": "2018-10-11",
        },
        {
            "ref_arxiv_id": "1706.03762",
            "ref_title": "Attention Is All You Need",
            "ref_authors": ["Ashish Vaswani"],
            "ref_submission_date": "2017-06-12",
        },
    ]

    matched_id = heuristic_match_entry(bib_entry, crawled_refs)
    assert matched_id == "1706.03762"

    # 2. Tác giả là list các dictionary từ Semantic Scholar (chống crash AttributeError)
    crawled_refs_dict_authors = [
        {
            "ref_arxiv_id": "1706.03762",
            "ref_title": "Attention Is All You Need",
            "authors": [{"name": "Ashish Vaswani"}, {"name": "Noam Shazeer"}],
            "publicationDate": "2017-06-12",
        }
    ]
    bib_entry_dict_authors = {
        "title": "Attention Is All You Need",
        "authors": [{"name": "Ashish Vaswani"}],
        "year": 2017,
    }
    matched_dict_id = heuristic_match_entry(bib_entry_dict_authors, crawled_refs_dict_authors)
    assert matched_dict_id == "1706.03762"

    # 3. Trường hợp không có tài liệu nào khớp
    unrelated_bib = {
        "title": "A Completely Unrelated Paper About Quantum Gravity",
        "authors": ["Albert Einstein"],
        "year": 1950,
    }
    assert heuristic_match_entry(unrelated_bib, crawled_refs) is None



def test_features_and_rankers_end_to_end():
    """Kiểm tra trích xuất đặc trưng và xếp hạng bằng cả Heuristic và Learned Ranker."""
    data = generate_mock_matching_dataset(num_pubs=6, refs_per_pub=10, entries_per_pub=10, seed=42)
    bib_entries = data["bibtex"]
    cands = data["references"]

    # 1. Kiểm tra feature extraction không bị lỗi với ref_submission_date
    f_dict = extract_pair_features(bib_entries[0], cands[0])
    assert "title_token_jaccard" in f_dict
    assert isinstance(f_dict["year_diff"], float)

    # 2. Kiểm tra HeuristicRanker
    h_ranker = HeuristicRanker()
    preds_h = predict_top_k_candidates(bib_entries[:5], cands, model=h_ranker, k=5)
    assert len(preds_h) == 5
    assert all("cand_1" in p for p in preds_h)

    # 3. Kiểm tra huấn luyện và xếp hạng của LearnedRanker (Logistic Regression)
    X, y, meta = build_pairwise_dataset(bib_entries[:30], cands, negative_sample_ratio=5, seed=42)
    assert len(X) == len(y)
    assert 1 in y and 0 in y  # Có cả mẫu âm và dương

    ml_ranker = LearnedRanker(model_type="logistic", random_state=42)
    ml_ranker.fit(X, y)
    assert ml_ranker.is_fitted

    preds_ml = predict_top_k_candidates(bib_entries[30:40], cands, model=ml_ranker, k=5)
    assert len(preds_ml) == 10
    # Đảm bảo top 5 không bị trùng lặp candidate
    for p in preds_ml:
        c_list = [p[f"cand_{i}"] for i in range(1, 6) if p[f"cand_{i}"] is not None]
        assert len(c_list) == len(set(c_list))