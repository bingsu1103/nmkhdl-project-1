# Milestone 1 integration status — 04/11/2026

Đây là snapshot có bằng chứng sau khi fetch tất cả remote branches. Không dùng tài liệu này để tuyên bố Milestone 1 đã hoàn tất.

## Remote branch audit

| Nguồn | Đã thấy | Trạng thái tích hợp |
|---|---|---|
| `origin/main` | Semantic Scholar core, schemas/storage/validation/metrics, notebooks | Đã merge vào branch Member 1 |
| `origin/member-3/references-bibtex` | CLI S2 và test bổ sung | Chưa merge vào `main`; Member 1 không cherry-pick/sửa branch owner |
| `origin/member-4/quality-matching` | Không có commit mới ngoài `main` tại thời điểm fetch | Đã nhận phần merge trên `main` |
| `origin/member-5/book-poster` | Plan/assignment; chưa thấy Jupyter Book implementation mới ngoài `main` | Chờ Member 5 |
| `member-2/source-parsing` | Không xuất hiện trên remote | Blocker cho source download/extraction M1 |

## Member 1 đã hoàn tất trong Phase 2

- Inclusive range expansion: 5.000 IDs, `2509.16047..2509.21046`.
- SHA-256 expanded manifest: `cd37816ec1d36e61e71fc4ba57b27499610548de7f8292f911300ff0a83d9b38`.
- Live arXiv batch client: custom User-Agent, timeout, retry/backoff, 3-second pacing, raw XML cache.
- Metadata mapping, version enumeration, atomic checkpoint/resume.
- `discover` CLI và handoff files cho metadata, version tasks, statuses, events, summary.
- Unit/integration suite pass sau merge; ResourceMonitor test cần quyền đọc process metrics của runtime.

## Runtime evidence

Pilot ba ID đầu đã chạy bằng implementation thật. arXiv API không trả metadata: client ghi ba `retryable_failure` do `ReadTimeout`; probe trực tiếp ngay sau đó nhận HTTP 429 `Rate exceeded`. Vì vậy full 5.000-ID discovery chưa được chạy và không được báo cáo là thành công.

## Blockers trước khi Milestone 1 toàn nhóm hoàn tất

1. arXiv API hết rate-limit hoặc chuyển pilot/full run sang Colab/network khác.
2. Member 2 push/merge downloader và safe extractor để xử lý mọi version.
3. Member 3 merge CLI/test S2 đang nằm trên branch riêng.
4. Tích hợp outputs Member 1–3 với schema/validation/metrics Member 4.
5. Chạy full range, reconciliation, benchmark Colab CPU-only và Jupyter Book M1.
