from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict


from .paths import APP_ROOT, CONFIG_PATH, PROJECTS_DIR, SECRETS_PATH


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
    "audio_crawler_project": {
        "initialized": False,
        "mode": "playlist",
        "video_urls": "",
        "playlist_url": "",
        "playlist_limit": 100,
        "channel_url": "",
        "channel_limit": 50,
        "channel_order": "newest_first",
        "channel_date_filter": "all",
        "channel_date_from": "",
        "channel_date_to": "",
        "save_folder": "",
        "auto_add_to_audio_list": True,
        "direct_crawl": True,
        "only_new": True,
        "audio_trim": {
            "enabled": False,
            "mode": "remove_segment",
            "start_time": "00:00:00",
            "end_time": "00:00:10",
        },
        "history": {},
    },
    "media_files": [],
    "shuffle_media": True,
    "avoid_repeat": True,
    "delete_audio_after_render": False,
    "intro_file": "",
    "intro_mode": "sequential",  # "sequential" (nối tiếp trước MP3) hoặc "overlay" (đè lên đầu MP3)
    "outro_file": "",
    "intro_outro_presets": [],
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
    "opening_effect": {
        "enabled": False,
        "mode": "fade_black",
        "duration": 0.8,
        "audio_fade_enabled": False,
        "audio_fade_duration": 0.3,
    },
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
        "whisper_enhance_voice": True,  # Lọc dải tần DSP giọng đọc & triệt tiêu nhạc nền
        "sub_mode": "rolling_2line",
        "auto_detect_srt": True,
        "custom_sub_file": "",
        "font_name": "Arial",
        "font_size": 28,
        "font_color": "#FFFFFF",
        "highlight_color": "#FFE600",
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
    "render_queue": [],
}


# Project files are portable workspaces. Machine/account settings intentionally
# stay outside them so opening a project cannot replace crawler credentials,
# YouTube accounts, or application-wide defaults.
PROJECT_SETTING_KEYS = {
    "audio_files", "audio_source_mode", "audio_crawler_project", "media_files", "shuffle_media",
    "avoid_repeat", "delete_audio_after_render", "intro_file", "intro_mode",
    "outro_file", "intro_outro_presets", "filter_bgm_after_30s", "logo_file",
    "logo_enabled", "logo_position", "logo_scale", "logo_margin_x",
    "logo_margin_y", "watermark_file", "watermark_enabled",
    "watermark_opacity", "watermark_scale", "background_music", "promo_audio",
    "image_duration_mode", "effect_mode", "image_motion_enabled",
    "video_effect_mode", "video_effect_enabled", "video_effect_custom_file",
    "video_effect_opacity", "transition_mode", "transition_enabled",
    "transition_duration", "opening_effect", "layout_studio", "audio_speed", "video_speed",
    "performance", "text_overlay", "subtitle", "export", "project",
    "render_queue",
}

GLOBAL_SETTING_KEYS = {"audio_crawler", "youtube_uploader", "performance", "project"}


def _project_payload(settings: Dict[str, Any]) -> Dict[str, Any]:
    payload = {k: deepcopy(settings[k]) for k in PROJECT_SETTING_KEYS if k in settings}
    project = payload.setdefault("project", {})
    project.pop("current_path", None)
    return payload


def _extract_secrets(settings: Dict[str, Any]) -> Dict[str, Any]:
    crawler = settings.get("audio_crawler", {}) or {}
    youtube = settings.get("youtube_uploader", {}) or {}
    return {
        "audio_crawler": {
            "cookie_file_path": str(crawler.get("cookie_file_path", "") or ""),
        },
        "youtube_uploader": {
            key: str(value or "")
            for key, value in youtube.items()
            if key.endswith("api_key")
        },
    }


def _without_secrets(settings: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(settings)
    result.setdefault("audio_crawler", {}).pop("cookie_file_path", None)
    yt = result.setdefault("youtube_uploader", {})
    for key in list(yt):
        if key.endswith("api_key"):
            yt.pop(key, None)
    return result


def _load_secrets() -> Dict[str, Any]:
    try:
        if SECRETS_PATH.exists():
            data = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _save_secrets(secrets: Dict[str, Any]) -> None:
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SECRETS_PATH.write_text(json.dumps(secrets, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_intro_outro_presets(settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Đảm bảo settings luôn có danh sách intro_outro_presets hợp lệ.
    Nếu chưa có hoặc rỗng, tự động tạo preset 'Mặc định' từ intro_file, intro_mode, outro_file hiện tại.
    Đồng thời đồng bộ root intro_file/intro_mode/outro_file với preset mặc định.
    """
    presets = settings.get("intro_outro_presets")
    if not isinstance(presets, list) or len(presets) == 0:
        presets = [
            {
                "id": "default",
                "name": "Mặc định (Chung)",
                "intro_file": str(settings.get("intro_file") or "").strip(),
                "intro_mode": str(settings.get("intro_mode") or "sequential").strip(),
                "outro_file": str(settings.get("outro_file") or "").strip(),
                "is_default": True,
            }
        ]
        settings["intro_outro_presets"] = presets
    else:
        # Nếu có duy nhất 1 preset mặc định nhưng các đường dẫn trống, trong khi root settings có file (migration)
        if len(presets) == 1 and not presets[0].get("intro_file") and not presets[0].get("outro_file"):
            if settings.get("intro_file") or settings.get("outro_file"):
                presets[0]["intro_file"] = str(settings.get("intro_file") or "").strip()
                presets[0]["intro_mode"] = str(settings.get("intro_mode") or "sequential").strip()
                presets[0]["outro_file"] = str(settings.get("outro_file") or "").strip()

        has_default = any(bool(p.get("is_default")) for p in presets)
        if not has_default and len(presets) > 0:
            presets[0]["is_default"] = True

    default_p = next((p for p in presets if p.get("is_default")), presets[0])
    settings["intro_file"] = default_p.get("intro_file", "")
    settings["intro_mode"] = default_p.get("intro_mode", "sequential")
    settings["outro_file"] = default_p.get("outro_file", "")
    return presets


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
            res = deepcopy(DEFAULT_SETTINGS)
            normalize_intro_outro_presets(res)
            return res
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            res = deep_merge(DEFAULT_SETTINGS, data)
            res = deep_merge(res, _load_secrets())
            normalize_intro_outro_presets(res)
            return res
        except Exception:
            res = deepcopy(DEFAULT_SETTINGS)
            normalize_intro_outro_presets(res)
            return res

    def save(self, settings: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        normalize_intro_outro_presets(settings)
        _save_secrets(_extract_secrets(settings))
        global_payload = {
            key: deepcopy(settings[key]) for key in GLOBAL_SETTING_KEYS if key in settings
        }
        crawler = settings.get("audio_crawler", {}) or {}
        global_payload["audio_crawler"] = {
            key: deepcopy(crawler[key])
            for key in ("platform", "browser_cookie", "cookie_file_path", "audio_quality")
            if key in crawler
        }
        project = settings.get("project", {}) or {}
        global_payload["project"] = {
            "current_name": str(project.get("current_name", "") or ""),
            "current_path": str(project.get("current_path", "") or ""),
        }
        # Remember the active project, but never persist its output/render state
        # in the global application config.
        safe_payload = _without_secrets(global_payload)
        self.path.write_text(json.dumps(safe_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def save_project(path: str | Path, settings: Dict[str, Any]) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        normalize_intro_outro_presets(settings)
        p.write_text(json.dumps(_project_payload(settings), ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def load_project(path: str | Path, base_settings: Dict[str, Any] | None = None) -> Dict[str, Any]:
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        # Filtering also sanitizes legacy projects which used to contain the
        # complete global config, including account credentials.
        base = deep_merge(DEFAULT_SETTINGS, base_settings or {})
        res = deep_merge(base, _project_payload(data))
        if "audio_crawler_project" not in data:
            legacy = (base_settings or {}).get("audio_crawler", {}) or {}
            profile = deepcopy(DEFAULT_SETTINGS["audio_crawler_project"])
            for key in (
                "mode", "video_urls", "playlist_url", "playlist_limit",
                "channel_url", "channel_limit", "channel_order",
                "channel_date_filter", "channel_date_from", "channel_date_to",
                "save_folder", "auto_add_to_audio_list", "direct_crawl", "audio_trim",
            ):
                if key in legacy:
                    profile[key] = deepcopy(legacy[key])
            profile["initialized"] = True
            res["audio_crawler_project"] = profile
        res.setdefault("project", {})["current_path"] = str(p)
        normalize_intro_outro_presets(res)
        return res

    @staticmethod
    def resolve_current_project(settings: Dict[str, Any]) -> Path | None:
        project = settings.get("project", {}) or {}
        configured = str(project.get("current_path", "") or "").strip()
        if configured:
            path = Path(configured)
            if path.exists():
                return path
        name = str(project.get("current_name", "") or "").strip()
        if name:
            candidate = SettingsManager.project_path(name)
            if candidate.exists():
                return candidate
        return None

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
