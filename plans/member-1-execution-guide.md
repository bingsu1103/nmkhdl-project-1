# Member 1 Execution Guide — Ngô Gia An

Tài liệu này là hướng dẫn thực hiện từ A đến Z cho Member 1. Nó chuyển các yêu cầu trong `member-1-assignment.md` thành thứ tự thao tác cụ thể. Khi có khác biệt, đề bài trong `instructions/` và contract đã được nhóm duyệt luôn có ưu tiên cao hơn.

## 1. Bạn cần cung cấp gì trước khi bắt đầu?

### 1.1. Bắt buộc để chạy dữ liệu thật

Gửi bốn giá trị trên dòng của Ngô Gia An trong sheet đăng ký:

```text
start_month = ?
start_id    = ?
end_month   = ?
end_id      = ?
```

Tốt nhất gửi ảnh chụp nguyên dòng, gồm header và giá trị, để không mất số `0` ở đầu.

Để chạy toàn nhóm, cần thêm bốn dòng tương tự của Member 2–5. Nếu hiện chỉ có range Member 1, vẫn có thể:

- Xây dựng và test pipeline.
- Chạy pilot trên range Member 1 sau khi xác nhận cách expand.
- Chưa được tuyên bố coverage toàn nhóm hoặc chạy final group dataset.

Ngoài bốn giá trị, cần xác nhận nếu Lab có ghi chú về:

- Hai đầu range có inclusive hay không.
- `start_id`/`end_id` có bao nhiêu chữ số và có giữ zero-padding không.
- Range có thể đi qua nhiều tháng hay không.
- Có ID bị khuyết trong khoảng hay không và phải xử lý ra sao.

Không tự suy đoán các quy tắc này.

### 1.2. Cần trước khi lập lịch và nộp bài

- ID nhóm để đặt tên poster `<group_id>.pptx`.
- Deadline chính xác của Jupyter Book, GitHub repository, Hugging Face dataset và Poster.
- Ngôn ngữ chính thức của chương trình: tiếng Việt hay tiếng Anh.
- Họ tên, MSSV và mapping Member 2–5.
- GitHub username tương ứng Member 2–5 để gắn reviewer/owner chính xác.
- Hugging Face username của từng người, có thể cung cấp gần Milestone 3.

### 1.3. Không gửi cho Codex hoặc commit vào Git

- GitHub token.
- Hugging Face token.
- Semantic Scholar API key.
- Mật khẩu hoặc mã OTP.

Các secret về sau chỉ đặt qua environment variables, GitHub Secrets, Colab Secrets hoặc Hugging Face secrets.

## 2. Hiểu đúng vai trò Member 1

Ngô Gia An không phải người viết toàn bộ pipeline. Member 1 chịu trách nhiệm:

1. Nhận và kiểm tra ranges.
2. Discovery metadata arXiv và phát hiện đầy đủ versions.
3. Định nghĩa CLI/config/contracts chung.
4. Nối module của Member 2–4 thành pipeline có resume và audit trail.
5. Viết README để người khác tái chạy được.
6. Điều phối integration/release gates.
7. Vẫn hoàn thành quota cá nhân của Milestone 3 và upload dataset cá nhân.

Không sửa trực tiếp file do thành viên khác sở hữu. Nếu contract không khớp, mở issue và để owner sửa trên nhánh của họ.

## 3. Quy trình Git bắt buộc

### 3.1. Bắt đầu một phiên làm việc

```bash
git switch main
git pull --ff-only origin main
git switch member-1/discovery-orchestration
git merge main
git status
```

Kết quả mong đợi:

- Đang ở `member-1/discovery-orchestration`.
- Branch đã nhận thay đổi mới nhất từ `main`.
- Working tree sạch trước khi code.

Không dùng `git push --force`, không commit trực tiếp vào `main`, không checkout rồi sửa branch người khác.

### 3.2. Mỗi task là một chu kỳ nhỏ

```text
chọn task ID
→ tạo/sửa code và tests
→ chạy test tập trung
→ chạy toàn test suite
→ git diff --check
→ commit nhỏ
→ push branch
→ mở Pull Request
→ review/CI
→ merge vào main
```

Commit message đề xuất:

```text
feat(discovery): validate assigned ranges
feat(arxiv): resolve paper metadata and versions
feat(cli): add discovery command
test(pipeline): cover resume after interruption
docs(readme): document milestone 1 workflow
```

## 4. Cấu trúc Member 1 cần tạo

```text
src/
├── __init__.py
├── config.py
├── ids.py
├── arxiv_client.py
├── version_resolver.py
├── cli.py
└── pipeline.py
tests/
├── fixtures/
│   ├── ranges/
│   ├── arxiv_api/
│   └── pipeline/
├── test_ids.py
├── test_arxiv_client.py
├── test_version_resolver.py
├── test_cli.py
└── test_pipeline.py
requirements.txt
README.md
```

Working data thật nằm ngoài repository, ví dụ:

```text
/content/arxiv-data/       # Colab
../arxiv-data/             # local, bên ngoài repo
```

Không đặt corpus thật trong `src/`, `tests/fixtures/` hoặc `book/`. Fixtures chỉ là dữ liệu nhỏ, synthetic hoặc response đã rút gọn và không chứa secret.

## 5. Milestone 1 — thực hiện từ A đến Z

## 5.1. Bước A — Chốt contracts trước khi code

Tạo issue/decision record cho các contract sau:

- `AssignedRange`: member ID và bốn giá trị range gốc.
- `OwnedPaper`: canonical arXiv ID và member owner.
- `PaperMetadata`: fields cần cho bảng `papers`.
- `VersionTask`: base ID, versioned ID và expected version number.
- `StageStatus`: pending/running/success/no-source/permanent-failure/retryable-failure.
- `RunManifest`: run ID, timestamp UTC, git SHA, config sanitized và input checksum.

Phải thống nhất với:

- Member 2: input của downloader/extractor.
- Member 3: base arXiv ID cho Semantic Scholar.
- Member 4: metadata/schema/metrics.
- Member 5: run ID, command và evidence cho report.

Điểm dừng: chưa code network client nếu schema trung gian chưa được review.

## 5.2. Bước B — Scaffold môi trường

Chốt một Python version mà cả nhóm và Colab đều test được; đề xuất bắt đầu thử với Python 3.12, nhưng chỉ ghi là supported sau khi CI/Colab chạy thành công.

Tạo virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Dependencies tối thiểu sẽ được chốt theo implementation, thường gồm:

- `arxiv`
- `requests` hoặc standard HTTP client đã thống nhất
- `pydantic` hoặc dataclasses + explicit validation
- `pyarrow`
- `psutil`
- `pytest`
- formatter/linter/type checker nhóm chọn

Không pin version theo phỏng đoán. Cài, test clean environment rồi mới ghi constraints vào `requirements.txt`.

Điểm đạt:

- `python --version` được ghi lại.
- `python -m pytest` chạy được dù ban đầu chưa có tests.
- `.venv/` không xuất hiện trong `git status`.

## 5.3. Bước C — Viết `ids.py` và range validation

Input dự kiến:

```csv
member_id,start_month,start_id,end_month,end_id
member-1,....,....,....,....
member-2,....,....,....,....
member-3,....,....,....,....
member-4,....,....,....,....
member-5,....,....,....,....
```

`ids.py` cần:

1. Đọc CSV không làm mất zero-padding.
2. Kiểm tra đủ columns.
3. Kiểm tra đúng năm member IDs và không trùng.
4. Kiểm tra month/id theo convention Lab đã xác nhận.
5. Kiểm tra start không lớn hơn end.
6. Phát hiện overlap giữa member ranges.
7. Expand deterministic thành danh sách candidate arXiv IDs.
8. Gắn `member_id` cho từng ID.
9. Tính SHA-256 input và expanded output.
10. Ghi `expanded_ids.csv`/manifest ngoài Git.

Tests bắt buộc:

- Thiếu column.
- Member bị lặp hoặc thiếu.
- Month malformed.
- Zero-padding được giữ.
- Start/end đảo ngược.
- Range một tháng và nhiều tháng.
- Hai member overlap.
- Cùng input tạo output/checksum giống nhau.

Lưu ý: nếu chưa có convention chính thức, test phải chứng minh chương trình fail với thông báo “range convention not configured”, không tự chọn inclusive/exclusive.

Điểm đạt: toàn bộ validation xảy ra trước request Internet.

## 5.4. Bước D — Viết `config.py`

Config tối thiểu:

- `ids_file`
- `data_dir`
- arXiv request delay, timeout và max attempts
- Semantic Scholar delay/timeout/max attempts
- descriptive User-Agent
- log level
- resume flag
- optional environment variable name cho API key

Quy tắc:

- Không có secret trong object được log.
- Không hard-code absolute path máy cá nhân.
- `data_dir` không nằm trong tracked repository; nếu nằm trong repo thì fail hoặc cảnh báo nghiêm trọng.
- Default phải an toàn và tuân thủ pacing đề bài.

Tests: invalid timeout, negative attempts, data dir trong repo, missing User-Agent và secret redaction.

## 5.5. Bước E — Viết `arxiv_client.py`

Trách nhiệm:

1. Nhận base arXiv IDs đã validate.
2. Query targeted discovery bằng `id_list`/modern client pattern.
3. Một connection/worker cho arXiv và cách tối thiểu 3 giây giữa request liên tiếp.
4. Có connect/read timeout.
5. Retry hữu hạn cho network, 429 và 5xx với backoff/jitter.
6. Không retry vô hạn cho malformed ID hoặc permanent 4xx.
7. Map raw response sang `PaperMetadata`.
8. Cache raw response ngoài Git để audit/resume.
9. Phân biệt success/not-found/transient/permanent/malformed.

Fields bảng `papers` phải có đường đi rõ:

- `arxiv_id`
- `title`
- `authors` dưới dạng ordered list
- `submission_date`
- `revised_dates`
- nullable `venue`

Tests không gọi Internet thật. Dùng mocked responses cho:

- 200 valid.
- Empty/not found.
- 429 + Retry-After nếu có.
- 500 rồi success.
- Timeout.
- Malformed response.
- Metadata null/Unicode/multiple authors.

Chỉ sau khi mocked tests pass mới chạy một pilot request hợp lệ.

## 5.6. Bước F — Viết `version_resolver.py`

Input: canonical base ID + latest versioned ID từ discovery.

Ví dụ:

```text
latest = 2310.12345v4
tasks  = 2310.12345v1, v2, v3, v4
```

Mỗi `VersionTask` phải có:

- owner member ID
- base arXiv ID
- versioned arXiv ID
- integer version
- expected status ban đầu
- run/input provenance

Tests:

- Paper một version.
- Paper nhiều version.
- Old-style arXiv ID.
- Latest ID thiếu suffix.
- Base mismatch.
- Suffix zero/negative/malformed.
- Duplicate task prevention.

Không download ở module này. Nó chỉ tạo deterministic work queue cho Member 2.

## 5.7. Bước G — Định nghĩa handoff cho Members 2–4

Với Member 2, bàn giao:

```text
base_arxiv_id
versioned_arxiv_id
version
member_id
data_dir/output location
request policy
run_id
```

Với Member 3:

```text
base_arxiv_id
member_id
paper metadata/provenance
run_id
```

Với Member 4:

```text
paper metadata rows
expected publication/version counts
stage status events
input checksums
```

Viết contract tests trước khi module thật của họ merge. Trong lúc chờ, dùng fake adapters có cùng interface.

## 5.8. Bước H — Viết `cli.py`

Commands tối thiểu M1:

```text
discover
crawl-sources
crawl-references
build-tables
validate
benchmark
run-all
```

Ví dụ UX mục tiêu:

```bash
python -m src.cli discover \
  --ranges-file /path/to/assigned_ranges.csv \
  --data-dir /path/outside/repo/arxiv-data
```

CLI phải:

- Có `--help` rõ ràng.
- Validate config trước network.
- Không in API key.
- Có exit code khác nhau cho config error, partial failure và validation failure.
- Cho phép chọn `--member member-1`, `--paper ID` hoặc full group khi cần.
- `run-all` dùng đúng các commands/stages, không có logic riêng làm lệch kết quả.

Tests gọi CLI bằng fixture/fake adapters, không phụ thuộc Internet.

## 5.9. Bước I — Viết `pipeline.py`

Pipeline state machine đề xuất:

```text
pending → running → success
                  ↘ retryable_failure
                  ↘ permanent_failure
                  ↘ no_source
```

Yêu cầu:

- Tạo run ID và UTC timestamps.
- Ghi git SHA, package versions, sanitized config và input checksums.
- Atomic write: file tạm rồi rename khi hoàn tất.
- Checkpoint theo publication/version.
- `--resume` không lặp lại stage success khi input/config/code schema không đổi.
- Nếu checksum/config đổi, không reuse nhầm output cũ.
- Continue các paper khác khi một paper lỗi.
- Cuối run trả non-zero nếu còn pending/permanent critical failure.
- Graceful interrupt giữ checkpoint.
- Structured JSONL events cho Member 4; không yêu cầu parse log text.

Integration tests:

- 2–3 synthetic papers.
- Một paper nhiều versions.
- Một paper no source.
- Một transient failure rồi success.
- Crash giữa run rồi resume.
- Rerun không nhân đôi records.

## 5.10. Bước J — README và reproducibility

README phải cho người mới làm được mà không hỏi miệng:

1. Supported Python version.
2. Tạo environment/cài dependencies.
3. Cấu hình environment variables.
4. Chuẩn bị range CSV.
5. Chạy từng command.
6. Chạy `run-all`.
7. Cấu trúc output.
8. Resume sau lỗi.
9. Chạy tests.
10. Chạy trên Colab CPU-only.
11. Troubleshooting 403/429/timeout/no source.
12. Quy định không commit data/secrets.

Nhờ một thành viên khác clone mới và thực hiện đúng README. Nếu họ cần hướng dẫn miệng, README chưa đạt.

## 5.11. Bước K — Governance và CI

Tạo:

- Pull Request template: Requirement IDs, commands, test evidence, data/secret checklist.
- Issue template cho bug/contract change.
- CI chạy lint/type/test và data-leak guard.
- Branch protection/ruleset cho `main` nếu GitHub plan cho phép.

PR chỉ merge khi:

- Diff đúng scope.
- Tests pass.
- Không có data/secret.
- Interface docs được cập nhật.
- Reviewer ngoài tác giả approve theo rule nhóm.

## 5.12. Bước L — Pilot và full run M1

Chỉ làm khi có range thật và các adapters cần thiết đã merge.

Pilot từ assigned range cần đại diện:

- Paper một version.
- Paper nhiều versions.
- Missing/no-source case nếu có.
- Ít/nhiều references.
- Archive/file layout khác thường.

Pilot checks:

- Expected versions = terminal statuses.
- Source output chỉ `.tex`/`.bib`.
- TeX commands về figures còn nguyên.
- Raw S2 references được giữ local; published references chỉ giữ valid arXiv refs.
- Rerun/resume không tải/ghi trùng.

Sau pilot mới chạy full union năm ranges. Không sửa output bằng tay; sửa code rồi rerun.

## 5.13. Bước M — Benchmark/report handoff M1

Cùng Member 4 chạy Colab CPU-only và cung cấp cho Member 5:

- Run ID và exact git SHA.
- Input checksums/range counts.
- Paper/version success/failure counts.
- Size trước/sau lọc.
- Reference counts/coverage.
- Discovery/end-to-end/per-paper timing.
- Peak/average RAM.
- Max/final disk size.
- Exact commands để tái tạo.

Không nhập số thủ công vào report nếu số có thể sinh từ `summary.json`.

## 6. Milestone 2 — phần Member 1 từ A đến Z

Member 1 không viết hierarchy parser/BibTeX internals. Bạn làm integration.

### 6.1. Khóa contract M1 → M2

Mỗi expected version phải có một trong:

- Source success + eligible file manifest.
- Explicit empty/no-source.
- Explicit failure chưa giải quyết.

Parser input phải có relative paths, checksums, encoding hints, base/version IDs, member owner và run provenance.

Viết reconciliation test:

```text
expected M1 versions
= parseable M2 versions
+ empty M2 versions
+ explicit unresolved failures
```

Không được có version biến mất im lặng.

### 6.2. Mở rộng CLI/orchestrator

Thêm:

```text
parse
standardize
build-parsing-tables
validate-parsing
benchmark-parsing
```

Mỗi stage có checkpoint/resume riêng. Cho phép chạy một member, một paper hoặc toàn nhóm bằng cùng implementation.

### 6.3. Tích hợp module Member 2–4

- Member 2: compilation graph + hierarchy tree.
- Member 3: normalization + BibTeX + dedup/citation aliases.
- Member 4: three schemas + tree/dedup/coverage validation.

Viết cross-module fixture cho paper hai versions, shared cleaned sentence và changed parent. Kết quả phải deterministic và parent edges hợp lệ.

### 6.4. Reproducibility/release M2

- Cập nhật README commands/output/recovery.
- Fresh clone trên CPU-only.
- Full parse union ranges.
- Reconcile all publications/versions.
- Chỉ tag/release khi schemas, tree integrity, dedup, benchmark và Jupyter Book M2 pass.
- Xác nhận Book M1+M2 vẫn ở cùng URL GitHub Pages đã nộp.

## 7. Milestone 3 — phần Member 1 từ A đến Z

### 7.1. Labeling governance

Cùng Member 4 chốt guideline trước khi label:

- Candidate chỉ thuộc cùng publication.
- Một true match hoặc no-match.
- Ambiguous cases có notes/adjudication.
- Không dùng final test predictions để sửa ground truth.

Nhóm 5 người cần tối thiểu:

- 25 manual publications.
- 500 manually labeled entries.
- Mỗi người >=5 publications, mỗi publication >=20 entries, tổng mỗi người >=100 entries.
- Automatic pool >=10% remaining publications và >=10 publications.
- Validation: 5 manual + 5 automatic publications.
- Test: 5 manual + 5 automatic publications.

Ngô Gia An phải tự hoàn thành quota cá nhân, không chỉ điều phối.

### 7.2. Split và chống leakage

- Split theo publication, không theo entry/pair.
- Một publication chỉ nằm ở một partition.
- Duplicate versions/elements của publication ở cùng partition.
- Preprocessing/features fit trên train only.
- Model/threshold chọn bằng validation.
- Test chỉ dùng đánh giá cuối sau khi khóa config.

Lưu split manifest, seed và hash trước khi train final.

### 7.3. Mở rộng CLI/orchestrator M3

Thêm:

```text
label-validate
build-features
train
evaluate
predict
export-member-dataset
```

Run manifest cần feature config, model params, seeds, input hashes, package versions và model artifact hash.

### 7.4. Tích hợp sáu bảng

Final tables:

```text
papers
references
elements
hierarchy
bibtex
predictions
```

Cross-check:

- Every citing/prediction arXiv ID thuộc đúng paper scope.
- Every hierarchy node/parent tồn tại.
- Every prediction citation key tồn tại trong `bibtex`.
- Every candidate ID tồn tại trong `references` của cùng publication.
- `partition` khớp split manifest.
- Predictions chỉ có rows cho matching pools.

Không publish nếu còn critical integrity failure.

### 7.5. Personal Hugging Face dataset của Ngô Gia An

1. Filter sáu tables theo `arxiv_id` thuộc range Member 1.
2. Chạy schema, range-isolation, coverage và cross-key validation.
3. Shard Parquet theo cấu trúc đề.
4. Tạo dataset card với một config mỗi table.
5. Upload public dưới tài khoản HF cá nhân.
6. Test dataset viewer/streaming và incognito.
7. Tự dán link vào cổng Moodle cá nhân.

Không upload raw API cache, labels nội bộ, logs, archives hoặc secrets ngoài six-table schema.

### 7.6. Final release/poster coordination

Release manifest cuối phải liên kết:

- Code commit/tag.
- Stable Book URL.
- Five range/input checksums.
- Split manifest hash.
- Model artifact/config hash.
- Five personal HF URLs.
- Poster checksum.

Audit bốn cổng nộp:

- Jupyter Book: một GitHub Pages URL chứa M1+M2.
- GitHub repository: một public code repo tích lũy.
- Hugging Face: mỗi member tự nộp personal dataset URL.
- Poster: đại diện nhóm upload một `<group_id>.pptx`, one-slide portrait A2.

## 8. Thứ tự PR đề xuất cho Member 1

Không gom toàn bộ thành một PR khổng lồ.

### PR 1 — Contracts và scaffold

- Data models/interfaces.
- Package/test structure.
- Config base.
- CI skeleton nếu chưa có.

### PR 2 — Assigned range validation

- `ids.py`.
- Range fixtures/tests.
- Checksum/expanded manifest.

### PR 3 — arXiv discovery/version resolver

- `arxiv_client.py`.
- `version_resolver.py`.
- Mocked HTTP tests.

### PR 4 — CLI

- `discover` và common config/options.
- CLI tests/help/docs.

### PR 5 — Orchestrator/resume

- `pipeline.py`.
- Fake adapters.
- Crash/restart/idempotency integration tests.

### PR 6 — README/governance

- Full setup/run/recovery guide.
- Templates/rules/CI/data-leak guard.
- Fresh-clone evidence.

Các PR tích hợp Member 2–4 chỉ mở sau khi contracts tương ứng đã merge.

## 9. Checklist hằng ngày

Trước khi code:

- [ ] Đang ở branch Member 1.
- [ ] Đã merge `main` mới nhất vào branch của mình.
- [ ] Working tree sạch.
- [ ] Task ID và acceptance criteria rõ.

Trước commit:

- [ ] Focused tests pass.
- [ ] Full tests pass.
- [ ] `git diff --check` pass.
- [ ] Không có data/secret/local path.
- [ ] README/interface docs được cập nhật nếu cần.

Trước PR:

- [ ] PR nhỏ, đúng scope.
- [ ] Có Requirement/task IDs.
- [ ] Có commands và test output tóm tắt.
- [ ] Có risk/rollback nếu đổi contract.
- [ ] Chỉ request reviewer đúng owner.

## 10. Khi nào bạn có thể bắt đầu ngay?

Ngay bây giờ, chưa cần range thật, bạn có thể làm:

1. PR 1: contracts/scaffold.
2. `ids.py` với synthetic fixtures và convention configurable.
3. Mocked arXiv client tests.
4. Version resolver.
5. CLI/fake pipeline.
6. README khung và PR templates.

Bạn chỉ cần range thật trước khi:

- Pilot discovery/crawl.
- Benchmark corpus thật.
- Tính statistics/report thật.
- Full M1 run và downstream M2/M3 dataset.

## 11. Definition of Done cá nhân

Member 1 hoàn tất khi:

- Range input được validate, owned, expanded và checksum reproducibly.
- Mọi resolved publication có deterministic version tasks hoặc explicit failure.
- CLI/orchestrator chạy end-to-end, resume được và emit structured evidence.
- Contracts với Members 2–4 có tests.
- README được người khác fresh-clone/tái chạy thành công.
- M1/M2/M3 release gates được điều phối trung thực.
- Quota labeling cá nhân hoàn tất.
- Personal six-table HF dataset public và đã nộp.
- Group Book/repo/poster deliverables được audit đúng cổng.

