# Member 4 - Từ Quốc Nghĩa — Data Quality, Matching Model và Evaluation

## 1. Vai trò

Làm việc duy nhất trên nhánh `member-4/quality-matching`. Là data-contract/quality owner và ML owner: validate sáu bảng, reconciliation, metrics/benchmark, labeling contract, feature/model/evaluation. Không chỉnh API clients/report prose để ép dữ liệu qua validation.

## 2. Requirement chịu trách nhiệm

- R07, R10–R12.
- R20–R23.
- Góp phần R13, R18 và final grading evidence.

## 3. Deliverables sở hữu

- `src/normalize.py`, `src/storage.py`, `src/validate.py`, `src/metrics.py`.
- `tests/test_schema.py`, validation/reconciliation/performance instrumentation tests.
- `notebooks/colab_benchmark.ipynb` hoặc script/notebook tương đương.
- Machine-readable `summary.json` contract cho M5.

## 4. Milestone 1 — Crawling: task chi tiết

### MS1-M4-T01 — Formal schema contracts

`papers`:

- `arxiv_id`: string non-null, unique publication key.
- `title`: string.
- `authors`: list<string>, giữ thứ tự.
- `submission_date`: ISO string.
- `revised_dates`: list<string>.
- `venue`: nullable string.

`references`:

- `arxiv_id`: citing paper ID, string non-null.
- `ref_arxiv_id`: string non-null.
- `ref_title`: string.
- `ref_authors`: list<string>.
- `ref_submission_date`: string.
- `ref_s2_id`: string.

- Dùng Arrow schema explicit; không để pandas tự suy type giữa shard.
- Document semantics/null policy; nếu source thiếu field non-null theo spec, record validation failure thay vì fabricate.
- Schema/version ID được ghi trong dataset/run metadata.

**Acceptance:** round-trip write/read giữ schema và nested list types; wrong/null values fail có row identity.

### MS1-M4-T02 — Normalize và deduplicate

- Normalize whitespace/date/ID có quy tắc deterministic; giữ raw field/provenance ngoài published tables.
- `papers` có một row mỗi assigned publication, không mỗi version; revised dates tổng hợp đúng metadata.
- `references` chỉ nhận eligible rows từ M3; chốt dedup key và report dropped duplicates.
- Không merge two people/title heuristically gây mất dữ liệu nếu không có spec.

### MS1-M4-T03 — Parquet sharding/storage

- Write sharded Parquet với deterministic naming/order/row-group policy vừa phải.
- Atomic staging -> validate -> publish processed directory.
- Reload tất cả shards và so count/hash/selected values.
- Không publish Hugging Face ở M1; chỉ đảm bảo output sẵn sàng cho M3 final hosting guidance.
- Data dir nằm ngoài Git; `.gitignore` và scan bảo vệ.

### MS1-M4-T04 — Reconciliation và data-quality gates

- Assigned papers = resolved success + explicit discovery failures.
- Expected versions = tất cả source terminal status; không có pending ở release.
- Source success inventory chỉ `.tex`/`.bib`.
- S2 attempted papers = scope đã định; raw/eligible/reference table counts reconcile.
- Check duplicate PK, nullability, type, invalid ISO date, invalid IDs, unknown statuses, FK citing paper -> papers.
- Xuất QA summary có severity; critical failure làm CLI non-zero.

**Acceptance:** intentionally corrupt fixtures bị bắt đúng rule; report có denominator/failed IDs.

### MS1-M4-T05 — Structured measurement

- Nhận stage/paper events từ M1–M3; monotonic clock cho duration.
- Sampling RSS định kỳ bằng psutil; công bố sampling interval; peak và arithmetic/time-weighted average được định nghĩa.
- Theo dõi disk usage định kỳ của working data dir để tìm max; final output size tách archive/cache/corpus/processed.
- Không dựa vào notebook wall-clock cell thủ công.
- Ghi environment: Colab CPU-only, Python/package versions, git SHA, run ID, assigned-input checksum.

### MS1-M4-T06 — Các metric bắt buộc

- Papers scraped successfully, total assigned, overall success rate.
- Average paper/source size trước/sau remove figure, cùng denominator.
- Average all references và eligible arXiv references per paper.
- Reference metadata success rate với numerator/denominator chốt trước.
- Total time one paper (distribution/examples), average per required paper, total entry discovery, total end-to-end.
- Peak/average RAM, maximum disk storage during run, final output storage.
- Failure breakdown và version coverage để không dùng average che missing data.

**Acceptance:** mọi số trong report có key trực tiếp từ summary hoặc notebook computation version-controlled.

### MS1-M4-T07 — Colab CPU-only benchmark protocol

- Notebook khởi tạo clean runtime, assert GPU không được dùng/CPU-only context được ghi.
- Clone pinned commit/tag, setup từ `requirements.txt`, mount/obtain assigned IDs an toàn, đặt external data-dir.
- Chạy end-to-end bằng đúng public command README; không chạy từng cell sửa state ẩn.
- Lưu raw resource samples/logs/summary ngoài code repo theo hướng dẫn nhóm.
- Nếu chạy lặp, giữ từng run và giải thích chọn median/mean; không cherry-pick fastest run.
- Dùng cùng rate-limit policy production; không loại network wait khỏi end-to-end.

### MS1-M4-T08 — Git/data leak guard

- `.gitignore` cover data roots, archives, parquet, logs, secrets, notebook checkpoints.
- CI/pre-commit check tracked extensions/large files; allow synthetic fixtures nhỏ rõ ràng.
- Trước release chạy `git ls-files` + secret scan + size audit.
- Phát hiện leak thì báo M1, rotate secret nếu cần; không chỉ xóa ở latest commit khi history vẫn chứa.

## 5. Phối hợp

- Review metadata mapping của M1 và reference mapping của M3.
- Nhận archive/file size/status từ M2, không tự tính bằng cách đọc log.
- Cấp stable `summary.json` + schema description + run metadata cho M5.
- Cùng M5 kiểm tra từng chart/table về denominator và units.

## 6. Test/evidence bắt buộc

- Arrow schema and round-trip tests.
- Duplicate/null/date/ID/FK/status failure fixtures.
- End-to-end reconciliation fixture.
- Metrics tests với known timestamps/RSS/disk samples.
- Colab clean-run evidence và command/commit/run ID.
- Data leak audit output.

## 7. Không được làm

- Không điền giả field thiếu để đạt 100%.
- Không đổi denominator sau khi thấy kết quả.
- Không loại rate-limit/network time khỏi end-to-end mà không báo.
- Không đưa data thật vào GitHub code repo hoặc submit data ở M1.
- Không publish Hugging Face trước hướng dẫn/final milestone.

## 8. Definition of Done

- Hai table đúng schema, sharded/reload được và reconciled.
- Tất cả critical QA gates pass hoặc failure được report trung thực.
- Summary chứa đủ metric bắt buộc, units/denominators/run metadata.
- Benchmark tái chạy trên Colab CPU-only từ clean checkout.
- M5 có thể build toàn bộ bảng/figure mà không nhập số thủ công.

## 9. Milestone 2 — Parsing and Standardization: task chi tiết

### MS2-M4-T01 — Arrow schemas cho ba bảng

- Khóa explicit types cho `elements`, `hierarchy`, `bibtex` đúng đề, gồm dictionary/string/list/int/nullability.
- Quy định element/citation key uniqueness scope và stable serialization.
- Round-trip sharded Parquet không đổi schema/list order/null semantics.
- Version schema và migration policy được ghi trong run manifest.

### MS2-M4-T02 — Tree integrity validation

- Một document root/version; mọi node/parent reference tồn tại trong `elements` của cùng publication.
- Phát hiện cycle, self-parent, orphan, duplicate edge và version ngoài expected set.
- Cho phép một deduplicated element xuất hiện trong edges nhiều versions nhưng không cross-publication.
- Empty version có zero edges/elements và explicit status.

### MS2-M4-T03 — Dedup/normalization validation

- Recompute hashes của cleaned content; identical content trong publication dùng cùng element ID.
- Counts trước/sau cleanup/dedup theo kind/version/publication/member.
- Validate canonical BibTeX key, aliases, field union, unresolved citations và conflicts.
- Không coi lowercasing/whitespace alone là đủ nếu cleanup contract khác.

### MS2-M4-T04 — Coverage/reconciliation

- Union năm ranges -> M1 publications/versions -> M2 parse statuses -> three table rows.
- Report success/empty/failure denominators riêng; không loại failures khỏi rate.
- Mọi schema/tree/dedup critical issue làm release command non-zero.
- Tạo machine-readable QA summary cho Member 5.

### MS2-M4-T05 — Parser benchmark

- Trên Colab CPU-only đo end-to-end wall time, average/publication, peak RSS và final output size.
- Capture git SHA, input range hashes, package versions, config và sampling interval.
- Không cherry-pick fastest run; ghi run selection/statistic policy.
- Export raw resource samples và derived summary để Book generate figures/tables.

## 10. Milestone 3 — Matching, Final Dataset và Poster: task chi tiết

### MS3-M4-T01 — Labeling protocol/tool/validation

- Định nghĩa one-positive-or-no-match row semantics, evidence fields, ambiguous/adjudication states.
- Tool chỉ cho chọn candidate thuộc cùng publication; không cho duplicate labels.
- Enforce mỗi manual publication >=20 labeled entries và each member >=5 publications/>=100 entries.
- Double-review sample và freeze ground truth trước final test.

### MS3-M4-T02 — Automatic labeling baseline

- Implement classic regex/string-similarity matcher trên title/author/year/identifiers.
- Apply cho >=10% publications ngoài manual pool và tối thiểu 10 publications toàn nhóm.
- Threshold/rules tuning chỉ trên train/validation; lưu confidence, rule provenance và coverage.
- Automatic matcher labels mọi BibTeX entry của publication được chọn.

### MS3-M4-T03 — Publication-level split

- Deterministic split manifest: valid 5 manual +5 automatic; test 5 manual +5 automatic; remaining labeled publications train.
- Không split entry/pair gây same-publication leakage.
- Stratify/inspect candidate sizes và no-match ratio nếu feasible nhưng quota đề là hard constraint.
- Hash/freeze manifest trước model selection; mọi change cần decision log và rerun.

### MS3-M4-T04 — Candidate construction và features

- Mỗi BibTeX entry chỉ pair với arXiv-keyed references cùng publication.
- Features đề xuất: normalized title similarities, author overlap/order, year distance, DOI/arXiv exact, venue/journal, optional hierarchy context.
- Fit vectorizer/scaler/encoder trên train only; apply immutable transforms valid/test.
- Unit tests cho nulls, empty candidates, duplicate refs, extreme candidate matrices và determinism.

### MS3-M4-T05 — Model training/selection

- Xác định formulation rõ: ranking/classification/regression; document target và scoring-to-rank conversion.
- Có heuristic baseline và ít nhất một learned model hợp lý; record seeds/hyperparameters/artifact hashes.
- Chọn features/threshold/model chỉ bằng train+validation; không xem test MRR trong iteration.
- Phân tích ablation/feature importance phù hợp để justify features.

### MS3-M4-T06 — Top-5 và MRR@5

- Rank candidates per entry, deterministic tie-breaking, output nullable `cand_1..cand_5`.
- Reciprocal rank `1/rank` nếu correct ref ở vị trí 1–5, ngược lại 0; mean trên labeled test entries theo contract.
- Unit tests known examples, fewer-than-5 candidates, no candidate, no-match ground truth và ties.
- Báo aggregate + slices manual/automatic/candidate size/error type; không đổi test set.

### MS3-M4-T07 — Predictions/six-table validation

- Validate `arxiv_id`, `partition`, `citation_key`, nullable ground truth/candidates theo schema.
- Một prediction row/BibTeX entry của matching publications; no rows cho publications ngoài pools.
- Cross-check all candidate IDs in references and citation keys in bibtex; partition matches manifest.
- Chạy leakage scan, duplicate/null/type/range tests trước export.

### MS3-M4-T08 — Personal HF export và support

- Tự hoàn tất Member 4 manual-label quota và cross-review member khác.
- Filter/validate six tables cho range Member 4; upload public và tự nộp link.
- Cung cấp common exporter/validator để mỗi member tự tạo dataset riêng dưới tài khoản cá nhân.
- Test sharded Parquet viewer/streaming, dataset card configs, public/incognito access cho cả năm links.

### MS3-M4-T09 — Final evidence cho poster

- Cấp reproducible metrics: baseline/model MRR@5, feature ablations, coverage và error analysis.
- Mọi chart/table có data source, run ID, split hash, units/denominator.
- Review poster claims và reject số liệu nhập tay/không truy ngược được.
