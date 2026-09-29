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


def format_bytes_human(num: float) -> str:
    """Chuyển đổi số bytes sang định dạng dung lượng dễ đọc (B, KB, MB, GB)."""
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(max(0.0, num))
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{value:.1f} TB"


def cleanup_all_temp_caches(
    custom_temp_dir: str = "",
    output_dir: str = "",
    extra_dirs: list[str] | None = None,
) -> dict:
    """Quét và xóa sạch các file tạm, thư mục _avr_temp, cache python và rác hệ thống."""
    total_freed = 0
    deleted_files = 0
    deleted_folders = 0
    errors = []

    # 1. Thư mục TEMP mặc định của app
    target_dirs = [TEMP_DIR]
    if custom_temp_dir and Path(custom_temp_dir).exists():
        target_dirs.append(Path(custom_temp_dir))
    if output_dir and Path(output_dir).exists():
        target_dirs.append(Path(output_dir) / "_avr_temp")
    if extra_dirs:
        for d in extra_dirs:
            if d and Path(d).exists():
                target_dirs.append(Path(d))

    seen_paths = set()
    for td in target_dirs:
        if not td or str(td) in seen_paths:
            continue
        seen_paths.add(str(td))
        p = Path(td)
        if not p.exists():
            continue

        if p.is_dir():
            try:
                for item in list(p.rglob("*")):
                    if item.is_file() or item.is_symlink():
                        try:
                            sz = item.stat().st_size
                            item.unlink(missing_ok=True)
                            total_freed += sz
                            deleted_files += 1
                        except Exception:
                            pass
                if "_avr_temp" in p.name.lower():
                    try:
                        shutil.rmtree(p, ignore_errors=True)
                        deleted_folders += 1
                    except Exception:
                        pass
            except Exception as e:
                errors.append(str(e))

    # 2. Xóa __pycache__ và file .pyc trong SRC_APP_DIR
    try:
        for pyc_dir in SRC_APP_DIR.rglob("__pycache__"):
            if pyc_dir.exists() and pyc_dir.is_dir():
                try:
                    for f in pyc_dir.glob("*.pyc"):
                        total_freed += f.stat().st_size
                        deleted_files += 1
                    shutil.rmtree(pyc_dir, ignore_errors=True)
                    deleted_folders += 1
                except Exception:
                    pass
    except Exception:
        pass

    return {
        "success": True,
        "freed_bytes": total_freed,
        "freed_formatted": format_bytes_human(total_freed),
        "deleted_files": deleted_files,
        "deleted_folders": deleted_folders,
        "errors": errors,
    }

