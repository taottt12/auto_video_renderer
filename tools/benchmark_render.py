from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

if sys.platform == "win32" and sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src_app.core.job_logger import JobLogger, GpuTelemetrySampler, get_system_gpu_metrics
from src_app.core.process_utils import GpuResourceManager, run_hidden
from src_app.core.paths import find_binary, TEMP_DIR


def run_benchmark(duration_sec: int = 5) -> dict:
    """Benchmark các thành phần cốt lõi: GPU NVENC, CPU libx264, và VRAM telemetry."""
    print("=" * 60)
    print("BẮT ĐẦU BENCHMARK HỆ THỐNG RENDER AUTO VIDEO RENDERER")
    print("=" * 60)

    ffmpeg = find_binary("ffmpeg.exe") if os.name == "nt" else find_binary("ffmpeg")
    initial_metrics = get_system_gpu_metrics()
    print(f"GPU: {initial_metrics.get('gpu_name')}")
    print(f"VRAM Khởi điểm: {initial_metrics.get('vram_used_mb')} MB / {initial_metrics.get('vram_total_mb')} MB")
    print(f"RAM Khởi điểm:  {initial_metrics.get('ram_used_mb')} MB / {initial_metrics.get('ram_total_mb')} MB")
    print("-" * 60)

    results: dict = {
        "gpu_name": initial_metrics.get("gpu_name"),
        "initial_vram_used_mb": initial_metrics.get("vram_used_mb"),
        "initial_ram_used_mb": initial_metrics.get("ram_used_mb"),
        "benchmarks": {},
    }

    test_dir = TEMP_DIR / "_bench_temp"
    test_dir.mkdir(parents=True, exist_ok=True)

    # 1. Benchmark GPU NVENC
    print(f"[1/2] Đang benchmark GPU Hardware Encoder (NVENC) [{duration_sec}s test clip]...")
    nvenc_out = test_dir / "bench_nvenc.mp4"
    logger_nvenc = JobLogger(job_id="bench_nvenc", run_id="run_01")
    sampler_nvenc = GpuTelemetrySampler(logger_nvenc, interval_sec=0.1)
    sampler_nvenc.start()

    cmd_nvenc = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration_sec}:size=1080x1920:rate=30",
        "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "22",
        "-pix_fmt", "yuv420p",
        str(nvenc_out),
    ]

    t0 = time.time()
    p_nvenc = run_hidden(cmd_nvenc, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    nvenc_elapsed = time.time() - t0
    sampler_nvenc.stop()
    sampler_nvenc.join(timeout=2.0)
    nvenc_peaks = sampler_nvenc.get_peak_metrics()

    nvenc_ok = p_nvenc.returncode == 0 and nvenc_out.exists()
    results["benchmarks"]["nvenc"] = {
        "success": nvenc_ok,
        "elapsed_sec": round(nvenc_elapsed, 2),
        "fps": round((duration_sec * 30) / max(0.01, nvenc_elapsed), 1),
        "peak_vram_used_mb": nvenc_peaks.get("peak_vram_used_mb"),
        "size_kb": round(nvenc_out.stat().st_size / 1024, 1) if nvenc_ok else 0,
    }
    print(f" -> NVENC: {'Thành công' if nvenc_ok else 'Thất bại'} | Thời gian: {nvenc_elapsed:.2f}s | FPS: {results['benchmarks']['nvenc']['fps']} | Peak VRAM: {nvenc_peaks.get('peak_vram_used_mb')} MB")

    # 2. Benchmark CPU libx264
    print(f"[2/2] Đang benchmark CPU Software Encoder (libx264) [{duration_sec}s test clip]...")
    cpu_out = test_dir / "bench_cpu.mp4"
    logger_cpu = JobLogger(job_id="bench_cpu", run_id="run_01")
    sampler_cpu = GpuTelemetrySampler(logger_cpu, interval_sec=0.1)
    sampler_cpu.start()

    cmd_cpu = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration_sec}:size=1080x1920:rate=30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-pix_fmt", "yuv420p",
        str(cpu_out),
    ]

    t0 = time.time()
    p_cpu = run_hidden(cmd_cpu, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    cpu_elapsed = time.time() - t0
    sampler_cpu.stop()
    sampler_cpu.join(timeout=2.0)
    cpu_peaks = sampler_cpu.get_peak_metrics()

    cpu_ok = p_cpu.returncode == 0 and cpu_out.exists()
    results["benchmarks"]["cpu"] = {
        "success": cpu_ok,
        "elapsed_sec": round(cpu_elapsed, 2),
        "fps": round((duration_sec * 30) / max(0.01, cpu_elapsed), 1),
        "peak_vram_used_mb": cpu_peaks.get("peak_vram_used_mb"),
        "size_kb": round(cpu_out.stat().st_size / 1024, 1) if cpu_ok else 0,
    }
    print(f" -> CPU:   {'Thành công' if cpu_ok else 'Thất bại'} | Thời gian: {cpu_elapsed:.2f}s | FPS: {results['benchmarks']['cpu']['fps']} | Peak VRAM: {cpu_peaks.get('peak_vram_used_mb')} MB")

    # Cleanup temp
    shutil.rmtree(test_dir, ignore_errors=True)
    if logger_nvenc.job_dir.exists():
        shutil.rmtree(logger_nvenc.job_dir, ignore_errors=True)
    if logger_cpu.job_dir.exists():
        shutil.rmtree(logger_cpu.job_dir, ignore_errors=True)

    print("=" * 60)
    speedup = round(cpu_elapsed / max(0.01, nvenc_elapsed), 2)
    print(f"TỔNG KẾT: GPU NVENC nhanh gấp {speedup}x so với CPU libx264 trên cùng thiết lập!")
    print("=" * 60)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto Video Renderer Hardware Benchmark")
    parser.add_argument("--duration", type=int, default=5, help="Thời lượng clip test (giây)")
    args = parser.parse_args()
    res = run_benchmark(duration_sec=args.duration)
