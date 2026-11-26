# Milestone 1 — Crawling

## 1. Mục tiêu và phạm vi

Milestone 1 xây dựng tập dữ liệu nền từ các paper IDs arXiv được giảng viên phân công. Công việc gồm:

1. Khám phá metadata cho từng paper ID và xác định toàn bộ phiên bản.
2. Tải source archive cho từng phiên bản, chỉ trích xuất tệp `.tex` và `.bib`.
3. Thu thập reference metadata thông qua Semantic Scholar.
4. Xây dựng hai bảng `papers` và `references`, sau đó kiểm định phạm vi, schema, tính duy nhất và quan hệ dữ liệu.

Nhóm 18 được giao 25.000 candidate IDs, chia thành năm shard, mỗi thành viên 5.000 IDs. Chương này trước mắt báo cáo **shard Member 5**, không phải kết quả tổng hợp toàn nhóm.

### Phạm vi Member 5

| Khoảng ID inclusive | Số lượng |
|---|---:|
| `2510.24401`–`2510.27692` | 3.292 |
| `2511.00001`–`2511.01708` | 1.708 |
| **Tổng** | **5.000** |

## 2. Kiến trúc và luồng dữ liệu

```{mermaid}
flowchart TD
    A[Assigned arXiv IDs] --> B[Discovery: arXiv API]
    B --> C[Paper metadata]
    B --> D[Version task manifest]
    D --> E[Source download per version]
    E --> F[Extract .tex and .bib]
    C --> G[Semantic Scholar reference crawl]
    G --> H[Raw references and metadata]
    F --> I[Local corpus]
    C --> J[Build papers table]
    H --> K[Filter references with arXiv ID]
    K --> L[Build references table]
    J --> M[Validation and reconciliation]
    L --> M
```

Dữ liệu crawl, cache, corpus và Parquet được lưu ngoài code repository. Repository chứa mã nguồn, cấu hình và báo cáo; các artifact tổng hợp được chia sẻ theo quy định của nhóm.

## 3. Kết quả tổng quan Member 5

| Chỉ số | Kết quả |
|---|---:|
| Paper IDs được giao | 5.000 |
| Discovery thành công | 5.000 |
| Version tasks | 7.806 |
| Source version có terminal status | 7.806 / 7.806 |
| Semantic Scholar `ok` | 4.994 |
| Semantic Scholar `not_found` | 6 |
| Semantic Scholar `failed` | 0 |
| References crawl thô | 198.107 |
| References đủ điều kiện vào bảng | 92.563 |
| Bảng `papers` | 5.000 dòng |
| Bảng `references` | 92.563 dòng |
| Validation | Pass, 0 errors, 0 warnings |

## 4. Tổ chức các phần

- **Methodology:** các stage, API và cách tổ chức pipeline.
- **Data quality:** discovery/source/Semantic Scholar statuses và validation.
- **Corpus analysis:** dung lượng source, reference coverage và các bảng thống kê.
- **Performance:** số liệu đã đo và những phép đo còn thiếu.
- **Limitations:** các lỗi, giới hạn API và giới hạn phạm vi báo cáo.
