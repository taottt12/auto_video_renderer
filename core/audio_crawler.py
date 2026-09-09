from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yt_dlp

from .paths import find_binary
from .process_utils import run_hidden

LogCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int, str], None]  # current, total, status_text


def sanitize_filename(name: str) -> str:
    """Loại bỏ ký tự không hợp lệ cho tên file trên Windows."""
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:180] or "audio"


def get_ffmpeg_dir() -> str:
    try:
        binary = find_binary("ffmpeg.exe")
    except Exception:
        binary = find_binary("ffmpeg")
    return str(Path(binary).parent)


def normalize_channel_url(url: str) -> str:
    """Đảm bảo URL kênh trỏ đúng vào tab /videos để lấy danh sách video upload."""
    url = url.strip()
    if not url:
        return ""
    if "@" in url and not any(sub in url for sub in ["/videos", "/shorts", "/streams", "/playlists"]):
        url = url.rstrip("/") + "/videos"
    return url


def filter_by_date(
    entries: List[Dict[str, Any]],
    date_filter: str,
    date_from: str = "",
    date_to: str = "",
) -> List[Dict[str, Any]]:
    """Lọc danh sách video theo thời gian upload (YYYYMMDD)."""
    if date_filter == "all" or not date_filter:
        return entries

    today = datetime.now()
    cutoff_str = ""

    if date_filter == "7d":
        cutoff_str = (today - timedelta(days=7)).strftime("%Y%m%d")
    elif date_filter == "30d":
        cutoff_str = (today - timedelta(days=30)).strftime("%Y%m%d")
    elif date_filter == "90d":
        cutoff_str = (today - timedelta(days=90)).strftime("%Y%m%d")
    elif date_filter == "365d":
        cutoff_str = (today - timedelta(days=365)).strftime("%Y%m%d")
    elif date_filter == "custom":
        from_str = date_from.replace("-", "") if date_from else "19700101"
        to_str = date_to.replace("-", "") if date_to else "20991231"
        filtered = []
        for e in entries:
            d = str(e.get("upload_date") or "").strip()
            # Nếu yt-dlp flat không lấy được upload_date thì vẫn giữ lại để tải
            if not d or (from_str <= d <= to_str):
                filtered.append(e)
        return filtered

    if cutoff_str:
        filtered = []
        for e in entries:
            d = str(e.get("upload_date") or "").strip()
            if not d or d >= cutoff_str:
                filtered.append(e)
        return filtered

    return entries


def extract_entry_list(
    url: str,
    limit: int = 0,
    order: str = "newest_first",
    date_filter: str = "all",
    date_from: str = "",
    date_to: str = "",
    log: LogCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> List[Dict[str, Any]]:
    """Duyệt nhanh danh sách video từ Playlist hoặc Channel bằng flat-playlist và lọc video bị chặn/hội viên."""
    _log = log or (lambda msg: None)
    _log(f"Đang quét danh sách video từ: {url}")

    ffmpeg_dir = get_ffmpeg_dir()
    ydl_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "ffmpeg_location": ffmpeg_dir,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        if cancel_event and cancel_event.is_set():
            return []
        info = ydl.extract_info(url, download=False)
        if not info:
            return []

    entries: List[Dict[str, Any]] = []
    if "entries" in info and info["entries"]:
        entries = [e for e in info["entries"] if e and isinstance(e, dict)]
    else:
        entries = [info]

    _log(f"Đã tìm thấy {len(entries)} video thô từ nguồn.")

    # 1. Lọc video bị khóa hội viên (members-only), gói thành viên, video riêng tư hoặc chưa công chiếu
    valid_entries: List[Dict[str, Any]] = []
    blocked_count = 0
    blocked_keywords = ["chỉ dành cho hội viên", "dành cho hội viên", "members only", "gói thành viên", "[hội viên]", "(hội viên)"]

    for item in entries:
        title = str(item.get("title") or "").strip()
        title_lower = title.lower()

        availability = str(item.get("availability") or "").lower()
        live_status = str(item.get("live_status") or "").lower()

        # Kiểm tra điều kiện bị khóa
        is_blocked = (
            availability in {"subscriber_only", "premium_only", "needs_auth", "private"}
            or live_status in {"is_upcoming", "is_live"}
            or any(kw in title_lower for kw in blocked_keywords)
        )

        if is_blocked:
            blocked_count += 1
            continue
        valid_entries.append(item)

    if blocked_count > 0:
        _log(f"🛡 Đã tự động loại bỏ {blocked_count} video bị khóa hội viên/chưa phát hành.")

    # 2. Lọc ngày
    valid_entries = filter_by_date(valid_entries, date_filter, date_from, date_to)

    # 3. Sắp xếp theo thứ tự
    if order == "oldest_first":
        valid_entries = list(reversed(valid_entries))

    # 4. Giới hạn số lượng
    if limit > 0:
        valid_entries = valid_entries[:limit]

    result: List[Dict[str, Any]] = []
    for item in valid_entries:
        vid_id = item.get("id") or ""
        title = item.get("title") or vid_id or "audio"
        item_url = item.get("url") or item.get("webpage_url") or ""
        if vid_id and not item_url.startswith("http"):
            item_url = f"https://www.youtube.com/watch?v={vid_id}"
        if item_url:
            dur_sec = item.get("duration")
            if isinstance(dur_sec, (int, float)) and dur_sec > 0:
                m, s = divmod(int(dur_sec), 60)
                h, m = divmod(m, 60)
                dur_str = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
            else:
                dur_str = "--:--"
            result.append({
                "id": vid_id,
                "title": title,
                "url": item_url,
                "duration": dur_sec or 0,
                "duration_str": dur_str,
                "upload_date": item.get("upload_date") or "",
            })

    _log(f"Sau khi lọc: {len(result)} video hợp lệ sẵn sàng để cào MP3.")
    return result


def download_single_audio(
    url: str,
    save_folder: str | Path,
    title_hint: str = "",
    log: LogCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> Optional[str]:
    """Tải và chuyển đổi 1 video sang MP3."""
    _log = log or (lambda msg: None)
    save_dir = Path(save_folder)
    save_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_dir = get_ffmpeg_dir()

    downloaded_paths: List[str] = []
    last_log_time = [0.0]

    def post_hook(d: Dict[str, Any]) -> None:
        if d.get("status") == "finished":
            info_dict = d.get("info_dict") or {}
            fpath = info_dict.get("filepath") or d.get("filepath")
            if fpath and str(fpath).lower().endswith(".mp3") and os.path.exists(fpath):
                downloaded_paths.append(str(fpath))

    def progress_hook(d: Dict[str, Any]) -> None:
        if cancel_event and cancel_event.is_set():
            raise Exception("Đã dừng tác vụ bởi người dùng.")
        if d.get("status") == "downloading":
            now = time.time()
            if now - last_log_time[0] >= 1.2:
                last_log_time[0] = now
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                speed = d.get("speed") or 0
                eta = d.get("eta") or 0
                pct = f"{(downloaded / total * 100):.1f}%" if total > 0 else ""
                spd = f"{speed / (1024 * 1024):.2f} MB/s" if speed else ""
                eta_s = f"ETA {int(eta)}s" if eta else ""
                parts = [p for p in [pct, spd, eta_s] if p]
                if parts:
                    _log(f"   ↳ [Đang tải] {' | '.join(parts)}")

    class YtLogger:
        def debug(self, msg: str) -> None:
            clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", msg).strip()
            if any(k in clean for k in ["[ExtractAudio]", "Destination:", "Deleting original", "has already been downloaded"]):
                _log(f"   ↳ {clean}")

        def info(self, msg: str) -> None:
            clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", msg).strip()
            if clean and not clean.startswith("[download]"):
                _log(f"   ↳ {clean}")

        def warning(self, msg: str) -> None:
            clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", msg).strip()
            if "No supported JavaScript runtime" in clean:
                return
            if clean:
                _log(f"   ⚠ [Cảnh báo] {clean}")

        def error(self, msg: str) -> None:
            clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", msg).strip()
            if clean:
                _log(f"   ❌ [Lỗi] {clean}")

    out_template = str(save_dir / "%(title)s.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "outtmpl": out_template,
        "ffmpeg_location": ffmpeg_dir,
        "quiet": False,
        "no_warnings": False,
        "ignoreerrors": False,
        "logger": YtLogger(),
        "postprocessor_hooks": [post_hook],
        "progress_hooks": [progress_hook],
    }

    if cancel_event and cancel_event.is_set():
        return None

    info = None
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        if cancel_event and cancel_event.is_set():
            _log("Đã dừng tải theo yêu cầu người dùng.")
        else:
            _log(f"❌ Lỗi tải: {exc}")
        return None

    # 1. Kiểm tra từ post_hook
    if downloaded_paths and os.path.exists(downloaded_paths[-1]):
        return downloaded_paths[-1]

    # 2. Kiểm tra từ info['requested_downloads']
    if isinstance(info, dict):
        for rd in (info.get("requested_downloads") or []):
            rf = rd.get("filepath")
            if rf and os.path.exists(rf) and str(rf).lower().endswith(".mp3"):
                return str(rf)

        # Kiểm tra info.filepath
        info_f = info.get("filepath")
        if info_f and os.path.exists(info_f) and str(info_f).lower().endswith(".mp3"):
            return str(info_f)

        # 3. Tính tên file chuẩn từ ydl.prepare_filename
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                prep = ydl.prepare_filename(info)
                prep_mp3 = Path(prep).with_suffix(".mp3")
                if prep_mp3.exists():
                    return str(prep_mp3)
        except Exception:
            pass

    # 4. Tìm theo title hint
    target_title = ""
    if isinstance(info, dict):
        target_title = info.get("title") or ""
    if not target_title and title_hint:
        target_title = title_hint

    if target_title:
        safe_hint = sanitize_filename(target_title)
        candidates = list(save_dir.glob(f"*{safe_hint[:25]}*.mp3"))
        if candidates:
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return str(candidates[0])

    # 5. Fallback: file mp3 mới sinh ra trong thư mục trong 3 phút gần nhất
    all_mp3s = list(save_dir.glob("*.mp3"))
    if all_mp3s:
        all_mp3s.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        newest = all_mp3s[0]
        if time.time() - newest.stat().st_mtime < 180:
            return str(newest)

    return None


def parse_time_str(t_str: str) -> float:
    """Parse time string like '00:00:10', '00:10', '10.5', '10' into seconds (float)."""
    t_str = str(t_str or "").strip()
    if not t_str:
        return 0.0
    parts = t_str.split(":")
    try:
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        else:
            return float(parts[0])
    except Exception:
        return 0.0


def trim_audio_file(
    mp3_path: str,
    trim_cfg: Dict[str, Any] | None,
    log: LogCallback | None = None,
) -> str:
    """Cắt file audio sau khi tải về theo cấu hình trim_cfg."""
    if not trim_cfg or not trim_cfg.get("enabled"):
        return mp3_path

    _log = log or (lambda msg: None)
    if not os.path.exists(mp3_path):
        return mp3_path

    start_str = str(trim_cfg.get("start_time") or "").strip()
    end_str = str(trim_cfg.get("end_time") or "").strip()
    mode = str(trim_cfg.get("mode") or "remove_segment")

    start_sec = parse_time_str(start_str)
    end_sec = parse_time_str(end_str)

    if start_sec <= 0 and end_sec <= 0:
        return mp3_path

    try:
        ffmpeg_bin = find_binary("ffmpeg.exe")
    except Exception:
        ffmpeg_bin = find_binary("ffmpeg")

    src_p = Path(mp3_path)
    tmp_p = src_p.with_name(f"trim_{src_p.stem}_{int(time.time() * 1000)}.mp3")

    _log(f"✂ [Cắt audio] Đang xử lý '{src_p.name}' ({'Bỏ đoạn' if mode == 'remove_segment' else 'Chỉ giữ đoạn'}: {start_str or '00:00:00'} ➔ {end_str or 'Hết'})...")

    cmd: List[str] = []
    if mode == "remove_segment":
        # Cắt bỏ đoạn [start_sec -> end_sec]
        if start_sec <= 0.05 and end_sec > 0:
            # Bỏ đoạn đầu: từ 00:00 đến end_sec => Lấy từ end_sec đến hết
            cmd = [ffmpeg_bin, "-y", "-ss", str(end_sec), "-i", str(src_p), "-c", "copy", str(tmp_p)]
        elif start_sec > 0 and end_sec > start_sec:
            # Bỏ đoạn giữa: ghép đoạn 1 (0 -> start) và đoạn 2 (end -> hết)
            cmd = [
                ffmpeg_bin, "-y", "-i", str(src_p),
                "-filter_complex",
                f"[0:a]atrim=0:{start_sec},asetpts=PTS-STARTPTS[a1];[0:a]atrim=start={end_sec},asetpts=PTS-STARTPTS[a2];[a1][a2]concat=n=2:v=0:a=1[aout]",
                "-map", "[aout]", "-c:a", "libmp3lame", "-q:a", "2",
                str(tmp_p)
            ]
        elif start_sec > 0 and end_sec <= 0:
            # Bỏ từ start_sec tới hết => Giữ từ 0 đến start_sec
            cmd = [ffmpeg_bin, "-y", "-to", str(start_sec), "-i", str(src_p), "-c", "copy", str(tmp_p)]
        else:
            return mp3_path
    else:
        # keep_segment: Chỉ lấy đoạn từ start_sec đến end_sec
        cmd = [ffmpeg_bin, "-y"]
        if start_sec > 0:
            cmd.extend(["-ss", str(start_sec)])
        cmd.extend(["-i", str(src_p)])
        if end_sec > start_sec:
            cmd.extend(["-t", str(end_sec - start_sec)])
        cmd.extend(["-c", "copy", str(tmp_p)])

    res = run_hidden(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    # Fallback to re-encode if stream copy created an invalid file
    if not tmp_p.exists() or tmp_p.stat().st_size < 1024:
        if "-c" in cmd and "copy" in cmd:
            cmd_reencode: List[str] = []
            idx = 0
            while idx < len(cmd):
                if cmd[idx] == "-c" and idx + 1 < len(cmd) and cmd[idx + 1] == "copy":
                    cmd_reencode.extend(["-c:a", "libmp3lame", "-q:a", "2"])
                    idx += 2
                else:
                    cmd_reencode.append(cmd[idx])
                    idx += 1
            run_hidden(cmd_reencode, capture_output=True, text=True, encoding="utf-8", errors="ignore")

    if tmp_p.exists() and tmp_p.stat().st_size >= 1024:
        try:
            src_p.unlink(missing_ok=True)
            tmp_p.rename(src_p)
            _log(f"✂ [Cắt audio] Cắt thành công: {src_p.name} ({round(src_p.stat().st_size / 1024, 1)} KB)")
            return str(src_p)
        except Exception as exc:
            _log(f"⚠ Lỗi lưu file đã cắt: {exc}")
            if tmp_p.exists():
                return str(tmp_p)
    else:
        err_hint = res.stderr.strip().splitlines()[-1] if res.stderr else "Lỗi không xác định"
        _log(f"⚠ Cắt audio không thành công ({err_hint}), giữ lại file gốc.")
        if tmp_p.exists():
            try:
                tmp_p.unlink(missing_ok=True)
            except Exception:
                pass
    return mp3_path


def run_crawler(
    crawler_cfg: Dict[str, Any],
    log: LogCallback | None = None,
    progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
    on_file_downloaded: Callable[[str], None] | None = None,
) -> List[str]:
    """Hàm chính điều phối toàn bộ tác vụ cào MP3."""
    _log = log or (lambda msg: None)
    _progress = progress or (lambda cur, tot, txt: None)
    _cancel = cancel_event or threading.Event()

    save_folder = str(crawler_cfg.get("save_folder") or "").strip()
    if not save_folder:
        raise ValueError("Chưa chọn thư mục lưu file MP3.")

    Path(save_folder).mkdir(parents=True, exist_ok=True)
    mode = str(crawler_cfg.get("mode") or "video")

    targets: List[Dict[str, str]] = []

    if crawler_cfg.get("selected_targets"):
        targets = list(crawler_cfg["selected_targets"])
        _log(f"Sử dụng danh sách {len(targets)} video đã chọn trước đó.")
    elif mode == "video":
        raw_text = str(crawler_cfg.get("video_urls") or "")
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        for line in lines:
            targets.append({"url": line, "title": "", "id": ""})
        _log(f"Chế độ cào Video: tìm thấy {len(targets)} link hợp lệ.")

    elif mode == "playlist":
        playlist_url = str(crawler_cfg.get("playlist_url") or "").strip()
        if not playlist_url:
            raise ValueError("Chưa nhập URL Danh sách phát (Playlist).")
        limit = int(crawler_cfg.get("playlist_limit") or 0)
        targets = extract_entry_list(
            url=playlist_url,
            limit=limit,
            log=_log,
            cancel_event=_cancel,
        )

    elif mode == "channel":
        channel_url = str(crawler_cfg.get("channel_url") or "").strip()
        if not channel_url:
            raise ValueError("Chưa nhập URL Kênh (Channel).")
        channel_url = normalize_channel_url(channel_url)
        limit = int(crawler_cfg.get("channel_limit") or 0)
        order = str(crawler_cfg.get("channel_order") or "newest_first")
        date_filter = str(crawler_cfg.get("channel_date_filter") or "all")
        date_from = str(crawler_cfg.get("channel_date_from") or "")
        date_to = str(crawler_cfg.get("channel_date_to") or "")

        targets = extract_entry_list(
            url=channel_url,
            limit=limit,
            order=order,
            date_filter=date_filter,
            date_from=date_from,
            date_to=date_to,
            log=_log,
            cancel_event=_cancel,
        )

    total = len(targets)
    if total == 0:
        _log("Không có video nào để cào MP3.")
        return []

    _log(f"Bắt đầu tải {total} file MP3 vào thư mục: {save_folder}")
    downloaded_files: List[str] = []

    for index, item in enumerate(targets):
        if _cancel.is_set():
            _log("Đã dừng quá trình cào MP3 theo yêu cầu.")
            break

        title = item.get("title") or item.get("url") or f"Item {index + 1}"
        _progress(index + 1, total, f"Đang cào ({index + 1}/{total}): {title[:40]}...")
        _log(f"[{index + 1}/{total}] Đang tải: {title}")

        mp3_path = download_single_audio(
            url=item["url"],
            save_folder=save_folder,
            title_hint=item.get("title", ""),
            log=_log,
            cancel_event=_cancel,
        )

        if mp3_path and os.path.exists(mp3_path):
            trim_cfg = crawler_cfg.get("audio_trim")
            if trim_cfg and trim_cfg.get("enabled"):
                mp3_path = trim_audio_file(mp3_path, trim_cfg, _log)

            downloaded_files.append(mp3_path)
            _log(f"➔ Đã cào thành công: {os.path.basename(mp3_path)}")
            if on_file_downloaded:
                on_file_downloaded(mp3_path)
        else:
            _log(f"⚠ Tải thất bại hoặc bị bỏ qua: {item['url']}")

    _progress(total, total, f"Hoàn thành! Đã cào thành công {len(downloaded_files)}/{total} file.")
    _log(f"Hoàn tất quá trình cào MP3. Đã tải {len(downloaded_files)}/{total} file thành công.")
    return downloaded_files
