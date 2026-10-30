# Đồ án arXiv — Kế hoạch tổng thể Milestone 1–3

> Phạm vi: toàn bộ đồ án Nhập môn Khoa học Dữ liệu, dựa trên `instructions/index.md`, `instructions/crawling.md`, `instructions/parsing.md`, `instructions/matching.md` và thông tin các cổng nộp Moodle do sinh viên cung cấp.
>
> Trạng thái tại ngày 24/10/2026: **Có thể bắt đầu thiết kế, viết mã khung và kiểm thử giả lập; chưa thể chạy dữ liệu chính thức** vì mới có tên bốn cột range nhưng chưa có giá trị range của năm thành viên.

## 0. Xác định đúng phạm vi đồ án

Đây là **một đồ án arXiv duy nhất gồm ba milestone phụ thuộc tuần tự**, không phải ba đồ án độc lập:

1. **Milestone 1 — Crawling:** lấy paper metadata, mọi version source `.tex`/`.bib` và Semantic Scholar references.
2. **Milestone 2 — Parsing:** dùng trực tiếp corpus M1 để dựng hierarchy, normalize/deduplicate và tạo `elements`, `hierarchy`, `bibtex`.
3. **Milestone 3 — Matching:** dùng `bibtex` của M2 và `references` của M1 để label, tạo feature, train/evaluate reference matcher bằng MRR@5 và tạo `predictions`.

Bốn cổng Moodle là bốn deliverable/checkpoint của cùng đồ án:

- Jupyter Book: nhóm nộp một URL GitHub Pages ổn định, chứa report M1 và M2.
- GitHub repository: nhóm nộp một repository mã nguồn tích lũy của toàn pipeline, bao gồm cả source dùng viết Jupyter Book.
- Hugging Face Dataset: **mỗi thành viên** nộp dataset public cho phần range cá nhân của mình.
- Poster: đại diện nhóm nộp `<group_id>.pptx`, một trang A2 dọc; đây là deliverable cuối của M3.

Vì thế mọi quyết định ở M1 phải bảo toàn dữ liệu cần cho M2/M3; không được tối ưu riêng crawling rồi làm mất compilation path, version lineage, raw references hoặc provenance.

## 1. Kết luận kiểm tra đầu vào

### 1.1. Đã có

- Mô tả logistics chung của cả ba milestone.
- Yêu cầu chi tiết của cả ba milestone: crawling, parsing/standardization, reference matching, benchmark, Jupyter Book, Hugging Face và poster.
- Schema bắt buộc cho sáu bảng `papers`, `references`, `elements`, `hierarchy`, `bibtex`, `predictions` ở lần công bố dataset cuối cùng.
- Cấu trúc tối thiểu của repository mã nguồn.
- Năm tiêu chí chấm điểm.

### 1.2. Cần người dùng/nhóm cung cấp hoặc xác nhận

| Mức độ | Đầu vào còn thiếu | Vì sao cần | Có thể làm gì trước khi có |
|---|---|---|---|
| **BLOCKER** | Năm dòng giá trị `start_month`, `start_id`, `end_month`, `end_id`, một dòng cho mỗi thành viên | Bốn trường mã hóa arXiv range cá nhân; union năm range là corpus nhóm sau khi xác nhận quy ước biên | Viết pipeline, fixture và test với ID mẫu; không công bố kết quả thật |
| **BLOCKER trước khi nộp** | Ngày/giờ deadline, múi giờ và link Moodle | Chốt lịch freeze, review, submit; đề bài chỉ nói không nhận trễ | Làm theo lịch tương đối T-14, T-7, T-3, T-1 |
| **BLOCKER trước khi viết report** | Ngôn ngữ chính thức của chương trình | Đề bài yêu cầu mọi submission dùng official language | Viết mã/comment tiếng Anh; giữ report ở trạng thái dàn ý đến khi xác nhận |
| **Cần xác nhận một phần** | Member 1 là **Ngô Gia An**, Member 3 là **Nguyễn Đức Quang**; vẫn cần tên/ID sinh viên và GitHub username của Member 2, 4, 5 | Gán owner, reviewer và ghi đóng góp trung thực | Giữ nhãn Member 2, 4, 5 tạm thời đến khi có thông tin |
| **Cần xác nhận** | Tên group, tên hai public repository và GitHub organization/account | Cần tạo URL nộp cho code repo và Jupyter Book repo | Dùng tên đề xuất trong mục 4 |
| **Cần xác nhận** | Quy ước chính xác để expand range: tháng dạng `YYMM`, `start_id/end_id` có zero-padding bao nhiêu chữ số và hai đầu có inclusive không | Ảnh chỉ cho thấy header, chưa có ví dụ giá trị; không nên tự suy đoán ID | Chuẩn bị validator và chờ một dòng range thật để xác minh |
| **Cần xác nhận** | Hướng dẫn bổ sung từ Lab Instructors về Hugging Face/Colab và naming dataset cá nhân | Moodle yêu cầu mỗi thành viên upload phần dữ liệu của mình | Thiết kế export Parquet tương thích; chưa publish |
| Tùy chọn | Semantic Scholar API key | Không bắt buộc, nhưng ổn định hơn pool anonymous | Hỗ trợ cả có/không key qua biến môi trường |

Không yêu cầu người dùng gửi mật khẩu, GitHub token, API key hoặc secret vào repository/chat. Secret chỉ được đặt qua biến môi trường hoặc GitHub/Colab Secrets.

### 1.3. Danh sách thành viên

| Vai trò | Họ tên | GitHub | Trạng thái |
|---|---|---|---|
| Member 1 | **Ngô Gia An** | Chưa cung cấp | Đã xác nhận — technical integrator, discovery/versioning/orchestration |
| Member 2 | Chưa cung cấp | Chưa cung cấp | Chờ cập nhật |
| Member 3 | **Nguyễn Đức Quang** | `ducquang2` | Đã xác nhận — Semantic Scholar, BibTeX conversion/reference dedup |
| Member 4 | Chưa cung cấp | Chưa cung cấp | Chờ cập nhật |
| Member 5 | Chưa cung cấp | Chưa cung cấp | Chờ cập nhật |

### 1.4. Format cần gửi — không cần liệt kê từng arXiv ID

Chỉ cần gửi năm dòng theo mẫu sau; pipeline sẽ expand programmatically:

```text
member_id,start_month,start_id,end_month,end_id
member-1,YYMM,NNNNN,YYMM,NNNNN
member-2,YYMM,NNNNN,YYMM,NNNNN
member-3,YYMM,NNNNN,YYMM,NNNNN
member-4,YYMM,NNNNN,YYMM,NNNNN
member-5,YYMM,NNNNN,YYMM,NNNNN
```

Range manifest phải lưu `member_id` và bốn giá trị gốc, checksum, thời điểm import và danh sách ID đã expand. Cách zero-pad, xử lý range đi qua nhiều tháng và việc hai đầu có được tính hay không phải theo ví dụ/quy ước Lab xác nhận; không tự suy đoán từ tên cột.

## 2. Requirement traceability — điều kiện đạt điểm tối đa

| ID | Yêu cầu gốc | Deliverable / bằng chứng | Owner chính | Cách kiểm chứng |
|---|---|---|---|---|
| R01 | Chỉ crawl các ID trong range được giao | Input loader + manifest có checksum | M1 | So sánh tập ID đầu vào, accepted, failed, skipped |
| R02 | Phát hiện đầy đủ mọi version | Version resolver từ latest suffix và kiểm tra từng `v1..vN` | M1 | Test paper 1 version/nhiều version; coverage report |
| R03 | Tải riêng từng version từ versioned `/src/` | Downloader có retry, pacing, User-Agent | M2 | Log URL/status/checksum cho từng version |
| R04 | Chỉ giữ `.tex` và `.bib`; không đưa figure binary vào corpus | Safe extractor allowlist theo extension | M2 | Test archive có image/style/path traversal; file inventory |
| R05 | Giữ nguyên lệnh LaTeX về figure trong `.tex` | Không sửa nội dung file; checksum raw member/extracted file | M2 | Regression test chứa `figure` và `\includegraphics` |
| R06 | Phiên bản không có TeX/Bib vẫn có empty record, không bị drop | Status record cho mọi paper/version | M2 + M4 | Reconciliation: requested versions = terminal statuses |
| R07 | Metadata paper: title, authors, dates, venue | Normalizer và `papers` table đúng schema | M1 + M4 | Schema/null/type/uniqueness tests |
| R08 | Crawl reference metadata qua Semantic Scholar cho mỗi publication | S2 client có throttle, retry, cache/checkpoint | M3 | Request audit + success/failure counters |
| R09 | Giữ toàn bộ crawled references cục bộ | Local raw reference JSONL/Parquet ngoài Git | M3 | Count raw references và provenance |
| R10 | Bảng final `references` chỉ chứa ref có arXiv ID | Eligibility filter, hỗ trợ old-style ID | M3 + M4 | Tests old/new/missing IDs; FK check |
| R11 | Hai bảng đúng schema đề bài | `papers` và `references` sharded Parquet | M4 | PyArrow schema contract + dataset reload |
| R12 | Không nộp data ở M1, không commit data | `.gitignore`, pre-commit/CI size & extension guard | M4 | `git ls-files` audit trước PR/release |
| R13 | Code sạch, dễ đọc, chạy được | Modules, type hints, docstrings, tests, CLI | Tất cả; M1 tích hợp | Fresh-clone run trên CPU |
| R14 | `requirements.txt` tái tạo môi trường | Pinned/compatible dependencies + Python version | M1 | Tạo venv sạch và chạy test |
| R15 | README hướng dẫn setup/config/run cụ thể | README code repo | M1 | Người khác chạy chỉ từ README |
| R16 | Một public code repo, lịch sử tích lũy | PRs nhỏ, review, main protected | M1 | GitHub audit và public access check |
| R17 | Jupyter Book ở public repo riêng, GitHub Pages | Book build + deploy workflow | M5 | Mở public URL trên cửa sổ ẩn danh |
| R18 | Figure/table sinh trong lúc build, không dùng screenshot tĩnh | Notebook/script nguồn cho mọi chart/table | M5 | Clean build tạo lại artifacts |
| R19 | Report mô tả quy trình, tool/library | Chương Methodology | M5, reviewers M1–M4 | Trace nội dung về code/commit thật |
| R20 | Thống kê crawl bắt buộc | Success count/rate, size trước/sau, ref averages | M4 + M5 | Recompute từ metrics files |
| R21 | Benchmark runtime bắt buộc | Total/paper average/discovery wall time | M4 + M5 | Colab CPU-only benchmark log |
| R22 | Benchmark memory/storage bắt buộc | peak/avg RAM, max disk, final size | M4 + M5 | psutil sampling + `du` snapshots |
| R23 | Benchmark end-to-end nếu hệ thống nhiều chương trình | Một lệnh orchestrate toàn pipeline | M1 + M4 | Timed clean run from IDs to outputs |
| R24 | Citation đầy đủ, không đạo văn | Bibliography + in-text citations | M5 | Link/citation audit; không sao chép vô nguồn |
| R25 | Nộp hai public links qua Moodle, đúng hạn | Submission checklist và bằng chứng truy cập | M1 + M5 | Incognito test + receipt/screenshot nội bộ |

## 3. Kiến trúc pipeline đề xuất

```text
assigned IDs
    -> validate/canonicalize IDs
    -> resolve metadata + latest version
    -> enumerate v1..vN
    -> download each versioned source archive
    -> safe extract only .tex/.bib
    -> write per-version status + file metrics
    -> crawl Semantic Scholar references per publication
    -> retain complete local reference records
    -> normalize + validate papers/references tables
    -> follow LaTeX compilation path for every version
    -> parse hierarchy + normalize/deduplicate content and BibTeX
    -> build elements/hierarchy/bibtex tables
    -> manually/automatically label publication-scoped matches
    -> feature engineering + model + MRR@5 evaluation
    -> build predictions table
    -> calculate QA and benchmark metrics per member and group
    -> generate M1/M2 report figures/tables during Jupyter Book build
    -> export six-table personal Hugging Face dataset for each member
    -> generate final A2 portrait poster
```

Nguyên tắc thiết kế:

- Idempotent: chạy lại không tải/ghi đè vô lý; kiểm tra checksum và trạng thái hoàn tất.
- Resumable: lỗi mạng hoặc 429 không làm mất tiến độ; checkpoint theo paper/version.
- Auditable: mọi record có source endpoint, timestamp UTC, status/error code, attempt count.
- Polite crawling: arXiv chạy một kết nối và cách ít nhất 3 giây giữa các request liên tiếp; Semantic Scholar không vượt 1 request/giây và 100 request/5 phút khi anonymous.
- Không chỉnh nội dung `.tex`/`.bib`; chỉ lọc loại file khi extract.
- Tách working data khỏi code repo; không commit archive, corpus, logs lớn hay secrets.
- Không dùng OAI-PMH/Kaggle để thay thế assigned-ID flow. Có thể mô tả như toolbox trong report, nhưng graded implementation phải resolve đúng các ID được giao.

## 4. Hai repository và cấu trúc thư mục

Đề bài **có yêu cầu cấu trúc tối thiểu cho code repo** và trang đề chính thức mô tả Jupyter Book trên repository riêng. Thông tin Moodle bổ sung rằng code repo nhóm phải chứa cả file có nội dung dùng viết Jupyter Book, dù repo compile Pages không nhất thiết là repo đó. Vì vậy `book/` trong code repo là nguồn report được version-control, còn repository Pages bên dưới là bản deploy/sync. Không chỉnh report độc lập ở hai nơi gây drift.

### 4.1. Repository 1 — mã nguồn công khai

Tên đề xuất: `<group>-arxiv-pipeline`

```text
<group>-arxiv-pipeline/
├── README.md
├── .gitignore
├── src/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── ids.py
│   ├── arxiv_client.py
│   ├── version_resolver.py
│   ├── downloader.py
│   ├── extractor.py
│   ├── s2_client.py
│   ├── normalize.py
│   ├── storage.py
│   ├── validate.py
│   ├── metrics.py
│   ├── latex_graph.py
│   ├── hierarchy_parser.py
│   ├── standardize.py
│   ├── bibtex.py
│   ├── label.py
│   ├── features.py
│   ├── model.py
│   ├── evaluate.py
│   ├── export_hf.py
│   └── pipeline.py
├── tests/
│   ├── fixtures/                 # chỉ fixture nhỏ, synthetic, không phải corpus thật
│   ├── test_ids.py
│   ├── test_version_resolver.py
│   ├── test_extractor.py
│   ├── test_s2_client.py
│   ├── test_schema.py
│   ├── test_latex_graph.py
│   ├── test_hierarchy_parser.py
│   ├── test_deduplication.py
│   ├── test_features.py
│   ├── test_evaluate.py
│   └── test_pipeline.py
├── notebooks/
│   ├── colab_crawling_benchmark.ipynb
│   ├── colab_parsing_benchmark.ipynb
│   └── matching_analysis.ipynb
├── book/                       # source M1/M2 dùng để viết Jupyter Book
│   ├── _config.yml
│   ├── _toc.yml
│   ├── milestone-1/
│   └── milestone-2/
└── requirements.txt
```

Nếu giảng viên hiểu cấu trúc mẫu theo nghĩa tuyệt đối “chỉ `src/`, `README.md`, `requirements.txt`”, trước khi nộp nhóm phải hỏi Lab Instructor xem `tests/`, `.gitignore`, `notebooks/` có được giữ hay không. Không tự bỏ test/benchmark khi chưa xác nhận.

### 4.2. Working data — tuyệt đối không commit

Root do CLI nhận qua `--data-dir`, ví dụ `/content/arxiv-data` trên Colab:

```text
<data-dir>/
├── inputs/
│   ├── assigned_ranges.csv
│   └── expanded_ids.csv
├── raw/
│   ├── archives/<paper>/<version>.tar.gz
│   ├── api/arxiv/<paper>.json
│   └── api/semantic_scholar/<paper>.json
├── corpus/
│   └── <normalized-paper-id>/
│       └── <version>/
│           ├── tex/**/*.tex
│           ├── bib/**/*.bib
│           └── status.json
├── manifests/
│   ├── run.json
│   ├── versions.jsonl
│   ├── files.jsonl
│   └── references_raw.jsonl
├── processed/
│   ├── papers/part-*.parquet
│   ├── references/part-*.parquet
│   ├── elements/part-*.parquet
│   ├── hierarchy/part-*.parquet
│   ├── bibtex/part-*.parquet
│   └── predictions/part-*.parquet
├── labels/
│   ├── manual/
│   └── automatic/
├── models/
├── member-exports/
│   └── <member-id>/            # chỉ rows thuộc range cá nhân
│       ├── README.md
│       └── data/{papers,references,elements,hierarchy,bibtex,predictions}/
├── metrics/
│   ├── crawl_metrics.jsonl
│   ├── resource_samples.jsonl
│   └── summary.json
└── logs/
```

Quy ước folder paper thay dấu `.` bằng `-`; ID old-style phải normalize an toàn để không tạo đường dẫn lồng ngoài ý muốn. Mọi đường dẫn archive phải được kiểm tra chống path traversal và symlink escape.

### 4.3. Repository 2 — Jupyter Book công khai

Tên đề xuất: `<group>-arxiv-project-report`

```text
<group>-arxiv-project-report/
├── README.md
├── _config.yml
├── _toc.yml
├── requirements.txt
├── references.bib
├── milestone-1/
│   ├── index.md
│   ├── methodology.ipynb
│   ├── data-quality.ipynb
│   ├── corpus-analysis.ipynb
│   ├── performance.ipynb
│   └── limitations.md
├── milestone-2/
│   ├── index.md
│   ├── hierarchy-parsing.ipynb
│   ├── standardization.ipynb
│   ├── deduplication.ipynb
│   ├── performance.ipynb
│   └── limitations.md
└── .github/workflows/deploy-book.yml
```

Nội dung repository này phải được sync từ `book/` của code repo ở một commit xác định. Notebook đọc các file metrics/processed được tạo lại trong job build hoặc từ một artifact/sample công khai được duyệt; mọi bảng và biểu đồ phải có code sinh ra, nhãn trục, đơn vị, caption và giải thích.

Thư mục `plans/` hiện tại là tài liệu điều phối nội bộ. Nó không bắt buộc thuộc một trong hai repository nộp bài.

### 4.4. Chính xác phải nộp gì tại mục “Đồ án: Jupyter Book”

Đại diện nhóm **không upload file `.ipynb`, `.html`, `.pdf`, `.zip` hay repository source** tại mục này. Đại diện nhóm dán vào textbox Moodle **một URL GitHub Pages công khai (`github.io`) trỏ đến trang chủ của một Jupyter Book đã deploy**, ví dụ:

```text
https://<github-account-or-org>.github.io/<book-repository>/
```

Cuốn Book tại URL đó phải là **một book duy nhất chứa cả hai phần**:

- Milestone 1 — Data Crawling: implementation, corpus statistics, crawl success/failure, runtime/RAM/disk analysis và figures/tables generated during build.
- Milestone 2 — Parsing and Standardization: hierarchy parser, cleanup/normalization, BibTeX/reference/full-text deduplication, coverage/statistics/performance và figures/tables generated during build.

Trước khi nộp, mở URL trong cửa sổ ẩn danh để kiểm tra book render được, menu điều hướng mở được cả M1/M2 và không yêu cầu đăng nhập. Đây là checkpoint đốc thúc tiến độ: nhóm được tiếp tục sửa nội dung sau hạn của mục Jupyter Book đến trước hạn Poster, nhưng **không được đổi URL đã nộp**. Link GitHub repository mã nguồn được nộp ở mục “Đồ án: Repository Github”, không dùng thay cho link Pages này.

## 5. Chiến lược Git bắt buộc cho 5 thành viên

### 5.1. Nhánh độc lập

Mỗi người chỉ phát triển trên một nhánh cá nhân dài hạn của mình:

- `member-1/discovery-orchestration`
- `member-2/source-parsing`
- `member-3/references-bibtex`
- `member-4/quality-matching`
- `member-5/book-poster`

Quy tắc:

1. Không push, force-push, rebase hoặc sửa trực tiếp nhánh của người khác.
2. Không commit trực tiếp vào `main`; `main` bật branch protection.
3. Mỗi task tạo commit nhỏ trên đúng nhánh cá nhân; mở PR vào `main`.
4. PR phải có ít nhất một reviewer không phải tác giả; thay đổi contract/schema cần M1 và M4 duyệt, thay đổi số liệu/report cần M4 và M5 duyệt.
5. Khi cần cập nhật từ `main`, tác giả tự merge/rebase `main` vào **nhánh của chính mình**; không nhờ người khác sửa hộ trên branch.
6. Người review chỉ comment/approve; không checkout rồi commit vào branch tác giả.
7. File ownership ở mục 7 được tôn trọng. Nếu cần đổi file của owner khác, tạo issue mô tả contract và để owner thực hiện, hoặc thống nhất PR phối hợp có ghi rõ đồng tác giả.
8. Chỉ Member 1 (integrator) hoặc GitHub merge queue được merge PR đã đạt gate. Việc merge không đồng nghĩa chỉnh branch của người khác.
9. Không dùng `git push --force` sau khi đã mở PR, trừ khi cả nhóm phê duyệt và có backup.
10. Không commit dữ liệu thật, secret, notebook output khổng lồ, archive hoặc log chứa thông tin nhạy cảm.

### 5.2. Hai lớp trách nhiệm của mỗi thành viên

Mỗi người đồng thời có:

1. **Functional ownership:** module chung được giao trong mục 7 và file assignment cá nhân.
2. **Personal-range ownership:** chịu trách nhiệm theo dõi phần publications thuộc bốn trường range của mình qua cả M1, M2, M3 và upload một Hugging Face dataset cá nhân.

Không chia dữ liệu theo module. Ví dụ Member 2 viết parser chung nhưng vẫn phải kiểm tra đủ crawling/parsing/matching output cho range cá nhân; Member 4 viết model chung nhưng không sở hữu dữ liệu của Member 2. `member_id` chỉ nằm ở manifest/provenance và bước partition export, không tự ý thêm vào sáu published schemas nếu đề không quy định.

Checklist bắt buộc cho **từng** member range:

- Range gốc và expanded IDs đã được người sở hữu xác nhận.
- M1: mọi publication/version có status và hai bảng `papers`, `references` đúng scope.
- M2: mọi version được parse hoặc explicit empty/failure; có `elements`, `hierarchy`, `bibtex`.
- M3: người đó tự hoàn thành tối thiểu 5 manual publications, mỗi publication >=20 labeled entries, tổng >=100 entries; tham gia automatic pool và split đúng quota nhóm.
- Sáu table được lọc theo `arxiv_id` thuộc range cá nhân, schema/referential integrity pass.
- Dataset card và sharded Parquet được upload public dưới tài khoản Hugging Face cá nhân.
- Link dataset cá nhân mở được không cần đăng nhập và được chính thành viên nộp Moodle.

### 5.3. Definition of Ready cho mỗi task

- Requirement ID đã xác định.
- Input/output contract và file owner rõ ràng.
- Dependency đã merge hoặc mock/fixture đã thống nhất.
- Có test cases và acceptance criteria.

### 5.4. Definition of Done cho mỗi PR

- Code chạy trên clean environment và test mới/ảnh hưởng đều pass.
- Có type hints/docstring/comment cho logic không hiển nhiên.
- Có xử lý timeout, retry, rate limit và error path phù hợp.
- Không có data/secrets/unrelated files trong diff.
- README hoặc interface docs cập nhật khi contract đổi.
- PR mô tả Requirement IDs, cách chạy, kết quả test, rủi ro và rollback.
- Reviewer xác nhận không bịa/chỉnh tay số liệu.

## 6. Contract tích hợp dùng chung

Các owner phải thống nhất contract này trước khi code song song:

- Canonical paper key: giữ nguyên arXiv ID không version trong record; filesystem dùng dạng đã sanitize.
- Version key: base ID + `vN`; không suy đoán version bị thiếu là thành công.
- Terminal status tối thiểu: `success`, `no_tex_bib`, `not_found`, `http_error`, `invalid_archive`, `api_error`, `pending_retry`.
- Tất cả timestamp hệ thống ở UTC ISO-8601; ngày publication giữ đúng semantic của API.
- Authors luôn là ordered list of strings, không nối thành một string.
- `venue` nullable; không thay null bằng chuỗi `"Unknown"` trong dataset.
- `papers.arxiv_id` là non-null và unique theo publication.
- `references` có một row cho mỗi reference của citing paper mà `externalIds.ArXiv` tồn tại; define rõ dedup key trước khi export.
- Raw reference record không bị loại chỉ vì thiếu arXiv ID.
- Mọi request có timeout hữu hạn, User-Agent mô tả nhóm, exponential backoff có jitter, và giới hạn attempts.
- Metrics không phụ thuộc log text; ghi structured JSONL để report đọc máy được.

## 7. Phân chia ownership

| Thành viên | Phạm vi chính | File/module sở hữu dự kiến | Không tự ý sửa |
|---|---|---|---|
| M1 — Ngô Gia An | Discovery, versioning, CLI, orchestration, integration | `ids.py`, `arxiv_client.py`, `version_resolver.py`, `cli.py`, `pipeline.py`, `README.md` | Downloader/extractor, S2 internals, report |
| M2 | Source download/extraction + compilation graph + hierarchy parser | `downloader.py`, `extractor.py`, `latex_graph.py`, `hierarchy_parser.py` | Schema/export/model/report prose |
| M3 — Nguyễn Đức Quang | Semantic Scholar + BibTeX conversion/reference dedup | `s2_client.py`, `bibtex.py`, reference lineage/dedup tests | Downloader/model/report figures |
| M4 | Storage/schema/validation/metrics + labeling/model/evaluation | `storage.py`, `normalize.py`, `validate.py`, `metrics.py`, `label.py`, `features.py`, `model.py`, `evaluate.py` | API client internals/report prose |
| M5 | M1/M2 Jupyter Book + analysis + poster + deployment/submission QA | `book/`, report deploy repo, analysis notebooks, poster source | Sửa số liệu nguồn hoặc pipeline để khớp narrative |

Chi tiết từng người nằm trong `member-1-assignment.md` đến `member-5-assignment.md`.

## 8. Lộ trình Milestone 1 theo phase và dependency

### Phase 0 — Intake và governance

- Nhận đủ blocker ở mục 1.2.
- Map tên thật vào Member 1…5.
- Tạo hai public repo, branch protection, issue/PR templates.
- Chốt Python version, dependency policy, output contracts và User-Agent contact.
- Tạo risk register và decision log.

**Gate G0:** Năm assigned ranges và expanded IDs đã checksum; deadline/ngôn ngữ được xác nhận; hai repo truy cập công khai.

### Phase 1 — Contract và test foundation

- M1 tạo CLI/config/contracts và fake clients.
- M2/M3/M4 tạo unit tests độc lập dựa trên fixtures synthetic.
- M5 dựng Jupyter Book skeleton và CI build.
- Review chéo schema/status/error policy.

**Gate G1:** Clean install + unit tests + book build đều pass; chưa cần Internet.

### Phase 2 — Feature implementation

- M1: ID validation, API resolution, version enumeration.
- M2: download/version archive, safe extract, checksum, status.
- M3: S2 crawling, full raw retention, eligible-ref filter.
- M4: normalized storage, schema validation, reconciliation, metrics sampler.
- M5: report notebooks đọc fixture/metrics contract; bibliography.

**Gate G2:** Integration tests dùng mocked HTTP chứng minh success và failure paths.

### Phase 3 — Pilot crawl

- Chọn tập pilot đại diện từ **assigned IDs**: single-version, multi-version, missing source, archive lạ, nhiều/ít references.
- Chạy tốc độ đúng etiquette, kiểm tra resume/idempotency.
- So sánh thủ công một mẫu nhỏ với trang/API nguồn.
- Chốt threshold cảnh báo, không che lỗi bằng cách bỏ record.

**Gate G3:** 100% assigned pilot versions có terminal status; không có binary figure; reconciliation pass.

### Phase 4 — Full crawl và recovery

- Chạy end-to-end trên assigned range, checkpoint thường xuyên.
- Retry có giới hạn cho transient errors; tách permanent vs retryable.
- Khóa run manifest, package versions và git SHA.
- Không sửa tay outputs; mọi correction phải bằng code và rerun.

**Gate G4:** Mọi ID/version accounted for; schema pass; failure list có nguyên nhân và retry evidence.

### Phase 5 — Benchmark chuẩn Colab CPU-only

- Khởi tạo runtime sạch, ghi machine/runtime metadata.
- Chạy một lệnh end-to-end với cùng config chính thức.
- Đo discovery total, per-paper total/average, peak/average RAM, max disk, final output size.
- Lặp lại đủ để phát hiện bất thường; report rõ số lần và statistic dùng.

**Gate G5:** Metrics có machine-readable raw samples, không chỉ ảnh chụp hoặc số nhập tay.

### Phase 6 — Analysis và Jupyter Book

- Build thống kê/biểu đồ từ processed data + metrics.
- Viết methods, findings, failures, limitations và ethical/API etiquette notes.
- Link code repo + commit SHA/run ID; citation đầy đủ.
- Clean build trên CI và deploy GitHub Pages.

**Gate G6:** Clone/build sạch tái tạo bảng/figure; public URL mở được ẩn danh.

### Phase 7 — Final QA và submission

- Audit năm grading criteria theo evidence matrix.
- Fresh-clone code repo và chạy README trên Colab CPU-only.
- Audit `git ls-files`: không data, secret, archive, logs lớn.
- Freeze release tag/commit; test links ẩn danh.
- Hai người cùng kiểm tra form Moodle trước submit; lưu receipt nội bộ.

**Gate G7:** Code link + Jupyter Book link đúng; submit trước deadline; không submit dataset ở M1.

## 9. Lịch tương đối đề xuất

Do chưa có deadline, dùng ký hiệu `T` là thời điểm Moodle đóng:

| Mốc | Mục tiêu |
|---|---|
| T-21 đến T-17 | Phase 0–1 |
| T-16 đến T-12 | Phase 2 |
| T-11 đến T-9 | Pilot + sửa lỗi |
| T-8 đến T-6 | Full crawl + recovery |
| T-5 đến T-4 | Colab benchmark + analysis |
| T-3 | Content freeze; book hoàn chỉnh |
| T-2 | Independent reproduction + grading audit |
| T-1 | Link/access/submission rehearsal; chỉ sửa blocker |
| T-6 giờ | Submit chính thức, tránh sát hạn |

Nếu thời gian ngắn hơn, không bỏ requirement; giảm scope phụ như dashboard/optimization không cần thiết và ưu tiên completeness, reproducibility, truthful report.

## 10. Test matrix tối thiểu

- ID mới `YYMM.NNNNN`, ID old-style `archive/YYMMNNN`, ID có/không version, malformed ID.
- Paper một version, nhiều version, API latest suffix bất thường.
- HTTP timeout, 403, 404, 429, 5xx, truncated download, checksum mismatch.
- Gzipped tar hợp lệ, single gzip/non-tar, corrupt archive, nested dirs, duplicate filename, absolute path, `../`, symlink/hardlink escape.
- Archive có `.tex`, `.bib`, uppercase extension, image, `.sty`, `.cls`, PDF-only/no eligible file.
- `.tex` chứa `figure`, `\includegraphics`, Unicode và multiple encodings; bytes phải giữ nguyên.
- S2 result có/mất `externalIds`, old/new arXiv ID, null authors/date/title, duplicate refs, empty refs.
- Restart giữa run; rerun completed paper; concurrent invocation bị khóa hoặc xử lý an toàn.
- Schema wrong type/null/duplicate/FK violation; sharding + reload equality.
- Report build từ clean checkout; mọi figure/table tái sinh.

## 11. Metrics và công thức bắt buộc

- `paper_success_rate = successful_assigned_papers / total_assigned_papers`.
- `version_coverage = terminal_versions / expected_versions`; report riêng success và terminal failure.
- `avg_original_source_bytes`: trung bình archive bytes trên đơn vị được định nghĩa rõ (version hoặc paper).
- `avg_filtered_source_bytes`: trung bình tổng `.tex`/`.bib` sau extract trên cùng đơn vị.
- `reduction_rate = 1 - filtered_bytes / original_bytes` (xử lý denominator 0).
- `avg_references_per_paper`: nêu rõ dùng toàn bộ S2 references hay chỉ eligible arXiv refs; nên báo cả hai.
- `reference_metadata_success_rate`: định nghĩa numerator/denominator trước khi chạy, không đổi để làm đẹp số.
- `total_entry_discovery_wall_time`, `total_end_to_end_wall_time`, `avg_wall_time_per_paper`.
- `peak_rss_bytes`, `avg_rss_bytes` từ sampling interval được công bố.
- `max_disk_bytes_during_run`, `final_output_bytes`.

Mọi summary phải kèm count denominator, failure categories và run metadata. Không so sánh “nhanh hơn nhóm khác” nếu không có testbed và dữ liệu tương đương.

## 12. Risk register

| Rủi ro | Giảm thiểu | Owner |
|---|---|---|
| Chưa có assigned IDs | Không chạy corpus chính thức; theo dõi G0 | M1 |
| API thay đổi/rate limit | Adapter, timeout, backoff, cache, contract tests | M1/M3 |
| Chặn 403 do crawling mạnh | export mirror, descriptive UA, one connection, pacing | M2 |
| Archive độc hại/lạ | Safe extraction allowlist, size limits, traversal tests | M2 |
| S2 thiếu/chậm index | Không bịa; ghi status/null/limitation; retry có giới hạn | M3 |
| Data/report không khớp | Report chỉ đọc structured outputs có run ID | M4/M5 |
| Merge conflict giữa 5 người | File ownership, contract-first, PR nhỏ | M1 |
| Colab mất session/disk | Checkpoint ngoài runtime theo hướng dẫn được phép; resume | M4 |
| Vô tình commit data/secret | `.gitignore`, scanner, `git ls-files` audit | M4 |
| Số liệu đẹp nhưng không tái tạo | Clean-run benchmark và machine-readable evidence | M4/M5 |
| Vi phạm trung thực học thuật | Citation, authorship log, không fabricate | Tất cả |

## 13. Checklist nghiệm thu cuối Milestone 1

- [ ] Danh sách assigned IDs và checksum được lưu trong run manifest ngoài Git.
- [ ] Mọi publication và mọi version có terminal status.
- [ ] Source được tải bằng versioned export endpoint với pacing đúng.
- [ ] Corpus chỉ chứa `.tex`/`.bib`; TeX content không bị chỉnh.
- [ ] Empty record được giữ cho version không có source phù hợp.
- [ ] Tất cả reference metadata crawl được giữ local; eligible table chỉ giữ ref có arXiv ID.
- [ ] `papers` và `references` pass schema/uniqueness/reconciliation tests.
- [ ] Không có dữ liệu thật hoặc secret trong code repo.
- [ ] README tái tạo được môi trường và chạy pipeline bằng lệnh cụ thể.
- [ ] Benchmark thực hiện trên Google Colab CPU-only và đủ mọi metric bắt buộc.
- [ ] Jupyter Book ở repo riêng, public, GitHub Pages hoạt động.
- [ ] Tất cả bảng/figure được sinh trong build, không pasted screenshot.
- [ ] Report có implementation, tools, statistics, performance, limitations, citations.
- [ ] Năm grading criteria đều có artifact/evidence tương ứng.
- [ ] Hai URL được kiểm tra ở chế độ ẩn danh và nộp trước hạn.
- [ ] Không nộp dataset ở Milestone 1.

## 14. Milestone 2 — Parsing and Standardization

### 14.1. Phạm vi bắt buộc

- Xử lý mọi publication/version do M1 tạo ra; version không có TeX phải được ghi empty, không bị bỏ.
- Tìm root `.tex` chứa `\documentclass`; follow transitively `\input`/`\include`; ignore command bị comment và file không reachable.
- Dựng tree mỗi version: document, heading levels, paragraph/list/item và leaf gồm sentence, block formula, figure; table được coi là figure.
- Không parse references section vào hierarchy; vẫn bao gồm acknowledgements và appendices kể cả unnumbered.
- Sentence splitter không cắt trong math, commands, abbreviations, URL hoặc decimal.
- Cleanup format không mang semantic; normalize inline/block math.
- Chuyển `\bibitem` thành BibTeX programmatically.
- Deduplicate full-text elements sau cleanup trên các version.
- Deduplicate reference entries, chọn canonical citation key, rename `\cite{}` và union fields thay vì làm mất fields.
- Tạo ba bảng đúng schema: `elements`, `hierarchy`, `bibtex`.

### 14.2. Phase và gates

1. **M2-P0 — Grammar/contracts:** kind taxonomy, element ID, parent-edge, compilation graph, empty-version contract.
2. **M2-P1 — Multi-file gather:** root/include resolution, comments/cycles/missing includes/path safety tests.
3. **M2-P2 — Hierarchy parse:** headings, lists, paragraphs, leaves, exclusion/inclusion rules.
4. **M2-P3 — Standardize:** cleanup/math normalization with semantic-preservation regression tests.
5. **M2-P4 — BibTeX + dedup:** conversion, key rewrite, field union, cross-version content dedup.
6. **M2-P5 — Full run:** process union of five ranges; reconcile publication/version coverage.
7. **M2-P6 — Benchmark/report:** Colab CPU-only end-to-end/average time, peak RAM, final output size; add M2 section to same Book URL.

**Gate M2-G:** Tables pass schema + tree integrity (one root/version, valid parents, no cycles/orphans unless explicitly modeled), all versions accounted for, Jupyter Book clean-build generates M2 figures/tables.

### 14.3. Metrics tối thiểu

- Parsing success rate và version coverage cho từng publication/member và toàn nhóm.
- File counts reachable vs ignored; root/include error categories.
- Element counts by kind, trước/sau dedup; dedup ratio.
- BibTeX entries trước/sau dedup; key rewrites và field unions.
- End-to-end parser wall time, average/publication, peak RAM, final output bytes trên Colab CPU-only.

## 15. Milestone 3 — Reference Matching Pipeline

### 15.1. Quota cho nhóm 5 người

Từ requirement per-member (`k = 5`):

- Manual pool: tối thiểu **25 publications** toàn nhóm.
- Mỗi thành viên phụ trách ít nhất **5 manual publications** thuộc phạm vi được nhóm chọn; mỗi publication có ít nhất **20 labeled BibTeX entries**.
- Tổng tối thiểu **500 manually labeled entries** toàn nhóm, tương đương >=100 mỗi thành viên.
- Automatic pool: ít nhất **10% số publications ngoài manual pool**, đồng thời không ít hơn **10 publications** toàn nhóm (`2*k`).
- Validation: **5 manual + 5 automatic publications**.
- Test: **5 manual + 5 automatic publications**.
- Training: phần còn lại của manual + automatic pools.

Split phải theo publication, không theo row/pair, để tránh leakage. Candidate/label chỉ ghép BibTeX entry với reference của cùng publication. Một entry có tối đa một positive match; nếu true reference không có trong crawled candidates thì cả row là negative và ground truth nullable theo contract.

### 15.2. Phase và gates

1. **M3-P0 — Label protocol:** guideline, ambiguous/no-match policy, double-check sample, label audit trail.
2. **M3-P1 — Automatic baseline:** regex/string similarity matcher trên ít nhất quota; lưu confidence và rule provenance.
3. **M3-P2 — Dataset/split:** publication-disjoint train/valid/test đúng quota per-member; deterministic seed/manifest.
4. **M3-P3 — Features:** title/author/year/venue/identifier similarities và feature từ hierarchy nếu có; fit preprocessing chỉ trên train.
5. **M3-P4 — Model:** baseline + ít nhất model hợp lý cho ranking/classification; hyperparameter selection trên validation, không test.
6. **M3-P5 — Evaluation:** top-5 candidates, MRR@5, zero khi true candidate ngoài top 5; error/slice analysis.
7. **M3-P6 — Predictions/export:** một row mỗi BibTeX entry thuộc matching pools, đúng `partition`, nullable ground truth và `cand_1..cand_5`.
8. **M3-P7 — Personal HF datasets:** partition sáu tables theo member range, sharded Parquet + dataset card, public/access/schema/viewer checks.
9. **M3-P8 — Poster:** một slide A2 dọc `<group_id>.pptx`, chọn kết quả tốt nhất và trung thực; rehearsal poster session.

**Gate M3-G:** quota/split pass, không leakage, MRR@5 có unit test và reproducible result, six-table exports pass cross-table integrity, năm public HF links và poster final đều sẵn sàng.

### 15.3. Chống leakage và đánh giá trung thực

- Không dùng test labels trong threshold, feature, preprocessing, model selection hoặc post-processing tuning.
- Mọi duplicate/cross-version record của cùng publication ở cùng partition.
- Báo baseline, validation selection và final test riêng.
- Lưu random seed, package versions, feature config, model artifact hash và split manifest.
- Nếu dùng LLM/pretrained model, ghi rõ external knowledge vì đề nói nhóm này được chấm tách biệt; không trộn với classic baseline.

## 16. Sáu bảng final và partition theo thành viên

| Table | Nguồn | Quy tắc lọc personal dataset |
|---|---|---|
| `papers` | M1 | `arxiv_id` thuộc expanded range của member |
| `references` | M1 | citing `arxiv_id` thuộc range; ref có arXiv ID |
| `elements` | M2 | `arxiv_id` thuộc range |
| `hierarchy` | M2 | `arxiv_id` thuộc range; mọi `element_id/parent_id` tồn tại |
| `bibtex` | M2 | `arxiv_id` thuộc range |
| `predictions` | M3 | `arxiv_id` thuộc range và publication nằm trong train/valid/test matching pools |

Mỗi dataset cá nhân có dataset card root và `data/<table>/*.parquet`. Không dùng custom loader, nested objects hoặc JSON-string để né schema. Trước upload phải chạy filter-isolation test để bảo đảm không lẫn publication của thành viên khác và coverage test để không thiếu publication thuộc range do lỗi partition.

## 17. Ma trận deliverable Moodle

| Cổng nộp | Ai nộp | Nội dung | Thời điểm logic |
|---|---|---|---|
| Jupyter Book | Đại diện nhóm | Dán **một URL `https://...github.io/.../`** đến trang chủ Book đã deploy, chứa report M1 + M2; không upload file và không dán link repo thay thế | Checkpoint tiến độ; được sửa nội dung đến poster, URL không đổi |
| GitHub Repository | Đại diện nhóm | Một repo code toàn pipeline, gồm source dùng viết Book | Checkpoint tiến độ; commit cuối cùng trước poster deadline |
| Hugging Face Dataset | Từng thành viên | Một public dataset riêng cho range cá nhân, sáu Parquet tables | Final M3 |
| Poster | Đại diện nhóm | `<group_id>.pptx`, một trang portrait A2 | Final review/session |

## 18. Lịch tổng thể tương đối

Do chưa có deadline cụ thể, dùng ba checkpoint `D1` (Book M1), `D2` (Book M2) và `DF` (HF/Repo/Poster cuối):

- Trước D1: hoàn tất G0–G7 của M1; submit Book/Repo URLs sớm và giữ URL cố định.
- D1 đến D2: hoàn tất M2-P0..P6; append section vào cùng Book; rerun M1 fixes nếu cần.
- Sau D2 đến DF-14: label protocol/pools, feature/model iterations.
- DF-14 đến DF-7: freeze split/model, final test evaluation, personal dataset exports.
- DF-6 đến DF-3: poster, independent reproduction, HF public/access/schema QA.
- DF-2: code/content freeze, rehearsal và cross-member dataset audit.
- DF-1: đại diện/từng thành viên nộp đúng cổng; không chờ sát giờ.

## 19. Checklist cuối toàn đồ án

- [ ] Năm range cá nhân được import/expand/checksum và không overlap ngoài ý muốn.
- [ ] M1 coverage/schema/report/performance gates pass.
- [ ] M2 compilation path/hierarchy/normalization/dedup/schema/report/performance gates pass.
- [ ] Manual pool >=25 publications, mỗi member >=5 publications và >=100 entries.
- [ ] Automatic pool >=10% remaining và >=10 publications.
- [ ] Valid/test mỗi set có 5 manual +5 automatic publications; không leakage.
- [ ] MRR@5 implementation được unit-test và final test chỉ chạy sau model selection.
- [ ] Sáu tables pass schema và referential integrity.
- [ ] Năm personal exports chỉ chứa đúng member range.
- [ ] Năm Hugging Face dataset links public và dataset viewer/streaming đọc được.
- [ ] Code repo có toàn bộ source pipeline và source dùng tạo Jupyter Book.
- [ ] Book repo/Pages sync đúng commit, URL không đổi, M1 + M2 build sạch.
- [ ] Textbox “Đồ án: Jupyter Book” chứa đúng một URL GitHub Pages mở công khai đến trang chủ Book, không phải URL repository/file.
- [ ] Poster đúng một slide portrait A2, tên `<group_id>.pptx`.
- [ ] Tất cả submission links mở được ở incognito và nộp đúng người/cổng/hạn.

## 20. Ma trận assignment chi tiết theo milestone

Task ID dùng quy ước `MS<1|2|3>-M<1..5>-T<nn>`. Mỗi member file phải có đủ ba milestone; không được hiểu phần “functional owner” là miễn trách nhiệm kiểm tra range cá nhân.

| Member | Milestone 1 | Milestone 2 | Milestone 3 | Trách nhiệm dữ liệu cá nhân bắt buộc |
|---|---:|---:|---:|---|
| Member 1 — Ngô Gia An | 7 task: ranges/discovery/version/CLI/orchestration/repro/integration | 5 task: handoff/orchestration/integration/repro/release | 5 task: quota/split/orchestration/six-table/HF/release | Manual label >=5 publications, >=100 entries; personal six-table HF dataset |
| Member 2 | 7 task: download/payload/safe extract/preservation/empty/metrics/pilot | 7 task: root/graph/tree/leaves/sentences/coverage/performance | 5 task: manual labels/hierarchy features/prediction QA/HF/poster | Manual label >=5 publications, >=100 entries; personal six-table HF dataset |
| Member 3 — Nguyễn Đức Quang | 7 task: S2 query/rate/raw/IDs/mapping/metrics/QA | 7 task: bibliography/bibitem/normalize/ref dedup/cite rewrite/content dedup/handoff | 5 task: manual labels/candidates/integrity/HF/poster | Manual label >=5 publications, >=100 entries; personal six-table HF dataset |
| Member 4 | 8 task: schemas/storage/QA/metrics/benchmark/leak guard | 5 task: M2 schemas/tree/dedup/coverage/benchmark | 9 task: labels/automatic/split/features/model/MRR/predictions/HF/evidence | Manual label >=5 publications, >=100 entries; personal six-table HF dataset |
| Member 5 | 8 task: M1 Book/analysis/citations/deploy | 6 task: M2 Book/explanations/figures/analysis/deploy | 6 task: manual labels/analysis/poster/HF/submission | Manual label >=5 publications, >=100 entries; personal six-table HF dataset |

Chi tiết và acceptance criteria nằm trong:

- `member-1-assignment.md`
- `member-2-assignment.md`
- `member-3-assignment.md`
- `member-4-assignment.md`
- `member-5-assignment.md`
