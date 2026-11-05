# Introduction to Data Science — arXiv Project

Repository mã nguồn chung của nhóm 18 cho đồ án arXiv môn Nhập môn Khoa học Dữ liệu. Đồ án gồm Milestone 1 Crawling, Milestone 2 Parsing/Standardization và Milestone 3 Matching.

Workspace này là **code repository của toàn đồ án**. Jupyter Book/GitHub Pages là deliverable riêng; đại diện nhóm sẽ nộp URL Pages công khai chứa nội dung M1 + M2.

## Trạng thái hiện tại

Member 1 đã hoàn tất contract foundation và phần feature implementation của discovery:

- Data contracts và status policy dùng chung.
- Validate/checksum assigned ranges; không tự đoán boundary convention.
- Typed config với pacing an toàn và không log secret value.
- Fake và live arXiv clients, batch tối đa 100 IDs/request, pacing tối thiểu 3 giây, timeout, bounded retry và raw-response cache.
- Deterministic version resolver và metadata/version/status manifests.
- Atomic checkpoint, crash/resume và structured JSONL events.
- CLI fixture offline và lệnh `discover` thật có filter `--member`, `--paper`, `--limit`.

Milestone 1 toàn nhóm **chưa hoàn tất**: chưa có downloader/safe extractor của Member 2 trên remote, CLI Semantic Scholar của Member 3 còn ở branch chưa merge, và full assigned discovery đang bị arXiv rate-limit/timeout. Các command chưa tích hợp vẫn trả exit code `3` để không tạo bằng chứng giả.

## Cấu trúc

```text
.
├── docs/                    # Contract kỹ thuật đã khóa theo phase
├── examples/phase1/         # Input synthetic nhỏ để rehearsal offline
├── instructions/            # Đề bài chính thức của ba milestone
├── plans/                   # Plan tổng và assignment của 5 thành viên
├── src/                     # Package pipeline
└── tests/                   # Unit/integration tests offline
```

## Yêu cầu môi trường

- Python `>=3.11` vì code dùng `enum.StrEnum`.
- Discovery arXiv không cần API key; Semantic Scholar key là tùy chọn và không được commit.
- Lần kiểm tra hiện tại chạy bằng Python 3.14; nhóm vẫn phải rehearsal trên Python/Colab version chính thức trước release.

Thiết lập local:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest -q
```

## Assigned ranges nhóm 18

Đã nhận đủ năm range inclusive, mỗi thành viên 5.000 IDs, union 25.000 IDs không overlap. Member 5 đi qua tháng và dùng explicit monthly ceiling `2025-10=27692`, được xác minh bằng targeted arXiv API.

Input thật để tại `local/assigned_ranges.csv`; `local/` đã bị Git ignore. Validate đủ năm dòng, chưa expand:

```bash
python -m src.cli validate-ranges \
  --ranges-file local/assigned_ranges.csv
```

Expand theo quy ước đã xác nhận và ghi output ngoài repository:

```bash
python -m src.cli validate-ranges \
  --ranges-file local/assigned_ranges.csv \
  --inclusive-end \
  --month-ceiling 2025-10=27692 \
  --output ../arxiv-data/expanded_ids.csv
```

Checksums đã xác minh:

```text
raw ranges: a49e21baf649021df0dd6a24af58514906aef2a5b0b92608fa0f48c470a20448
expanded:   e653c561b6a3cac16ea58882475138a3843cecd19a535dc3133578d55d72d7b4
```

## Chạy discovery thật

Chạy riêng Member 1, output luôn nằm ngoài repository:

```bash
python -m src.cli discover \
  --owned-papers local/expanded_ids.csv \
  --data-dir ../nmkhdl-project-1-data \
  --user-agent "group-18-nmkhdl-project/0.2 (+https://github.com/bingsu1103/nmkhdl-project-1)" \
  --member member-1 \
  --resume
```

Run chính thức ngày 05/11/2026 đã đạt 5.000/5.000 metadata success và sinh 7.858 version tasks. Nếu run bị gián đoạn, chạy lại cùng input/config với `--resume`.

Output chính:

```text
<data-dir>/
├── raw/arxiv_api/                     # Atom XML cache theo batch
├── checkpoints/discovery/             # checkpoint theo publication
├── events/discovery.jsonl             # structured stage events
└── manifests/discovery/
    ├── papers.jsonl
    ├── version_tasks.csv
    ├── discovery_status.jsonl
    └── discovery_summary.json
```

Không đổi `retryable_failure` thành success thủ công. Xem run evidence và checksums tại `docs/member1-discovery-run-2026-11-05.md`.

## References, tables và validation M1

Semantic Scholar key là tùy chọn nhưng anonymous endpoint có thể trả HTTP 429. Nếu có key, tự đặt trong shell/Colab Secret; không gửi hoặc commit key:

```bash
export SEMANTIC_SCHOLAR_API_KEY="<your-key>"
python -m src.cli crawl-references \
  --owned-papers local/expanded_ids.csv \
  --data-dir ../nmkhdl-project-1-data \
  --member member-1
```

Chỉ sau khi mọi publication có S2 terminal status `ok` hoặc `not_found`:

```bash
python -m src.cli build-tables \
  --data-dir ../nmkhdl-project-1-data

python -m src.cli validate \
  --owned-papers local/expanded_ids.csv \
  --data-dir ../nmkhdl-project-1-data \
  --member member-1
```

`build-tables` sẽ fail nếu S2 còn thiếu, unexpected hoặc non-terminal status; không tạo bảng thiếu dữ liệu để vượt validation giả.

## Chạy fixture end-to-end Phase 1

Tạo output ngoài repository rồi chạy:

```bash
mkdir -p ../arxiv-data-phase1
python -m src.cli fixture-discover \
  --owned-papers examples/phase1/owned_papers.csv \
  --metadata-fixture examples/phase1/metadata.json \
  --checkpoint-dir ../arxiv-data-phase1/checkpoints \
  --events-output ../arxiv-data-phase1/events.jsonl
```

Kết quả mong đợi: exit code `0`, `paper_count` bằng `2`, `success` bằng `2`, checkpoint JSON theo publication và file `events.jsonl` có structured events.

Chạy lại bằng checkpoint:

```bash
python -m src.cli fixture-discover \
  --owned-papers examples/phase1/owned_papers.csv \
  --metadata-fixture examples/phase1/metadata.json \
  --checkpoint-dir ../arxiv-data-phase1/checkpoints \
  --events-output ../arxiv-data-phase1/events-resumed.jsonl \
  --resume
```

Event resumed có `"resumed": true`. Nếu bytes của một trong hai input thay đổi, fingerprint đổi và pipeline không reuse checkpoint cũ.

## Exit codes

| Code | Ý nghĩa |
|---:|---|
| `0` | Lệnh hoàn tất và mọi selected paper success |
| `2` | Config/input validation error (`argparse` kết thúc) |
| `3` | Command thuộc phase sau, chưa được triển khai |
| `4` | Run có ít nhất một paper không success |

## Quy tắc Git

- `main` chỉ để tích hợp; không phát triển trực tiếp.
- Mỗi member làm đúng branch của mình, không push/rebase/sửa branch người khác.
- Member 1 dùng `member-1/discovery-orchestration`.
- Merge qua Pull Request sau khi tests và review pass.
- Không commit corpus, Parquet outputs, archives, logs, checkpoints, credentials hoặc API keys.

Thiết lập Ruleset/branch protection, required review và merge policy trên GitHub là thao tác owner thực hiện thủ công. Codex không tự đổi GitHub Settings theo yêu cầu của chủ repository.

## Tài liệu

- [Kế hoạch tổng](plans/project-1-master-plan.md)
- [Assignment Member 1](plans/member-1-assignment.md)
- [Phase 1 contracts](docs/phase1-contracts.md)
- [Milestone 1 integration status](docs/milestone1-integration-status.md)
- [Member 1 full discovery evidence](docs/member1-discovery-run-2026-11-05.md)
- [Đề bài](instructions/index.md)
