# Member 3 — Nguyễn Đức Quang — Semantic Scholar, BibTeX và Reference Deduplication

## 1. Vai trò

**Nguyễn Đức Quang** đảm nhận Member 3 và **chỉ làm việc trên nhánh** `member-3/references-bibtex`. Sở hữu Semantic Scholar client, raw reference retention, BibTeX conversion/reference deduplication và lineage. Không sửa downloader, schema/export hoặc report để che lỗi dữ liệu.

## 2. Requirement chịu trách nhiệm

- R08–R10.
- Một phần R20: average references và reference metadata success rate.
- Góp phần R13/R19/R24 bằng implementation notes và nguồn API chính xác.

## 3. Deliverables sở hữu

- `src/s2_client.py`.
- Reference mapper/helper trong phạm vi contract thống nhất với M4.
- `tests/test_s2_client.py` và response fixtures synthetic/redacted.
- Raw reference/status record contract.

## 4. Milestone 1 — Crawling: task chi tiết

### MS1-M3-T01 — Query contract

- Endpoint theo publication: `/graph/v1/paper/arXiv:{arxiv_id}`.
- Request flat fields tối thiểu: reference paper ID, title, authors, year/publicationDate, venue nếu dùng, externalIds.
- Không request nested form bị API từ chối; kiểm tra response schema defensively.
- Base publication ID không mang version khi Semantic Scholar không phân biệt version; document limitation này.
- API key đọc qua env, không hard-code/log; anonymous mode vẫn hoạt động.

**Acceptance:** URL/params được contract-test; thiếu key không làm crash/config leak.

### MS1-M3-T02 — Rate limiting và resilience

- Anonymous policy không vượt 1 request/giây và 100 request/5 phút; API-key mode cũng mặc định conservative nếu chưa có quota chính thức khác.
- Central limiter, không dùng sleep rải rác khó audit.
- Timeout + exponential backoff/jitter; honor `Retry-After` nếu có; bounded retries.
- Phân loại 404/not indexed, 429, 5xx, network, malformed JSON và schema error.
- Cache/checkpoint theo citing paper để resume không gọi lại không cần thiết.

**Acceptance:** fake-clock tests chứng minh limiter; retry tests không busy-loop hoặc vượt attempt budget.

### MS1-M3-T03 — Lưu toàn bộ references cục bộ

- Với mỗi citing paper, lưu raw/reference-normalized record cho **mọi** reference S2 trả về, kể cả thiếu arXiv ID.
- Giữ `paperId`/S2 ID và external IDs để provenance; không drop null title/authors/date trong raw layer.
- Ghi query timestamp, request status, attempts, response reference count, parse failures.
- Atomic write và idempotent resume; không append duplicate khi rerun.

**Acceptance:** raw count bằng response count trừ record malformed được ghi failure rõ; không silent loss.

### MS1-M3-T04 — Chuẩn hóa arXiv ID của reference

- Đọc `externalIds.ArXiv`; hỗ trợ modern `YYMM.NNNNN` và old-style `archive/YYMMNNN`.
- Strip URL/prefix/version chỉ theo policy đã review; giữ raw value song song để audit.
- Missing/invalid arXiv ID không vào final `references` table nhưng vẫn còn raw local.
- Không suy đoán arXiv ID từ title/DOI nếu đề bài không yêu cầu; nếu thử enrichment phụ, phải tách cờ/source và không nhập vào official output khi chưa xác minh.

**Acceptance:** tests modern, old-style, versioned, missing, malformed và multiple external IDs.

### MS1-M3-T05 — Mapping fields cho eligible reference

- Map đúng contract: citing `arxiv_id`, `ref_arxiv_id`, `ref_title`, ordered `ref_authors`, `ref_submission_date`, `ref_s2_id`.
- Quyết định null/default phải thống nhất M4 và không vi phạm type; không dùng fabricated placeholder để tăng success.
- Định nghĩa dedup key cùng M4 (đề xuất citing ID + normalized ref arXiv ID + S2 ID/record identity) và lưu duplicate statistics.
- Không nhầm publication date của reference với ngày API crawl hoặc year.

### MS1-M3-T06 — Metrics có denominator rõ

- Tổng citing papers attempted/succeeded/not indexed/failed.
- Raw references returned; eligible arXiv references; missing key fields; duplicates.
- `avg_all_references_per_paper` và `avg_eligible_arxiv_references_per_paper` để tránh diễn giải mơ hồ.
- Đề xuất định nghĩa `reference_metadata_success_rate` và chốt với M4/M5 trước full run; lưu numerator/denominator trong `summary.json`.

### MS1-M3-T07 — Manual QA và limitations

- Với sample assigned papers, đối chiếu một số reference trên response/source page khi có thể.
- Ghi limitation: recent paper indexing delay, non-English/unconventional docs, version differences, API coverage.
- Không sửa số liệu do S2 thiếu; report failure trung thực và retry evidence.

## 5. Interface bàn giao

Input: base citing arXiv ID, API config/rate policy, output root, run ID.

Output:

- Per-paper crawl status.
- Full local reference records với raw identifiers/provenance.
- Eligible normalized records cho M4.
- Structured counters/timings.

## 6. Test/evidence bắt buộc

- Fields/URL/query contract.
- Rate limiter bằng fake clock.
- 200 empty refs, 404, 429 + Retry-After, 5xx, timeout, invalid JSON.
- Missing/null fields, old/new IDs, duplicates, resume.
- Reconciliation response count -> raw stored count -> eligible count.

## 7. Không được làm

- Không bỏ reference chỉ vì thiếu arXiv ID khỏi **raw local data**.
- Không đưa reference thiếu valid arXiv ID vào final `references` table.
- Không gọi theo từng version nếu API chỉ có publication-level result rồi nhân bản rows.
- Không vượt rate limit để tối ưu thời gian benchmark.
- Không đưa API key vào notebook, log, fixture, PR hoặc screenshot.

## 8. Definition of Done

- Mọi assigned publication có S2 terminal status.
- Full raw references được giữ và eligible filter traceable.
- Rate limit/retry/cache/resume có automated evidence.
- Fields final mapping đúng schema và được M4 contract-review.
- Metrics/limitations đủ để M5 viết report mà không suy đoán.

## 9. Milestone 2 — Parsing and Standardization: task chi tiết

### MS2-M3-T01 — Thu thập bibliography trên compilation path

- Nhận ordered reachable files từ Member 2; chỉ đọc bibliography thực sự tham gia document.
- Phát hiện `\bibliography`, `\addbibresource`, inline `thebibliography`/`\bibitem` và multiple sources.
- Không nhập `.bib` unused chỉ vì nằm trong folder.
- Lưu source file/span/version cho mỗi raw entry.

**Đạt:** fixtures cover inline, external `.bib`, multiple files, commented command, missing bibliography file.

### MS2-M3-T02 — Chuyển `\bibitem` thành BibTeX

- Parse citation key, optional label và raw reference text; convert bằng deterministic rules/tooling.
- Xác định entry type và fields chỉ khi evidence cho phép; missing fields giữ empty/null đúng contract.
- Preserve raw text và conversion warnings để audit; malformed item không làm mất các item còn lại.
- Test braces, escaped characters, multiline entries, Unicode, macros và nested commands.

### MS2-M3-T03 — Cleanup/normalization semantic

- Phối hợp M2 chuẩn hóa formatting commands không mang nghĩa và inline/block math formats.
- Không xóa nội dung semantic, citations, formula hoặc hierarchy boundaries.
- Canonicalize BibTeX title/author/year/doi/journal/url có policy rõ; giữ raw values.
- Regression tests chứng minh cleanup idempotent và không thay meaning ở representative fixtures.

### MS2-M3-T04 — Deduplicate reference entries

- Deduplicate trong một version và across versions của cùng publication.
- Dùng evidence nhiều trường, không chỉ citation key; tránh merge hai references khác nhau có title gần giống.
- Chọn canonical citation key deterministic; tạo alias map từ dropped keys.
- Union non-conflicting fields; conflict phải có priority rule và audit record, không silent overwrite.

**Đạt:** worked example nhiều version giữ đủ title/author/year/doi và một canonical key.

### MS2-M3-T05 — Rewrite citations

- Rewrite `\cite{}` trong standardized representation theo alias map, hỗ trợ multi-key citations.
- Không sửa raw `.tex`; lưu before/after mapping và unresolved keys.
- Validate mọi surviving citation key trỏ đến unified BibTeX entry hoặc explicit unresolved status.
- Test citations trong prose, figure caption, commands và duplicate aliases.

### MS2-M3-T06 — Full-text dedup phối hợp

- Cùng M2/M4 hash/match exact cleaned content across versions của một publication.
- Một identical element dùng một `element_id`; hierarchy mỗi version vẫn có edges riêng.
- Không dedup chỉ theo raw text trước cleanup; không dedup across different publications.
- Kiểm tra collision/determinism và parent-edge integrity sau ID reuse.

### MS2-M3-T07 — `bibtex` handoff và Book evidence

- Xuất schema-ready unified entries kèm lineage/version sources và dedup metrics.
- Cung cấp counts before/after, merged fields, renamed keys, unresolved/conflict categories.
- Review chương standardization/dedup M2 trong Book và bảo đảm mọi example có source/test thật.

## 10. Milestone 3 — Matching, Final Dataset và Poster: task chi tiết

### MS3-M3-T01 — Manual labeling quota cá nhân

- Chọn >=5 publications theo split manifest, mỗi publication >=20 entries, tổng >=100.
- So khớp BibTeX entry với M1 crawled references trong cùng publication; một match hoặc no-match.
- Ưu tiên DOI/arXiv ID/exact metadata khi có; trường hợp fuzzy phải có notes/evidence.
- Review chéo và adjudicate disagreements; không dùng model test predictions để sửa ground truth sau evaluation.

### MS3-M3-T02 — Candidate and automatic-matcher quality

- Cung cấp normalized title/author/year/DOI/arXiv fields cho Member 4 tạo candidate features.
- Phân tích missing candidate do S2 coverage so với true no-match.
- Review classic regex/string-similarity automatic matcher và threshold trên training/validation only.
- Tạo error taxonomy cho title abbreviation, author order, transliteration, year drift và duplicate references.

### MS3-M3-T03 — Matching data integrity

- Reconcile every prediction `citation_key` với canonical M2 `bibtex` row.
- Kiểm tra candidates thuộc `references` của cùng citing publication và giữ valid arXiv ID.
- Đảm bảo alias/dedup không tạo duplicate prediction rows hoặc mất BibTeX entries.
- Cấp failures cho M4 trước model freeze.

### MS3-M3-T04 — Personal Hugging Face dataset

- Xác nhận expanded range Member 3 và coverage raw reference -> bibtex -> predictions.
- Export sáu tables theo range, chạy schema/key/isolation/viewer tests.
- Viết dataset card theo template chung, upload public tài khoản cá nhân và tự nộp link Moodle.
- Không đưa raw API payload/labels/private notes vào published dataset ngoài sáu schema.

### MS3-M3-T05 — Poster/session contribution

- Chuẩn bị figures/examples cho reference coverage, BibTeX dedup và matching error cases.
- Review claims về S2, label ground truth và candidate availability.
- Có khả năng giải thích vì sao MRR=0 khi true reference không ở top 5/no candidate.
