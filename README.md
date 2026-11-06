# Introduction to Data Science — arXiv Project

Repository mã nguồn chung của nhóm 18 cho đồ án arXiv môn Nhập môn Khoa học Dữ liệu. Đồ án gồm Milestone 1 Crawling, Milestone 2 Parsing/Standardization và Milestone 3 Matching.
> **🌐 Xem Jupyter Book Report Online tại đây:** [https://ppakhang.github.io/nmkhdl-project-1-report/](https://ppakhang.github.io/nmkhdl-project-1-report/)
> 
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

Milestone 1 toàn nhóm **chưa hoàn tất trên dữ liệu thật**: full discovery Member 1 đã đạt 5.000/5.000; downloader/safe extractor của Member 2 và CLI Semantic Scholar của Member 3 đã được merge. Source pilot thật đạt 3/3 version và checksum-based resume đạt 3/3. Source-completeness gate, `run-all` và benchmark/metrics đã có code và test offline, nhưng nhóm vẫn phải chạy đủ 7.858 source-version tasks, hoàn tất Semantic Scholar crawl (anonymous smoke test đang nhận HTTP 429), rồi lưu artifact validation/benchmark thật trước khi tuyên bố hoàn tất.

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

Không đổi `retryable_failure` thành success thủ công. Runtime summary, checksums và corpus thật được giữ ngoài Git; Jupyter Book đọc các artifact máy sinh thay vì dựa vào nhật ký Markdown thủ công.

## Source crawl và completeness gate M1

Tiếp tục tải/extract toàn bộ version của Member 1 từ manifest discovery đã có:

```bash
python -m src.cli crawl-sources \
  --data-dir ../nmkhdl-project-1-data \
  --user-agent "group-18-nmkhdl-project/0.2 (+https://github.com/bingsu1103/nmkhdl-project-1)" \
  --member member-1
```

Lệnh ghi checkpoint terminal theo từng version vào `manifests/source_status.jsonl`; chạy lại sẽ resume mặc định. Cổng validation chỉ qua khi mọi `versioned_arxiv_id` trong `version_tasks.csv` có đúng một terminal status, không thiếu, không dư và không trùng.

Nếu một run dài bị dừng sau khi đã có nhiều status, ưu tiên hoàn thành phần chưa từng xử lý trước mà không duyệt lại cache cũ:

```bash
python -m src.cli crawl-sources \
  --data-dir ../nmkhdl-project-1-data \
  --user-agent "group-18-nmkhdl-project/0.2 (+https://github.com/bingsu1103/nmkhdl-project-1)" \
  --member member-1 \
  --missing-only
```

Sau khi không còn version thiếu, retry riêng các status lỗi; `success` và `no_tex_bib` được bỏ qua:

```bash
python -m src.cli crawl-sources \
  --data-dir ../nmkhdl-project-1-data \
  --user-agent "group-18-nmkhdl-project/0.2 (+https://github.com/bingsu1103/nmkhdl-project-1)" \
  --member member-1 \
  --retry-failures-only
```

Hai chế độ trên không được chạy đồng thời và không được chạy hai process trên cùng `data-dir`. Source endpoint trả PDF-only được ghi nhận là `no_tex_bib`, đúng hợp đồng empty record thay vì lỗi archive.

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

## Chạy toàn bộ M1 và benchmark

`run-all` nối discovery → source crawl → Semantic Scholar → hai bảng Parquet → validation → metrics. Dùng `--resume` cho runtime thật dài hoặc bị gián đoạn:

```bash
python -m src.cli run-all \
  --owned-papers local/expanded_ids.csv \
  --data-dir ../nmkhdl-project-1-data \
  --user-agent "group-18-nmkhdl-project/0.2 (+https://github.com/bingsu1103/nmkhdl-project-1)" \
  --member member-1 \
  --resume
```

Release gate chỉ trả exit code `0` khi discovery, source completeness, Semantic Scholar terminal statuses, schema/FK/reconciliation và validation đều qua. Kết quả máy sinh nằm ở:

```text
<data-dir>/manifests/m1_run_summary.json
<data-dir>/tables/m1_validation_report.json
<data-dir>/metrics/summary.json
```

Benchmark chính thức phải dùng một `data-dir` sạch và không dùng `--resume`, để thời gian/RAM/disk không bị trộn với cache của run cũ:

```bash
python -m src.cli benchmark \
  --owned-papers local/expanded_ids.csv \
  --data-dir ../nmkhdl-project-1-benchmark \
  --user-agent "group-18-nmkhdl-project/0.2 (+https://github.com/bingsu1103/nmkhdl-project-1)" \
  --member member-1
```

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
- [Đề bài](instructions/index.md)
