from __future__ import annotations

import os
import subprocess
from typing import Any, Dict


def hidden_subprocess_kwargs() -> Dict[str, Any]:
    """Return subprocess kwargs that prevent FFmpeg/FFprobe console windows on Windows.

    When the app is launched with pythonw.exe, Windows console executables such as
    ffmpeg.exe can still create a small black CMD window for every subprocess call.
    CREATE_NO_WINDOW + STARTUPINFO hides those child windows so rendering does not
    steal focus while the user is working.
    """
    if os.name != "nt":
        return {}

    kwargs: Dict[str, Any] = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    try:
        startupinfo = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    except Exception:
        # creationflags alone is usually enough. Keep this defensive so the app
        # can still run on unusual Python/Windows builds.
        pass
    return kwargs


def run_hidden(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
    kwargs.update(hidden_subprocess_kwargs())
    return subprocess.run(*args, **kwargs)


def popen_hidden(*args: Any, **kwargs: Any) -> subprocess.Popen:
    kwargs.update(hidden_subprocess_kwargs())
    return subprocess.Popen(*args, **kwargs)


import contextlib
import re
import sys
import threading
from typing import List, Optional


class GpuResourceManager:
    """Quản lý và điều phối tài nguyên GPU/VRAM tập trung, ngăn chặn xung đột giữa PyTorch Whisper và FFmpeg NVENC."""

    _instance: Optional[GpuResourceManager] = None
    _lock = threading.Lock()

    def __new__(cls) -> GpuResourceManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_semaphores()
            return cls._instance

    def _init_semaphores(self) -> None:
        # RTX 2060 6 GB không đủ dư địa để Whisper và NVENC/NVDEC chạy đồng thời.
        # Hai semaphore độc lập trước đây chỉ giới hạn từng loại tác vụ, nhưng vẫn
        # cho phép job A encode trong lúc job B đang transcribe. Dùng chung một cổng
        # GPU để tránh tranh chấp VRAM và driver reset/CUDA error 700.
        self.gpu_heavy_semaphore = threading.Semaphore(1)
        # Giữ alias để tương thích với code/plugin cũ có thể đọc thuộc tính này.
        self.whisper_gpu_semaphore = self.gpu_heavy_semaphore
        self.nvenc_gpu_semaphore = self.gpu_heavy_semaphore

    @classmethod
    @contextlib.contextmanager
    def acquire_whisper_gpu(cls, timeout: float = 3600.0):
        mgr = cls()
        acquired = mgr.whisper_gpu_semaphore.acquire(timeout=timeout)
        if not acquired:
            raise TimeoutError("Không thể giành quyền sử dụng GPU cho Whisper AI sau thời gian chờ.")
        try:
            yield
        finally:
            mgr.whisper_gpu_semaphore.release()
            cls.clean_torch_cuda_vram()

    @classmethod
    @contextlib.contextmanager
    def acquire_nvenc_gpu(cls, timeout: float = 3600.0):
        mgr = cls()
        acquired = mgr.nvenc_gpu_semaphore.acquire(timeout=timeout)
        if not acquired:
            raise TimeoutError("Không thể giành quyền sử dụng GPU cho FFmpeg NVENC sau thời gian chờ.")
        try:
            yield
        finally:
            mgr.nvenc_gpu_semaphore.release()

    @staticmethod
    def clean_torch_cuda_vram() -> None:
        """Giải phóng bộ nhớ PyTorch CUDA an toàn nếu torch đã được nạp."""
        try:
            if "torch" in sys.modules:
                import torch
                if torch.cuda.is_available() and torch.cuda.is_initialized():
                    torch.cuda.empty_cache()
                    if hasattr(torch.cuda, "ipc_collect"):
                        torch.cuda.ipc_collect()
        except Exception:
            pass

    @staticmethod
    def is_gpu_hardware_failure(stderr_content: str, exit_code: int = 0) -> bool:
        """Xác định chính xác xem lỗi xảy ra có phải do phần cứng GPU/CUDA/NVENC hay không."""
        if not stderr_content:
            return False
        lower = stderr_content.lower()

        # Các lỗi tuyệt đối KHÔNG phải lỗi GPU (lỗi ổ đĩa, cú pháp filter, thiếu file)
        non_gpu_indicators = [
            "no space left on device",
            "error code: -28",
            "no such file or directory",
            "permission denied",
            "invalid argument",
            "filter_complex",
            "error reinitializing filters",
            "error initializing complex filters",
            "cannot find a matching stream",
        ]
        for non_gpu in non_gpu_indicators:
            if non_gpu in lower:
                return False

        # Các dấu hiệu lỗi phần cứng GPU/NVENC thực tế
        gpu_error_patterns = [
            r"cannot load nvcuda\.dll",
            r"cannot load nvencodeapi",
            r"out of memory",
            r"out of device memory",
            r"failed to allocate.*cuda",
            r"nvenc.*error",
            r"nvenc.*failed",
            r"device does not support",
            r"driver does not support",
            r"no nvenc capable devices",
            r"an illegal memory access was encountered",
            r"cuda_error",
            r"cuvid.*error",
            r"hardware accelerator.*failed",
            r"hardware device initialization failed",
            r"gpu hardware encode.*error",
            r"error initializing nvenc",
            r"function not implemented",
        ]
        return any(re.search(pat, lower) for pat in gpu_error_patterns)

    @staticmethod
    def strip_cuda_hwaccel_from_cmd(cmd: List[str]) -> List[str]:
        """Loại bỏ cờ -hwaccel cuda một cách an toàn mà không làm mất các chuỗi chứa chữ 'cuda' khác."""
        new_cmd: List[str] = []
        i = 0
        while i < len(cmd):
            if cmd[i] == "-hwaccel" and i + 1 < len(cmd) and cmd[i + 1].lower() == "cuda":
                i += 2  # Bỏ qua cả "-hwaccel" và "cuda"
                continue
            new_cmd.append(cmd[i])
            i += 1
        return new_cmd

