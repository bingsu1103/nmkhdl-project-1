# Introduction to Data Science — arXiv Project

Repository mã nguồn chung của nhóm 18 cho đồ án arXiv môn Nhập môn Khoa học Dữ liệu. Đồ án gồm Milestone 1 Crawling, Milestone 2 Parsing/Standardization và Milestone 3 Matching.

Workspace này là **code repository của toàn đồ án**. Jupyter Book/GitHub Pages là deliverable riêng; đại diện nhóm sẽ nộp URL Pages công khai chứa nội dung M1 + M2.

## Trạng thái hiện tại

Giai đoạn 1 (contract và test foundation) đã có:

- Data contracts và status policy dùng chung.
- Validate/checksum assigned ranges; không tự đoán boundary convention.
- Typed config với pacing an toàn và không log secret value.
- Fake arXiv client, deterministic version resolver.
- Atomic checkpoint, crash/resume và structured JSONL events.
- CLI fixture end-to-end không gọi Internet.

Chưa triển khai network client/crawl thật. Các command `discover`, `crawl-sources`, `crawl-references`, `build-tables`, `validate`, `benchmark`, `run-all` hiện trả exit code `3` để không tạo bằng chứng giả.

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
- Phase 1 chỉ dùng Python standard library, không cần API key.
- Lần kiểm tra hiện tại chạy bằng Python 3.14; nhóm vẫn phải rehearsal trên Python/Colab version sẽ dùng chính thức trước khi tuyên bố support version đó.

Thiết lập local:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m unittest discover -v
```

## Assigned range của Member 1

Thông tin đã nhận: Ngô Gia An, MSSV `23120205`, nhóm `18`, range `2025-09/16047` đến `2025-09/21046`.

Input thật để tại `local/assigned_ranges.csv`; `local/` đã bị Git ignore. Quy ước đã xác nhận là **inclusive**: tính cả `start_id` và `end_id`, tương ứng đúng 5.000 candidate IDs.

Chỉ validate một dòng Member 1, chưa expand:

```bash
python -m src.cli validate-ranges \
  --ranges-file local/assigned_ranges.csv \
  --allow-partial
```

Expand theo quy ước đã xác nhận và ghi output ngoài repository:

```bash
python -m src.cli validate-ranges \
  --ranges-file local/assigned_ranges.csv \
  --allow-partial \
  --inclusive-end \
  --output ../arxiv-data/expanded_ids.csv
```

Không đổi sang `--exclusive-end`; cờ đó chỉ tồn tại để pipeline hỗ trợ range khác nếu Lab đưa quy ước khác.

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

## Exit codes Phase 1

| Code | Ý nghĩa |
|---:|---|
| `0` | Lệnh hoàn tất và mọi fixture paper success |
| `2` | Config/input validation error (`argparse` kết thúc) |
| `3` | Command thuộc phase sau, chưa được triển khai |
| `4` | Fixture run có ít nhất một paper không success |

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
