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


def _register_cuda_dll_directories() -> None:
    """Tự động tìm kiếm, nạp và preload các thư mục chứa DLL của CUDA/cuBLAS/cuDNN vào Windows process."""
    import sys, os, ctypes
    if sys.platform != "win32":
        return

    added = set()
    for p in sys.path:
        if not p or not os.path.exists(p):
            continue
        p_path = Path(p)
        candidates = [
            p_path / "nvidia" / "cublas" / "bin",
            p_path / "nvidia" / "cublas" / "lib",
            p_path / "nvidia" / "cudnn" / "bin",
            p_path / "nvidia" / "cudnn" / "lib",
            p_path / "nvidia" / "cuda_nvrtc" / "bin",
            p_path / "nvidia" / "cuda_nvrtc" / "lib",
            p_path / "ctranslate2",
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

                # Preload các dll quan trọng nếu có trong thư mục
                for dll_file in c.glob("*.dll"):
                    try:
                        ctypes.CDLL(str(dll_file))
                    except Exception:
                        pass


def check_cuda_whisper_support() -> bool:
    """Kiểm tra thực tế xem CUDA và các thư viện DLL cuBLAS / cuDNN có sẵn sàng chạy Whisper AI trên GPU không."""
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() <= 0:
            return False
    except Exception:
        return False

    _register_cuda_dll_directories()

    import ctypes
    # Thử nạp cublas DLL trực tiếp
    for dll_name in ("cublas64_12.dll", "cublasLt64_12.dll", "cublas64_11.dll", "cublasLt64_11.dll"):
        try:
            ctypes.CDLL(dll_name)
            return True
        except Exception:
            continue

    # Thử tìm file DLL trong sys.path
    import sys
    for p in sys.path:
        if not p or not os.path.exists(p):
            continue
        p_path = Path(p)
        for cand in [p_path / "nvidia" / "cublas" / "bin", p_path / "torch" / "lib", p_path / "ctranslate2"]:
            for dll_name in ("cublas64_12.dll", "cublasLt64_12.dll", "cublas64_11.dll"):
                target = cand / dll_name
                if target.exists():
                    try:
                        ctypes.CDLL(str(target))
                        return True
                    except Exception:
                        pass
    return False


def transcribe_audio_to_srt(
    audio_path: str | Path,
    out_srt_path: str | Path,
    model_size: str = "base",
    language: str | None = None,
    log_callback: Any = None,
    progress_callback: Any = None,
    speed: float = 1.0,
    cancel_event: Any = None,
    audio_duration: float = 0.0,
) -> Tuple[Path, str]:
    """Tự động nghe audio bằng Whisper AI, nhận diện ngôn ngữ và xuất file .srt chuẩn xác theo từng từ với cơ chế Safe Fallback 100%."""
    if cancel_event and getattr(cancel_event, "is_set", lambda: False)():
        raise RenderCancelled("Đã dừng bởi người dùng")

    _register_cuda_dll_directories()
    p_audio = Path(audio_path)
    p_out = Path(out_srt_path)
    p_out.parent.mkdir(parents=True, exist_ok=True)

    import gc
    from faster_whisper import WhisperModel

    model_size = str(model_size or "base").strip()

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

    def _do_transcribe(device: str, compute_type: str) -> Tuple[List[Tuple[float, float, str]], str]:
        if cancel_event and getattr(cancel_event, "is_set", lambda: False)():
            raise RenderCancelled("Đã dừng bởi người dùng")

        if log_callback:
            if device == "cuda":
                log_callback(f"🚀 Đang khởi tạo Whisper AI [{model_size}] trên GPU (NVIDIA CUDA / {compute_type})...")
            else:
                cpu_threads = max(4, (os.cpu_count() or 4))
                log_callback(f"💻 Đang xử lý Whisper AI model [{model_size}] trên CPU (Đa luồng {cpu_threads} cores / {compute_type})...")

        cpu_threads = max(4, (os.cpu_count() or 4)) if device == "cpu" else 0
        model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads if device == "cpu" else 4,
            num_workers=2,
        )

        lang_msg = f"ngôn ngữ chỉ định: [{target_lang.upper()}]" if target_lang else "chế độ tự động nhận diện ngôn ngữ"
        if log_callback:
            log_callback(f"Đang quét giọng nói trong {p_audio.name} ({lang_msg}) bằng {device.upper()}...")

        segments, info = model.transcribe(
            str(p_audio),
            beam_size=5,
            best_of=5,
            language=target_lang,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=250),
            word_timestamps=True,
            condition_on_previous_text=False,
        )

        detected = target_lang or getattr(info, "language", "unknown") or "unknown"
        prob = getattr(info, "language_probability", 1.0) * 100
        if log_callback:
            log_callback(f"✔ Nhận diện giọng nói: [{detected.upper()}] (độ tin cậy: {prob:.1f}%) — Đang xử lý bóc tách...")

        try:
            events_list = build_accurate_subtitles(
                segments,
                max_words_per_line=6,
                max_duration_sec=2.8,
                speed=speed,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
                total_duration_sec=audio_duration,
            )
        finally:
            # Giải phóng model và bộ nhớ
            del model
            gc.collect()

        return events_list, detected

    events: List[Tuple[float, float, str]] = []
    detected_lang = target_lang or "unknown"
    used_device = "cpu"
    cuda_success = False

    # Giai đoạn 1: Chạy bằng GPU CUDA nếu Preflight Check đạt chuẩn
    if has_cuda_runtime:
        try:
            events, detected_lang = _do_transcribe("cuda", "float16")
            used_device = "cuda"
            cuda_success = True
        except RenderCancelled:
            raise
        except Exception as cuda_ex:
            if log_callback:
                log_callback(f"⚠️ GPU CUDA float16 gặp sự cố ({cuda_ex}) -> Tự động chuyển sang CPU int8 đa luồng...")
            events = []
            cuda_success = False
    else:
        if log_callback:
            log_callback("💡 GPU chưa đủ bộ thư viện CUDA cuBLAS -> Tự động xử lý Whisper AI bằng CPU đa luồng an toàn.")

    # Giai đoạn 2: Fallback sang CPU 100% an toàn nếu CUDA không khả dụng hoặc bị lỗi
    if not cuda_success:
        if cancel_event and getattr(cancel_event, "is_set", lambda: False)():
            raise RenderCancelled("Đã dừng bởi người dùng")
        events, detected_lang = _do_transcribe("cpu", "int8")
        used_device = "cpu"

    srt_lines: List[str] = []
    for idx, (start_sec, end_sec, text) in enumerate(events, start=1):
        if not text:
            continue
        start_str = format_timestamp_srt(start_sec)
        end_str = format_timestamp_srt(end_sec)
        srt_lines.append(f"{idx}\n{start_str} --> {end_str}\n{text}\n")

    p_out.write_text("\n".join(srt_lines), encoding="utf-8")
    if log_callback:
        log_callback(f"✔ Đã tạo file phụ đề .srt chính xác ({used_device.upper()}): {p_out.name} (gồm {len(events)} cụm thoại)")

    return p_out, detected_lang

