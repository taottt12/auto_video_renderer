from __future__ import annotations

import shutil
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
TEMP_DIR = APP_ROOT / "temp"
OUTPUT_DIR = APP_ROOT / "output"
LOG_DIR = APP_ROOT / "logs"


def ensure_dirs() -> None:
    for folder in (TEMP_DIR, OUTPUT_DIR, LOG_DIR):
        folder.mkdir(parents=True, exist_ok=True)


def find_binary(name: str) -> str:
    local = APP_ROOT / "tools" / "ffmpeg" / "bin" / name
    if local.exists():
        return str(local)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(
        f"Không tìm thấy {name}. Hãy đặt {name} vào tools/ffmpeg/bin hoặc thêm FFmpeg vào PATH."
    )
