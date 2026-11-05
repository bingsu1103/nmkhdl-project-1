# Milestone 1 integration status — 05/11/2026

Đây là snapshot có bằng chứng sau khi fetch tất cả remote branches. Không dùng tài liệu này để tuyên bố Milestone 1 đã hoàn tất.

## Remote branch audit

| Nguồn | Đã thấy | Trạng thái tích hợp |
|---|---|---|
| `origin/main` | Member 1 discovery; Semantic Scholar core/CLI/tests; schemas/storage/validation/metrics; notebooks | Đã đồng bộ vào branch Member 1 |
| `origin/member-3/references-bibtex` | CLI S2, tests và API-key env fix | Đã merge vào `main` |
| `origin/member-4/quality-matching` | Không có commit mới ngoài `main` tại thời điểm fetch | Đã nhận phần merge trên `main` |
| `origin/member-5/book-poster` | Plan/assignment; chưa thấy Jupyter Book implementation mới ngoài `main` | Chờ Member 5 |
| `member-2/source-parsing` | Không xuất hiện trên remote | Blocker cho source download/extraction M1 |

## Member 1 đã hoàn tất trong Phase 2

- Đủ năm inclusive ranges: 25.000 IDs, mỗi member đúng 5.000, không overlap.
- SHA-256 raw ranges: `a49e21baf649021df0dd6a24af58514906aef2a5b0b92608fa0f48c470a20448`.
- SHA-256 expanded manifest: `e653c561b6a3cac16ea58882475138a3843cecd19a535dc3133578d55d72d7b4`.
- Live arXiv batch client: custom User-Agent, timeout, retry/backoff, 3-second pacing, raw XML cache.
- Metadata mapping, version enumeration, atomic checkpoint/resume.
- `discover` CLI và handoff files cho metadata, version tasks, statuses, events, summary.
- Full Member 1 discovery: 5.000/5.000 success, 7.858 version tasks.
- CLI `crawl-references`, `build-tables`, `validate` đã nối qua public interfaces của Member 3/4; table builder có completeness guard.
- 121 tests pass sau cross-month support và M1 integration gates; ResourceMonitor test cần quyền đọc process metrics của runtime.

## Runtime evidence

Pilot retry đạt 3/3. Full discovery Member 1 sau đó đạt 5.000/5.000 metadata success, không có missing/permanent/retryable failure, sinh 7.858 version tasks. Run ID và artifact checksums nằm trong `docs/member1-discovery-run-2026-11-05.md`.

## Blockers trước khi Milestone 1 toàn nhóm hoàn tất

1. Member 2 push/merge downloader và safe extractor để xử lý mọi version.
2. S2 smoke-test 3 paper nhận HTTP 429; cần retry bằng `SEMANTIC_SCHOLAR_API_KEY` đặt local/Colab Secret hoặc runtime có quota.
3. Hoàn tất 5.000 S2 terminal statuses rồi build/validate hai bảng M1.
4. Tích hợp source stage và metrics thành `run-all`; chạy reconciliation và benchmark Colab CPU-only.
5. Member 5 hoàn tất Jupyter Book M1 và cung cấp Pages URL.
