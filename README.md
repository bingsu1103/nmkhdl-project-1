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

Milestone 1 toàn nhóm **chưa hoàn tất trên dữ liệu thật**. Member 1 đã discovery đủ 5.000/5.000 papers và xử lý đủ 7.858/7.858 version tasks: 7.390 `success`, 430 `no_tex_bib`, 37 `http_error` và 1 `invalid_archive`. Member 2–5 phải chạy shard 5.000 IDs của mình theo hướng dẫn bên dưới. Sau đó nhóm mới tổng hợp đủ 25.000 IDs, hoàn tất Semantic Scholar, tables, validation và benchmark Colab trước khi công bố kết quả toàn nhóm.

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

## Chiến lược crawl phân tán cho 5 thành viên

Từ ngày 11/11/2026, nhóm chuyển sang **mỗi thành viên tự crawl shard 5.000 IDs được giao**. Không một máy cá nhân nào phải giữ toàn bộ raw source của 25.000 IDs. Mọi người phải dùng cùng code trên `main`, cùng input range và cùng cấu hình; kết quả toàn nhóm được tổng hợp từ năm shard không overlap.

| Thành viên | GitHub | `--member` | Data directory đề xuất |
|---|---|---|---|
| Ngô Gia An | `bingsu1103` | `member-1` | `../nmkhdl-project-1-data` (đã chạy) |
| Lày Khánh An | `laykhanhan01062005-star` | `member-2` | `../nmkhdl-project-1-data-member-2` |
| Nguyễn Đức Quang | `ducquang2` | `member-3` | `../nmkhdl-project-1-data-member-3` |
| Từ Quốc Nghĩa | `tuquocnghia` | `member-4` | `../nmkhdl-project-1-data-member-4` |
| Phạm Phúc An Khang | `PPAKhang` | `member-5` | `../nmkhdl-project-1-data-member-5` |

Quy tắc bắt buộc:

1. Chỉ chạy shard của mình; luôn truyền đúng `--member member-N`.
2. Không chạy hai process ghi vào cùng một `data-dir`.
3. Có thể `Ctrl+C` và chạy lại cùng lệnh; checkpoint/resume phải được giữ nguyên.
4. Không sửa tay status, số liệu hoặc xóa failure để làm đẹp kết quả.
5. Không commit `raw/`, `corpus/`, Parquet, checkpoints, logs hay secret lên GitHub.
6. Mỗi người giữ raw data của mình và bàn giao manifest/metrics theo hợp đồng ở cuối phần này.

### Chuẩn bị input local

`local/` bị Git ignore nên mỗi thành viên tạo `local/assigned_ranges.csv` như sau:

```csv
member_id,start_month,start_id,end_month,end_id
member-1,2025-09,16047,2025-09,21046
member-2,2025-09,21047,2025-09,26046
member-3,2025-10,19401,2025-10,24400
member-4,2024-09,13594,2024-09,18593
member-5,2025-10,24401,2025-11,01708
```

Sau đó tạo manifest 25.000 IDs dùng chung:

```bash
.venv/bin/python -m src.cli validate-ranges \
  --ranges-file local/assigned_ranges.csv \
  --inclusive-end \
  --month-ceiling 2025-10=27692 \
  --output local/expanded_ids.csv
```

Trong JSON do lệnh in ra, trường `paper_count` phải bằng `25000` và `papers_sha256` phải đúng checksum `e653c561b6a3cac16ea58882475138a3843cecd19a535dc3133578d55d72d7b4`. Đây là checksum canonical của tập ID do CLI tính, không phải byte checksum từ lệnh `shasum` trên file CSV.

### Lệnh chạy shard cá nhân

Trong toàn bộ block dưới đây, mỗi người thay đúng hai giá trị:

- `MEMBER_NO`: số thành viên từ `1` đến `5`.
- `MEMBER_DATA_DIR`: thư mục ngoài repository, ưu tiên ổ có tối thiểu 40 GB trống.

Ví dụ Member 2 dùng `MEMBER_NO=2`; các biến chỉ có hiệu lực trong terminal hiện tại:

```bash
MEMBER_NO=2
MEMBER_DATA_DIR="../nmkhdl-project-1-data-member-2"
```

Discovery:

```bash
caffeinate -i .venv/bin/python -m src.cli discover \
  --owned-papers local/expanded_ids.csv \
  --data-dir "$MEMBER_DATA_DIR" \
  --user-agent "group-18-nmkhdl-project/0.2 (+https://github.com/bingsu1103/nmkhdl-project-1)" \
  --member "member-$MEMBER_NO" \
  --resume
```

Crawl mọi source-version chưa có status:

```bash
caffeinate -i .venv/bin/python -m src.cli crawl-sources \
  --data-dir "$MEMBER_DATA_DIR" \
  --user-agent "group-18-nmkhdl-project/0.2 (+https://github.com/bingsu1103/nmkhdl-project-1)" \
  --member "member-$MEMBER_NO" \
  --missing-only \
  --read-timeout 300
```

Retry riêng failure; exit code `4` vẫn có thể là kết quả terminal hợp lệ như 404, archive quá lớn hoặc source không phải TeX:

```bash
caffeinate -i .venv/bin/python -m src.cli crawl-sources \
  --data-dir "$MEMBER_DATA_DIR" \
  --user-agent "group-18-nmkhdl-project/0.2 (+https://github.com/bingsu1103/nmkhdl-project-1)" \
  --member "member-$MEMBER_NO" \
  --retry-failures-only \
  --read-timeout 300
```

Crawl references qua Semantic Scholar. API key là tùy chọn và chỉ đặt trong biến môi trường/secret, tuyệt đối không commit:

```bash
caffeinate -i .venv/bin/python -m src.cli crawl-references \
  --owned-papers local/expanded_ids.csv \
  --data-dir "$MEMBER_DATA_DIR" \
  --member "member-$MEMBER_NO"
```

Khi Semantic Scholar đã có terminal status cho mọi publication, tạo bảng và validate shard:

```bash
.venv/bin/python -m src.cli build-tables \
  --data-dir "$MEMBER_DATA_DIR"

.venv/bin/python -m src.cli validate \
  --owned-papers local/expanded_ids.csv \
  --data-dir "$MEMBER_DATA_DIR" \
  --member "member-$MEMBER_NO"
```

### Artifact bàn giao để tổng hợp báo cáo

Mỗi thành viên gửi cho integrator một gói artifact nhỏ, giữ nguyên cấu trúc đường dẫn:

```text
manifests/discovery/discovery_summary.json
manifests/discovery/discovery_status.jsonl
manifests/discovery/papers.jsonl
manifests/discovery/version_tasks.csv
manifests/source_status.jsonl             # nguồn chuẩn để tính tổng toàn shard
manifests/source_summary.json             # summary của run gần nhất, không mặc định là tổng shard
manifests/s2_summary.json                 # chỉ dùng sau full-shard S2 crawl, không dùng pilot/smoke
events/discovery.jsonl
tables/m1_validation_report.json        # chỉ có sau build/validate
metrics/summary.json                    # chỉ có sau run-all/metrics
```

Gửi kèm file text ghi `member_id`, commit SHA (`git rev-parse HEAD`), lệnh đã chạy, thời điểm bắt đầu/kết thúc và môi trường chạy. Nếu benchmark Colab được chia thành nhiều phiên, phải giữ resource/runtime log của từng phiên.

Các thư mục dữ liệu lớn sau **không đưa vào code repository**:

```text
raw/
corpus/
checkpoints/
tables/papers/
tables/references/
```

Người sở hữu shard giữ các thư mục này trên máy/Drive/SSD để tái xử lý. Integrator chỉ ghép các Parquet shard và manifest bằng bước merge/reconciliation có kiểm tra duplicate, coverage, schema và foreign key; không nối JSONL hoặc copy đè thủ công.

Trạng thái Member 1 tại ngày 11/11/2026: discovery và source-version coverage đã xong; số tổng phải được tính từ 7.858 record trong `manifests/source_status.jsonl`. `manifests/source_summary.json` hiện là summary của lượt retry cuối, còn `manifests/s2_summary.json` hiện chỉ thuộc smoke test 3 paper. Vì vậy Member 1 vẫn phải chạy full Semantic Scholar, build tables, validation và metrics trước khi có một handoff bundle hoàn chỉnh cho báo cáo M1.

## Ví dụ run đã hoàn tất của Member 1

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

## Source crawl và completeness gate M1 — ví dụ Member 1

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

## References, tables và validation M1 — ví dụ Member 1

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
