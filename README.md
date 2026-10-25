# Introduction to Data Science — arXiv Project

Repository mã nguồn chung cho đồ án arXiv của môn Nhập môn Khoa học Dữ liệu.

Đồ án gồm ba milestone:

1. Data Crawling
2. Hierarchical Parsing and Standardization
3. Reference Matching Pipeline

## Cấu trúc hiện tại

```text
.
├── instructions/   # Đề bài chính thức của ba milestone
└── plans/          # Kế hoạch tổng và assignment cho 5 thành viên
```

Mã nguồn, kiểm thử, notebook và nội dung Jupyter Book sẽ được bổ sung theo kế hoạch trong [`plans/project-1-master-plan.md`](plans/project-1-master-plan.md).

## Quy tắc làm việc

- `main` là nhánh tích hợp, không phát triển trực tiếp.
- Mỗi thành viên làm việc trên nhánh riêng được ghi trong plan tổng.
- Mọi thay đổi vào `main` thông qua pull request và review.
- Không commit corpus, Parquet output, archive tải về, model artifacts, credentials hoặc API keys.

