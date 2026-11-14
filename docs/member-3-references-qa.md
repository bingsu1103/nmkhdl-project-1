# Member 3 — Reference metrics, QA và limitations (MS1-M3-T07, T08)

Người xác nhận: Member 3 (Nguyễn Đức Quang), 14/11/2026. Số liệu từ shard `member-3` (`2510.19401..2510.24400`, 5.000 paper), artifact trên Drive (link trong README).

## 1. Số liệu reference đã xác nhận (shard `member-3`)

Nguồn: `manifests/s2_summary.json`, `tables/m1_validation_report.json`.

| Chỉ số | Giá trị | Mẫu số |
|---|---|---|
| Citing paper gửi S2 | 5.000 | assigned |
| S2 `ok` | 4.998 | 5.000 |
| S2 `not_found` (S2 chưa index) | 2 | 5.000 |
| S2 lỗi cuối cùng (429/mạng) | 0 | 5.000 |
| Raw references S2 trả về | 201.470 | — |
| Raw ref không có arXiv ID | 103.888 (51,6%) | 201.470 |
| Eligible arXiv references (bảng `references`) | 97.582 | — |
| Duplicate bị loại | 0 | — |
| Eligible thiếu `ref_submission_date` | 246 | 97.582 |
| Eligible thiếu title / authors | 0 / 0 | 97.582 |
| `avg_all_references_per_paper` | 40,31 | 4.998 paper `ok` |
| `avg_eligible_arxiv_references_per_paper` | 19,52 | 4.998 paper `ok` |
| Citing paper có ≥ 1 eligible ref | 4.299 | 5.000 |
| `reference_metadata_success_rate` | **0,9996** | 4.998 / 5.000 |

Retry: 2.202 paper xong ở lần gọi đầu, 1.644 cần 2 lần, 682 cần 3, 472 cần 4 (phần lớn do 429). Có 4 lượt crawl resume: paper đã `ok`/`not_found` được dùng lại từ cache, chỉ paper lỗi được gọi lại.

## 2. Định nghĩa `reference_metadata_success_rate` (đề xuất chốt với M4)

```
reference_metadata_success_rate = số citing paper S2 trả status ok / số citing paper được gửi S2
```

- `ok` gồm cả paper S2 trả 0 reference: request thành công, chỉ là S2 không có dữ liệu reference.
- `not_found`, rate-limit và lỗi mạng còn lại vẫn nằm trong mẫu số, không bị loại ra để tăng tỷ lệ.
- Code hiện tại đã khớp với định nghĩa này: `compute_crawl_statistics` của M4 nhận `s2_succeeded_count = s2_citing_papers_succeeded` (commit `0a2d27c`).
- "Paper có ≥ 1 eligible arXiv reference" (4.299/5.000 = 0,86) là một chỉ số **khác**: nó đo độ phủ của arXiv trong reference, không đo crawl thành công. Đề xuất báo riêng, không dùng làm success rate. Fallback trong `compute_crawl_statistics` khi không truyền `s2_succeeded_count` vẫn tính theo cách này, nên khi tổng hợp phải truyền số `ok`.

## 3. Manual QA

Cách làm: chọn ngẫu nhiên 10 paper (seed 18) trong shard. Với mỗi paper, so danh sách reference S2 với bibliography mà version mới nhất của paper thật sự `\cite` (từ adapter BibTeX của M2). Title được coi là trùng khi giống nhau ≥ 90% sau chuẩn hóa. Với eligible ref, so `ref_arxiv_id` với arXiv ID ghi trong entry BibTeX của source (nếu có).

Chạy lại: `python scripts/qa_references.py <data-dir> 10 18`

| arxiv_id | S2 refs | eligible arXiv | key được `\cite` | cite có BibTeX | cite có trong S2 | arXiv ID khớp source |
|---|---|---|---|---|---|---|
| 2510.20407 | 36 | 7 | 29 | 29 | 29 | 2/2 |
| 2510.20885 | 43 | 21 | 35 | 35 | 31 | 2/2 |
| 2510.20899 | 4 | 0 | 88 | 0 | 0 | — |
| 2510.21022 | 14 | 4 | 21 | 21 | 12 | — |
| 2510.21362 | 0 | 0 | 0 | 0 | 0 | — |
| 2510.22141 | 25 | 20 | 31 | 29 | 23 | 4/4 |
| 2510.23077 | 55 | 38 | 55 | 54 | 48 | 2/2 |
| 2510.23331 | 29 | 23 | 29 | 29 | 28 | — |
| 2510.23411 | 44 | 21 | 43 | 43 | 40 | 3/3 |
| 2510.23448 | 80 | 60 | 82 | 82 | 79 | 14/14 |

Kết quả:

- **Recall**: 290/322 = **90,1%** reference được cite (có BibTeX) có trong danh sách S2.
- **Độ đúng arXiv ID**: 27/27 eligible ref có arXiv ID trong source đều khớp `ref_arxiv_id`.
- **Toàn shard**: với 4.480 paper có `\cite` trong source, median (số ref S2 / số key được cite) = 1,0. Có 610 paper S2 trả < 50% và 120 paper > 150%.
- Ca lệch đã xem tay:
  - `2510.20899` (A&A, astro-ph): S2 chỉ có 4 ref, source cite 88 key. Source gọi `\bibliography{ref}` nhưng file trong archive là `aa54503-25.bib`, nên adapter không đọc được.
  - `2510.21022`: S2 thiếu 9/21 ref. Phần thiếu là bài journal không có trên arXiv (space physics), sách (*Data mining: the textbook*), và website/dataset (OMNI Web, ICME Catalog).
  - `2510.21362`: S2 `ok` nhưng 0 reference; paper không có source `.tex` (`no_tex_bib`).

## 4. Limitations

1. **Paper mới chưa có reference trên S2**: 308/4.998 paper `ok` có 0 reference. Range là paper tháng 10/2025, S2 cần thời gian để trích reference. Không coi đây là lỗi crawl.
2. **S2 không phủ hết reference**: khoảng 10% reference được cite không có trong S2. Hay thiếu nhất là sách, website/dataset, journal ngoài CS. Ở 610 paper, S2 có chưa đến một nửa số reference của source.
3. **Hơn một nửa reference không có arXiv ID** (51,6%) nên không vào bảng `references` theo đề. S2 cũng không phải lúc nào cũng gắn `externalIds.ArXiv` cho bài có trên arXiv (ví dụ *End-To-End Memory Networks* chỉ có MAG/DBLP), nên số eligible có thể thấp hơn thực tế.
4. **Reference theo paper, không theo version**: S2 trả reference của paper (bản S2 index), không tách theo từng version arXiv.
5. **`ref_submission_date`** lấy từ `publicationDate` của S2, không suy từ `year`. 246 eligible ref không có ngày nên để null.
6. **Không index**: 2 paper S2 trả 404 (`not_found`), giữ trong mẫu số.
7. **Rate limit**: kể cả có API key (1 req/s), S2 vẫn trả 429 ngắt quãng. Cần 4 lượt resume, 1.154 paper cần ≥ 3 lần gọi. Thời gian crawl S2 phụ thuộc rate limit, không phản ánh tốc độ code.
8. **Source không chuẩn ảnh hưởng QA**: tên `.bib` không khớp lệnh `\bibliography`, key `\bibitem` bị trùng (`2510.19401`), title IEEE `"…,"`. Recall ở mục 3 chỉ tính trên reference adapter đọc được.
