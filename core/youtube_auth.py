from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .paths import APP_ROOT

TOKENS_DIR = APP_ROOT / "tokens"
REGISTRY_FILE = TOKENS_DIR / "channels_registry.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.readonly",
]


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

    def add_channel_oauth(self, client_secrets_file: str | Path, port: int = 0) -> Dict[str, Any]:
        """Chạy luồng đăng nhập OAuth qua trình duyệt và lưu trữ token."""
        cs_path = Path(client_secrets_file)
        if not cs_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file client_secrets: {cs_path}")

        flow = InstalledAppFlow.from_client_secrets_file(str(cs_path), SCOPES)
        # run_local_server mở trình duyệt và chờ callback
        creds = flow.run_local_server(port=port, prompt="consent", access_type="offline")

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
        port: int = 0
    ) -> Dict[str, Any]:
        """Tạo client_secret từ Client ID và Secret (hoặc dán JSON) và đăng nhập OAuth không cần nạp file."""
        if raw_json_str.strip():
            try:
                client_config = json.loads(raw_json_str.strip())
            except Exception as e:
                raise ValueError(f"Nội dung JSON không hợp lệ: {e}")
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
                    "redirect_uris": ["http://localhost"]
                }
            }

        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        creds = flow.run_local_server(port=port, prompt="consent", access_type="offline")

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
