# Milestone 1 — Data Crawling & Pipeline Implementation

## 1. Giới thiệu & Tổng quan kiến trúc
- **Mục tiêu:** Xây dựng pipeline tự động hóa thu thập dữ liệu bài báo khoa học từ arXiv và thông tin tài liệu tham khảo từ Semantic Scholar, phục vụ cho các bước phân tích và xử lý tiếp theo trong đồ án Nhập môn Khoa học Dữ liệu — Nhóm 18.
- **Mô hình triển khai:** Báo cáo này được duy trì dưới dạng một Jupyter Book độc lập với kho lưu trữ mã nguồn chung và được xuất bản công khai qua GitHub Pages.
- **Các giai đoạn chính của Milestone 1[cite: 1]:**
  1. **Discovery:** Phát hiện và thu thập metadata bài báo qua arXiv API[cite: 1].
  2. **Version Resolution:** Xác định các phiên bản của bài báo và quản lý manifest[cite: 1].
  3. **Source Crawling & Extraction:** Tải source archive (`.tar.gz`) và trích xuất có chọn lọc các tệp `.tex` và `.bib`[cite: 1].
  4. **Reference Crawling:** Thu thập metadata tài liệu tham khảo từ Semantic Scholar[cite: 1].
  5. **Storage & Validation:** Lưu trữ, kiểm tra tính toàn vẹn (checksum) và validate dữ liệu qua các cổng kiểm định (completeness gate)[cite: 1].

---

## 2. Quy trình thực thi & Công nghệ sử dụng
- **Thư viện và công cụ cốt lõi:** 
  - Ngôn ngữ: Python $\ge 3.11$ (sử dụng `enum.StrEnum`)[cite: 1].
  - Giao tiếp API & HTTP: `requests` library, arXiv API (hỗ trợ batch tối đa 100 IDs/request, pacing tối thiểu 3 giây, bounded retry, raw-response cache)[cite: 1], và Semantic Scholar API[cite: 1].
- **Phân chia công việc & Dữ liệu đầu vào:** 
  - Nhóm xử lý tổng cộng 25.000 IDs được chia đều cho 5 thành viên (mỗi thành viên 5.000 IDs không chồng lấn)[cite: 1].
  - Ví dụ thực tế từ Member 1: Đã hoàn tất discovery 5.000/5.000 metadata, sinh ra 7.858 version tasks và kiểm thử source pilot đạt 3/3 version với cơ chế checkpoint/resume dựa trên checksum[cite: 1].

---

## 3. Thống kê & Phân tích dữ liệu (Data Statistics)
*(Lưu ý: Các biểu bảng và số liệu dưới đây được sinh tự động trong quá trình biên dịch Jupyter Book)*
- **Số lượng bài báo thu thập thành công:** *[PENDING - Chờ chạy hoàn tất toàn bộ corpus thực tế trên toàn bộ assigned ranges]*
- **Tỷ lệ thành công tổng thể (Overall success rate):** *[PENDING]*
- **Kích thước trung bình của bài báo (Bytes):**
  - Trước khi loại bỏ hình vẽ/figures: *[PENDING]*
  - Sau khi loại bỏ hình vẽ/figures (chỉ giữ lại cấu trúc văn bản/tex): *[PENDING]*
- **Số lượng tài liệu tham khảo trung bình mỗi bài báo:** *[PENDING]*
- **Tỷ lệ thành công khi thu thập metadata tham khảo (Semantic Scholar):** *[PENDING]*

---

## 4. Đánh giá hiệu năng hệ thống (Performance Benchmarking)
*Môi trường thử nghiệm chuẩn (Testbed): Google Colab chạy ở chế độ CPU-only.*

### A. Thời gian thực thi (Running Time)
- Tổng thời gian xử lý toàn bộ hệ thống (End-to-end wall time)[cite: 1].
- Thời gian trung bình để xử lý một bài báo cụ thể.
- Tổng thời gian dành riêng cho giai đoạn entry discovery.

### B. Mức tiêu thụ tài nguyên (Memory Footprint & Storage)
- **RAM:** Lượng RAM tối đa tiêu thụ trong quá trình chạy (peak RAM) và mức tiêu thụ RAM trung bình (được đo đạc qua công cụ kiểm định như `/usr/bin/time -v` hoặc `psutil`)[cite: 1].
- **Lưu trữ (Disk Storage):** Dung lượng đĩa tối đa yêu cầu trong quá trình chạy và kích thước lưu trữ của thư mục output cuối cùng (được đo đạc qua `du` hoặc tương đương)[cite: 1].

---

## 5. Trạng thái hiện tại & Hướng phát triển tiếp theo
- **Trạng thái:** Đã hoàn thiện toàn bộ mã nguồn pipeline, unit/integration tests offline, cơ chế kiểm thử checkpoint/resume và các lệnh CLI (`discover`, `crawl-sources`, `crawl-references`, `run-all`, `benchmark`)[cite: 1].
- **Hạng mục PENDING:** Đang tiến hành chạy thực tế toàn bộ 7.858 source-version tasks, khắc phục giới hạn rate-limit (HTTP 429) của Semantic Scholar (thông qua cấu hình API Key bảo mật), và xuất các artifact benchmark/validation chính thức để chốt sổ Milestone 1[cite: 1].