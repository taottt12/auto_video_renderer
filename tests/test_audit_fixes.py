from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path

# Thêm thư mục gốc vào sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src_app.core.job_logger import JobLogger, GpuTelemetrySampler, get_system_gpu_metrics
from src_app.core.process_utils import GpuResourceManager
from src_app.core.paths import LOG_DIR
from src_app.core.media_utils import _DURATION_CACHE, _DURATION_CACHE_LOCK
from src_app.core.render_engine import RenderEngine


class TestAuditAndOptimizationFixes(unittest.TestCase):
    """Bộ kiểm thử hồi quy cho các tính năng giám sát, bảo vệ GPU và tối ưu pipeline."""

    def setUp(self):
        self.test_job_id = f"test_audit_{int(time.time())}"
        self.test_run_id = "run_01"
        self.logger = JobLogger(job_id=self.test_job_id, run_id=self.test_run_id)

    def tearDown(self):
        if self.logger.job_dir.exists():
            shutil.rmtree(self.logger.job_dir, ignore_errors=True)

    def test_job_logger_jsonl_structure(self):
        """Kiểm tra cấu trúc và tính hợp lệ của file log JSON Lines."""
        self.logger.log_event("job_started", stage="init", data={"test_param": 123})
        self.logger.log_event("input_validation_started", stage="validate")
        self.logger.log_event("input_validation_completed", stage="validate", data={"size": 1024})
        self.logger.log_event("ffmpeg_command_started", stage="render", data={"cmd": ["ffmpeg", "-version"]})
        self.logger.log_event("output_validation_completed", stage="validate_output", data={"valid": True})
        self.logger.log_event("job_completed", stage="completed")

        self.assertTrue(self.logger.log_file.exists(), "File log JSONL phải tồn tại")
        
        with open(self.logger.log_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        self.assertEqual(len(lines), 6, "Phải có đúng 6 sự kiện được ghi")

        mandatory_fields = {"timestamp", "level", "event", "job_id", "run_id", "stage", "elapsed_ms", "thread_name"}
        for line in lines:
            record = json.loads(line)
            for field in mandatory_fields:
                self.assertIn(field, record, f"Trường bắt buộc '{field}' bị thiếu trong record")
            self.assertEqual(record["job_id"], self.test_job_id)
            self.assertEqual(record["run_id"], self.test_run_id)

    def test_gpu_telemetry_sampler(self):
        """Kiểm tra luồng lấy mẫu GPU VRAM/RAM định kỳ."""
        sampler = GpuTelemetrySampler(self.logger, interval_sec=0.2)
        sampler.start()
        time.sleep(0.65)
        sampler.stop()
        sampler.join(timeout=2.0)

        peak_metrics = sampler.get_peak_metrics()
        self.assertGreaterEqual(peak_metrics["sample_count"], 2, "Bộ lấy mẫu phải thu thập được ít nhất 2 mẫu")
        self.assertGreaterEqual(peak_metrics["peak_ram_used_mb"], 0.0)
        self.assertGreaterEqual(peak_metrics["peak_vram_used_mb"], 0.0)

        with open(self.logger.log_file, "r", encoding="utf-8") as f:
            sample_events = [json.loads(line) for line in f if "gpu_metrics_sample" in line]
        self.assertGreaterEqual(len(sample_events), 2, "File log phải chứa ít nhất 2 sự kiện gpu_metrics_sample")

    def test_gpu_hardware_failure_classification(self):
        """Kiểm tra hàm phân loại lỗi phần cứng GPU vs các lỗi thông thường."""
        # Lỗi GPU/NVENC
        gpu_errors = [
            "CUDA error: an illegal memory access was encountered",
            "Error: Cannot load nvcuda.dll",
            "out of memory while allocating buffer",
            "Failed to allocate CUDA memory surface",
            "nvenc error: initialization failed",
            "Device does not support requested NVENC profile",
        ]
        for err in gpu_errors:
            self.assertTrue(
                GpuResourceManager.is_gpu_hardware_failure(err, exit_code=1),
                f"Phải nhận diện '{err}' là lỗi phần cứng GPU",
            )

        # Lỗi KHÔNG phải GPU
        non_gpu_errors = [
            "No space left on device when writing output",
            "Error code: -28 while writing to disk",
            "No such file or directory: 'input.mp3'",
            "Permission denied: 'out.mp4'",
            "Error initializing complex filters: Invalid syntax",
            "Cannot find a matching stream for unlabeled input",
        ]
        for err in non_gpu_errors:
            self.assertFalse(
                GpuResourceManager.is_gpu_hardware_failure(err, exit_code=1),
                f"Tuyệt đối KHÔNG được nhận diện '{err}' là lỗi phần cứng GPU",
            )

    def test_strip_cuda_hwaccel_from_cmd(self):
        """Kiểm tra loại bỏ cờ -hwaccel cuda an toàn mà không làm mất đường dẫn chứa chữ cuda."""
        cmd = [
            "ffmpeg",
            "-y",
            "-hwaccel", "cuda",
            "-i", "C:/my_cuda_videos/cuda_intro.mp4",
            "-c:v", "libx264",
            "C:/output_cuda/result.mp4",
        ]
        cleaned = GpuResourceManager.strip_cuda_hwaccel_from_cmd(cmd)

        expected = [
            "ffmpeg",
            "-y",
            "-i", "C:/my_cuda_videos/cuda_intro.mp4",
            "-c:v", "libx264",
            "C:/output_cuda/result.mp4",
        ]
        self.assertEqual(cleaned, expected, "Chỉ được xóa cờ '-hwaccel', 'cuda' theo cặp, không làm mất chữ 'cuda' trong path")

    def test_gpu_resource_semaphores(self):
        """Kiểm tra semaphores điều phối tài nguyên GPU của Whisper và NVENC."""
        with GpuResourceManager.acquire_whisper_gpu():
            # Trong lock của Whisper
            pass

        with GpuResourceManager.acquire_nvenc_gpu():
            # Trong lock của NVENC
            pass

    def test_render_engine_initialization_with_logger(self):
        """Kiểm tra RenderEngine tích hợp đầy đủ JobLogger và thuộc tính truy vết."""
        engine = RenderEngine(
            settings={"export": {"width": 1080, "height": 1920}},
            job_id=self.test_job_id,
            run_id=self.test_run_id,
            job_logger=self.logger,
        )
        self.assertEqual(engine.job_id, self.test_job_id)
        self.assertEqual(engine.run_id, self.test_run_id)
        self.assertEqual(engine.job_logger, self.logger)


if __name__ == "__main__":
    unittest.main()
