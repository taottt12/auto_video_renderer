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


def srt_time_to_seconds(t_str: str) -> float:
    """Chuyển đổi thời gian dạng chuỗi (00:01:23,456 hoặc 01:23.45) sang giây."""
    t_str = t_str.strip().replace(",", ".")
    parts = t_str.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 1 and parts[0]:
            return float(parts[0])
    except Exception:
        return 0.0
    return 0.0


def seconds_to_ass_time(sec: float) -> str:
    """Chuyển đổi số giây thành định dạng thời gian ASS (0:01:23.45)."""
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    cs = int(round((s - int(s)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def srt_time_to_ass(t_str: str, speed: float = 1.0) -> str:
    """Chuyển đổi thời gian từ định dạng SRT (00:01:23,456) sang ASS (0:01:23.45) có bù trừ tốc độ."""
    sec = srt_time_to_seconds(t_str)
    if speed > 0.001 and abs(speed - 1.0) > 0.001:
        sec = sec / speed
    return seconds_to_ass_time(sec)


def parse_srt_to_raw_events(srt_text: str, speed: float = 1.0) -> List[Tuple[float, float, str]]:
    """Phân tích văn bản SRT thành danh sách (start_sec, end_sec, text) đã bù trừ audio_speed."""
    blocks = re.split(r"\n\s*\n", srt_text.strip())
    raw_events: List[Tuple[float, float, str]] = []
    time_pat = re.compile(r"(\d+:\d+:\d+[,\.]\d+)\s*-->\s*(\d+:\d+:\d+[,\.]\d+)")
    eff_speed = speed if (speed > 0.001) else 1.0

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
            s_sec = srt_time_to_seconds(time_match.group(1)) / eff_speed
            e_sec = srt_time_to_seconds(time_match.group(2)) / eff_speed
            txt = " ".join(text_lines).strip()
            if txt:
                raw_events.append((s_sec, e_sec, txt))
    return raw_events


def generate_rolling_2line_events(
    raw_events: List[Tuple[float, float, str]],
    max_hold_sec: float = 3.5
) -> List[Tuple[str, str, str]]:
    """Tạo event ASS cuộn 2 dòng: câu cũ được đẩy lên trên giữ thêm thời gian, câu mới xuất hiện ở dưới."""
    dialogues: List[Tuple[str, str, str]] = []
    n = len(raw_events)
    for i in range(n):
        s_i, e_i, t_i = raw_events[i]
        next_s = raw_events[i + 1][0] if i + 1 < n else e_i + max_hold_sec
        eff_end = min(next_s, max(e_i + 1.5, s_i + 2.0))
        if next_s - s_i <= max_hold_sec:
            eff_end = next_s

        start_ass = seconds_to_ass_time(s_i)
        end_ass = seconds_to_ass_time(eff_end)

        if i == 0:
            dialogues.append((start_ass, end_ass, t_i))
        else:
            prev_t = raw_events[i - 1][2]
            dialogues.append((start_ass, end_ass, f"{prev_t}\\N{t_i}"))
    return dialogues


def generate_cinema_hold_events(
    raw_events: List[Tuple[float, float, str]],
    min_hold_sec: float = 2.5,
    max_gap_bridge_sec: float = 1.0
) -> List[Tuple[str, str, str]]:
    """Tạo event ASS chuẩn điện ảnh: câu hoàn chỉnh, giữ tối thiểu 2.5s để kịp đọc."""
    dialogues: List[Tuple[str, str, str]] = []
    n = len(raw_events)
    for i in range(n):
        s_i, e_i, t_i = raw_events[i]
        next_s = raw_events[i + 1][0] if i + 1 < n else e_i + min_hold_sec

        dur = e_i - s_i
        target_end = e_i
        if dur < min_hold_sec:
            target_end = s_i + min_hold_sec
        if next_s - e_i <= max_gap_bridge_sec:
            target_end = next_s

        eff_end = min(target_end, next_s) if next_s > s_i else target_end

        start_ass = seconds_to_ass_time(s_i)
        end_ass = seconds_to_ass_time(eff_end)
        dialogues.append((start_ass, end_ass, t_i))
    return dialogues


def generate_karaoke_events(
    raw_events: List[Tuple[float, float, str]],
    min_hold_sec: float = 2.0
) -> List[Tuple[str, str, str]]:
    """Tạo event ASS Karaoke Highlight từng từ theo nhịp đọc phát âm."""
    dialogues: List[Tuple[str, str, str]] = []
    n = len(raw_events)
    for i in range(n):
        s_i, e_i, t_i = raw_events[i]
        words = t_i.split()
        if not words:
            continue

        next_s = raw_events[i + 1][0] if i + 1 < n else e_i + min_hold_sec
        dur_sec = max(0.5, e_i - s_i)
        total_cs = int(dur_sec * 100)

        total_chars = sum(len(w) for w in words)
        if total_chars == 0:
            total_chars = 1

        karaoke_parts = []
        for w in words:
            w_cs = max(5, int((len(w) / total_chars) * total_cs))
            karaoke_parts.append(f"{{\\kf{w_cs}}}{w}")

        karaoke_text = " ".join(karaoke_parts)
        eff_end = min(next_s, max(e_i + 0.8, s_i + min_hold_sec))
        start_ass = seconds_to_ass_time(s_i)
        end_ass = seconds_to_ass_time(eff_end)
        dialogues.append((start_ass, end_ass, karaoke_text))
    return dialogues


def parse_srt(srt_text: str, speed: float = 1.0) -> List[Tuple[str, str, str]]:
    """Phân tích văn bản SRT thành danh sách (start, end, dialogue_text) đồng bộ theo audio_speed."""
    raw = parse_srt_to_raw_events(srt_text, speed=speed)
    return [(seconds_to_ass_time(s), seconds_to_ass_time(e), t) for s, e, t in raw]


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
    """Chuyển đổi file .srt sang .ass với cấu hình phong cách chữ, bounding box và 3 chế độ hiển thị."""
    srt_p = Path(srt_path)
    out_p = Path(out_ass_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    speed = float(sub_cfg.get("audio_speed", 1.0) or 1.0)
    sub_mode = str(sub_cfg.get("sub_mode", "rolling_2line") or "rolling_2line").strip().lower()

    content = read_subtitle_file(srt_p)
    raw_events = parse_srt_to_raw_events(content, speed=speed)

    font_name = str(sub_cfg.get("font_family", "Arial") or "Arial")
    font_size = int(sub_cfg.get("font_size", 38) or 38)
    scaled_font_size = max(14, int(font_size * (height / 1080.0))) if height > 0 else font_size

    font_color = str(sub_cfg.get("font_color", "#FFFFFF") or "#FFFFFF")
    highlight_color = str(sub_cfg.get("highlight_color", "#FFE600") or "#FFE600")
    outline_color = str(sub_cfg.get("outline_color", "#000000") or "#000000")
    outline_width = float(sub_cfg.get("outline_width", 2.5) or 2.5)
    bold = -1 if bool(sub_cfg.get("bold", True)) else 0
    italic = -1 if bool(sub_cfg.get("italic", False)) else 0

    # Vùng hiển thị phụ đề (Bounding Box theo tỉ lệ 0.0 -> 1.0)
    box_x = float(sub_cfg.get("box_x", 0.15))
    box_y = float(sub_cfg.get("box_y", 0.70))
    box_w = float(sub_cfg.get("box_w", 0.70))
    box_h = float(sub_cfg.get("box_h", 0.20))

    margin_l = max(10, int(box_x * width))
    margin_r = max(10, int((1.0 - (box_x + box_w)) * width))
    margin_v = max(10, int((1.0 - (box_y + box_h)) * height))

    # Alignment trong ASS: 1 = Bottom-Left, 2 = Bottom-Center, 3 = Bottom-Right
    align_str = str(sub_cfg.get("align", "center")).lower()
    if align_str == "left":
        ass_align = 1
    elif align_str == "right":
        ass_align = 3
    else:
        ass_align = 2

    # Thiết lập màu sắc và sự kiện theo chế độ phụ đề
    if sub_mode == "karaoke_highlight":
        primary_color_ass = hex_to_ass_color(highlight_color)
        secondary_color_ass = hex_to_ass_color(font_color)
        outline_color_ass = hex_to_ass_color(outline_color)
        dialogues = generate_karaoke_events(raw_events)
    elif sub_mode == "cinema_hold":
        primary_color_ass = hex_to_ass_color(font_color)
        secondary_color_ass = "&H000000FF"
        outline_color_ass = hex_to_ass_color(outline_color)
        dialogues = generate_cinema_hold_events(raw_events)
    else: # rolling_2line (mặc định)
        primary_color_ass = hex_to_ass_color(font_color)
        secondary_color_ass = "&H000000FF"
        outline_color_ass = hex_to_ass_color(outline_color)
        dialogues = generate_rolling_2line_events(raw_events)

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
        f"Style: Default,{font_name},{scaled_font_size},{primary_color_ass},{secondary_color_ass},{outline_color_ass},&H00000000,{bold},{italic},0,0,100,100,0,0,1,{outline_width:.1f},0,{ass_align},{margin_l},{margin_r},{margin_v},1",
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


def build_accurate_subtitles(
    segments: Any,
    max_words_per_line: int = 6,
    max_duration_sec: float = 2.8,
    speed: float = 1.0,
) -> List[Tuple[float, float, str]]:
    """Gom nhóm từ theo cụm ngắn tự nhiên và bắt đúng mili-giây thời điểm phát âm."""
    events: List[Tuple[float, float, str]] = []
    eff_speed = speed if (speed > 0.001) else 1.0

    for seg in segments:
        words = list(getattr(seg, "words", None) or [])
        if not words:
            start = seg.start / eff_speed
            end = seg.end / eff_speed
            text = seg.text.strip()
            if text:
                events.append((start, end, text))
            continue

        current_chunk: List[Any] = []
        chunk_start: float | None = None

        for w in words:
            w_text = str(w.word or "").strip()
            if not w_text:
                continue

            if chunk_start is None:
                chunk_start = float(w.start)

            current_chunk.append(w)

            # Ngắt cụm khi: có dấu câu, đạt số từ tối đa, hoặc thời lượng cụm vượt ngưỡng
            is_punct = any(w_text.endswith(p) for p in [".", "?", "!", ",", ":", ";", "—", "..."])
            dur = float(w.end) - chunk_start

            if is_punct or len(current_chunk) >= max_words_per_line or dur >= max_duration_sec:
                c_text = " ".join(str(item.word or "").strip() for item in current_chunk)
                events.append((chunk_start / eff_speed, float(w.end) / eff_speed, c_text))
                current_chunk = []
                chunk_start = None

        if current_chunk and chunk_start is not None:
            c_text = " ".join(str(item.word or "").strip() for item in current_chunk)
            events.append((chunk_start / eff_speed, float(current_chunk[-1].end) / eff_speed, c_text))

    return events


def transcribe_audio_to_srt(
    audio_path: str | Path,
    out_srt_path: str | Path,
    model_size: str = "base",
    language: str | None = None,
    log_callback: Any = None,
    speed: float = 1.0,
) -> Tuple[Path, str]:
    """Tự động nghe audio bằng Whisper AI, nhận diện ngôn ngữ và xuất file .srt chuẩn xác theo từng từ."""
    p_audio = Path(audio_path)
    p_out = Path(out_srt_path)
    p_out.parent.mkdir(parents=True, exist_ok=True)

    from faster_whisper import WhisperModel

    model_size = str(model_size or "base").strip()

    # Tự động phát hiện GPU (NVIDIA CUDA) hay CPU thông qua CTranslate2
    model = None
    device_used = "cpu"
    compute_type_used = "int8"

    has_cuda = False
    try:
        import ctranslate2
        has_cuda = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        try:
            import torch
            has_cuda = torch.cuda.is_available()
        except Exception:
            has_cuda = False

    if has_cuda:
        try:
            if log_callback:
                log_callback(f"🚀 Phát hiện Card đồ họa rời (NVIDIA CUDA): Đang khởi tạo Whisper AI [{model_size}] trên GPU...")
            model = WhisperModel(model_size, device="cuda", compute_type="float16")
            device_used = "cuda"
            compute_type_used = "float16"
        except Exception as cuda_ex:
            try:
                # Thử với compute_type int8_float16 nếu GPU không tương thích hoàn toàn float16
                model = WhisperModel(model_size, device="cuda", compute_type="int8_float16")
                device_used = "cuda"
                compute_type_used = "int8_float16"
            except Exception:
                if log_callback:
                    log_callback(f"⚠️ GPU CUDA không tương thích ({cuda_ex}) -> Tự động chuyển sang CPU...")
                model = None

    if model is None:
        if log_callback and device_used != "cuda":
            log_callback(f"💻 Đang tải Whisper AI model [{model_size}] trên CPU...")
        model = WhisperModel(model_size, device="cpu", compute_type="int8")


    target_lang = language if (language and language not in ["auto", "None", "none", ""]) else None

    if log_callback:
        lang_msg = f"ngôn ngữ chỉ định: [{target_lang.upper()}]" if target_lang else "chế độ tự động nhận diện ngôn ngữ"
        log_callback(f"Đang quét giọng nói trong {p_audio.name} ({lang_msg}) bằng {device_used.upper()}...")

    segments, info = model.transcribe(
        str(p_audio),
        beam_size=5,
        language=target_lang,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=400, speech_pad_ms=200),
        word_timestamps=True,
    )

    detected_lang = target_lang or getattr(info, "language", "unknown") or "unknown"
    prob = getattr(info, "language_probability", 1.0) * 100
    if log_callback:
        log_callback(f"✔ Nhận diện giọng nói hoàn tất: [{detected_lang.upper()}] (độ tin cậy: {prob:.1f}%)")

    # Gom nhóm từ chính xác theo cụm câu phát âm thực tế
    events = build_accurate_subtitles(segments, max_words_per_line=6, max_duration_sec=2.8, speed=speed)

    srt_lines: List[str] = []
    for idx, (start_sec, end_sec, text) in enumerate(events, start=1):
        if not text:
            continue
        start_str = format_timestamp_srt(start_sec)
        end_str = format_timestamp_srt(end_sec)
        srt_lines.append(f"{idx}\n{start_str} --> {end_str}\n{text}\n")

    p_out.write_text("\n".join(srt_lines), encoding="utf-8")
    if log_callback:
        log_callback(f"✔ Đã tạo file phụ đề .srt chính xác: {p_out.name} (gồm {len(events)} cụm thoại)")

    return p_out, detected_lang
