# Member 1 full discovery evidence — 05/11/2026

Đây là runtime evidence của phần discovery/versioning thuộc Member 1. Output corpus nằm ngoài Git tại `/Users/ngogiaan1103/Documents/ChatGPT/nmkhdl-project-1-data`.

## Input

| Field | Value |
|---|---|
| Owner | `member-1` — Ngô Gia An — MSSV 23120205 |
| Assigned boundary | `2509.16047..2509.21046`, inclusive |
| Candidate count | 5.000 |
| Group expanded manifest SHA-256 | `e653c561b6a3cac16ea58882475138a3843cecd19a535dc3133578d55d72d7b4` |

## Command contract

Lệnh dùng `discover --member member-1 --resume`, batch size 100, delay 3 giây, timeout 45 giây và tối đa 4 attempts. User-Agent trỏ về public repository; không có API key hoặc secret.

## Result

| Metric | Value |
|---|---:|
| Run ID | `23ca527d-a989-4020-ab59-f6e0243ce4f6` |
| Assigned papers | 5.000 |
| Metadata success | 5.000 |
| No source | 0 |
| Retryable failure | 0 |
| Permanent failure | 0 |
| Version tasks | 7.858 |
| Maximum observed version | `v7` |

Mọi version task đang ở trạng thái `pending` để bàn giao downloader Member 2; `pending` ở đây không phải discovery failure.

## Output checksums

| Artifact | SHA-256 |
|---|---|
| `papers.jsonl` | `405fecacad3d9d97f32528007231f7dd88634e66be814a0ba5e61c414d004fef` |
| `version_tasks.csv` | `ecf0b99ef5c71b404b0ca31f50d2a79f777f013e4845f5f510c15d003f40fbf2` |
| `discovery_status.jsonl` | `c4095fbe28c6e295590585dd1b5ca42285304a4ab6c3deddab506d73e68fa7c4` |

Không commit ba artifacts này vì chúng là dữ liệu chạy thật. Checksums và summary được commit để audit/reproduce.
