# MEMBER 2 – Khánh An – TẢI MÃ NGUỒN, GIẢI NÉN AN TOÀN VÀ PHÂN TÍCH CẤU TRÚC LATEX

## 1. Tổng quan

Member 2 phụ trách xây dựng giai đoạn xử lý mã nguồn bài báo khoa học trong hệ thống xử lý dữ liệu arXiv.

Nhiệm vụ chính là tải mã nguồn của các bài báo được phân công, giải nén dữ liệu một cách an toàn, xác định tài liệu LaTeX chính và phân tích nội dung thành cấu trúc phân cấp có thể sử dụng cho các giai đoạn xử lý tiếp theo.

Mục tiêu là chuyển đổi dữ liệu mã nguồn thô từ arXiv thành dữ liệu có cấu trúc, phục vụ việc trích xuất, tìm kiếm và phân tích nội dung bài báo khoa học.

### Các nhiệm vụ chính

- Tải mã nguồn bài báo từ arXiv.
- Xử lý lỗi mạng, timeout và tải lại khi thất bại.
- Hỗ trợ tiếp tục quá trình xử lý khi bị gián đoạn.
- Giải nén các tệp mã nguồn một cách an toàn.
- Ngăn chặn các rủi ro bảo mật khi giải nén tệp nén.
- Xác định tệp LaTeX chính của bài báo.
- Phân tích các lệnh `\input` và `\include` đệ quy.
- Trích xuất cấu trúc phân cấp của tài liệu LaTeX.
- Trích xuất văn bản, công thức, hình ảnh, bảng và danh sách.
- Trích xuất thông tin tài liệu tham khảo.
- Xuất dữ liệu có cấu trúc để tích hợp với các thành phần khác.

---

## 2. Quy trình xử lý tổng thể

Gồm ba giai đoạn chính:

```text
Manifest danh sách phiên bản bài báo
              |
              v
       Source Downloader
              |
              v
       Tải mã nguồn arXiv
              |
              v
       Safe Archive Extractor
              |
              v
       Giải nén mã nguồn LaTeX
              |
              v
       Hierarchical LaTeX Parser
              |
              v
       Dữ liệu bài báo có cấu trúc
              |
              v
       Các giai đoạn xử lý tiếp theo
```

### Giai đoạn 1: Tải mã nguồn (Source Downloading)

Downloader nhận danh sách các bài báo và phiên bản từ giai đoạn Discovery, sau đó tải mã nguồn tương ứng từ arXiv.

Các chức năng cần thực hiện:

- Tải mã nguồn dựa trên mã định danh arXiv và phiên bản bài báo.
- Xử lý lỗi HTTP và lỗi kết nối.
- Triển khai cơ chế thử lại khi tải thất bại.
- Thiết lập thời gian chờ cho các yêu cầu mạng.
- Hạn chế tải lại những tệp đã được tải thành công.
- Lưu trữ tệp đã tải và trạng thái xử lý.
- Hỗ trợ tiếp tục xử lý khi bị gián đoạn nếu CLI cung cấp chức năng này.

### Giai đoạn 2: Giải nén an toàn (Safe Extraction)

Extractor thực hiện giải nén các tệp mã nguồn đã tải vào những thư mục riêng biệt.

Các yêu cầu về an toàn:

- Ngăn chặn tấn công Path Traversal thông qua đường dẫn như `../`.
- Từ chối các đường dẫn tuyệt đối không an toàn.
- Kiểm tra và xử lý Symbolic Link an toàn.
- Không cho phép giải nén tệp ra ngoài thư mục đích.
- Xử lý các tệp nén bị lỗi hoặc không được hỗ trợ.
- Giới hạn hợp lý kích thước tệp và số lượng tệp sau giải nén.
- Giữ lại tệp nén gốc để phục vụ kiểm tra và tái hiện lỗi.

### Giai đoạn 3: Phân tích LaTeX phân cấp (Hierarchical LaTeX Parsing)

Parser chuyển đổi các tệp LaTeX thành dữ liệu có cấu trúc.

Các chức năng chính:

1. Xác định tệp `.tex` chính, thường chứa lệnh `\documentclass`.
2. Phân tích đệ quy các lệnh `\input{}` và `\include{}`.
3. Bỏ qua các lệnh include nằm trong phần chú thích.
4. Không phân tích những tệp `.tex` không được sử dụng trong tài liệu chính.
5. Bảo toàn cấu trúc section và subsection.
6. Trích xuất đoạn văn, câu, công thức, hình ảnh, bảng và danh sách.
7. Xử lý thông tin trích dẫn và tài liệu tham khảo.
8. Chuẩn hóa cú pháp LaTeX nhưng vẫn bảo toàn nội dung toán học quan trọng.

---

## 3. Yêu cầu phân tích LaTeX

### 3.1. Cấu trúc tài liệu

Parser cần nhận diện cấu trúc phân cấp của một bài báo khoa học:

```text
Paper
 ├── Abstract
 ├── Section
 │    ├── Subsection
 │    │    ├── Paragraph
 │    │    │    ├── Sentence
 │    │    │    └── Formula
 │    │    └── List
 │    └── Figure
 ├── Table
 ├── Acknowledgements
 ├── Appendix
 └── References
```

### 3.2. Các thành phần LaTeX cần hỗ trợ

| Thành phần | Ví dụ |
|---|---|
| Tài liệu | `\documentclass`, `\begin{document}` |
| Tiêu đề mục | `\section`, `\subsection`, `\subsubsection` |
| Đoạn văn | Các khối văn bản thông thường |
| Câu | Các câu được tách từ đoạn văn |
| Công thức | `$...$`, `\(...\)`, `\[...\]`, equation |
| Hình ảnh | figure, `\includegraphics`, `\caption` |
| Bảng | table, tabular, `\caption` |
| Danh sách | itemize, enumerate, `\item` |
| Tài liệu tham khảo | `\bibliography`, `thebibliography`, BibTeX |

### 3.3. Các trường hợp đặc biệt

Parser cần xử lý những trường hợp sau:

- Biểu thức toán học có chứa dấu chấm.
- Các từ viết tắt như `e.g.`, `i.e.`, `et al.`.
- Số thập phân.
- URL và địa chỉ email.
- Các dòng chú thích LaTeX.
- Các môi trường LaTeX lồng nhau.
- Tài liệu LaTeX gồm nhiều tệp.
- Lệnh trích dẫn và tài liệu tham khảo.
- Phần Acknowledgements và Appendix.

Đặc biệt, thuật toán tách câu cần tránh việc chia sai nội dung bên trong công thức toán học, URL, từ viết tắt và số thập phân.

### 3.4. Xử lý tài liệu tham khảo và trùng lặp

Hệ thống cần:

- Trích xuất thông tin tài liệu tham khảo khi có dữ liệu.
- Bảo toàn các lệnh trích dẫn và mối liên hệ với tài liệu tham khảo.
- Hạn chế lưu trữ nội dung trùng lặp giữa các phiên bản.
- Bảo toàn cấu trúc phân cấp riêng của từng phiên bản.
- Tạo bản ghi có cấu trúc rỗng đối với phiên bản không có mã nguồn LaTeX hợp lệ.

---

## 4. Dữ liệu đầu vào và đầu ra

### 4.1. Dữ liệu đầu vào

Đầu vào chính là danh sách các tác vụ xử lý phiên bản bài báo được tạo ra từ giai đoạn Discovery.

Cấu trúc thư mục dữ liệu dự kiến:

```text
nmkhdl-project-1-data/
 ├── manifests/
 │    └── discovery/
 │         └── version_tasks.csv
 ├── sources/
 ├── extracted/
 ├── parsed/
 └── logs/
```

Lưu ý: Đây là cấu trúc minh họa. Tên thư mục và tệp thực tế cần tuân theo cấu hình chung của dự án.

### 4.2. Dữ liệu đầu ra

Kết quả phân tích dự kiến gồm ba thành phần chính:

| Thành phần | Mô tả |
|---|---|
| `elements` | Nội dung được trích xuất từ bài báo: văn bản, công thức, hình ảnh, bảng và các thành phần khác |
| `hierarchy` | Quan hệ phân cấp giữa tài liệu, section, subsection, paragraph và các phần tử |
| `bibtex` | Thông tin tài liệu tham khảo và các mục BibTeX |

Định dạng đầu ra cần thống nhất với yêu cầu tích hợp của toàn bộ hệ thống.

---

## 5. Cài đặt môi trường

Thực hiện các lệnh sau tại thư mục gốc của repository.

### Bước 1: Tạo môi trường ảo

```powershell
python -m venv .venv
```

### Bước 2: Kích hoạt môi trường

```powershell
.\.venv\Scripts\Activate.ps1
```

### Bước 3: Cài đặt thư viện

```powershell
python -m pip install -r requirements.txt
```

Nếu dự án sử dụng thêm các thư viện phục vụ phân tích LaTeX hoặc xử lý tệp nén, cần cài đặt theo cấu hình dependencies của repository.

---

## 6. Hướng dẫn thực thi

Các lệnh dưới đây mô tả quy trình dự kiến. Trước khi thực thi, cần kiểm tra `python -m src.cli --help` và hướng dẫn của từng subcommand để xác nhận các tham số thực tế.

### Bước 1: Tạo danh sách phiên bản bài báo

Giai đoạn Discovery cần tạo ra tệp:

```text
nmkhdl-project-1-data/manifests/discovery/version_tasks.csv
```

Ví dụ:

```powershell
python -m src.cli discover `
    --owned-papers examples/phase1/owned_papers.csv `
    --data-dir ../nmkhdl-project-1-data `
    --user-agent "group-18-nmkhdl-project/0.2 (+https://github.com/bingsu1103/nmkhdl-project-1)" `
    --member member-2 `
    --resume
```

**Lưu ý quan trọng:** Tệp `examples/phase1/owned_papers.csv` có thể chỉ chứa dữ liệu mẫu được phân công cho các thành viên khác. Khi xử lý dữ liệu thực tế, cần sử dụng manifest chứa đúng danh sách bài báo.

### Bước 2: Tải và giải nén mã nguồn

```powershell
python -m src.cli crawl-sources `
    --data-dir ../nmkhdl-project-1-data `
    --user-agent "group-18-nmkhdl-project/0.2 (+https://github.com/bingsu1103/nmkhdl-project-1)" `
    --member member-2
```

Cần kiểm tra `crawl-sources --help` trước khi thêm các tham số tùy chọn. Không mặc định rằng lệnh này hỗ trợ `--resume`.

### Bước 3: Phân tích mã nguồn LaTeX

Kiểm tra tham số của lệnh:

```powershell
python -m src.cli parse-sources --help
```

Sau đó sử dụng đúng các tham số được CLI cung cấp để chạy quá trình phân tích trên dữ liệu đã giải nén.

---

## 7. Kiểm thử

Các thành phần cần được kiểm thử độc lập trước khi tích hợp vào hệ thống tổng thể.

### 7.1. Các nhóm kiểm thử

| Thành phần | Nội dung kiểm thử |
|---|---|
| Downloader | Tải thành công, lỗi HTTP, retry, timeout và tải bị gián đoạn |
| Extractor | Giải nén hợp lệ, tệp lỗi, Path Traversal, Symbolic Link và giới hạn giải nén |
| Source Pipeline | Đọc manifest, quản lý trạng thái, tích hợp tải và giải nén |
| LaTeX Parser | Xác định tài liệu chính, include đệ quy, chú thích, section, công thức, hình ảnh và bảng |
| Parse Pipeline | Xử lý nhiều phiên bản, thiếu tệp nguồn, tính nhất quán của đầu ra và xử lý lỗi |

### 7.2. Liệt kê các tệp kiểm thử hiện có

```powershell
Get-ChildItem -Path . -Recurse -File -Include "test_*.py","*_test.py"
```

### 7.3. Thu thập danh sách test mà chưa thực thi

```powershell
python -m pytest tests -v --collect-only
```

### 7.4. Chạy toàn bộ test

```powershell
python -m pytest -v
```

### 7.5. Lưu kết quả kiểm thử

```powershell
python -m pytest tests -v --tb=short |
    Tee-Object -FilePath member2_test_results.txt
```

Chỉ ghi nhận một test là thành công sau khi test đó thực sự được thực thi và cho kết quả đạt yêu cầu trên repository hiện tại.

---

## 8. Xử lý lỗi và đảm bảo độ tin cậy

Hệ thống cần xử lý các trường hợp:

- Không thể kết nối mạng.
- HTTP 404 hoặc mã nguồn arXiv không khả dụng.
- Quá thời gian tải xuống.
- Tệp nén bị hỏng.
- Định dạng tệp nén không được hỗ trợ.
- Đường dẫn giải nén không an toàn.
- Không tìm thấy tệp `.tex` chính.
- Thiếu các tệp `.tex` được include.
- Vòng lặp đệ quy trong các lệnh `\input` hoặc `\include`.
- Cú pháp LaTeX không thể phân tích.
- Thiếu tệp thư mục tài liệu tham khảo.
- Tệp mã nguồn rỗng hoặc không đầy đủ.

Lỗi xảy ra ở một phiên bản bài báo không nên làm dừng toàn bộ quá trình xử lý những bài báo khác.

Mỗi tác vụ cần có trạng thái xử lý và mô tả lỗi tương ứng để thuận tiện cho việc theo dõi và khôi phục.

---

## 9. Tích hợp với các thành viên khác

Member 2 phụ thuộc vào dữ liệu đầu ra từ giai đoạn Discovery của Member 1.

Quy trình tích hợp dự kiến:

```text
Member 1: Paper Discovery
          |
          v
Version Task Manifest
          |
          v
Member 2: Download + Extract + Parse
          |
          v
Structured Paper Data
          |
          v
Member 3: Reference / BibTeX Processing
          |
          v
Member 4: Quality Matching
          |
          v
Member 5: Book / Poster Processing
```

Các giao diện và cấu trúc dữ liệu đầu ra cần được thống nhất với các thành viên khác trước khi tích hợp chính thức.

Điều kiện cần đảm bảo:

- Giữ nguyên mã định danh bài báo và phiên bản.
- Theo dõi được trạng thái xử lý từng tác vụ.
- Đầu ra tương thích với các module xử lý phía sau.
- Có thể xác định và xử lý lại các tác vụ thất bại.
- Không âm thầm bỏ qua dữ liệu bị thiếu hoặc không hợp lệ.

---

## 10. Các yêu cầu về bảo mật

Mã nguồn bài báo tải từ Internet được xem là dữ liệu đầu vào không đáng tin cậy.

Extractor tuyệt đối không được cho phép tệp nén:

- Ghi tệp ra ngoài thư mục giải nén được chỉ định.
- Ghi đè các tệp không liên quan trong dự án.
- Tạo Symbolic Link không an toàn.
- Làm cạn kiệt dung lượng lưu trữ do giải nén quá mức.
- Tiêu thụ tài nguyên hệ thống không kiểm soát.

Tất cả đường dẫn bên trong tệp nén cần được kiểm tra trước khi thực hiện giải nén.

---

## 11. Checklist hoàn thành

- [ ] Tìm hiểu cấu trúc manifest từ Member 1.
- [ ] Xây dựng chức năng tải mã nguồn.
- [ ] Xử lý retry và timeout.
- [ ] Xây dựng chức năng giải nén an toàn.
- [ ] Kiểm tra đường dẫn và giới hạn giải nén.
- [ ] Xác định tệp LaTeX chính.
- [ ] Phân tích đệ quy `\input` và `\include`.
- [ ] Trích xuất cấu trúc phân cấp tài liệu.
- [ ] Trích xuất công thức, hình ảnh, bảng và danh sách.
- [ ] Xây dựng thuật toán tách câu.
- [ ] Trích xuất thông tin tài liệu tham khảo.
- [ ] Xử lý trường hợp thiếu hoặc không hợp lệ mã nguồn LaTeX.
- [ ] Xuất dữ liệu phân tích có cấu trúc.
- [ ] Viết unit test cho từng thành phần.
- [ ] Chạy kiểm thử và lưu kết quả.
- [ ] Tích hợp với pipeline tổng thể.
- [ ] Hoàn thiện tài liệu hướng dẫn và các giới hạn đã biết.

---

## 12. Thông tin đóng góp

| Thuộc tính | Thông tin |
|---|---|
| Thành viên | Member 2 - Khánh An - |
| Nhánh Git | `member-2/source-parsing` |
| Phạm vi phụ trách | Tải mã nguồn, giải nén an toàn và phân tích LaTeX phân cấp |
| Repository | https://github.com/bingsu1103/nmkhdl-project-1 |

Các thay đổi cần được commit lên nhánh được phân công. Sau khi hoàn thành kiểm thử và xác nhận khả năng tương thích với các thành phần khác, tiến hành tạo Pull Request để tích hợp vào nhánh chính của dự án.
