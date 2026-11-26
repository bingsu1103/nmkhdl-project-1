# Limitations and Threats to Validity

## 1. Phạm vi báo cáo

Các kết quả định lượng trong chương M1 này chỉ phản ánh shard Member 5 với 5.000 paper IDs. Chưa gộp shard của các thành viên khác; do đó không được trình bày các con số này như kết quả toàn nhóm 25.000 IDs.

## 2. Source retrieval

Trong 7.806 version tasks, có 7.217 `success`, 543 `no_tex_bib`, 41 `http_error` và 5 `invalid_archive`. Tất cả version tasks đều có terminal status, nhưng 46 trường hợp HTTP/archive vẫn là lỗi retrieval. `no_tex_bib` được giữ như một trạng thái tường minh, không bị loại khỏi manifest.

## 3. Semantic Scholar

Có 4.994 kết quả `ok`, 6 `not_found` và 0 `failed`. Các references không có arXiv ID không được đưa vào bảng references theo schema M1 nhưng vẫn được giữ trong dữ liệu làm việc. Có 234 references đủ điều kiện thiếu submission date; không tự điền giá trị không có nguồn.

## 4. Benchmark

Chưa có log kiểm chứng về runtime, RAM trung bình/cực đại, peak disk và final output size. Benchmark chính thức cần thực hiện trên Google Colab CPU-only. Hai tổng dung lượng archive và TeX/Bib không thể thay thế các chỉ số này.

## 5. Tính tái lập và trách nhiệm dữ liệu

Khi tổng hợp toàn nhóm, cần giữ rõ nguồn gốc shard, commit SHA, run ID, input checksum và các manifest trạng thái. Không sửa status hoặc loại bỏ các trường hợp thất bại để cải thiện tỷ lệ. Dữ liệu thô, corpus, cache, checkpoint và Parquet không được đưa vào code repository.
