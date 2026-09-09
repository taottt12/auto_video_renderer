from __future__ import annotations

import json
import os
import time
import webbrowser
import wsgiref.simple_server
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import (
    InstalledAppFlow,
    _ExclusiveWSGIServer,
    _WSGIRequestHandler,
    _RedirectWSGIApp,
)
from googleapiclient.discovery import build

from .paths import APP_ROOT

TOKENS_DIR = APP_ROOT / "tokens"
REGISTRY_FILE = TOKENS_DIR / "channels_registry.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.readonly",
]

DEFAULT_OAUTH_PORT = 8918


def run_flow_server(
    flow: InstalledAppFlow,
    port: int = DEFAULT_OAUTH_PORT,
    timeout_seconds: int = 180,
    cancel_check_fn: Optional[Callable[[], bool]] = None,
    success_message: str = "Đăng nhập YouTube thành công! Bạn có thể đóng tab này và quay lại ứng dụng."
) -> Credentials:
    """Chạy local server nhận OAuth callback với cơ chế timeout và hủy tức thì."""
    wsgi_app = _RedirectWSGIApp(success_message)
    local_server = None

    # Thử bind port được chỉ định trước (mặc định 8918 - ít bị xung đột cổng hơn 8080)
    candidate_ports = [port]
    if port != DEFAULT_OAUTH_PORT:
        candidate_ports.append(DEFAULT_OAUTH_PORT)
    candidate_ports.extend([8919, 8920, 8080, 0])

    for p in candidate_ports:
        try:
            local_server = wsgiref.simple_server.make_server(
                "localhost",
                p,
                wsgi_app,
                server_class=_ExclusiveWSGIServer,
                handler_class=_WSGIRequestHandler,
            )
            break
        except OSError:
            continue

    if local_server is None:
        raise OSError("Không thể khởi tạo cổng mạng cục bộ để lắng nghe phản hồi OAuth!")

    try:
        actual_port = local_server.server_port
        flow.redirect_uri = f"http://localhost:{actual_port}/"
        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")

        # Mở trình duyệt mặc định
        webbrowser.open(auth_url, new=1, autoraise=True)

        # Đặt timeout ngắn (0.5s) cho từng lần thăm dò socket để kiểm tra cờ hủy liên tục
        local_server.timeout = 0.5
        start_time = time.time()

        while wsgi_app.last_request_uri is None:
            if cancel_check_fn and cancel_check_fn():
                raise InterruptedError("Người dùng đã hủy đăng nhập.")
            if time.time() - start_time > timeout_seconds:
                raise TimeoutError("Quá thời gian chờ xác thực từ trình duyệt (quá 3 phút).")
            local_server.handle_request()

        if cancel_check_fn and cancel_check_fn():
            raise InterruptedError("Người dùng đã hủy đăng nhập.")

        authorization_response = wsgi_app.last_request_uri.replace("http:", "https:")
        flow.fetch_token(authorization_response=authorization_response)
        return flow.credentials
    finally:
        if local_server:
            try:
                local_server.server_close()
            except Exception:
                pass


class YouTubeAuthManager:
    """Quản lý xác thực OAuth 2.0 đa kênh / đa tài khoản cho YouTube."""

    def __init__(self) -> None:
        TOKENS_DIR.mkdir(parents=True, exist_ok=True)
        if not REGISTRY_FILE.exists():
            self._save_registry({})

    def _load_registry(self) -> Dict[str, Dict[str, Any]]:
        if not REGISTRY_FILE.exists():
            return {}
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_registry(self, registry: Dict[str, Dict[str, Any]]) -> None:
        TOKENS_DIR.mkdir(parents=True, exist_ok=True)
        with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(registry, f, ensure_ascii=False, indent=2)

    def list_channels(self) -> List[Dict[str, Any]]:
        reg = self._load_registry()
        return list(reg.values())

    def get_channel(self, channel_id: str) -> Optional[Dict[str, Any]]:
        reg = self._load_registry()
        return reg.get(channel_id)

    def add_channel_oauth(
        self,
        client_secrets_file: str | Path,
        port: int = DEFAULT_OAUTH_PORT,
        cancel_check_fn: Optional[Callable[[], bool]] = None,
        timeout_seconds: int = 180,
    ) -> Dict[str, Any]:
        """Chạy luồng đăng nhập OAuth qua trình duyệt và lưu trữ token."""
        cs_path = Path(client_secrets_file)
        if not cs_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file client_secrets: {cs_path}")

        flow = InstalledAppFlow.from_client_secrets_file(str(cs_path), SCOPES)
        creds = run_flow_server(
            flow,
            port=port,
            timeout_seconds=timeout_seconds,
            cancel_check_fn=cancel_check_fn,
        )

        # Truy vấn thông tin kênh YouTube vừa cấp quyền
        youtube = build("youtube", "v3", credentials=creds)
        resp = youtube.channels().list(part="snippet,contentDetails", mine=True).execute()

        items = resp.get("items", [])
        if not items:
            raise RuntimeError("Tài khoản Google này chưa có kênh YouTube nào được tạo!")

        channel_item = items[0]
        channel_id = channel_item["id"]
        snippet = channel_item.get("snippet", {})
        title = snippet.get("title", "Kênh không tên")
        custom_url = snippet.get("customUrl", "")
        thumbnails = snippet.get("thumbnails", {})
        avatar_url = (
            thumbnails.get("default", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
            or ""
        )

        token_file = TOKENS_DIR / f"channel_{channel_id}.json"
        with open(token_file, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

        channel_info: Dict[str, Any] = {
            "channel_id": channel_id,
            "title": title,
            "custom_url": custom_url,
            "avatar_url": avatar_url,
            "client_secrets_path": str(cs_path.resolve()),
            "token_path": str(token_file.resolve()),
        }

        reg = self._load_registry()
        reg[channel_id] = channel_info
        self._save_registry(reg)

        return channel_info

    def add_channel_by_keys(
        self,
        client_id: str,
        client_secret: str,
        raw_json_str: str = "",
        port: int = DEFAULT_OAUTH_PORT,
        cancel_check_fn: Optional[Callable[[], bool]] = None,
        timeout_seconds: int = 180,
    ) -> Dict[str, Any]:
        """Tạo client_secret từ Client ID và Secret (hoặc dán JSON) và đăng nhập OAuth không cần nạp file."""
        if raw_json_str.strip():
            try:
                client_config = json.loads(raw_json_str.strip())
            except Exception as e:
                raise ValueError(f"Nội dung JSON không hợp lệ: {e}")

            # Đảm bảo cấu trúc có installed hoặc web
            if "installed" not in client_config and "web" not in client_config:
                if "client_id" in client_config and "client_secret" in client_config:
                    client_config = {
                        "installed": {
                            **client_config,
                            "auth_uri": client_config.get("auth_uri", "https://accounts.google.com/o/oauth2/auth"),
                            "token_uri": client_config.get("token_uri", "https://oauth2.googleapis.com/token"),
                            "redirect_uris": client_config.get("redirect_uris", [f"http://localhost:{port}/", "http://localhost"]),
                        }
                    }
        else:
            cid = client_id.strip()
            csec = client_secret.strip()
            if not cid or not csec:
                raise ValueError("Vui lòng nhập đầy đủ Client ID và Client Secret!")
            client_config = {
                "installed": {
                    "client_id": cid,
                    "client_secret": csec,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "redirect_uris": [
                        f"http://localhost:{port}/",
                        f"http://127.0.0.1:{port}/",
                        "http://localhost",
                        "http://localhost:8918/",
                        "http://localhost:8918",
                        "http://localhost:8080/",
                        "http://localhost:8080"
                    ]
                }
            }

        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        creds = run_flow_server(
            flow,
            port=port,
            timeout_seconds=timeout_seconds,
            cancel_check_fn=cancel_check_fn,
        )

        youtube = build("youtube", "v3", credentials=creds)
        resp = youtube.channels().list(part="snippet,contentDetails", mine=True).execute()

        items = resp.get("items", [])
        if not items:
            raise RuntimeError("Tài khoản Google này chưa có kênh YouTube nào được tạo!")

        channel_item = items[0]
        channel_id = channel_item["id"]
        snippet = channel_item.get("snippet", {})
        title = snippet.get("title", "Kênh không tên")
        custom_url = snippet.get("customUrl", "")
        thumbnails = snippet.get("thumbnails", {})
        avatar_url = (
            thumbnails.get("default", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
            or ""
        )

        # Lưu client_secret.json riêng theo từng kênh vào thư mục tokens
        cs_file = TOKENS_DIR / f"client_secret_{channel_id}.json"
        with open(cs_file, "w", encoding="utf-8") as f:
            json.dump(client_config, f, ensure_ascii=False, indent=2)

        token_file = TOKENS_DIR / f"channel_{channel_id}.json"
        with open(token_file, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

        channel_info: Dict[str, Any] = {
            "channel_id": channel_id,
            "title": title,
            "custom_url": custom_url,
            "avatar_url": avatar_url,
            "client_secrets_path": str(cs_file.resolve()),
            "token_path": str(token_file.resolve()),
        }

        reg = self._load_registry()
        reg[channel_id] = channel_info
        self._save_registry(reg)

        return channel_info

    def get_service(self, channel_id: str):
        """Lấy YouTube service client, tự động refresh token nếu hết hạn."""
        reg = self._load_registry()
        ch = reg.get(channel_id)
        if not ch:
            raise ValueError(f"Kênh {channel_id} chưa được đăng nhập!")

        token_path = Path(ch["token_path"])
        if not token_path.exists():
            raise FileNotFoundError(f"Không tìm thấy token của kênh: {token_path}")

        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())

        return build("youtube", "v3", credentials=creds)

    def delete_channel(self, channel_id: str) -> bool:
        reg = self._load_registry()
        if channel_id in reg:
            ch = reg.pop(channel_id)
            token_path = Path(ch.get("token_path", ""))
            if token_path.exists():
                try:
                    token_path.unlink()
                except Exception:
                    pass
            self._save_registry(reg)
            return True
        return False
