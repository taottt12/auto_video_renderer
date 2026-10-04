from __future__ import annotations

import copy
import hashlib
import os
import json
import random
import re
import shlex
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from .media_utils import choose_media_sequence, get_duration_seconds, is_image, is_video
from .overlay_generator import get_overlay_file, ensure_default_overlays
from .paths import TEMP_DIR, OUTPUT_DIR, DATA_DIR, APP_ROOT, ensure_dirs, find_binary
from .process_utils import popen_hidden, run_hidden
from .subtitle_utils import (
    ensure_cuda_whisper_libraries,
    find_subtitle_file,
    preflight_whisper_model,
    srt_to_ass,
    transcribe_audio_to_srt,
)
LogCallback = Callable[[str], None]
ProgressCallback = Callable[[int, str], None]


@dataclass
class RenderResult:
    audio_file: str
    output_file: str
    success: bool
    message: str = ""


class RenderCancelled(RuntimeError):
    pass


class RenderEngine:
    """FFmpeg render pipeline.

    V5.1 fast pipeline:
    1. Đọc audio duration và chọn media vừa đủ duration audio.
    2. Tạo video nền, không render dư phần video quá audio.
    3. Mix audio-only: audio chính + nhạc nền + promo audio, hỗ trợ ducking.
    4. Gắn logo/watermark/text trong một video pass duy nhất.
    5. Ghép video + audio bằng stream copy.
    6. Ghép intro/outro theo fast path copy, không encode lại main video nếu có thể.
    7. Move MP4 cuối và tự dọn temp.
    """

    def __init__(
        self,
        settings: Dict[str, Any],
        log: LogCallback | None = None,
        progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        ensure_dirs()
        self.settings = settings
        raw_log = log or (lambda msg: None)
        raw_progress = progress or (lambda percent, stage: None)
        def _safe_log_cb(msg: str) -> None:
            try:
                raw_log(msg)
            except Exception:
                pass
        def _safe_prog_cb(pct: int, stg: str) -> None:
            try:
                raw_progress(pct, stg)
            except Exception:
                pass
        self.log = _safe_log_cb
        self.progress = _safe_prog_cb
        self.cancel_event = cancel_event or threading.Event()
        self.ffmpeg = self._find_binary_pair("ffmpeg")
        self.ffprobe = self._find_binary_pair("ffprobe")
        self.temp_root = TEMP_DIR

    def _find_binary_pair(self, name: str) -> str:
        try:
            return find_binary(f"{name}.exe")
        except Exception:
            return find_binary(name)

    def render_audio(self, audio_file: str, custom_title: str = "") -> RenderResult:
        job_id = uuid.uuid4().hex[:10]
        job_temp: Path | None = None
        success = False

        try:
            self._raise_if_cancelled()
            audio_path = Path(audio_file)
            if not audio_path.exists():
                raise FileNotFoundError(f"Không tìm thấy audio: {audio_file}")

            # Tiêu đề video hiển thị và đặt tên file: Ưu tiên custom_title nếu có
            title_to_use = str(custom_title).strip() if custom_title and str(custom_title).strip() else audio_path.stem

            export = self.settings.get("export", {})
            width = int(export.get("width", 1080))
            height = int(export.get("height", 1920))
            fps = int(export.get("fps", 30))
            out_folder_str = self.settings.get("project", {}).get("output_folder") or export.get("output_folder") or "output"
            output_folder = Path(out_folder_str)
            if not output_folder.is_absolute():
                output_folder = DATA_DIR / output_folder
            output_folder.mkdir(parents=True, exist_ok=True)

            # V4.3.6: đặt temp ngay bên trong output folder để tránh đầy ổ C/app folder
            # và để file cuối có thể move/replace thay vì copy thêm một bản MP4 rất lớn.
            job_temp = self._make_job_temp(output_folder, job_id)
            self._cleanup_old_temp_dirs(job_temp.parent)

            # Tên file video xuất ra theo tiêu đề đã chọn (loại bỏ ký tự cấm của file hệ thống)
            clean_out_name = re.sub(r'[\\/*?:"<>|]', '_', title_to_use).strip() or audio_path.stem
            output_file = self._dedupe_output(output_folder / f"{clean_out_name}.mp4")

            self.progress(5, "Chuẩn bị audio")
            original_audio_path = audio_path
            audio_path, original_duration = self._prepare_audio_input(audio_path, job_temp)
            audio_speed = self._audio_speed()
            render_duration = max(0.5, original_duration / audio_speed)
            self.log(f"Audio duration gốc: {original_duration:.2f}s")
            self.log(f"Audio speed: {audio_speed:.2f}x → duration render: {render_duration:.2f}s")
            self.log(f"Encoder: {self._encoder_label()} | Parallel jobs: {self._max_parallel_jobs()}")
            self.log(f"Temp drive: {job_temp.parent} | Output: {output_folder}")
            self._preflight_disk_space(output_folder, job_temp.parent, render_duration, width, height, fps)
            if self._encoder() != "cpu":
                self.log(f"GPU strict mode: {'tắt, cho phép fallback CPU' if self._allow_cpu_fallback() else 'bật, KHÔNG tự chuyển sang CPU'}")
                if self._gpu_preflight_check():
                    self._check_gpu_encoder_available()

            image_duration = self._get_image_duration(render_duration)
            video_speed = self._video_speed()
            media_sequence = choose_media_sequence(
                media_files=self.settings.get("media_files", []),
                target_duration=render_duration,
                image_duration=image_duration,
                shuffle=bool(self.settings.get("shuffle_media", True)),
                avoid_repeat=bool(self.settings.get("avoid_repeat", True)),
                video_speed=video_speed,
            )
            self.log(f"Image duration: {image_duration:.2f}s | Video speed: {video_speed:.2f}x")

            # Xử lý phụ đề Subtitle (nếu được bật trong Cài đặt hoặc trong Studio Layout)
            sub_cfg = copy.deepcopy(self.settings.get("subtitle", {}) or {})
            sub_ass_file: Path | None = None

            ls_layers = (self.settings.get("layout_studio", {}) or {}).get("layers", [])
            has_studio_sub = any(isinstance(l, dict) and l.get("type") == "subtitle" and l.get("enabled", True) for l in ls_layers)
            sub_is_enabled = bool(sub_cfg.get("enabled") or has_studio_sub)

            if sub_is_enabled:
                sub_folder = sub_cfg.get("folder", "")
                raw_sub = find_subtitle_file(original_audio_path, sub_folder)

                # Tập hợp từ khóa ngữ cảnh (Initial Prompt) mớm cho Whisper AI & bộ lọc nắn chỉnh phụ đề
                prompt_tokens: List[str] = []
                raw_keywords = str(sub_cfg.get("whisper_keywords", "") or "").strip()
                if raw_keywords:
                    prompt_tokens.extend([k.strip() for k in raw_keywords.split(",") if k.strip()])
                if title_to_use:
                    prompt_tokens.append(title_to_use.strip())
                for l in ls_layers:
                    if isinstance(l, dict) and l.get("type") == "text":
                        t_txt = str(l.get("text_content") or l.get("text") or l.get("content") or "").strip()
                        if t_txt and not t_txt.startswith("{"):
                            prompt_tokens.append(t_txt)
                combined_prompt = ", ".join(dict.fromkeys(prompt_tokens))
                sub_cfg["whisper_keywords"] = combined_prompt

                # NẾU CHƯA CÓ FILE SUB: TỰ ĐỘNG CHẠY WHISPER AI ĐỂ BÓC TÁCH SUB
                if not raw_sub or not raw_sub.exists():
                    self.progress(12, "Whisper AI nhận diện giọng nói & tạo sub")
                    model_size = str(sub_cfg.get("whisper_model", "turbo") or "turbo")
                    whisper_lang = str(sub_cfg.get("whisper_language", "auto") or "auto").strip()
                    lang_param = None if whisper_lang in ["auto", "", "None", "none"] else whisper_lang
                    lang_display = whisper_lang.upper() if lang_param else "TỰ ĐỘNG (AUTO)"
                    whisper_enhance = bool(sub_cfg.get("whisper_enhance_voice", True))
                    whisper_vocal_sep = bool(sub_cfg.get("whisper_vocal_separation", True))

                    self.log(
                        f"⚡ Bật phụ đề: Đang dùng Whisper AI [{model_size}], ngôn ngữ [{lang_display}], "
                        f"Tách Voice AI (Demucs): [{'Bật' if whisper_vocal_sep else 'Tắt'}], "
                        f"Từ khóa Context: [{combined_prompt or 'Không'}] quét audio {original_audio_path.name}..."
                    )
                    auto_srt_path = original_audio_path.with_suffix(".srt")
                    try:
                        raw_sub, detected_lang = transcribe_audio_to_srt(
                            audio_path=original_audio_path,
                            out_srt_path=auto_srt_path,
                            model_size=model_size,
                            language=lang_param,
                            log_callback=self.log,
                            progress_callback=self.progress,
                            speed=audio_speed,
                            cancel_event=self.cancel_event,
                            audio_duration=original_duration,
                            enhance_voice=whisper_enhance,
                            vocal_separation=whisper_vocal_sep,
                            initial_prompt=combined_prompt,
                        )
                    except RenderCancelled:
                        raise
                    except Exception as ex:
                        self.log(f"❌ Lỗi Whisper AI khi tự động tạo phụ đề cho '{original_audio_path.name}': {ex}")
                        raise RuntimeError(f"Lỗi Whisper AI khi tạo phụ đề: {ex}") from ex

                if not raw_sub or not raw_sub.exists():
                    raise RuntimeError(
                        f"Đã bật phụ đề nhưng không tìm thấy file phụ đề (.srt/.ass) và Whisper AI không thể tạo sub cho: '{original_audio_path.name}'."
                    )

                self.log(f"✔ Sử dụng file phụ đề: {raw_sub.name}")
                sub_ass_file = job_temp / "subtitles.ass"
                if raw_sub.suffix.lower() == ".ass":
                    shutil.copy2(raw_sub, sub_ass_file)
                else:
                    # Đồng bộ cấu hình từ Layer Subtitle trong Layout Studio nếu có
                    for l in ls_layers:
                        if isinstance(l, dict) and l.get("type") == "subtitle" and l.get("enabled", True):
                            sub_cfg["box_x"] = float(l.get("box_x", 0.15))
                            sub_cfg["box_y"] = float(l.get("box_y", 0.70))
                            sub_cfg["box_w"] = float(l.get("box_w", 0.70))
                            sub_cfg["box_h"] = float(l.get("box_h", 0.20))
                            sub_cfg["font_family"] = l.get("font_name", sub_cfg.get("font_family", "Arial"))
                            sub_cfg["font_size"] = int(l.get("font_size", sub_cfg.get("font_size", 38)))
                            sub_cfg["font_color"] = l.get("font_color", sub_cfg.get("font_color", "#FFFFFF"))
                            sub_cfg["highlight_color"] = l.get("highlight_color", sub_cfg.get("highlight_color", "#FFE600"))
                            sub_cfg["outline_color"] = l.get("outline_color", sub_cfg.get("outline_color", "#000000"))
                            sub_cfg["outline_width"] = float(l.get("outline_width", sub_cfg.get("outline_width", 2.5)))
                            sub_cfg["bold"] = bool(l.get("bold", True))
                            sub_cfg["italic"] = bool(l.get("italic", False))
                            sub_cfg["align"] = str(l.get("align", sub_cfg.get("align", "center"))).lower()
                            sub_cfg["sub_mode"] = str(l.get("sub_mode", sub_cfg.get("sub_mode", "rolling_2line"))).lower()
                            break
                    sub_cfg["audio_speed"] = audio_speed
                    sub_mode_display = {
                        "rolling_2line": "Cuộn 2 dòng (Rolling 2-Line)",
                        "cinema_hold": "Chuẩn điện ảnh (Cinema Hold)",
                        "karaoke_highlight": "Karaoke Highlight từng từ"
                    }.get(sub_cfg.get("sub_mode", "rolling_2line"), sub_cfg.get("sub_mode", "rolling_2line"))
                    srt_to_ass(raw_sub, sub_ass_file, width, height, sub_cfg)

                if not sub_ass_file.exists() or sub_ass_file.stat().st_size == 0:
                    raise RuntimeError(f"Không thể biên dịch file phụ đề ASS cho: {original_audio_path.name}")

                self.log(f"✔ Đã biên dịch ASS subtitle (Kiểu: {sub_mode_display}, Căn lề: {sub_cfg.get('align', 'center')}) sẵn sàng gắn vào video")

            # LẬP KẾ HOẠCH MEDIA TASKS VÀ KIỂM TRA ĐIỀU KIỆN DIRECT 1-PASS
            media_tasks = self._plan_media_tasks(media_sequence, render_duration, image_duration, width, height, fps)
            batch_limit = self._transition_batch_size()

            if len(media_tasks) <= batch_limit:
                self.progress(45, f"Render Direct 1-Pass ({len(media_tasks)} media -> video cuối)")
                visual_out = job_temp / "visual_video.mp4"
                self._render_direct_single_pass(media_tasks, visual_out, width, height, fps, sub_ass_file=sub_ass_file, audio_title=title_to_use)
                current_video = visual_out
            else:
                self.progress(15, "Tạo clip từ ảnh/video (Fallback danh sách nhiều media)")
                clips, clip_durations = self._create_media_clips(media_sequence, job_temp, width, height, fps, image_duration, render_duration)
                self.progress(50, "Nối clip thành video nền")
                base_video = job_temp / "base_video.mp4"
                self._concat_clips(clips, base_video, clip_durations)
                self._delete_temp_files(clips, "clip tạm sau khi nối")
                current_video = base_video

                if self._has_visual_overlays(sub_ass_file=sub_ass_file):
                    self.progress(72, "Gắn visual overlay 1 lần")
                    visual_out = job_temp / "visual_video.mp4"
                    self._apply_visual_overlays(base_video, visual_out, width, height, sub_ass_file=sub_ass_file, audio_title=title_to_use)
                    current_video = visual_out
                    self._delete_temp_file(base_video, "base_video sau khi gắn visual overlay")
                else:
                    self.log("Không bật logo/watermark/text/sub: bỏ qua pass overlay để tiết kiệm thời gian.")

            self.progress(80, "Chuẩn bị/mix audio")
            final_audio = self._build_final_audio(audio_path, job_temp, render_duration, audio_speed)

            self.progress(86, "Ghép audio cuối")
            with_audio = job_temp / "with_audio.mp4"
            self._attach_audio(current_video, final_audio, with_audio, render_duration, 1.0)
            self._delete_temp_file(current_video, "video tạm sau khi ghép audio")
            self._delete_temp_file(final_audio, "audio tạm sau khi ghép vào video")

            current_video = with_audio
            intro_file = self.settings.get("intro_file") or ""
            outro_file = self.settings.get("outro_file") or ""
            if intro_file or outro_file:
                self.progress(92, "Ghép intro/outro")
                intro_out = job_temp / "with_intro_outro.mp4"
                prev_video = current_video
                self._add_intro_outro(current_video, intro_file, outro_file, intro_out, job_temp, width, height, fps)
                current_video = intro_out
                self._delete_temp_file(prev_video, "video tạm trước intro/outro")

            self.progress(98, "Xuất file cuối")
            self._finalize_output(current_video, output_file)
            success = True
            self.progress(100, "Hoàn thành")
            return RenderResult(audio_file=audio_file, output_file=str(output_file), success=True)

        except RenderCancelled:
            return RenderResult(audio_file=audio_file, output_file="", success=False, message="Đã dừng bởi người dùng")
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.log(f"❌ Render engine error: {exc}")
            return RenderResult(audio_file=audio_file, output_file="", success=False, message=str(exc))
        finally:
            if job_temp is not None:
                self._cleanup_job_temp(job_temp, success=success)

    def _performance(self) -> Dict[str, Any]:
        return self.settings.get("performance", {}) or {}

    def _encoder(self) -> str:
        value = str(self._performance().get("encoder", "cpu")).lower().strip()
        allowed = {"cpu", "nvidia", "intel", "amd"}
        return value if value in allowed else "cpu"

    def _encoder_label(self) -> str:
        labels = {
            "cpu": "CPU / libx264",
            "nvidia": "NVIDIA GPU / h264_nvenc",
            "intel": "Intel GPU / h264_qsv",
            "amd": "AMD GPU / h264_amf",
        }
        return labels.get(self._encoder(), labels["cpu"])

    def _max_parallel_jobs(self) -> int:
        try:
            return max(1, min(10, int(self._performance().get("max_parallel_jobs", 1))))
        except Exception:
            return 1

    def _cpu_threads(self) -> int:
        try:
            return max(0, min(64, int(self._performance().get("cpu_threads", 0))))
        except Exception:
            return 0

    def _allow_cpu_fallback(self) -> bool:
        return bool(self._performance().get("allow_cpu_fallback", False))

    def _gpu_preflight_check(self) -> bool:
        return bool(self._performance().get("gpu_preflight_check", True))

    def _selected_ffmpeg_encoder_name(self) -> str:
        return {"nvidia": "h264_nvenc", "intel": "h264_qsv", "amd": "h264_amf"}.get(self._encoder(), "libx264")

    def _check_gpu_encoder_available(self) -> None:
        """Dừng sớm nếu người dùng chọn GPU nhưng FFmpeg/driver không chạy được encoder đó.

        Trước đây nếu GPU lỗi, tool có thể fallback sang CPU nên Task Manager nhìn như không dùng GPU.
        Bản này mặc định không fallback nữa: GPU lỗi thì báo lỗi rõ để người dùng sửa driver/FFmpeg.
        """
        encoder_name = self._selected_ffmpeg_encoder_name()
        if encoder_name == "libx264":
            return
        encoders = run_hidden([self.ffmpeg, "-hide_banner", "-encoders"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="ignore")
        if encoder_name not in encoders.stdout:
            raise RuntimeError(
                f"FFmpeg hiện tại không có encoder {encoder_name}. Hãy dùng bản FFmpeg full build có NVENC/QSV/AMF hoặc chọn CPU."
            )
        # Không dùng 64x64 để test NVENC. Một số driver/card NVIDIA báo
        # "Frame Dimension less than the minimum supported value" với khung quá nhỏ,
        # dù encoder thật sự vẫn chạy tốt ở 720p/1080p. Test bằng 1280x720 để giống
        # điều kiện render thực tế và tránh báo lỗi giả.
        test_cmd = [
            self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=30:d=0.2",
            "-vf", "format=yuv420p",
            "-c:v", encoder_name, "-f", "null", "-"
        ]
        test = run_hidden(test_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
        if test.returncode != 0:
            detail = (test.stderr or test.stdout or "").strip()
            lower_detail = detail.lower()
            if "frame dimension less than the minimum supported value" in lower_detail:
                raise RuntimeError(
                    "GPU encoder nhận được khung hình test quá nhỏ nên NVENC từ chối encode. "
                    "Đây là lỗi preflight/test, không phải do RTX 2060 không hỗ trợ GPU. "
                    "Bản V4.2.3 đã đổi khung test GPU sang 1280x720 để tránh lỗi này. "
                    f"Chi tiết gốc từ FFmpeg: {detail}"
                )
            if encoder_name == "h264_nvenc" and ("driver does not support the required nvenc api" in lower_detail or "minimum required nvidia driver" in lower_detail):
                raise RuntimeError(
                    "NVIDIA NVENC không chạy được vì driver NVIDIA hiện tại quá cũ so với bản FFmpeg đang dùng. "
                    "Đây không phải lỗi do source video hay setting render. RTX vẫn có thể hỗ trợ NVENC, nhưng FFmpeg của bạn yêu cầu NVENC API mới hơn driver đang có. "
                    "Cách xử lý: cập nhật NVIDIA Driver lên bản 570.0 trở lên, hoặc thay ffmpeg.exe/ffprobe.exe trong tools/ffmpeg/bin bằng một bản FFmpeg cũ hơn tương thích với driver hiện tại. "
                    "Sau khi cập nhật driver hoặc đổi FFmpeg, bấm chạy lại với GPU check bật. "
                    f"Chi tiết gốc từ FFmpeg: {detail}"
                )
            raise RuntimeError(
                f"Đã chọn {self._encoder_label()} nhưng encoder {encoder_name} không chạy được. "
                f"Tool sẽ không tự nhảy sang CPU. Chi tiết: {detail}"
            )
        self.log(f"GPU encoder OK: {encoder_name}")

    def _target_bitrate_bits(self) -> int:
        """Bitrate mục tiêu tối ưu cho video chuẩn nét YouTube 1080p và tùy chỉnh người dùng."""
        export = self.settings.get("export", {}) or {}
        quality = str(export.get("quality", "standard") or "standard").lower()

        if quality == "custom":
            custom_kbps = max(500, min(50000, int(export.get("custom_bitrate_kbps", 6000) or 6000)))
            return custom_kbps * 1000

        base_map = {
            "economy": 2_500_000,
            "low": 2_500_000,
            "draft": 2_500_000,
            "standard": 6_000_000,
            "high": 10_000_000,
            "ultra": 16_000_000,
        }
        base = base_map.get(quality, 6_000_000)
        width = max(1, int(export.get("width", 1080) or 1080))
        height = max(1, int(export.get("height", 1920) or 1920))
        fps = max(1, int(export.get("fps", 30) or 30))
        # Tối ưu hệ số tỉ lệ theo độ phân giải & FPS
        res_scale = max(0.40, (width * height) / (1080 * 1920))
        fps_scale = min(1.30, max(0.70, fps / 30.0))
        return int(base * res_scale * fps_scale)

    @staticmethod
    def _ffmpeg_bitrate(value_bits: int) -> str:
        return f"{max(300, int(round(value_bits / 1000)))}k"

    def _video_encode_args(self) -> List[str]:
        encoder = self._encoder()
        quality = str(self.settings.get("export", {}).get("quality", "standard") or "standard").lower()
        cq_map = {"economy": "28", "low": "28", "draft": "28", "standard": "23", "high": "19", "ultra": "16", "custom": "23"}
        crf_map = {"economy": "28", "low": "28", "draft": "28", "standard": "22", "high": "18", "ultra": "15", "custom": "22"}
        target = self._target_bitrate_bits()
        maxrate = int(target * 1.30)
        bufsize = int(target * 1.60)
        b = self._ffmpeg_bitrate(target)
        mr = self._ffmpeg_bitrate(maxrate)
        bs = self._ffmpeg_bitrate(bufsize)

        fps = max(1, int(self.settings.get("export", {}).get("fps", 30) or 30))
        gop = str(fps * 2)  # GOP 2s tối ưu nén khung hình

        if encoder == "nvidia":
            return [
                "-c:v", "h264_nvenc",
                "-preset", "p2",
                "-tune", "hq",
                "-rc", "vbr",
                "-cq:v", cq_map.get(quality, "23"),
                "-b:v", b,
                "-maxrate", mr,
                "-bufsize", bs,
                "-g", gop,
                "-spatial-aq", "1",
                "-temporal-aq", "1",
                "-delay", "0",
                "-pix_fmt", "yuv420p",
            ]
        if encoder == "intel":
            return [
                "-c:v", "h264_qsv",
                "-preset", "veryfast",
                "-global_quality", cq_map.get(quality, "23"),
                "-b:v", b,
                "-maxrate", mr,
                "-bufsize", bs,
                "-g", gop,
                "-look_ahead", "0",
                "-pix_fmt", "yuv420p",
            ]
        if encoder == "amd":
            return [
                "-c:v", "h264_amf",
                "-quality", "quality",
                "-rc", "vbr_peak",
                "-b:v", b,
                "-maxrate", mr,
                "-g", gop,
                "-pix_fmt", "yuv420p",
            ]

        args = [
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", crf_map.get(quality, "22"),
            "-maxrate", mr,
            "-bufsize", bs,
            "-g", gop,
            "-pix_fmt", "yuv420p",
        ]
        threads = self._cpu_threads()
        if threads > 0:
            args += ["-threads", str(threads)]
        return args

    def _fallback_cpu_encode_args(self) -> List[str]:
        quality = str(self.settings.get("export", {}).get("quality", "standard") or "standard").lower()
        crf_map = {"economy": "28", "low": "28", "draft": "28", "standard": "22", "high": "18", "ultra": "15", "custom": "22"}
        target = self._target_bitrate_bits()
        maxrate = int(target * 1.30)
        bufsize = int(target * 1.60)
        fps = max(1, int(self.settings.get("export", {}).get("fps", 30) or 30))
        gop = str(fps * 2)

        args = [
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", crf_map.get(quality, "27"),
            "-maxrate", self._ffmpeg_bitrate(maxrate),
            "-bufsize", self._ffmpeg_bitrate(bufsize),
            "-g", gop,
            "-pix_fmt", "yuv420p",
        ]
        threads = self._cpu_threads()
        if threads > 0:
            args += ["-threads", str(threads)]
        return args

    def _make_job_temp(self, output_folder: Path, job_id: str) -> Path:
        perf = self._performance()
        custom_temp = str(perf.get("temp_folder", "") or "").strip()
        if custom_temp:
            root_base = Path(custom_temp)
            if not root_base.is_absolute():
                root_base = DATA_DIR / root_base
            root = root_base / "_avr_temp"
        else:
            root = output_folder / "_avr_temp"
        root.mkdir(parents=True, exist_ok=True)
        job_temp = root / job_id
        job_temp.mkdir(parents=True, exist_ok=True)
        return job_temp

    def _cleanup_old_temp_dirs(self, temp_root: Path, max_age_hours: float = 12.0) -> None:
        """Dọn cache cũ do app crash/lỗi để tránh đầy ổ. Không đụng folder mới đang chạy."""
        try:
            now = time.time()
            for child in temp_root.iterdir():
                if not child.is_dir():
                    continue
                age_hours = (now - child.stat().st_mtime) / 3600.0
                if age_hours >= max_age_hours:
                    shutil.rmtree(child, ignore_errors=True)
                    self.log(f"Đã dọn temp cũ: {child}")
        except Exception as exc:
            self.log(f"Không dọn được temp cũ trong {temp_root}: {exc}")

    @staticmethod
    def _format_bytes(num: float) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(max(0.0, num))
        for unit in units:
            if value < 1024.0 or unit == units[-1]:
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024.0
        return f"{value:.1f} TB"

    def _disk_free_bytes(self, folder: Path) -> int:
        folder = folder.resolve()
        probe = folder
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        return int(shutil.disk_usage(probe).free)

    def _estimate_video_bytes(self, duration: float, width: int, height: int, fps: int) -> int:
        return int(max(1.0, duration) * self._target_bitrate_bits() / 8.0)

    def _same_drive_or_mount(self, a: Path, b: Path) -> bool:
        try:
            return os.path.splitdrive(str(a.resolve()))[0].lower() == os.path.splitdrive(str(b.resolve()))[0].lower() and a.resolve().anchor == b.resolve().anchor
        except Exception:
            return False

    def _preflight_disk_space(self, output_folder: Path, temp_root: Path, duration: float, width: int, height: int, fps: int) -> None:
        output_free = self._disk_free_bytes(output_folder)
        temp_free = self._disk_free_bytes(temp_root)
        one_video = self._estimate_video_bytes(duration, width, height, fps)
        transition = str(self.settings.get("transition_mode", "fade") or "none") != "none"
        has_visual = self._has_visual_overlays()
        # V5.0 gộp audio + logo/watermark/text nên peak thấp hơn 4.x.
        # Vẫn chừa dư vì transition/xfade cần thêm file base + file output cùng lúc.
        temp_copies = 1.85 + (0.45 if transition else 0.0) + (0.35 if has_visual else 0.0)
        temp_need_per_job = int(one_video * temp_copies + 900 * 1024**2)
        final_need_per_job = int(one_video * 1.15 + 350 * 1024**2)
        temp_need = temp_need_per_job * self._max_parallel_jobs()
        output_need = final_need_per_job * self._max_parallel_jobs()
        self.log(
            f"Dung lượng trống temp: {self._format_bytes(temp_free)} | output: {self._format_bytes(output_free)} | "
            f"ước lượng cần temp/output cho {self._max_parallel_jobs()} luồng: {self._format_bytes(temp_need)} / {self._format_bytes(output_need)}"
        )
        if self._same_drive_or_mount(output_folder, temp_root):
            total_need = temp_need + output_need
            free = min(output_free, temp_free)
            if free < total_need:
                raise RuntimeError(
                    "Ổ đĩa chứa output/temp không đủ dung lượng để render an toàn. "
                    f"Đang trống {self._format_bytes(free)}, tool ước lượng cần khoảng {self._format_bytes(total_need)} "
                    f"cho {self._max_parallel_jobs()} luồng với video dài {self._format_seconds(duration)}. "
                    "Cách xử lý: chọn Temp folder/Output folder sang ổ còn trống hơn, xóa _avr_temp cũ, giảm số luồng, hoặc hạ Quality/FPS."
                )
        else:
            if temp_free < temp_need:
                raise RuntimeError(
                    f"Ổ temp không đủ dung lượng. Temp đang trống {self._format_bytes(temp_free)}, cần khoảng {self._format_bytes(temp_need)}. "
                    "Hãy chọn Temp folder sang ổ còn trống hơn, giảm số luồng, hoặc hạ Quality/FPS."
                )
            if output_free < output_need:
                raise RuntimeError(
                    f"Ổ output không đủ dung lượng. Output đang trống {self._format_bytes(output_free)}, cần khoảng {self._format_bytes(output_need)}. "
                    "Hãy chọn Output folder sang ổ còn trống hơn, giảm số luồng, hoặc hạ Quality/FPS."
                )

    def _path_is_inside_job_temp(self, path: Path) -> bool:
        try:
            return "_avr_temp" in path.resolve().parts
        except Exception:
            return False

    def _delete_temp_file(self, path: Path, label: str = "file tạm") -> None:
        try:
            if path and path.exists() and self._path_is_inside_job_temp(path):
                path.unlink(missing_ok=True)
                self.log(f"Đã xóa {label}: {path.name}")
        except Exception as exc:
            self.log(f"Không xóa được {label} {path}: {exc}")

    def _delete_temp_files(self, paths: List[Path], label: str = "file tạm") -> None:
        for path in paths:
            self._delete_temp_file(path, label)

    def _cleanup_job_temp(self, job_temp: Path, success: bool) -> None:
        perf = self._performance()
        auto_clear = bool(perf.get("auto_clear_temp", True))
        keep_on_error = bool(perf.get("keep_temp_on_error", False))
        if not auto_clear:
            return
        if not success and keep_on_error:
            self.log(f"Giữ lại cache lỗi để kiểm tra: {job_temp}")
            return
        try:
            shutil.rmtree(job_temp, ignore_errors=True)
        except Exception as exc:
            self.log(f"Không xóa được temp {job_temp}: {exc}")

    def _audio_speed(self) -> float:
        try:
            return min(4.0, max(0.25, float(self.settings.get("audio_speed", 1.0))))
        except Exception:
            return 1.0

    def _video_speed(self) -> float:
        try:
            return min(4.0, max(0.25, float(self.settings.get("video_speed", 1.0))))
        except Exception:
            return 1.0

    def _get_image_duration(self, audio_duration: float) -> float:
        mode = self.settings.get("image_duration_mode", "auto")
        if mode == "auto":
            if audio_duration <= 180:
                return 5.0
            if audio_duration <= 600:
                return 6.0
            return 7.0
        try:
            return max(2.0, float(mode))
        except Exception:
            return 6.0

    def _raise_if_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise RenderCancelled("Đã dừng bởi người dùng")

    def _run(self, cmd: List[str], stage: str, allow_cpu_fallback: bool = False, fallback_builder: Callable[[], List[str]] | None = None) -> None:
        self._raise_if_cancelled()
        self.log(f"{stage}: {self._pretty_cmd(cmd)}")
        try:
            process = popen_hidden(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="ignore")
        except OSError as exc:
            # Windows báo WinError 206 khi command line quá dài. Trường hợp hay gặp nhất
            # là xfade transition với vài trăm clip ảnh/video khiến -filter_complex phình rất lớn.
            # Bản v5.2 đã chia transition theo batch và dùng filter_complex_script, nhưng đoạn này
            # vẫn giữ để báo lỗi dễ hiểu nếu người dùng gặp command khác quá dài.
            winerror = getattr(exc, "winerror", None)
            detail = str(exc)
            if winerror == 206 or "filename or extension is too long" in detail.lower() or "file name too long" in detail.lower():
                raise RuntimeError(
                    f"Lệnh FFmpeg quá dài ở bước: {stage}. "
                    "Tool đã có chế độ chia batch transition tự động; nếu vẫn gặp lỗi này, hãy giảm số clip trong một batch transition, "
                    "rút ngắn đường dẫn Temp folder/Output folder, hoặc tắt transition cho job cực dài."
                ) from exc
            raise
        recent_lines: List[str] = []
        try:
            assert process.stdout is not None
            while True:
                if self.cancel_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise RenderCancelled("Đã dừng bởi người dùng")
                line = process.stdout.readline()
                if line:
                    line = line.strip()
                    if line:
                        recent_lines.append(line)
                        if len(recent_lines) > 25:
                            recent_lines = recent_lines[-25:]
                        self.log(line)
                elif process.poll() is not None:
                    break
                else:
                    time.sleep(0.05)
            code = process.wait()
        finally:
            if process.poll() is None:
                process.kill()

        if code != 0:
            detail = "\n".join(recent_lines[-12:]).strip()
            if allow_cpu_fallback and self._encoder() != "cpu" and fallback_builder is not None and self._allow_cpu_fallback():
                self.log(f"GPU encoder lỗi ở bước '{stage}'. Người dùng cho phép fallback nên tự chuyển sang CPU/libx264 cho bước này.")
                if detail:
                    self.log("Lỗi GPU gần nhất:\n" + detail)
                self._run(fallback_builder(), stage + " (CPU fallback)", allow_cpu_fallback=False)
                return
            if allow_cpu_fallback and self._encoder() != "cpu" and fallback_builder is not None and not self._allow_cpu_fallback():
                self.log(f"GPU encoder lỗi ở bước '{stage}'. Đang bật GPU strict nên KHÔNG fallback sang CPU.")
            lower_detail = detail.lower()
            if "no space left on device" in lower_detail or "error code: -28" in lower_detail:
                hint = self._disk_hint_from_cmd(cmd)
                raise RuntimeError(
                    f"Ổ đĩa bị hết dung lượng khi FFmpeg đang ghi file ở bước: {stage}.\n"
                    f"{hint}\n"
                    "Cách xử lý: dọn ổ đang chứa Output folder/_avr_temp, chọn Output folder sang ổ còn trống hơn, "
                    "giảm số luồng hoặc hạ Quality/FPS. Đây không phải lỗi GPU/NVENC.\n"
                    f"Chi tiết cuối từ FFmpeg:\n{detail}"
                )
            if detail:
                raise RuntimeError(f"FFmpeg lỗi ở bước: {stage}\nChi tiết cuối từ FFmpeg:\n{detail}")
            raise RuntimeError(f"FFmpeg lỗi ở bước: {stage}")

    def _disk_hint_from_cmd(self, cmd: List[str]) -> str:
        try:
            out_path = Path(cmd[-1])
            folder = out_path.parent if out_path.suffix else out_path
            free = self._disk_free_bytes(folder)
            return f"Đường dẫn đang ghi: {folder} | còn trống: {self._format_bytes(free)}"
        except Exception:
            return "Không đọc được dung lượng ổ ghi từ command FFmpeg."

    def _probe_has_audio(self, video: Path) -> bool:
        cmd = [self.ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(video)]
        result = run_hidden(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
        return "audio" in result.stdout.lower()

    @staticmethod
    def _pretty_cmd(cmd: List[str]) -> str:
        return " ".join(shlex.quote(part) for part in cmd)

    @staticmethod
    def _dedupe_output(path: Path) -> Path:
        if not path.exists():
            return path
        index = 1
        while True:
            candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
            if not candidate.exists():
                return candidate
            index += 1

    def _prepare_audio_input(self, audio_path: Path, job_temp: Path) -> tuple[Path, float]:
        """Copy audio sang tên ASCII và thử chuẩn hóa nếu ffprobe không đọc được.

        Nếu vẫn lỗi với thông báo kiểu "Failed to find two consecutive MPEG audio frames"
        thì gần như chắc chắn file .mp3 đó không phải audio hợp lệ, tải chưa xong, hoặc file rỗng.
        """
        if audio_path.stat().st_size < 1024:
            raise RuntimeError(f"File audio quá nhỏ hoặc rỗng ({audio_path.stat().st_size} bytes): {audio_path}")

        safe_audio = job_temp / f"input_audio{audio_path.suffix.lower() or '.mp3'}"
        if audio_path != safe_audio:
            shutil.copy2(audio_path, safe_audio)

        for candidate, label in ((audio_path, "file gốc"), (safe_audio, "bản copy tên an toàn")):
            try:
                return candidate, get_duration_seconds(candidate)
            except Exception as exc:
                self.log(f"ffprobe không đọc được {label}: {exc}")

        # Fallback cuối: thử decode/chuẩn hóa bằng ffmpeg. Nếu file còn frame audio hợp lệ, bước này sẽ cứu được.
        repaired = job_temp / "input_audio_repaired.m4a"
        cmd = [
            self.ffmpeg, "-y", "-hide_banner", "-err_detect", "ignore_err",
            "-analyzeduration", "100M", "-probesize", "100M",
            "-i", str(safe_audio), "-vn", "-ac", "2", "-ar", "48000",
            "-c:a", "aac", "-b:a", "192k", str(repaired),
        ]
        try:
            self._run(cmd, "Thử sửa/chuẩn hóa audio lỗi")
            duration = get_duration_seconds(repaired)
            self.log("Đã cứu được audio bằng cách chuẩn hóa sang m4a tạm.")
            return repaired, duration
        except Exception as exc:
            head = safe_audio.read_bytes()[:64].hex(" ")
            raise RuntimeError(
                "Không đọc được audio này. Đây thường không phải lỗi tên file nữa mà là file MP3 bị hỏng, tải chưa xong, "
                "hoặc file có đuôi .mp3 nhưng dữ liệu bên trong không phải âm thanh hợp lệ. "
                f"Hãy mở thử file bằng VLC/Chrome hoặc tải lại/đổi nguồn. File: {audio_path}. "
                f"64 byte đầu: {head}. Chi tiết sửa audio: {exc}"
            ) from exc

    def _probe_video_metadata(self, path: Path) -> Dict[str, Any]:
        """Đọc metadata chi tiết của video (codec, width, height, fps) bằng ffprobe."""
        try:
            cmd = [
                self.ffprobe,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,width,height,r_frame_rate",
                "-of", "json",
                str(path),
            ]
            res = run_hidden(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
            if res.returncode == 0 and res.stdout:
                data = json.loads(res.stdout)
                streams = data.get("streams", [])
                if streams:
                    st = streams[0]
                    codec = str(st.get("codec_name", "")).lower()
                    w = int(st.get("width", 0) or 0)
                    h = int(st.get("height", 0) or 0)
                    fps_str = str(st.get("r_frame_rate", "30/1"))
                    if "/" in fps_str:
                        num, den = fps_str.split("/", 1)
                        fps = float(num) / max(1.0, float(den))
                    else:
                        fps = float(fps_str or 30.0)
                    return {"codec": codec, "width": w, "height": h, "fps": fps}
        except Exception:
            pass
        return {"codec": "", "width": 0, "height": 0, "fps": 30.0}

    def _normalize_source_video_cache(self, src: Path, target_w: int, target_h: int, target_fps: int) -> Path:
        """Tự động chuẩn hóa video nguồn nặng (AV1 / 60fps / 4K) sang H.264 1080p 30fps đúng 1 lần duy nhất để kích hoạt GPU NVDEC siêu tốc."""
        meta = self._probe_video_metadata(src)
        codec = meta.get("codec", "")
        src_w = meta.get("width", 0)
        src_h = meta.get("height", 0)
        src_fps = meta.get("fps", 30.0)

        needs_norm = False
        reasons = []
        if codec in {"av1", "libaom-av1", "av01"}:
            needs_norm = True
            reasons.append(f"codec {codec} -> H.264")
        if src_fps > (target_fps + 1.0):
            needs_norm = True
            reasons.append(f"fps cao {src_fps:.1f}fps -> {target_fps}fps")
        if src_w > target_w * 1.5 and src_h > target_h * 1.5 and src_w > 0:
            needs_norm = True
            reasons.append(f"độ phân giải {src_w}x{src_h} -> {target_w}x{target_h}")

        if not needs_norm:
            return src

        perf = self._performance()
        custom_temp = str(perf.get("temp_folder", "") or "").strip()
        if custom_temp:
            root_base = Path(custom_temp)
            if not root_base.is_absolute():
                root_base = DATA_DIR / root_base
            cache_dir = root_base / "_avr_temp" / "_avr_media_cache"
        else:
            cache_dir = TEMP_DIR / "_avr_media_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        try:
            stat = src.stat()
            hash_input = f"{src.resolve()}_{stat.st_mtime}_{stat.st_size}_{target_w}_{target_h}_{target_fps}"
            key = hashlib.md5(hash_input.encode("utf-8")).hexdigest()[:12]
        except Exception:
            key = "norm"

        clean_stem = re.sub(r'[^\w\-_\.]', '_', src.stem)[:30]
        cached_file = cache_dir / f"{clean_stem}_{key}.mp4"

        # Nếu file cache đã tồn tại và hợp lệ, tái sử dụng tức thì 0s
        if cached_file.exists() and cached_file.stat().st_size > 10240:
            self.log(f"⚡ Smart Media Cache: Tái sử dụng video nền đã chuẩn hóa H.264 ({cached_file.name})")
            return cached_file

        self.log(f"⚡ Smart Media Cache: Đang chuẩn hóa video nền '{src.name}' ({', '.join(reasons)}) để kích hoạt GPU NVDEC siêu tốc...")
        start_t = time.time()
        temp_out = cache_dir / f"tmp_{uuid.uuid4().hex[:8]}.mp4"

        vf = f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h},setsar=1,fps={target_fps},format=yuv420p"
        is_nv = self._encoder() == "nvidia"
        if is_nv:
            enc_args = ["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ll", "-rc", "vbr", "-cq:v", "26", "-b:v", "3500k", "-maxrate", "5000k", "-bufsize", "7000k"]
        else:
            enc_args = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "22"]

        norm_cmd = [self.ffmpeg, "-y", "-threads", "0", "-i", str(src), "-vf", vf, "-an"] + enc_args + ["-movflags", "+faststart", str(temp_out)]

        try:
            self._run(
                norm_cmd,
                "Chuẩn hóa video nền (Smart Cache)",
                allow_cpu_fallback=True,
                fallback_builder=lambda: [self.ffmpeg, "-y", "-threads", "0", "-i", str(src), "-vf", vf, "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22", "-movflags", "+faststart", str(temp_out)],
            )
            if temp_out.exists() and temp_out.stat().st_size > 10240:
                if cached_file.exists():
                    try:
                        cached_file.unlink()
                    except Exception:
                        pass
                temp_out.replace(cached_file)
                elapsed = time.time() - start_t
                self.log(f"⚡ Smart Media Cache: Chuẩn hóa hoàn tất trong {elapsed:.1f}s -> Các video tiếp theo trong hàng đợi sẽ render với tốc độ GPU NVDEC tối đa!")
                return cached_file
            else:
                if temp_out.exists():
                    temp_out.unlink()
                return src
        except Exception as ex:
            self.log(f"⚠️ Chuẩn hóa video nền gặp lỗi: {ex}, tiếp tục dùng video gốc.")
            if temp_out.exists():
                try:
                    temp_out.unlink()
                except Exception:
                    pass
            return src

    def _plan_media_tasks(self, media_sequence: List[str], target_duration: float, image_duration: float, width: int = 1080, height: int = 1920, fps: int = 30) -> List[Tuple[int, Path, str, float, float]]:
        """Lập kế hoạch media clips (idx, src, media_type, duration, speed) mà không ghi file đĩa."""
        tasks: List[Tuple[int, Path, str, float, float]] = []
        total_seq = len(media_sequence)
        video_speed = self._video_speed()
        transition_mode = str(self.settings.get("transition_mode", "fade") or "none")
        transition_enabled = transition_mode != "none" and total_seq > 1
        transition_duration_cfg = max(0.0, float(self.settings.get("transition_duration", 0.5) or 0.0))
        timeline_duration = 0.0
        target_with_buffer = max(0.5, float(target_duration)) + 0.35

        # Tối ưu siêu tốc: Nếu sequence chỉ dùng 1 file video duy nhất lặp lại,
        # chỉ cần 1 task duy nhất với duration = target_with_buffer, FFmpeg sẽ stream_loop tự động cực nhẹ!
        unique_media = list(dict.fromkeys(media_sequence))
        if len(unique_media) == 1 and is_video(Path(unique_media[0])):
            src = Path(unique_media[0])
            src = self._normalize_source_video_cache(src, width, height, fps)
            tasks.append((1, src, "video", target_with_buffer, video_speed))
            self.log(f"⚡ Single Video Loop Optimizer: Phát hiện 1 video duy nhất ('{src.name}'), kích hoạt stream loop trực tiếp {target_with_buffer:.2f}s.")
            return tasks

        for idx, media in enumerate(media_sequence, start=1):
            if timeline_duration >= target_with_buffer and tasks:
                self.log(f"Đã đủ nền theo audio ({timeline_duration:.2f}s/{target_duration:.2f}s), bỏ qua media dư còn lại.")
                break

            src = Path(media)
            if is_image(src):
                duration = image_duration
                remaining = target_with_buffer - timeline_duration
                if remaining > 0 and remaining < duration:
                    duration = max(0.5, remaining + (transition_duration_cfg if transition_enabled else 0.0))
                tasks.append((idx, src, "image", duration, 1.0))
            elif is_video(src):
                src = self._normalize_source_video_cache(src, width, height, fps)
                original_video_duration = get_duration_seconds(src)
                full_duration = max(0.1, original_video_duration / video_speed)
                remaining = target_with_buffer - timeline_duration
                if remaining > 0 and full_duration > remaining:
                    duration = max(0.5, remaining + (transition_duration_cfg if transition_enabled else 0.0))
                    duration = min(full_duration, duration)
                else:
                    duration = full_duration
                tasks.append((idx, src, "video", duration, video_speed))
            else:
                continue

            if len(tasks) == 1:
                timeline_duration = duration
            else:
                prev_duration = tasks[-2][3]
                overlap = self._transition_duration(min(duration, prev_duration)) if transition_enabled else 0.0
                timeline_duration += max(0.1, duration) - overlap

        if not tasks:
            raise ValueError("Không tạo được task media nào từ danh sách file nền.")
        return tasks

    def _create_media_clips(self, media_sequence: List[str], job_temp: Path, width: int, height: int, fps: int, image_duration: float, target_duration: float) -> Tuple[List[Path], List[float]]:
        plan_tasks = self._plan_media_tasks(media_sequence, target_duration, image_duration, width, height, fps)
        tasks: List[Tuple[int, Path, Path, str, float, float]] = [
            (idx, src, job_temp / f"clip_{idx:05d}.mp4", mtype, dur, spd)
            for idx, src, mtype, dur, spd in plan_tasks
        ]

        total = len(tasks)
        is_gpu = self._encoder() in {"nvidia", "intel", "amd"}
        max_workers = min(3 if is_gpu else max(1, min(2, (os.cpu_count() or 4) // 4)), total)
        self.log(f"Tạo {total} media clips với {max_workers} luồng xử lý song song.")

        completed_count = 0
        lock = threading.Lock()

        def _render_task(task: Tuple[int, Path, Path, str, float, float]) -> None:
            nonlocal completed_count
            self._raise_if_cancelled()
            idx, src, out, media_type, duration, speed = task
            if media_type == "image":
                self._create_image_clip(src, out, width, height, fps, duration, idx)
            else:
                self._create_video_clip(src, out, width, height, fps, duration, idx, speed)
            with lock:
                completed_count += 1
                percent = 15 + int((completed_count / max(1, total)) * 30)
                self.progress(percent, f"Tạo clip {completed_count}/{total}")
                self.log(f"Clip {idx} ({'ảnh' if media_type == 'image' else 'video'}): {duration:.2f}s [xong {completed_count}/{total}]")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_render_task, t) for t in tasks]
            for future in as_completed(futures):
                self._raise_if_cancelled()
                future.result()

        clips = [t[2] for t in tasks]
        clip_durations = [t[4] for t in tasks]
        return clips, clip_durations

    def _create_image_clip(self, src: Path, out: Path, width: int, height: int, fps: int, duration: float, index: int) -> None:
        vf = self._image_effect_filter(width, height, fps, duration, index)
        def build(args: List[str]) -> List[str]:
            return [
                self.ffmpeg, "-y",
                "-framerate", str(fps),
                "-loop", "1",
                "-i", str(src),
                "-t", f"{duration:.6f}",
                "-vf", vf,
                "-an"
            ] + args + ["-movflags", "+faststart", str(out)]
        self._run(build(self._video_encode_args()), "Tạo image clip", True, lambda: build(self._fallback_cpu_encode_args()))

    def _image_effect_filter(self, width: int, height: int, fps: int, duration: float, index: int) -> str:
        effect_mode = str(self.settings.get("effect_mode", "auto_light") or "auto_light")
        motion_enabled = bool(self.settings.get("image_motion_enabled", effect_mode != "none"))
        if not motion_enabled or effect_mode == "none":
            return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps={fps},format=yuv420p"

        frames = max(1, int(duration * fps))
        # Tối ưu tốc độ: scale trực tiếp 1.0x (1080p), tăng tốc ~40% CPU
        base_scale = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"

        # Chu kỳ lặp chuyển động dao động mượt mà cho ảnh thời lượng dài:
        # Nới rộng thời gian chu kỳ chuyển động từ 7s lên 25s - 30s để chuyển động siêu êm, không bị nhanh
        cycle = max(180, int(min(30.0, max(18.0, duration)) * fps))

        patterns = {
            # Zoom in nhẹ nhàng, mượt mà suốt thời lượng clip
            "zoom_in": f"zoompan=z='1.0+0.05*(0.5-0.5*cos(PI*on/{frames}))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps}",
            "zoom_in_center": f"zoompan=z='1.0+0.06*(0.5-0.5*cos(PI*on/{frames}))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps}",
            # Zoom out nhẹ nhàng
            "zoom_out": f"zoompan=z='1.05-0.05*(0.5-0.5*cos(PI*on/{frames}))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps}",
            "zoom_out_center": f"zoompan=z='1.06-0.06*(0.5-0.5*cos(PI*on/{frames}))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps}",
            # Zoom vào các góc điện ảnh
            "zoom_in_top_left": f"zoompan=z='1.0+0.05*(0.5-0.5*cos(PI*on/{frames}))':x='0':y='0':d={frames}:s={width}x{height}:fps={fps}",
            "zoom_in_top_right": f"zoompan=z='1.0+0.05*(0.5-0.5*cos(PI*on/{frames}))':x='iw-iw/zoom':y='0':d={frames}:s={width}x{height}:fps={fps}",
            "zoom_in_bottom_left": f"zoompan=z='1.0+0.05*(0.5-0.5*cos(PI*on/{frames}))':x='0':y='ih-ih/zoom':d={frames}:s={width}x{height}:fps={fps}",
            "zoom_in_bottom_right": f"zoompan=z='1.0+0.05*(0.5-0.5*cos(PI*on/{frames}))':x='iw-iw/zoom':y='ih-ih/zoom':d={frames}:s={width}x{height}:fps={fps}",
            # Pan ngang / dọc trôi êm ái
            "pan_left": f"zoompan=z='1.04':x='(iw-iw/zoom)*(1-on/{frames})':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps}",
            "pan_right": f"zoompan=z='1.04':x='(iw-iw/zoom)*(on/{frames})':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps}",
            "pan_up": f"zoompan=z='1.04':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*(1-on/{frames})':d={frames}:s={width}x{height}:fps={fps}",
            "pan_down": f"zoompan=z='1.04':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*(on/{frames})':d={frames}:s={width}x{height}:fps={fps}",
            # Chuyển động nhịp thở & lặp hình sin tuần hoàn chậm rãi (chu kỳ 25-30s)
            "smooth_pulse": f"zoompan=z='1.02+0.03*sin(2*PI*on/{cycle})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps}",
            "loop_zoom": f"zoompan=z='1.03+0.025*sin(2*PI*on/{cycle})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps}",
            "loop_pan_zoom": f"zoompan=z='1.03+0.02*sin(2*PI*on/{cycle})':x='(iw-iw/zoom)*(0.5+0.45*cos(2*PI*on/{cycle}))':y='(ih-ih/zoom)*(0.5+0.45*sin(2*PI*on/{cycle}))':d={frames}:s={width}x{height}:fps={fps}",
        }
        # Auto mode: tự đổi hiệu ứng theo từng ảnh
        if effect_mode in {"auto_smart", "auto_rich", "random_rich", "auto", "random"}:
            keys = [
                "zoom_in_center", "pan_right", "zoom_out_center", "pan_left",
                "zoom_in_top_left", "loop_pan_zoom", "pan_up", "smooth_pulse",
                "zoom_in_top_right", "pan_down"
            ]
            selected = patterns[keys[(index - 1) % len(keys)]]
        elif effect_mode in {"auto_light", "random_light"}:
            keys = ["zoom_in", "zoom_out", "pan_left", "pan_right"]
            selected = patterns[keys[(index - 1) % len(keys)]]
        elif effect_mode in patterns:
            selected = patterns[effect_mode]
        else:
            selected = patterns["zoom_in"] if index % 2 else patterns["zoom_out"]
        return f"{base_scale},{selected},setsar=1,format=yuv420p"

    def _video_effect_filter(self, width: int, height: int, fps: int, duration: float, index: int) -> str:
        effect_mode = str(self.settings.get("video_effect_mode", "none") or "none")
        if effect_mode in {"none", "off", "auto_cinematic", "auto", "random"}:
            return ""  # Giữ 100% màu gốc của ảnh, không đổi màu

        filters = {
            "vignette": "vignette=PI/6",
            "color_boost": "eq=contrast=1.04:saturation=1.05",
            "film_grain": "noise=c1s=5:c0f=u:allf=t",
            "slow_zoom": f"crop=w='iw*min(1,1-0.0001*n)':h='ih*min(1,1-0.0001*n)':x='(iw-ow)/2':y='(ih-oh)/2',scale={width}:{height}",
        }
        return filters.get(effect_mode, "")

    def _create_video_clip(self, src: Path, out: Path, width: int, height: int, fps: int, duration: float, index: int, speed: float) -> None:
        base_vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps={fps}"
        if abs(speed - 1.0) > 0.001:
            vf = f"setpts=PTS/{speed:.6f},{base_vf}"
        else:
            vf = base_vf

        fx_enabled = bool(self.settings.get("video_effect_enabled", False))
        extra_fx = self._video_effect_filter(width, height, fps, duration, index) if fx_enabled else ""
        if extra_fx:
            vf = f"{vf},{extra_fx},format=yuv420p"
        else:
            vf = f"{vf},format=yuv420p"

        def build(args: List[str]) -> List[str]:
            # Không stream_loop ở đây: video dùng full thời lượng gốc của chính nó,
            # không bị cắt/lặp theo setting "Thời lượng mỗi ảnh".
            return [self.ffmpeg, "-y", "-i", str(src), "-t", f"{duration:.6f}", "-vf", vf, "-an"] + args + [str(out)]
        self._run(build(self._video_encode_args()), "Tạo video clip", True, lambda: build(self._fallback_cpu_encode_args()))

    def _concat_clips(self, clips: List[Path], out: Path, clip_durations: List[float]) -> None:
        transition_mode = str(self.settings.get("transition_mode", "fade") or "none")
        if transition_mode == "none" or len(clips) <= 1:
            self._concat_clips_copy(clips, out)
            return

        transition_duration = self._transition_duration(min(clip_durations) if clip_durations else 0.0)
        if transition_duration <= 0:
            self._concat_clips_copy(clips, out)
            return

        batch_size = self._transition_batch_size()
        if len(clips) > batch_size:
            self._concat_clips_transition_chunked(clips, out, clip_durations, transition_mode, transition_duration, batch_size)
            return

        self._concat_clips_xfade_batch(clips, out, clip_durations, transition_mode, transition_duration, batch_index=1, total_batches=1)

    def _transition_batch_size(self) -> int:
        """Giới hạn số input cho mỗi lệnh xfade.

        Windows có giới hạn command line. Với video 1 giờ và ảnh 6-7 giây, tool có thể sinh
        vài trăm clip. Nếu nhét toàn bộ vào một filter_complex duy nhất sẽ gây WinError 206 và
        cũng rất nặng. Chia batch giúp command ngắn, dễ dọn temp, và lỗi ở batch nào cũng rõ hơn.
        """
        perf = self._performance()
        raw = perf.get("transition_batch_size", perf.get("max_transition_inputs", 36))
        try:
            value = int(raw)
        except Exception:
            value = 36
        return max(8, min(80, value))

    def _concat_clips_transition_chunked(
        self,
        clips: List[Path],
        out: Path,
        clip_durations: List[float],
        transition_mode: str,
        transition_duration: float,
        batch_size: int,
    ) -> None:
        total_batches = (len(clips) + batch_size - 1) // batch_size
        self.log(
            f"Transition có {len(clips)} clip nên tự chia {total_batches} batch, "
            f"mỗi batch tối đa {batch_size} clip. Cách này tránh WinError 206 và nhẹ hơn cho job dài."
        )
        chunks: List[Path] = []
        for batch_index, start_index in enumerate(range(0, len(clips), batch_size), start=1):
            group = clips[start_index:start_index + batch_size]
            group_durations = clip_durations[start_index:start_index + batch_size]
            chunk_out = out.parent / f"{out.stem}_transition_chunk_{batch_index:04d}.mp4"
            self.progress(50, f"Nối transition batch {batch_index}/{total_batches}")
            if len(group) == 1:
                # Chuẩn codec giống các chunk khác, nhưng chỉ copy để nhẹ.
                self._concat_clips_copy(group, chunk_out)
            else:
                self._concat_clips_xfade_batch(
                    group,
                    chunk_out,
                    group_durations,
                    transition_mode,
                    transition_duration,
                    batch_index=batch_index,
                    total_batches=total_batches,
                )
            chunks.append(chunk_out)
            # Khi chunk đã tạo xong, xóa luôn clip nguồn của batch đó để giảm peak dung lượng.
            self._delete_temp_files(group, f"clip tạm của transition batch {batch_index}")

        self.progress(56, "Nối các batch transition")
        self._concat_clips_copy(chunks, out)
        self._delete_temp_files(chunks, "chunk transition tạm")

    def _concat_clips_xfade_batch(
        self,
        clips: List[Path],
        out: Path,
        clip_durations: List[float],
        transition_mode: str,
        transition_duration: float,
        batch_index: int,
        total_batches: int,
    ) -> None:
        # Dùng filter_complex_script thay vì nhét filter dài trực tiếp vào command line.
        # Đây là fix chính cho lỗi Windows: [WinError 206] The filename or extension is too long.
        selected_transitions = self._transition_sequence(transition_mode, max(1, len(clips) - 1))
        filters: List[str] = []
        prev = "[0:v]"
        timeline_duration = max(0.1, clip_durations[0])
        for idx in range(1, len(clips)):
            trans = selected_transitions[idx - 1]
            offset = max(0.05, timeline_duration - transition_duration)
            out_label = f"[v{idx}]" if idx < len(clips) - 1 else "[v]"
            filters.append(
                f"{prev}[{idx}:v]xfade=transition={trans}:duration={transition_duration:.2f}:offset={offset:.2f}{out_label}"
            )
            timeline_duration = timeline_duration + max(0.1, clip_durations[idx]) - transition_duration
            prev = out_label

        script_file = out.parent / f"{out.stem}_xfade_filter_{batch_index:04d}.txt"
        script_file.write_text(";".join(filters), encoding="utf-8")

        def build(args: List[str]) -> List[str]:
            cmd = [self.ffmpeg, "-y"]
            for clip in clips:
                cmd += ["-i", str(clip)]
            return cmd + ["-filter_complex_script", str(script_file), "-map", "[v]"] + args + [str(out)]

        stage = "Concat clips với transition"
        if total_batches > 1:
            stage += f" batch {batch_index}/{total_batches}"
        self._run(build(self._video_encode_args()), stage, True, lambda: build(self._fallback_cpu_encode_args()))

    def _concat_clips_copy(self, clips: List[Path], out: Path) -> None:
        list_file = out.parent / "concat.txt"
        list_file.write_text("\n".join(f"file '{clip.as_posix()}'" for clip in clips), encoding="utf-8")
        cmd = [self.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out)]
        self._run(cmd, "Concat clips")

    def _transition_duration(self, min_clip_duration: float) -> float:
        try:
            value = float(self.settings.get("transition_duration", 0.5))
        except Exception:
            value = 0.5
        return max(0.0, min(value, max(0.0, min_clip_duration / 2 - 0.05)))

    @staticmethod
    def _transition_sequence(mode: str, count: int) -> List[str]:
        soft = ["fade", "fadeblack", "fadewhite", "dissolve", "slideleft", "slideright"]
        dynamic = [
            "fade", "fadeblack", "fadewhite", "dissolve",
            "slideleft", "slideright", "slideup", "slidedown",
            "wipeleft", "wiperight", "wipeup", "wipedown",
            "circleopen", "circleclose", "zoomin", "pixelize", "radial"
        ]

        def auto_no_repeat(pool: List[str]) -> List[str]:
            if count <= 0:
                return []
            seq: List[str] = []
            last = ""
            for _ in range(count):
                choices = [item for item in pool if item != last] or pool
                picked = random.choice(choices)
                seq.append(picked)
                last = picked
            return seq

        if mode in {"auto_soft", "auto_light", "random_basic", "auto", "random"}:
            return auto_no_repeat(soft)
        if mode in {"auto_dynamic", "auto_rich", "random_rich"}:
            return auto_no_repeat(dynamic)
        if mode in dynamic or mode in soft:
            return [mode] * count
        return auto_no_repeat(soft)

    def _get_background_music_file(self) -> str:
        bgm_cfg = self.settings.get("background_music", {}) or {}
        files = [str(f).strip() for f in (bgm_cfg.get("files") or []) if str(f).strip()]
        legacy_file = str(bgm_cfg.get("file", "")).strip()
        if legacy_file and legacy_file not in files:
            files.append(legacy_file)
        selected = str(bgm_cfg.get("selected_file", "")).strip()
        if selected:
            return selected
        if not files:
            return ""
        if bool(bgm_cfg.get("shuffle", True)):
            return random.choice(files)
        return files[0]

    def _build_final_audio(self, audio: Path, job_temp: Path, duration: float, speed: float) -> Path:
        """Tạo audio cuối ở dạng m4a trước khi ghép vào video.

        V4.3.6 tối ưu lớn: background music và promo audio được mix ở audio-only.
        Nhờ vậy không còn tạo thêm nhiều bản MP4 khổng lồ chỉ để thay đổi âm thanh.
        """
        current = job_temp / "main_audio.m4a"
        afilters = ["aresample=48000", "aformat=channel_layouts=stereo"]
        if abs(speed - 1.0) > 0.001:
            afilters.append(self._atempo_filter(speed))
        cmd = [
            self.ffmpeg, "-y", "-i", str(audio), "-vn",
            "-af", ",".join(afilters),
            "-t", f"{duration:.6f}",
            "-c:a", "aac", "-b:a", "192k", str(current),
        ]
        self._run(cmd, "Chuẩn hóa audio chính")

        bgm_cfg = self.settings.get("background_music", {}) or {}
        bgm_file = self._get_background_music_file()
        if bgm_cfg.get("enabled") and bgm_file:
            bgm_out = job_temp / "audio_with_background.m4a"
            self.log(f"Nhạc nền: {bgm_file}")
            self._mix_background_music_audio(current, Path(bgm_file), bgm_out, duration)
            self._delete_temp_file(current, "audio chính tạm trước nhạc nền")
            current = bgm_out
        elif bgm_cfg.get("enabled"):
            self.log("Đã bật nhạc nền nhưng chưa có file nhạc nền hợp lệ.")

        promo_cfg = self.settings.get("promo_audio", {}) or {}
        if promo_cfg.get("enabled"):
            positions = self._parse_promo_positions(str(promo_cfg.get("positions_text", "")), duration)
            promo_files = self._select_promo_files_for_positions(positions)
            if positions and promo_files:
                promo_out = job_temp / "audio_with_promo.m4a"
                self.log(f"Chèn {len(promo_files)} audio quảng bá tại: {', '.join(self._format_seconds(p) for p in positions)}")
                self._mix_promo_audio_audio(current, promo_files, positions, promo_out, duration)
                self._delete_temp_file(current, "audio tạm trước promo")
                current = promo_out
            else:
                self.log("Đã bật audio quảng bá nhưng chưa có file hoặc chưa có vị trí chèn hợp lệ.")

        # Lọc tạp âm / triệt tiêu nhạc nền sau 30s đầu (30s đầu giữ nguyên cho Voice Intro / Nhạc mở màn)
        if self.settings.get("filter_bgm_after_30s", False) and duration > 30.0:
            self.log("🎙️ Lọc tạp âm/nhạc nền sau 30s: Giữ nguyên 30s đầu (Voice/BGM Intro), lọc dải tần giọng nói từ giây thứ 30 trở đi.")
            filter_audio_out = job_temp / "audio_filtered_30s.m4a"
            af_filter_complex = (
                "[0:a]asplit=2[a_full][a_to_filter];"
                "[a_to_filter]highpass=f=120,lowpass=f=3800,afftdn=nf=-25,dynaudnorm=f=150:g=15[a_clean];"
                "[a_full]atrim=0:30,asetpts=PTS-STARTPTS[a_intro];"
                "[a_clean]atrim=30,asetpts=PTS-STARTPTS[a_body];"
                "[a_intro][a_body]concat=n=2:v=0:a=1,aresample=48000,aformat=channel_layouts=stereo[a]"
            )
            filter_cmd = [
                self.ffmpeg, "-y", "-i", str(current),
                "-filter_complex", af_filter_complex,
                "-map", "[a]", "-t", f"{duration:.6f}",
                "-c:a", "aac", "-b:a", "192k", str(filter_audio_out),
            ]
            try:
                self._run(filter_cmd, "Lọc nhạc nền sau 30s đầu")
                self._delete_temp_file(current, "audio trước khi lọc nhạc sau 30s")
                current = filter_audio_out
            except Exception as ex:
                self.log(f"⚠️ Bộ lọc nhạc sau 30s gặp cảnh báo: {ex}, tiếp tục dùng audio hiện tại.")

        return current

    def _mix_background_music_audio(self, main_audio: Path, music: Path, out: Path, duration: float) -> None:
        if not music.exists():
            self.log(f"Bỏ qua nhạc nền vì không tìm thấy file: {music}")
            shutil.copy2(main_audio, out)
            return
        bgm_cfg = self.settings.get("background_music", {}) or {}
        volume = min(1.0, max(0.0, float(bgm_cfg.get("volume", 0.18))))
        loop = bool(bgm_cfg.get("loop", True))
        cmd = [self.ffmpeg, "-y", "-i", str(main_audio)]
        if loop:
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", str(music)]
        filter_complex = (
            "[0:a]aresample=48000,aformat=channel_layouts=stereo,volume=1.0[main];"
            f"[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={volume}[bgm];"
            "[main][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            "alimiter=limit=0.95,aresample=48000,aformat=channel_layouts=stereo[a]"
        )
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "[a]", "-t", f"{duration:.6f}",
            "-c:a", "aac", "-b:a", "192k", str(out),
        ]
        self._run(cmd, "Mix background music audio-only")

    def _mix_promo_audio_audio(self, main_audio: Path, promo_files: List[Path], positions: List[float], out: Path, duration: float) -> None:
        promo_cfg = self.settings.get("promo_audio", {}) or {}
        volume = min(3.0, max(0.0, float(promo_cfg.get("volume", 1.0))))
        duck_enabled = bool(promo_cfg.get("duck_enabled", True))
        duck_volume = min(1.0, max(0.0, float(promo_cfg.get("duck_volume", 0.35))))
        duck_pad_start = max(0.0, float(promo_cfg.get("duck_pad_start_ms", 100)) / 1000.0)
        duck_pad_end = max(0.0, float(promo_cfg.get("duck_pad_end_ms", 300)) / 1000.0)
        pairs = [(p, pos) for p, pos in zip(promo_files, positions) if p.exists()]
        if not pairs:
            shutil.copy2(main_audio, out)
            return

        promo_durations: List[float] = []
        for promo, _pos in pairs:
            try:
                promo_durations.append(max(0.05, get_duration_seconds(promo)))
            except Exception as exc:
                self.log(f"Không đọc được duration promo {promo.name}, dùng 10s tạm. Chi tiết: {exc}")
                promo_durations.append(10.0)

        cmd = [self.ffmpeg, "-y", "-i", str(main_audio)]
        for promo, _ in pairs:
            cmd += ["-i", str(promo)]

        filters: List[str] = []
        main_filter = "[0:a]aresample=48000,aformat=channel_layouts=stereo"
        if duck_enabled and duck_volume < 0.999:
            duck_expr = self._promo_duck_volume_expr(pairs, promo_durations, duck_volume, duck_pad_start, duck_pad_end, duration)
            main_filter += f",volume='{duck_expr}':eval=frame"
            self.log(f"Ducking promo: bật | audio chính còn {duck_volume:.2f}x khi promo phát")
        else:
            main_filter += ",volume=1.0"
            self.log("Ducking promo: tắt")
        filters.append(main_filter + "[main]")

        mix_inputs = ["[main]"]
        for idx, (_promo, pos) in enumerate(pairs, start=1):
            delay_ms = max(0, int(round(pos * 1000)))
            label = f"p{idx}"
            # adelay với 2 channel stereo; audio quảng bá được chồng lên audio chính tại đúng mốc.
            filters.append(
                f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,volume={volume},"
                f"adelay={delay_ms}|{delay_ms}[{label}]"
            )
            mix_inputs.append(f"[{label}]")
        filters.append(
            "".join(mix_inputs)
            + f"amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0:normalize=0,"
            + "alimiter=limit=0.95,aresample=48000,aformat=channel_layouts=stereo[a]"
        )
        cmd += [
            "-filter_complex", ";".join(filters),
            "-map", "[a]", "-t", f"{duration:.6f}",
            "-c:a", "aac", "-b:a", "192k", str(out),
        ]
        self._run(cmd, "Mix promo audio-only + ducking")

    def _promo_duck_volume_expr(self, pairs: List[tuple[Path, float]], promo_durations: List[float], duck_volume: float, pad_start: float, pad_end: float, total_duration: float) -> str:
        conditions: List[str] = []
        for (_promo, pos), promo_duration in zip(pairs, promo_durations):
            start = max(0.0, float(pos) - pad_start)
            end = min(max(0.1, total_duration), float(pos) + max(0.05, promo_duration) + pad_end)
            if end > start:
                conditions.append(f"between(t,{start:.3f},{end:.3f})")
        if not conditions:
            return "1.0"
        condition = "+".join(conditions)
        # Khi bất kỳ promo nào đang phát, audio chính giảm xuống duck_volume.
        return f"if(gt({condition},0),{duck_volume:.4f},1.0)"

    def _attach_audio(self, video: Path, audio: Path, out: Path, duration: float, speed: float) -> None:
        # Audio đã được chuẩn hóa/mix sẵn ở _build_final_audio, nên bước này chỉ remux:
        # copy video + copy AAC audio. Rất nhẹ và ít tốn ổ hơn encode lại.
        cmd = [
            self.ffmpeg, "-y", "-i", str(video), "-i", str(audio),
            "-t", f"{duration:.6f}",
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "copy",
            "-shortest", "-movflags", "+faststart", str(out),
        ]
        self._run(cmd, "Attach audio")

    def _atempo_filter(self, speed: float) -> str:
        parts: List[float] = []
        remaining = speed
        while remaining > 2.0:
            parts.append(2.0)
            remaining /= 2.0
        while remaining < 0.5:
            parts.append(0.5)
            remaining /= 0.5
        parts.append(remaining)
        return ",".join(f"atempo={p:.4f}" for p in parts)

    def _mix_background_music(self, video: Path, music: Path, out: Path) -> None:
        if not music.exists():
            self.log(f"Bỏ qua nhạc nền vì không tìm thấy file: {music}")
            shutil.copy2(video, out)
            return
        bgm_cfg = self.settings.get("background_music", {}) or {}
        volume = min(1.0, max(0.0, float(bgm_cfg.get("volume", 0.18))))
        loop = bool(bgm_cfg.get("loop", True))
        cmd = [self.ffmpeg, "-y", "-i", str(video)]
        if loop:
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", str(music)]
        # Audio-only step: chỉ trộn âm thanh và COPY video, không encode lại video toàn bộ.
        # Đây là tối ưu lớn giúp chạy nhiều luồng nhẹ hơn rất nhiều so với v4.3.4.
        filter_complex = (
            f"[0:a]aresample=48000,volume=1.0[main];"
            f"[1:a]volume={volume},aresample=48000[bgm];"
            f"[main][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            f"alimiter=limit=0.95,aresample=48000[a]"
        )
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", str(out),
        ]
        self._run(cmd, "Mix background music")


    @staticmethod
    def _format_seconds(seconds: float) -> str:
        seconds_i = max(0, int(round(seconds)))
        h = seconds_i // 3600
        m = (seconds_i % 3600) // 60
        sec = seconds_i % 60
        if h:
            return f"{h:02d}:{m:02d}:{sec:02d}"
        return f"{m:02d}:{sec:02d}"

    @staticmethod
    def _parse_time_to_seconds(value: str) -> float | None:
        value = value.strip()
        if not value:
            return None
        try:
            if ":" not in value:
                seconds = float(value)
                return seconds if seconds >= 0 else None
            parts = [p.strip() for p in value.split(":")]
            if len(parts) == 2:
                minutes = int(parts[0])
                seconds = float(parts[1])
                return minutes * 60 + seconds
            if len(parts) == 3:
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = float(parts[2])
                return hours * 3600 + minutes * 60 + seconds
        except Exception:
            return None
        return None

    def _parse_promo_positions(self, text: str, duration: float) -> List[float]:
        """Parse promo insert positions from UI text.

        Accepted formats:
        - 60
        - 01:00
        - 05:30
        - 00:10:00
        Values can be separated by comma, semicolon, spaces, or new lines.
        """
        raw_tokens = []
        for chunk in text.replace(";", ",").replace("\n", ",").split(","):
            token = chunk.strip()
            if token:
                raw_tokens.extend([x.strip() for x in token.split() if x.strip()])

        positions: List[float] = []
        seen = set()
        for token in raw_tokens:
            seconds = self._parse_time_to_seconds(token)
            if seconds is None:
                self.log(f"Bỏ qua mốc audio quảng bá không hợp lệ: {token}")
                continue
            # Không chèn ở cuối hoặc vượt quá video vì FFmpeg sẽ tạo input vô nghĩa.
            if seconds < 0 or seconds >= max(0.0, duration - 0.1):
                self.log(f"Bỏ qua mốc audio quảng bá ngoài thời lượng video: {token}")
                continue
            key = round(seconds, 3)
            if key not in seen:
                seen.add(key)
                positions.append(seconds)
        return positions

    def _select_promo_files_for_positions(self, positions: List[float]) -> List[Path]:
        promo_cfg = self.settings.get("promo_audio", {}) or {}
        files = [str(f).strip() for f in (promo_cfg.get("files") or []) if str(f).strip()]
        legacy_file = str(promo_cfg.get("file", "")).strip()
        if legacy_file and legacy_file not in files:
            files.append(legacy_file)

        files = [f for f in files if Path(f).exists()]
        if not positions or not files:
            return []

        shuffle = bool(promo_cfg.get("shuffle", True))
        avoid_repeat = bool(promo_cfg.get("avoid_repeat", True))
        pool = files[:]
        selected: List[str] = []
        last = ""
        for index in range(len(positions)):
            if shuffle:
                candidates = pool[:]
                if avoid_repeat and len(candidates) > 1 and last in candidates:
                    candidates.remove(last)
                choice = random.choice(candidates)
            else:
                choice = pool[index % len(pool)]
                if avoid_repeat and len(pool) > 1 and choice == last:
                    choice = pool[(index + 1) % len(pool)]
            selected.append(choice)
            last = choice
        return [Path(f) for f in selected]

    def _mix_promo_audio(self, video: Path, promo_files: List[Path], positions: List[float], out: Path) -> None:
        pairs = [(p, pos) for p, pos in zip(promo_files, positions) if p.exists()]
        if not pairs:
            shutil.copy2(video, out)
            return

        promo_cfg = self.settings.get("promo_audio", {}) or {}
        volume = min(3.0, max(0.0, float(promo_cfg.get("volume", 1.0))))

        cmd = [self.ffmpeg, "-y", "-i", str(video)]
        for promo_file, _pos in pairs:
            cmd += ["-i", str(promo_file)]

        filters: List[str] = []
        # Đưa audio chính vào label riêng và giữ volume 1.0 để không bị amix tự kéo lên/xuống.
        filters.append("[0:a]aresample=48000,volume=1.0[main]")
        mix_inputs = ["[main]"]
        for idx, (_promo_file, pos) in enumerate(pairs, start=1):
            delay_ms = max(0, int(round(pos * 1000)))
            label = f"[promo{idx}]"
            # adelay=...:all=1 đặt audio quảng bá đúng mốc thời gian, rồi amix chồng lên audio chính.
            filters.append(
                f"[{idx}:a]aresample=48000,volume={volume},adelay={delay_ms}:all=1{label}"
            )
            mix_inputs.append(label)

        filters.append(
            "".join(mix_inputs)
            + f"amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0:normalize=0,"
            + "alimiter=limit=0.95,aresample=48000[a]"
        )
        filter_complex = ";".join(filters)

        # Audio-only step: copy video, không encode lại video sau khi chèn promo.
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", str(out),
        ]
        self._run(cmd, "Mix promo audio")

    def _apply_intro_overlay(self, main_video: Path, intro_file: str, out: Path, job_temp: Path, width: int, height: int, fps: int) -> None:
        """Đè hình ảnh video Intro lên các giây đầu của video chính với hiệu ứng Fade Out chuyển cảnh mượt mà (Tăng tốc qua GPU NVENC)."""
        intro_path = Path(intro_file)
        if not intro_path.exists():
            if main_video != out:
                shutil.copyfile(main_video, out)
            return

        intro_dur = get_duration_seconds(intro_path)
        if intro_dur <= 0.1:
            if main_video != out:
                shutil.copyfile(main_video, out)
            return

        fade_dur = min(0.8, max(0.2, intro_dur * 0.2))
        fade_st = max(0.0, intro_dur - fade_dur)
        self.log(f"🎬 Chế độ Intro Đè lên đầu MP3: Hiển thị hình ảnh Intro trong {intro_dur:.2f}s đầu (Fade Out {fade_dur:.2f}s), audio MP3 phát từ 0:00...")

        fade_filter = (
            f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps={fps},format=rgba,fade=t=out:st={fade_st:.3f}:d={fade_dur:.3f}:alpha=1[fade_intro];"
            f"[0:v][fade_intro]overlay=0:0:enable='between(t,0,{intro_dur:.3f})':format=auto[vout]"
        )

        enc_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "19", "-b:v", "0"] if self._encoder() == "nvidia" else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19"]
        cmd = [
            self.ffmpeg, "-y",
            "-i", str(main_video),
            "-i", str(intro_path),
            "-filter_complex", fade_filter,
            "-map", "[vout]",
            "-map", "0:a?",
            *enc_args,
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(out)
        ]
        self._run(cmd, "Hòa trộn Intro Overlay mượt mà lên đầu video")

    def _add_intro_outro(self, main_video: Path, intro_file: str, outro_file: str, out: Path, job_temp: Path, width: int, height: int, fps: int) -> None:
        """Ghép intro/outro theo fast path hỗ trợ cả 2 chế độ Nối tiếp và Đè lên đầu MP3."""
        intro_mode = str(self.settings.get("intro_mode", "sequential") or "sequential").lower()
        current_main = main_video

        # Nếu chọn chế độ Intro Đè lên đầu MP3:
        # Nếu đã render qua Direct 1-Pass Filtergraph thì bỏ qua không re-encode lại lần 2
        if intro_file and Path(intro_file).exists() and intro_mode == "overlay":
            # Đã được tích hợp trực tiếp trong 1-Pass Filtergraph qua GPU NVENC
            intro_file = ""

        segments: List[Path] = []
        prepared_side_segments: List[Path] = []

        if intro_file and Path(intro_file).exists():
            intro_ready = self._prepare_intro_outro_segment(
                src=Path(intro_file),
                main_video=current_main,
                out=job_temp / "intro_ready.mp4",
                width=width,
                height=height,
                fps=fps,
                label="intro",
            )
            segments.append(intro_ready)
            if intro_ready != Path(intro_file):
                prepared_side_segments.append(intro_ready)
        elif intro_file:
            self.log(f"Bỏ qua intro vì không tìm thấy file: {intro_file}")

        segments.append(current_main)

        if outro_file and Path(outro_file).exists():
            outro_ready = self._prepare_intro_outro_segment(
                src=Path(outro_file),
                main_video=current_main,
                out=job_temp / "outro_ready.mp4",
                width=width,
                height=height,
                fps=fps,
                label="outro",
            )
            segments.append(outro_ready)
            if outro_ready != Path(outro_file):
                prepared_side_segments.append(outro_ready)
        elif outro_file:
            self.log(f"Bỏ qua outro vì không tìm thấy file: {outro_file}")

        if len(segments) == 1:
            if segments[0] != out:
                if out.exists():
                    out.unlink()
                shutil.copyfile(segments[0], out)
            return

        try:
            self._concat_segments_copy(segments, out)
            self.log("Intro/outro fast path OK: nối bằng -c copy, không encode lại video chính.")
            return
        except Exception as exc:
            self.log(
                "Fast concat intro/outro bằng -c copy không chạy được với bộ file này. "
                f"Thử fallback remux TS không encode lại video chính. Chi tiết: {exc}"
            )

        try:
            self._concat_segments_copy_via_ts(segments, out, job_temp)
            self.log("Intro/outro TS fallback OK: remux/copy, không encode lại video chính.")
            return
        except Exception as exc:
            self.log(
                "Fallback TS concat vẫn không được. Chuyển sang safe fallback cuối cùng: "
                "chuẩn hóa lại toàn bộ segment, có thể chậm với video dài. "
                f"Chi tiết: {exc}"
            )

        # Fallback cuối để ưu tiên tạo được video thay vì lỗi hàng loạt.
        safe_segments: List[Path] = []
        for idx, segment in enumerate(segments):
            safe_out = job_temp / f"safe_segment_{idx:02d}.mp4"
            self._normalize_segment(segment, safe_out, width, height, fps)
            safe_segments.append(safe_out)
        self._concat_segments_filter(safe_segments, out)

    def _prepare_intro_outro_segment(self, src: Path, main_video: Path, out: Path, width: int, height: int, fps: int, label: str) -> Path:
        if self._segment_copy_compatible(src, main_video, width, height, fps):
            self.log(f"{label}: cùng chuẩn với output/main → dùng trực tiếp, không encode lại.")
            return src
        self.log(f"{label}: khác chuẩn hoặc thiếu audio → chỉ chuẩn hóa {label}, không đụng main video.")
        self._normalize_segment(src, out, width, height, fps)
        return out

    def _probe_media_info(self, src: Path) -> Dict[str, Any]:
        cmd = [
            self.ffprobe, "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", str(src)
        ]
        result = run_hidden(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe không đọc được media info: {src}. Chi tiết: {(result.stderr or result.stdout or '').strip()}")
        try:
            return json.loads(result.stdout or "{}")
        except Exception as exc:
            raise RuntimeError(f"ffprobe trả JSON không hợp lệ cho file: {src}") from exc

    def _first_stream(self, info: Dict[str, Any], codec_type: str) -> Dict[str, Any] | None:
        for stream in info.get("streams", []) or []:
            if stream.get("codec_type") == codec_type:
                return stream
        return None

    @staticmethod
    def _parse_rate(rate: str | None) -> float:
        if not rate or rate == "0/0":
            return 0.0
        try:
            if "/" in rate:
                num, den = rate.split("/", 1)
                den_f = float(den)
                return float(num) / den_f if den_f else 0.0
            return float(rate)
        except Exception:
            return 0.0

    def _segment_copy_compatible(self, segment: Path, main_video: Path, width: int, height: int, fps: int) -> bool:
        """Kiểm tra intro/outro có thể nối copy với main/output không.

        Điều kiện cố ý hơi chặt để tránh lỗi concat hàng loạt: H.264 + AAC, cùng kích thước,
        fps gần bằng output, audio 48k stereo. Nếu sai thì chỉ encode intro/outro lại.
        """
        try:
            seg_info = self._probe_media_info(segment)
            main_info = self._probe_media_info(main_video)
            seg_v = self._first_stream(seg_info, "video")
            seg_a = self._first_stream(seg_info, "audio")
            main_v = self._first_stream(main_info, "video")
            main_a = self._first_stream(main_info, "audio")
            if not seg_v or not main_v or not seg_a or not main_a:
                return False
            if str(seg_v.get("codec_name", "")).lower() != str(main_v.get("codec_name", "")).lower():
                return False
            if str(seg_v.get("codec_name", "")).lower() not in {"h264", "avc1"}:
                return False
            if int(seg_v.get("width", 0) or 0) != int(main_v.get("width", width) or width):
                return False
            if int(seg_v.get("height", 0) or 0) != int(main_v.get("height", height) or height):
                return False
            seg_fps = self._parse_rate(seg_v.get("avg_frame_rate") or seg_v.get("r_frame_rate"))
            main_fps = self._parse_rate(main_v.get("avg_frame_rate") or main_v.get("r_frame_rate"))
            target_fps = main_fps or float(fps)
            if target_fps and abs(seg_fps - target_fps) > 0.15:
                return False
            if str(seg_a.get("codec_name", "")).lower() != str(main_a.get("codec_name", "")).lower():
                return False
            if str(seg_a.get("codec_name", "")).lower() != "aac":
                return False
            if int(seg_a.get("sample_rate", 0) or 0) != int(main_a.get("sample_rate", 48000) or 48000):
                return False
            seg_channels = int(seg_a.get("channels", 0) or 0)
            main_channels = int(main_a.get("channels", 0) or 0)
            if seg_channels and main_channels and seg_channels != main_channels:
                return False
            pix = str(seg_v.get("pix_fmt", "") or "").lower()
            if pix and pix != "yuv420p":
                return False
            return True
        except Exception as exc:
            self.log(f"Không kiểm tra được độ tương thích intro/outro, sẽ normalize segment. Chi tiết: {exc}")
            return False

    def _concat_segments_copy(self, segments: List[Path], out: Path) -> None:
        if len(segments) == 1:
            os.replace(segments[0], out)
            return
        list_file = out.parent / "intro_outro_concat.txt"
        list_file.write_text("".join(f"file '{self._escape_concat_path(p)}'\n" for p in segments), encoding="utf-8")
        cmd = [
            self.ffmpeg, "-y", "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-avoid_negative_ts", "make_zero",
            "-c", "copy", "-movflags", "+faststart", str(out),
        ]
        self._run(cmd, "Concat intro/main/outro copy")

    def _concat_segments_copy_via_ts(self, segments: List[Path], out: Path, job_temp: Path) -> None:
        ts_segments: List[Path] = []
        for idx, segment in enumerate(segments):
            ts_out = job_temp / f"concat_ts_{idx:02d}.ts"
            cmd = [
                self.ffmpeg, "-y", "-i", str(segment),
                "-map", "0:v:0", "-map", "0:a:0?",
                "-c", "copy", "-bsf:v", "h264_mp4toannexb", "-f", "mpegts", str(ts_out),
            ]
            self._run(cmd, f"Remux segment intro/outro sang TS {idx + 1}/{len(segments)}")
            ts_segments.append(ts_out)
        list_file = job_temp / "intro_outro_concat_ts.txt"
        list_file.write_text("".join(f"file '{self._escape_concat_path(p)}'\n" for p in ts_segments), encoding="utf-8")
        cmd = [
            self.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart", str(out),
        ]
        self._run(cmd, "Concat intro/main/outro TS copy")

    @staticmethod
    def _escape_concat_path(path: Path) -> str:
        return str(path.resolve()).replace("\\", "/").replace("'", "'\\''")


    def _normalize_segment(self, src: Path, out: Path, width: int, height: int, fps: int) -> None:
        """Chuẩn hóa một segment ngắn sang chuẩn output.

        Hàm này dùng chủ yếu cho intro/outro. Trong V5.1 fast path, main video dài không đi qua đây,
        trừ fallback cuối cùng khi mọi kiểu concat copy đều thất bại.
        """
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps={fps},format=yuv420p"
        if self._probe_has_audio(src):
            def build(args: List[str]) -> List[str]:
                return [
                    self.ffmpeg, "-y", "-i", str(src),
                    "-vf", vf,
                    "-af", "aresample=48000,aformat=channel_layouts=stereo",
                ] + args + ["-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)]
        else:
            duration = get_duration_seconds(src)
            def build(args: List[str]) -> List[str]:
                return [
                    self.ffmpeg, "-y", "-i", str(src),
                    "-f", "lavfi", "-t", str(duration), "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                    "-vf", vf,
                    "-map", "0:v:0", "-map", "1:a:0",
                ] + args + ["-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)]
        self._run(build(self._video_encode_args()), "Chuẩn hóa intro/outro segment", True, lambda: build(self._fallback_cpu_encode_args()))

    def _concat_segments_filter(self, segments: List[Path], out: Path) -> None:
        """Fallback cuối: concat bằng filter, chậm nhưng cứu các file quá lệch chuẩn."""
        if len(segments) == 1:
            os.replace(segments[0], out)
            return
        def build(args: List[str]) -> List[str]:
            cmd = [self.ffmpeg, "-y"]
            for segment in segments:
                cmd += ["-i", str(segment)]
            filter_inputs = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(len(segments)))
            filter_complex = f"{filter_inputs}concat=n={len(segments)}:v=1:a=1[v][a]"
            return cmd + ["-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]"] + args + ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
        self._run(build(self._video_encode_args()), "Concat intro/main/outro safe fallback", True, lambda: build(self._fallback_cpu_encode_args()))


    def _has_visual_overlays(self, sub_ass_file: Path | None = None) -> bool:
        layout_studio = self.settings.get("layout_studio", {}) or {}
        studio_enabled = bool(layout_studio.get("enabled", True))
        studio_layers = [l for l in (layout_studio.get("layers", []) or []) if isinstance(l, dict) and l.get("enabled", True)]
        if studio_enabled and len(studio_layers) > 0:
            return True

        text = self.settings.get("text_overlay", {}) or {}
        sub = self.settings.get("subtitle", {}) or {}
        fx_mode = str(self.settings.get("video_effect_mode", "none") or "none")
        fx_enabled = bool(self.settings.get("video_effect_enabled", True))
        custom_fx_file = str(self.settings.get("video_effect_custom_file", "") or "").strip()
        has_video_fx = fx_enabled and fx_mode != "none"
        if has_video_fx and fx_mode == "custom" and not (custom_fx_file and Path(custom_fx_file).exists()):
            has_video_fx = False
        has_sub = bool(sub_ass_file and sub_ass_file.exists()) if sub_ass_file is not None else bool(sub.get("enabled"))
        return bool(
            (self.settings.get("watermark_enabled") and self.settings.get("watermark_file"))
            or (self.settings.get("logo_enabled") and self.settings.get("logo_file"))
            or (text.get("enabled") and str(text.get("content", "")).strip())
            or has_sub
            or has_video_fx
        )

    def _resolve_asset_path(self, path_str: str) -> Optional[Path]:
        """Kiểm tra đường dẫn file tài nguyên. Nếu không tìm thấy, thử tìm trên các ổ đĩa khác (E: <-> F:)."""
        if not path_str or not str(path_str).strip():
            return None
        p = Path(str(path_str).strip())
        if p.exists():
            return p
        s = str(p)
        for drive in ["F:", "E:", "D:", "C:"]:
            if len(s) > 2 and s[1] == ":":
                candidate = Path(drive + s[2:])
                if candidate.exists():
                    self.log(f"💡 Tự động nhận diện tài nguyên tại ổ {drive}: {candidate}")
                    return candidate
        return None

    def _video_effect_filter_for_overlay(self, mode: str, width: int, height: int) -> str:
        if not mode or mode == "none":
            return ""
        filters = {
            "film_grain": "noise=alls=14:allf=t+u",
            "vignette": "vignette=PI/4",
            "color_boost": "eq=contrast=1.08:brightness=0.01:saturation=1.20",
            "slow_zoom": f"crop=w='iw*min(1,1-0.00015*n)':h='ih*min(1,1-0.00015*n)':x='(iw-ow)/2':y='(ih-oh)/2',scale={width}:{height}",
            "auto_cinematic": "vignette=PI/4,eq=contrast=1.08:saturation=1.15",
        }
        if mode in filters:
            return filters[mode]
        if mode in {"auto", "random"}:
            return filters["auto_cinematic"]
        return ""

    def _bake_static_layout_canvas(
        self,
        layers: List[Dict[str, Any]],
        width: int,
        height: int,
        out_png: Path,
    ) -> Tuple[List[Dict[str, Any]], Path | None]:
        """Gộp các layer ảnh tĩnh (PNG/JPG/Watermark/Logo) thành 1 canvas RGBA duy nhất để tối ưu cực hạn tốc độ encode."""
        from PIL import Image

        static_layers = []
        for l in layers:
            l_type = str(l.get("type", "image")).lower()
            blend = str(l.get("blend_mode", "alpha")).lower()
            in_eff = str(l.get("in_effect", "none")).lower()
            out_eff = str(l.get("out_effect", "none")).lower()
            mot_eff = str(l.get("motion_effect", "none")).lower()
            has_anim = (in_eff != "none" or out_eff != "none" or mot_eff != "none")

            if l_type in {"image", "banner", "logo", "watermark", "chat_bubble"} and blend in {"alpha", ""} and not has_anim:
                f_path = str(l.get("file_path", "")).strip()
                if f_path:
                    res = self._resolve_asset_path(f_path)
                    if res and res.exists():
                        static_layers.append((l, res))

        if len(static_layers) >= 1:
            try:
                canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                remaining = []
                static_ids = {id(l) for l, _ in static_layers}

                for l in layers:
                    if id(l) in static_ids:
                        f_path = str(l.get("file_path", "")).strip()
                        res = self._resolve_asset_path(f_path)
                        if not res:
                            continue
                        with Image.open(res) as src_img:
                            img = src_img.convert("RGBA")
                            bx = float(l.get("box_x", 0.0))
                            by = float(l.get("box_y", 0.0))
                            bw = float(l.get("box_w", 0.3))
                            bh = float(l.get("box_h", 0.2))

                            px = int(width * bx)
                            py = int(height * by)
                            pw = max(16, int(width * bw))
                            ph = max(16, int(height * bh))
                            opacity = float(l.get("opacity", 1.0) if l.get("opacity") is not None else 1.0)
                            opacity = max(0.0, min(1.0, opacity))

                            scale_mode = str(l.get("scale_mode", "stretch")).lower()
                            if scale_mode == "fit":
                                img.thumbnail((pw, ph), Image.Resampling.LANCZOS)
                                offset_x = px + (pw - img.width) // 2
                                offset_y = py + (ph - img.height) // 2
                            elif scale_mode == "crop":
                                src_ratio = img.width / max(1, img.height)
                                target_ratio = pw / max(1, ph)
                                if src_ratio > target_ratio:
                                    new_w = int(img.height * target_ratio)
                                    left = (img.width - new_w) // 2
                                    img = img.crop((left, 0, left + new_w, img.height))
                                else:
                                    new_h = int(img.width / target_ratio)
                                    top = (img.height - new_h) // 2
                                    img = img.crop((0, top, img.width, top + new_h))
                                img = img.resize((pw, ph), Image.Resampling.LANCZOS)
                                offset_x = px
                                offset_y = py
                            else:
                                img = img.resize((pw, ph), Image.Resampling.LANCZOS)
                                offset_x = px
                                offset_y = py

                            if opacity < 0.999:
                                r, g, b, a = img.split()
                                a = a.point(lambda p: int(p * opacity))
                                img = Image.merge("RGBA", (r, g, b, a))

                            # Hỗ trợ dán ảnh với tọa độ âm / tràn viền bằng paste(img, pos, mask)
                            canvas.paste(img, (offset_x, offset_y), img)
                    else:
                        remaining.append(l)

                canvas.save(out_png, "PNG")
                self.log(f"⚡ Canvas Optimizer: Đã gộp {len(static_layers)} layer tĩnh thành 1 ảnh overlay duy nhất.")
                return remaining, out_png
            except Exception as ex:
                self.log(f"⚠️ Canvas Optimizer gặp lỗi: {ex}, tiếp tục xử lý qua FFmpeg từng layer.")
                return layers, None

        return layers, None

    def _bake_animated_layout_canvas(
        self,
        layers: List[Dict[str, Any]],
        width: int,
        height: int,
        temp_dir: Path,
        fps: int = 30,
    ) -> Tuple[List[Dict[str, Any]], Path | None]:
        """Gộp toàn bộ các layer ảnh tĩnh và hoạt họa động (GIF / Reaction / Video Mask / Image)
        thành 1 luồng video trong suốt ngắn (6.0s, QTRLE RGBA) bảo toàn 100% thứ tự Z-Index và nền trong suốt tuyệt đối."""
        visual_layers: List[Tuple[Dict[str, Any], Path, str]] = []
        remaining_layers: List[Dict[str, Any]] = []
        has_animated = False

        for l in layers:
            l_type = str(l.get("type", "image")).lower()
            f_path_raw = str(l.get("file_path", "")).strip()
            if not f_path_raw:
                remaining_layers.append(l)
                continue

            resolved = self._resolve_asset_path(f_path_raw)
            if not resolved or not resolved.exists():
                remaining_layers.append(l)
                continue

            in_eff = str(l.get("in_effect", "none")).lower()
            out_eff = str(l.get("out_effect", "none")).lower()
            mot_eff = str(l.get("motion_effect", "none")).lower()
            has_anim = (in_eff != "none" or out_eff != "none" or mot_eff != "none")

            if l_type in {"gif", "reaction", "video_mask"}:
                visual_layers.append((l, resolved, l_type))
                has_animated = True
            elif l_type in {"image", "banner", "logo", "watermark", "chat_bubble"}:
                if has_anim:
                    # Layer có hiệu ứng In/Out/Motion -> Render động trực tiếp qua FFmpeg Filtergraph
                    remaining_layers.append(l)
                else:
                    visual_layers.append((l, resolved, l_type))
            else:
                remaining_layers.append(l)

        # Nếu không có layer thị giác nào: giữ nguyên danh sách
        if not visual_layers:
            return layers, None

        canvas_png = temp_dir / "static_layout_canvas.png"

        # Nếu không có layer động nào (chỉ toàn ảnh tĩnh): dùng Pillow gộp siêu tốc 0.03s
        if not has_animated:
            return self._bake_static_layout_canvas(layers, width, height, canvas_png)

        # Nếu CÓ layer động (GIF / Reaction / Video Mask):
        # Tạo file video trong suốt ngắn (6.0s) bảo toàn 100% thứ tự Z-Index của tất cả layer
        anim_mov = temp_dir / "animated_layout_canvas.mov"
        anim_dur = 6.0  # 6 giây là chu kỳ lặp hoàn hảo cho GIF hoạt họa

        # Khởi tạo nền hoàn toàn trong suốt tuyệt đối bằng RGBA 0x00000000
        cmd = [
            self.ffmpeg, "-y", "-threads", "0",
            "-f", "lavfi", "-i", f"color=c=0x00000000:s={width}x{height}:d={anim_dur}:r={fps},format=rgba"
        ]
        filters: List[str] = [f"[0:v]format=rgba[c_base]"]
        last_lbl = "[c_base]"
        in_idx = 1

        for layer, resolved, l_type in visual_layers:
            if l_type in {"gif", "reaction"}:
                cmd += ["-ignore_loop", "0", "-t", str(anim_dur), "-i", str(resolved)]
            elif l_type == "video_mask":
                cmd += ["-stream_loop", "-1", "-t", str(anim_dur), "-i", str(resolved)]
            else:  # image, logo, banner, watermark...
                cmd += ["-loop", "1", "-t", str(anim_dur), "-i", str(resolved)]

            bx = float(layer.get("box_x", 0.0))
            by = float(layer.get("box_y", 0.0))
            bw = float(layer.get("box_w", 0.3))
            bh = float(layer.get("box_h", 0.2))
            px = int(width * bx)
            py = int(height * by)
            pw = max(16, int(width * bw))
            ph = max(16, int(height * bh))
            opacity = max(0.0, min(1.0, float(layer.get("opacity", 1.0) if layer.get("opacity") is not None else 1.0)))
            blend_mode = str(layer.get("blend_mode", "alpha")).lower()

            scale_mode = str(layer.get("scale_mode", "stretch")).lower()
            if scale_mode == "fit":
                fchain = [f"scale={pw}:{ph}:force_original_aspect_ratio=decrease,pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2:color=black@0,fps={fps},format=rgba"]
            elif scale_mode == "crop":
                fchain = [f"scale={pw}:{ph}:force_original_aspect_ratio=increase,crop={pw}:{ph},fps={fps},format=rgba"]
            else:
                fchain = [f"scale={pw}:{ph},fps={fps},format=rgba"]

            if blend_mode in {"colorkey_black", "screen"}:
                fchain.append("colorkey=0x000000:0.15:0.1")
            if opacity < 0.999:
                fchain.append(f"colorchannelmixer=aa={opacity:.2f}")

            in_lbl = f"[a_in_{in_idx}]"
            out_lbl = f"[a_v_{in_idx}]"
            filters.append(f"[{in_idx}:v]{','.join(fchain)}{in_lbl}")
            filters.append(f"{last_lbl}{in_lbl}overlay={px}:{py}:format=auto{out_lbl}")
            last_lbl = out_lbl
            in_idx += 1

        cmd += [
            "-filter_complex", ";".join(filters),
            "-map", last_lbl,
            "-t", str(anim_dur),
            "-c:v", "qtrle",
            "-pix_fmt", "argb",
            str(anim_mov),
        ]

        try:
            start_bake = time.time()
            self._run(
                cmd,
                "Pre-bake Animated Layout Canvas",
                allow_cpu_fallback=True,
            )
            if anim_mov.exists() and anim_mov.stat().st_size > 10240:
                elapsed = time.time() - start_bake
                self.log(f"⚡ Layout Animation Optimizer: Đã nén trước {len(visual_layers)} layer theo đúng Z-Index thành 1 luồng video trong suốt ({anim_dur:.1f}s) trong {elapsed:.1f}s!")
                return remaining_layers, anim_mov
        except Exception as ex:
            self.log(f"⚠️ Layout Animation Optimizer gặp lỗi: {ex}, tiếp tục xử lý qua FFmpeg từng layer.")

        # Fallback về static canvas nếu anim mov thất bại
        return self._bake_static_layout_canvas(layers, width, height, canvas_png)

    def _build_visual_layers_filtergraph(
        self,
        cmd: List[str],
        filters: List[str],
        base_label: str,
        input_index_start: int,
        width: int,
        height: int,
        sub_ass_file: Path | None = None,
        audio_title: str = "",
        temp_dir: Path | None = None,
        fps: int = 30,
    ) -> Tuple[str, int]:
        """Tạo chuỗi filtergraph cho toàn bộ các layer (Layout Studio multi-layer) hoặc fallback cũ."""
        last = base_label
        input_index = input_index_start
        stage = 0

        layout_studio = self.settings.get("layout_studio", {}) or {}
        studio_enabled = bool(layout_studio.get("enabled", True))
        raw_layers = [l for l in (layout_studio.get("layers", []) or []) if isinstance(l, dict) and l.get("enabled", True)]
        sub_rendered = False

        # Nếu có danh sách layers được cấu hình trong Studio Layout:
        if studio_enabled and len(raw_layers) > 0:
            if temp_dir:
                layers, baked_asset = self._bake_static_layout_canvas(raw_layers, width, height, temp_dir / "static_layout_canvas.png")
                if baked_asset and baked_asset.exists():
                    cmd += ["-i", str(baked_asset)]
                    in_lbl = f"[layer_in_{stage}]"
                    out_lbl = f"[layer_v_{stage}]"
                    filters.append(f"[{input_index}:v]format=rgba{in_lbl}")
                    filters.append(f"{last}{in_lbl}overlay=0:0:format=auto{out_lbl}")
                    last = out_lbl
                    input_index += 1
                    stage += 1
            else:
                layers = raw_layers

            for layer in layers:
                l_type = str(layer.get("type", "image")).lower()
                l_name = str(layer.get("name", "Layer"))
                opacity = float(layer.get("opacity", 1.0) if layer.get("opacity") is not None else 1.0)
                opacity = max(0.0, min(1.0, opacity))
                blend_mode = str(layer.get("blend_mode", "alpha"))

                # Tọa độ chuẩn hóa (hỗ trợ âm / tràn viền)
                bx = float(layer.get("box_x", 0.0))
                by = float(layer.get("box_y", 0.0))
                bw = float(layer.get("box_w", 0.3))
                bh = float(layer.get("box_h", 0.2))

                px = int(width * bx)
                py = int(height * by)
                pw = max(16, int(width * bw))
                ph = max(16, int(height * bh))

                if l_type in {"image", "gif", "video_mask", "banner", "logo", "watermark", "chat_bubble", "reaction"}:
                    f_path_raw = str(layer.get("file_path", "")).strip()
                    if not f_path_raw:
                        continue
                    resolved = self._resolve_asset_path(f_path_raw)
                    if not resolved or not resolved.exists():
                        raise FileNotFoundError(f"Không tìm thấy file của layer '{l_name}': {f_path_raw}")

                    if l_type in {"gif", "reaction"}:
                        cmd += ["-ignore_loop", "0", "-i", str(resolved)]
                    elif l_type == "video_mask":
                        cmd += ["-stream_loop", "-1", "-i", str(resolved)]
                    else:
                        cmd += ["-i", str(resolved)]

                    in_lbl = f"[layer_in_{stage}]"
                    out_lbl = f"[layer_v_{stage}]"

                    scale_mode = str(layer.get("scale_mode", "stretch")).lower()
                    if scale_mode == "fit":
                        filter_chain = [f"scale={pw}:{ph}:force_original_aspect_ratio=decrease,pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2:color=black@0,fps={fps},format=rgba"]
                    elif scale_mode == "crop":
                        filter_chain = [f"scale={pw}:{ph}:force_original_aspect_ratio=increase,crop={pw}:{ph},fps={fps},format=rgba"]
                    else:  # stretch (mặc định khớp khung kéo)
                        filter_chain = [f"scale={pw}:{ph},fps={fps},format=rgba"]

                    if blend_mode in {"colorkey_black", "screen"}:
                        filter_chain.append("colorkey=0x000000:0.15:0.1")
                    if opacity < 0.999:
                        filter_chain.append(f"colorchannelmixer=aa={opacity:.2f}")

                    in_eff = str(layer.get("in_effect", "none")).lower()
                    in_dur = max(0.2, min(5.0, float(layer.get("in_duration", 0.8) or 0.8)))
                    mot_eff = str(layer.get("motion_effect", "none")).lower()

                    if in_eff == "fade_in":
                        filter_chain.append(f"fade=t=in:st=0:d={in_dur:.2f}:alpha=1")

                    x_expr = str(px)
                    y_expr = str(py)
                    has_spatial_anim = False

                    if in_eff == "slide_left":
                        x_expr = f"if(lte(t,{in_dur:.2f}), {px}-({pw}*(1-t/{in_dur:.2f})), {px})"
                        has_spatial_anim = True
                    elif in_eff == "slide_right":
                        x_expr = f"if(lte(t,{in_dur:.2f}), {px}+({pw}*(1-t/{in_dur:.2f})), {px})"
                        has_spatial_anim = True
                    elif in_eff == "slide_up":
                        y_expr = f"if(lte(t,{in_dur:.2f}), {py}+({ph}*(1-t/{in_dur:.2f})), {py})"
                        has_spatial_anim = True
                    elif in_eff == "slide_down":
                        y_expr = f"if(lte(t,{in_dur:.2f}), {py}-({ph}*(1-t/{in_dur:.2f})), {py})"
                        has_spatial_anim = True

                    if mot_eff == "float":
                        y_expr = f"({y_expr})+5*sin(2*PI*t/3)"
                        has_spatial_anim = True
                    elif mot_eff == "pulse":
                        y_expr = f"({y_expr})+2*sin(2*PI*t/2)"
                        has_spatial_anim = True

                    filters.append(f"[{input_index}:v]{','.join(filter_chain)}{in_lbl}")
                    if has_spatial_anim:
                        filters.append(f"{last}{in_lbl}overlay=x='{x_expr}':y='{y_expr}':eval=frame:format=auto{out_lbl}")
                    else:
                        filters.append(f"{last}{in_lbl}overlay={px}:{py}:format=auto{out_lbl}")
                    last = out_lbl
                    input_index += 1
                    stage += 1

                elif l_type == "text":
                    raw_content = str(layer.get("text_content", "") or layer.get("content", "")).strip()
                    content = raw_content
                    # Tự động thay thế biến động {title}, {filename}, v.v. bằng tên file audio đang render
                    if not content and (l_name.lower() in ["tiêu-đề", "tieu de", "title", "tiêu đề", "tieude"]):
                        content = audio_title
                    elif audio_title:
                        for tag in ["{title}", "{filename}", "{name}", "{audio_name}", "{ten_audio}", "{ten_video}", "{tieu_de}"]:
                            content = content.replace(tag, audio_title).replace(tag.upper(), audio_title)

                    content = self._clean_title_text(content)
                    if not content:
                        continue

                    font_size = int(layer.get("font_size", 36) or 36)
                    font_name = str(layer.get("font_name", "Arial") or "Arial")
                    font_bold = bool(layer.get("bold", True))
                    font_italic = bool(layer.get("italic", False))

                    font_file = self._find_font_file_by_name(font_name, font_bold, font_italic)

                    # Tự động ngắt dòng và co kích thước chữ vừa vặn hoàn hảo trong ô
                    layer_spacing = int(layer.get("line_spacing", 4) or 4)
                    wrapped_content, fitted_font_size = self._wrap_text_for_box(
                        text=content,
                        font_file=font_file,
                        font_size=font_size,
                        max_w=pw,
                        max_h=ph,
                        line_spacing=layer_spacing,
                        max_lines=2,
                    )

                    font_color_raw = str(layer.get("font_color", "#FFFFFF")).strip()
                    font_color = self._normalize_ffmpeg_color(font_color_raw)

                    outline_color_raw = str(layer.get("outline_color", "#000000")).strip()
                    outline_width = float(layer.get("outline_width", 2.0) or 2.0)
                    has_outline = (outline_color_raw.lower() not in {"none", "transparent", ""}) and outline_width > 0

                    bg_color_raw = str(layer.get("bg_box_color", "black")).strip()
                    bg_box_enabled = bool(layer.get("bg_box_enabled", False)) and (bg_color_raw.lower() not in {"none", "transparent", ""})
                    bg_opacity = float(layer.get("bg_box_opacity", 0.5) if layer.get("bg_box_opacity") is not None else 0.5)

                    in_eff = str(layer.get("in_effect", "none")).lower()
                    in_dur = max(0.2, min(5.0, float(layer.get("in_duration", 0.8) or 0.8)))
                    mot_eff = str(layer.get("motion_effect", "none")).lower()

                    font_align = str(layer.get("align", "center")).lower()
                    if font_align == "center":
                        base_x = f"{px}+({pw}-text_w)/2"
                        base_y = f"{py}+({ph}-text_h)/2"
                    elif font_align == "right":
                        base_x = f"{px}+{pw}-text_w"
                        base_y = f"{py}+({ph}-text_h)/2"
                    else:  # left
                        base_x = f"{px}"
                        base_y = f"{py}+({ph}-text_h)/2"

                    x_pos = base_x
                    y_pos = base_y
                    has_anim_pos = False

                    if in_eff == "slide_up":
                        y_pos = f"if(lte(t,{in_dur:.2f}), ({base_y})+({ph}*(1-t/{in_dur:.2f})), ({base_y}))"
                        has_anim_pos = True
                    elif in_eff == "slide_down":
                        y_pos = f"if(lte(t,{in_dur:.2f}), ({base_y})-({ph}*(1-t/{in_dur:.2f})), ({base_y}))"
                        has_anim_pos = True
                    elif in_eff == "slide_left":
                        x_pos = f"if(lte(t,{in_dur:.2f}), ({base_x})-({pw}*(1-t/{in_dur:.2f})), ({base_x}))"
                        has_anim_pos = True
                    elif in_eff == "slide_right":
                        x_pos = f"if(lte(t,{in_dur:.2f}), ({base_x})+({pw}*(1-t/{in_dur:.2f})), ({base_x}))"
                        has_anim_pos = True

                    if mot_eff == "float":
                        y_pos = f"({y_pos})+4*sin(2*PI*t/3)"
                        has_anim_pos = True
                    elif mot_eff == "pulse":
                        y_pos = f"({y_pos})+2*sin(2*PI*t/2)"
                        has_anim_pos = True

                    if has_anim_pos:
                        pos_expr = f"x='{x_pos}':y='{y_pos}'"
                    else:
                        pos_expr = f"x={base_x}:y={base_y}"

                    eff_spacing = layer_spacing
                    if fitted_font_size >= 60:
                        eff_spacing = max(-35, layer_spacing - int(fitted_font_size * 0.20))
                    elif fitted_font_size >= 35:
                        eff_spacing = max(-20, layer_spacing - int(fitted_font_size * 0.10))

                    dt_parts = [
                        f"text='{self._escape_drawtext(wrapped_content)}'",
                        f"fontsize={fitted_font_size}",
                        f"fontcolor={font_color}",
                        pos_expr,
                        f"line_spacing={eff_spacing}",
                    ]

                    if in_eff == "fade_in":
                        dt_parts.append(f"alpha='if(lte(t,{in_dur:.2f}), t/{in_dur:.2f}, 1)'")

                    if has_outline:
                        border_color = self._normalize_ffmpeg_color(outline_color_raw)
                        dt_parts.append(f"borderw={int(round(outline_width))}")
                        dt_parts.append(f"bordercolor={border_color}")
                    else:
                        dt_parts.append("borderw=0")

                    if font_file:
                        dt_parts.append(f"fontfile='{self._escape_drawtext(font_file.as_posix())}'")

                    if bg_box_enabled:
                        norm_bg = self._normalize_ffmpeg_color(bg_color_raw)
                        dt_parts += ["box=1", f"boxcolor={norm_bg}@{bg_opacity:.2f}", "boxborderw=10"]

                    out_lbl = f"[layer_v_{stage}]"
                    filters.append(f"{last}drawtext={':'.join(dt_parts)}{out_lbl}")
                    last = out_lbl
                    stage += 1

                elif l_type == "subtitle":
                    if sub_ass_file and sub_ass_file.exists():
                        out_lbl = f"[v_sub_{stage}]"
                        ass_path_escaped = str(sub_ass_file.resolve()).replace("\\", "/").replace(":", "\\:")
                        filters.append(f"{last}ass='{ass_path_escaped}'{out_lbl}")
                        last = out_lbl
                        stage += 1
                        sub_rendered = True

                elif l_type == "live_badge":
                    # Huy hiệu LIVE đỏ góc trên
                    dt_parts = [
                        "text='LIVE'",
                        f"fontsize={max(14, int(ph * 0.45))}",
                        "fontcolor=white",
                        f"x={px + 10}:y={py + 5}",
                        "box=1", "boxcolor=red@0.85", "boxborderw=8"
                    ]
                    out_lbl = f"[layer_v_{stage}]"
                    filters.append(f"{last}drawtext={':'.join(dt_parts)}{out_lbl}")
                    last = out_lbl
                    stage += 1

        else:
            # Fallback legacy cấu hình cũ nếu chưa dùng Studio layers:
            # 1. Video Effect / Particles
            fx_mode = str(self.settings.get("video_effect_mode", "none") or "none")
            fx_enabled = bool(self.settings.get("video_effect_enabled", True))
            custom_fx_file = str(self.settings.get("video_effect_custom_file", "") or "").strip()
            overlay_video = get_overlay_file(fx_mode, custom_file=custom_fx_file)

            if fx_enabled and overlay_video and overlay_video.exists():
                cmd += ["-stream_loop", "-1", "-i", str(overlay_video)]
                fx_opacity = min(1.0, max(0.05, float(self.settings.get("video_effect_opacity", 0.80) or 0.80)))
                ov_label = f"[ov{stage}]"
                out_label = f"[v_stage{stage}]"
                filters.append(
                    f"[{input_index}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},format=rgba,colorkey=0x000000:0.15:0.1,colorchannelmixer=aa={fx_opacity:.2f}{ov_label}"
                )
                filters.append(f"{last}{ov_label}overlay=0:0:format=auto{out_label}")
                last = out_label
                input_index += 1
                stage += 1
            elif fx_enabled and fx_mode != "none":
                fx_str = self._video_effect_filter_for_overlay(fx_mode, width, height)
                if fx_str:
                    out_label = f"[v_stage{stage}]"
                    filters.append(f"{last}{fx_str}{out_label}")
                    last = out_label
                    stage += 1

            # Watermark
            watermark_file = str(self.settings.get("watermark_file", "") or "").strip()
            if self.settings.get("watermark_enabled") and watermark_file:
                watermark = self._resolve_asset_path(watermark_file)
                if watermark:
                    cmd += ["-i", str(watermark)]
                    opacity = min(1.0, max(0.0, float(self.settings.get("watermark_opacity", 0.2))))
                    wm_scale = min(3.0, max(0.5, float(self.settings.get("watermark_scale", 1.0))))
                    scaled_w = max(width, int(width * wm_scale))
                    scaled_h = max(height, int(height * wm_scale))
                    wm_label = f"[wm{stage}]"
                    out_label = f"[v_stage{stage}]"
                    filters.append(
                        f"[{input_index}:v]scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase,"
                        f"crop={width}:{height},format=rgba,colorchannelmixer=aa={opacity}{wm_label}"
                    )
                    filters.append(f"{last}{wm_label}overlay=0:0:format=auto{out_label}")
                    last = out_label
                    input_index += 1
                    stage += 1
                else:
                    raise FileNotFoundError(f"Không tìm thấy file Watermark kênh: {watermark_file}")

            # Logo
            logo_file = str(self.settings.get("logo_file", "") or "").strip()
            if self.settings.get("logo_enabled") and logo_file:
                logo = self._resolve_asset_path(logo_file)
                if logo:
                    cmd += ["-i", str(logo)]
                    scale = float(self.settings.get("logo_scale", 0.12))
                    logo_width = max(32, int(width * scale))
                    pos = self.settings.get("logo_position", "top_right")
                    margin_x = int(self.settings.get("logo_margin_x", 30))
                    margin_y = int(self.settings.get("logo_margin_y", 30))
                    positions = {
                        "top_left": f"{margin_x}:{margin_y}",
                        "top_center": f"(W-w)/2:{margin_y}",
                        "top_right": f"W-w-{margin_x}:{margin_y}",
                        "center_left": f"{margin_x}:(H-h)/2",
                        "center": "(W-w)/2:(H-h)/2",
                        "center_right": f"W-w-{margin_x}:(H-h)/2",
                        "bottom_left": f"{margin_x}:H-h-{margin_y}",
                        "bottom_center": f"(W-w)/2:H-h-{margin_y}",
                        "bottom_right": f"W-w-{margin_x}:H-h-{margin_y}",
                    }
                    lg_label = f"[lg{stage}]"
                    out_label = f"[v_stage{stage}]"
                    filters.append(f"[{input_index}:v]scale={logo_width}:-1,format=rgba{lg_label}")
                    filters.append(f"{last}{lg_label}overlay={positions.get(pos, positions['top_right'])}:format=auto{out_label}")
                    last = out_label
                    input_index += 1
                    stage += 1
                else:
                    raise FileNotFoundError(f"Không tìm thấy file Logo kênh: {logo_file}")

            # Text overlay
            text_cfg = self.settings.get("text_overlay", {}) or {}
            raw_text = str(text_cfg.get("content", "")).strip()
            content = raw_text
            if audio_title:
                for tag in ["{title}", "{filename}", "{name}", "{audio_name}", "{ten_audio}", "{ten_video}", "{tieu_de}"]:
                    content = content.replace(tag, audio_title).replace(tag.upper(), audio_title)
            if not content and audio_title:
                content = audio_title
            if text_cfg.get("enabled") and content:
                out_label = f"[v_stage{stage}]"
                filters.append(f"{last}{self._drawtext_filter_body(text_cfg, content)}{out_label}")
                last = out_label
                stage += 1

        # Subtitle overlay via ASS (nếu chưa được chèn theo layer z-index ở trên)
        if not sub_rendered and sub_ass_file and sub_ass_file.exists():
            out_label = f"[v_sub_{stage}]"
            ass_path_escaped = str(sub_ass_file.resolve()).replace("\\", "/").replace(":", "\\:")
            filters.append(f"{last}ass='{ass_path_escaped}'{out_label}")
            last = out_label
            stage += 1

        # TÍCH HỢP INTRO OVERLAY VÀO 1-PASS FILTERGRAPH Ở LỚP CAO NHẤT (PHỦ TOÀN BỘ LAYOUT & SUBTITLE CHO ĐẾN KHI FADE OUT)
        intro_file = self.settings.get("intro_file") or ""
        intro_mode = str(self.settings.get("intro_mode", "sequential") or "sequential").lower()
        if intro_file and Path(intro_file).exists() and intro_mode == "overlay":
            intro_path = Path(intro_file)
            intro_dur = get_duration_seconds(intro_path)
            if intro_dur > 0.1:
                cmd += ["-i", str(intro_path)]
                out_intro = f"[intro_fade_{stage}]"
                out_lbl = f"[intro_v_{stage}]"
                fade_dur = min(0.8, max(0.2, intro_dur * 0.2))
                fade_st = max(0.0, intro_dur - fade_dur)
                filters.append(
                    f"[{input_index}:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps={fps},format=rgba,fade=t=out:st={fade_st:.3f}:d={fade_dur:.3f}:alpha=1{out_intro}"
                )
                filters.append(
                    f"{last}{out_intro}overlay=0:0:enable='between(t,0,{intro_dur:.3f})':format=auto{out_lbl}"
                )
                last = out_lbl
                input_index += 1
                stage += 1

        return last, input_index

    def _apply_visual_overlays(self, video: Path, out: Path, width: int, height: int, sub_ass_file: Path | None = None, audio_title: str = "") -> None:
        """Gộp visual overlays (Layout Studio đa tầng / Watermark / Logo / Text / Mask) vào một lần encode video."""
        fps = int(self.settings.get("export", {}).get("fps", 30) or 30)
        cmd = [self.ffmpeg, "-y", "-threads", "0", "-i", str(video)]
        filters: List[str] = []

        last, _ = self._build_visual_layers_filtergraph(
            cmd=cmd,
            filters=filters,
            base_label="[0:v]",
            input_index_start=1,
            width=width,
            height=height,
            sub_ass_file=sub_ass_file,
            audio_title=audio_title,
            temp_dir=out.parent,
            fps=fps,
        )

        filters.append(f"{last}format=yuv420p[v]")
        duration = get_duration_seconds(video)

        def build(args: List[str]) -> List[str]:
            return cmd + ["-filter_complex", ";".join(filters), "-map", "[v]", "-an", "-t", f"{duration:.6f}"] + args + [str(out)]

        self._run(build(self._video_encode_args()), "Visual overlay 1 pass", True, lambda: build(self._fallback_cpu_encode_args()))

    def _render_direct_single_pass(
        self,
        tasks: List[Tuple[int, Path, str, float, float]],
        out: Path,
        width: int,
        height: int,
        fps: int,
        sub_ass_file: Path | None = None,
        audio_title: str = "",
    ) -> None:
        """Render trực tiếp từ ảnh/video nguồn + transitions + visual overlays + phụ đề ASS chỉ trong 1 pass duy nhất."""
        cmd = [self.ffmpeg, "-y", "-threads", "0"]
        filters: List[str] = []
        is_cuda_hwaccel = self._encoder() == "nvidia"

        if len(tasks) == 1:
            idx, src, media_type, duration, speed = tasks[0]
            if media_type == "image":
                cmd += ["-framerate", str(fps), "-loop", "1", "-i", str(src)]
                vf = self._image_effect_filter(width, height, fps, duration, 1)
                filters.append(f"[0:v]{vf},trim=duration={duration:.6f},setpts=PTS-STARTPTS[base_bg]")
            else:
                if is_cuda_hwaccel:
                    cmd += ["-hwaccel", "cuda", "-stream_loop", "-1", "-i", str(src)]
                else:
                    cmd += ["-stream_loop", "-1", "-i", str(src)]
                base_vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps={fps}"
                if abs(speed - 1.0) > 0.001:
                    base_vf = f"setpts=PTS/{speed:.6f},{base_vf}"
                fx_enabled = bool(self.settings.get("video_effect_enabled", False))
                extra_fx = self._video_effect_filter(width, height, fps, duration, 1) if fx_enabled else ""
                if extra_fx:
                    base_vf = f"{base_vf},{extra_fx}"
                filters.append(f"[0:v]{base_vf},trim=duration={duration:.6f},setpts=PTS-STARTPTS[base_bg]")

            total_duration = duration
            input_index_start = 1
        else:
            for i, (idx, src, media_type, duration, speed) in enumerate(tasks):
                if media_type == "image":
                    cmd += ["-framerate", str(fps), "-loop", "1", "-t", f"{duration:.6f}", "-i", str(src)]
                    vf = self._image_effect_filter(width, height, fps, duration, idx)
                    filters.append(f"[{i}:v]{vf},trim=duration={duration:.6f},setpts=PTS-STARTPTS[v_clip_{i}]")
                else:
                    if is_cuda_hwaccel:
                        cmd += ["-hwaccel", "cuda", "-i", str(src)]
                    else:
                        cmd += ["-i", str(src)]
                    base_vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps={fps}"
                    if abs(speed - 1.0) > 0.001:
                        base_vf = f"setpts=PTS/{speed:.6f},{base_vf}"
                    fx_enabled = bool(self.settings.get("video_effect_enabled", False))
                    extra_fx = self._video_effect_filter(width, height, fps, duration, idx) if fx_enabled else ""
                    if extra_fx:
                        base_vf = f"{base_vf},{extra_fx}"
                    filters.append(f"[{i}:v]{base_vf},trim=duration={duration:.6f},setpts=PTS-STARTPTS[v_clip_{i}]")

            transition_mode = str(self.settings.get("transition_mode", "fade") or "none")
            durations = [t[3] for t in tasks]
            if transition_mode != "none":
                transition_duration = self._transition_duration(min(durations) if durations else 0.0)
                selected_transitions = self._transition_sequence(transition_mode, max(1, len(tasks) - 1))
                prev = "[v_clip_0]"
                timeline_duration = max(0.1, durations[0])
                for idx_trans in range(1, len(tasks)):
                    trans = selected_transitions[idx_trans - 1]
                    offset = max(0.05, timeline_duration - transition_duration)
                    out_label = f"[v_xf_{idx_trans}]" if idx_trans < len(tasks) - 1 else "[base_bg]"
                    filters.append(
                        f"{prev}[v_clip_{idx_trans}]xfade=transition={trans}:duration={transition_duration:.2f}:offset={offset:.2f}{out_label}"
                    )
                    timeline_duration = timeline_duration + max(0.1, durations[idx_trans]) - transition_duration
                    prev = out_label
                total_duration = timeline_duration
            else:
                concat_inputs = "".join(f"[v_clip_{i}]" for i in range(len(tasks)))
                filters.append(f"{concat_inputs}concat=n={len(tasks)}:v=1:a=0[base_bg]")
                total_duration = sum(durations)

            input_index_start = len(tasks)

        last, _ = self._build_visual_layers_filtergraph(
            cmd=cmd,
            filters=filters,
            base_label="[base_bg]",
            input_index_start=input_index_start,
            width=width,
            height=height,
            sub_ass_file=sub_ass_file,
            audio_title=audio_title,
            temp_dir=out.parent,
            fps=fps,
        )
        filters.append(f"{last}format=yuv420p[v]")

        script_file = out.parent / f"{out.stem}_direct_1pass_filter.txt"
        script_file.write_text(";".join(filters), encoding="utf-8")

        def build(args: List[str]) -> List[str]:
            return cmd + ["-filter_complex_script", str(script_file), "-map", "[v]", "-an", "-t", f"{total_duration:.6f}"] + args + ["-movflags", "+faststart", str(out)]

        def build_cpu() -> List[str]:
            cpu_cmd = [part for part in cmd if part not in {"-hwaccel", "cuda"}]
            return cpu_cmd + ["-filter_complex_script", str(script_file), "-map", "[v]", "-an", "-t", f"{total_duration:.6f}"] + self._fallback_cpu_encode_args() + ["-movflags", "+faststart", str(out)]

        stage_name = f"Render Direct 1-Pass ({len(tasks)} media -> video cuối)"
        self._run(build(self._video_encode_args()), stage_name, True, build_cpu)

    def _concat_and_overlay_single_pass(
        self,
        clips: List[Path],
        out: Path,
        clip_durations: List[float],
        width: int,
        height: int,
        sub_ass_file: Path | None = None,
        audio_title: str = "",
        fps: int = 30,
    ) -> None:
        """Gộp XFade transitions và toàn bộ visual overlays (Layout Studio đa tầng) thành 1 pass duy nhất."""
        transition_mode = str(self.settings.get("transition_mode", "fade") or "none")
        transition_duration = self._transition_duration(min(clip_durations) if clip_durations else 0.0)
        selected_transitions = self._transition_sequence(transition_mode, max(1, len(clips) - 1))

        filters: List[str] = []
        prev = "[0:v]"
        timeline_duration = max(0.1, clip_durations[0])
        for idx in range(1, len(clips)):
            trans = selected_transitions[idx - 1]
            offset = max(0.05, timeline_duration - transition_duration)
            out_label = f"[v{idx}]" if idx < len(clips) - 1 else "[v_xfade]"
            filters.append(
                f"{prev}[{idx}:v]xfade=transition={trans}:duration={transition_duration:.2f}:offset={offset:.2f}{out_label}"
            )
            timeline_duration = timeline_duration + max(0.1, clip_durations[idx]) - transition_duration
            prev = out_label

        cmd = [self.ffmpeg, "-y", "-threads", "0"]
        for clip in clips:
            cmd += ["-i", str(clip)]

        last, _ = self._build_visual_layers_filtergraph(
            cmd=cmd,
            filters=filters,
            base_label="[v_xfade]",
            input_index_start=len(clips),
            width=width,
            height=height,
            sub_ass_file=sub_ass_file,
            audio_title=audio_title,
            temp_dir=out.parent,
            fps=fps,
        )

        filters.append(f"{last}format=yuv420p[v]")

        script_file = out.parent / f"{out.stem}_1pass_filter.txt"
        script_file.write_text(";".join(filters), encoding="utf-8")

        def build(args: List[str]) -> List[str]:
            return cmd + ["-filter_complex_script", str(script_file), "-map", "[v]", "-an", "-t", f"{timeline_duration:.6f}"] + args + [str(out)]

        stage_name = "Nối clip & gắn visual overlay (1-pass siêu tốc)"
        self._run(build(self._video_encode_args()), stage_name, True, lambda: build(self._fallback_cpu_encode_args()))

    def _drawtext_filter_body(self, text_cfg: Dict[str, Any], content: str) -> str:
        font_size = int(text_cfg.get("font_size", 48))
        position = text_cfg.get("position", "bottom_center")
        margin_x = int(text_cfg.get("margin_x", 40))
        margin_y = int(text_cfg.get("margin_y", 80))
        font_color = self._normalize_ffmpeg_color(str(text_cfg.get("font_color", "#FFFFFF")))
        box_enabled = bool(text_cfg.get("box_enabled", True))
        box_opacity = float(text_cfg.get("box_opacity", 0.45))
        moving_enabled = bool(text_cfg.get("moving_enabled", False))
        speed_x = int(text_cfg.get("speed_x", 135))
        speed_y = int(text_cfg.get("speed_y", 85))

        if moving_enabled:
            # Chuyển động hình thoi / phản xạ quanh toàn màn hình với góc tới < 90 độ (Chống Reup)
            # Dấu phẩy trong hàm mod() bên trong chuỗi phải escape thành \, để FFmpeg không tách filter
            span_x = max(20, margin_x * 2)
            span_y = max(20, margin_y * 2)
            pos_x = f"x='abs(mod(t*{speed_x}\\, 2*(w-text_w-{span_x})) - (w-text_w-{span_x})) + {margin_x}'"
            pos_y = f"y='abs(mod(t*{speed_y}\\, 2*(h-text_h-{span_y})) - (h-text_h-{span_y})) + {margin_y}'"
            pos_expr = f"{pos_x}:{pos_y}"
        else:
            positions = {
                "top_left": f"x={margin_x}:y={margin_y}", "top_center": f"x=(w-text_w)/2:y={margin_y}",
                "top_right": f"x=w-text_w-{margin_x}:y={margin_y}", "center": "x=(w-text_w)/2:y=(h-text_h)/2",
                "bottom_left": f"x={margin_x}:y=h-text_h-{margin_y}", "bottom_center": f"x=(w-text_w)/2:y=h-text_h-{margin_y}",
                "bottom_right": f"x=w-text_w-{margin_x}:y=h-text_h-{margin_y}",
            }
            pos_expr = positions.get(position, positions["bottom_center"])

        drawtext_parts = [
            f"text='{self._escape_drawtext(content)}'",
            f"fontsize={font_size}",
            f"fontcolor={font_color}",
            pos_expr,
            "line_spacing=8",
        ]
        font_file = self._default_font_file()
        if font_file:
            drawtext_parts.append(f"fontfile='{self._escape_drawtext(font_file.as_posix())}'")
        if box_enabled:
            drawtext_parts += ["box=1", f"boxcolor=black@{box_opacity}", "boxborderw=18"]
        return "drawtext=" + ":".join(drawtext_parts)


    def _finalize_output(self, src: Path, out: Path) -> None:
        """Đưa file cuối ra output.

        V4.3.6 ưu tiên move/replace thay vì remux tạo thêm một bản MP4 lớn.
        Vì temp được đặt trong Output folder/_avr_temp nên đa số trường hợp là cùng ổ, move rất nhanh
        và không cần thêm dung lượng gấp đôi ở bước cuối.
        """
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(src, out)
            self.log(f"Đã move file cuối sang output: {out}")
            return
        except Exception as exc:
            self.log(f"Move file cuối không được, thử shutil.move. Chi tiết: {exc}")
        try:
            shutil.move(str(src), str(out))
            self.log(f"Đã chuyển file cuối sang output: {out}")
            return
        except Exception as exc:
            raise RuntimeError(f"Không chuyển được file cuối sang output {out}: {exc}") from exc

    def _overlay_logo(self, video: Path, logo: Path, out: Path, width: int, height: int) -> None:
        resolved = self._resolve_asset_path(str(logo))
        if not resolved:
            self.log(f"⚠️ [Bỏ qua Logo] Không tìm thấy logo: {logo}. Tiếp tục render video.")
            try:
                shutil.copy2(str(video), str(out))
            except Exception as e:
                self.log(f"Lỗi sao chép video tạm: {e}")
            return
        logo = resolved
        scale = float(self.settings.get("logo_scale", 0.12))
        logo_width = max(32, int(width * scale))
        pos = self.settings.get("logo_position", "top_right")
        margin_x = int(self.settings.get("logo_margin_x", 30))
        margin_y = int(self.settings.get("logo_margin_y", 30))
        positions = {
            "top_left": f"{margin_x}:{margin_y}",
            "top_center": f"(W-w)/2:{margin_y}",
            "top_right": f"W-w-{margin_x}:{margin_y}",
            "center_left": f"{margin_x}:(H-h)/2",
            "center": "(W-w)/2:(H-h)/2",
            "center_right": f"W-w-{margin_x}:(H-h)/2",
            "bottom_left": f"{margin_x}:H-h-{margin_y}",
            "bottom_center": f"(W-w)/2:H-h-{margin_y}",
            "bottom_right": f"W-w-{margin_x}:H-h-{margin_y}",
        }
        filter_complex = (
            f"[1:v]scale={logo_width}:-1,format=rgba[lg];"
            f"[0:v][lg]overlay={positions.get(pos, positions['top_right'])}:format=auto,format=yuv420p[v]"
        )
        def build(args: List[str]) -> List[str]:
            return [
                self.ffmpeg, "-y", "-i", str(video), "-i", str(logo),
                "-filter_complex", filter_complex,
                "-map", "[v]", "-map", "0:a?",
            ] + args + ["-c:a", "copy", "-movflags", "+faststart", str(out)]
        self._run(build(self._video_encode_args()), "Overlay logo", True, lambda: build(self._fallback_cpu_encode_args()))

    def _overlay_watermark(self, video: Path, watermark: Path, out: Path, width: int, height: int) -> None:
        resolved = self._resolve_asset_path(str(watermark))
        if not resolved:
            self.log(f"⚠️ [Bỏ qua Watermark] Không tìm thấy watermark: {watermark}. Tiếp tục render video.")
            try:
                shutil.copy2(str(video), str(out))
            except Exception as e:
                self.log(f"Lỗi sao chép video tạm: {e}")
            return
        watermark = resolved
        opacity = min(1.0, max(0.0, float(self.settings.get("watermark_opacity", 0.2))))
        wm_scale = min(3.0, max(0.5, float(self.settings.get("watermark_scale", 1.0))))
        scaled_w = max(width, int(width * wm_scale))
        scaled_h = max(height, int(height * wm_scale))
        filter_complex = (
            f"[1:v]scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},format=rgba,colorchannelmixer=aa={opacity}[wm];"
            f"[0:v][wm]overlay=0:0:format=auto,format=yuv420p[v]"
        )
        def build(args: List[str]) -> List[str]:
            return [
                self.ffmpeg, "-y", "-i", str(video), "-i", str(watermark),
                "-filter_complex", filter_complex,
                "-map", "[v]", "-map", "0:a?",
            ] + args + ["-c:a", "copy", "-movflags", "+faststart", str(out)]
        self._run(build(self._video_encode_args()), "Overlay watermark", True, lambda: build(self._fallback_cpu_encode_args()))

    def _overlay_text(self, video: Path, out: Path) -> None:
        text_cfg = self.settings.get("text_overlay", {})
        content = str(text_cfg.get("content", "")).strip()
        font_size = int(text_cfg.get("font_size", 48))
        position = text_cfg.get("position", "bottom_center")
        margin_x = int(text_cfg.get("margin_x", 40))
        margin_y = int(text_cfg.get("margin_y", 80))
        font_color = self._normalize_ffmpeg_color(str(text_cfg.get("font_color", "#FFFFFF")))
        box_enabled = bool(text_cfg.get("box_enabled", True))
        box_opacity = float(text_cfg.get("box_opacity", 0.45))
        positions = {
            "top_left": f"x={margin_x}:y={margin_y}", "top_center": f"x=(w-text_w)/2:y={margin_y}",
            "top_right": f"x=w-text_w-{margin_x}:y={margin_y}", "center": "x=(w-text_w)/2:y=(h-text_h)/2",
            "bottom_left": f"x={margin_x}:y=h-text_h-{margin_y}", "bottom_center": f"x=(w-text_w)/2:y=h-text_h-{margin_y}",
            "bottom_right": f"x=w-text_w-{margin_x}:y=h-text_h-{margin_y}",
        }
        drawtext_parts = [f"text='{self._escape_drawtext(content)}'", f"fontsize={font_size}", f"fontcolor={font_color}", positions.get(position, positions["bottom_center"]), "line_spacing=8"]
        font_file = self._default_font_file()
        if font_file:
            drawtext_parts.append(f"fontfile='{self._escape_drawtext(font_file.as_posix())}'")
        if box_enabled:
            drawtext_parts += ["box=1", f"boxcolor=black@{box_opacity}", "boxborderw=18"]
        vf = "drawtext=" + ":".join(drawtext_parts)
        def build(args: List[str]) -> List[str]:
            return [
                self.ffmpeg, "-y", "-i", str(video), "-vf", vf,
                "-map", "0:v:0", "-map", "0:a?",
            ] + args + ["-c:a", "copy", "-movflags", "+faststart", str(out)]
        self._run(build(self._video_encode_args()), "Overlay text", True, lambda: build(self._fallback_cpu_encode_args()))

    @staticmethod
    def _normalize_ffmpeg_color(value: str) -> str:
        value = value.strip() or "#FFFFFF"
        if value.startswith("#") and len(value) in (4, 7):
            if len(value) == 4:
                value = "#" + "".join(ch * 2 for ch in value[1:])
            return "0x" + value[1:]
        return value

    @staticmethod
    def _escape_drawtext(text: str) -> str:
        # Chuẩn hóa nháy đơn, nháy kép sang typography an toàn tránh vỡ cú pháp FFmpeg Filtergraph:
        # ' -> ’ (right single quote / apostrophe: It's -> It’s)
        # " -> ” (right double quote)
        # ` -> ‘ (left single quote)
        safe = (
            str(text)
            .replace("'", "’")
            .replace('"', '”')
            .replace("`", "‘")
            .replace("\\", "\\\\")
            .replace(":", "\\:")
            .replace("%", "\\%")
        )
        return safe

    @staticmethod
    def _find_font_file_by_name(font_name: str, bold: bool = False, italic: bool = False) -> Path | None:
        if not font_name:
            return RenderEngine._default_font_file()

        font_clean = font_name.strip()
        font_clean_lower = font_clean.lower()
        win_fonts = Path("C:/Windows/Fonts")

        # 1. Tra cứu tự động từ Windows Font Registry (Chuẩn xác 100% cho mọi font chữ hệ thống & font cài thêm)
        try:
            import winreg

            reg_roots = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
            ]
            font_candidates: List[Tuple[str, Path]] = []
            for hkey, subkey in reg_roots:
                try:
                    with winreg.OpenKey(hkey, subkey) as key:
                        num_values = winreg.QueryInfoKey(key)[1]
                        for i in range(num_values):
                            val_name, val_data, _ = winreg.EnumValue(key, i)
                            clean_val = re.sub(r"\s*\((TrueType|OpenType|All type)\)", "", str(val_name), flags=re.IGNORECASE).strip().lower()
                            file_p = Path(str(val_data))
                            if not file_p.is_absolute():
                                file_p = win_fonts / val_data
                            if file_p.exists():
                                font_candidates.append((clean_val, file_p))
                except Exception:
                    pass

            target_style = font_clean_lower
            if bold and italic:
                target_style += " bold italic"
            elif bold:
                target_style += " bold"
            elif italic:
                target_style += " italic"

            # Tìm khớp chính xác tên + style
            for name, fpath in font_candidates:
                if name == target_style:
                    return fpath

            # Tìm khớp chính xác tên font
            for name, fpath in font_candidates:
                if name == font_clean_lower:
                    return fpath

            # Tìm chứa chuỗi tên font (khớp style)
            for name, fpath in font_candidates:
                if font_clean_lower in name:
                    if bold and "bold" in name:
                        return fpath
                    elif italic and "italic" in name:
                        return fpath
                    elif not bold and not italic and "bold" not in name and "italic" not in name:
                        return fpath

            for name, fpath in font_candidates:
                if font_clean_lower in name:
                    return fpath
        except Exception:
            pass

        # 2. Bảng mapping mở rộng cho các font phổ biến
        if win_fonts.exists():
            mapping = {
                "arial": "arialbd.ttf" if bold else ("ariali.ttf" if italic else "arial.ttf"),
                "times new roman": "timesbd.ttf" if bold else ("timesi.ttf" if italic else "times.ttf"),
                "tahoma": "tahomabd.ttf" if bold else "tahoma.ttf",
                "segoe ui": "segoeuib.ttf" if bold else ("segoeuii.ttf" if italic else "segoeui.ttf"),
                "segoe script": "segoescb.ttf" if bold else "segoesc.ttf",
                "brush script mt": "BRUSHSCI.TTF",
                "brush script": "BRUSHSCI.TTF",
                "calibri": "calibrib.ttf" if bold else ("calibrii.ttf" if italic else "calibri.ttf"),
                "consolas": "consolab.ttf" if bold else ("consolai.ttf" if italic else "consola.ttf"),
                "comic sans ms": "comicbd.ttf" if bold else "comic.ttf",
                "verdana": "verdanab.ttf" if bold else ("verdanai.ttf" if italic else "verdana.ttf"),
                "georgia": "georgiab.ttf" if bold else ("georgiai.ttf" if italic else "georgia.ttf"),
                "impact": "impact.ttf",
                "trebuchet ms": "trebucbd.ttf" if bold else "trebuc.ttf",
                "monotype corsiva": "MTCORSVA.TTF",
                "lucida handwriting": "LHANDW.TTF",
                "chiller": "CHILLER.TTF",
                "freestyle script": "FREESCPT.TTF",
                "kristen itc": "ITCKRIST.TTF",
                "mistral": "MISTRAL.TTF",
                "papyrus": "PAPYRUS.TTF",
            }
            if font_clean_lower in mapping:
                f_path = win_fonts / mapping[font_clean_lower]
                if f_path.exists():
                    return f_path

            # 3. Quét trực tiếp file stem trong C:/Windows/Fonts
            for f in win_fonts.glob("*.ttf"):
                if font_clean_lower in f.stem.lower():
                    return f
            for f in win_fonts.glob("*.otf"):
                if font_clean_lower in f.stem.lower():
                    return f

        # 4. Quét thư mục assets/fonts của ứng dụng nếu có
        try:
            from .paths import APP_ROOT
            app_fonts = APP_ROOT / "assets" / "fonts"
            if app_fonts.exists():
                for f in app_fonts.glob("*.*"):
                    if f.suffix.lower() in {".ttf", ".otf"} and font_clean_lower in f.stem.lower():
                        return f
        except Exception:
            pass

        return RenderEngine._default_font_file()

    @staticmethod
    def _default_font_file() -> Path | None:
        candidates = [Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/Arial.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
        for path in candidates:
            if path.exists():
                return path
        return None

    @staticmethod
    def _clean_title_text(text: str) -> str:
        """Làm sạch các ký tự unicode đặc biệt / ô vuông lỗi thường gặp trong tiêu đề YouTube."""
        if not text:
            return ""
        s = (
            str(text)
            .replace("\uff5c", "|")  # ｜
            .replace("\uff1a", ":")  # ：
            .replace("\uff0f", "/")  # ／
            .replace("\u25a1", "")   # ▯
            .replace("\ufffd", "")   # replacement char
            .replace("\u200b", "")   # zero-width space
            .replace("\ufeff", "")   # BOM
        )
        return s.strip()

    @classmethod
    def _wrap_text_for_box(
        cls,
        text: str,
        font_file: Path | None,
        font_size: int,
        max_w: int,
        max_h: int,
        line_spacing: int = 4,
        min_font_size: int = 16,
        max_lines: int = 2,
    ) -> tuple[str, int]:
        """
        Tự động ngắt dòng theo ranh giới từ (không xé đôi từ, không ngắt ở dấu gạch nối)
        và tự động co nhỏ font_size sao cho tiêu đề nằm vừa vặn hoàn hảo trong tối đa `max_lines` dòng (mặc định 2 dòng)
        và không vượt quá chiều rộng/chiều cao của Bounding Box (tính chính xác Line Height, Ascent, Descent, Line Spacing).
        """
        from PIL import ImageFont, ImageDraw, Image

        clean_text = cls._clean_title_text(text)
        if not clean_text:
            return "", font_size

        avail_w = max(40, int(max_w * 0.94))
        avail_h = max(24, int(max_h * 0.90))

        cur_font_size = int(font_size)
        dummy_img = Image.new("RGB", (1, 1))
        draw = ImageDraw.Draw(dummy_img)

        best_lines = [clean_text]
        best_size = cur_font_size

        while cur_font_size >= min_font_size:
            font = None
            try:
                if font_file and font_file.exists():
                    font = ImageFont.truetype(str(font_file), cur_font_size)
                else:
                    font = ImageFont.load_default()
            except Exception:
                font = None

            def get_w(s: str) -> int:
                if not s:
                    return 0
                if font and hasattr(draw, "textbbox"):
                    bbox = draw.textbbox((0, 0), s, font=font)
                    return bbox[2] - bbox[0]
                elif font and hasattr(font, "getlength"):
                    return int(font.getlength(s))
                else:
                    return int(len(s) * cur_font_size * 0.55)

            def get_line_h() -> int:
                if font and hasattr(font, "getmetrics"):
                    ascent, descent = font.getmetrics()
                    return ascent + descent
                if font and hasattr(draw, "textbbox"):
                    bbox = draw.textbbox((0, 0), "ÁyTgjpqQ|", font=font)
                    return bbox[3] - bbox[1]
                return int(cur_font_size * 1.25)

            # Ngắt dòng theo từ ngữ nguyên vẹn (Word Wrapping chuẩn xác từng pixel)
            words = clean_text.split()
            raw_lines: List[str] = []
            cur_line = ""

            for w in words:
                test_line = f"{cur_line} {w}".strip() if cur_line else w
                if get_w(test_line) <= avail_w:
                    cur_line = test_line
                else:
                    if cur_line:
                        raw_lines.append(cur_line)
                    cur_line = w
            if cur_line:
                raw_lines.append(cur_line)

            # Dọn dẹp ký tự ngăn cách ở đầu/cuối dòng (chống rớt dấu |, -, :, ;, /, \ xuống đầu dòng mới)
            lines: List[str] = []
            for idx, l in enumerate(raw_lines):
                l_clean = l.strip()
                if idx > 0:
                    l_clean = re.sub(r"^[\|\-:\;/\\]+\s*", "", l_clean).strip()
                l_clean = re.sub(r"\s*[\|\-:\;/\\]+$", "", l_clean).strip()
                if l_clean:
                    lines.append(l_clean)

            line_h = get_line_h()
            # Bù trừ line_spacing cho font lớn để 2 dòng ôm sát nhau chuẩn poster
            eff_spacing = line_spacing
            if cur_font_size >= 60:
                eff_spacing = line_spacing - int(cur_font_size * 0.20)
            elif cur_font_size >= 35:
                eff_spacing = line_spacing - int(cur_font_size * 0.10)

            total_h = len(lines) * line_h + (len(lines) - 1) * eff_spacing
            max_line_w = max((get_w(l) for l in lines), default=0)

            # Điều kiện đạt chuẩn: Không vượt quá max_lines (2 dòng), không tràn chiều rộng, không tràn chiều cao
            if len(lines) <= max_lines and max_line_w <= avail_w and total_h <= avail_h:
                return "\n".join(lines), cur_font_size

            best_lines = lines if lines else raw_lines
            best_size = cur_font_size
            cur_font_size -= 2

        return "\n".join(best_lines), best_size
