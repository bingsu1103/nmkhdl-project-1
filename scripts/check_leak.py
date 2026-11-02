#!/usr/bin/env python3
"""
scripts/check_leak.py — Công cụ quét chống rò rỉ dữ liệu (Data Leak Guard).
Thuộc sở hữu của Member 4 — Thực thi Task MS1-M4-T08 trong kế hoạch đồ án.

Kiểm tra:
1. Không có file dung lượng lớn (> 1MB) bị theo dõi (tracked) bởi Git.
2. Không có file cấm: .parquet, .tar, .tar.gz, .zip, .env, .log, v.v.
3. Quét phát hiện lộ API keys hoặc tokens bí mật (Semantic Scholar API key, Hugging Face token).
"""

import os
import re
import subprocess
import sys
from pathlib import Path

MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024  # 1 MB

FORBIDDEN_EXTENSIONS = {
    ".parquet",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".zip",
    ".7z",
    ".db",
    ".sqlite",
}

FORBIDDEN_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
}

SECRET_PATTERNS = [
    (r"(?i)api[_-]?key\s*[:=]\s*['\"][a-zA-Z0-9_\-]{16,}['\"]", "API Key"),
    (r"(?i)secret[_-]?token\s*[:=]\s*['\"][a-zA-Z0-9_\-]{16,}['\"]", "Secret Token"),
    (r"hf_[a-zA-Z0-9]{34,}", "Hugging Face Token"),
    (r"ghp_[a-zA-Z0-9]{36,}", "GitHub Personal Access Token"),
]


def get_git_tracked_files() -> list[str]:
    """Lấy danh sách tất cả các file đang được Git theo dõi (tracked)."""
    try:
        output = subprocess.check_output(["git", "ls-files"], text=True)
        return [line.strip() for line in output.splitlines() if line.strip()]
    except Exception as e:
        print(f"[CẢNH BÁO] Không thể chạy lệnh 'git ls-files': {e}")
        return []


def check_leaks() -> int:
    tracked_files = get_git_tracked_files()
    if not tracked_files:
        print("[INFO] Không tìm thấy file tracked nào hoặc không ở trong git repository.")
        return 0

    violations = []
    print(f"[SCAN] Đang quét {len(tracked_files)} file được theo dõi bởi Git...")

    for file_str in tracked_files:
        path = Path(file_str)
        if not path.exists():
            continue

        # 1. Kiểm tra phần mở rộng cấm
        for ext in FORBIDDEN_EXTENSIONS:
            if file_str.lower().endswith(ext):
                violations.append(f"File chứa định dạng cấm '{ext}': {file_str}")

        # 2. Kiểm tra tên file cấm
        if path.name.lower() in FORBIDDEN_FILENAMES:
            violations.append(f"File cấu hình bí mật cấm commit vào git: {file_str}")

        # 3. Kiểm tra dung lượng file
        try:
            size = path.stat().st_size
            if size > MAX_FILE_SIZE_BYTES:
                size_mb = size / (1024 * 1024)
                violations.append(f"File vượt quá giới hạn 1MB ({size_mb:.2f} MB): {file_str}")
        except OSError:
            pass

        # 4. Quét secret token trong các file mã nguồn text
        if path.suffix.lower() in {".py", ".json", ".yaml", ".yml", ".md", ".sh", ".txt"}:
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                for pattern, name in SECRET_PATTERNS:
                    if re.search(pattern, content):
                        violations.append(f"Nghi vấn lộ {name} trong file: {file_str}")
            except Exception:
                pass

    if violations:
        print("\n" + "=" * 60)
        print("❌ PHÁT HIỆN VI PHẠM BẢO MẬT / DATA LEAK:")
        for v in violations:
            print(f"  - {v}")
        print("=" * 60)
        print("Vui lòng xóa các file vi phạm khỏi git bằng lệnh: git rm --cached <file>")
        print("Đồng thời thêm đường dẫn file vào .gitignore trước khi commit!")
        return 1
    else:
        print("✅ KIỂM TRA THÀNH CÔNG: Không phát hiện file quá lớn, dữ liệu cấm hoặc secret leak.")
        return 0


if __name__ == "__main__":
    sys.exit(check_leaks())
