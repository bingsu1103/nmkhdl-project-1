# Member 2 Assignment — Source Download, Safe Extraction và Hierarchy Parsing

## 1. Vai trò

Làm việc duy nhất trên nhánh `member-2/source-parsing`. Sở hữu luồng tải source từng version, trích xuất chỉ `.tex`/`.bib`, compilation graph và hierarchy parser. Không chỉnh nhánh/file của người khác ngoài quy trình issue + owner change.

## 2. Requirement chịu trách nhiệm

- R03–R06.
- Một phần R20 về kích thước trước/sau loại figure.
- Góp phần R13 và R19 bằng implementation evidence chính xác.

## 3. Deliverables sở hữu

- `src/downloader.py`.
- `src/extractor.py`.
- Unit/contract tests và synthetic archive fixtures tương ứng.
- Source-status/file-manifest contract gửi M4.

## 4. Milestone 1 — Crawling: task chi tiết

### MS1-M2-T01 — Download contract theo version

- Input bắt buộc là versioned arXiv ID từ M1; reject base ID không suffix ở layer download.
- URL đúng: `https://export.arxiv.org/src/{versioned_arxiv_id}`; không tự động crawl `arxiv.org` main site.
- Một kết nối, pacing ít nhất 3 giây giữa successive arXiv requests; descriptive User-Agent.
- Connect/read timeout; exponential backoff + jitter cho network/429/5xx; bounded attempts.
- Stream vào file tạm, fsync/atomic rename khi hoàn tất để không coi partial file là success.
- Ghi HTTP status, bytes, content type, elapsed time, attempts, SHA-256 và endpoint.
- Resume dựa trên success status + checksum; corrupt/partial được quarantine hoặc tải lại có audit.

**Acceptance:** test 200, timeout, disconnect giữa stream, 403, 404, 429, 5xx, retry exhausted, rerun completed.

### MS1-M2-T02 — Nhận dạng payload/source type

- Không giả định mọi response là `.tar.gz` chỉ dựa vào tên file/content type.
- Detect gzip/tar bằng magic/attempt an toàn; hỗ trợ form source hợp lệ mà không mất `.tex/.bib` nếu feasible.
- HTML error page trả 200 phải bị phát hiện, không lưu là archive success.
- Áp dụng configurable compressed/uncompressed size limits để tránh decompression bomb; report rõ khi vượt.
- Phân biệt `invalid_archive`, `no_tex_bib`, `http_error` và `success`.

**Acceptance:** fixture tar.gz, gzip single source, corrupt gzip, fake HTML, oversize metadata đều có deterministic status.

### MS1-M2-T03 — Safe extractor allowlist

- Chỉ extract regular files có extension `.tex`/`.bib` theo policy đã chốt; không extract image, PDF, `.sty`, `.cls`, `.bbl` hoặc executable.
- Chặn absolute paths, `..`, Windows separators/drive paths, NUL và mọi path thoát output root.
- Không follow symlink/hardlink; reject hoặc skip có logged reason.
- Xử lý nested dirs và collision/case collision rõ ràng; không silent overwrite.
- Dùng atomic per-version output; chỉ mark success sau validation.

**Acceptance:** security tests chứng minh không file nào có thể được ghi ngoài version output directory.

### MS1-M2-T04 — Bảo toàn bytes LaTeX/BibTeX

- Không parse/rewrite/re-encode/remove LaTeX commands trong M1.
- Copy byte-for-byte eligible member; ghi member checksum và extracted checksum.
- Regression fixture chứa `figure`, `\includegraphics`, Unicode, unusual encoding và multiple files.
- So sánh hash để chứng minh figure environments còn nguyên dù image binary bị loại.

**Acceptance:** checksum source member = checksum extracted file cho mọi eligible file.

### MS1-M2-T05 — Empty records và manifest

- Tạo `status.json`/structured record cho **mọi** expected version, kể cả PDF-only hoặc không có `.tex`/`.bib`.
- Record gồm paper/version IDs, terminal status, file list, archive/original bytes, filtered bytes, timestamps, attempts và error taxonomy.
- Không xóa record do không có eligible file.
- Cung cấp reconciliation API/file để M1/M4 chứng minh expected versions = status records.

**Acceptance:** fixture no-source vẫn xuất hiện trong manifest với `no_tex_bib` và zero eligible files.

### MS1-M2-T06 — Size/performance instrumentation

- Đo archive bytes trước lọc và tổng bytes `.tex`/`.bib` sau lọc trên cùng unit.
- Ghi extraction/download wall time riêng để phân tích bottleneck.
- Không lấy `du` của toàn data-dir làm paper size vì chứa cache/log khác.
- Document denominator: per version, và cung cấp aggregation đủ để M4 tính per paper nếu cần.

### MS1-M2-T07 — Pilot verification

- Cùng M1 chọn assigned pilot có single/multi-version và edge cases; không chọn ID ngoài range để thay evidence chính thức.
- Đối chiếu thủ công nhỏ: endpoint/version, file inventory, hash/content commands.
- Report mọi unsupported payload thật; không ép status thành success.

## 5. Interface bàn giao

Input tối thiểu:

- `base_arxiv_id`, `versioned_arxiv_id`, destination root, request policy, run ID.

Output tối thiểu:

- terminal status, archive path/checksum/bytes, eligible files with relative paths/checksums/bytes, filtered total, timestamps, attempts, error code/message sanitized.

M2 không tự định nghĩa lại paper schema hoặc report formula; trao đổi M4 qua contract review.

## 6. Test/evidence bắt buộc

- Security path traversal/symlink/collision tests.
- HTTP failure/retry/resume tests bằng mock server.
- Byte preservation regression test.
- Inventory assertion không có extension ngoài `.tex`/`.bib`.
- Pilot manifest + hash evidence + size metrics.

## 7. Không được làm

- Không dùng PDF làm thay thế hoặc chuyển PDF/DOCX sang TeX rồi coi là source gốc.
- Không xóa `figure`/`includegraphics` text trong `.tex`.
- Không dùng unversioned source endpoint cho vòng crawl chính thức.
- Không giải nén toàn bộ rồi mới xóa figures.
- Không commit archive/corpus/manifest thật vào code repo.

## 8. Definition of Done

- Mọi task version nhận từ M1 cho ra terminal status/audit record.
- Thành công chỉ chứa `.tex`/`.bib`, bytes bảo toàn và extraction an toàn.
- Resume/retry không nhân đôi hoặc nhận nhầm partial file.
- Metrics trước/sau lọc đủ để M4/M5 tái tính.
- PR được ít nhất M1 hoặc M4 review và toàn bộ test pass.

## 9. Milestone 2 — Parsing and Standardization: task chi tiết

### MS2-M2-T01 — Xác định compilation root

- Scan eligible `.tex` files và phát hiện root bằng `\documentclass`, không dựa đơn thuần vào filename `main.tex`.
- Xử lý zero/one/multiple root candidates bằng deterministic policy và explicit diagnostic.
- Không diễn giải `\documentclass` nằm trong comment/verbatim như root thật.
- Giữ root decision/provenance theo paper/version để audit.

**Đạt:** fixtures cover normal root, renamed root, commented fake root, multiple roots và no root.

### MS2-M2-T02 — Multi-file compilation graph

- Parse `\input`/`\include` transitively theo đúng thứ tự xuất hiện; ignore commented-out commands.
- Resolve extension omitted, relative nested paths và normalized path dưới corpus root.
- Phát hiện cycle, repeated include, missing file và path escape; không loop hoặc đọc ngoài version folder.
- Chỉ reachable files vào parse stream; unused/redundant `.tex` bị loại nhưng ghi count.

**Đạt:** graph deterministic, cycle-safe; reachable inventory khớp expected fixtures.

### MS2-M2-T03 — Hierarchy stack

- Tạo document root riêng cho mỗi version.
- Parse chapter/section/subsection/subsubsection/paragraph/starred variants theo nesting hợp lệ.
- Dùng stack để gắn parent; xử lý skipped heading level có rule document rõ.
- Bao gồm acknowledgements/appendices; không parse references section vào hierarchy.

**Đạt:** one root/version, mọi non-root node có valid parent, không cycle/orphan.

### MS2-M2-T04 — Lists và leaf elements

- Itemize/enumerate là branching components; mỗi `\item` là level con phù hợp.
- Leaf types bắt buộc: sentence, block formula, figure; table map vào figure theo đề.
- Giữ captions/semantic content theo contract, không phụ thuộc image binary đã loại ở M1.
- Xử lý nested lists, list trong section, display math xen prose.

### MS2-M2-T05 — Sentence segmentation an toàn LaTeX

- Không split ở inline/block math, command arguments, URLs, decimal numbers hoặc abbreviations như `i.e.`, `et al.`, `Fig. 1`.
- Tách câu sau cleanup phù hợp nhưng trước content dedup theo contract chung.
- Duy trì mapping từ leaf về source file/span để debug và review sample.
- Test Unicode, escaped period, citations, references và formula punctuation.

### MS2-M2-T06 — Empty/failure coverage

- Version `no_tex_bib` từ M1 tạo explicit empty parse status, zero elements/edges.
- Phân biệt no root, missing include, syntax recovery và parser crash.
- Cho phép partial diagnostic nhưng không mark success nếu tree contract fail.
- Cấp coverage records cho M4 và Book statistics.

### MS2-M2-T07 — Parser performance và handoff

- Emit wall time/publication/version, reachable file count/bytes và parse-stage timings.
- Không giữ toàn corpus AST trong RAM nếu có thể stream/release per publication.
- Bàn giao raw tree/content spans cho Member 3 standardize/BibTeX và schema-ready records cho Member 4.
- Review/approve nội dung hierarchy trong Jupyter Book M2.

## 10. Milestone 3 — Matching, Final Dataset và Poster: task chi tiết

### MS3-M2-T01 — Manual labeling quota cá nhân

- Chọn tối thiểu 5 publications theo split plan của M4, ưu tiên có >=20 BibTeX entries và candidate references đủ để label.
- Label ít nhất 20 entries mỗi publication, tổng >=100; mỗi entry có one true match hoặc explicit no-match.
- Lưu evidence/provenance/notes cho ambiguous cases; không infer match chỉ vì title gần giống.
- Review chéo sample của một member khác và sửa theo adjudication protocol.

### MS3-M2-T02 — Parser-derived feature support

- Cung cấp hierarchy/context features chỉ khi reproducible và không dùng test labels.
- Document cách lấy section/citation context từ element/hierarchy IDs.
- Test missing context/empty version không làm feature pipeline crash.
- So sánh ablation có/không hierarchy để M4/M5 biết feature có giá trị hay không.

### MS3-M2-T03 — Prediction QA cho range cá nhân

- Chạy shared locked model/config trên publications Member 2 trong matching pools.
- Kiểm tra top-5 candidates đều thuộc references của cùng citing publication.
- Spot-check parser-related false negatives: malformed titles/authors/citation context.
- Báo lỗi về đúng owner; không sửa predictions bằng tay.

### MS3-M2-T04 — Personal Hugging Face dataset

- Xác nhận expanded range và coverage sáu tables cho Member 2.
- Export sharded Parquet theo common exporter; validate schema, keys, range isolation và predictions partition.
- Tạo dataset card đúng configs/paths; upload public dưới tài khoản cá nhân.
- Test load/stream/viewer/incognito rồi tự nộp link Moodle.

### MS3-M2-T05 — Poster/session contribution

- Cung cấp diagram/sample về compilation graph/hierarchy và parser metrics/outliers.
- Review mọi claim liên quan source extraction/parsing trong poster.
- Chuẩn bị giải thích edge cases, trade-offs và performance tại poster session.
