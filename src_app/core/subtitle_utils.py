from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

os.environ["CUDA_MODULE_LOADING"] = "LAZY"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ.pop("CUBLAS_WORKSPACE_CONFIG", None)
os.environ.pop("CT2_CUDA_ALLOCATOR", None)


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


def post_process_subtitle_text(text: str, keywords: str | List[str] = "") -> str:
    """Nắn chỉnh và chuẩn hóa các từ nhận diện nhầm của Whisper AI dựa theo danh sách từ khóa ngữ cảnh & tiêu đề."""
    if not text:
        return ""

    clean_t = str(text)
    kw_list: List[str] = []
    if isinstance(keywords, str):
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
    elif isinstance(keywords, list):
        for k in keywords:
            if isinstance(k, str) and k.strip():
                kw_list.extend([subk.strip() for subk in k.split(",") if subk.strip()])

    # 1. Các quy tắc nhận diện sai phiên âm phổ biến (Common Misrecognitions)
    common_rules = [
        (r"\b(ain\s*awao|ayna\s*waw|ayna\s*waow|ayn\s*awow|ayna\s*vao|ain\s*wow|ayn\s*a\s*wow)\b", "AYNA WOW"),
        (r"\b(pinoy\s*lugh\s*radio|pinoy\s*lough\s*radio|pinoy\s*lauch\s*radio|pinoy\s*laugh\s*rad)\b", "PINOY LAUGH RADIO"),
    ]
    for pat, repl in common_rules:
        clean_t = re.sub(pat, repl, clean_t, flags=re.IGNORECASE)

    # 2. Quy tắc động từ Keywords người dùng cung cấp
    for kw in kw_list:
        kw_clean = kw.strip()
        if not kw_clean or len(kw_clean) < 3:
            continue
        kw_tokens = re.split(r"[\s\-_]+", kw_clean)
        if len(kw_tokens) >= 2:
            token_pattern = r"\s+".join(re.escape(tok) for tok in kw_tokens)
            try:
                clean_t = re.sub(r"\b" + token_pattern + r"\b", kw_clean, clean_t, flags=re.IGNORECASE)
            except Exception:
                pass

    return clean_t


def split_long_subtitle_event(
    start_sec: float,
    end_sec: float,
    text: str,
    max_words_per_line: int = 6,
    max_chars: int = 45,
) -> List[Tuple[float, float, str]]:
    """Tự động băm nhỏ các block sub quá dài (>= 8 từ hoặc >= 45 ký tự) thành các cụm 5-7 từ, tối đa 2 dòng."""
    clean_text = str(text or "").strip()
    if not clean_text:
        return []

    words = clean_text.split()
    # Nếu câu đã ngắn (<= 7 từ và <= 45 ký tự) thì giữ nguyên
    if len(words) <= 7 and len(clean_text) <= 45:
        return [(start_sec, end_sec, clean_text)]

    punct_marks = {".", "?", "!", ",", ":", ";", "—", "...", "…"}
    chunks: List[str] = []
    current_chunk: List[str] = []

    for w in words:
        current_chunk.append(w)
        cur_t = " ".join(current_chunk)
        is_punct = any(w.endswith(p) for p in punct_marks)

        should_break = False
        if is_punct and len(current_chunk) >= 2:
            should_break = True
        elif len(current_chunk) >= max_words_per_line:
            should_break = True
        elif len(cur_t) >= max_chars:
            should_break = True

        if should_break:
            chunks.append(cur_t.strip())
            current_chunk = []

    if current_chunk:
        rem = " ".join(current_chunk).strip()
        if rem:
            chunks.append(rem)

    if not chunks:
        return [(start_sec, end_sec, clean_text)]
    if len(chunks) == 1:
        return [(start_sec, end_sec, chunks[0])]

    res: List[Tuple[float, float, str]] = []
    tot_words = sum(max(1, len(c.split())) for c in chunks)
    tot_dur = max(0.4, end_sec - start_sec)
    cur_s = start_sec
    for idx, c in enumerate(chunks):
        w_c = max(1, len(c.split()))
        c_dur = tot_dur * (w_c / tot_words)
        c_e = end_sec if idx == len(chunks) - 1 else min(end_sec, cur_s + c_dur)
        res.append((cur_s, c_e, c))
        cur_s = c_e

    return res


def parse_srt_to_raw_events(
    srt_text: str,
    speed: float = 1.0,
    keywords: str | List[str] = "",
) -> List[Tuple[float, float, str]]:
    """Phân tích văn bản SRT thành danh sách (start_sec, end_sec, text) đã bù trừ audio_speed và nắn chỉnh từ khóa."""
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
                txt = post_process_subtitle_text(txt, keywords=keywords)
                # Băm nhỏ ngay nếu block sub trong SRT ban đầu quá dài
                sub_chunks = split_long_subtitle_event(s_sec, e_sec, txt)
                for cs, ce, ct in sub_chunks:
                    raw_events.append((cs, ce, ct))
    return raw_events


def generate_rolling_2line_events(
    raw_events: List[Tuple[float, float, str]],
    max_hold_sec: float = 3.0
) -> List[Tuple[str, str, str]]:
    """Tạo event ASS cuộn 2 dòng: câu cũ được đẩy lên trên, câu mới xuất hiện ở dưới theo đúng nhịp nói."""
    dialogues: List[Tuple[str, str, str]] = []
    n = len(raw_events)
    for i in range(n):
        s_i, e_i, t_i = raw_events[i]
        next_s = raw_events[i + 1][0] if i + 1 < n else e_i + 1.5
        eff_end = min(next_s, max(e_i, s_i + 1.2))

        start_ass = seconds_to_ass_time(s_i)
        end_ass = seconds_to_ass_time(eff_end)

        if i == 0:
            dialogues.append((start_ass, end_ass, t_i))
        else:
            prev_t = raw_events[i - 1][2]
            prev_s = raw_events[i - 1][0]
            # Chỉ gộp dòng trước nếu khoảng cách ngắn (<= 2.5s) và dòng trước không quá dài
            if (s_i - prev_s <= 2.5) and (len(prev_t) + len(t_i) <= 65):
                dialogues.append((start_ass, end_ass, f"{prev_t}\\N{t_i}"))
            else:
                dialogues.append((start_ass, end_ass, t_i))
    return dialogues


def generate_cinema_hold_events(
    raw_events: List[Tuple[float, float, str]],
    min_hold_sec: float = 1.0,
    max_gap_bridge_sec: float = 0.25
) -> List[Tuple[str, str, str]]:
    """Tạo event ASS chuẩn điện ảnh: hiển thị từng câu/cụm ngắn chuẩn xác theo nhịp phát âm."""
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
    sub_keywords = sub_cfg.get("whisper_keywords", "") or sub_cfg.get("initial_prompt", "") or ""

    content = read_subtitle_file(srt_p)
    raw_events = parse_srt_to_raw_events(content, speed=speed, keywords=sub_keywords)
    dialogues: List[Tuple[str, str, str]] = []

    font_name = str(sub_cfg.get("font_name") or sub_cfg.get("font_family") or "Arial")
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

    # Tính MarginV căn giữa tâm Bounding Box khớp chính xác 100% với Canvas Preview (Qt.AlignCenter)
    box_pixel_h = int(box_h * height)
    text_est_h = int(scaled_font_size * 2.2)
    center_v_offset = max(0, (box_pixel_h - text_est_h) // 2)
    margin_v = max(10, int((1.0 - (box_y + box_h)) * height) + center_v_offset)

    # Alignment trong ASS: 1 = Bottom-Left, 2 = Bottom-Center, 3 = Bottom-Right
    align_str = str(sub_cfg.get("align", "center")).lower()
    if align_str == "left":
        ass_align = 1
    elif align_str == "right":
        ass_align = 3
    else:
        ass_align = 2

    # Thiết lập màu sắc và sự kiện theo chế độ phụ đề
    if not raw_events:
        primary_color_ass = hex_to_ass_color(font_color)
        secondary_color_ass = "&H000000FF"
        outline_color_ass = hex_to_ass_color(outline_color)
        dialogues = []
    elif sub_mode == "karaoke_highlight":
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


class RenderCancelled(RuntimeError):
    """Ngoại lệ khi người dùng chủ động bấm Dừng render."""
    pass


def format_timestamp_short(seconds: float) -> str:
    """Định dạng giây thành chuỗi MM:SS hoặc HH:MM:SS ngắn gọn."""
    sec = max(0, int(seconds))
    hrs = sec // 3600
    mins = (sec % 3600) // 60
    secs = sec % 60
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def build_accurate_subtitles(
    segments: Any,
    max_words_per_line: int = 6,
    max_duration_sec: float = 2.8,
    speed: float = 1.0,
    cancel_event: Any = None,
    progress_callback: Any = None,
    total_duration_sec: float = 0.0,
) -> List[Tuple[float, float, str]]:
    """Gom nhóm từ theo cụm ngắn tự nhiên, bắt đúng mili-giây và hỗ trợ ngắt khi hủy cùng cập nhật tiến trình."""
    events: List[Tuple[float, float, str]] = []
    eff_speed = speed if (speed > 0.001) else 1.0

    for seg in segments:
        if cancel_event and getattr(cancel_event, "is_set", lambda: False)():
            raise RenderCancelled("Đã dừng bởi người dùng")

        if progress_callback and total_duration_sec > 0:
            cur_sec = float(getattr(seg, "end", 0.0) or 0.0)
            pct = min(99, max(12, int((cur_sec / total_duration_sec) * 100)))
            cur_str = format_timestamp_short(cur_sec)
            tot_str = format_timestamp_short(total_duration_sec)
            progress_callback(pct, f"Whisper AI: {cur_str} / {tot_str} ({pct}%)")

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
            if cancel_event and getattr(cancel_event, "is_set", lambda: False)():
                raise RenderCancelled("Đã dừng bởi người dùng")

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


def ensure_cuda_whisper_libraries() -> bool:
    """Tự động kiểm tra và cấu hình các thư mục DLL CUDA cần thiết cho PyTorch Whisper trên GPU NVIDIA."""
    _register_cuda_dll_directories()
    return check_cuda_whisper_support()


def _register_cuda_dll_directories() -> None:
    """Tự động tìm kiếm, nạp và preload các thư mục chứa DLL của CUDA/cuBLAS/cuDNN vào Windows process."""
    import sys, os
    if sys.platform != "win32":
        return

    added = set()
    for p in sys.path:
        if not p or not os.path.exists(p):
            continue
        p_path = Path(p)
        candidates = [
            p_path / "nvidia" / "cublas" / "bin",
            p_path / "nvidia" / "cudnn" / "bin",
            p_path / "nvidia" / "cuda_nvrtc" / "bin",
            p_path / "nvidia" / "cuda_runtime" / "bin",
            p_path / "torch" / "lib",
        ]
        for c in candidates:
            if c.exists() and str(c) not in added:
                try:
                    if hasattr(os, "add_dll_directory"):
                        os.add_dll_directory(str(c))
                    os.environ["PATH"] = str(c) + os.pathsep + os.environ.get("PATH", "")
                    added.add(str(c))
                except Exception:
                    pass


CUDA_FATAL_EXIT_CODE = 42


def normalize_whisper_model_name(raw_name: str) -> str:
    """Chuẩn hóa tên model theo danh mục hỗ trợ chuẩn của OpenAI Whisper."""
    name = str(raw_name or "turbo").strip().lower()
    if name in ["turbo", "large-v3-turbo", "large_v3_turbo", "large-turbo", "turbo-v3"]:
        return "turbo"
    valid_exact = [
        "tiny.en", "tiny",
        "base.en", "base",
        "small.en", "small",
        "medium.en", "medium",
        "large-v3", "large-v2", "large-v1", "large",
    ]
    if name in valid_exact:
        return name
    for valid in valid_exact:
        if name == valid or name.startswith(valid) or f"/{valid}" in name or f"-{valid}" in name or f"_{valid}" in name:
            return valid
    if "turbo" in name:
        return "turbo"
    if "medium" in name:
        return "medium"
    if "small" in name:
        return "small"
    if "base" in name:
        return "base"
    if "tiny" in name:
        return "tiny"
    if "large" in name:
        return "large-v3"
    return "turbo"


def check_cuda_whisper_support() -> bool:
    """Kiểm tra thực tế xem CUDA GPU có sẵn sàng chạy PyTorch Whisper AI không."""
    try:
        _register_cuda_dll_directories()
        import torch
        return bool(torch.cuda.is_available() and torch.cuda.device_count() > 0)
    except Exception:
        return False


def preflight_whisper_model(model_name: str = "turbo", log_callback: Any = None) -> Tuple[bool, str]:
    """Kiểm tra nhanh toàn diện model Whisper và GPU CUDA trước khi render trong Sandbox an toàn."""
    def _safe_log_local(msg: str):
        if log_callback:
            try:
                log_callback(msg)
            except Exception:
                try:
                    # Fallback ASCII safe print
                    log_callback(msg.encode("ascii", errors="replace").decode("ascii"))
                except Exception:
                    pass

    try:
        ensure_cuda_whisper_libraries()
        has_cuda = check_cuda_whisper_support()
        if not has_cuda:
            msg = "CUDA GPU không khả dụng. Sẽ sử dụng CPU đa luồng để bóc tách phụ đề."
            _safe_log_local(f"ℹ️ {msg}")
            return True, msg

        m_id = normalize_whisper_model_name(model_name)
        _safe_log_local(f"🔍 [Preflight] Đang kiểm tra Whisper AI [{m_id}] trên GPU CUDA...")

        import tempfile
        import wave
        import struct

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_wav = Path(tmp_dir) / "test_preflight.wav"
            tmp_srt = Path(tmp_dir) / "test_preflight.srt"
            with wave.open(str(tmp_wav), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(struct.pack("<16000h", *([0] * 16000)))

            ok, err_msg, detected, ret_code = _run_isolated_whisper(
                audio_path=tmp_wav,
                out_srt_path=tmp_srt,
                model_size=m_id,
                language="en",
                device="cuda",
                compute_type="fp16",
                speed=1.0,
                audio_duration=1.0,
                cancel_event=None,
                log_callback=_safe_log_local,
                progress_callback=None,
            )

        if ok:
            success_msg = f"GPU CUDA & Whisper AI [{m_id}] sẵn sàng 100%!"
            _safe_log_local(f"✔ [Preflight] {success_msg}")
            return True, success_msg
        else:
            err_msg_clean = f"Model [{m_id}] gặp sự cố trên GPU CUDA ({err_msg})."
            _safe_log_local(f"⚠️ [Preflight] {err_msg_clean}")
            return False, err_msg_clean
    except Exception as ex:
        err_msg = f"Model [{model_name}] gặp cảnh báo trên GPU: {ex}"
        _safe_log_local(f"⚠️ [Preflight] {err_msg}")
        return False, str(ex)



def _safe_log(cb, msg: str):
    """Gửi log an toàn, chống lỗi UnicodeEncodeError trên console Windows CP1252."""
    if not cb or not msg:
        return
    try:
        cb(str(msg))
    except Exception:
        try:
            clean = str(msg).encode("ascii", errors="replace").decode("ascii")
            cb(clean)
        except Exception:
            pass


def _run_isolated_whisper(
    audio_path: Path,
    out_srt_path: Path,
    model_size: str,
    language: str | None,
    device: str,
    compute_type: str,
    speed: float,
    audio_duration: float,
    cancel_event: Any,
    log_callback: Any,
    progress_callback: Any = None,
    cpu_threads: int = 0,
    enhance_voice: bool = True,
    initial_prompt: str = "",
) -> Tuple[bool, str, str, int]:
    """Chạy Whisper AI trong Process Sandbox riêng biệt để cách ly tuyệt đối lỗi driver/C++ khỏi GUI."""
    import json
    import queue
    import subprocess
    import threading
    import time

    python_exe = sys.executable
    if not python_exe or not Path(python_exe).exists():
        python_exe = "python"

    cmd = [
        str(python_exe),
        "-u",
        "-m",
        "src_app.core.subtitle_worker",
        "--audio", str(audio_path),
        "--output", str(out_srt_path),
        "--model", str(model_size),
        "--language", str(language or ""),
        "--device", str(device),
        "--compute-type", str(compute_type),
        "--speed", str(speed),
        "--duration", str(audio_duration),
        "--cpu-threads", str(cpu_threads),
    ]
    if initial_prompt:
        cmd.extend(["--initial-prompt", str(initial_prompt)])
    if enhance_voice:
        cmd.append("--enhance-voice")
    else:
        cmd.append("--no-enhance-voice")

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    worker_env = os.environ.copy()
    worker_env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    worker_env["CUDA_MODULE_LOADING"] = "LAZY"
    worker_env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creation_flags,
            cwd=str(Path(__file__).resolve().parents[2]),
            env=worker_env,
        )
    except Exception as spawn_err:
        return False, f"Không thể khởi động worker: {spawn_err}", "unknown", -1

    detected_lang = language or "unknown"
    error_msg = ""
    out_queue: queue.Queue[str | None] = queue.Queue()

    def _reader_thread_target():
        try:
            if proc.stdout:
                for line in iter(proc.stdout.readline, ""):
                    if line:
                        out_queue.put(line)
        except Exception:
            pass
        finally:
            out_queue.put(None)

    t_reader = threading.Thread(target=_reader_thread_target, daemon=True)
    t_reader.start()

    while True:
        if cancel_event and getattr(cancel_event, "is_set", lambda: False)():
            try:
                proc.kill()
                proc.wait(timeout=1.5)
            except Exception:
                pass
            raise RenderCancelled("Đã dừng bởi người dùng")

        try:
            line = out_queue.get(timeout=0.1)
        except queue.Empty:
            if proc.poll() is not None:
                # Tiến trình đã kết thúc và không còn dòng log mới trong queue
                break
            continue

        if line is None:
            # Luồng đọc kết thúc stream output
            break

        clean_line = line.strip()
        if clean_line.startswith("__AVR_MSG__"):
            try:
                payload = json.loads(clean_line[len("__AVR_MSG__"):])
                msg_type = payload.get("type")
                if msg_type == "log":
                    _safe_log(log_callback, payload.get("text", ""))
                elif msg_type == "progress" and progress_callback:
                    progress_callback(int(payload.get("percent", 0)), str(payload.get("message", "")))
                elif msg_type == "detected":
                    detected_lang = payload.get("language", detected_lang)
                elif msg_type == "error":
                    error_msg = payload.get("text", "")
                elif msg_type == "success":
                    detected_lang = payload.get("language", detected_lang)
            except Exception:
                pass

    try:
        proc.wait(timeout=2.0)
    except Exception:
        pass

    ret_code = proc.poll()
    if ret_code is None:
        ret_code = 0 if (out_srt_path.exists() and out_srt_path.stat().st_size > 0) else 1

    if ret_code == 0 and out_srt_path.exists():
        return True, "", detected_lang, ret_code
    else:
        err = error_msg or f"Tiến trình kết thúc với mã {ret_code}"
        return False, err, detected_lang, ret_code


def transcribe_audio_to_srt(
    audio_path: str | Path,
    out_srt_path: str | Path,
    model_size: str = "turbo",
    language: str | None = None,
    log_callback: Any = None,
    progress_callback: Any = None,
    speed: float = 1.0,
    cancel_event: Any = None,
    audio_duration: float = 0.0,
    enhance_voice: bool = True,
    initial_prompt: str = "",
) -> Tuple[Path, str]:
    """Tự động nghe audio bằng Whisper AI, nhận diện ngôn ngữ và xuất file .srt chuẩn xác theo từng từ với Process Sandbox 100% an toàn."""
    if cancel_event and getattr(cancel_event, "is_set", lambda: False)():
        raise RenderCancelled("Đã dừng bởi người dùng")

    _register_cuda_dll_directories()
    p_audio = Path(audio_path)
    p_out = Path(out_srt_path)
    p_out.parent.mkdir(parents=True, exist_ok=True)

    # Chuẩn hóa model size chính xác theo danh mục chuẩn (không ép nhỏ về turbo)
    model_size = normalize_whisper_model_name(model_size)

    # Chuẩn hóa mã ngôn ngữ (Philippines: tl / fil)
    target_lang = None
    if language:
        lang_clean = str(language).strip().lower()
        if lang_clean not in ["auto", "none", ""]:
            if lang_clean in ["tl", "fil", "tagalog", "filipino", "philippines"]:
                target_lang = "tl"
            else:
                target_lang = lang_clean

    # Preflight Check CUDA cuBLAS thực tế
    has_cuda_runtime = check_cuda_whisper_support()

    success = False
    detected_lang = target_lang or "unknown"
    used_device = "cpu"

    # Giai đoạn 1: Chạy trực tiếp trên GPU CUDA bằng Process Sandbox (Tách biệt hoàn toàn process)
    if has_cuda_runtime:
        try:
            ok, err_msg, lang_res, ret_code = _run_isolated_whisper(
                audio_path=p_audio,
                out_srt_path=p_out,
                model_size=model_size,
                language=target_lang,
                device="cuda",
                compute_type="fp16",
                speed=speed,
                audio_duration=audio_duration,
                cancel_event=cancel_event,
                log_callback=log_callback,
                progress_callback=progress_callback,
                enhance_voice=enhance_voice,
                initial_prompt=initial_prompt,
            )
            if ok:
                success = True
                used_device = "GPU CUDA (PyTorch Native FP16)"
                detected_lang = lang_res
            elif ret_code == CUDA_FATAL_EXIT_CODE:
                _safe_log(
                    log_callback,
                    f"⚠️ [Process Sandbox] Worker CUDA gặp lỗi CUDA context/driver (Exit code {CUDA_FATAL_EXIT_CODE}: {err_msg}). "
                    f"Tiến trình cũ đã bị hủy. Đang spawn 1 worker CUDA MỚI hoàn toàn để retry (1/1)..."
                )
                if cancel_event and getattr(cancel_event, "is_set", lambda: False)():
                    raise RenderCancelled("Đã dừng bởi người dùng")

                # Spawn worker CUDA mới toanh (fresh process, fresh CUDA context)
                ok_retry, err_retry, lang_retry, ret_retry = _run_isolated_whisper(
                    audio_path=p_audio,
                    out_srt_path=p_out,
                    model_size=model_size,
                    language=target_lang,
                    device="cuda",
                    compute_type="fp16",
                    speed=speed,
                    audio_duration=audio_duration,
                    cancel_event=cancel_event,
                    log_callback=log_callback,
                    progress_callback=progress_callback,
                    enhance_voice=enhance_voice,
                    initial_prompt=initial_prompt,
                )
                if ok_retry:
                    success = True
                    used_device = "GPU CUDA (PyTorch Native FP16 - Recovered Worker)"
                    detected_lang = lang_retry
                    _safe_log(log_callback, f"🎉 [Process Sandbox] Worker CUDA mới đã hoàn tất bóc tách phụ đề thành công!")
                else:
                    _safe_log(
                        log_callback,
                        f"⚠️ [Process Sandbox] Worker CUDA mới retry tiếp tục thất bại ({err_retry}) -> Chuyển sang fallback CPU đa luồng giữ nguyên model [{model_size}]..."
                    )
            else:
                _safe_log(log_callback, f"⚠️ GPU CUDA gặp sự cố [{err_msg}] -> Tự động chuyển sang CPU đa luồng giữ nguyên model [{model_size}]...")
        except RenderCancelled:
            raise
        except Exception as cuda_ex:
            _safe_log(log_callback, f"⚠️ GPU CUDA gặp ngoại lệ [{cuda_ex}] -> Tự động chuyển sang CPU đa luồng giữ nguyên model [{model_size}]...")

    # Giai đoạn 2: Fallback sang CPU đa luồng nếu GPU hoàn toàn không khả dụng
    if not success:
        if cancel_event and getattr(cancel_event, "is_set", lambda: False)():
            raise RenderCancelled("Đã dừng bởi người dùng")
        cpu_threads_count = min(8, max(2, os.cpu_count() or 4))
        ok, err_msg, lang_cpu, ret_code = _run_isolated_whisper(
            audio_path=p_audio,
            out_srt_path=p_out,
            model_size=model_size,
            language=target_lang,
            device="cpu",
            compute_type="fp32",
            speed=speed,
            audio_duration=audio_duration,
            cancel_event=cancel_event,
            log_callback=log_callback,
            progress_callback=progress_callback,
            cpu_threads=cpu_threads_count,
            enhance_voice=enhance_voice,
            initial_prompt=initial_prompt,
        )
        if not ok:
            raise RuntimeError(f"Lỗi Whisper AI khi tạo phụ đề trên CPU: {err_msg}")
        used_device = f"cpu ({cpu_threads_count} threads)"
        detected_lang = lang_cpu

    if not p_out.exists():
        raise RuntimeError(f"Không thể tạo file phụ đề cho: '{p_audio.name}'.")

    _safe_log(log_callback, f"✔ Đã tạo file phụ đề .srt chính xác ({used_device.upper()}): {p_out.name}")

    return p_out, detected_lang

