"""
Module model.py: Matching Models (Scoring, Ranking và Top-5 Prediction) cho Milestone 3.
Thuộc sở hữu của Member 4 - Data Quality, Matching Model và Evaluation.

Bao gồm:
1. HeuristicRanker: Baseline Rule-based ranker kết hợp trọng số diễn giải được.
2. LearnedRanker: Mô hình học máy xếp hạng ứng viên via Scikit-Learn
   (Logistic Regression, Pairwise Logistic, Random Forest, HistGradientBoosting).
3. build_pairwise_dataset & build_preference_dataset: Trích xuất tập dữ liệu huấn luyện (có hard-negative mining).
4. predict_top_k_candidates: Sinh dự đoán Top-5 candidates đúng cấu trúc PREDICTIONS_SCHEMA.
5. generate_mock_matching_dataset: Sinh dữ liệu giả lập chuẩn schema để thử nghiệm pipeline và tuning.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from src.features import (
    FEATURE_NAMES,
    _prepare_bib_entry,
    _prepare_candidate_ref,
    _score_prepared_pair,
    _score_prepared_vector,
    extract_feature_vector,
    extract_pair_features,
)
from src.normalize import normalize_arxiv_id


# ==============================================================================
# 1. HEURISTIC WEIGHTED RANKER (BASELINE MODEL)
# ==============================================================================

DEFAULT_HEURISTIC_WEIGHTS: Dict[str, float] = {
    "title_token_jaccard": 2.5,
    "title_token_overlap": 1.5,
    "title_edit_ratio": 2.0,
    "title_token_set_ratio": 2.0,
    "first_author_match": 1.5,
    "author_set_overlap": 1.0,
    "author_bib_recall": 1.2,
    "year_proximity": 1.0,
    "doi_match": 10.0,
    "arxiv_id_match": 10.0,
    "citation_key_hint_match": 1.2,
    "venue_token_overlap": 0.5,
}


class HeuristicRanker:
    """
    Baseline Ranker dựa trên trọng số heuristic:
    Tính điểm tương đồng tổng hợp từ các đặc trưng văn bản, tác giả, năm và định danh.
    Không yêu cầu huấn luyện trước.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = DEFAULT_HEURISTIC_WEIGHTS.copy() if weights is None else dict(weights)

    def _score_features(self, features: Dict[str, float]) -> float:
        if features.get("arxiv_id_match", 0.0) == 1.0:
            return 100.0 + features.get("title_edit_ratio", 0.0)
        if features.get("doi_match", 0.0) == 1.0:
            return 90.0 + features.get("title_edit_ratio", 0.0)

        score = 0.0
        for feat_name, weight in self.weights.items():
            score += weight * features.get(feat_name, 0.0)
        return float(score)

    def score_pair(self, bib_entry: Dict[str, Any], candidate_ref: Dict[str, Any]) -> float:
        """Tính điểm tương đồng số học giữa một entry và một candidate."""
        return self._score_features(extract_pair_features(bib_entry, candidate_ref))

    def score_prepared_pair(self, prep_bib: Dict[str, Any], prep_cand: Dict[str, Any]) -> float:
        """Fast pair scoring using precomputed bib/candidate dictionaries."""
        return self._score_features(_score_prepared_pair(prep_bib, prep_cand))

    def rank_candidates(
        self,
        bib_entry: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> List[Tuple[str, float]]:
        """
        Xếp hạng danh sách ứng viên theo điểm số giảm dần.
        Sử dụng tie-breaking tất định theo ref_arxiv_id khi điểm bằng nhau.
        """
        prep_bib = _prepare_bib_entry(bib_entry)
        scored: List[Tuple[str, float]] = []
        for c in candidates:
            ext_ids = c.get("externalIds") if isinstance(c.get("externalIds"), dict) else {}
            c_aid = normalize_arxiv_id(c.get("ref_arxiv_id") or ext_ids.get("ArXiv"))
            if not c_aid:
                continue
            s = self.score_prepared_pair(prep_bib, _prepare_candidate_ref(c))
            scored.append((c_aid, s))

        # Sắp xếp giảm dần theo điểm, nếu bằng nhau thì tăng dần theo mã arXiv (deterministic tie-break)
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored


# ==============================================================================
# 2. LEARNED MACHINE LEARNING RANKER (POINTWISE CLASSIFIER)
# ==============================================================================

class LearnedRanker:
    """
    Mô hình học máy phân lớp / xếp hạng ứng viên (Pointwise & Pairwise Ranking via Scikit-Learn).
    Hỗ trợ:
    - 'logistic': StandardScaler + LogisticRegression (pointwise P(match=1)).
    - 'pairwise_logistic': StandardScaler(with_mean=False) + LogisticRegression(fit_intercept=False)
      huấn luyện trên vector hiệu (x_pos - x_neg) để tối ưu trực tiếp thứ tự xếp hạng trong từng bài báo.
    - 'random_forest': RandomForestClassifier.
    - 'hist_gb': HistGradientBoostingClassifier.
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
        if self.model_type in {"logistic", "pairwise_logistic"}:
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import Pipeline
            from sklearn.preprocessing import StandardScaler

            is_pairwise = self.model_type == "pairwise_logistic"
            self.model = Pipeline([
                ("scaler", StandardScaler(with_mean=not is_pairwise)),
                (
                    "clf",
                    LogisticRegression(
                        fit_intercept=not is_pairwise,
                        class_weight=None if is_pairwise else class_weight,
                        random_state=random_state,
                        max_iter=kwargs.get("max_iter", 1000),
                        C=kwargs.get("C", 1.0),
                    ),
                ),
            ])
        elif self.model_type == "random_forest":
            from sklearn.ensemble import RandomForestClassifier
            self.model = RandomForestClassifier(
                n_estimators=kwargs.get("n_estimators", 100),
                max_depth=kwargs.get("max_depth", 8),
                class_weight=class_weight,
                n_jobs=kwargs.get("n_jobs", -1),
                random_state=random_state,
            )
        elif self.model_type in {"hist_gb", "hist_gradient_boosting"}:
            from sklearn.ensemble import HistGradientBoostingClassifier
            self.model = HistGradientBoostingClassifier(
                max_iter=kwargs.get("max_iter", 150),
                max_depth=kwargs.get("max_depth", 6),
                learning_rate=kwargs.get("learning_rate", 0.08),
                class_weight=class_weight,
                random_state=random_state,
            )
        else:
            raise ValueError(
                f"model_type không hợp lệ: {model_type}. "
                "Chọn 'logistic', 'pairwise_logistic', 'random_forest' hoặc 'hist_gb'."
            )

    def get_final_estimator(self) -> Any:
        """Trả về estimator cuối cùng (tự động bóc Pipeline nếu có StandardScaler)."""
        from sklearn.pipeline import Pipeline

        if isinstance(self.model, Pipeline) and "clf" in self.model.named_steps:
            return self.model.named_steps["clf"]
        return self.model

    def fit(self, X: Any, y: Any, sample_weight: Optional[Any] = None) -> LearnedRanker:
        """Huấn luyện mô hình trên tập dữ liệu đặc trưng (X, y), hỗ trợ sample_weight."""
        if len(X) == 0 or len(y) == 0:
            raise ValueError("Tập dữ liệu huấn luyện (X, y) không được rỗng!")
        if len(X) != len(y):
            raise ValueError(f"Độ dài X ({len(X)}) và y ({len(y)}) không khớp!")
        if sample_weight is not None:
            if len(sample_weight) != len(y):
                raise ValueError(
                    f"Độ dài sample_weight ({len(sample_weight)}) và y ({len(y)}) không khớp!"
                )
            from sklearn.pipeline import Pipeline

            if isinstance(self.model, Pipeline) and "clf" in self.model.named_steps:
                self.model.fit(X, y, clf__sample_weight=sample_weight)
            else:
                self.model.fit(X, y, sample_weight=sample_weight)
        else:
            self.model.fit(X, y)
        self.is_fitted = True
        return self

    def _positive_probs(self, probs: Any) -> List[float]:
        classes = list(getattr(self.model, "classes_", []))
        if 1 not in classes:
            return [0.0] * len(probs)
        pos_idx = classes.index(1)
        return [float(row[pos_idx]) for row in probs]

    def score_pair(self, bib_entry: Dict[str, Any], candidate_ref: Dict[str, Any]) -> float:
        """Dự đoán xác suất match P(match=1) cho 1 cặp."""
        if not self.is_fitted:
            raise RuntimeError("Mô hình chưa được fit! Hãy gọi fit(X, y) trước.")
        feat_vec = extract_feature_vector(bib_entry, candidate_ref)
        probs = self.model.predict_proba([feat_vec])
        return self._positive_probs(probs)[0]

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
        if not self.is_fitted:
            raise RuntimeError("Mô hình chưa được huấn luyện! Hãy gọi .fit() trước.")

        prep_bib = _prepare_bib_entry(bib_entry)
        c_aids: List[str] = []
        feat_matrix: List[List[float]] = []

        for c in candidates:
            ext_ids = c.get("externalIds") if isinstance(c.get("externalIds"), dict) else {}
            c_aid = normalize_arxiv_id(c.get("ref_arxiv_id") or ext_ids.get("ArXiv"))
            if not c_aid:
                continue
            c_aids.append(c_aid)
            feat_matrix.append(_score_prepared_vector(prep_bib, _prepare_candidate_ref(c)))

        if not feat_matrix:
            return []

        probs = self.model.predict_proba(feat_matrix)
        scores = self._positive_probs(probs)

        scored = list(zip(c_aids, scores))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored


# ==============================================================================
# 3. CHUẨN BỊ TẬP DỮ LIỆU HUẤN LUYỆN (PAIRWISE DATASET GENERATOR)
# ==============================================================================

def _prepare_candidates_by_pub(
    candidates: List[Dict[str, Any]],
) -> Dict[str, List[Tuple[str, Dict[str, Any]]]]:
    cand_by_pub: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
    seen: Set[Tuple[str, str]] = set()
    for c in candidates:
        aid = normalize_arxiv_id(c.get("arxiv_id"))
        if not aid:
            continue
        ext_ids = c.get("externalIds") if isinstance(c.get("externalIds"), dict) else {}
        c_aid = normalize_arxiv_id(c.get("ref_arxiv_id") or ext_ids.get("ArXiv"))
        if not c_aid or (aid, c_aid) in seen:
            continue
        seen.add((aid, c_aid))
        cand_by_pub.setdefault(aid, []).append((c_aid, _prepare_candidate_ref(c)))
    return cand_by_pub


def _unique_top_k(scored: List[Tuple[str, float]], k: int) -> List[str]:
    scored.sort(key=lambda item: (-item[1], item[0]))
    seen_ids: Set[str] = set()
    unique_top: List[str] = []
    for c_id, _ in scored:
        if c_id not in seen_ids:
            seen_ids.add(c_id)
            unique_top.append(c_id)
            if len(unique_top) == k:
                break
    return unique_top


def _cheap_hard_negative_score(prep_bib: Dict[str, Any], prep_cand: Dict[str, Any]) -> float:
    """Chấm điểm sơ bộ cực nhanh O(|tokens|) để chọn hard negatives mà không cần gọi Levenshtein."""
    bt = prep_bib["tokens"]
    rt = prep_cand["tokens"]
    if bt and rt:
        inter = len(bt.intersection(rt))
        union = len(bt) + len(rt) - inter
        jacc = inter / union if union else 0.0
    else:
        jacc = 0.0
    first_match = (
        1.0
        if (
            prep_bib["first_author"]
            and prep_cand["first_author"]
            and prep_bib["first_author"] == prep_cand["first_author"]
        )
        else 0.0
    )
    ba = prep_bib["authors"]
    ra = prep_cand["authors"]
    a_recall = (len(ba.intersection(ra)) / len(ba)) if (ba and ra) else 0.0
    by = prep_bib["year"]
    ry = prep_cand["year"]
    y_match = 1.0 if (by is not None and ry is not None and abs(by - ry) <= 1) else 0.0
    return 3.0 * jacc + 1.5 * first_match + 1.0 * a_recall + 0.5 * y_match


def _select_negatives(
    prep_bib: Dict[str, Any],
    neg_candidates: List[Tuple[str, Dict[str, Any]]],
    max_negs: int,
    hard_negative_fraction: float,
    rng: random.Random,
) -> List[Tuple[str, Dict[str, Any]]]:
    if len(neg_candidates) <= max_negs:
        return neg_candidates
    if hard_negative_fraction <= 0.0:
        return rng.sample(neg_candidates, max_negs)
    frac = min(1.0, hard_negative_fraction)
    n_hard = min(len(neg_candidates), int(round(max_negs * frac)))
    ranked = sorted(
        neg_candidates,
        key=lambda item: (-_cheap_hard_negative_score(prep_bib, item[1]), item[0]),
    )
    hard_picked = ranked[:n_hard]
    remainder = ranked[n_hard:]
    n_rand = max_negs - len(hard_picked)
    if n_rand > 0 and remainder:
        rand_picked = rng.sample(remainder, min(n_rand, len(remainder)))
    else:
        rand_picked = []
    return hard_picked + rand_picked


def build_pairwise_dataset(
    bib_entries: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    negative_sample_ratio: Optional[int] = None,
    seed: int = 42,
    hard_negative_fraction: float = 0.0,
    skip_unlabeled: bool = True,
) -> Tuple[List[List[float]], List[int], List[Dict[str, Any]]]:
    """
    Sinh tập dữ liệu đặc trưng (X, y, metadata) từ các nhãn ground truth:
    - Bỏ qua các entry đánh dấu `is_labeled=False` (chưa gán nhãn, tránh bơm nhiễu false-negative).
    - Với mỗi entry trong cùng publication:
      - Cặp đúng (ground truth match): y = 1.
      - Các cặp còn lại: y = 0.
    - negative_sample_ratio: Downsample mẫu âm trước khi trích xuất vector đặc trưng.
    - hard_negative_fraction: Tỷ lệ mẫu âm khó (0.0..1.0) chọn bằng pre-score token/author.
    """
    cand_by_pub = _prepare_candidates_by_pub(candidates)

    rng = random.Random(seed)
    X: List[List[float]] = []
    y: List[int] = []
    meta: List[Dict[str, Any]] = []

    for entry in bib_entries:
        if skip_unlabeled and entry.get("is_labeled") is False:
            continue

        pub_id = normalize_arxiv_id(entry.get("arxiv_id"))
        ckey = str(entry.get("citation_key", ""))
        gt_id = normalize_arxiv_id(entry.get("groundtruth_arxiv_id"))
        label_method = str(entry.get("label_method") or "unknown")
        cands = cand_by_pub.get(pub_id, [])
        if not cands:
            continue

        prep_bib = _prepare_bib_entry(entry)
        pos_candidates: List[Tuple[str, Dict[str, Any]]] = []
        neg_candidates: List[Tuple[str, Dict[str, Any]]] = []

        for c_aid, prep_c in cands:
            if gt_id and c_aid == gt_id:
                pos_candidates.append((c_aid, prep_c))
            else:
                neg_candidates.append((c_aid, prep_c))

        # Chọn mẫu âm trước khi trích xuất đặc trưng đầy đủ (có thể kết hợp hard negatives)
        if negative_sample_ratio is not None and neg_candidates:
            max_negs = max(1, len(pos_candidates)) * negative_sample_ratio
            neg_candidates = _select_negatives(
                prep_bib, neg_candidates, max_negs, hard_negative_fraction, rng
            )

        for label, selected in ((1, pos_candidates), (0, neg_candidates)):
            for candidate_aid, prep_candidate in selected:
                X.append(_score_prepared_vector(prep_bib, prep_candidate))
                y.append(label)
                meta.append(
                    {
                        "arxiv_id": pub_id,
                        "citation_key": ckey,
                        "ref_arxiv_id": candidate_aid,
                        "groundtruth_arxiv_id": gt_id,
                        "label_method": label_method,
                    }
                )

    return X, y, meta


def build_preference_dataset(
    bib_entries: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    negative_sample_ratio: Optional[int] = 10,
    hard_negative_fraction: float = 0.5,
    seed: int = 42,
    manual_sample_weight: float = 5.0,
    skip_unlabeled: bool = True,
) -> Tuple[List[List[float]], List[int], List[float], List[Dict[str, Any]]]:
    """
    Sinh tập cặp đối xứng (x_pos - x_neg -> 1, x_neg - x_pos -> 0) phục vụ Pairwise Ranking
    (LearnedRanker với model_type='pairwise_logistic').
    Tối ưu trực tiếp thứ tự xếp hạng giữa ứng viên đúng và các ứng viên sai trong cùng bài báo.
    """
    cand_by_pub = _prepare_candidates_by_pub(candidates)
    rng = random.Random(seed)
    X_diff: List[List[float]] = []
    y_diff: List[int] = []
    weights: List[float] = []
    meta: List[Dict[str, Any]] = []

    for entry in bib_entries:
        if skip_unlabeled and entry.get("is_labeled") is False:
            continue

        pub_id = normalize_arxiv_id(entry.get("arxiv_id"))
        ckey = str(entry.get("citation_key", ""))
        gt_id = normalize_arxiv_id(entry.get("groundtruth_arxiv_id"))
        if not gt_id:
            continue
        cands = cand_by_pub.get(pub_id, [])
        if not cands:
            continue

        pos_pair: Optional[Tuple[str, Dict[str, Any]]] = None
        neg_candidates: List[Tuple[str, Dict[str, Any]]] = []
        for c_aid, prep_c in cands:
            if c_aid == gt_id:
                pos_pair = (c_aid, prep_c)
            else:
                neg_candidates.append((c_aid, prep_c))

        if pos_pair is None or not neg_candidates:
            continue

        prep_bib = _prepare_bib_entry(entry)
        if negative_sample_ratio is not None:
            neg_candidates = _select_negatives(
                prep_bib, neg_candidates, max(1, negative_sample_ratio), hard_negative_fraction, rng
            )

        v_pos = _score_prepared_vector(prep_bib, pos_pair[1])
        label_method = str(entry.get("label_method") or "unknown")
        w = float(manual_sample_weight) if label_method == "manual" else 1.0

        for neg_aid, prep_neg in neg_candidates:
            v_neg = _score_prepared_vector(prep_bib, prep_neg)
            X_diff.append([a - b for a, b in zip(v_pos, v_neg)])
            y_diff.append(1)
            weights.append(w)
            meta.append({
                "arxiv_id": pub_id,
                "citation_key": ckey,
                "pos_arxiv_id": pos_pair[0],
                "neg_arxiv_id": neg_aid,
                "label_method": label_method,
            })

            X_diff.append([b - a for a, b in zip(v_pos, v_neg)])
            y_diff.append(0)
            weights.append(w)
            meta.append({
                "arxiv_id": pub_id,
                "citation_key": ckey,
                "pos_arxiv_id": neg_aid,
                "neg_arxiv_id": pos_pair[0],
                "label_method": label_method,
            })

    return X_diff, y_diff, weights, meta


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
    batch_size: int = 32768,
) -> List[Dict[str, Any]]:
    """
    Sinh danh sách kết quả dự đoán top-k ứng viên cho từng BibTeX entry.
    Đầu ra tuân thủ chính xác 100% PREDICTIONS_SCHEMA:
    - arxiv_id, partition, citation_key, groundtruth_arxiv_id, cand_1..cand_5.
    - Đảm bảo candidate deduplication: cand_1..cand_5 là các ref_arxiv_id phân biệt.
    - Đảm bảo padding None nếu số ứng viên < k.
    - Đảm bảo không leak candidate khác publication.
    """
    is_learned = isinstance(model, LearnedRanker)
    is_heuristic = isinstance(model, HeuristicRanker)
    if is_learned and not model.is_fitted:
        raise RuntimeError("Mô hình chưa được huấn luyện! Hãy gọi .fit() trước.")

    cand_by_pub: Dict[str, List[Any]]
    if is_learned or is_heuristic:
        cand_by_pub = _prepare_candidates_by_pub(candidates)
    else:
        raw_by_pub: Dict[str, List[Dict[str, Any]]] = {}
        for c in candidates:
            aid = normalize_arxiv_id(c.get("arxiv_id"))
            if aid:
                raw_by_pub.setdefault(aid, []).append(c)
        cand_by_pub = raw_by_pub

    norm_split_manifest: Optional[Dict[str, str]] = None
    if split_manifest is not None:
        norm_split_manifest = {
            norm_k: str(part).strip().lower()
            for k_aid, part in split_manifest.items()
            if (norm_k := normalize_arxiv_id(k_aid))
        }

    predictions: List[Dict[str, Any]] = []
    pending_rows: List[Tuple[int, List[str], int, int]] = []
    pending_X: List[List[float]] = []

    def _flush_learned_batch() -> None:
        if not pending_X:
            return
        probs = model.model.predict_proba(pending_X)  # type: ignore[union-attr]
        scores = model._positive_probs(probs)  # type: ignore[union-attr]
        for row_idx, c_aids, start, end in pending_rows:
            unique_top = _unique_top_k(list(zip(c_aids, scores[start:end])), k)
            row = predictions[row_idx]
            for rank_idx in range(1, k + 1):
                row[f"cand_{rank_idx}"] = unique_top[rank_idx - 1] if rank_idx <= len(unique_top) else None
        pending_rows.clear()
        pending_X.clear()

    for entry in bib_entries:
        pub_id = normalize_arxiv_id(entry.get("arxiv_id"))
        if not pub_id:
            continue

        # Nếu có split_manifest: chỉ tạo prediction cho bài nằm trong matching pools (train/valid/test)
        if norm_split_manifest is not None:
            if pub_id not in norm_split_manifest:
                continue
            part = norm_split_manifest[pub_id]
        else:
            part = default_partition

        ckey = str(entry.get("citation_key", ""))
        gt_id = normalize_arxiv_id(entry.get("groundtruth_arxiv_id")) or None
        cands = cand_by_pub.get(pub_id, [])

        row: Dict[str, Any] = {
            "arxiv_id": pub_id,
            "partition": part,
            "citation_key": ckey,
            "groundtruth_arxiv_id": gt_id,
        }
        for rank_idx in range(1, k + 1):
            row[f"cand_{rank_idx}"] = None

        row_idx = len(predictions)
        predictions.append(row)

        if not cands:
            continue

        if is_learned:
            prep_bib = _prepare_bib_entry(entry)
            start = len(pending_X)
            c_aids: List[str] = []
            for c_aid, prep_c in cands:
                c_aids.append(c_aid)
                pending_X.append(_score_prepared_vector(prep_bib, prep_c))
            pending_rows.append((row_idx, c_aids, start, len(pending_X)))
            if len(pending_X) >= batch_size:
                _flush_learned_batch()
        elif is_heuristic:
            prep_bib = _prepare_bib_entry(entry)
            scored = [(c_aid, model.score_prepared_pair(prep_bib, prep_c)) for c_aid, prep_c in cands]
            unique_top = _unique_top_k(scored, k)
            for rank_idx in range(1, k + 1):
                row[f"cand_{rank_idx}"] = unique_top[rank_idx - 1] if rank_idx <= len(unique_top) else None
        else:
            ranked = model.rank_candidates(entry, cands)
            unique_top = _unique_top_k(list(ranked), k)
            for rank_idx in range(1, k + 1):
                row[f"cand_{rank_idx}"] = unique_top[rank_idx - 1] if rank_idx <= len(unique_top) else None

    _flush_learned_batch()
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
        used_ref_aids: Set[str] = set()
        for r_idx in range(1, refs_per_pub + 1):
            month = (r_idx - 1) % 12 + 1
            while True:
                ref_aid = f"17{month:02d}.{rng.randint(10000, 99999)}"
                if ref_aid not in used_ref_aids:
                    used_ref_aids.add(ref_aid)
                    break
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
        matched_in_pub = 0
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
                matched_in_pub += 1
            elif prob < 0.85 and pub_cands:
                # 25% Fuzzy match có nhiễu
                matched_cand = pub_cands[(e_idx - 1) % len(pub_cands)]
                gt_aid = matched_cand["ref_arxiv_id"]
                # Thêm typo nhỏ hoặc viết hoa/thường
                e_title = matched_cand["ref_title"].lower() + " (extended study)"
                e_authors = [matched_cand["ref_authors"][0].split()[0]]  # Chỉ giữ họ
                e_year = matched_cand["ref_year"] + rng.choice([-1, 0, 1])
                e_doi = None  # Thiếu DOI
                matched_in_pub += 1
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
                "method": "manual",
                "labeled_by": "member_4",
                "entries_count": entries_per_pub,
                "labeled_count": entries_per_pub,
                "matched_count": matched_in_pub,
            })
        else:
            auto_pool.append({
                "arxiv_id": pub_aid,
                "method": "automatic",
                "labeled_by": "auto_heuristic",
                "entries_count": entries_per_pub,
                "labeled_count": entries_per_pub,
                "matched_count": matched_in_pub,
            })

    return {
        "papers": papers,
        "references": references,
        "bibtex": bibtex,
        "manual_pool": manual_pool,
        "auto_pool": auto_pool,
    }
