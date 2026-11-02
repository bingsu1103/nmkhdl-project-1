"""
Test suite cho module đo lường hiệu năng và tài nguyên (metrics.py).
Thuộc sở hữu của Member 4 - Data Quality, Schema và Storage Owner.
"""

import json
import tempfile
import time
from pathlib import Path

from src.metrics import ResourceMonitor, generate_benchmark_summary


def test_resource_monitor_sampling():
    """Kiểm tra ResourceMonitor thu thập RAM và dung lượng Disk hợp lệ."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        monitor = ResourceMonitor(data_dir=Path(tmp_dir), interval_sec=0.05, disk_interval_sec=0.05)
        monitor.start()

        # Tạo một file tạm khoảng 1MB trong thư mục data_dir
        dummy_file = Path(tmp_dir) / "test_data.bin"
        with open(dummy_file, "wb") as f:
            f.write(b"0" * (1024 * 1024))

        # Chờ 1 chút để monitor kịp lấy mẫu
        time.sleep(0.35)
        metrics = monitor.stop()

        assert metrics["sample_count"] >= 2
        assert metrics["peak_ram_mb"] > 0
        assert metrics["avg_ram_mb"] > 0
        assert metrics["time_weighted_ram_mb"] > 0
        # Disk phải ghi nhận xấp xỉ 1MB
        assert metrics["max_disk_mb"] >= 0.9
        assert metrics["final_storage_mb"] >= 0.9


def test_generate_benchmark_summary():
    """Kiểm tra hàm tạo file summary.json chuẩn hóa theo hợp đồng với Member 5."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        summary_path = Path(tmp_dir) / "summary.json"

        stats_crawling = {
            "total_assigned": 100,
            "papers_scraped_successfully": 98,
            "paper_success_rate": 0.98,
            "avg_original_source_bytes": 1048576,
            "avg_filtered_source_bytes": 262144,
            "reduction_rate": 0.75,
            "avg_all_references_per_paper": 35.2,
            "avg_eligible_arxiv_references_per_paper": 18.5,
            "reference_metadata_success_rate": 0.96,
        }

        perf_metrics = {
            "total_discovery_time_sec": 12.5,
            "total_end_to_end_time_sec": 450.0,
            "avg_time_per_paper_sec": 4.5,
            "peak_ram_mb": 256.0,
            "avg_ram_mb": 180.5,
            "max_disk_mb": 512.0,
            "final_storage_mb": 128.0,
        }

        summary = generate_benchmark_summary(
            stats_crawling=stats_crawling,
            performance_metrics=perf_metrics,
            output_path=summary_path,
            git_sha="abcdef123456",
        )

        assert summary_path.exists()
        with open(summary_path, "r", encoding="utf-8") as f:
            loaded_json = json.load(f)

        assert loaded_json["crawl_statistics"]["paper_success_rate"] == 0.98
        assert loaded_json["performance_metrics"]["peak_ram_mb"] == 256.0
        assert "environment" in loaded_json["metadata"]
        assert loaded_json["metadata"]["git_sha"] == "abcdef123456"
