"""
Module metrics.py: Đo lường tài nguyên (RAM, Disk, Wall-clock Time) và tạo summary.json.
Thuộc sở hữu của Member 4 - Data Quality, Schema và Storage Owner.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil


class ResourceMonitor:
    """
    Tiến trình theo dõi tài nguyên RAM và Disk chạy nền (background sampler).
    Đo đạc Peak RAM, Average RAM, và Maximum Disk Usage.
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        interval_sec: float = 0.5,
        disk_interval_sec: float = 2.0,
    ):
        self.data_dir = Path(data_dir) if data_dir else None
        self.interval_sec = interval_sec
        self.disk_interval_sec = disk_interval_sec
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.rss_samples: List[int] = []
        self.disk_samples: List[int] = []
        self.timestamps: List[float] = []

    def start(self) -> None:
        """Bắt đầu thu thập số liệu tài nguyên."""
        self._stop_event.clear()
        self.rss_samples.clear()
        self.disk_samples.clear()
        self.timestamps.clear()

        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def _sample_loop(self) -> None:
        process = psutil.Process(os.getpid())
        last_disk_time = 0.0
        current_disk_bytes = 0

        while not self._stop_event.is_set():
            now = time.monotonic()
            try:
                # 1. Đo RAM (RSS bytes của tiến trình hiện tại + các tiến trình con nếu có)
                mem_info = process.memory_info()
                rss = mem_info.rss
                for child in process.children(recursive=True):
                    try:
                        rss += child.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                # 2. Đo dung lượng thư mục dữ liệu (Đo định kỳ theo disk_interval_sec để tránh nghẽn I/O)
                if (now - last_disk_time >= self.disk_interval_sec or last_disk_time == 0.0) and self.data_dir and self.data_dir.exists():
                    total_disk = 0
                    for dirpath, _, filenames in os.walk(self.data_dir):
                        for f in filenames:
                            fp = os.path.join(dirpath, f)
                            try:
                                if not os.path.islink(fp):
                                    total_disk += os.path.getsize(fp)
                            except OSError:
                                pass
                    current_disk_bytes = total_disk
                    last_disk_time = now

                # Đảm bảo cả 3 danh sách luôn đồng bộ độ dài 100%
                self.rss_samples.append(rss)
                self.disk_samples.append(current_disk_bytes)
                self.timestamps.append(now)
            except Exception:
                pass

            time.sleep(self.interval_sec)

    def stop(self) -> Dict[str, float]:
        """Dừng thu thập và tính toán các chỉ số thống kê (bao gồm Time-Weighted Average RAM)."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

        # Tính dung lượng lưu trữ cuối cùng
        final_disk_bytes = 0
        if self.data_dir and self.data_dir.exists():
            for dirpath, _, filenames in os.walk(self.data_dir):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        if not os.path.islink(fp):
                            final_disk_bytes += os.path.getsize(fp)
                    except OSError:
                        pass

        peak_ram_bytes = max(self.rss_samples) if self.rss_samples else 0
        avg_ram_bytes = sum(self.rss_samples) / len(self.rss_samples) if self.rss_samples else 0
        # max_disk_bytes không thể nhỏ hơn final_disk_bytes
        sampled_max_disk = max(self.disk_samples) if self.disk_samples else 0
        max_disk_bytes = max(sampled_max_disk, final_disk_bytes)

        # Tính Time-weighted Average RAM (theo hình thang trên chuỗi thời gian monotonic)
        time_weighted_ram_bytes = 0.0
        if len(self.rss_samples) > 1:
            total_duration = self.timestamps[-1] - self.timestamps[0]
            if total_duration > 0:
                weighted_sum = sum(
                    (self.rss_samples[i] + self.rss_samples[i + 1]) / 2 * (self.timestamps[i + 1] - self.timestamps[i])
                    for i in range(len(self.rss_samples) - 1)
                )
                time_weighted_ram_bytes = weighted_sum / total_duration
        if time_weighted_ram_bytes == 0.0:
            time_weighted_ram_bytes = avg_ram_bytes

        return {
            "peak_ram_mb": round(peak_ram_bytes / (1024 * 1024), 2),
            "avg_ram_mb": round(avg_ram_bytes / (1024 * 1024), 2),
            "time_weighted_ram_mb": round(time_weighted_ram_bytes / (1024 * 1024), 2),
            "max_disk_mb": round(max_disk_bytes / (1024 * 1024), 2),
            "final_storage_mb": round(final_disk_bytes / (1024 * 1024), 2),
            "sample_count": len(self.rss_samples),
            "sampling_interval_sec": self.interval_sec,
        }


def generate_benchmark_summary(
    stats_crawling: Dict[str, Any],
    performance_metrics: Dict[str, Any],
    output_path: Path,
    git_sha: str = "unknown",
) -> Dict[str, Any]:
    """
    Tạo file summary.json chuẩn hóa theo hợp đồng để Member 5 dùng làm đầu vào cho Jupyter Book.
    """
    summary = {
        "metadata": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "git_sha": git_sha,
            "environment": {
                "os": platform.platform(),
                "python_version": sys.version.split()[0],
                "cpu_count": psutil.cpu_count(logical=True),
                "total_system_ram_mb": round(psutil.virtual_memory().total / (1024 * 1024), 2),
            },
        },
        "crawl_statistics": {
            "total_assigned": stats_crawling.get("total_assigned", 0),
            "papers_scraped_successfully": stats_crawling.get("papers_scraped_successfully", 0),
            "paper_success_rate": stats_crawling.get("paper_success_rate", 0.0),
            "avg_original_source_bytes": stats_crawling.get("avg_original_source_bytes", 0.0),
            "avg_filtered_source_bytes": stats_crawling.get("avg_filtered_source_bytes", 0.0),
            "reduction_rate": stats_crawling.get("reduction_rate", 0.0),
            "avg_all_references_per_paper": stats_crawling.get("avg_all_references_per_paper", 0.0),
            "avg_eligible_arxiv_references_per_paper": stats_crawling.get("avg_eligible_arxiv_references_per_paper", 0.0),
            "reference_metadata_success_rate": stats_crawling.get("reference_metadata_success_rate", 0.0),
        },
        "performance_metrics": performance_metrics,
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary
