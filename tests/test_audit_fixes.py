from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
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
from src_app.core.subtitle_worker import _checkpoint_path, _load_checkpoint, _save_checkpoint


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

    def test_whisper_and_nvenc_share_one_gpu_gate(self):
        """NVENC không được chen vào trong lúc Whisper đang giữ VRAM."""
        entered_nvenc = threading.Event()

        def try_nvenc():
            with GpuResourceManager.acquire_nvenc_gpu(timeout=1.0):
                entered_nvenc.set()

        with GpuResourceManager.acquire_whisper_gpu():
            thread = threading.Thread(target=try_nvenc)
            thread.start()
            time.sleep(0.1)
            self.assertFalse(entered_nvenc.is_set())

        thread.join(timeout=2.0)
        self.assertTrue(entered_nvenc.is_set())

    def test_whisper_checkpoint_round_trip(self):
        out_path = self.logger.job_dir / "subtitle.srt"
        signature = {"model": "turbo", "chunks": 2}
        segments = [{"start": 0.0, "end": 1.0, "text": "hello"}]
        _save_checkpoint(out_path, signature, segments, {0}, "en")

        loaded_segments, completed, language = _load_checkpoint(out_path, signature)
        self.assertEqual(loaded_segments, segments)
        self.assertEqual(completed, {0})
        self.assertEqual(language, "en")
        self.assertTrue(_checkpoint_path(out_path).exists())

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

    def test_audio_cleanup_is_combined_into_normalize_pass(self):
        calls = []
        engine = RenderEngine(settings={
            "filter_bgm_after_30s": True,
            "background_music": {"enabled": False},
            "promo_audio": {"enabled": False},
        })
        engine._run = lambda cmd, stage, *args, **kwargs: calls.append((cmd, stage))
        with tempfile.TemporaryDirectory() as tmp:
            result = engine._build_final_audio(Path(tmp) / "input.mp3", Path(tmp), 3600.0, 1.0)
        self.assertEqual(len(calls), 1, "Normalize và lọc voice phải dùng chung một lần encode AAC")
        self.assertIn("-filter_complex", calls[0][0])
        self.assertIn("asplit=2", calls[0][0][calls[0][0].index("-filter_complex") + 1])
        self.assertEqual(result.name, "main_audio.m4a")

    def test_animated_layout_is_replaced_by_reusable_overlay(self):
        engine = RenderEngine(settings={"export": {"fps": 25}})
        created_files = []

        def fake_run(cmd, stage, *args, **kwargs):
            out = Path(cmd[-1])
            out.write_bytes(b"0" * 12000)
            created_files.append(out)

        engine._run = fake_run
        with tempfile.TemporaryDirectory() as tmp:
            gif = Path(tmp) / "badge.gif"
            gif.write_bytes(b"GIF89a-test")
            layers = [{
                "type": "gif", "file_path": str(gif), "enabled": True,
                "box_x": 0.1, "box_y": 0.2, "box_w": 0.3, "box_h": 0.2,
                "in_effect": "none", "out_effect": "none", "motion_effect": "none",
            }]
            optimized = engine._prepare_cached_animated_layers(layers, 1280, 720, 25)
            self.assertEqual(optimized[0]["type"], "compiled_overlay")
            cached = Path(optimized[0]["file_path"])
            self.assertTrue(cached.exists())
            cached.unlink(missing_ok=True)
        for path in created_files:
            path.unlink(missing_ok=True)

    def test_multiline_dynamic_title_uses_explicit_line_positions(self):
        layer = {
            "type": "text", "name": "title", "enabled": True,
            "text_content": "FIRST LINE\nSECOND LINE", "font_name": "Arial",
            "font_size": 72, "line_spacing": -8, "auto_fit": True,
            "font_color": "#ffffff", "outline_color": "#000000", "outline_width": 2,
            "box_x": 0.1, "box_y": 0.2, "box_w": 0.8, "box_h": 0.3,
            "in_effect": "fade_in", "out_effect": "none", "motion_effect": "none",
        }
        engine = RenderEngine(settings={"layout_studio": {"enabled": True, "layers": [layer]}})
        cmd, filters = [engine.ffmpeg], []
        engine._build_visual_layers_filtergraph(cmd, filters, "[0:v]", 1, 1280, 720, fps=25)
        title_filters = [part for part in filters if "drawtext=" in part]
        self.assertEqual(len(title_filters), 2)
        self.assertTrue(any("FIRST LINE" in part for part in title_filters))
        self.assertTrue(any("SECOND LINE" in part for part in title_filters))
        self.assertTrue(all("\n" not in part and "\r" not in part for part in title_filters))

    def test_project_opening_effect_is_applied_after_visual_layers(self):
        engine = RenderEngine(settings={
            "opening_effect": {
                "enabled": True,
                "mode": "fade_white",
                "duration": 1.2,
            },
            "layout_studio": {"enabled": False, "layers": []},
        })
        cmd, filters = [engine.ffmpeg], []
        last, next_input = engine._build_visual_layers_filtergraph(
            cmd, filters, "[0:v]", 1, 1280, 720, fps=25
        )
        self.assertEqual(next_input, 1)
        self.assertTrue(last.startswith("[v_opening_"))
        self.assertTrue(any("fade=t=in:st=0:d=1.200:color=white" in part for part in filters))
        self.assertTrue(engine._has_visual_overlays())

    def test_project_opening_effect_is_skipped_when_intro_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            intro = Path(tmp) / "intro.mp4"
            intro.write_bytes(b"placeholder")
            engine = RenderEngine(settings={
                "intro_file": str(intro),
                "intro_mode": "sequential",
                "opening_effect": {"enabled": True, "mode": "fade_black", "duration": 0.8},
            })
            self.assertIsNone(engine._active_opening_effect())


if __name__ == "__main__":
    unittest.main()
