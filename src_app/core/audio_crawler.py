from __future__ import annotations

import json
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


def json_cookies_to_netscape_content(data: list) -> str:
    """Chuyển đổi danh sách Cookie JSON (như từ Cookie-Editor) sang định dạng Netscape chuẩn."""
    lines = ["# Netscape HTTP Cookie File", "# https://curl.haxx.se/rfc/cookie_spec.html", ""]
    for c in data:
        if not isinstance(c, dict):
            continue
        domain = str(c.get("domain") or "").strip()
        if not domain:
            domain = ".youtube.com"
        include_sub = "TRUE" if domain.startswith(".") else "FALSE"
        path = str(c.get("path") or "/").strip()
        secure = "TRUE" if c.get("secure", True) else "FALSE"
        exp_val = c.get("expirationDate") or c.get("expiry") or (time.time() + 365 * 86400)
        try:
            expiry = str(int(float(exp_val)))
        except Exception:
            expiry = str(int(time.time() + 365 * 86400))
        name = str(c.get("name") or "").strip()
        value = str(c.get("value") or "").strip()
        if name:
            lines.append(f"{domain}\t{include_sub}\t{path}\t{secure}\t{expiry}\t{name}\t{value}")
    return "\n".join(lines) + "\n"


def extract_cookies_from_any_source(source: str) -> Tuple[List[Dict[str, Any]], str]:
    """
    Trích xuất danh sách cookie dict từ bất kỳ nguồn nào:
    - File path (.json, .txt, .cookies)
    - JSON chuẩn từ Cookie-Editor
    - JSON bị lỗi cú pháp / dán dở / thiếu ngoặc (tự phục hồi bằng Regex)
    - Netscape format (.txt)
    - Header string (SID=...; HSID=...)
    Trả về: (danh_sách_cookie, tên_định_dạng)
    """
    if not source:
        return [], "empty"
    source = str(source).strip()
    if not source:
        return [], "empty"

    # 1. Nếu là đường dẫn file
    if os.path.exists(source) and os.path.isfile(source):
        try:
            with open(source, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read().strip()
            cookies, _ = extract_cookies_from_any_source(content)
            return cookies, f"File ({Path(source).name})"
        except Exception:
            pass

    # 2. Thử parse JSON chuẩn
    try:
        parsed = json.loads(source)
        raw_list = []
        if isinstance(parsed, list):
            raw_list = parsed
        elif isinstance(parsed, dict):
            if "cookies" in parsed and isinstance(parsed["cookies"], list):
                raw_list = parsed["cookies"]
            elif "name" in parsed and "value" in parsed:
                raw_list = [parsed]

        if raw_list:
            clean_list = []
            for item in raw_list:
                if isinstance(item, dict) and item.get("name") and item.get("value"):
                    clean_list.append({
                        "name": str(item["name"]).strip(),
                        "value": str(item["value"]).strip(),
                        "domain": str(item.get("domain") or ".youtube.com").strip(),
                        "path": str(item.get("path") or "/").strip(),
                        "secure": bool(item.get("secure", True)),
                        "expirationDate": float(item.get("expirationDate") or item.get("expiry") or (time.time() + 365 * 86400)),
                    })
            if clean_list:
                return clean_list, "JSON (Cookie-Editor)"
    except Exception:
        pass

    # 3. Thử Regex khôi phục JSON bị lỗi cú pháp / dán dở / thiếu dấu ngoặc
    if "{" in source or "}" in source or '"name"' in source or '"value"' in source:
        recovered = []
        obj_matches = re.findall(r'\{[^{}]*\}', source)
        for obj_str in obj_matches:
            name_m = re.search(r'"name"\s*:\s*"([^"]+)"', obj_str)
            val_m = re.search(r'"value"\s*:\s*"([^"]+)"', obj_str)
            if name_m and val_m:
                dom_m = re.search(r'"domain"\s*:\s*"([^"]+)"', obj_str)
                exp_m = re.search(r'"(?:expirationDate|expiry)"\s*:\s*([0-9.]+)', obj_str)
                dom = dom_m.group(1).strip() if dom_m else ".youtube.com"
                exp = float(exp_m.group(1)) if exp_m else (time.time() + 365 * 86400)
                recovered.append({
                    "name": name_m.group(1).strip(),
                    "value": val_m.group(1).strip(),
                    "domain": dom,
                    "path": "/",
                    "secure": True,
                    "expirationDate": exp,
                })
        if recovered:
            return recovered, "JSON (Tự động sửa lỗi cú pháp)"

    # 4. Netscape format (chứa tab hoặc dòng comment Netscape)
    if "\t" in source or "# Netscape" in source or ".youtube.com" in source:
        netscape_cookies = []
        for line in source.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                domain, _, path, secure, exp_str, name, val = parts[:7]
                try:
                    exp = float(exp_str)
                except Exception:
                    exp = time.time() + 365 * 86400
                netscape_cookies.append({
                    "name": name.strip(),
                    "value": val.strip(),
                    "domain": domain.strip() or ".youtube.com",
                    "path": path.strip() or "/",
                    "secure": secure.upper() == "TRUE",
                    "expirationDate": exp,
                })
            elif len(parts) >= 2:
                netscape_cookies.append({
                    "name": parts[0].strip(),
                    "value": parts[1].strip(),
                    "domain": ".youtube.com",
                    "path": "/",
                    "secure": True,
                    "expirationDate": time.time() + 365 * 86400,
                })
        if netscape_cookies:
            return netscape_cookies, "Netscape (cookies.txt)"

    # 5. Header format (key=value; key2=value2)
    if "=" in source:
        header_cookies = []
        pairs = source.split(";")
        for p in pairs:
            if "=" in p:
                k, v = p.strip().split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and v:
                    header_cookies.append({
                        "name": k,
                        "value": v,
                        "domain": ".youtube.com",
                        "path": "/",
                        "secure": True,
                        "expirationDate": time.time() + 365 * 86400,
                    })
        if header_cookies:
            return header_cookies, "Header (SID=...; HSID=...)"

    return [], "Không xác định"


def validate_and_inspect_cookie(source: str) -> Dict[str, Any]:
    """
    Phân tích toàn diện nguồn Cookie (chuỗi dán hoặc file path):
    - Định dạng phát hiện
    - Tình trạng các trường bảo mật cốt lõi của YouTube
    - Thời hạn sử dụng (số ngày còn lại, ngày hết hạn cụ thể)
    - Đánh giá trạng thái: success (🟢), warning (🟡), error (🔴)
    """
    cookies, fmt = extract_cookies_from_any_source(source)
    if not cookies:
        return {
            "valid": False,
            "status_level": "error",
            "format": fmt,
            "total_cookies": 0,
            "days_remaining": 0,
            "expiry_date_str": "N/A",
            "is_expired": True,
            "has_auth": False,
            "core_keys": {},
            "summary": "Không nhận diện được Cookie hợp lệ trong nội dung đã nhập.",
            "recommendation": "Hãy dán Cookie từ Cookie-Editor (Export as Netscape hoặc JSON) hoặc chọn file cookies.txt.",
        }

    now = time.time()
    core_keys_check = {
        "LOGIN_INFO": False,
        "__Secure-1PSID": False,
        "__Secure-3PSID": False,
        "SID": False,
        "HSID": False,
        "SSID": False,
        "SAPISID": False,
        "PREF": False,
    }

    expiries = []
    for c in cookies:
        name = c["name"]
        if name in core_keys_check:
            core_keys_check[name] = True
        exp = c.get("expirationDate")
        if exp and isinstance(exp, (int, float)) and exp > 0:
            expiries.append(exp)

    min_exp = min(expiries) if expiries else (now + 365 * 86400)
    is_expired = min_exp < now
    seconds_left = max(0, min_exp - now)
    days_remaining = int(seconds_left // 86400)

    try:
        expiry_dt = datetime.fromtimestamp(min_exp)
        expiry_date_str = expiry_dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        expiry_date_str = "Không giới hạn"

    has_strong_auth = core_keys_check["LOGIN_INFO"] or core_keys_check["__Secure-1PSID"] or core_keys_check["SID"]

    if is_expired:
        status_level = "error"
        days_ago = abs(int((now - min_exp) // 86400))
        summary = f"Cookie đã hết hạn từ ngày {expiry_date_str}! (Hết hạn {days_ago} ngày trước)"
        rec = "Cookie này không còn hiệu lực. Hãy mở lại trình duyệt Chrome và xuất file Cookie mới nhất."
    elif not has_strong_auth:
        status_level = "warning"
        summary = f"Cookie nhận diện được ({len(cookies)} mục), nhưng thiếu trường đăng nhập chính (LOGIN_INFO / SID)."
        rec = "Nên đăng nhập tài khoản YouTube trên trình duyệt trước khi xuất Cookie để có đủ quyền vượt chặn Bot."
    else:
        status_level = "success"
        summary = f"Cookie hoạt động tốt! Còn hạn {days_remaining} ngày (Hết hạn: {expiry_date_str})."
        rec = "Cookie có đầy đủ mã xác thực tài khoản YouTube. Sẵn sàng cào nhạc vượt mọi giới hạn Bot!"

    return {
        "valid": True,
        "status_level": status_level,
        "format": fmt,
        "total_cookies": len(cookies),
        "days_remaining": days_remaining,
        "expiry_date_str": expiry_date_str,
        "is_expired": is_expired,
        "has_auth": has_strong_auth,
        "core_keys": core_keys_check,
        "summary": summary,
        "recommendation": rec,
        "cookies": cookies,
    }


def parse_raw_cookie_data(raw_data: Any) -> Optional[List[Dict[str, Any]]]:
    """Trích xuất mảng cookie từ bất kỳ cấu trúc JSON nào (list hoặc dict với key 'cookies')."""
    if isinstance(raw_data, dict):
        if "cookies" in raw_data and isinstance(raw_data["cookies"], list):
            return raw_data["cookies"]
        elif "name" in raw_data and "value" in raw_data:
            return [raw_data]
        return None
    elif isinstance(raw_data, list):
        return raw_data
    return None


def get_node_runtime() -> Optional[Dict[str, Any]]:
    """Tự động tìm kiếm Node.js nhúng hoặc Node.js trên hệ thống để giải mã YouTube n-challenge."""
    from .paths import TOOLS_DIR, APP_ROOT
    embedded_candidates = [
        TOOLS_DIR / "js" / "node.exe",
        TOOLS_DIR / "nodejs" / "node.exe",
        TOOLS_DIR / "node.exe",
        APP_ROOT / "tools" / "js" / "node.exe",
    ]
    for c in embedded_candidates:
        if c.exists() and os.path.isfile(c):
            return {"node": {"path": str(c.resolve())}}

    candidates = [
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
        r"D:\laragon\bin\nodejs\node-v22\node.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return {"node": {"path": c}}
    try:
        import shutil
        node_p = shutil.which("node")
        if node_p and os.path.exists(node_p):
            return {"node": {"path": node_p}}
    except Exception:
        pass
    return None


def json_cookies_to_netscape_content(cookies: List[Dict[str, Any]]) -> str:
    """Chuyển đổi danh sách cookie sang định dạng file Netscape chuẩn, lọc các trường timestamp volatile."""
    lines = [
        "# Netscape HTTP Cookie File",
        "# https://curl.se/docs/http-cookies.html",
        "# This file was generated by AutoVideoRenderer.",
        "",
    ]
    # Lọc bỏ các token thời gian ngắn hạn dễ gây lệch phiên (Session Desync -> 'The page needs to be reloaded')
    volatile_keys = {"__Secure-1PSIDTS", "__Secure-3PSIDTS"}
    for c in cookies:
        name = str(c.get("name", "")).strip()
        if not name or name in volatile_keys:
            continue
        domain = str(c.get("domain") or ".youtube.com").strip()
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        path = str(c.get("path") or "/").strip()
        secure = "TRUE" if c.get("secure", True) else "FALSE"
        try:
            exp = int(float(c.get("expirationDate") or c.get("expiry") or (time.time() + 365 * 86400)))
        except Exception:
            exp = int(time.time() + 365 * 86400)
        val = str(c.get("value", "")).strip()
        lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{exp}\t{name}\t{val}")
    return "\n".join(lines) + "\n"


def ensure_netscape_cookie_file(source: str) -> Optional[str]:
    """
    Chuyển đổi bất kỳ nguồn Cookie nào (file .json, .txt, hoặc chuỗi dán trực tiếp JSON/Netscape/Header)
    thành đường dẫn file cookies.txt chuẩn Netscape cho yt-dlp.
    """
    if not source:
        return None
    source = str(source).strip()
    if not source:
        return None

    from .paths import TEMP_DIR
    temp_dir = TEMP_DIR
    temp_dir.mkdir(parents=True, exist_ok=True)
    out_cookie_file = temp_dir / "active_cookies.txt"

    # 1. Nếu là đường dẫn file .txt chuẩn Netscape sẵn
    if os.path.exists(source) and os.path.isfile(source):
        src_path = Path(source)
        try:
            with open(src_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read().strip()
            if src_path.suffix.lower() == ".txt" and ("\t" in content or "# Netscape" in content):
                return str(src_path)
        except Exception:
            pass

    # 2. Dùng bộ trích xuất vạn năng
    cookies, _ = extract_cookies_from_any_source(source)
    if cookies:
        netscape_text = json_cookies_to_netscape_content(cookies)
        out_cookie_file.write_text(netscape_text, encoding="utf-8")
        return str(out_cookie_file)

    return None


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
    browser_cookie: str = "chrome",
    cookie_file: str = "",
    log: LogCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> List[Dict[str, Any]]:
    """Duyệt nhanh danh sách video từ Playlist hoặc Channel bằng flat-playlist và lọc video bị chặn/hội viên."""
    _log = log or (lambda msg: None)
    _log(f"Đang quét danh sách video từ: {url}")

    # Nếu chọn xác thực qua Kênh OAuth đã đăng nhập trên Tool
    if browser_cookie.startswith("oauth:"):
        try:
            from .youtube_auth import YouTubeAuthManager
            import urllib.parse
            mgr = YouTubeAuthManager()
            ch_id = browser_cookie.split(":", 1)[1]
            srv = mgr.get_service(ch_id)
            parsed_u = urllib.parse.urlparse(url)
            query_params = urllib.parse.parse_qs(parsed_u.query)
            p_id = query_params.get("list", [""])[0]
            if p_id:
                _log(f"🔐 Đang quét Danh sách phát qua YouTube Data API v3 (Kênh OAuth)...")
                api_items: List[Dict[str, Any]] = []
                page_token = None
                while True:
                    if cancel_event and cancel_event.is_set():
                        return []
                    res = srv.playlistItems().list(
                        part="snippet,contentDetails",
                        playlistId=p_id,
                        maxResults=50,
                        pageToken=page_token
                    ).execute()
                    for it in res.get("items", []):
                        vid_id = it.get("contentDetails", {}).get("videoId")
                        t = it.get("snippet", {}).get("title", "")
                        if vid_id:
                            api_items.append({
                                "id": vid_id,
                                "title": t,
                                "url": f"https://www.youtube.com/watch?v={vid_id}",
                                "duration": 0,
                                "duration_str": "--:--",
                                "upload_date": "",
                            })
                    page_token = res.get("nextPageToken")
                    if not page_token:
                        break
                _log(f"🔐 Đã tìm thấy {len(api_items)} video qua YouTube Data API v3 chính chủ.")
                return api_items
        except Exception as e:
            _log(f"⚠ Không thể quét bằng YouTube API ({e}), chuyển sang quét thông thường...")

    ffmpeg_dir = get_ffmpeg_dir()
    ydl_opts: Dict[str, Any] = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "socket_timeout": 8,
        "retries": 2,
        "fragment_retries": 2,
        "ffmpeg_location": ffmpeg_dir,
        "remote_components": ["ejs:github"],
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "tv", "web"]
            }
        },
    }

    node_rt = get_node_runtime()
    if node_rt:
        ydl_opts["js_runtimes"] = node_rt

    VALID_BROWSERS = {"chrome", "edge", "brave", "firefox", "chromium", "opera", "vivaldi", "safari"}
    if browser_cookie in ["file", "custom", "text"] and cookie_file:
        cfile = ensure_netscape_cookie_file(cookie_file)
        if cfile and os.path.exists(cfile):
            ydl_opts["cookiefile"] = cfile
            ydl_opts["extractor_args"] = {
                "youtube": {
                    "player_client": ["android", "ios", "tv", "web"]
                }
            }
    elif browser_cookie.lower() in VALID_BROWSERS:
        ydl_opts["cookiesfrombrowser"] = (browser_cookie.lower(), )

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
    browser_cookie: str = "chrome",
    cookie_file: str = "",
    audio_quality: str = "192",
    log: LogCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> Optional[str]:
    """Tải và chuyển đổi 1 video sang MP3 với hỗ trợ Cookie trình duyệt, Cookie File .txt, Client Spoofing & Tăng tốc tối đa."""
    _log = log or (lambda msg: None)
    save_dir = Path(save_folder)
    save_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_dir = get_ffmpeg_dir()

    downloaded_paths: List[str] = []
    last_log_time = [0.0]

    preferred_q = str(audio_quality or "192").strip()
    if preferred_q not in ["128", "192", "256", "320", "0"]:
        preferred_q = "192"

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
            if any(ign in clean for ign in [
                "No supported JavaScript runtime",
                "Skipping client",
                "Remote component challenge solver",
                "GVS PO Token",
                "SABR-only streaming experiment",
            ]):
                return
            if clean:
                _log(f"   ⚠ [Cảnh báo] {clean}")

        def error(self, msg: str) -> None:
            clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", msg).strip()
            if clean:
                _log(f"   ❌ [Lỗi] {clean}")

    out_template = str(save_dir / "%(title)s.%(ext)s")

    ydl_opts: Dict[str, Any] = {
        "format": "ba/b*/bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": preferred_q,
        }],
        "postprocessor_args": {
            "FFmpegExtractAudio": ["-threads", "0"]
        },
        "concurrent_fragment_downloads": 8,
        "http_chunk_size": 10485760,
        "outtmpl": out_template,
        "ffmpeg_location": ffmpeg_dir,
        "socket_timeout": 10,
        "retries": 2,
        "fragment_retries": 2,
        "quiet": False,
        "no_warnings": False,
        "ignoreerrors": False,
        "logger": YtLogger(),
        "postprocessor_hooks": [post_hook],
        "progress_hooks": [progress_hook],
        "remote_components": ["ejs:github"],
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "tv", "web"]
            }
        },
    }

    node_rt = get_node_runtime()
    if node_rt:
        ydl_opts["js_runtimes"] = node_rt

    VALID_BROWSERS = {"chrome", "edge", "brave", "firefox", "chromium", "opera", "vivaldi", "safari"}
    if browser_cookie in ["file", "custom", "text"] and cookie_file:
        cfile = ensure_netscape_cookie_file(cookie_file)
        if cfile and os.path.exists(cfile):
            ydl_opts["cookiefile"] = cfile
            ydl_opts["extractor_args"] = {
                "youtube": {
                    "player_client": ["android", "ios", "tv", "web"]
                }
            }
    elif browser_cookie.lower() in VALID_BROWSERS:
        ydl_opts["cookiesfrombrowser"] = (browser_cookie.lower(), )

    if cancel_event and cancel_event.is_set():
        return None

    info = None
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        err_str = str(exc)

        # 1. Bỏ qua nhẹ nhàng NẾU THỰC SỰ là video bị xóa hoặc video riêng tư (không dính nhầm format error)
        is_truly_deleted = any(
            k in err_str.lower()
            for k in [
                "this video has been removed",
                "private video",
                "video is private",
                "video has been deleted",
                "this video is unavailable",
                "account associated with this video has been terminated",
            ]
        ) and "requested format is not available" not in err_str.lower() and "the page needs to be reloaded" not in err_str.lower()

        if is_truly_deleted:
            _log(f"   ⚠ [Bỏ qua: Video không khả dụng] Video '{title_hint}' ({url}) đã bị xóa hoặc đặt ở chế độ riêng tư.")
            return None

        # 2. Nếu lỗi liên quan đến cookie, bot, PO token, hoặc format không tải được qua Web
        is_auth_or_format_issue = any(
            k in err_str.lower()
            for k in [
                "could not copy",
                "could not find",
                "database is locked",
                "permission denied",
                "the page needs to be reloaded",
                "unplayable",
                "sign in to confirm you're not a bot",
                "bot",
                "requested format is not available",
                "only images are available",
                "gvs po token",
                "http error 403",
                "forbidden",
                "403",
            ]
        )

        if is_auth_or_format_issue:
            _log(f"   ⚠ Cookie/Web Client gặp trở ngại ({err_str[:60]}...). Đang tự động chuyển sang Mobile/SmartTV Client không dùng Cookie để tải...")
            opts_fallback = dict(ydl_opts)
            opts_fallback.pop("cookiesfrombrowser", None)
            opts_fallback.pop("cookiefile", None)
            opts_fallback["extractor_args"] = {
                "youtube": {
                    "player_client": ["android", "ios", "tv"]
                }
            }
            try:
                with yt_dlp.YoutubeDL(opts_fallback) as ydl_fb:
                    info = ydl_fb.extract_info(url, download=True)
            except Exception as fb_exc:
                fb_err = str(fb_exc)
                if any(k in fb_err.lower() for k in ["this video has been removed", "private video", "video is private"]):
                    _log(f"   ⚠ [Bỏ qua: Video không khả dụng] Video '{title_hint}' đã bị xóa hoặc riêng tư.")
                    return None
                if cancel_event and cancel_event.is_set():
                    _log("Đã dừng tải theo yêu cầu người dùng.")
                else:
                    _log(f"❌ Lỗi tải: {fb_exc}")
                return None
        else:
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
    browser_cookie = str(crawler_cfg.get("browser_cookie") or "chrome").strip()
    cookie_file = str(crawler_cfg.get("cookie_file_path") or "").strip()
    if browser_cookie.startswith("oauth:"):
        _log("🔐 Chế độ Xác thực: Sử dụng Kênh YouTube OAuth (Quét API v3 chính chủ & Tải thông minh).")
    elif browser_cookie in ["file", "custom", "text"] and cookie_file:
        _log(f"🍪 Chế độ Cookie: Sử dụng File Cookie tùy chỉnh '{Path(cookie_file).name}'.")
    elif browser_cookie.lower() in ["chrome", "edge", "brave", "firefox", "chromium", "opera", "vivaldi"]:
        _log(f"🍪 Chế độ Cookie vượt chặn Bot: Sử dụng Cookie từ trình duyệt '{browser_cookie.capitalize()}'.")
    else:
        _log("🍪 Chế độ Cookie: Tắt (Dùng Client Spoofing SmartTV/Mobile).")

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
            browser_cookie=browser_cookie,
            cookie_file=cookie_file,
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
            browser_cookie=browser_cookie,
            cookie_file=cookie_file,
            log=_log,
            cancel_event=_cancel,
        )

    total = len(targets)
    if total == 0:
        _log("Không có video nào để cào MP3.")
        return []

    _log(f"Bắt đầu tải {total} file MP3 vào thư mục: {save_folder}")
    downloaded_files: List[str] = []

    audio_quality = str(crawler_cfg.get("audio_quality") or "192").strip()

    for index, item in enumerate(targets):
        if _cancel.is_set():
            _log("Đã dừng quá trình cào MP3 theo yêu cầu.")
            break

        title = item.get("title") or item.get("url") or f"Item {index + 1}"
        _progress(index + 1, total, f"Đang cào ({index + 1}/{total}): {title[:40]}...")

        # 1. Kiểm tra nếu file MP3 đã tồn tại sẵn trong thư mục lưu (tự động bỏ qua để tiếp tục các tập còn thiếu)
        safe_title = sanitize_filename(title)
        existing_match = None
        exact_path = Path(save_folder) / f"{safe_title}.mp3"
        if exact_path.exists() and exact_path.is_file() and exact_path.stat().st_size > 10240:
            existing_match = exact_path
        else:
            clean_search = re.sub(r'[\W_]+', '', safe_title[:20]).lower()
            if clean_search:
                for f in Path(save_folder).glob("*.mp3"):
                    f_clean = re.sub(r'[\W_]+', '', f.stem).lower()
                    if clean_search in f_clean and f.stat().st_size > 10240:
                        existing_match = f
                        break

        if existing_match:
            _log(f"⚡ [{index + 1}/{total}] [Đã có sẵn] {existing_match.name} ➔ Bỏ qua không tải lại.")
            downloaded_files.append(str(existing_match))
            if on_file_downloaded:
                on_file_downloaded(str(existing_match))
            continue

        _log(f"[{index + 1}/{total}] Đang tải: {title}")

        mp3_path = download_single_audio(
            url=item["url"],
            save_folder=save_folder,
            title_hint=item.get("title", ""),
            browser_cookie=browser_cookie,
            cookie_file=cookie_file,
            audio_quality=audio_quality,
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

        # Giãn cách 0.5 giây giữa các lần tải
        if index < total - 1 and not _cancel.is_set():
            time.sleep(0.5)

    _progress(total, total, f"Hoàn thành! Đã cào thành công {len(downloaded_files)}/{total} file.")
    _log(f"Hoàn tất quá trình cào MP3. Đã tải {len(downloaded_files)}/{total} file thành công.")
    return downloaded_files
