# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from typing import Any, Dict, List

# Thiết lập bảng mã UTF-8 cho console Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from .paths import CONFIG_PATH
from .settings import SettingsManager


def get_system_gpus() -> List[str]:
    """Lấy danh sách Card màn hình (GPU) trên máy tính qua lệnh hệ thống Windows."""
    gpus: List[str] = []
    try:
        cmd = ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, encoding="utf-8", errors="ignore")
        if res.returncode == 0 and res.stdout.strip():
            for line in res.stdout.strip().splitlines():
                line = line.strip()
                if line and line not in gpus:
                    gpus.append(line)
    except Exception:
        pass
    return gpus


def check_cuda_support() -> Dict[str, Any]:
    """Kiểm tra khả năng tăng tốc GPU NVIDIA CUDA."""
    cuda_devices = 0
    cuda_ok = False
    details = ""
    try:
        import torch
        if torch.cuda.is_available():
            cuda_devices = torch.cuda.device_count()
            dev_name = torch.cuda.get_device_name(0)
            cuda_ok = True
            details = f"Sẵn sàng {cuda_devices} thiết bị CUDA ({dev_name}, PyTorch CUDA)"
        else:
            details = "Không phát hiện thiết bị CUDA khả dụng trong PyTorch"
    except Exception as e:
        details = f"Không nạp được thư viện PyTorch CUDA: {e}"

    return {
        "cuda_ok": cuda_ok,
        "cuda_devices": cuda_devices,
        "details": details
    }


def run_hardware_check(auto_apply: bool = False) -> None:
    """Chạy toàn bộ quy trình kiểm tra phần cứng và gợi ý cấu hình."""
    print("=" * 66)
    print("      🔍 KIỂM TRA PHẦN CỨNG & TỐI ƯU HÓA AUTO VIDEO RENDERER      ")
    print("=" * 66)
    print()

    # 1. Thông tin CPU
    cpu_count = os.cpu_count() or 4
    print(f"🔹 [CPU] Số luồng xử lý: {cpu_count} Threads")

    # 2. Thông tin GPU
    gpus = get_system_gpus()
    print("🔹 [GPU] Card màn hình phát hiện trên máy:")
    has_nvidia = False
    for i, g in enumerate(gpus, 1):
        is_nv = "nvidia" in g.lower() or "geforce" in g.lower() or "rtx" in g.lower() or "gtx" in g.lower()
        if is_nv:
            has_nvidia = True
            print(f"    {i}. ⭐ {g} (Có hỗ trợ NVIDIA NVENC & CUDA)")
        else:
            print(f"    {i}. 💻 {g}")
    if not gpus:
        print("    (Không phát hiện thông tin GPU rời, đang dùng đồ họa cơ bản)")

    # 3. Thông tin CUDA & Whisper AI
    print()
    print("🔹 [AI & ENCODER] Kiểm tra tính tương thích tăng tốc phần cứng:")
    cuda_info = check_cuda_support()
    if cuda_info["cuda_ok"]:
        print(f"    ✔ CUDA GPU: SẴN SÀNG ({cuda_info['details']})")
    else:
        print(f"    ⚠️ CUDA GPU: CHƯA KÍCH HOẠT ({cuda_info['details']})")

    # 4. Đưa ra khuyến nghị
    print()
    print("-" * 66)
    print("💡 ĐỀ XUẤT CẤU HÌNH TỐI ƯU NHẤT CHO MÁY NÀY:")
    print("-" * 66)

    mgr = SettingsManager(CONFIG_PATH)
    cur_settings = mgr.load()
    perf = cur_settings.get("performance", {})
    sub = cur_settings.get("subtitle", {})

    if has_nvidia and cuda_info["cuda_ok"]:
        rec_encoder = "nvidia"
        rec_sub_device = "cuda (float16)"
        rec_threads = 0
        print("✔ Chế độ Render Video: NVIDIA NVENC (GPU) -> Xuất video cực nhanh, siêu nhẹ máy.")
        print("✔ Chế độ Whisper Subtitle: GPU CUDA (float16) -> Quét chữ và sub giọng nói tức thì.")
    else:
        rec_encoder = "cpu"
        rec_sub_device = "cpu (int8)"
        rec_threads = max(1, cpu_count - 2)
        print("✔ Chế độ Render Video: CPU (libx264 đa luồng) -> Tương thích 100%, an toàn và ổn định.")
        print(f"✔ Chế độ Whisper Subtitle: CPU (int8 đa luồng, dùng {rec_threads} threads) -> Chạy mượt mà, không bị crash.")

    print("-" * 66)
    print()

    # Áp dụng tự động hoặc hỏi người dùng
    should_apply = auto_apply
    if not should_apply and sys.stdin and sys.stdin.isatty():
        try:
            ans = input("👉 Bạn có muốn tự động lưu cấu hình tối ưu này vào config.json không? (y/n) [Mặc định: y]: ").strip().lower()
            if ans in ["", "y", "yes"]:
                should_apply = True
        except Exception:
            pass

    if should_apply:
        cur_settings.setdefault("performance", {})
        cur_settings["performance"]["encoder"] = rec_encoder
        cur_settings["performance"]["allow_cpu_fallback"] = True
        cur_settings["performance"]["gpu_preflight_check"] = True
        if rec_encoder == "cpu":
            cur_settings["performance"]["cpu_threads"] = rec_threads
        mgr.save(cur_settings)
        print("🎉 [THÀNH CÔNG] Đã lưu cấu hình tối ưu vào config.json!")
    else:
        print("ℹ️ Giữ nguyên cấu hình hiện tại.")

    print()
    print("=" * 66)


if __name__ == "__main__":
    auto = "--auto" in sys.argv
    run_hardware_check(auto_apply=auto)
