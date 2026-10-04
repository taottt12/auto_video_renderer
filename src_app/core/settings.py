from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict


from .paths import APP_ROOT, CONFIG_PATH, PROJECTS_DIR


DEFAULT_SETTINGS: Dict[str, Any] = {
    "audio_files": [],
    "audio_source_mode": "local",
    "audio_crawler": {
        "platform": "youtube",
        "browser_cookie": "chrome",
        "cookie_file_path": "",
        "save_folder": "",
        "auto_add_to_audio_list": True,
        "mode": "video",
        "video_urls": "",
        "playlist_url": "",
        "playlist_limit": 0,
        "channel_url": "",
        "channel_limit": 50,
        "channel_order": "newest_first",
        "channel_date_filter": "all",
        "channel_date_from": "",
        "channel_date_to": "",
        "direct_crawl": True,
        "audio_quality": "192",
    },
    "media_files": [],
    "shuffle_media": True,
    "avoid_repeat": True,
    "delete_audio_after_render": False,
    "intro_file": "",
    "intro_mode": "sequential",  # "sequential" (nối tiếp trước MP3) hoặc "overlay" (đè lên đầu MP3)
    "outro_file": "",
    "filter_bgm_after_30s": False,  # Giảm/lọc nhạc nền sau 30s đầu (giữ voice & SFX)
    "logo_file": "",
    "logo_enabled": False,
    "logo_position": "top_right",
    "logo_scale": 0.12,
    "logo_margin_x": 30,
    "logo_margin_y": 30,
    "watermark_file": "",
    "watermark_enabled": False,
    "watermark_opacity": 0.2,
    "watermark_scale": 1.0,
    "background_music": {
        "enabled": False,
        "file": "",  # legacy: tương thích project cũ
        "files": [],
        "shuffle": True,
        "avoid_repeat": True,
        "volume": 0.18,
        "loop": True,
    },
    "promo_audio": {
        "enabled": False,
        "files": [],
        "positions_text": "",  # mỗi dòng hoặc ngăn cách dấu phẩy: 01:00, 05:30, 00:10:00
        "shuffle": True,
        "avoid_repeat": True,
        "volume": 1.0,
        "duck_enabled": True,
        "duck_volume": 0.35,
        "duck_pad_start_ms": 100,
        "duck_pad_end_ms": 300,
    },
    "image_duration_mode": "auto",
    "effect_mode": "auto_smart",
    "image_motion_enabled": True,
    "video_effect_mode": "none",
    "transition_mode": "auto_soft",
    "transition_duration": 0.5,
    "layout_studio": {
        "enabled": True,
        "selected_preset": "custom",
        "layers": [],
        "custom_presets": {},
    },
    "audio_speed": 1.0,
    "video_speed": 1.0,
    "performance": {
        "encoder": "cpu",
        "max_parallel_jobs": 1,
        "cpu_threads": 0,
        "auto_clear_temp": True,
        "keep_temp_on_error": False,
        "allow_cpu_fallback": False,
        "gpu_preflight_check": True,
        "temp_folder": ""
    },
    "text_overlay": {
        "enabled": False,
        "moving_enabled": False,
        "speed_x": 135,
        "speed_y": 85,
        "content": "",
        "font_size": 48,
        "position": "bottom_center",
        "margin_x": 40,
        "margin_y": 80,
        "font_color": "#FFFFFF",
        "box_enabled": True,
        "box_opacity": 0.45
    },
    "subtitle": {
        "enabled": False,
        "auto_transcribe": False,
        "whisper_language": "auto",
        "whisper_model": "turbo",
        "whisper_enhance_voice": True,  # Lọc tạp âm & dải tần giọng nói giúp Whisper dịch chuẩn 100%
        "auto_detect_srt": True,
        "custom_sub_file": "",
        "font_name": "Arial",
        "font_size": 28,
        "font_color": "#FFFFFF",
        "outline_color": "#000000",
        "outline_width": 2.5,
        "bold": True,
        "italic": False,
        "shadow_offset": 1.0,
        "shadow_color": "#000000",
        "bg_box_enabled": False,
        "bg_box_color": "#000000",
        "bg_box_opacity": 0.5,
        "box_x": 0.15,
        "box_y": 0.70,
        "box_w": 0.70,
        "box_h": 0.20
    },
    "export": {
        "ratio": "9:16",
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "quality": "standard",
        "custom_bitrate_kbps": 6000,
        "format": "mp4",
        "output_folder": "output",
    },
    "youtube_uploader": {
        "gemini_api_key": "",
        "gemini_model": "gemini-2.0-flash",
        "active_channel_id": "",
        "privacy_status": "schedule",
        "schedule_videos_per_day": 2,
        "schedule_time_slots": "11:30, 19:30",
        "is_premiere": False,
        "default_playlist": "",
        "category_id": "24",
    },
    "project": {
        "current_name": "",
        "current_path": "",
    },
}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class SettingsManager:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or CONFIG_PATH
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            self.save(DEFAULT_SETTINGS)
            return deepcopy(DEFAULT_SETTINGS)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return deep_merge(DEFAULT_SETTINGS, data)
        except Exception:
            return deepcopy(DEFAULT_SETTINGS)

    def save(self, settings: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        merged = deep_merge(DEFAULT_SETTINGS, settings)
        self.path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def save_project(path: str | Path, settings: Dict[str, Any]) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(deep_merge(DEFAULT_SETTINGS, settings), ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def load_project(path: str | Path) -> Dict[str, Any]:
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        return deep_merge(DEFAULT_SETTINGS, data)

    @staticmethod
    def list_projects() -> list[Path]:
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        return sorted(PROJECTS_DIR.glob("*.avr.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    @staticmethod
    def project_path(name: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in name).strip()
        safe = safe or "project"
        if not safe.endswith(".avr.json"):
            safe += ".avr.json"
        return PROJECTS_DIR / safe
