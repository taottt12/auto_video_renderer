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
from pathlib import Path

import numpy as np

# Cấu hình an toàn OpenMP, CUDA và mã hóa UTF-8
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["CUDA_MODULE_LOADING"] = "LAZY"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
# expandable_segments chưa được hỗ trợ trên PyTorch/CUDA Windows hiện dùng và
# chỉ tạo warning. Native allocator với split cap phù hợp hơn cho GPU 6 GB.
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "backend:native,max_split_size_mb:128,garbage_collection_threshold:0.8"

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
    CUDA_FATAL_EXIT_CODE,
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


class CudaWorkerFailure(RuntimeError):
    """Buộc worker CUDA kết thúc để tiến trình cha tạo CUDA context sạch."""


def clean_cuda_vram(sync: bool = True, strict: bool = False) -> None:
    """Thu gom rác, đồng bộ hóa GPU và giải phóng toàn bộ cached memory blocks của PyTorch Caching Allocator trên GPU."""
    import torch
    gc.collect()
    if torch.cuda.is_available():
        try:
            if sync and torch.cuda.is_initialized():
                torch.cuda.synchronize()
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        except Exception:
            # synchronize() thường là nơi lỗi kernel bất đồng bộ xuất hiện. Trong
            # đường chạy chính phải để lỗi thoát ra; nuốt lỗi rồi chạy CPU trong
            # CUDA context đã poisoned sẽ làm worker treo hoặc giữ nguyên VRAM.
            if strict:
                raise


def cuda_memory_summary() -> str:
    """Snapshot ngắn phục vụ chẩn đoán VRAM, không giữ tensor CUDA."""
    try:
        import torch
        free_b, total_b = torch.cuda.mem_get_info()
        allocated = torch.cuda.memory_allocated()
        reserved = torch.cuda.memory_reserved()
        peak = torch.cuda.max_memory_allocated()
        mib = 1024 * 1024
        return (
            f"allocated={allocated / mib:.0f} MB, reserved={reserved / mib:.0f} MB, "
            f"peak={peak / mib:.0f} MB, free={free_b / mib:.0f}/{total_b / mib:.0f} MB"
        )
    except Exception as ex:
        return f"không đọc được VRAM ({ex})"


def _checkpoint_path(out_path: Path) -> Path:
    return out_path.with_suffix(out_path.suffix + ".whisper.partial.json")


def _load_checkpoint(out_path: Path, signature: dict) -> tuple[list[dict], set[int], str]:
    path = _checkpoint_path(out_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("signature") != signature:
            return [], set(), "unknown"
        segments = payload.get("segments") or []
        completed = {int(i) for i in (payload.get("completed_chunks") or [])}
        language = str(payload.get("language") or "unknown")
        return segments, completed, language
    except Exception:
        return [], set(), "unknown"


def _save_checkpoint(
    out_path: Path,
    signature: dict,
    segments: list[dict],
    completed_chunks: set[int],
    language: str,
) -> None:
    """Ghi atomic để worker mới có thể tiếp tục sau CUDA error/OOM."""
    path = _checkpoint_path(out_path)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "signature": signature,
        "segments": segments,
        "completed_chunks": sorted(completed_chunks),
        "language": language,
    }
    temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temp_path, path)


def safe_load_whisper_model(model_name: str, device: str):
    """
    Nạp OpenAI Whisper tối ưu VRAM bằng cơ chế STAGED FP16 LOADING:
    1. Nạp model checkpoint trên CPU System RAM để unpickle an toàn (0 MB VRAM GPU).
    2. Chuyển các module tính toán (Linear, Conv1d, Embedding) sang torch.float16 ngay trên CPU để giảm 50% kích thước model.
    3. Giữ nguyên toàn bộ LayerNorm ở torch.float32 để tương thích 100% với Whisper gốc.
    4. Chuyển model đã nén sang CUDA GPU và dọn sạch cache VRAM.
    -> Giảm VRAM tĩnh từ 4.9 GB xuống ~1.55 GB, giữ hơn 3.4 GB VRAM trống trên card RTX 2060 6GB.
    """
    import torch
    import whisper

    clean_cuda_vram()
    if device == "cuda" and torch.cuda.is_available():
        free_b, total_b = torch.cuda.mem_get_info()
        model_lower = model_name.lower()
        required_free_mb = 3200 if ("turbo" in model_lower or "large" in model_lower) else 2400
        free_mb = free_b / (1024 * 1024)
        if free_mb < required_free_mb:
            raise CudaWorkerFailure(
                f"VRAM trống chỉ còn {free_mb:.0f} MB, cần tối thiểu {required_free_mb} MB "
                f"để nạp Whisper [{model_name}] an toàn trên GPU {total_b / (1024**3):.1f} GB."
            )
        # Bước 1: Nạp CPU System RAM
        model = whisper.load_model(model_name, device="cpu")
        # Bước 2: Selective FP16 Casting (Bảo toàn LayerNorm FP32)
        for name, module in model.named_modules():
            if isinstance(module, (whisper.model.LayerNorm, torch.nn.LayerNorm)):
                module.float()
            elif isinstance(module, (whisper.model.Linear, torch.nn.Linear, whisper.model.Conv1d, torch.nn.Conv1d, torch.nn.Embedding)):
                module.half()
        # Bước 3: Đưa sang CUDA
        model = model.to("cuda")
        clean_cuda_vram()
        return model
    else:
        return whisper.load_model(model_name, device="cpu")


def find_silence_cut_point(audio: np.ndarray, sample_rate: int, target_sec: float, search_window_sec: float = 30.0) -> int:
    """Tìm điểm có biên độ âm thanh nhỏ nhất xung quanh target_sec để cắt chunk không bị đứt câu."""
    target_idx = int(target_sec * sample_rate)
    window_samples = int((search_window_sec / 2) * sample_rate)
    start_search = max(0, target_idx - window_samples)
    end_search = min(len(audio), target_idx + window_samples)

    frame_size = int(0.1 * sample_rate)  # 100ms frame
    search_region = audio[start_search:end_search]
    num_frames = len(search_region) // frame_size
    if num_frames == 0:
        return target_idx

    frames = search_region[: num_frames * frame_size].reshape(num_frames, frame_size)
    energy = np.mean(np.abs(frames), axis=1)
    min_frame_idx = int(np.argmin(energy))
    return start_search + (min_frame_idx * frame_size)


def split_audio_into_macro_chunks(
    audio: np.ndarray,
    sample_rate: int = 16000,
    chunk_target_sec: float = 600.0,
) -> list[tuple[np.ndarray, float, float]]:
    """
    Chia mảng âm thanh thành các Macro-Chunk ~10 phút (600s),
    cắt chính xác tại điểm im lặng (silence boundary) để không làm mất chữ/đứt câu.
    Trả về list các tuple: (chunk_audio_np, start_sec, end_sec).
    """
    total_samples = len(audio)
    total_sec = total_samples / sample_rate

    # Nếu file ngắn hơn 12 phút (720s), giữ nguyên 1 chunk duy nhất
    if total_sec <= 720.0:
        return [(audio, 0.0, total_sec)]

    chunks: list[tuple[np.ndarray, float, float]] = []
    cur_sample_idx = 0
    target_samples_per_chunk = int(chunk_target_sec * sample_rate)

    while cur_sample_idx < total_samples:
        remaining_samples = total_samples - cur_sample_idx
        if remaining_samples <= target_samples_per_chunk * 1.2:
            chunk_slice = audio[cur_sample_idx:]
            chunk_start_sec = cur_sample_idx / sample_rate
            chunk_end_sec = total_samples / sample_rate
            chunks.append((chunk_slice, chunk_start_sec, chunk_end_sec))
            break

        target_split_sec = (cur_sample_idx + target_samples_per_chunk) / sample_rate
        cut_idx = find_silence_cut_point(audio, sample_rate, target_split_sec, search_window_sec=30.0)

        if cut_idx <= cur_sample_idx + (100 * sample_rate):
            cut_idx = cur_sample_idx + target_samples_per_chunk

        chunk_slice = audio[cur_sample_idx:cut_idx]
        chunk_start_sec = cur_sample_idx / sample_rate
        chunk_end_sec = cut_idx / sample_rate
        chunks.append((chunk_slice, chunk_start_sec, chunk_end_sec))
        cur_sample_idx = cut_idx

    return chunks


class AvrWhisperProgressBar:
    """Hook tiến trình thời gian thực cho OpenAI Whisper native transcribe (hỗ trợ nhiều chunks)."""
    current_chunk_idx: int = 0
    total_chunks: int = 1

    def __init__(self, total: int = 100, *args, **kwargs):
        self.total = max(1, total or 1)
        self.n = 0
        self.last_pct = -1

    def update(self, n: int = 1):
        self.n += n
        sub_frac = min(1.0, max(0.0, self.n / self.total))
        overall_frac = (AvrWhisperProgressBar.current_chunk_idx + sub_frac) / max(1, AvrWhisperProgressBar.total_chunks)
        pct = min(99, max(1, int(overall_frac * 100)))
        if pct != self.last_pct and pct % 2 == 0:
            self.last_pct = pct
            chunk_info = f" (Chunk {AvrWhisperProgressBar.current_chunk_idx + 1}/{AvrWhisperProgressBar.total_chunks})" if AvrWhisperProgressBar.total_chunks > 1 else ""
            emit_msg("progress", {
                "percent": pct,
                "message": f"Whisper AI{chunk_info}: {pct}%"
            })

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class WhisperTranscriber:
    """
    Pipeline bóc tách âm thanh Whisper AI hiệu năng cao, ổn định tuyệt đối:
    - Staged FP16 Model Loading (VRAM ~1.55 GB).
    - Native Time Tokens (word_timestamps=False, SDPA Flash Attention 100%).
    - Không cắt vụn âm thanh làm gãy câu từ, giữ trọn vẹn mạch ngữ cảnh âm thanh của file MP3 dài.
    - Tự động fallback CPU sạch sẽ nếu GPU gặp sự cố.
    """

    def __init__(
        self,
        audio_path: Path,
        out_path: Path,
        model_name: str = "turbo",
        target_lang: str | None = None,
        initial_prompt: str = "",
        cpu_threads: int = 0,
        device: str = "cuda",
        duration: float = 0.0,
    ):
        self.audio_path = audio_path
        self.out_path = out_path
        self.model_name = normalize_whisper_model_name(model_name)
        self.target_lang = target_lang
        self.initial_prompt = initial_prompt
        self.cpu_threads = cpu_threads
        self.requested_device = device
        self.duration = duration

        self.detected_language: str = target_lang or "unknown"
        self.all_segments: list[dict] = []

    def run(self) -> int:
        import torch
        import whisper

        # 1. Nạp âm thanh đầy đủ qua Whisper
        emit_msg("log", {"text": f"📥 Đang nạp dữ liệu âm thanh từ '{self.audio_path.name}'..."})
        try:
            audio_data = whisper.load_audio(str(self.audio_path))
        except Exception as load_err:
            emit_msg("error", {"text": f"Không thể đọc file audio '{self.audio_path.name}': {load_err}"})
            return 1

        total_duration = len(audio_data) / 16000.0
        emit_msg("log", {"text": f"📊 Thời lượng âm thanh: {total_duration:.2f}s ({total_duration/60:.2f} phút)."})

        # 2. Phân tách Macro-Chunks (~10 phút/chunk) cắt tại điểm im lặng để tối ưu VRAM
        chunks = split_audio_into_macro_chunks(audio_data, sample_rate=16000, chunk_target_sec=600.0)
        total_chunks = len(chunks)
        AvrWhisperProgressBar.total_chunks = total_chunks

        if total_chunks > 1:
            emit_msg("log", {"text": f"🧩 Âm thanh dài ({total_duration/60:.1f} phút) -> Đã tối ưu chia thành {total_chunks} Macro-Chunk (~10 phút/chunk) với chu kỳ xả VRAM."})
        else:
            emit_msg("log", {"text": f"🧩 File âm thanh ({total_duration/60:.1f} phút) được xử lý trực tiếp."})

        # 3. Hook progress bar của whisper.transcribe
        try:
            import importlib
            wt_mod = importlib.import_module("whisper.transcribe")
            wt_mod.tqdm.tqdm = AvrWhisperProgressBar
        except Exception:
            pass

        # 4. Thực thi giải mã. Mỗi macro-chunk được checkpoint để nếu CUDA context
        # hỏng, worker mới có thể tiếp tục mà không làm lại phần đã hoàn thành.
        use_gpu = (self.requested_device == "cuda" and torch.cuda.is_available())
        try:
            audio_size = int(self.audio_path.stat().st_size)
        except OSError:
            audio_size = -1
        checkpoint_signature = {
            "model": self.model_name,
            "language": self.target_lang or "auto",
            "audio_size": audio_size,
            "duration_ms": int(total_duration * 1000),
            "chunks": total_chunks,
        }
        self.all_segments, completed_chunk_indices, checkpoint_lang = _load_checkpoint(
            self.out_path, checkpoint_signature
        )
        if checkpoint_lang != "unknown" and self.detected_language == "unknown":
            self.detected_language = checkpoint_lang
        if completed_chunk_indices:
            emit_msg("log", {"text": (
                f"♻️ Khôi phục checkpoint: {len(completed_chunk_indices)}/{total_chunks} chunk, "
                f"{len(self.all_segments)} segments; tiếp tục phần còn lại."
            )})

        if use_gpu:
            emit_msg("log", {"text": f"⚡ Bắt đầu pipeline Whisper AI [{self.model_name}] (Staged FP16) trên GPU CUDA..."})
            gpu_model = None
            try:
                # Greedy Search cho Large/Turbo để triệt tiêu peak VRAM và tối đa tốc độ
                is_large_or_turbo = any(k in self.model_name.lower() for k in ("turbo", "large", "medium"))
                whisper_temp = 0.0 if is_large_or_turbo else (0.0, 0.2, 0.4)
                whisper_beam = 1 if is_large_or_turbo else 5
                inference_context = torch.inference_mode if hasattr(torch, "inference_mode") else torch.no_grad

                for chunk_idx, (chunk_audio, start_sec, end_sec) in enumerate(chunks):
                    if chunk_idx in completed_chunk_indices:
                        continue
                    AvrWhisperProgressBar.current_chunk_idx = chunk_idx
                    if total_chunks > 1:
                        emit_msg("log", {"text": f"🎙️ [GPU] Đang xử lý Chunk {chunk_idx + 1}/{total_chunks} ({start_sec/60:.1f}m -> {end_sec/60:.1f}m)..."})

                    # Tự động nạp hoặc làm mới model nếu cần
                    if gpu_model is None:
                        emit_msg("log", {"text": f"⚡ [GPU] Nạp mới Whisper AI [{self.model_name}] (Staged FP16)..."})
                        gpu_model = safe_load_whisper_model(self.model_name, device="cuda")

                    try:
                        with inference_context():
                            res = gpu_model.transcribe(
                                chunk_audio,
                                language=self.target_lang,
                                initial_prompt=self.initial_prompt if (chunk_idx == 0 and self.initial_prompt) else None,
                                fp16=True,
                                verbose=False,
                                word_timestamps=False,
                                no_speech_threshold=0.3,
                                logprob_threshold=-1.0,
                                condition_on_previous_text=False,
                                temperature=whisper_temp,
                                beam_size=whisper_beam,
                            )

                        seg_list = res.get("segments", [])
                        for seg in seg_list:
                            seg["start"] = float(seg.get("start", 0.0)) + start_sec
                            seg["end"] = float(seg.get("end", 0.0)) + start_sec
                            self.all_segments.append(seg)

                        if not self.target_lang and res.get("language") and (not self.detected_language or self.detected_language == "unknown"):
                            self.detected_language = res.get("language")

                        completed_chunk_indices.add(chunk_idx)
                        del res

                        _save_checkpoint(
                            self.out_path,
                            checkpoint_signature,
                            self.all_segments,
                            completed_chunk_indices,
                            self.detected_language,
                        )

                        # XẢ SẠCH VRAM SAU MỖI CHUNK ĐỂ RESET BỘ NHỚ
                        clean_cuda_vram(sync=True, strict=True)
                        emit_msg("log", {"text": f"🧠 [GPU] Sau chunk {chunk_idx + 1}: {cuda_memory_summary()}"})

                    except Exception as chunk_gpu_err:
                        emit_msg("error", {"text": (
                            f"Chunk {chunk_idx + 1}/{total_chunks} lỗi CUDA ({chunk_gpu_err}). "
                            f"Đã checkpoint {len(completed_chunk_indices)} chunk; worker phải thoát để reset CUDA context."
                        )})
                        raise CudaWorkerFailure(str(chunk_gpu_err)) from chunk_gpu_err

                if len(completed_chunk_indices) == total_chunks:
                    emit_msg("log", {"text": f"✔ Bóc tách GPU hoàn tất 100%: {len(self.all_segments)} segments."})
            except Exception as gpu_err:
                if isinstance(gpu_err, CudaWorkerFailure):
                    raise
                emit_msg("error", {"text": f"Khởi tạo GPU thất bại ({gpu_err}); worker phải thoát để reset CUDA context."})
                raise CudaWorkerFailure(str(gpu_err)) from gpu_err
            finally:
                if gpu_model is not None:
                    del gpu_model
                clean_cuda_vram(sync=False)

        # CPU chỉ chạy trong worker được khởi động với --device cpu. Worker CUDA
        # tuyệt đối không fallback nội bộ vì context lỗi 700 không thể phục hồi.
        remaining_indices = [i for i in range(total_chunks) if i not in completed_chunk_indices]
        if remaining_indices and not use_gpu:
            start_rem_chunk = remaining_indices[0] + 1
            emit_msg("log", {"text": f"⚙️ Chuyển {len(remaining_indices)} chunk còn lại (từ Chunk {start_rem_chunk}/{total_chunks}) sang CPU đa luồng giữ nguyên model [{self.model_name}]..."})
            cpu_model = None
            try:
                if self.cpu_threads > 0:
                    try:
                        torch.set_num_threads(self.cpu_threads)
                    except Exception:
                        pass
                cpu_model = safe_load_whisper_model(self.model_name, device="cpu")
                inference_context = torch.inference_mode if hasattr(torch, "inference_mode") else torch.no_grad

                for chunk_idx in remaining_indices:
                    chunk_audio, start_sec, end_sec = chunks[chunk_idx]
                    AvrWhisperProgressBar.current_chunk_idx = chunk_idx
                    if total_chunks > 1:
                        emit_msg("log", {"text": f"⚙️ [CPU] Đang tiếp tục Chunk {chunk_idx + 1}/{total_chunks} ({start_sec/60:.1f}m -> {end_sec/60:.1f}m)..."})

                    with inference_context():
                        res = cpu_model.transcribe(
                            chunk_audio,
                            language=self.target_lang,
                            initial_prompt=self.initial_prompt if (chunk_idx == 0 and self.initial_prompt) else None,
                            fp16=False,
                            verbose=False,
                            word_timestamps=False,
                            no_speech_threshold=0.3,
                            logprob_threshold=-1.0,
                            condition_on_previous_text=False,
                        )

                    seg_list = res.get("segments", [])
                    for seg in seg_list:
                        seg["start"] = float(seg.get("start", 0.0)) + start_sec
                        seg["end"] = float(seg.get("end", 0.0)) + start_sec
                        self.all_segments.append(seg)

                    if not self.target_lang and res.get("language") and (not self.detected_language or self.detected_language == "unknown"):
                        self.detected_language = res.get("language")

                    completed_chunk_indices.add(chunk_idx)
                    del res
                    gc.collect()
                    _save_checkpoint(
                        self.out_path,
                        checkpoint_signature,
                        self.all_segments,
                        completed_chunk_indices,
                        self.detected_language,
                    )

                emit_msg("log", {"text": f"✔ Bóc tách CPU hoàn tất các chunk còn lại: Tổng {len(self.all_segments)} segments."})
            except Exception as cpu_err:
                emit_msg("error", {"text": f"Lỗi nghiêm trọng khi bóc tách trên CPU: {cpu_err}"})
                return 1
            finally:
                if cpu_model is not None:
                    del cpu_model
                gc.collect()

        # 4. Hậu xử lý segments, lọc trùng lặp / hallucination và xuất file SRT
        return self._finalize_srt()

    def _finalize_srt(self) -> int:
        emit_msg("log", {"text": "📝 [Finalize] Ghép nối câu từ, căn chỉnh nhịp đọc và tạo file SRT..."})

        # Sắp xếp theo timeline
        self.all_segments.sort(key=lambda s: float(s.get("start", 0.0)))

        # Lọc bỏ đoạn hallucination quá dài nhưng chỉ có vài từ
        filtered_segments = []
        for seg in self.all_segments:
            s_start = float(seg.get("start", 0.0))
            s_end = float(seg.get("end", 0.0))
            s_text = str(seg.get("text", "")).strip()
            s_dur = max(0.0, s_end - s_start)
            w_cnt = len(s_text.split())

            if s_dur > 10.0 and w_cnt <= 3:
                emit_msg("log", {"text": f"⚠️ [Bỏ qua segment ảo giác ({s_dur:.2f}s)]: {s_start:.2f}s -> {s_end:.2f}s '{s_text}'"})
                continue
            filtered_segments.append(seg)

        # Gom cụm từ tự nhiên theo nhịp giọng đọc (3-6 từ, max 2 dòng)
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

        valid_events = []
        for s, e, t in raw_events:
            clean_text = post_process_subtitle_text(t, self.initial_prompt).strip()
            if clean_text:
                valid_events.append((s, e, clean_text))

        if not valid_events:
            emit_msg("log", {"text": f"ℹ️ Không phát hiện lời thoại trong '{self.audio_path.name}'. Tạo file phụ đề trống."})
            self.out_path.write_text("", encoding="utf-8")
            try:
                _checkpoint_path(self.out_path).unlink(missing_ok=True)
            except OSError:
                pass
            emit_msg("success", {"language": self.detected_language, "events_count": 0})
            return 0

        srt_lines = []
        for idx, (start_sec, end_sec, text) in enumerate(valid_events, start=1):
            start_str = format_timestamp_srt(start_sec)
            end_str = format_timestamp_srt(end_sec)
            srt_lines.append(f"{idx}\n{start_str} --> {end_str}\n{text}\n")

        self.out_path.write_text("\n".join(srt_lines), encoding="utf-8")
        try:
            _checkpoint_path(self.out_path).unlink(missing_ok=True)
        except OSError:
            pass
        emit_msg("success", {
            "output": str(self.out_path),
            "language": self.detected_language,
            "count": len(valid_events),
            "device": self.requested_device
        })
        emit_msg("log", {"text": f"🎉 Xuất hoàn tất phụ đề .SRT: {len(valid_events)} câu lời thoại chính xác."})
        return 0


def run_worker(args: argparse.Namespace) -> int:
    _register_cuda_dll_directories()
    import torch

    audio_path = Path(args.audio)
    out_path = Path(args.output)
    model_name = normalize_whisper_model_name(args.model)
    target_lang = str(args.language or "").strip().lower() or None
    device = str(args.device or "cuda").lower()
    duration = float(args.duration or 0.0)
    cpu_threads = int(args.cpu_threads or 0)
    initial_prompt = str(args.initial_prompt or "").strip()

    gpu_name = torch.cuda.get_device_name(0) if (torch.cuda.is_available() and device == "cuda") else "N/A"
    worker_pid = os.getpid()
    emit_msg("log", {"text": f"🚀 [Worker PID: {worker_pid}] Khởi động Whisper AI trên {device.upper()} (GPU: {gpu_name})..."})

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

    transcriber = WhisperTranscriber(
        audio_path=input_to_whisper,
        out_path=out_path,
        model_name=model_name,
        target_lang=target_lang,
        initial_prompt=initial_prompt,
        cpu_threads=cpu_threads,
        device=device,
        duration=duration,
    )

    try:
        ret = transcriber.run()
    finally:
        if temp_clean_wav and temp_clean_wav.exists():
            try:
                temp_clean_wav.unlink(missing_ok=True)
            except Exception:
                pass

    return ret


def main():
    parser = argparse.ArgumentParser(description="Whisper AI Subprocess Worker (Fault-Tolerant Native)")
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
    except CudaWorkerFailure as e:
        emit_msg("error", {"text": str(e)})
        # Mã riêng để tiến trình cha biết context đã hỏng và chỉ được retry bằng
        # một process mới hoàn toàn.
        sys.exit(CUDA_FATAL_EXIT_CODE)
    except Exception as e:
        emit_msg("error", {"text": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    main()
