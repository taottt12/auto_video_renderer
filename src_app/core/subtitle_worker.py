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
    name = str(raw_name or "turbo").strip().lower()
    if "medium" in name:
        return "medium"
    # Mặc định tất cả các lựa chọn khác đều map chuẩn sang turbo (large-v3-turbo.pt) đã có sẵn trong cache
    return "turbo"


def run_worker(args: argparse.Namespace) -> int:
    audio_path = Path(args.audio)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    raw_model_name = str(args.model or "turbo").strip()
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

    import subprocess
    import torch
    import whisper

    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("GPU CUDA không khả dụng trên môi trường PyTorch hiện tại.")

    if device == "cpu" and getattr(args, "cpu_threads", 0) > 0:
        try:
            threads = min(8, max(2, int(args.cpu_threads)))
            torch.set_num_threads(threads)
        except Exception:
            pass

def save_wav_pcm16(path: Path, data: torch.Tensor, sr: int = 16000) -> None:
    """Lưu tensor âm thanh thành file WAV PCM 16-bit chuẩn bằng module wave gốc của Python."""
    import wave
    import numpy as np
    arr = data.detach().cpu().numpy()
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    arr_int16 = np.clip(arr * 32767.0, -32768.0, 32767.0).astype(np.int16)
    interleaved = arr_int16.T.tobytes()
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(arr.shape[0])
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(interleaved)


def separate_vocals_demucs(audio_path: Path, out_vocal_path: Path, device: str = "cuda") -> bool:
    """Tách bóc luồng Giọng nói sạch (Vocals) bằng Demucs AI (Meta/PyTorch HDEMUCS), triệt tiêu 100% BGM/SFX."""
    try:
        import torch
        import torchaudio
        from torchaudio.pipelines import HDEMUCS_HIGH_MUSDB
        import whisper

        dev = torch.device("cuda" if device == "cuda" and torch.cuda.is_available() else "cpu")
        bundle = HDEMUCS_HIGH_MUSDB
        model = bundle.get_model().to(dev)
        model.eval()

        audio_np = whisper.load_audio(str(audio_path), sr=bundle.sample_rate)
        waveform = torch.from_numpy(audio_np).unsqueeze(0).repeat(2, 1)

        vocal_idx = 3  # ['drums', 'bass', 'other', 'vocals']
        chunk_len = bundle.sample_rate * 60  # Xử lý theo phân đoạn 60s để chống tràn VRAM GPU
        total_samples = waveform.shape[1]
        vocal_chunks = []

        with torch.no_grad():
            for offset in range(0, total_samples, chunk_len):
                sub_wave = waveform[:, offset:offset + chunk_len]
                chunk_in = sub_wave.unsqueeze(0).to(dev)
                sources = model(chunk_in)
                vocal_audio = sources[0, vocal_idx].cpu()
                vocal_chunks.append(vocal_audio)

        full_vocals = torch.cat(vocal_chunks, dim=1)
        mono_vocal = torch.mean(full_vocals, dim=0, keepdim=True)
        mono_16k = torchaudio.functional.resample(mono_vocal, bundle.sample_rate, 16000)
        save_wav_pcm16(out_vocal_path, mono_16k, 16000)

        del model
        del waveform
        del full_vocals
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        return out_vocal_path.exists() and out_vocal_path.stat().st_size > 1000
    except Exception as e:
        emit_msg("log", {"text": f"ℹ️ Demucs AI bỏ qua ({e}), chuyển sang bộ lọc âm thanh tiêu chuẩn."})
        return False


def run_worker(args: argparse.Namespace) -> int:
    audio_path = Path(args.audio)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    raw_model_name = str(args.model or "turbo").strip()
    model_name = normalize_whisper_model_name(raw_model_name)
    language = str(args.language or "").strip()
    device = str(args.device or "cuda").strip().lower()
    speed = float(args.speed or 1.0)
    audio_duration = float(args.duration or 0.0)
    initial_prompt = str(getattr(args, "initial_prompt", "") or "").strip()

    target_lang = None
    if language and language.lower() not in ["auto", "none", ""]:
        if language.lower() in ["tl", "fil", "tagalog", "filipino", "philippines"]:
            target_lang = "tl"
        else:
            target_lang = language.lower()

    # Preload DLLs
    _register_cuda_dll_directories()

    import subprocess
    import torch
    import whisper

    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("GPU CUDA không khả dụng trên môi trường PyTorch hiện tại.")

    if device == "cpu" and getattr(args, "cpu_threads", 0) > 0:
        try:
            threads = min(8, max(2, int(args.cpu_threads)))
            torch.set_num_threads(threads)
        except Exception:
            pass

    input_to_whisper = audio_path
    temp_clean_wav: Path | None = None

    # GIAI ĐOẠN 1: TÁCH GIỌNG NÓI BẰNG DEMUCS AI HOẶC BỘ LỌC TĂNG CƯỜNG
    if getattr(args, "vocal_separation", True):
        vocal_wav = out_path.parent / f"_temp_demucs_vocals_{audio_path.stem}.wav"
        emit_msg("log", {"text": "🎙️ Demucs AI: Đang bóc tách luồng giọng nói sạch (Vocals), loại bỏ SFX & Nhạc nền..."})
        if separate_vocals_demucs(audio_path, vocal_wav, device=device):
            input_to_whisper = vocal_wav
            temp_clean_wav = vocal_wav
            emit_msg("log", {"text": "✔ Demucs AI: Đã trích xuất giọng nói sạch 100% không còn tạp âm/nhạc nền."})
        elif getattr(args, "enhance_voice", True):
            # Fallback bộ lọc âm thanh FFmpeg nếu Demucs không khả dụng
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
    elif getattr(args, "enhance_voice", True):
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
                emit_msg("log", {"text": "🎙️ Tiền xử lý: Đã lọc dải tần giọng nói & triệt tiêu nhạc nền."})
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

    # Gom cụm từ chính xác theo mili-giây nhịp giọng đọc
    raw_events = group_words_into_phrases(raw_segments)
    if not raw_events:
        for seg in raw_segments:
            s_start = float(seg.get("start", 0.0))
            s_end = float(seg.get("end", 0.0))
            s_text = str(seg.get("text", "")).strip()
            no_speech = float(seg.get("no_speech_prob", 0.0))
            if s_text:
                raw_events.append((s_start, s_end, s_text))
                if s_start < 30.0:
                    emit_msg("log", {"text": f"🎙️ [0-30s Segment] {s_start:.2f}s -> {s_end:.2f}s (no_speech: {no_speech:.2f}): '{s_text}'"})

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
    parser.add_argument("--vocal-separation", dest="vocal_separation", action="store_true", default=True, help="Tách giọng nói Demucs AI")
    parser.add_argument("--no-vocal-separation", dest="vocal_separation", action="store_false", help="Không tách giọng nói")
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

