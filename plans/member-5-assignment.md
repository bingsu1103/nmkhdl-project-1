# Member 5 Assignment — Jupyter Book, Analysis, Citations và Submission QA

## 1. Vai trò

Làm việc duy nhất trên nhánh `member-5/book-poster`. Sở hữu `book/` trong code repo, repository deploy Pages, analysis và poster. Nếu cần thay đổi pipeline, phải mở issue cho đúng owner; không chỉnh dữ liệu để làm narrative đẹp hơn.

Sở hữu Jupyter Book Milestone 1, CI/GitHub Pages, analysis notebooks, bibliography, mapping report-to-evidence và final link QA.

## 2. Requirement chịu trách nhiệm

- R17–R19, R24–R25.
- Trình bày R20–R23 từ evidence M4.
- Bao phủ tiêu chí Report và hỗ trợ audit cả năm grading criteria.

## 3. Deliverables sở hữu

- Report repo skeleton: `_config.yml`, `_toc.yml`, `README.md`, `requirements.txt`, `references.bib`.
- `milestone-1/index.md`, `methodology.ipynb`, `data-quality.ipynb`, `corpus-analysis.ipynb`, `performance.ipynb`, `limitations.md`.
- `.github/workflows/deploy-book.yml`.
- Report traceability/checklist và public Pages URL.

## 4. Milestone 1 — Crawling/Jupyter Book: task chi tiết

### MS1-M5-T01 — Jupyter Book repository

- Dựng repo public riêng code repo; không đặt report như folder duy nhất trong crawler repo.
- Cấu hình title/authors/group, navigation, repository buttons, citations và GitHub Pages.
- Book build trên clean environment/CI; dependency versions reproducible.
- Thiết kế để Milestone 2 bổ sung section sau này, không phá URL M1.
- README report repo chỉ cách build/serve/deploy.

**Acceptance:** `jupyter-book build` sạch và Pages mở ở incognito; broken link check pass.

### MS1-M5-T02 — Outline bám requirement

Milestone 1 section tối thiểu:

1. Objectives/scope và assigned corpus (không công khai thông tin bị cấm nếu Lab yêu cầu).
2. System architecture/data flow.
3. Entry discovery và all-version resolution.
4. Versioned source download, source-type handling, `.tex`/`.bib` extraction.
5. Semantic Scholar reference crawling.
6. Data organization/schema/quality validation.
7. Corpus statistics và crawl success/failures.
8. Performance benchmark trên Colab CPU-only.
9. Limitations/threats to validity/ethical crawling.
10. Reproducibility, code link/commit và contributions.
11. References.

Mọi claim kỹ thuật phải trùng code đã merge; chưa chạy thì dùng TODO, không viết như đã có kết quả.

### MS1-M5-T03 — Figures/tables generated at build

- Notebook đọc processed tables/`summary.json` theo documented input contract.
- Sinh programmatically: success/failure table, version distribution, before/after source size, reference distribution/coverage, runtime distribution/stages, RAM timeline, disk timeline/max/final.
- Mọi chart có title/caption, axes, units, sample size/denominator và accessible colors.
- Mọi table có code cell tạo, formatting deterministic; không paste screenshot/Excel image.
- Chạy kernel từ đầu đến cuối; xóa hidden manual state và hard-coded result numbers.

**Acceptance:** xóa build artifacts rồi rebuild vẫn ra mọi figure/table từ nguồn được cung cấp.

### MS1-M5-T04 — Required analysis

- Report count papers scraped successfully và overall success rate với denominator.
- Average bytes before/after removing figure binaries; giải thích TeX figure commands vẫn nguyên.
- Average references/paper và reference metadata success; phân biệt all vs eligible arXiv references.
- Total one-paper/average required-paper/discovery/end-to-end times.
- Peak/average RAM, maximum disk during run, final output size.
- Không chỉ liệt kê số: giải thích failure categories, outliers, trade-offs và implications.
- Không so sánh performance với nhóm khác nếu không có controlled evidence.

### MS1-M5-T05 — Methodology và reproducibility

- Mô tả assigned-ID path là graded path; OAI-PMH/Kaggle chỉ là background/toolbox nếu không dùng.
- Ghi đúng modern arXiv client style/versioned export endpoint, pacing, User-Agent, retry.
- Mô tả safe extraction, empty records, S2 raw retention/eligible filter, schemas và resume/idempotency.
- Link public code repo, exact release tag/commit SHA và README run command.
- Ghi benchmark environment/run ID/input checksum từ M4.

### MS1-M5-T06 — Citations và academic integrity

- Tạo `references.bib` cho arXiv API/manual/ToU, OAI-PMH nếu nhắc, Kaggle nếu nhắc, Semantic Scholar API/platform, libraries và methods dùng thật.
- Citation đặt gần claim; URLs/metadata kiểm tra được; không để citation key unresolved.
- Paraphrase bằng hiểu biết nhóm; không copy dài từ đề bài/web.
- Contribution statement đúng lịch sử issue/PR; không gán công việc chưa làm.

### MS1-M5-T07 — Limitations và truthful reporting

- Thảo luận API throttling/outage, S2 indexing delay/coverage, archive formats, missing sources, network variability, Colab constraints.
- Failure vẫn xuất hiện trong denominator; không drop để tăng success rate.
- Phân biệt measured, inferred và expected; không bịa benchmark trước full run.
- Nếu dataset chưa publish ở M1, nói rõ đó là expected theo submission contract, không gọi là thiếu deliverable.

### MS1-M5-T08 — Jupyter Book checkpoint submission QA

- Đối chiếu năm grading criteria với section/figure/table/code evidence.
- Xác nhận official language trước khi content freeze; dịch thống nhất thuật ngữ nếu cần.
- Kiểm tra Pages/code repo public qua incognito và không cần login.
- Tại Moodle “Đồ án: Jupyter Book”, đại diện nhóm dán **một URL GitHub Pages `https://...github.io/.../` đến trang chủ Book chứa cả M1 và M2**; không upload `.ipynb/.html/.pdf/.zip` và không dán URL repository thay thế.
- Giữ nguyên URL này sau khi nộp; nội dung Book được phép tiếp tục cập nhật đến trước hạn Poster.
- Kiểm tra link commit/tag cố định, không chỉ branch thay đổi.
- Cùng M1 review Moodle fields; submit đúng hai links của M1, không dataset.
- Lưu nội bộ timestamp/receipt; không commit thông tin cá nhân nhạy cảm.

## 5. Input cần từ từng member

- M1: architecture, CLI, discovery/version evidence, README command, git SHA/run ID.
- M2: extraction algorithm, file/status/size metrics và edge cases.
- M3: API fields, rate-limit policy, raw/eligible counts và limitations.
- M4: validated tables, `summary.json`, resource samples, metric definitions, Colab metadata.

Member 5 không tự suy đoán thiếu dữ liệu. Mọi inconsistency phải mở issue cho owner giải quyết.

## 6. Review matrix

- M1 review architecture/reproducibility/code links.
- M2 review source download/extraction claims.
- M3 review S2/reference claims.
- M4 review toàn bộ số liệu, denominator, units, chart/table.
- M5 xử lý editorial/build/accessibility; ít nhất hai người proofread bản final.

## 7. Test/evidence bắt buộc

- Clean book build log.
- Notebook run-all without manual edits.
- Link/citation/unresolved-reference checks.
- Generated-artifact inventory chứng minh figure/table đến từ code.
- Incognito Pages access check.
- Report-to-requirement checklist có page/section cụ thể.

## 8. Không được làm

- Không paste static screenshots thay figure/table generated during build.
- Không nhập tay số liệu benchmark/corpus vào Markdown khi đã có nguồn structured.
- Không dùng ngôn ngữ submission trước khi official language được xác nhận.
- Không công bố dataset/Hugging Face như deliverable M1.
- Không che limitation/failure hoặc claim 100% khi reconciliation không chứng minh.

## 9. Definition of Done

- Jupyter Book public repo riêng, clean build và deploy Pages thành công.
- Tất cả required statistics/performance points có generated table/figure + interpretation.
- Implementation narrative được owner kỹ thuật sign off.
- Citation/link/language/submission checklist pass.
- URL Jupyter Book và code repository được mở công khai, đúng loại link và sẵn sàng nộp trước deadline.

## 10. Milestone 2 — Parsing and Standardization/Jupyter Book: task chi tiết

### MS2-M5-T01 — M2 information architecture

- Thêm M2 vào **cùng Jupyter Book và cùng URL** đã dùng cho M1; cập nhật `_toc.yml` rõ navigation.
- Sections tối thiểu: compilation-path gathering, hierarchy, leaves/exclusions/inclusions, cleanup/math, BibTeX conversion, both dedup levels, statistics, benchmark, limitations.
- Giữ M1 intact và link nội bộ giữa M1 inputs -> M2 outputs.
- Book source canonical ở `book/` code repo và sync deploy repo theo exact commit.

### MS2-M5-T02 — Hierarchical parsing explanation

- Dùng diagram/code-linked examples giải thích root detection, transitive includes, ignored files và failure recovery.
- Minh họa tree document→headings→paragraph/list→sentence/formula/figure; table-as-figure rule.
- Nêu rõ references excluded, acknowledgements/appendices included.
- Member 2 sign off mọi claim và edge-case example.

### MS2-M5-T03 — Standardization/dedup explanation

- Trình bày removed formatting vs preserved semantics; inline/block math normalization.
- Có worked example `\bibitem` → BibTeX, canonical key, `\cite{}` rewrite và union fields.
- Minh họa identical cleaned element dùng một ID across versions nhưng edges vẫn per-version.
- Member 3 sign off; không dùng synthetic example như kết quả corpus nếu không ghi rõ fixture.

### MS2-M5-T04 — M2 figures/tables generated during build

- Programmatically tạo parsing success/version coverage per member/group.
- Reachable/ignored file counts, element counts by kind, before/after content dedup.
- BibTeX before/after dedup, key rewrites, conflicts/unresolved counts.
- Parser wall time/average publication, peak RAM, final output size; axes/units/denominators/captions đầy đủ.

### MS2-M5-T05 — M2 analysis và limitations

- Giải thích failures/outliers thay vì chỉ báo averages.
- Phân tích root/include ambiguity, LaTeX macro complexity, sentence boundary errors và dedup trade-offs.
- Phân biệt measured results, manual inspection và inference.
- Link exact code SHA/run ID/schema version.

### MS2-M5-T06 — Build/deploy/checkpoint QA

- Clean execute all notebooks và `jupyter-book build`; không hidden state/hard-coded outputs.
- Broken links/citations/accessibility/public-incognito test.
- Deploy vào URL cũ, xác nhận M1+M2 menu hoạt động; không tạo URL mới sau Moodle submission.
- Lưu build log/deploy commit và report-to-requirement checklist.

## 11. Milestone 3 — Matching, Personal Dataset và Poster: task chi tiết

### MS3-M5-T01 — Manual labeling quota cá nhân

- Chọn >=5 publications theo split manifest, mỗi publication >=20 labeled entries, tổng >=100.
- Theo guideline one-match/no-match và evidence; tham gia cross-review/adjudication.
- Không sửa ground truth theo final test predictions.
- Cập nhật progress board để group quota không thiếu sát hạn.

### MS3-M5-T02 — Matching analysis package

- Nhận immutable metrics từ M4: pool/split counts, baseline/model MRR@5, feature ablation, coverage/error slices.
- Tạo figures/tables bằng code trong repository; mọi result gắn run ID/split hash.
- Viết justification cho features/model dựa trên analysis thực, không mô tả generic.
- Phân biệt manual vs automatic subset và no-candidate/no-match cases.

### MS3-M5-T03 — Poster content architecture

- Một slide portrait A2 với hierarchy: problem/data → pipeline → strongest parsing/matching evidence → MRR/results → limitations/contributions.
- Chọn nội dung chất lượng cao/khác biệt thay vì nhồi toàn bộ report.
- Font/labels/captions đọc được ở kích thước in; màu accessible; không dùng screenshot bảng nhỏ.
- Citation ngắn gọn và truthful contribution statement.

### MS3-M5-T04 — Poster production/verification

- File duy nhất `<group_id>.pptx`, đúng portrait A2 và đúng một slide.
- Export PDF/image để kiểm tra clipping, font substitution, image resolution và margins; PPTX vẫn là file nộp.
- M1 review overall, M2 parser, M3 references, M4 model/metrics; resolve comments trước freeze.
- Rehearse phần nói/Q&A, phân công ai giải thích từng component và limitations.

### MS3-M5-T05 — Personal Hugging Face dataset

- Xác nhận expanded range Member 5 và six-table coverage.
- Chạy common exporter/validator; dataset card + sharded Parquet đúng configs/paths.
- Upload public dưới tài khoản HF cá nhân, kiểm tra viewer/streaming/incognito và tự nộp Moodle link.
- Không nhầm personal HF URL với group Book/repository submissions.

### MS3-M5-T06 — Final submission matrix

- Jupyter Book: đại diện dán một stable GitHub Pages URL chứa M1+M2.
- GitHub Repository: đại diện dán một public group code repo gồm pipeline và files dùng viết Book.
- Hugging Face: từng member tự dán personal public dataset URL.
- Poster: đại diện upload `<group_id>.pptx` một slide A2 portrait.
- Kiểm tra deadline, official language, permissions và receipts cho từng cổng.
