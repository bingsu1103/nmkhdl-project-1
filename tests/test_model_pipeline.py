"""
Test suite cho Feature Engineering và Model Ranking (src/features.py và src/model.py).
Thuộc sở hữu của Member 4 - Data Quality, Matching Model và Evaluation.
"""

import pytest

from src.evaluate import compute_mrr_at_k
from src.features import (
    FEATURE_NAMES,
    clean_tokens,
    extract_author_tokens,
    extract_feature_vector,
    extract_pair_features,
    extract_year,
    normalize_doi,
)
from src.model import (
    HeuristicRanker,
    LearnedRanker,
    build_pairwise_dataset,
    generate_mock_matching_dataset,
    predict_top_k_candidates,
)
from src.storage import (
    BIBTEX_SCHEMA,
    PAPERS_SCHEMA,
    PREDICTIONS_SCHEMA,
    REFERENCES_SCHEMA,
    create_table_from_records,
)
from src.validate import validate_predictions_table


# ==============================================================================
# 1. TEST FEATURE ENGINEERING (src/features.py)
# ==============================================================================

def test_feature_preprocessing_helpers():
    """Kiểm tra các hàm tiền xử lý text, tác giả, năm và DOI."""
    # 1. clean_tokens
    tokens = clean_tokens("Attention Is All You Need: A Deep Learning Study!")
    assert "attention" in tokens
    assert "deep" in tokens
    assert "learning" in tokens
    assert "the" not in tokens
    assert "is" not in tokens  # Stopword

    # 2. extract_author_tokens với nhiều định dạng
    # Format "Last, First"
    first, all_a = extract_author_tokens("Vaswani, Ashish and Shazeer, Noam")
    assert first == "vaswani"
    assert all_a == {"vaswani", "shazeer"}

    # Format list dicts (Semantic Scholar)
    first_dict, all_dict = extract_author_tokens([{"name": "Ashish Vaswani"}, {"name": "Noam Shazeer"}])
    assert first_dict == "vaswani"
    assert all_dict == {"vaswani", "shazeer"}

    # Format list strings
    first_str, all_str = extract_author_tokens(["Ashish Vaswani", "Noam Shazeer"])
    assert first_str == "vaswani"
    assert all_str == {"vaswani", "shazeer"}

    # 3. extract_year
    assert extract_year(2017) == 2017
    assert extract_year("2017") == 2017
    assert extract_year("Published in 2021.") == 2021
    assert extract_year("invalid") is None
    assert extract_year(1750) is None  # Ngoài khoảng 1800-2050

    # 4. normalize_doi
    assert normalize_doi("https://doi.org/10.1145/12345") == "10.1145/12345"
    assert normalize_doi("doi:10.1145/12345") == "10.1145/12345"
    assert normalize_doi(None) == ""


def test_extract_pair_features():
    """Kiểm tra trích xuất đặc trưng số học cho 1 cặp (BibTeX, Candidate)."""
    bib_entry = {
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer"],
        "year": 2017,
        "doi": "10.1000/182",
        "journal": "NeurIPS",
        "eprint": "1706.03762",
    }

    # Case 1: Candidate khớp hoàn toàn
    perfect_cand = {
        "ref_arxiv_id": "1706.03762",
        "ref_title": "Attention is all you need",
        "ref_authors": [{"name": "Ashish Vaswani"}, {"name": "Noam Shazeer"}],
        "ref_year": 2017,
        "doi": "https://doi.org/10.1000/182",
        "venue": "NeurIPS",
    }
    feats = extract_pair_features(bib_entry, perfect_cand)
    assert feats["title_token_jaccard"] == 1.0
    assert feats["first_author_match"] == 1.0
    assert feats["author_set_overlap"] == 1.0
    assert feats["year_diff"] == 0.0
    assert feats["year_exact_match"] == 1.0
    assert feats["year_proximity"] == 1.0
    assert feats["doi_match"] == 1.0
    assert feats["arxiv_id_match"] == 1.0

    # Case 2: Candidate khác biệt hoàn toàn
    unrelated_cand = {
        "ref_arxiv_id": "2103.99999",
        "ref_title": "Quantum Gravity and Black Holes",
        "ref_authors": ["Stephen Hawking"],
        "ref_year": 1988,
        "doi": "10.2000/999",
        "venue": "Nature",
    }
    unrelated_feats = extract_pair_features(bib_entry, unrelated_cand)
    assert unrelated_feats["title_token_jaccard"] == 0.0
    assert unrelated_feats["first_author_match"] == 0.0
    assert unrelated_feats["year_exact_match"] == 0.0
    assert unrelated_feats["doi_match"] == 0.0
    assert unrelated_feats["arxiv_id_match"] == 0.0

    # Vector length khớp danh sách FEATURE_NAMES
    vec = extract_feature_vector(bib_entry, perfect_cand)
    assert len(vec) == len(FEATURE_NAMES)


# ==============================================================================
# 2. TEST HEURISTIC RANKER (src/model.py)
# ==============================================================================

def test_heuristic_ranker():
    """Kiểm tra HeuristicRanker chấm điểm và xếp hạng candidates."""
    ranker = HeuristicRanker()

    bib_entry = {
        "title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        "authors": ["Jacob Devlin", "Ming-Wei Chang"],
        "year": 2018,
    }

    candidates = [
        # Candidate 1: Khớp tiêu đề và tác giả
        {
            "ref_arxiv_id": "1810.04805",
            "ref_title": "BERT: Pre-training of Deep Bidirectional Transformers",
            "ref_authors": ["Jacob Devlin"],
            "ref_year": 2018,
        },
        # Candidate 2: Không liên quan
        {
            "ref_arxiv_id": "1706.03762",
            "ref_title": "Attention Is All You Need",
            "ref_authors": ["Ashish Vaswani"],
            "ref_year": 2017,
        },
    ]

    ranked = ranker.rank_candidates(bib_entry, candidates)
    assert len(ranked) == 2
    # Candidate 1 phải đứng đầu
    assert ranked[0][0] == "1810.04805"
    assert ranked[0][1] > ranked[1][1]


# ==============================================================================
# 3. TEST LEARNED RANKER VỚI LOGISTIC REGRESSION (src/model.py)
# ==============================================================================

def test_learned_ranker_training_and_ranking():
    """Kiểm tra huấn luyện LearnedRanker và dự đoán xác suất."""
    # Sinh dữ liệu huấn luyện nhỏ có 2 class 0 và 1
    X = [
        [1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0],  # Match tốt -> 1
        [0.9, 0.8, 0.9, 1.0, 0.8, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0],  # Match tốt -> 1
        [0.0, 0.0, 0.1, 0.0, 0.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # Không match -> 0
        [0.1, 0.1, 0.2, 0.0, 0.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # Không match -> 0
    ]
    y = [1, 1, 0, 0]

    model = LearnedRanker(model_type="logistic", random_state=42)
    model.fit(X, y)
    assert model.is_fitted is True

    bib_entry = {
        "title": "Deep Residual Learning for Image Recognition",
        "authors": ["Kaiming He"],
        "year": 2015,
    }
    cands = [
        {
            "ref_arxiv_id": "1512.03385",
            "ref_title": "Deep Residual Learning for Image Recognition",
            "ref_authors": ["Kaiming He"],
            "ref_year": 2015,
        },
        {
            "ref_arxiv_id": "1409.1556",
            "ref_title": "Very Deep Convolutional Networks for Large-Scale Image Recognition",
            "ref_authors": ["Karen Simonyan"],
            "ref_year": 2014,
        },
    ]

    ranked = model.rank_candidates(bib_entry, cands)
    assert len(ranked) == 2
    assert ranked[0][0] == "1512.03385"
    assert ranked[0][1] >= ranked[1][1]


# ==============================================================================
# 4. TEST PREDICT TOP-K VÀ CHUẨN SCHEMA PREDICTIONS
# ==============================================================================

def test_predict_top_k_candidates_and_schema_validation():
    """Kiểm tra hàm predict_top_k_candidates sinh bảng predictions vượt qua Quality Gate."""
    mock_data = generate_mock_matching_dataset(num_pubs=3, refs_per_pub=8, entries_per_pub=5, seed=123)

    ranker = HeuristicRanker()
    predictions = predict_top_k_candidates(
        bib_entries=mock_data["bibtex"],
        candidates=mock_data["references"],
        model=ranker,
        default_partition="test",
        k=5,
    )

    assert len(predictions) == len(mock_data["bibtex"])

    # Tạo bảng PyArrow để validate schema
    papers_table = create_table_from_records(mock_data["papers"], PAPERS_SCHEMA)
    refs_table = create_table_from_records(mock_data["references"], REFERENCES_SCHEMA)
    bib_table = create_table_from_records(mock_data["bibtex"], BIBTEX_SCHEMA)
    pred_table = create_table_from_records(predictions, PREDICTIONS_SCHEMA)

    report = validate_predictions_table(
        pred_table,
        bibtex_table=bib_table,
        references_table=refs_table,
        papers_table=papers_table,
    )
    assert report.is_valid is True, f"Lỗi validation bảng predictions: {report.errors}"

    # Kiểm tra tính metric MRR@5 trên các dự đoán
    mrr_res = compute_mrr_at_k(predictions, k=5, partition_filter="test")
    assert mrr_res["total_queries"] > 0
    assert mrr_res["mrr"] >= 0.50  # Heuristic ranker trên mock dataset phải đạt MRR cao


# ==============================================================================
# 5. TEST END-TO-END PIPELINE: DATASET -> TRAINING -> VALIDATION MRR
# ==============================================================================

def test_end_to_end_pipeline_with_mock_dataset():
    """
    Kiểm thử quy trình hoàn chỉnh:
    Sinh Mock Dataset -> Tách Train/Valid -> Fit LearnedRanker -> So sánh MRR@5 giữa Baseline và Learned Model.
    """
    dataset = generate_mock_matching_dataset(num_pubs=10, refs_per_pub=10, entries_per_pub=10, seed=42)

    # Chia train/valid: 6 pubs train, 4 pubs valid
    train_pubs = {f"2301.{i:05d}" for i in range(1, 7)}
    valid_pubs = {f"2301.{i:05d}" for i in range(7, 11)}

    train_entries = [e for e in dataset["bibtex"] if e["arxiv_id"] in train_pubs]
    valid_entries = [e for e in dataset["bibtex"] if e["arxiv_id"] in valid_pubs]

    # 1. Trích xuất dataset huấn luyện
    X_train, y_train, _ = build_pairwise_dataset(train_entries, dataset["references"])
    assert len(X_train) > 0
    assert 1 in y_train and 0 in y_train

    # 2. Huấn luyện LearnedRanker
    ml_ranker = LearnedRanker(model_type="logistic", random_state=42)
    ml_ranker.fit(X_train, y_train)

    # 3. Đánh giá Baseline Heuristic trên tập Validation
    heuristic_model = HeuristicRanker()
    heuristic_preds = predict_top_k_candidates(
        bib_entries=valid_entries,
        candidates=dataset["references"],
        model=heuristic_model,
        default_partition="valid",
    )
    heuristic_mrr = compute_mrr_at_k(heuristic_preds, k=5, partition_filter="valid")

    # 4. Đánh giá Learned Model trên tập Validation
    ml_preds = predict_top_k_candidates(
        bib_entries=valid_entries,
        candidates=dataset["references"],
        model=ml_ranker,
        default_partition="valid",
    )
    ml_mrr = compute_mrr_at_k(ml_preds, k=5, partition_filter="valid")

    # Cả 2 mô hình đều phải có MRR > 0 và chạy thành công không crash
    assert heuristic_mrr["mrr"] > 0.0
    assert ml_mrr["mrr"] > 0.0
    assert heuristic_mrr["total_queries"] == len(valid_entries)
    assert ml_mrr["total_queries"] == len(valid_entries)


def test_predict_top_k_candidates_filters_matching_pools():
    """Kiểm tra chỉ bài báo nằm trong split_manifest mới xuất hiện trong bảng predictions."""
    bib_entries = [
        {"arxiv_id": "2301.00001", "citation_key": "k1", "title": "Paper 1"},
        {"arxiv_id": "2301.00002", "citation_key": "k2", "title": "Paper 2"},
        {"arxiv_id": "2301.00003", "citation_key": "k3", "title": "Paper 3 (Outside Pool)"},
    ]
    candidates = [
        {"arxiv_id": "2301.00001", "ref_arxiv_id": "1701.00001", "ref_title": "Ref 1"},
        {"arxiv_id": "2301.00002", "ref_arxiv_id": "1701.00002", "ref_title": "Ref 2"},
        {"arxiv_id": "2301.00003", "ref_arxiv_id": "1701.00003", "ref_title": "Ref 3"},
    ]
    manifest = {
        "2301.00001": "train",
        "2301.00002": "test",
        # 2301.00003 không có trong manifest (ngoài pool)
    }

    preds = predict_top_k_candidates(
        bib_entries=bib_entries,
        candidates=candidates,
        model=HeuristicRanker(),
        split_manifest=manifest,
    )

    pred_aids = {p["arxiv_id"] for p in preds}
    assert "2301.00001" in pred_aids
    assert "2301.00002" in pred_aids
    assert "2301.00003" not in pred_aids
    assert len(preds) == 2


def test_none_external_ids_handling():
    """Kiểm tra xử lý an toàn khi candidate có trường externalIds = None (tránh AttributeError)."""
    bib_entry = {
        "title": "Deep Learning Study",
        "authors": ["Bengio"],
        "year": 2020,
        "doi": "10.1000/123",
    }
    candidate_none_ext = {
        "ref_arxiv_id": "2001.00001",
        "ref_title": "Deep Learning Study",
        "ref_authors": ["Bengio"],
        "ref_year": 2020,
        "externalIds": None,  # Khóa tồn tại nhưng giá trị là None
    }
    # 1. extract_pair_features không ném lỗi
    feats = extract_pair_features(bib_entry, candidate_none_ext)
    assert feats["title_token_jaccard"] == 1.0

    # 2. HeuristicRanker không ném lỗi
    ranker = HeuristicRanker()
    ranked = ranker.rank_candidates(bib_entry, [candidate_none_ext])
    assert len(ranked) == 1
    assert ranked[0][0] == "2001.00001"


def test_downsampling_unmatched_entries():
    """Kiểm tra downsampling mẫu âm khi entry không có match (groundtruth_arxiv_id = None)."""
    bib_entries = [
        {
            "arxiv_id": "2301.00001",
            "citation_key": "unmatched_key",
            "title": "A Book with No arXiv Reference",
            "authors": ["Unknown"],
            "year": 2000,
            "groundtruth_arxiv_id": None,  # Không có match (15% theo đề bài)
        }
    ]
    # Tạo 20 candidates trong cùng publication
    candidates = [
        {
            "arxiv_id": "2301.00001",
            "ref_arxiv_id": f"1701.{i:05d}",
            "ref_title": f"Candidate Title {i}",
            "ref_authors": ["Author"],
            "ref_year": 2017,
        }
        for i in range(1, 21)
    ]

    # Yêu cầu downsample với ratio = 3 (thay vì đẩy toàn bộ 20 candidates âm vào)
    X, y, meta = build_pairwise_dataset(bib_entries, candidates, negative_sample_ratio=3, seed=42)
    assert len(X) == 3
    assert len(y) == 3
    assert all(label == 0 for label in y)


def test_create_table_numeric_string_coercion():
    """Kiểm tra create_table_from_records tự động ép kiểu chuỗi nếu dữ liệu chứa số (tránh ArrowInvalid)."""
    records = [
        {
            "arxiv_id": "2301.00001",
            "citation_key": "vaswani2017",
            "entry_type": "article",
            "title": 2026,  # Số nguyên thay vì chuỗi
            "authors": ["Author 1"],
            "year": 2026,
            "doi": None,
            "journal": 12345,  # Số nguyên thay vì chuỗi
            "url": None,
        }
    ]
    table = create_table_from_records(records, BIBTEX_SCHEMA)
    assert table.num_rows == 1
    assert table.column("title")[0].as_py() == "2026"
    assert table.column("journal")[0].as_py() == "12345"


def test_create_table_float_int_coercion():
    """Kiểm tra ép kiểu float 2017.0 và NaN từ Pandas thành int32 hoặc None an toàn."""
    records = [
        {
            "arxiv_id": "2301.00001",
            "citation_key": "k1",
            "entry_type": "article",
            "title": "Title 1",
            "authors": ["Author"],
            "year": 2017.0,  # float64 từ pandas
            "doi": None,
            "journal": None,
            "url": None,
        },
        {
            "arxiv_id": "2301.00001",
            "citation_key": "k2",
            "entry_type": "article",
            "title": "Title 2",
            "authors": ["Author"],
            "year": float("nan"),  # NaN từ pandas
            "doi": None,
            "journal": None,
            "url": None,
        },
    ]
    table = create_table_from_records(records, BIBTEX_SCHEMA)
    assert table.num_rows == 2
    assert table.column("year")[0].as_py() == 2017
    assert table.column("year")[1].as_py() is None
