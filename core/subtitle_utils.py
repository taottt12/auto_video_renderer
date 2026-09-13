from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


def hex_to_ass_color(hex_color: str, alpha: int = 0) -> str:
    """Chuyển đổi '#RRGGBB' hoặc '#AARRGGBB' sang định dạng ASS '&HAABBGGRR'."""
    hex_color = str(hex_color or "#FFFFFF").strip().lstrip("#")
    if len(hex_color) == 6:
        r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
        a = f"{alpha:02X}"
    elif len(hex_color) == 8:
        a, r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6], hex_color[6:8]
    else:
        return "&H00FFFFFF"
    return f"&H{a}{b}{g}{r}".upper()


def srt_time_to_ass(t_str: str) -> str:
    """Chuyển đổi thời gian từ định dạng SRT (00:01:23,456) sang ASS (0:01:23.45)."""
    t_str = t_str.strip().replace(",", ".")
    parts = t_str.split(":")
    if len(parts) == 3:
        h = int(parts[0])
        m = int(parts[1])
        s = float(parts[2])
    elif len(parts) == 2:
        h = 0
        m = int(parts[0])
        s = float(parts[1])
    else:
        return "0:00:00.00"
    cs = int(round((s - int(s)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def parse_srt(srt_text: str) -> List[Tuple[str, str, str]]:
    """Phân tích văn bản SRT thành danh sách (start, end, dialogue_text)."""
    blocks = re.split(r"\n\s*\n", srt_text.strip())
    dialogues: List[Tuple[str, str, str]] = []
    time_pat = re.compile(r"(\d+:\d+:\d+[,\.]\d+)\s*-->\s*(\d+:\d+:\d+[,\.]\d+)")
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        time_match = None
        text_lines: List[str] = []
        for line in lines:
            m = time_pat.search(line)
            if m:
                time_match = m
            elif time_match:
                text_lines.append(line)
        if time_match and text_lines:
            start = srt_time_to_ass(time_match.group(1))
            end = srt_time_to_ass(time_match.group(2))
            text = r"\N".join(text_lines)
            dialogues.append((start, end, text))
    return dialogues


def read_subtitle_file(path: str | Path) -> str:
    """Đọc file phụ đề với fallback encoding an toàn."""
    p = Path(path)
    for enc in ("utf-8-sig", "utf-8", "utf-16", "cp1252", "latin1"):
        try:
            return p.read_text(encoding=enc)
        except Exception:
            pass
    return p.read_text(encoding="utf-8", errors="ignore")


def srt_to_ass(
    srt_path: str | Path,
    out_ass_path: str | Path,
    width: int,
    height: int,
    sub_cfg: Dict[str, Any]
) -> Path:
    """Chuyển đổi file .srt sang .ass với cấu hình phong cách chữ và bounding box."""
    srt_p = Path(srt_path)
    out_p = Path(out_ass_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    content = read_subtitle_file(srt_p)
    dialogues = parse_srt(content)

    font_name = str(sub_cfg.get("font_family", "Arial") or "Arial")
    font_size = int(sub_cfg.get("font_size", 38) or 38)
    # Tự động điều chỉnh tỉ lệ font_size nếu độ phân giải cao/thấp (chuẩn 1080p height = 38)
    scaled_font_size = max(14, int(font_size * (height / 1080.0))) if height > 0 else font_size

    font_color = str(sub_cfg.get("font_color", "#FFFFFF") or "#FFFFFF")
    outline_color = str(sub_cfg.get("outline_color", "#000000") or "#000000")
    outline_width = float(sub_cfg.get("outline_width", 2.5) or 2.5)
    bold = -1 if bool(sub_cfg.get("bold", True)) else 0
    italic = -1 if bool(sub_cfg.get("italic", False)) else 0

    # Vùng hiển thị phụ đề (Bounding Box theo tỉ lệ 0.0 -> 1.0)
    # Mặc định: 2 bên 15% (margin 15%), height 20%, cách đáy 10%
    box_x = float(sub_cfg.get("box_x", 0.15))
    box_y = float(sub_cfg.get("box_y", 0.70))
    box_w = float(sub_cfg.get("box_w", 0.70))
    box_h = float(sub_cfg.get("box_h", 0.20))

    margin_l = max(10, int(box_x * width))
    margin_r = max(10, int((1.0 - (box_x + box_w)) * width))
    margin_v = max(10, int((1.0 - (box_y + box_h)) * height))

    primary_color_ass = hex_to_ass_color(font_color)
    outline_color_ass = hex_to_ass_color(outline_color)

    ass_lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font_name},{scaled_font_size},{primary_color_ass},&H000000FF,{outline_color_ass},&H00000000,{bold},{italic},0,0,100,100,0,0,1,{outline_width:.1f},0,2,{margin_l},{margin_r},{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for start, end, text in dialogues:
        ass_lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    out_p.write_text("\n".join(ass_lines), encoding="utf-8")
    return out_p


def find_subtitle_file(audio_file: str | Path, sub_dir: str | Path | None = None) -> Path | None:
    """Tự động tìm file phụ đề (.srt hoặc .ass) tương ứng với file audio."""
    audio_path = Path(audio_file)
    stem = audio_path.stem

    # 1. Tìm cùng thư mục với file audio
    for ext in (".srt", ".ass"):
        candidate = audio_path.with_suffix(ext)
        if candidate.exists():
            return candidate

    # 2. Tìm trong thư mục phụ đề chỉ định (nếu có)
    if sub_dir:
        sd = Path(sub_dir)
        if sd.exists() and sd.is_dir():
            for ext in (".srt", ".ass"):
                candidate = sd / f"{stem}{ext}"
                if candidate.exists():
                    return candidate

    return None


def format_timestamp_srt(seconds: float) -> str:
    """Định dạng giây thành định dạng SRT 00:00:00,000."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"


def transcribe_audio_to_srt(
    audio_path: str | Path,
    out_srt_path: str | Path,
    model_size: str = "base",
    language: str | None = None,
    log_callback: Any = None,
) -> Tuple[Path, str]:
    """Tự động nghe audio bằng Whisper AI, nhận diện ngôn ngữ nước đó và xuất file .srt chuẩn."""
    p_audio = Path(audio_path)
    p_out = Path(out_srt_path)
    p_out.parent.mkdir(parents=True, exist_ok=True)

    if log_callback:
        log_callback(f"Đang tải Whisper AI model ({model_size}) để nhận diện giọng nói...")

    from faster_whisper import WhisperModel

    # Tự động chọn device CPU với int8 tối ưu
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    if log_callback:
        log_callback(f"Đang quét giọng nói trong audio và tự động nhận diện ngôn ngữ...")

    segments, info = model.transcribe(
        str(p_audio),
        beam_size=5,
        language=language if language else None,
        vad_filter=True,
    )

    detected_lang = info.language or "unknown"
    prob = getattr(info, "language_probability", 1.0) * 100
    if log_callback:
        log_callback(f"✔ Đã nhận diện ngôn ngữ audio: {detected_lang.upper()} (độ tin cậy: {prob:.1f}%)")

    srt_lines: List[str] = []
    idx = 1
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        start_str = format_timestamp_srt(seg.start)
        end_str = format_timestamp_srt(seg.end)
        srt_lines.append(f"{idx}\n{start_str} --> {end_str}\n{text}\n")
        idx += 1

    p_out.write_text("\n".join(srt_lines), encoding="utf-8")
    if log_callback:
        log_callback(f"✔ Đã tạo file phụ đề .srt: {p_out.name} (gồm {idx - 1} câu thoại)")

    return p_out, detected_lang
