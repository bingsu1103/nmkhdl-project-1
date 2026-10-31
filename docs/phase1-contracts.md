# Phase 1 contracts

Tài liệu này khóa interface offline cho Gate G1. Nó chưa phải bằng chứng crawl Internet hoặc hoàn tất Milestone 1.

## Data contracts

| Contract | Producer | Consumer | Ý nghĩa |
|---|---|---|---|
| `AssignedRange` | sheet import | range validator | Giữ nguyên bốn trường range và `member_id` nội bộ |
| `OwnedPaper` | range expander | discovery | Một base arXiv ID thuộc đúng một member |
| `PaperMetadata` | discovery adapter | storage/report | Metadata chuẩn hóa, authors giữ đúng thứ tự |
| `VersionTask` | version resolver | source downloader | Một work item deterministic cho mỗi revision `v1..vN` |
| `StageEvent` | orchestrator | metrics/report | JSONL event có run, stage, subject, status và UTC time |
| `RunManifest` | orchestrator | audit/reproduction | Git SHA, input checksum, config sanitized và package versions |

Source of truth là dataclass trong `src/contracts.py`. Khi thay đổi field, owner phải cập nhật contract tests và yêu cầu review từ consumer liên quan.

## Status policy

| Status | Khi dùng | Resume policy ở Phase 1 |
|---|---|---|
| `pending` | Work item đã tạo nhưng chưa chạy | Phải chạy |
| `running` | Stage đang xử lý | Sau crash phải chạy lại |
| `success` | Output hợp lệ và đầy đủ theo contract | Được reuse nếu fingerprint khớp |
| `no_source` | Publication/nguồn không tồn tại theo adapter | Được reuse nếu fingerprint khớp; không silently drop |
| `retryable_failure` | Timeout/rate limit/server transient | Chạy lại |
| `permanent_failure` | Response/schema/version malformed | Chạy lại sau khi code/input được sửa; không đổi thành success thủ công |

Checkpoint fingerprint gồm owner, arXiv ID và context checksum. CLI fixture tạo context từ bytes của cả owned-paper input và metadata fixture; input thay đổi thì checkpoint cũ không được reuse.

## Phase 1 boundary

Đã có: validation/checksum, safe config, fake discovery adapter, version enumeration, atomic checkpoint, resume, structured events và CLI fixture không Internet.

Chưa có: HTTP arXiv thật, retry/backoff thật, source/reference crawling, tables Parquet, benchmark và full assigned-range run. Các mục này thuộc Phase 2 trở đi và không được mô tả là đã hoàn tất.
