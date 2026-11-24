# Hướng Dẫn Gán Nhãn Tham Chiếu Milestone 3 (Thủ Công & Tự Động)

Tài liệu này hướng dẫn toàn bộ thành viên (`member-1` đến `member-5`) thực hiện **Bước 1 (gán nhãn thủ công)** và **Bước 2 (gán nhãn tự động)** cho bài toán **Reference Matching** trên shard `--data-dir` riêng của từng người.

---

## 1. Mục tiêu & Quota theo đề bài (mỗi thành viên `k = 1`)

| Hạng mục | Yêu cầu tối thiểu / thành viên | Ghi chú |
|---|---|---|
| **Gán nhãn thủ công** (`manual_labels.json`) | **>= 5 bài báo**, mỗi bài **>= 20** BibTeX entries, tổng **>= 100** entries | Phải gán nhãn 100% entries của các bài được chọn |
| **Gán nhãn tự động** (`auto_labels.json`) | **>= 10%** số bài còn lại ngoài tập manual (tối thiểu `>= 2` bài) | Mặc định `--fraction 0.12` (12%) để đảm bảo dư chuẩn |
| **Phạm vi ứng viên** | Chỉ match với `ref_arxiv_id` có trong `tables/references` của **cùng bài báo** | Nếu không có trong `references` cùng bài -> `None` (`0=No-Match`) |

> **Lưu ý Git:** Không commit `manual_labels.json`, `auto_labels.json` hay thư mục `tables/` lên GitHub. Sau khi chạy xong trên máy cá nhân, thành viên gửi 2 file JSON trong `<data-dir>/matching/` cho nhóm tổng hợp.

---

## 2. Gán nhãn thủ công — `scripts/label_tool.py`

### 2.1. Cách chạy cho từng thành viên

Thay `<MEMBER_ID>` (`member-1`..`member-5`) và `<DATA_DIR>` bằng thư mục dữ liệu của bạn:

1. **(Tuỳ chọn) Xem trước danh sách bài đủ chuẩn chưa gán nhãn:**
   ```powershell
   python scripts/label_tool.py --data-dir <DATA_DIR> --member <MEMBER_ID> --list-candidates
   ```
2. **Mở tool gán nhãn tương tác:**
   ```powershell
   python scripts/label_tool.py --data-dir <DATA_DIR> --member <MEMBER_ID>
   ```
   - Lần đầu chạy (chưa có `manual_labels.json`), tool tự chọn `5` bài hợp lệ (`--min-entries 20`, `--min-refs 5`) trong `<DATA_DIR>`, ưu tiên các bài gọn (`>= 20` entries nhỏ nhất trước) và có nhiều arXiv references.
   - Tiến độ được lưu nguyên tử sau mỗi thao tác vào `<DATA_DIR>/matching/manual_labels.json`; thoát giữa chừng rồi chạy lại lệnh trên sẽ tự **resume** đúng entry đang làm dở.
3. **Nghiệm thu sau khi gán xong:**
   ```powershell
   python scripts/label_tool.py --data-dir <DATA_DIR> --member <MEMBER_ID> --verify-only
   ```
   Đạt chuẩn khi kết quả in ra `"is_valid": true` và `"errors": []`.

### 2.2. Các tham số dòng lệnh chính

| Tham số | Mặc định | Mô tả |
|---|---|---|
| `--data-dir` | *(bắt buộc)* | Thư mục chứa `tables/papers`, `tables/bibtex`, `tables/references` |
| `--member` | `member-4` | Mã thành viên (`member-1`..`member-5`) |
| `--paper` | `[]` | Chỉ định thủ công ID bài báo (truyền lặp nhiều lần) |
| `--num-papers` | `5` | Số bài tự động chọn khi chạy mới hoặc bật `--auto-pick` |
| `--min-entries` | `20` | Số BibTeX entry tối thiểu của mỗi bài tự chọn |
| `--min-refs` | `5` | Số arXiv reference tối thiểu của mỗi bài tự chọn |
| `--auto-pick` | `False` | Chọn thêm `--num-papers` bài mới chưa gán nhãn dù đã có file cũ |
| `--exclude-labels` | `[]` | File `manual_labels.json` khác để loại trừ các bài đã gán (khi dùng chung dataset) |
| `--list-candidates` | `False` | Liệt kê các bài đủ điều kiện chưa gán nhãn rồi thoát |
| `--output` | `<data-dir>/matching/manual_labels.json` | Đổi đường dẫn file JSON đầu ra |
| `--verify-only` | `False` | Kiểm tra quota, tính đầy đủ và ràng buộc khóa ngoại của file nhãn |

### 2.3. Phím điều khiển khi gán nhãn

- **`1`..`5`** (hoặc `1..N` sau khi mở hết): chọn ứng viên đúng.
- **`0`**: **No-Match** (`None`) khi không có ứng viên nào khớp trong `references` của bài báo.
- **`a`**: bung **toàn bộ** `references` arXiv của bài báo (`ShowAll`) nếu chưa thấy trong Top 5.
- **`b`**: quay lại entry ngay trước đó (`Back`) để sửa.
- **`n`**: thêm / sửa / xóa ghi chú (`EditNote`, bỏ trống rồi Enter để xóa).
- **`Enter`**: giữ nguyên nhãn cũ (`Enter=Keep`, chỉ hiện khi xem lại entry đã gán).
- **`q`**: lưu và thoát (`Save&Quit`).
- Khi đã gán đủ **100%**, chạy lại tool cho phép chọn `[r]` (xem lại từ `#1`), `[e]` (nhảy tới entry số bất kỳ), hoặc `Enter`/`[q]` để thoát.

### 2.4. Nguyên tắc quyết định `Match` vs `No-Match`

1. **Đối chiếu `Title` + `Authors` + `Year`/`Extra` (`url`, `doi`)**:
   - Chọn `1..N` khi tiêu đề trùng khớp (chấp nhận khác nhẹ viết hoa, dấu câu, LaTeX hoặc bản preprint cùng bài) và nhóm tác giả khớp hợp lý.
   - Cảnh giác bài cùng nhóm tác giả + cùng năm nhưng **khác bài báo** (chỉ trùng từ khóa chung).
2. **Chỉ match trong tập `tables/references` của cùng bài báo**:
   - Nếu mục BibTeX là sách, website, thư viện phần mềm, bài hội nghị không có trên arXiv, hoặc có URL arXiv nhưng **không có trong danh sách `references` của bài đó** (do Semantic Scholar API thiếu), luôn bấm `a` kiểm tra hết danh sách rồi chọn **`0` (`No-Match`)**.
3. **Chú ý nhãn `[USED by ...]`**:
   - Nếu một ứng viên đã được gán cho `citation_key` khác trong cùng bài, kiểm tra lại để tránh gán nhầm 2 trích dẫn khác nhau vào cùng 1 paper (trừ trường hợp tác giả gốc trích dẫn lặp).

---

## 3. Gán nhãn tự động — `scripts/auto_label.py`

### 3.1. Cơ chế tính điểm (`src/label.py`)

`heuristic_match_publication` / `heuristic_match_entry` trong `src/label.py` tính điểm tương đồng cho từng cặp `(bib_entry, ref)`:

$$\text{total\_score} = \text{title\_jaccard}\ [0..1.0] + \text{author\_bonus}\ (0.15) + \text{year\_bonus}\ (0.10)$$

- Thang điểm tối đa là **`1.25`**.
- Nếu điểm cao nhất `< --threshold`, entry được gán `None` (`No-Match`); ngược lại gán `ref_arxiv_id` chuẩn hóa.
- **Ngưỡng mặc định `--threshold 0.75`** (hệ thống chấp nhận trong `[0.0, 1.25]`; benchmark trên 101 nhãn tay của `member-4` cho kết quả `acc = 0.990`, `precision = 1.000`, `recall = 0.985` ở mức `0.65`–`0.75`, với nhóm `No-Match` cao nhất chỉ đạt `0.635`).

### 3.2. Cách chạy cho từng thành viên

1. **Sinh file gán nhãn tự động (sau khi đã có `manual_labels.json`):**
   ```powershell
   python scripts/auto_label.py --data-dir <DATA_DIR> --member <MEMBER_ID>
   ```
   Script sẽ:
   - Tự động loại bỏ toàn bộ các bài đã nằm trong `manual_labels.json`.
   - Lấy mẫu ngẫu nhiên tất định (`--seed 42`) đúng `--fraction 0.12` (12%) số bài ngoài tập manual (từ các bài có ít nhất `--min-entries 1` BibTeX và `--min-refs 1` arXiv reference).
   - Gán nhãn toàn bộ BibTeX entries của các bài được chọn, ghi ra `<DATA_DIR>/matching/auto_labels.json` và chạy `validate_labeling_quota(..., num_members=1)`.

2. **Kiểm tra lại file `auto_labels.json` bất kỳ lúc nào:**
   ```powershell
   python scripts/auto_label.py --data-dir <DATA_DIR> --member <MEMBER_ID> --verify-only
   ```

### 3.3. Cấu trúc JSON đầu ra

Cả `manual_labels.json` và `auto_labels.json` dùng chung cấu trúc để bước train/split (`create_publication_split`, `validate_labeling_quota`) đọc trực tiếp:
- `selected_papers`: danh sách `arxiv_id` đã chuẩn hóa.
- `publications`: thống kê từng bài (`arxiv_id`, `method`, `labeled_by`, `entries_count`, `labeled_count`, `matched_count`).
- `labels`: từng cặp `(arxiv_id, citation_key)` kèm `groundtruth_arxiv_id` (`string` chuẩn hóa không kèm version, hoặc `null` nếu No-Match), `method`, `labeled_by`.
