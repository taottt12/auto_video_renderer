from __future__ import annotations

import ctypes
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src_app.core.paths import LOG_DIR

# Global NVML cache for ultra-fast in-process querying
_NVML_INITIALIZED = False
_NVML_HANDLE = None
_NVML_GPU_NAME = ""
_NVML_LOCK = threading.Lock()


def _init_nvml_if_possible() -> bool:
    global _NVML_INITIALIZED, _NVML_HANDLE, _NVML_GPU_NAME
    with _NVML_LOCK:
        if _NVML_INITIALIZED:
            return _NVML_HANDLE is not None
        _NVML_INITIALIZED = True
        try:
            nvml = ctypes.CDLL("nvml.dll")
            if nvml.nvmlInit_v2() == 0:
                handle = ctypes.c_void_p()
                if nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) == 0:
                    _NVML_HANDLE = handle
                    name_buf = ctypes.create_string_buffer(96)
                    if nvml.nvmlDeviceGetName(handle, name_buf, 96) == 0:
                        _NVML_GPU_NAME = name_buf.value.decode("utf-8", errors="ignore")
                    return True
        except Exception:
            _NVML_HANDLE = None
        return False


def get_system_gpu_metrics() -> Dict[str, Any]:
    """Lấy thông số GPU VRAM và System RAM bằng Ctypes NVML hoặc nvidia-smi an toàn."""
    metrics: Dict[str, Any] = {
        "gpu_name": "unavailable",
        "vram_total_mb": 0.0,
        "vram_used_mb": 0.0,
        "vram_free_mb": 0.0,
        "gpu_util_pct": 0.0,
        "mem_util_pct": 0.0,
        "ram_used_mb": 0.0,
        "ram_total_mb": 0.0,
        "ram_util_pct": 0.0,
    }

    # 1. Đo System RAM qua Windows API
    if os.name == "nt":
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total_mb = stat.ullTotalPhys / (1024 * 1024)
                avail_mb = stat.ullAvailPhys / (1024 * 1024)
                used_mb = total_mb - avail_mb
                metrics["ram_total_mb"] = round(total_mb, 1)
                metrics["ram_used_mb"] = round(used_mb, 1)
                metrics["ram_util_pct"] = int(stat.dwMemoryLoad)
        except Exception:
            pass

    # 2. Đo GPU qua NVML DLL (Microsecond in-process)
    nvml_ok = _init_nvml_if_possible()
    if nvml_ok and _NVML_HANDLE is not None:
        try:
            nvml = ctypes.CDLL("nvml.dll")
            metrics["gpu_name"] = _NVML_GPU_NAME

            class Memory(ctypes.Structure):
                _fields_ = [
                    ("total", ctypes.c_ulonglong),
                    ("free", ctypes.c_ulonglong),
                    ("used", ctypes.c_ulonglong),
                ]

            mem = Memory()
            if nvml.nvmlDeviceGetMemoryInfo(_NVML_HANDLE, ctypes.byref(mem)) == 0:
                metrics["vram_total_mb"] = round(mem.total / (1024 * 1024), 1)
                metrics["vram_used_mb"] = round(mem.used / (1024 * 1024), 1)
                metrics["vram_free_mb"] = round(mem.free / (1024 * 1024), 1)

            class Utilization(ctypes.Structure):
                _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

            u = Utilization()
            if nvml.nvmlDeviceGetUtilizationRates(_NVML_HANDLE, ctypes.byref(u)) == 0:
                metrics["gpu_util_pct"] = float(u.gpu)
                metrics["mem_util_pct"] = float(u.memory)
            return metrics
        except Exception:
            pass

    # 3. Fallback sang nvidia-smi nếu NVML DLL không nạp được
    try:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,utilization.memory",
                "--format=csv,noheader,nounits",
            ],
            creationflags=creation_flags,
            timeout=1.5,
            text=True,
            encoding="utf-8",
            errors="ignore",
        ).strip()
        if out:
            parts = [p.strip() for p in out.split(",")]
            if len(parts) >= 6:
                metrics["gpu_name"] = parts[0]
                metrics["vram_total_mb"] = float(parts[1])
                metrics["vram_used_mb"] = float(parts[2])
                metrics["vram_free_mb"] = float(parts[3])
                metrics["gpu_util_pct"] = float(parts[4])
                metrics["mem_util_pct"] = float(parts[5])
    except Exception:
        pass

    return metrics


class JobLogger:
    """Hệ thống logging có cấu trúc chuẩn JSON Lines (.jsonl) xuyên suốt vòng đời render job."""

    def __init__(
        self,
        job_id: str,
        run_id: str = "run_01",
        log_dir: Optional[Path] = None,
    ) -> None:
        self.job_id = str(job_id or f"job_{int(time.time())}")
        self.run_id = str(run_id or "run_01")
        base_dir = log_dir or (LOG_DIR / "render")
        self.job_dir = base_dir / self.job_id
        self.job_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.job_dir / f"{self.run_id}.jsonl"

        self.start_time = time.time()
        self.active_stage = "init"
        self.stage_start_time = self.start_time
        self._lock = threading.Lock()

    def set_stage(self, stage: str) -> None:
        """Cập nhật giai đoạn xử lý hiện tại để tính elapsed_ms theo từng stage."""
        with self._lock:
            self.active_stage = str(stage)
            self.stage_start_time = time.time()

    def log_event(
        self,
        event: str,
        stage: str = "",
        level: str = "INFO",
        data: Optional[Dict[str, Any]] = None,
        error: Optional[Exception] = None,
        error_type: str = "",
        error_message: str = "",
        traceback_str: str = "",
    ) -> Dict[str, Any]:
        """Ghi một sự kiện đơn lẻ thành một dòng JSON chuẩn vào file log của job."""
        now_dt = datetime.now(timezone.utc).astimezone()
        now_ts = time.time()

        err_cls = error_type or (type(error).__name__ if error else "")
        err_msg = error_message or (str(error) if error else "")
        tb_str = traceback_str or (traceback.format_exc() if error and not traceback_str else "")

        curr_stage = stage or self.active_stage

        record: Dict[str, Any] = {
            "timestamp": now_dt.isoformat(),
            "level": str(level).upper(),
            "event": str(event),
            "job_id": self.job_id,
            "run_id": self.run_id,
            "stage": curr_stage,
            "elapsed_ms": round((now_ts - self.start_time) * 1000.0, 2),
            "stage_elapsed_ms": round((now_ts - self.stage_start_time) * 1000.0, 2),
            "thread_name": threading.current_thread().name,
        }

        if err_cls:
            record["error_type"] = err_cls
            record["error_message"] = err_msg
            if tb_str and tb_str.strip() != "NoneType: None":
                record["traceback"] = tb_str.strip()

        if data:
            # Chuẩn hóa data an toàn, tránh object không serialize được
            safe_data: Dict[str, Any] = {}
            for k, v in data.items():
                if isinstance(v, (str, int, float, bool, list, dict)) or v is None:
                    safe_data[k] = v
                else:
                    safe_data[k] = str(v)
            record["data"] = safe_data

        line_str = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(line_str)
            except Exception as write_err:
                # Không bao giờ để lỗi ghi log làm crash cả chương trình
                sys.stderr.write(f"[JobLogger Error] {write_err}\n")

        return record

    @classmethod
    def cleanup_old_logs(
        cls,
        max_age_days: int = 14,
        max_total_mb: float = 200.0,
        base_dir: Optional[Path] = None,
    ) -> None:
        """Dọn dẹp các log cũ hơn max_age_days hoặc vượt quá hạn mức dung lượng."""
        render_logs = base_dir or (LOG_DIR / "render")
        if not render_logs.exists():
            return

        now = time.time()
        max_age_sec = max_age_days * 86400
        all_job_dirs = [d for d in render_logs.iterdir() if d.is_dir()]

        # 1. Xóa theo tuổi
        remaining_dirs = []
        for jd in all_job_dirs:
            try:
                mtime = jd.stat().st_mtime
                if now - mtime > max_age_sec:
                    shutil.rmtree(jd, ignore_errors=True)
                else:
                    remaining_dirs.append(jd)
            except Exception:
                pass

        # 2. Xóa theo dung lượng nếu vượt quá max_total_mb
        try:
            total_bytes = sum(
                f.stat().st_size
                for d in remaining_dirs
                for f in d.rglob("*")
                if f.is_file()
            )
            limit_bytes = int(max_total_mb * 1024 * 1024)
            if total_bytes > limit_bytes:
                # Sắp xếp thư mục từ cũ nhất đến mới nhất
                remaining_dirs.sort(key=lambda d: d.stat().st_mtime)
                for old_d in remaining_dirs:
                    if total_bytes <= limit_bytes:
                        break
                    dir_size = sum(f.stat().st_size for f in old_d.rglob("*") if f.is_file())
                    shutil.rmtree(old_d, ignore_errors=True)
                    total_bytes -= dir_size
        except Exception:
            pass


class GpuTelemetrySampler(threading.Thread):
    """Luồng chạy ngầm lấy mẫu tài nguyên GPU/VRAM/RAM định kỳ mà không gây chậm render."""

    def __init__(
        self,
        logger: JobLogger,
        interval_sec: float = 2.0,
    ) -> None:
        super().__init__(daemon=True, name=f"GpuTelemetry-{logger.job_id}")
        self.logger = logger
        self.interval_sec = max(0.5, float(interval_sec))
        self._stop_event = threading.Event()
        self.peak_vram_used_mb = 0.0
        self.peak_ram_used_mb = 0.0
        self.sample_count = 0
        self._metrics_lock = threading.Lock()

    def stop(self) -> None:
        self._stop_event.set()

    def get_peak_metrics(self) -> Dict[str, float]:
        with self._metrics_lock:
            return {
                "peak_vram_used_mb": self.peak_vram_used_mb,
                "peak_ram_used_mb": self.peak_ram_used_mb,
                "sample_count": self.sample_count,
            }

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                metrics = get_system_gpu_metrics()
                vram_used = float(metrics.get("vram_used_mb", 0.0))
                ram_used = float(metrics.get("ram_used_mb", 0.0))

                with self._metrics_lock:
                    self.sample_count += 1
                    if vram_used > self.peak_vram_used_mb:
                        self.peak_vram_used_mb = vram_used
                    if ram_used > self.peak_ram_used_mb:
                        self.peak_ram_used_mb = ram_used

                self.logger.log_event(
                    event="gpu_metrics_sample",
                    level="DEBUG",
                    data=metrics,
                )
            except Exception:
                pass

            if self._stop_event.wait(self.interval_sec):
                break
