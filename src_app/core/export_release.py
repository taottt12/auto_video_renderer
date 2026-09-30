# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    from .paths import APP_ROOT, SRC_APP_DIR, TOOLS_DIR
    from .settings import DEFAULT_SETTINGS, deep_merge
except (ImportError, ValueError):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.paths import APP_ROOT, SRC_APP_DIR, TOOLS_DIR
    from core.settings import DEFAULT_SETTINGS, deep_merge


def get_clean_config(source_config_path: Path) -> Dict[str, Any]:
    """Tạo bản config.json sạch 100%, bảo mật tuyệt đối, xóa sạch API key, token và đường dẫn cá nhân."""
    # Khởi tạo từ DEFAULT_SETTINGS chuẩn
    clean = json.loads(json.dumps(DEFAULT_SETTINGS))

    # Nếu có file cấu hình hiện tại, chỉ kế thừa các tùy chỉnh giao diện/chế độ chung, xóa sạch thông tin riêng tư
    if source_config_path.exists():
        try:
            cur = json.loads(source_config_path.read_text(encoding="utf-8"))
            # Giữ lại các cài đặt xuất chuẩn nếu có
            if "export" in cur and isinstance(cur["export"], dict):
                for k in ["ratio", "width", "height", "fps", "quality", "format"]:
                    if k in cur["export"]:
                        clean["export"][k] = cur["export"][k]
            # Giữ lại cài đặt hiệu năng chung
            if "performance" in cur and isinstance(cur["performance"], dict):
                for k in ["encoder", "max_parallel_jobs", "allow_cpu_fallback", "gpu_preflight_check"]:
                    if k in cur["performance"]:
                        clean["performance"][k] = cur["performance"][k]
        except Exception:
            pass

    # Đảm bảo triệt để các trường nhạy cảm đều RỖNG:
    clean["audio_files"] = []
    clean["media_files"] = []
    clean["intro_file"] = ""
    clean["outro_file"] = ""
    clean["logo_file"] = ""
    clean["watermark_file"] = ""
    clean["video_effect_custom_file"] = ""
    
    clean["audio_crawler"]["cookie_file_path"] = ""
    clean["audio_crawler"]["save_folder"] = ""
    clean["audio_crawler"]["video_urls"] = ""
    clean["audio_crawler"]["playlist_url"] = ""
    clean["audio_crawler"]["channel_url"] = ""

    clean["background_music"]["file"] = ""
    clean["background_music"]["files"] = []
    clean["background_music"]["enabled"] = False

    clean["promo_audio"]["files"] = []
    clean["promo_audio"]["positions_text"] = ""
    clean["promo_audio"]["enabled"] = False

    clean["export"]["output_folder"] = ""
    
    clean["project"]["current_name"] = ""
    clean["project"]["current_path"] = ""
    clean["project"]["output_folder"] = ""

    # BẢO MẬT API KEYS & YOUTUBE
    clean["youtube_uploader"]["gemini_api_key"] = ""
    clean["youtube_uploader"]["9router_api_key"] = ""
    clean["youtube_uploader"]["custom_api_key"] = ""
    clean["youtube_uploader"]["active_channel_id"] = ""
    clean["youtube_uploader"]["default_playlist"] = ""

    return clean


def create_clean_release(output_dir_name: str = "AutoVideoRenderer_Clean_Release", make_zip: bool = True) -> Path:
    """Tự động đóng gói bản phát hành sạch để phân phối cho người dùng khác."""
    root_dir = APP_ROOT
    target_dir = root_dir.parent / output_dir_name

    print("=" * 66)
    print("      📦 BẮT ĐẦU ĐÓNG GÓI PHÂN PHỐI SẠCH (CLEAN RELEASE)      ")
    print("=" * 66)
    print(f"👉 Thư mục gốc dự án: {root_dir}")
    print(f"👉 Thư mục xuất bản:  {target_dir}")
    print()

    # 1. Xóa thư mục đích cũ nếu có
    if target_dir.exists():
        print("🧹 Đang dọn dẹp thư mục xuất bản cũ...")
        shutil.rmtree(target_dir, ignore_errors=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    # 2. Tạo cấu trúc thư mục con trong bản Release
    (target_dir / "src_app").mkdir(exist_ok=True)
    (target_dir / "src_app" / "data").mkdir(exist_ok=True)
    for folder in ["output", "projects", "tokens", "logs", "temp"]:
        (target_dir / "src_app" / "data" / folder).mkdir(exist_ok=True)
    (target_dir / "src_app" / "data" / "presets" / "layouts").mkdir(parents=True, exist_ok=True)

    # 3. Sao chép mã nguồn core, ui, __init__.py
    print("📋 Đang sao chép mã nguồn src_app...")
    shutil.copytree(SRC_APP_DIR / "core", target_dir / "src_app" / "core", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"), dirs_exist_ok=True)
    shutil.copytree(SRC_APP_DIR / "ui", target_dir / "src_app" / "ui", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"), dirs_exist_ok=True)
    if (SRC_APP_DIR / "__init__.py").exists():
        shutil.copy2(SRC_APP_DIR / "__init__.py", target_dir / "src_app" / "__init__.py")

    # 4. Sao chép tài nguyên assets (Fonts chữ & Overlays)
    if (SRC_APP_DIR / "assets").exists():
        print("🎨 Đang sao chép Fonts chữ và Video Overlays mẫu...")
        shutil.copytree(SRC_APP_DIR / "assets", target_dir / "src_app" / "assets", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"), dirs_exist_ok=True)

    # 5. Sao chép Mẫu Bố Cục Presets Layout
    source_layouts = SRC_APP_DIR / "data" / "presets" / "layouts"
    target_layouts = target_dir / "src_app" / "data" / "presets" / "layouts"
    if source_layouts.exists():
        print("📐 Đang sao chép các Mẫu Bố Cục Layout đẹp mắt...")
        for p in source_layouts.glob("*.json"):
            shutil.copy2(p, target_layouts / p.name)

    # 6. Sao chép công cụ nhúng FFmpeg
    if TOOLS_DIR.exists():
        print("🛠 Đang sao chép công cụ nhúng FFmpeg...")
        shutil.copytree(TOOLS_DIR, target_dir / "tools", dirs_exist_ok=True)

    # 7. Tạo file config.json SẠCH 100% (Không chứa API Key / Token / Đường dẫn riêng)
    print("🔒 Đang làm sạch và bảo mật config.json (xóa API Key & thông tin nhạy cảm)...")
    clean_config = get_clean_config(root_dir / "config.json")
    (target_dir / "config.json").write_text(json.dumps(clean_config, ensure_ascii=False, indent=2), encoding="utf-8")

    # 8. Sao chép các file gốc quan trọng
    print("🚀 Đang tạo các file khởi chạy tự động...")
    shutil.copy2(root_dir / "app.py", target_dir / "app.py")
    shutil.copy2(root_dir / "requirements.txt", target_dir / "requirements.txt")
    shutil.copy2(root_dir / "setup.bat", target_dir / "setup.bat")
    shutil.copy2(root_dir / "ChayTool.bat", target_dir / "ChayTool.bat")
    if (root_dir / "ChayTool.vbs").exists():
        shutil.copy2(root_dir / "ChayTool.vbs", target_dir / "ChayTool.vbs")
    shutil.copy2(root_dir / "run.bat", target_dir / "run.bat")
    shutil.copy2(root_dir / "run_debug.bat", target_dir / "run_debug.bat")
    if (root_dir / "DongGoiTool.bat").exists():
        shutil.copy2(root_dir / "DongGoiTool.bat", target_dir / "DongGoiTool.bat")
    if (root_dir / "KiemTraPhanCung.bat").exists():
        shutil.copy2(root_dir / "KiemTraPhanCung.bat", target_dir / "KiemTraPhanCung.bat")

    # 9. Sao chép Sổ Tay Hướng Dẫn Sử Dụng Chi Tiết
    if (root_dir / "HuongDanSuDung.txt").exists():
        shutil.copy2(root_dir / "HuongDanSuDung.txt", target_dir / "HuongDanSuDung.txt")

    # 10. Nén thành file ZIP sạch (nếu có yêu cầu)
    zip_path = None
    if make_zip:
        zip_path = root_dir.parent / f"{output_dir_name}.zip"
        print(f"🗜 Đang nén toàn bộ thành file ZIP: {zip_path.name}...")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root_f, dirs, files in os.walk(target_dir):
                for f in files:
                    full_p = Path(root_f) / f
                    rel_p = full_p.relative_to(target_dir)
                    zf.write(full_p, rel_p)
        print(f"✔ Đã nén thành công: {zip_path}")

    print()
    print("=" * 66)
    print("🎉 ĐÓNG GÓI BẢN PHÂN PHỐI SẠCH HOÀN TẤT 100%!")
    print(f"📁 Thư mục Release: {target_dir}")
    if zip_path:
        print(f"📦 File nén ZIP:     {zip_path}")
    print("🔒 Tất cả API Key, Token YouTube và đường dẫn cá nhân đã được làm sạch!")
    print("=" * 66)

    return target_dir


if __name__ == "__main__":
    create_clean_release()
