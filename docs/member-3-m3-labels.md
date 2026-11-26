# Member 3 — Nhãn matching M3 (gửi M4)

Member 3 (Nguyễn Đức Quang), 24/11/2026. Shard `member-3` (`2510.19401..2510.24400`).

## Lấy file ở đâu

Folder Drive bàn giao của `member-3` (link trong README, mục "Link gói bàn giao"):

- `member-3-m3-labels.zip`: `matching/manual_labels.json` và `matching/auto_labels.json`
- `member-3-m3-labels-info.txt`: cách làm và số liệu
- `member-3-m2-bibtex.zip`: bảng `tables/bibtex` mà các nhãn trên được tạo từ đó

Định dạng JSON đúng như `scripts/label_tool.py` / `scripts/auto_label.py` (`docs/m3-labeling-guide.md`): `selected_papers`, `publications`, `labels[]` với `arxiv_id`, `citation_key`, `groundtruth_arxiv_id` (null = No-Match), `method`, `labeled_by`, `notes`.

## Số liệu

| | Giá trị |
|---|---|
| Manual | 5 bài × 20 entry = 100 nhãn; 57 match, 43 No-Match; `--verify-only`: `is_valid: true` |
| Bài manual | `2510.19872`, `2510.21866`, `2510.22425`, `2510.22700`, `2510.23097` (do `label_tool.py` tự chọn) |
| Auto | `auto_label.py` mặc định (`--fraction 0.12 --seed 42 --threshold 0.75`): 600 bài, 69.974 entry, 13.382 match; quota `is_valid: true` |
| Heuristic so với 100 nhãn manual | accuracy 0,98; precision 1,000; recall 0,965 (bỏ sót 2, không gán sai) |

## Cần biết khi dùng

1. **Manual là nhãn assisted, không phải người gán tay.** Agent AI đề xuất từng entry kèm lý do, sau đó AI duyệt lại: đối chiếu title/tác giả, kiểm tra arXiv URL, tìm match bị sót. Mỗi nhãn ghi rõ trong `notes` (`agent-proposed … | reviewed by Claude (AI), not by a human`). Khi báo cáo nên khai như `docs/member-1-m3-full-shard.md`. Chưa có review chéo của người.
2. **Bảng `bibtex` của shard này dùng parser đã sửa nhưng chưa merge.** Bản `src/bibtex.py` trên máy member-3 parse thêm `\bibitem` kiểu APA/Chicago `(2015). Title.`, apacite `\APACrefatitle`, Springer `\batitle` và kiểu `Tác giả, \emph{Title}, Journal (2012)`. Trên 34.235 `\bibitem` của shard, title rác giảm từ 9.046 xuống 6.064. Code trên `main` vẫn là bản cũ. `citation_key` không đổi giữa hai bản, nên nhãn vẫn khớp với bảng `bibtex` cũ, chỉ title khác.
3. **Định dạng nhãn ≠ `run-matching`.** `run-matching --manual-labels` trên `main` đang đọc file `.jsonl` của `assist-matching-labels`. Nhãn ở đây là JSON của `label_tool.py`. Member 3 chưa kiểm tra `run-matching` có đọc được định dạng này không; M4 xác nhận giúp nên dùng pipeline nào cho bước train.
4. No-Match ở bài `2510.22425` nhiều (13/20) vì phần lớn reference là bài trước khi có arXiv (1952–1993), không phải lỗi gán nhãn.
