# Member 1 source pilot evidence — 05/11/2026

Đây là runtime evidence cho handoff `version_tasks.csv` của Member 1 sang downloader/safe extractor của Member 2. Corpus thật nằm ngoài Git tại `/Users/ngogiaan1103/Documents/ChatGPT/nmkhdl-project-1-data`.

## Input và command contract

- Owner: `member-1` — Ngô Gia An — MSSV 23120205.
- Input: manifest discovery chính thức, lọc `--member member-1 --limit 3`.
- Endpoint: version-specific arXiv export source.
- Pacing: tối thiểu 3 giây; bounded retry; descriptive User-Agent.
- Output: raw archive, download status, allowlist `.tex/.bib`, extraction status và source manifest ngoài Git.

## First live run

| Metric | Value |
|---|---:|
| Run ID | `4dc8bc46-81bf-4d86-8714-f222a1e550ff` |
| Expected version tasks | 3 |
| Terminal status records | 3 |
| Success | 3 |
| Archive bytes | 2.795.141 |
| Filtered `.tex/.bib` bytes | 283.272 |

| Version | HTTP/attempts | Archive bytes | Extracted files | Filtered bytes | Archive SHA-256 |
|---|---:|---:|---:|---:|---|
| `2509.16047v1` | 200 / 1 | 51.428 | 4 | 156.867 | `5d2bd83f2847cd8bc5874b36f7fb653ebe660e9e2ca5794c78483b7702a3d225` |
| `2509.16048v1` | 200 / 1 | 2.088.520 | 2 | 95.857 | `f8747eedf3f4e8773677e8b690a866c61f355c718d22e289c18ac60568a792a9` |
| `2509.16049v1` | 200 / 2 | 655.193 | 2 | 30.548 | `89c0e3b41a9288335bbd4a572570206021419023acbf40b709bd3d928d090e1a` |

Mọi extracted source member trong ba version directory đều có extension `.tex` hoặc `.bib`; extraction status JSON được lưu cạnh version directory để audit, không phải source member.

## Resume evidence

Chạy lại cùng command không dùng `--no-resume` tạo run ID `0a3caf42-3823-43d9-b9e9-d0253e45abaf`, vẫn trả 3/3 success và giữ nguyên tổng archive/filtered bytes. Downloader xác minh archive checksum trước khi reuse.

## Gate tiếp theo

Pilot này chỉ chứng minh contract và một sample nhỏ; không được diễn giải là full source coverage. Trước release cần xử lý đủ 7.858 version tasks, giữ explicit terminal status cho mọi task và chứng minh expected-version count bằng terminal-status count.
