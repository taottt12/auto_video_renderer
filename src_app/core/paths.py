from __future__ import annotations

import shutil
from pathlib import Path

# Cấu trúc thư mục
SRC_CORE_DIR = Path(__file__).resolve().parent
SRC_APP_DIR = Path(__file__).resolve().parents[1]
APP_ROOT = Path(__file__).resolve().parents[2]

# Thư mục dữ liệu người dùng (nằm trong src_app/data)
DATA_DIR = SRC_APP_DIR / "data"
TEMP_DIR = DATA_DIR / "temp"
OUTPUT_DIR = DATA_DIR / "output"
LOG_DIR = DATA_DIR / "logs"
PROJECTS_DIR = DATA_DIR / "projects"
PRESETS_DIR = DATA_DIR / "presets"
LAYOUTS_DIR = PRESETS_DIR / "layouts"
TOKENS_DIR = DATA_DIR / "tokens"

# Thư mục tài nguyên và công cụ
ASSETS_DIR = SRC_APP_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
OVERLAYS_DIR = ASSETS_DIR / "overlays"
TOOLS_DIR = APP_ROOT / "tools"
CONFIG_PATH = APP_ROOT / "config.json"


def ensure_dirs() -> None:
    for folder in (DATA_DIR, TEMP_DIR, OUTPUT_DIR, LOG_DIR, PROJECTS_DIR, PRESETS_DIR, LAYOUTS_DIR, TOKENS_DIR):
        folder.mkdir(parents=True, exist_ok=True)


def find_binary(name: str) -> str:
    # 1. Ưu tiên tìm trong tools/ffmpeg/bin ở thư mục gốc
    local = TOOLS_DIR / "ffmpeg" / "bin" / name
    if local.exists():
        return str(local)
    # 2. Tìm trong src_app/tools nếu có
    local_src = SRC_APP_DIR / "tools" / "ffmpeg" / "bin" / name
    if local_src.exists():
        return str(local_src)
    # 3. Tìm trong PATH hệ thống
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(
        f"Không tìm thấy {name}. Hãy đặt {name} vào tools/ffmpeg/bin hoặc thêm FFmpeg vào PATH."
    )
