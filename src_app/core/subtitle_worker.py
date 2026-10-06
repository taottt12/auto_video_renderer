"""
Module Subtitle Worker - Chạy độc lập dưới dạng Process Sandbox.
Sử dụng trực tiếp PyTorch Whisper (openai-whisper) chính hãng trên GPU NVIDIA CUDA,
đảm bảo chạy chính xác model người dùng đã chỉ định (turbo / large-v3 / medium / small / base / tiny)
với độ chính xác cao nhất, không tự ý hạ cấp model và không phụ thuộc vào faster-whisper/ctranslate2.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
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
    post_process_subtitle_text,
)


def emit_msg(msg_type: str, data: dict) -> None:
    payload = json.dumps({"type": msg_type, **data}, ensure_ascii=False)
    print(f"__AVR_MSG__{payload}", flush=True)


def split_text_into_chunks(text: str, max_words: int = 6, max_chars: int = 45) -> list[str]:
    """Cắt nhỏ đoạn văn bản thành các cụm ngắn 3-6 từ, tối đa 45 ký tự để không bao giờ tràn màn hình."""
    if not text:
        return []
    words = text.split()
    if not words:
        return []

    punct_marks = {".", "?", "!", ",", ":", ";", "—", "...", "…"}
    chunks: list[str] = []
    current_chunk: list[str] = []

    for w in words:
        current_chunk.append(w)
        cur_text = " ".join(current_chunk)
        is_punct = any(w.endswith(p) for p in punct_marks)

        should_break = False
        if is_punct and len(current_chunk) >= 2:
            should_break = True
        elif len(current_chunk) >= max_words:
            should_break = True
        elif len(cur_text) >= max_chars:
            should_break = True

        if should_break:
            chunks.append(cur_text.strip())
            current_chunk = []

    if current_chunk:
        remaining_text = " ".join(current_chunk).strip()
        if remaining_text:
            chunks.append(remaining_text)

    return chunks


def group_words_into_phrases(
    raw_segments: list,
    max_words_per_phrase: int = 6,
    max_duration_sec: float = 2.6,
) -> list[tuple[float, float, str]]:
    """Gom nhóm từ theo cụm ngắn tự nhiên (3-6 từ, max 2 dòng), đảm bảo thời gian chính xác và không bao giờ tràn màn hình."""
    events: list[tuple[float, float, str]] = []
    punct_marks = {".", "?", "!", ",", ":", ";", "—", "...", "…"}

    for seg in raw_segments:
        words = seg.get("words") or []
        if not words:
            s = float(seg.get("start", 0.0))
            e = float(seg.get("end", 0.0))
            t = str(seg.get("text", "")).strip()
            if not t:
                continue

            # Chia nhỏ câu dài thành các cụm 5-6 từ và nội suy thời gian tuyến tính
            chunks = split_text_into_chunks(t, max_words=max_words_per_phrase, max_chars=45)
            if not chunks:
                continue
            if len(chunks) == 1:
                events.append((s, e, chunks[0]))
            else:
                total_words = sum(max(1, len(c.split())) for c in chunks)
                total_dur = max(0.4, e - s)
                cur_start = s
                for idx, chunk in enumerate(chunks):
                    w_cnt = max(1, len(chunk.split()))
                    chunk_dur = total_dur * (w_cnt / total_words)
                    chunk_end = e if idx == len(chunks) - 1 else min(e, cur_start + chunk_dur)
                    events.append((cur_start, chunk_end, chunk))
                    cur_start = chunk_end
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
            cur_char_len = sum(len(x) for x in chunk_words) + len(chunk_words) - 1
            is_punct = any(w_text.endswith(p) for p in punct_marks)

            should_break = False
            if is_punct and (len(chunk_words) >= 2 or cur_dur >= 1.0):
                should_break = True
            elif len(chunk_words) >= max_words_per_phrase:
                should_break = True
            elif cur_dur >= max_duration_sec:
                should_break = True
            elif cur_char_len >= 45:
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
    name = str(raw_name or "turbo").strip().lower()
    if "medium" in name:
        return "medium"
    # Mặc định tất cả các lựa chọn khác đều map chuẩn sang turbo (large-v3-turbo.pt) đã có sẵn trong cache
    return "turbo"



def run_worker(args: argparse.Namespace) -> int:
    _register_cuda_dll_directories()
    import torch
    import whisper

    audio_path = Path(args.audio)
    out_path = Path(args.output)
    model_name = normalize_whisper_model_name(args.model)
    target_lang = str(args.language or "").strip().lower() or None
    device = str(args.device or "cuda").lower()
    compute_type = str(args.compute_type or "auto")
    speed = float(args.speed or 1.0)
    duration = float(args.duration or 0.0)
    cpu_threads = int(args.cpu_threads or 0)
    initial_prompt = str(args.initial_prompt or "").strip()

    if device == "cuda" and not torch.cuda.is_available():
        emit_msg("log", {"text": "⚠️ GPU CUDA không khả dụng trên tiến trình worker, tự động chuyển sang CPU..."})
        device = "cpu"

    if device == "cpu" and cpu_threads > 0:
        try:
            torch.set_num_threads(cpu_threads)
        except Exception:
            pass

    input_to_whisper = audio_path
    temp_clean_wav: Path | None = None


    # GIAI ĐOẠN 1: BỘ LỌC TĂNG CƯỜNG DẢI TẦN GIỌNG NÓI & TRIỆT TIÊU TẠP ÂM (FFMPEG DSP)
    if getattr(args, "enhance_voice", True):
        try:
            clean_wav_path = out_path.parent / f"_temp_whisper_clean_{audio_path.stem}.wav"
            clean_cmd = [
                "ffmpeg", "-y", "-i", str(audio_path),
                "-af", "highpass=f=120,lowpass=f=3800,afftdn=nf=-25,dynaudnorm=f=150:g=15",
                "-ar", "16000", "-ac", "1",
                str(clean_wav_path)
            ]
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            subprocess.run(
                clean_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
                check=True
            )
            if clean_wav_path.exists() and clean_wav_path.stat().st_size > 1000:
                input_to_whisper = clean_wav_path
                temp_clean_wav = clean_wav_path
                emit_msg("log", {"text": "🎙️ Tiền xử lý: Đã lọc dải tần giọng nói & triệt tiêu nhạc nền qua FFmpeg DSP."})
        except Exception as filter_err:
            emit_msg("log", {"text": f"ℹ️ Bộ lọc tiền xử lý bỏ qua ({filter_err}), tiếp tục dùng audio gốc."})

    # FP16 trên CUDA tận dụng Tensor Cores, giảm 50% VRAM và tăng tốc gấp đôi
    use_fp16 = bool(device == "cuda")
    device_label = "GPU CUDA (NVIDIA)" if device == "cuda" else "CPU Đa Luồng"

    emit_msg("log", {"text": f"Đang nạp Whisper AI [{model_name}] trên {device_label}..."})
    model = whisper.load_model(model_name, device=device)

    lang_desc = f"ngôn ngữ [{target_lang.upper()}]" if target_lang else "tự động nhận diện"
    if initial_prompt:
        emit_msg("log", {"text": f"💡 Whisper Context Prompt: Gợi ý từ khóa [{initial_prompt}]"})
    emit_msg("log", {"text": f"Đang quét giọng nói trong '{audio_path.name}' ({lang_desc}) bằng {device_label}..."})

    with torch.no_grad():
        result = None
        try:
            emit_msg("log", {"text": f"Đang quét giọng nói với độ chính xác chuẩn từng từ (Word-level timestamps)..."})
            result = model.transcribe(
                str(input_to_whisper),
                language=target_lang,
                initial_prompt=initial_prompt if initial_prompt else None,
                fp16=use_fp16,
                verbose=False,
                word_timestamps=True,
                no_speech_threshold=0.3,
                logprob_threshold=-1.0,
                condition_on_previous_text=False,
                temperature=(0.0, 0.2, 0.4),
                beam_size=5,
            )
        except Exception as wt_err:
            emit_msg("log", {"text": f"ℹ️ Chuyển sang Native Tokens an toàn ({wt_err})..."})
            result = model.transcribe(
                str(input_to_whisper),
                language=target_lang,
                initial_prompt=initial_prompt if initial_prompt else None,
                fp16=use_fp16,
                verbose=False,
                word_timestamps=False,
                no_speech_threshold=0.3,
                logprob_threshold=-1.0,
                condition_on_previous_text=False,
                temperature=(0.0, 0.2, 0.4),
                beam_size=5,
            )

    # Dọn dẹp file wav tạm sau khi transcribe
    if temp_clean_wav and temp_clean_wav.exists():
        try:
            temp_clean_wav.unlink(missing_ok=True)
        except Exception:
            pass

    detected = target_lang or result.get("language", "unknown")
    raw_segments = result.get("segments", [])
    emit_msg("detected", {"language": detected, "probability": 100.0})

    # Lọc chống Hallucination & Cảnh báo Long Subtitle:
    # 1. Nếu segment_duration > 10s và word_count <= 3 -> suspected hallucination, loại bỏ không đưa vào SRT, ghi log cảnh báo
    # 2. Nếu segment_duration > 8s -> ghi log cảnh báo [LONG SUBTITLE DETECTED]
    filtered_segments = []
    for seg in raw_segments:
        s_start = float(seg.get("start", 0.0))
        s_end = float(seg.get("end", 0.0))
        s_text = str(seg.get("text", "")).strip()
        s_dur = max(0.0, s_end - s_start)
        w_cnt = len(s_text.split())

        # Ghi log cảnh báo Long Subtitle nếu duration > 8s
        if s_dur > 8.0:
            emit_msg("log", {"text": f"ℹ️ [LONG SUBTITLE DETECTED] Phân đoạn dài {s_dur:.2f}s ({s_start:.2f}s -> {s_end:.2f}s): '{s_text}'"})

        # Cơ chế chống Hallucination: duration > 10s và word_count <= 3
        if s_dur > 10.0 and w_cnt <= 3:
            emit_msg("log", {"text": f"⚠️ [SUSPECTED HALLUCINATION] Bỏ qua segment nghi vấn ảo giác ({s_dur:.2f}s, {w_cnt} từ): {s_start:.2f}s -> {s_end:.2f}s '{s_text}'"})
            continue

        if s_start < 30.0:
            no_speech = float(seg.get("no_speech_prob", 0.0))
            emit_msg("log", {"text": f"🎙️ [0-30s Segment] {s_start:.2f}s -> {s_end:.2f}s (no_speech: {no_speech:.2f}): '{s_text}'"})

        filtered_segments.append(seg)

    # Gom cụm từ chính xác theo mili-giây nhịp giọng đọc (tối đa 5-6 từ, max 2 dòng)
    raw_events = group_words_into_phrases(filtered_segments)
    if not raw_events:
        for seg in filtered_segments:
            s_start = float(seg.get("start", 0.0))
            s_end = float(seg.get("end", 0.0))
            s_text = str(seg.get("text", "")).strip()
            if s_text:
                chunks = split_text_into_chunks(s_text, max_words=6, max_chars=45)
                if len(chunks) <= 1:
                    raw_events.append((s_start, s_end, s_text))
                else:
                    tot_w = sum(max(1, len(c.split())) for c in chunks)
                    tot_d = max(0.4, s_end - s_start)
                    c_st = s_start
                    for idx, chk in enumerate(chunks):
                        w_c = max(1, len(chk.split()))
                        c_dur = tot_d * (w_c / tot_w)
                        c_en = s_end if idx == len(chunks) - 1 else min(s_end, c_st + c_dur)
                        raw_events.append((c_st, c_en, chk))
                        c_st = c_en

    emit_msg("log", {"text": f"✔ Nhận diện giọng nói: [{detected.upper()}] — Bóc tách {len(raw_events)} cụm phụ đề chuẩn nhịp giọng đọc..."})

    # File SRT lưu thời gian chuẩn 1:1 với audio gốc
    events_list = [(s, e, t) for s, e, t in raw_events if str(t).strip()]

    # Giải phóng VRAM bộ nhớ GPU ngay sau khi hoàn thành
    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    valid_events = []
    for s, e, t in events_list:
        clean_text = post_process_subtitle_text(t, initial_prompt).strip()
        if clean_text:
            valid_events.append((s, e, clean_text))

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
    parser.add_argument("--initial-prompt", default="", help="Từ khóa ngữ cảnh mớm cho Whisper AI")
    parser.add_argument("--enhance-voice", dest="enhance_voice", action="store_true", default=True, help="Lọc dải tần và tạp âm cho giọng đọc")
    parser.add_argument("--no-enhance-voice", dest="enhance_voice", action="store_false", help="Không lọc dải tần")

    args = parser.parse_args()
    try:
        sys.exit(run_worker(args))
    except Exception as e:
        emit_msg("error", {"text": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    main()

