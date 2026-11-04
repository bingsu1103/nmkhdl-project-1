"""
Module evaluate.py: Đánh giá mô hình Reference Matching bằng chỉ số MRR@5 (Mean Reciprocal Rank @5).
Thuộc sở hữu của Member 4 - Data Quality, Schema và ML Owner.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import pyarrow as pa
from src.normalize import normalize_arxiv_id


def compute_reciprocal_rank_at_k(
    groundtruth_arxiv_id: Optional[str],
    candidates: Sequence[Optional[str]],
    k: int = 5,
) -> Tuple[float, Optional[int]]:
    """
    Tính Reciprocal Rank @ k cho một mục BibTeX đơn lẻ:
    - groundtruth_arxiv_id: Mã arXiv của tài liệu tham khảo đúng (None nếu không có trên arXiv).
    - candidates: Danh sách các mã arXiv ứng viên do mô hình xếp hạng (thứ tự từ tốt nhất đến kém nhất).
    - k: Giới hạn xét top-k ứng viên (mặc định k=5 theo đề bài).

    Trả về: (reciprocal_rank, rank_position)
    - Nếu groundtruth_arxiv_id xuất hiện ở vị trí i (1-indexed, 1 <= i <= k):
      reciprocal_rank = 1.0 / i, rank_position = i.
    - Nếu không xuất hiện trong top-k hoặc groundtruth_arxiv_id là None:
      reciprocal_rank = 0.0, rank_position = None.
    """
    if not groundtruth_arxiv_id:
        return 0.0, None

    gt_norm = normalize_arxiv_id(groundtruth_arxiv_id)
    if not gt_norm:
        return 0.0, None

    # Chỉ xét tối đa k ứng viên đầu tiên
    top_k_cands = candidates[:k]
    for idx, cand in enumerate(top_k_cands):
        if cand is not None:
            cand_norm = normalize_arxiv_id(cand)
            if cand_norm and cand_norm == gt_norm:
                rank = idx + 1
                return (1.0 / rank), rank

    return 0.0, None


def compute_mrr_at_k(
    records: Union[List[Dict[str, Any]], pa.Table],
    k: int = 5,
    partition_filter: Optional[str] = "test",
) -> Dict[str, Any]:
    """
    Tính Mean Reciprocal Rank @ k (MRR@k) trên tập hợp các dòng dự đoán:
    MRR@k = (1 / |Q|) * sum_{i=1}^{|Q|} (1 / rank_i)
    
    Trong đó:
    - |Q| là tổng số dòng được đánh giá (ví dụ trên tập test).
    - rank_i là thứ tự của trích dẫn đúng trong top-k (nếu không nằm trong top-k thì điểm bằng 0).
    """
    if isinstance(records, pa.Table):
        rows = records.to_pylist()
    else:
        rows = records

    # Lọc theo partition nếu có yêu cầu (mặc định lọc partition='test')
    if partition_filter:
        target_part = partition_filter.strip().lower()
        rows = [r for r in rows if str(r.get("partition", "")).strip().lower() == target_part]

    total_q = len(rows)
    if total_q == 0:
        return {
            "mrr": 0.0,
            "total_queries": 0,
            "hits_at_k": 0,
            "hit_rate": 0.0,
            "rank_distribution": {f"rank_{i}": 0 for i in range(1, k + 1)},
            "unranked_count": 0,
        }

    sum_rr = 0.0
    hits_at_k = 0
    rank_dist = {f"rank_{i}": 0 for i in range(1, k + 1)}
    unranked_count = 0

    for r in rows:
        gt = r.get("groundtruth_arxiv_id")
        # Thu thập các ứng viên cand_1..cand_k
        cands = []
        for i in range(1, k + 1):
            cand_val = r.get(f"cand_{i}")
            cands.append(cand_val)

        rr, rank = compute_reciprocal_rank_at_k(gt, cands, k=k)
        sum_rr += rr
        if rank is not None:
            hits_at_k += 1
            rank_dist[f"rank_{rank}"] += 1
        else:
            unranked_count += 1

    mrr = round(sum_rr / total_q, 4)
    hit_rate = round(hits_at_k / total_q, 4)

    return {
        "mrr": mrr,
        "total_queries": total_q,
        "hits_at_k": hits_at_k,
        "hit_rate": hit_rate,
        "rank_distribution": rank_dist,
        "unranked_count": unranked_count,
    }


def evaluate_predictions_summary(
    table: pa.Table,
    k: int = 5,
) -> Dict[str, Any]:
    """
    Tổng hợp kết quả đánh giá MRR@k cho cả 3 phân vùng: Test, Validation và Train.
    """
    test_metrics = compute_mrr_at_k(table, k=k, partition_filter="test")
    valid_metrics = compute_mrr_at_k(table, k=k, partition_filter="valid")
    train_metrics = compute_mrr_at_k(table, k=k, partition_filter="train")

    return {
        "metric_name": f"MRR@{k}",
        "test": test_metrics,
        "valid": valid_metrics,
        "train": train_metrics,
    }
