"""
Module model.py: Matching Models (Scoring, Ranking và Top-5 Prediction) cho Milestone 3.
Thuộc sở hữu của Member 4 - Data Quality, Matching Model và Evaluation.

Bao gồm:
1. HeuristicRanker: Baseline Rule-based ranker kết hợp trọng số diễn giải được.
2. LearnedRanker: Mô hình học máy phân lớp / xếp hạng (Pointwise Classifier via Scikit-Learn: Logistic Regression / Random Forest).
3. build_pairwise_dataset: Trích xuất tập dữ liệu huấn luyện (X, y, metadata) từ ground truth.
4. predict_top_k_candidates: Sinh dự đoán Top-5 candidates đúng cấu trúc PREDICTIONS_SCHEMA.
5. generate_mock_matching_dataset: Sinh dữ liệu giả lập chuẩn schema để thử nghiệm pipeline và tuning.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from src.features import (
    FEATURE_NAMES,
    extract_feature_vector,
    extract_pair_features,
)
from src.normalize import normalize_arxiv_id


# ==============================================================================
# 1. HEURISTIC WEIGHTED RANKER (BASELINE MODEL)
# ==============================================================================

DEFAULT_HEURISTIC_WEIGHTS: Dict[str, float] = {
    "title_token_jaccard": 3.0,
    "title_token_overlap": 2.0,
    "title_edit_ratio": 2.5,
    "first_author_match": 1.5,
    "author_set_overlap": 1.5,
    "year_proximity": 1.0,
    "doi_match": 10.0,
    "arxiv_id_match": 10.0,
    "venue_token_overlap": 0.5,
}


class HeuristicRanker:
    """
    Baseline Ranker dựa trên trọng số heuristic:
    Tính điểm tương đồng tổng hợp từ các đặc trưng văn bản, tác giả, năm và định danh.
    Không yêu cầu huấn luyện trước.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or DEFAULT_HEURISTIC_WEIGHTS.copy()

    def score_pair(self, bib_entry: Dict[str, Any], candidate_ref: Dict[str, Any]) -> float:
        """Tính điểm tương đồng số học giữa một entry và một candidate."""
        features = extract_pair_features(bib_entry, candidate_ref)

        # Nếu trùng khớp định danh tuyệt đối (DOI hoặc arXiv ID), trao điểm ưu tiên cực đại
        if features.get("arxiv_id_match", 0.0) == 1.0:
            return 100.0 + features.get("title_edit_ratio", 0.0)
        if features.get("doi_match", 0.0) == 1.0:
            return 90.0 + features.get("title_edit_ratio", 0.0)

        score = 0.0
        for feat_name, weight in self.weights.items():
            val = features.get(feat_name, 0.0)
            score += weight * val

        return float(score)

    def rank_candidates(
        self,
        bib_entry: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> List[Tuple[str, float]]:
        """
        Xếp hạng danh sách ứng viên theo điểm số giảm dần.
        Sử dụng tie-breaking tất định theo ref_arxiv_id khi điểm bằng nhau.
        """
        scored: List[Tuple[str, float]] = []
        for c in candidates:
            ext_ids = c.get("externalIds") if isinstance(c.get("externalIds"), dict) else {}
            c_aid = normalize_arxiv_id(c.get("ref_arxiv_id") or ext_ids.get("ArXiv"))
            if not c_aid:
                continue
            s = self.score_pair(bib_entry, c)
            scored.append((c_aid, s))

        # Sắp xếp giảm dần theo điểm, nếu bằng nhau thì tăng dần theo mã arXiv (deterministic tie-break)
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored


# ==============================================================================
# 2. LEARNED MACHINE LEARNING RANKER (POINTWISE CLASSIFIER)
# ==============================================================================

class LearnedRanker:
    """
    Mô hình học máy phân lớp / xếp hạng ứng viên (Pointwise Ranking via Binary Classification).
    Dự đoán xác suất P(match=1) cho mỗi cặp (BibTeX, Candidate) rồi xếp hạng.
    Hỗ trợ Logistic Regression hoặc Random Forest từ scikit-learn.
    """

    def __init__(
        self,
        model_type: str = "logistic",
        random_state: int = 42,
        class_weight: str = "balanced",
        **kwargs: Any,
    ):
        self.model_type = model_type.lower()
        self.random_state = random_state
        self.feature_names = FEATURE_NAMES.copy()
        self.is_fitted = False

        # Khởi tạo estimator tương ứng
        if self.model_type == "logistic":
            from sklearn.linear_model import LogisticRegression
            self.model = LogisticRegression(
                class_weight=class_weight,
                random_state=random_state,
                max_iter=kwargs.get("max_iter", 1000),
                C=kwargs.get("C", 1.0),
            )
        elif self.model_type == "random_forest":
            from sklearn.ensemble import RandomForestClassifier
            self.model = RandomForestClassifier(
                n_estimators=kwargs.get("n_estimators", 100),
                max_depth=kwargs.get("max_depth", 8),
                class_weight=class_weight,
                random_state=random_state,
            )
        else:
            raise ValueError(f"model_type không hợp lệ: {model_type}. Chọn 'logistic' hoặc 'random_forest'.")

    def fit(self, X: List[List[float]], y: List[int]) -> LearnedRanker:
        """Huấn luyện mô hình trên tập dữ liệu đặc trưng (X, y)."""
        if not X or not y:
            raise ValueError("Tập dữ liệu huấn luyện (X, y) không được rỗng!")
        self.model.fit(X, y)
        self.is_fitted = True
        return self

    def score_pair(self, bib_entry: Dict[str, Any], candidate_ref: Dict[str, Any]) -> float:
        """Dự đoán xác suất match P(match=1) cho 1 cặp."""
        if not self.is_fitted:
            raise RuntimeError("Mô hình chưa được fit! Hãy gọi fit(X, y) trước.")
        feat_vec = extract_feature_vector(bib_entry, candidate_ref)
        probs = self.model.predict_proba([feat_vec])
        # Xác suất nhãn positive (class 1)
        if probs.shape[1] > 1:
            return float(probs[0][1])
        return float(probs[0][0])

    def rank_candidates(
        self,
        bib_entry: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> List[Tuple[str, float]]:
        """
        Tính xác suất match cho toàn bộ ứng viên và xếp hạng giảm dần.
        Sử dụng tie-breaking tất định theo ref_arxiv_id khi xác suất bằng nhau.
        """
        if not candidates:
            return []

        c_aids: List[str] = []
        feat_matrix: List[List[float]] = []

        for c in candidates:
            ext_ids = c.get("externalIds") if isinstance(c.get("externalIds"), dict) else {}
            c_aid = normalize_arxiv_id(c.get("ref_arxiv_id") or ext_ids.get("ArXiv"))
            if not c_aid:
                continue
            c_aids.append(c_aid)
            feat_matrix.append(extract_feature_vector(bib_entry, c))

        if not feat_matrix:
            return []

        if not self.is_fitted:
            raise RuntimeError("Mô hình chưa được huấn luyện! Hãy gọi .fit() trước.")

        probs = self.model.predict_proba(feat_matrix)
        scores = [float(p[1]) if len(p) > 1 else float(p[0]) for p in probs]

        scored = list(zip(c_aids, scores))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored


# ==============================================================================
# 3. CHUẨN BỊ TẬP DỮ LIỆU HUẤN LUYỆN (PAIRWISE DATASET GENERATOR)
# ==============================================================================

def build_pairwise_dataset(
    bib_entries: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    negative_sample_ratio: Optional[int] = None,
    seed: int = 42,
) -> Tuple[List[List[float]], List[int], List[Dict[str, Any]]]:
    """
    Sinh tập dữ liệu đặc trưng (X, y, metadata) từ các nhãn ground truth:
    - Với mỗi entry trong cùng publication:
      - Cặp đúng (ground truth match): y = 1.
      - Các cặp còn lại: y = 0.
    - negative_sample_ratio: Tùy chọn downsample mẫu âm (ví dụ 10 mẫu âm / 1 mẫu dương) để cân bằng dữ liệu.
    """
    # Gom nhóm candidates theo publication arxiv_id
    cand_by_pub: Dict[str, List[Dict[str, Any]]] = {}
    for c in candidates:
        aid = normalize_arxiv_id(c.get("arxiv_id"))
        if aid:
            cand_by_pub.setdefault(aid, []).append(c)

    rng = random.Random(seed)
    X: List[List[float]] = []
    y: List[int] = []
    meta: List[Dict[str, Any]] = []

    for entry in bib_entries:
        pub_id = normalize_arxiv_id(entry.get("arxiv_id"))
        ckey = str(entry.get("citation_key", ""))
        gt_id = normalize_arxiv_id(entry.get("groundtruth_arxiv_id"))
        cands = cand_by_pub.get(pub_id, [])

        pos_pairs: List[Tuple[List[float], Dict[str, Any]]] = []
        neg_pairs: List[Tuple[List[float], Dict[str, Any]]] = []

        for c in cands:
            ext_ids = c.get("externalIds") if isinstance(c.get("externalIds"), dict) else {}
            c_aid = normalize_arxiv_id(c.get("ref_arxiv_id") or ext_ids.get("ArXiv"))
            if not c_aid:
                continue

            f_vec = extract_feature_vector(entry, c)
            pair_meta = {
                "arxiv_id": pub_id,
                "citation_key": ckey,
                "ref_arxiv_id": c_aid,
                "groundtruth_arxiv_id": gt_id,
            }

            if gt_id and c_aid == gt_id:
                pos_pairs.append((f_vec, pair_meta))
            else:
                neg_pairs.append((f_vec, pair_meta))

        # Lưu mẫu positive
        for f, m in pos_pairs:
            X.append(f)
            y.append(1)
            meta.append(m)

        # Lưu mẫu negative (downsample nếu được chỉ định)
        if negative_sample_ratio is not None and neg_pairs:
            max_negs = max(1, len(pos_pairs)) * negative_sample_ratio
            if len(neg_pairs) > max_negs:
                neg_pairs = rng.sample(neg_pairs, max_negs)

        for f, m in neg_pairs:
            X.append(f)
            y.append(0)
            meta.append(m)

    return X, y, meta


# ==============================================================================
# 4. HÀM DỰ ĐOÁN TOP-K CANDIDATES CHO BẢNG PREDICTIONS
# ==============================================================================

def predict_top_k_candidates(
    bib_entries: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    model: Union[HeuristicRanker, LearnedRanker],
    default_partition: str = "test",
    split_manifest: Optional[Dict[str, str]] = None,
    k: int = 5,
) -> List[Dict[str, Any]]:
    """
    Sinh danh sách kết quả dự đoán top-k ứng viên cho từng BibTeX entry.
    Đầu ra tuân thủ chính xác 100% PREDICTIONS_SCHEMA:
    - arxiv_id, partition, citation_key, groundtruth_arxiv_id, cand_1..cand_5.
    - Đảm bảo candidate deduplication: cand_1..cand_5 là các ref_arxiv_id phân biệt.
    - Đảm bảo padding None nếu số ứng viên < k.
    - Đảm bảo không leak candidate khác publication.
    """
    cand_by_pub: Dict[str, List[Dict[str, Any]]] = {}
    for c in candidates:
        aid = normalize_arxiv_id(c.get("arxiv_id"))
        if aid:
            cand_by_pub.setdefault(aid, []).append(c)

    predictions: List[Dict[str, Any]] = []

    for entry in bib_entries:
        pub_id = normalize_arxiv_id(entry.get("arxiv_id"))
        if not pub_id:
            continue

        # Nếu có split_manifest: chỉ tạo prediction cho bài nằm trong matching pools (train/valid/test)
        if split_manifest is not None:
            if pub_id not in split_manifest:
                continue
            part = split_manifest[pub_id]
        else:
            part = default_partition

        ckey = str(entry.get("citation_key", ""))
        gt_id = normalize_arxiv_id(entry.get("groundtruth_arxiv_id")) or None

        cands = cand_by_pub.get(pub_id, [])

        # Xếp hạng các candidates trong publication
        if cands:
            ranked = model.rank_candidates(entry, cands)
            # Khử trùng lặp mã arXiv trong top candidates giữ nguyên thứ tự điểm
            seen_ids: Set[str] = set()
            unique_top: List[str] = []
            for c_id, _ in ranked:
                if c_id not in seen_ids:
                    seen_ids.add(c_id)
                    unique_top.append(c_id)
                if len(unique_top) == k:
                    break
        else:
            unique_top = []

        # Padding None cho đủ k ứng viên
        row: Dict[str, Any] = {
            "arxiv_id": pub_id,
            "partition": part,
            "citation_key": ckey,
            "groundtruth_arxiv_id": gt_id,
        }
        for rank_idx in range(1, k + 1):
            cand_key = f"cand_{rank_idx}"
            row[cand_key] = unique_top[rank_idx - 1] if rank_idx <= len(unique_top) else None

        predictions.append(row)

    return predictions


# ==============================================================================
# 5. GENERATOR DỮ LIỆU GIẢ LẬP ĐỂ TEST VÀ TÌM THAM SỐ (MOCK MATCHING DATA)
# ==============================================================================

def generate_mock_matching_dataset(
    num_pubs: int = 15,
    refs_per_pub: int = 15,
    entries_per_pub: int = 15,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Sinh bộ dữ liệu giả lập có cấu trúc thực tế và tỷ lệ nhiễu chuẩn:
    - 60% Khớp chính xác (Title, Author, Year trùng khớp).
    - 25% Nhiễu thực tế (Typo tiêu đề, khác biệt viết tắt tác giả, lệch ±1 năm).
    - 15% No-match (Ground truth = None).
    Giúp Member 4 kiểm thử trọn vẹn pipeline training, grid search, và MRR@5.
    """
    rng = random.Random(seed)

    words_pool = ["Attention", "Neural", "Network", "Deep", "Learning", "Transformer",
                  "Graph", "Language", "Model", "Representation", "Optimization", "Reinforcement"]
    authors_pool = ["Vaswani", "Devlin", "Goodfellow", "Bengio", "LeCun", "Hinton",
                    "He", "Brown", "Silver", "Sutskever"]

    papers: List[Dict[str, Any]] = []
    references: List[Dict[str, Any]] = []
    bibtex: List[Dict[str, Any]] = []
    manual_pool: List[Dict[str, Any]] = []
    auto_pool: List[Dict[str, Any]] = []

    for p_idx in range(1, num_pubs + 1):
        pub_aid = f"2301.{p_idx:05d}"
        pub_title = f"Advances in {' '.join(rng.sample(words_pool, 3))}"
        pub_authors = [f"{rng.choice(authors_pool)}, {chr(65 + rng.randint(0, 25))}."]
        pub_year = rng.randint(2018, 2024)

        papers.append({
            "arxiv_id": pub_aid,
            "title": pub_title,
            "authors": pub_authors,
            "submission_date": f"{pub_year}-01-15T00:00:00Z",
            "revised_dates": [f"{pub_year}-02-15T00:00:00Z"],
            "venue": "NeurIPS",
        })

        # Sinh các candidate references cho publication này
        pub_cands: List[Dict[str, Any]] = []
        for r_idx in range(1, refs_per_pub + 1):
            ref_aid = f"17{r_idx:02d}.{rng.randint(1000, 9999):05d}"
            r_title = f"On the Foundations of {' '.join(rng.sample(words_pool, 3))}"
            author_name = f"{rng.choice(authors_pool)} {chr(65 + rng.randint(0, 25))}."
            r_authors = [author_name]
            r_year = rng.randint(2015, pub_year)
            r_doi = f"10.1000/{rng.randint(1000, 9999)}"

            ref_record = {
                "arxiv_id": pub_aid,
                "ref_arxiv_id": ref_aid,
                "ref_title": r_title,
                "ref_authors": r_authors,
                "ref_submission_date": f"{r_year}-05-01T00:00:00Z",
                "ref_s2_id": f"s2_{p_idx}_{r_idx}",
                "ref_year": r_year,
                "doi": r_doi,
                "venue": "NeurIPS",
            }
            references.append(ref_record)
            pub_cands.append(ref_record)

        # Sinh các BibTeX entries
        for e_idx in range(1, entries_per_pub + 1):
            ckey = f"ref_{p_idx}_{e_idx}"
            prob = rng.random()

            if prob < 0.60 and pub_cands:
                # 60% Exact match
                matched_cand = pub_cands[(e_idx - 1) % len(pub_cands)]
                gt_aid = matched_cand["ref_arxiv_id"]
                e_title = matched_cand["ref_title"]
                e_authors = matched_cand["ref_authors"]
                e_year = matched_cand["ref_year"]
                e_doi = matched_cand["doi"]
            elif prob < 0.85 and pub_cands:
                # 25% Fuzzy match có nhiễu
                matched_cand = pub_cands[(e_idx - 1) % len(pub_cands)]
                gt_aid = matched_cand["ref_arxiv_id"]
                # Thêm typo nhỏ hoặc viết hoa/thường
                e_title = matched_cand["ref_title"].lower() + " (extended study)"
                e_authors = [matched_cand["ref_authors"][0].split()[-1]]  # Chỉ giữ họ
                e_year = matched_cand["ref_year"] + rng.choice([-1, 0, 1])
                e_doi = None  # Thiếu DOI
            else:
                # 15% No match
                gt_aid = None
                e_title = f"Unrelated Study on {' '.join(rng.sample(words_pool, 2))}"
                e_authors = [f"{rng.choice(authors_pool)}, X."]
                e_year = rng.randint(2010, 2017)
                e_doi = None

            bibtex.append({
                "arxiv_id": pub_aid,
                "citation_key": ckey,
                "entry_type": "article",
                "title": e_title,
                "authors": e_authors,
                "year": e_year,
                "journal": "arXiv preprint",
                "doi": e_doi,
                "url": f"https://arxiv.org/abs/{gt_aid}" if gt_aid else None,
                "groundtruth_arxiv_id": gt_aid,
            })

        # Phân chia pool manual vs auto
        if p_idx <= 5:
            manual_pool.append({
                "arxiv_id": pub_aid,
                "labeled_by": "member_4",
                "entries_count": entries_per_pub,
            })
        else:
            auto_pool.append({
                "arxiv_id": pub_aid,
                "labeled_by": "auto_heuristic",
                "entries_count": entries_per_pub,
            })

    return {
        "papers": papers,
        "references": references,
        "bibtex": bibtex,
        "manual_pool": manual_pool,
        "auto_pool": auto_pool,
    }
