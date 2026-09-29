from __future__ import annotations

import random
import re
import subprocess
from pathlib import Path
from typing import List

from .paths import find_binary
from .process_utils import run_hidden

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac"}


def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS


def is_video(path: str | Path) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def is_audio(path: str | Path) -> bool:
    return Path(path).suffix.lower() in AUDIO_EXTENSIONS


def get_duration_seconds(path: str | Path) -> float:
    """Đọc thời lượng media bằng ffprobe, có fallback và báo lỗi rõ hơn.

    Một số file tải từ web/YouTube có tên dài, ký tự Unicode hoặc metadata lạ.
    Hàm này không dùng shell, ghi rõ stderr để người dùng biết file lỗi hay FFmpeg lỗi.
    """
    media_path = Path(path)
    if not media_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {media_path}")

    try:
        ffprobe = find_binary("ffprobe.exe")
    except Exception:
        ffprobe = find_binary("ffprobe")

    probe_cmds = [
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(media_path)],
        [ffprobe, "-v", "error", "-analyzeduration", "100M", "-probesize", "100M", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(media_path)],
        [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(media_path)],
    ]
    completed = None
    for cmd in probe_cmds:
        completed = run_hidden(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        raw = (completed.stdout or "").strip().splitlines()
        for value in raw:
            try:
                parsed = float(value)
                if parsed > 0:
                    return parsed
            except ValueError:
                continue

    # Fallback: đọc dòng Duration từ ffmpeg -i, hữu ích với vài file metadata lạ.
    try:
        ffmpeg = find_binary("ffmpeg.exe")
    except Exception:
        ffmpeg = find_binary("ffmpeg")
    fallback = run_hidden([ffmpeg, "-hide_banner", "-i", str(media_path)], capture_output=True, text=True, encoding="utf-8", errors="ignore")
    text = (fallback.stderr or "") + "\n" + (fallback.stdout or "")
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if match:
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    stderr = (completed.stderr or text or "Không có thông tin lỗi từ FFmpeg").strip()
    raise RuntimeError(f"ffprobe không đọc được duration của file: {media_path}. Chi tiết: {stderr[:800]}")



def seconds_to_hhmmss(seconds: float) -> str:
    total = int(round(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _effective_media_duration(path: str | Path, image_duration: float, video_speed: float = 1.0) -> float:
    """Duration dùng để lấp nền video.

    Ảnh vẫn dùng image_duration. Video dùng full duration gốc chia cho video_speed,
    không còn bị ép theo duration ảnh.
    """
    media_path = Path(path)
    if is_video(media_path):
        try:
            speed = max(0.25, min(4.0, float(video_speed)))
        except Exception:
            speed = 1.0
        try:
            return max(0.1, get_duration_seconds(media_path) / speed)
        except Exception:
            # Nếu video lỗi metadata, vẫn cho qua để render_engine báo lỗi chi tiết ở bước tạo clip.
            return max(0.1, float(image_duration))
    return max(0.1, float(image_duration))


def choose_media_sequence(
    media_files: List[str],
    target_duration: float,
    image_duration: float,
    shuffle: bool = True,
    avoid_repeat: bool = True,
    video_speed: float = 1.0,
) -> List[str]:
    if not media_files:
        raise ValueError("Chưa chọn ảnh/video để render.")

    usable = [m for m in media_files if Path(m).exists()]
    if not usable:
        raise ValueError("Danh sách ảnh/video không có file tồn tại.")

    sequence: List[str] = []
    pool = usable[:]
    total_duration = 0.0
    # Thêm một khoảng đệm nhỏ để tránh bị hụt khi bật transition/xfade.
    duration_goal = max(0.5, float(target_duration)) + max(0.0, float(image_duration))

    while total_duration < duration_goal:
        if shuffle:
            random.shuffle(pool)
        appended_this_round = False
        for item in pool:
            if avoid_repeat and sequence and sequence[-1] == item and len(pool) > 1:
                continue
            sequence.append(item)
            total_duration += _effective_media_duration(item, image_duration, video_speed)
            appended_this_round = True
            if total_duration >= duration_goal:
                break
        if not appended_this_round:
            # Trường hợp avoid_repeat + pool bất thường, tránh vòng lặp vô hạn.
            item = pool[0]
            sequence.append(item)
            total_duration += _effective_media_duration(item, image_duration, video_speed)

    return sequence
