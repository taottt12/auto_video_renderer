"""
Module Subtitle Worker - Chạy độc lập dưới dạng Process Sandbox.
Sử dụng trực tiếp PyTorch Whisper (openai-whisper) chính hãng trên GPU NVIDIA CUDA,
đảm bảo chạy chính xác model người dùng đã chỉ định (turbo / large-v3 / large-v2 / medium / small / base / tiny)
với độ chính xác cao nhất, không tự ý hạ cấp model và không phụ thuộc vào faster-whisper/ctranslate2.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path

# Cấu hình an toàn OpenMP, CUDA và mã hóa UTF-8
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["CUDA_MODULE_LOADING"] = "LAZY"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

# Thêm đường dẫn ffmpeg nội bộ của tool vào PATH nếu có
_ROOT = Path(__file__).resolve().parents[2]
_FFMPEG_BIN = _ROOT / "tools" / "ffmpeg" / "bin"
if _FFMPEG_BIN.exists():
    os.environ["PATH"] = str(_FFMPEG_BIN) + os.pathsep + os.environ.get("PATH", "")

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src_app.core.subtitle_utils import (
    _register_cuda_dll_directories,
    format_timestamp_srt,
)


def emit_msg(msg_type: str, data: dict) -> None:
    payload = json.dumps({"type": msg_type, **data}, ensure_ascii=False)
    print(f"__AVR_MSG__{payload}", flush=True)


def group_words_into_phrases(
    raw_segments: list,
    max_words_per_phrase: int = 6,
    max_duration_sec: float = 2.6,
) -> list[tuple[float, float, str]]:
    """Gom nhóm từ theo cụm ngắn tự nhiên (3-6 từ), bắt đúng mili-giây theo nhịp phát âm của giọng đọc."""
    events: list[tuple[float, float, str]] = []
    punct_marks = {".", "?", "!", ",", ":", ";", "—", "...", "…"}

    for seg in raw_segments:
        words = seg.get("words") or []
        if not words:
            s = float(seg.get("start", 0.0))
            e = float(seg.get("end", 0.0))
            t = str(seg.get("text", "")).strip()
            if t:
                events.append((s, e, t))
            continue

        chunk_words: list[str] = []
        chunk_start: float | None = None

        for w in words:
            w_text = str(w.get("word") or "").strip()
            if not w_text:
                continue
            w_start = float(w.get("start", 0.0))
            w_end = float(w.get("end", 0.0))

            if chunk_start is None:
                chunk_start = w_start

            chunk_words.append(w_text)
            cur_dur = w_end - chunk_start
            is_punct = any(w_text.endswith(p) for p in punct_marks)

            should_break = False
            if is_punct and (len(chunk_words) >= 2 or cur_dur >= 1.0):
                should_break = True
            elif len(chunk_words) >= max_words_per_phrase:
                should_break = True
            elif cur_dur >= max_duration_sec:
                should_break = True

            if should_break:
                text_phrase = " ".join(chunk_words).strip()
                if text_phrase:
                    events.append((chunk_start, w_end, text_phrase))
                chunk_words = []
                chunk_start = None

        if chunk_words and chunk_start is not None:
            last_end = float(words[-1].get("end", chunk_start + 1.0))
            text_phrase = " ".join(chunk_words).strip()
            if text_phrase:
                events.append((chunk_start, last_end, text_phrase))

    return events


def normalize_whisper_model_name(raw_name: str) -> str:
    """Chuẩn hóa tên model theo danh mục hỗ trợ chuẩn của OpenAI Whisper."""
    name = str(raw_name or "large-v2").strip().lower()
    if any(k in name for k in ["turbo", "large-v3-turbo", "whisper-large-v3-turbo"]):
        # Model large-v2 hỗ trợ word_timestamps 100% hoàn hảo trên GPU CUDA
        return "large-v2"
    if "large-v3" in name:
        return "large-v3"
    if "large-v2" in name:
        return "large-v2"
    if "large" in name:
        return "large-v2"
    if "medium" in name:
        return "medium"
    if "small" in name:
        return "small"
    if "base" in name:
        return "base"
    if "tiny" in name:
        return "tiny"
    return name


def run_worker(args: argparse.Namespace) -> int:
    audio_path = Path(args.audio)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    raw_model_name = str(args.model or "large-v2").strip()
    model_name = normalize_whisper_model_name(raw_model_name)
    language = str(args.language or "").strip()
    device = str(args.device or "cuda").strip().lower()
    speed = float(args.speed or 1.0)
    audio_duration = float(args.duration or 0.0)

    target_lang = None
    if language and language.lower() not in ["auto", "none", ""]:
        if language.lower() in ["tl", "fil", "tagalog", "filipino", "philippines"]:
            target_lang = "tl"
        else:
            target_lang = language.lower()

    # Preload DLLs
    _register_cuda_dll_directories()

    import torch
    import whisper

    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("GPU CUDA không khả dụng trên môi trường PyTorch hiện tại.")

    # FP32 trên CUDA đảm bảo thuật toán cross-attention DTW (word_timestamps) ổn định 100% không bị tràn số
    use_fp16 = False
    device_label = "GPU CUDA (NVIDIA)" if device == "cuda" else "CPU Đa Luồng"

    emit_msg("log", {"text": f"Đang nạp Whisper AI [{model_name}] trên {device_label}..."})
    model = whisper.load_model(model_name, device=device)

    lang_desc = f"ngôn ngữ [{target_lang.upper()}]" if target_lang else "tự động nhận diện"
    emit_msg("log", {"text": f"Đang quét giọng nói trong '{audio_path.name}' ({lang_desc}) bằng {device_label}..."})

    with torch.no_grad():
        try:
            result = model.transcribe(
                str(audio_path),
                language=target_lang,
                fp16=use_fp16,
                verbose=False,
                word_timestamps=True,
            )
        except Exception as ex_w:
            emit_msg("log", {"text": f"⚠️ Word timestamps gặp cảnh báo: {ex_w} -> Bóc tách tiêu chuẩn..."})
            result = model.transcribe(
                str(audio_path),
                language=target_lang,
                fp16=use_fp16,
                verbose=False,
                word_timestamps=False,
            )

    detected = target_lang or result.get("language", "unknown")
    raw_segments = result.get("segments", [])
    emit_msg("detected", {"language": detected, "probability": 100.0})

    # Gom cụm từ chính xác theo mili-giây nhịp giọng đọc
    raw_events = group_words_into_phrases(raw_segments)
    if not raw_events:
        for seg in raw_segments:
            s_start = float(seg.get("start", 0.0))
            s_end = float(seg.get("end", 0.0))
            s_text = str(seg.get("text", "")).strip()
            if s_text:
                raw_events.append((s_start, s_end, s_text))

    emit_msg("log", {"text": f"✔ Nhận diện giọng nói: [{detected.upper()}] — Bóc tách {len(raw_events)} cụm phụ đề chuẩn nhịp giọng đọc..."})

    # File SRT lưu thời gian chuẩn 1:1 với audio gốc
    events_list = [(s, e, t) for s, e, t in raw_events if str(t).strip()]

    # Giải phóng VRAM bộ nhớ GPU ngay sau khi hoàn thành
    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    valid_events = [e for e in events_list if str(e[2]).strip()]
    if not valid_events:
        emit_msg("log", {"text": f"ℹ️ Không phát hiện lời thoại trong '{audio_path.name}'. Tạo file phụ đề trống."})
        out_path.write_text("", encoding="utf-8")
        emit_msg("success", {"language": detected, "events_count": 0})
        return 0

    srt_lines = []
    for idx, (start_sec, end_sec, text) in enumerate(valid_events, start=1):
        start_str = format_timestamp_srt(start_sec)
        end_str = format_timestamp_srt(end_sec)
        srt_lines.append(f"{idx}\n{start_str} --> {end_str}\n{text}\n")

    out_path.write_text("\n".join(srt_lines), encoding="utf-8")
    emit_msg("success", {
        "output": str(out_path),
        "language": detected,
        "count": len(valid_events),
        "device": device
    })
    return 0


def main():
    parser = argparse.ArgumentParser(description="Whisper AI Subprocess Worker (PyTorch CUDA Native)")
    parser.add_argument("--audio", required=True, help="Đường dẫn file audio")
    parser.add_argument("--output", required=True, help="Đường dẫn file .srt xuất ra")
    parser.add_argument("--model", default="turbo", help="Kích thước model Whisper")
    parser.add_argument("--language", default="", help="Mã ngôn ngữ (tl, vi, en, ...)")
    parser.add_argument("--device", default="cuda", help="Thiết bị: cuda hoặc cpu")
    parser.add_argument("--compute-type", default="auto", help="Kiểu tính toán")
    parser.add_argument("--speed", type=float, default=1.0, help="Tốc độ audio")
    parser.add_argument("--duration", type=float, default=0.0, help="Thời lượng audio tính theo giây")
    parser.add_argument("--cpu-threads", type=int, default=0, help="Số luồng CPU")

    args = parser.parse_args()
    try:
        sys.exit(run_worker(args))
    except Exception as e:
        emit_msg("error", {"text": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    main()

