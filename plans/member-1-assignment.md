# Member 1 — Ngô Gia An — Discovery, Versioning, Orchestration và Integration

## 1. Vai trò

**Ngô Gia An** đảm nhận Member 1 và vai trò technical integrator, nhưng **chỉ code trên nhánh** `member-1/discovery-orchestration`. Không sửa, push hoặc rebase nhánh thành viên khác. Việc tích hợp được thực hiện bằng review/merge PR đã đạt gate vào `main`.

Thông tin đã xác nhận: MSSV `23120205`, nhóm `18`, GitHub `bingsu1103`, assigned range inclusive `2025-09/16047` đến `2025-09/21046`, tương ứng 5.000 candidate IDs từ `2509.16047` đến `2509.21046`.

Phạm vi chính: nhận assigned IDs, chuẩn hóa/validate, gọi arXiv API để lấy metadata và latest version, enumerate mọi version, cung cấp CLI/orchestrator end-to-end, README và integration gates.

## 2. Requirement chịu trách nhiệm

- R01, R02, một phần R07.
- R13–R16 và R23.
- Điều phối bằng chứng cho R25.

## 3. Deliverables sở hữu

- `src/ids.py`: parser/canonicalizer assigned IDs.
- `src/arxiv_client.py`: adapter arXiv API, timeout/pacing/retry và response mapping.
- `src/version_resolver.py`: lấy latest version suffix và tạo `v1..vN`.
- `src/config.py`: typed config, env vars và validation; không chứa secret.
- `src/cli.py`: command line entry point.
- `src/pipeline.py`: orchestration qua interfaces của M2–M4.
- `tests/test_ids.py`, `tests/test_version_resolver.py`, integration tests liên quan.
- `README.md`, `requirements.txt` và contract docs trong code comments/README.

## 4. Milestone 1 — Crawling: task chi tiết

### MS1-M1-T01 — Intake assigned ranges

- Định nghĩa `assigned_ranges.csv` gồm `member_id,start_month,start_id,end_month,end_id`, đúng bốn trường trên sheet cho mỗi thành viên cộng member key nội bộ.
- Validate đủ đúng năm member rows, numeric/month formats, start/end ordering và duplicate/overlap; không tự suy đoán zero-padding hoặc inclusive/exclusive trước khi Lab convention được xác nhận.
- Expand range theo convention đã chốt thành `expanded_ids.csv`, giữ owner `member_id` cho từng publication và bốn raw values để audit.
- Resolve candidate IDs qua arXiv discovery; nonexistent IDs có explicit status, không silently skip và không làm thay đổi ownership.
- Tính SHA-256 cho input ranges lẫn expanded manifest; deterministic ordering và rerun equality.
- Test empty/missing column, malformed month/id, reversed range, overlap, multi-month boundary và five-member completeness.

**Acceptance:** cùng năm range rows luôn sinh cùng ordered owned-ID manifest/checksum; mọi invalid/ambiguous input fail trước network request với actionable diagnostic.

### MS1-M1-T02 — arXiv metadata adapter

- Dùng modern `client.results(search)` contract, không dùng API cũ đã bị xóa.
- Batch `id_list` hợp lý nhưng giữ pacing tối thiểu 3 giây giữa request liên tiếp và một connection tại một thời điểm.
- Descriptive User-Agent lấy từ config.
- Có connect/read timeout, bounded retry cho 429/5xx/network; không retry vô hạn 4xx permanent.
- Map title, ordered authors, submission date, revised dates, venue/category fields cần thiết; giữ raw response/cache ngoài Git để audit.
- Phân biệt not found, malformed response, transient API failure.

**Acceptance:** mocked tests cover 200/404/429/5xx/timeout; metadata mapping đúng schema trung gian.

### MS1-M1-T03 — Version resolver

- Parse ID latest version trả về, ví dụ `...v4` -> expected `v1..v4`.
- Nếu API không có suffix hoặc suffix bất thường, fail explicit/flag review; không tự gán count thiếu bằng success.
- Sinh task record cho mỗi version trước khi download để không làm rơi failure.
- Reconcile `expected_version_count` với status từ M2.
- Test 1 version, nhiều version, old-style ID, mismatched base ID và malformed suffix.

**Acceptance:** 100% paper đã resolve có deterministic version task list và audit fields.

### MS1-M1-T04 — CLI và config

- Commands đề xuất: `discover`, `crawl-sources`, `crawl-references`, `build-tables`, `validate`, `benchmark`, `run-all`.
- Tham số chung: `--ids-file`, `--data-dir`, `--resume`, `--log-level`, `--user-agent`, retry/timeouts.
- Semantic Scholar key chỉ đọc từ env như `SEMANTIC_SCHOLAR_API_KEY`; không log giá trị.
- Validate data directory không nằm trong tracked repo hoặc cảnh báo/fail an toàn.
- `--help` có ví dụ local và Colab; exit codes phân biệt config error, partial failure, validation failure.

**Acceptance:** lệnh `run-all` có thể chạy mocked end-to-end; invalid config fail trước request mạng.

### MS1-M1-T05 — Orchestrator/resume

- Gọi module của M2/M3/M4 qua stable interfaces, không import internals.
- Tạo run ID, timestamps, git SHA/package versions và config sanitized.
- State transitions atomic; rerun không ghi đè completed output nếu checksum/contracts khớp.
- Continue-on-error theo paper nhưng cuối run phải non-zero nếu còn permanent/unfinished records.
- Emit structured events cho M4 metrics, không buộc report parse log text.
- Hỗ trợ graceful interrupt để checkpoint.

**Acceptance:** integration test mô phỏng crash/restart chứng minh không mất/nhân đôi records.

### MS1-M1-T06 — Reproducibility và README

- Chốt Python version được nhóm test; dependencies có version constraint hợp lý.
- README gồm prerequisites, venv, install, env vars, data-dir, commands theo phase, expected outputs, resume, troubleshooting và Colab CPU-only.
- Ghi rõ không commit data và không nộp data ở M1.
- Fresh-clone rehearsal do người khác thực hiện chỉ dựa trên README.

**Acceptance:** reviewer mới clone chạy unit tests + fixture end-to-end không cần hướng dẫn miệng.

### MS1-M1-T07 — Integration governance

- Tạo issue/PR templates có Requirement IDs, test evidence, data/secret checklist.
- Bật protected `main`, required review/CI nếu quyền repo cho phép.
- Duy trì interface decision log; thay đổi schema phải được M4 duyệt.
- Merge theo dependency: contracts -> M2/M3 -> M4 -> orchestration -> report evidence.
- Không merge PR chỉ vì “chạy trên máy em”; phải có reproducible command/output.

### MS1-M1-T08 — Hoàn tất shard Member 1 và vận hành full-group crawl

Ngô Gia An hoàn tất/reconcile shard 5.000 paper thuộc `member-1`, sau đó là operator của full-group run cho union 25.000 assigned IDs. Quyết định này bám Q&A giảng viên: nhóm được phép tổng hợp ID rồi chạy chung để tiết kiệm tài nguyên; không bắt buộc năm crawler cá nhân.

```bash
python -m src.cli discover --owned-papers local/expanded_ids.csv --data-dir ../nmkhdl-project-1-data-member-1 --user-agent "group-18-nmkhdl-project/0.2 (+https://github.com/bingsu1103/nmkhdl-project-1)" --member member-1 --resume
python -m src.cli crawl-sources --data-dir ../nmkhdl-project-1-data-member-1 --user-agent "group-18-nmkhdl-project/0.2 (+https://github.com/bingsu1103/nmkhdl-project-1)" --member member-1
python -m src.cli crawl-references --owned-papers local/expanded_ids.csv --data-dir ../nmkhdl-project-1-data-member-1 --member member-1
```

Sau khi shard Member 1 đã dừng ghi và được validation, chạy full-group tuần tự trên data directory riêng:

```bash
python -m src.cli discover --owned-papers local/expanded_ids.csv --data-dir ../nmkhdl-project-1-data-group --user-agent "group-18-nmkhdl-project/0.2 (+https://github.com/bingsu1103/nmkhdl-project-1)" --resume
python -m src.cli crawl-sources --data-dir ../nmkhdl-project-1-data-group --user-agent "group-18-nmkhdl-project/0.2 (+https://github.com/bingsu1103/nmkhdl-project-1)"
python -m src.cli crawl-references --owned-papers local/expanded_ids.csv --data-dir ../nmkhdl-project-1-data-group
```

- Không truyền `--member` trong full-group run; scope phải đủ union 25.000 IDs.
- Không chạy hai process ghi cùng data directory đồng thời.
- Trước khi tái sử dụng shard Member 1 trong group data-dir, phải có merge/seed utility kiểm tra key `member_id + versioned_arxiv_id`, checksum, duplicate và reconciliation. Nếu utility chưa có thì không copy đè manifest thủ công.
- Chỉ dùng `expanded_ids.csv` đã xác minh checksum nhóm; không tự sửa range để né lỗi.
- Semantic Scholar key, nếu có, chỉ đặt trong environment/Colab Secret; không gửi cho thành viên khác và không commit.
- Discovery phải có status cho đủ 25.000 paper; mọi expected version phải có source terminal status; S2 phải có terminal status cho đủ group scope.
- Retry lỗi tạm thời; giữ `no_source`, `no_tex_bib`, `not_found` và lỗi vĩnh viễn trong denominator thay vì xóa.
- Bàn giao manifest, summary, checksums, run ID và failure list cho M4/M5; corpus thật không được commit vào Git.

**Acceptance:** shard Member 1 được bảo toàn; union 25.000 IDs không thiếu/trùng; mọi range có coverage report; expected versions reconcile với source statuses; group `papers`/`references` pass schema, FK và uniqueness gates hoặc có failure list trung thực.

## 5. Phối hợp

- Cấp version-task contract cho M2.
- Cấp paper metadata contract cho M4.
- Nhận source adapter từ M2, S2 adapter từ M3, validators/metrics từ M4.
- Cấp run ID/git SHA/README commands cho M5 trích dẫn chính xác.

## 6. Test và evidence bắt buộc

- Unit + mocked HTTP tests.
- Contract test giữa resolver và downloader.
- Integration test tất cả stages với 2–3 synthetic papers.
- Fresh venv install log, test summary, sample CLI help.
- PR/commit history trace về R01/R02/R13–R16/R23.

## 7. Không được làm

- Không crawl full arXiv bằng OAI/Kaggle thay cho assigned IDs.
- Không hard-code range, API key, local absolute path hoặc deadline.
- Không tuyên bố full coverage khi còn status pending/unknown.
- Không sửa module owner khác trực tiếp để “fix nhanh”; mở issue/contract request.

## 8. Definition of Done

- Assigned input được validate/checksum; mọi paper được resolve hoặc có explicit failure.
- Version task list đầy đủ và reconciled.
- Một lệnh end-to-end có resume và structured evidence.
- README được independent reviewer tái chạy thành công.
- Các PR đạt CI/review và không chứa corpus/secret.

## 9. Milestone 2 — Parsing and Standardization: task chi tiết

### MS2-M1-T01 — Contract chuyển giao M1 → M2

- Khóa manifest contract cho publication/version/source file, including empty/no-source statuses.
- Bảo đảm parser nhận đúng relative path, checksum và encoding hints mà không đọc archive chưa xác minh.
- Viết contract test chứng minh mọi expected version từ M1 xuất hiện ở input M2 hoặc explicit empty.
- Tài liệu hóa version lineage để `hierarchy.version` dùng integer đúng revision.

**Đầu ra:** typed input model, contract fixtures và reconciliation report. **Đạt:** không publication/version nào biến mất giữa hai milestone.

### MS2-M1-T02 — CLI/orchestration cho parser

- Thêm commands `parse`, `standardize`, `build-parsing-tables`, `validate-parsing`, `benchmark-parsing` và nối vào `run-all`.
- Stage boundaries checkpoint độc lập; crash khi parse một paper không làm mất kết quả paper đã hoàn tất.
- Resume chỉ reuse output khi source checksum, parser config và code/schema version khớp.
- Cho phép chạy một member range, một publication hoặc toàn group union bằng cùng code path.

**Đầu ra:** CLI help, orchestration tests, state-transition manifest. **Đạt:** clean fixture run tạo đủ three M2 tables hoặc failure records.

### MS2-M1-T03 — Integration root/include parser

- Nhận compilation graph API từ Member 2 và BibTeX/standardization API từ Member 3 qua interfaces, không import private internals.
- Chốt ordering khi include lồng nhau, multiple roots, cycles, missing includes và empty source.
- Điều phối contract về element IDs để dedup không phá parent edges.
- Mở integration issues cho mismatch; không commit vào branch M2/M3.

**Đầu ra:** cross-module integration tests. **Đạt:** synthetic multi-version paper có tree hợp lệ và deterministic output.

### MS2-M1-T04 — README và reproducibility M2

- Bổ sung lệnh parse single member/full group, expected directories và recovery instructions.
- Mô tả compilation-path rules, exclusions/inclusions, normalization/dedup stages ở mức người mới chạy được.
- Pin dependency mới; chạy fresh-clone rehearsal trên CPU-only.
- Cấp exact command/git SHA cho Member 5 viết Book, không để report dùng lệnh giả.

### MS2-M1-T05 — Milestone 2 release gate

- Điều phối full parse union năm ranges và version-coverage reconciliation.
- Chỉ tag M2 release khi schema/tree/dedup/benchmark/Book build đều pass.
- Ghi known failures theo member/publication/version và owner xử lý.
- Xác nhận cùng GitHub Pages URL đã nộp có cả M1 và M2.

## 10. Milestone 3 — Matching, Final Dataset và Poster: task chi tiết

### MS3-M1-T01 — Labeling/split governance

- Cùng Member 4 chốt labeling guideline, no-match/ambiguous policy và audit fields trước khi label.
- Điều phối mỗi member >=5 manual publications, mỗi publication >=20 entries, mỗi member >=100 entries.
- Reconcile group minimum >=25 manual publications/500 entries và automatic pool >=10% remaining, đồng thời >=10 publications.
- Khóa publication-disjoint split: valid/test mỗi set 5 manual +5 automatic; remaining pool train.

**Đạt:** quota validator và split manifest pass; không một publication xuất hiện ở nhiều partition.

### MS3-M1-T02 — CLI/orchestration matching

- Thêm commands `label-validate`, `build-features`, `train`, `evaluate`, `predict`, `export-member-dataset`.
- Capture seed, feature config, model params, package versions, input hashes và model artifact hash.
- Enforce train/validation/test lifecycle; test labels không được dùng trong fitting/tuning.
- Tạo predictions cho đúng matching pools và top-5 candidate contract.

### MS3-M1-T03 — Sáu-table final integration

- Nối outputs M1/M2/M3 thành six-table export; kiểm tra cross-table keys trước partition per member.
- `predictions` chỉ có rows cho train/valid/test publications; `partition` đúng manifest.
- Cùng M4 chạy schema, leakage, coverage và deterministic rerun tests.
- Không publish dataset nếu còn critical integrity failure.

### MS3-M1-T04 — Personal range/Hugging Face của Member 1

- Xác nhận bốn range values, expanded IDs và ownership manifest của Member 1.
- Tự manual-label quota cá nhân; tham gia reviewer chéo labels.
- Filter sáu tables theo citing/publication `arxiv_id` của range cá nhân, không lẫn rows member khác.
- Tạo sharded Parquet + dataset card, upload public dưới tài khoản cá nhân, test viewer/streaming/incognito và tự nộp Moodle link.

### MS3-M1-T05 — Final release và submission coordination

- Tạo release manifest liên kết code SHA, Book URL, five range checksums, split manifest, model hash, five HF URLs và poster checksum.
- Cùng M5 audit code repo, Book M1+M2, poster one-slide A2 portrait và tên `<group_id>.pptx`.
- Đại diện nhóm nộp đúng group artifacts; nhắc từng member tự nộp HF link cá nhân.
- Lưu submission receipt nội bộ và không đổi Book URL.
