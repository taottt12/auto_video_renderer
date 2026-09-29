from __future__ import annotations

import csv
import datetime
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import webbrowser
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QPixmap, QAction
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTextEdit,
    QPushButton, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox, QProgressBar,
    QGroupBox, QSplitter, QFrame, QDialog, QTabWidget, QRadioButton, QButtonGroup,
    QScrollArea, QMenu
)

from core.gemini_assistant import (
    GeminiAssistant, OfflineSEOAssistant, CustomAIAssistant,
    clean_story_title, clean_episode_badge, extract_clean_video_title,
    extract_highlight_from_title, ThumbnailPromptGenerator, detect_9router_api_key,
    PRESET_COUNTRIES, translate_video_metadata
)
from core.image_generator import AIImageGenerator
from core.settings import PROJECTS_DIR, SettingsManager
from core.thumbnail_builder import ThumbnailBuilder
from core.youtube_auth import YouTubeAuthManager
from core.youtube_uploader import YouTubeUploader


def natural_sort_key(s: str) -> list:
    """Tách số và chữ để sắp xếp tự nhiên: P1, P2, ... P9, P10, P32 thay vì P1, P10, P2."""
    name = Path(s).name
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


class AddChannelKeyDialog(QDialog):
    """Hộp thoại nhập Client ID & Secret hoặc dán JSON để kết nối kênh YouTube."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Thêm Kênh YouTube (Google OAuth 2.0)")
        self.resize(580, 500)
        self.client_id = ""
        self.client_secret = ""
        self.raw_json = ""
        self.port = 8918
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Khung hướng dẫn cấu hình chuẩn Google OAuth
        guide_box = QFrame()
        guide_box.setFrameShape(QFrame.StyledPanel)
        guide_box.setStyleSheet(
            "background-color: #23272d; border: 1px solid #3d444d; border-radius: 6px; padding: 6px;"
        )
        lay_guide = QVBoxLayout(guide_box)
        lay_guide.setSpacing(6)

        guide_title = QLabel("💡 <b>HƯỚNG DẪN TẠO OAUTH KEY (Google Cloud Console)</b>")
        guide_title.setStyleSheet("color: #58a6ff; font-size: 12px;")
        lay_guide.addWidget(guide_title)

        guide_desc = QLabel(
            "• <b>Cách 1 (Khuyên dùng - Nhanh nhất):</b> Khi tạo OAuth Client ID, chọn Application type là "
            "<span style='color: #7ee787;'><b>'Desktop app' (Ứng dụng máy tính)</b></span>.<br>"
            "&nbsp;&nbsp;→ Loại này <b>không yêu cầu</b> cài đặt Redirect URI, xác thực ngay 100% không lo lỗi.<br>"
            "• <b>Cách 2 (Nếu dùng 'Web application'):</b> Trong Google Cloud Console, mục "
            "<b>'Authorized redirect URIs'</b> (URI chuyển hướng), bạn phải nhấn <b>ADD URI</b> và thêm chính xác link sau:"
        )
        guide_desc.setWordWrap(True)
        guide_desc.setStyleSheet("color: #c9d1d9; font-size: 11px; line-height: 1.4;")
        lay_guide.addWidget(guide_desc)

        # Hàng hiển thị Redirect URI + Nút Copy + Cổng Port
        row_uri = QHBoxLayout()
        self.uri_display = QLineEdit("http://localhost:8918/")
        self.uri_display.setReadOnly(True)
        self.uri_display.setStyleSheet("background-color: #161b22; color: #58a6ff; font-weight: bold; font-family: Consolas;")
        row_uri.addWidget(self.uri_display, 1)

        self.copy_btn = QPushButton("📋 Sao chép URI")
        self.copy_btn.setStyleSheet("padding: 4px 10px; font-weight: bold;")
        self.copy_btn.clicked.connect(self._copy_redirect_uri)
        row_uri.addWidget(self.copy_btn)

        lbl_port = QLabel("Cổng (Port):")
        lbl_port.setStyleSheet("color: #c9d1d9; font-weight: bold; font-size: 11px;")
        row_uri.addWidget(lbl_port)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(8918)
        self.port_spin.setStyleSheet("background-color: #161b22; color: #58a6ff; font-weight: bold; padding: 2px;")
        self.port_spin.valueChanged.connect(self._on_port_changed)
        row_uri.addWidget(self.port_spin)

        lay_guide.addLayout(row_uri)
        layout.addWidget(guide_box)

        self.tab_type = QTabWidget()

        # Tab 1: Nhập Client ID & Client Secret
        tab_keys = QWidget()
        lay_keys = QVBoxLayout(tab_keys)
        lay_keys.setSpacing(8)

        lay_keys.addWidget(QLabel("Client ID:"))
        self.cid_edit = QLineEdit()
        self.cid_edit.setPlaceholderText("Ví dụ: 1035312312578-ocf0h...apps.googleusercontent.com")
        lay_keys.addWidget(self.cid_edit)

        lay_keys.addWidget(QLabel("Client Secret:"))
        self.csec_edit = QLineEdit()
        self.csec_edit.setEchoMode(QLineEdit.Password)
        self.csec_edit.setPlaceholderText("Ví dụ: GOCSPX-abcdef123456...")
        lay_keys.addWidget(self.csec_edit)

        # Nút hiện/ẩn Secret
        row_toggle = QHBoxLayout()
        self.show_sec_chk = QCheckBox("Hiện Client Secret")
        self.show_sec_chk.toggled.connect(
            lambda checked: self.csec_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        )
        row_toggle.addWidget(self.show_sec_chk)
        row_toggle.addStretch(1)
        lay_keys.addLayout(row_toggle)
        lay_keys.addStretch(1)

        self.tab_type.addTab(tab_keys, "🔑 Nhập Client ID & Secret")

        # Tab 2: Dán nội dung JSON
        tab_json = QWidget()
        lay_json = QVBoxLayout(tab_json)
        lay_json.addWidget(QLabel("Dán toàn bộ nội dung file client_secret.json (tải từ Google Cloud):"))
        self.json_edit = QTextEdit()
        self.json_edit.setPlaceholderText('{\n  "web": {\n    "client_id": "...",\n    "client_secret": "..."\n  }\n}')
        lay_json.addWidget(self.json_edit)
        self.tab_type.addTab(tab_json, "📄 Dán JSON")

        layout.addWidget(self.tab_type)

        btn_box = QHBoxLayout()
        self.ok_btn = QPushButton("🚀 Bắt đầu Đăng nhập")
        self.ok_btn.setStyleSheet("font-weight: bold; background-color: #2e7d32; color: white; padding: 6px 16px;")
        self.ok_btn.clicked.connect(self._on_submit)
        self.cancel_btn = QPushButton("Hủy")
        self.cancel_btn.clicked.connect(self.reject)
        btn_box.addStretch(1)
        btn_box.addWidget(self.ok_btn)
        btn_box.addWidget(self.cancel_btn)
        layout.addLayout(btn_box)

    def _on_port_changed(self, val: int) -> None:
        self.port = val
        self.uri_display.setText(f"http://localhost:{val}/")

    def _copy_redirect_uri(self) -> None:
        uri = self.uri_display.text().strip()
        QApplication.clipboard().setText(uri)
        self.copy_btn.setText("✔ Đã chép!")
        QTimer.singleShot(2000, lambda: self.copy_btn.setText("📋 Sao chép URI"))

    def _on_submit(self) -> None:
        self.port = self.port_spin.value()
        if self.tab_type.currentIndex() == 0:
            self.client_id = self.cid_edit.text().strip()
            self.client_secret = self.csec_edit.text().strip()
            if not self.client_id or not self.client_secret:
                QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập đầy đủ Client ID và Client Secret.")
                return
        else:
            self.raw_json = self.json_edit.toPlainText().strip()
            if not self.raw_json:
                QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng dán nội dung JSON vào ô.")
                return
        self.accept()


class OAuthWorker(QThread):
    finished_auth = Signal(bool, str, dict)

    def __init__(
        self,
        auth_mgr: YouTubeAuthManager,
        client_id: str = "",
        client_secret: str = "",
        raw_json: str = "",
        port: int = 8918,
    ) -> None:
        super().__init__()
        self.auth_mgr = auth_mgr
        self.client_id = client_id
        self.client_secret = client_secret
        self.raw_json = raw_json
        self.port = port
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        try:
            ch_info = self.auth_mgr.add_channel_by_keys(
                client_id=self.client_id,
                client_secret=self.client_secret,
                raw_json_str=self.raw_json,
                port=self.port,
                cancel_check_fn=lambda: self._is_cancelled,
                timeout_seconds=180,
            )
            self.finished_auth.emit(True, f"Đăng nhập thành công kênh: {ch_info.get('title')}", ch_info)
        except InterruptedError:
            self.finished_auth.emit(False, "Đã hủy xác thực kênh theo yêu cầu.", {})
        except TimeoutError as e:
            self.finished_auth.emit(False, str(e), {})
        except Exception as e:
            if self._is_cancelled:
                self.finished_auth.emit(False, "Đã hủy xác thực kênh theo yêu cầu.", {})
            else:
                self.finished_auth.emit(False, str(e), {})


class ContentWorker(QThread):
    item_finished_sig = Signal(int, bool, str, dict)
    all_finished_sig = Signal()

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        custom_base_url: str,
        tasks: List[Dict[str, Any]],
        channel_name: str,
        target_language: str = "vi",
        gen_title: bool = True,
        gen_desc: bool = True,
        gen_tags: bool = True,
        gen_thumb: bool = True,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.custom_base_url = custom_base_url
        self.tasks = tasks
        self.channel_name = channel_name
        self.target_language = target_language
        self.gen_title = gen_title
        self.gen_desc = gen_desc
        self.gen_tags = gen_tags
        self.gen_thumb = gen_thumb
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        # 1. Nhận diện và chuẩn hóa tên gốc của từng task trực tiếp từ file_name
        task_base_names = []
        for task in self.tasks:
            raw_title = task.get("file_name") or task.get("story_title", "") or ""
            clean_base = extract_clean_video_title(raw_title)
            if not clean_base or clean_base.lower() in ["video", "audio"]:
                clean_base = clean_story_title(task.get("story_title", ""))
            clean_base = clean_story_title(clean_base)
            task_base_names.append(clean_base or raw_title)

        # 2. Đếm tần suất xuất hiện của tên gốc để phân loại Series vs Video đơn lẻ
        base_counts = {}
        for b in task_base_names:
            k = b.strip().lower()
            base_counts[k] = base_counts.get(k, 0) + 1

        # Cache metadata chuẩn cho từng bộ Series / Playlist
        series_cache: Dict[str, Dict[str, Any]] = {}

        for idx, task in enumerate(self.tasks):
            if self._is_cancelled:
                break
            raw_title = task.get("story_title", "")
            ep = task.get("episode_badge") if task.get("episode_badge") is not None else ""
            ep_idx = task.get("episode_index")
            base_name = task_base_names[idx]
            base_key = base_name.strip().lower()

            is_series = (base_counts.get(base_key, 0) >= 2) or bool(ep)

            try:
                if is_series:
                    # Tạo hoặc lấy master metadata của Series
                    if base_key not in series_cache:
                        if self.provider == "offline":
                            master_data = OfflineSEOAssistant.generate_video_metadata(
                                story_title=base_name,
                                episode_name="",
                                channel_name=self.channel_name,
                                episode_index=None,
                                target_language=self.target_language,
                            )
                        elif self.provider in ["custom", "9router"]:
                            assistant = CustomAIAssistant(self.api_key, self.custom_base_url, self.model)
                            master_data = assistant.generate_video_metadata(
                                story_title=base_name,
                                episode_name="",
                                channel_name=self.channel_name,
                                episode_index=None,
                                target_language=self.target_language,
                            )
                        else:
                            assistant = GeminiAssistant(self.api_key, self.model)
                            master_data = assistant.generate_video_metadata(
                                story_title=base_name,
                                episode_name="",
                                channel_name=self.channel_name,
                                episode_index=None,
                                target_language=self.target_language,
                            )
                        series_cache[base_key] = master_data

                    master = series_cache[base_key]
                    master_title = master.get("title", base_name)
                    ch_clean = self.channel_name.split("(")[0].strip()
                    core_title = master_title
                    if ch_clean and core_title.endswith(f"| {ch_clean}"):
                        core_title = core_title[:-len(f"| {ch_clean}")].strip()
                    core_title = re.sub(r"^(?:\[?(?:p\s*\d{1,4}[a-zA-Z]?|(?:tập|tap)\s*\d{1,4}[a-zA-Z]?|(?:phần|phan)\s*\d{1,4}[a-zA-Z]?)\]?)[\s:\-_]+", "", core_title, flags=re.IGNORECASE).strip()
                    core_title = re.sub(r"[\s:\-_]+(?:\[?(?:p\s*\d{1,4}[a-zA-Z]?|(?:tập|tap)\s*\d{1,4}[a-zA-Z]?|(?:phần|phan)\s*\d{1,4}[a-zA-Z]?)\]?)$", "", core_title, flags=re.IGNORECASE).strip()

                    # Tiêu đề cố định theo Playlist 100% đồng bộ tên bộ truyện + Số tập
                    if ep:
                        final_title = f"{core_title} - {ep}"
                        if ch_clean and len(f"{final_title} | {ch_clean}") <= 98:
                            final_title = f"{final_title} | {ch_clean}"
                    else:
                        final_title = f"{core_title} | {ch_clean}" if ch_clean and len(f"{core_title} | {ch_clean}") <= 98 else core_title

                    if len(final_title) > 98:
                        final_title = final_title[:95] + "..."

                    # Tags đồng bộ
                    tags_base = master.get("tags", "")
                    if ep and ep.lower() not in tags_base.lower():
                        tags_base = f"{tags_base}, {ep.lower()}, {core_title.lower()} {ep.lower()}"

                    # Nếu người dùng tắt tự động tạo tiêu đề -> giữ nguyên tiêu đề ban đầu
                    actual_title = final_title if self.gen_title else (task.get("original_title") or task.get("story_title") or task.get("file_name", ""))
                    data = {
                        "title": actual_title,
                        "description": master.get("description", "") if self.gen_desc else task.get("description", ""),
                        "tags": tags_base.strip(", ") if self.gen_tags else task.get("tags", ""),
                        "thumbnail_badge": ep,
                        "thumbnail_highlight": master.get("thumbnail_highlight", extract_highlight_from_title(core_title)) if self.gen_thumb else task.get("thumbnail_hl", ""),
                        "thumbnail_ai_prompt": master.get("thumbnail_ai_prompt", "") if self.gen_thumb else task.get("ai_image_prompt", ""),
                        "provider_used": master.get("provider_used", self.provider),
                    }
                else:
                    # Video đơn lẻ (Standalone): Sinh tiêu đề & mô tả độc lập
                    if self.provider == "offline":
                        data = OfflineSEOAssistant.generate_video_metadata(
                            story_title=raw_title,
                            episode_name=ep,
                            channel_name=self.channel_name,
                            episode_index=ep_idx,
                            target_language=self.target_language,
                        )
                    elif self.provider in ["custom", "9router"]:
                        assistant = CustomAIAssistant(self.api_key, self.custom_base_url, self.model)
                        data = assistant.generate_video_metadata(
                            story_title=raw_title,
                            episode_name=ep,
                            channel_name=self.channel_name,
                            episode_index=ep_idx,
                            target_language=self.target_language,
                        )
                    else:
                        assistant = GeminiAssistant(self.api_key, self.model)
                        data = assistant.generate_video_metadata(
                            story_title=raw_title,
                            episode_name=ep,
                            channel_name=self.channel_name,
                            episode_index=ep_idx,
                            target_language=self.target_language,
                        )

                    if not self.gen_title:
                        data["title"] = task.get("original_title") or task.get("story_title") or task.get("file_name", "")
                    if not self.gen_desc:
                        data["description"] = task.get("description", "")
                    if not self.gen_tags:
                        data["tags"] = task.get("tags", "")
                    if not self.gen_thumb:
                        data["thumbnail_highlight"] = task.get("thumbnail_hl", "")
                        data["thumbnail_ai_prompt"] = task.get("ai_image_prompt", "")

                self.item_finished_sig.emit(idx, True, "Thành công", data)
            except Exception as e:
                self.item_finished_sig.emit(idx, False, str(e), {})

        self.all_finished_sig.emit()


# Giữ alias GeminiWorker để tương thích
GeminiWorker = ContentWorker


class UploadWorker(QThread):
    progress_sig = Signal(int, str, float)
    log_sig = Signal(str)
    item_finished_sig = Signal(int, bool, str)
    item_status_sig = Signal(int, str, str)  # row_idx, status_type ("uploading", "success", "error"), status_text
    item_updated_sig = Signal(int, dict)
    all_finished_sig = Signal()

    def __init__(
        self,
        uploader: YouTubeUploader,
        tasks: List[Dict[str, Any]],
        channel_id: str,
        ai_config: Optional[Dict[str, Any]] = None,
        thumb_config: Optional[Dict[str, Any]] = None,
        geo_config: Optional[Dict[str, Any]] = None,
        cooldown_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__()
        self.uploader = uploader
        self.tasks = tasks
        self.channel_id = channel_id
        self.ai_config = ai_config or {}
        self.thumb_config = thumb_config or {}
        self.geo_config = geo_config or {}
        self.cooldown_config = cooldown_config or {}
        self._is_cancelled = False
        self._series_cache: Dict[str, Dict[str, Any]] = {}

    def cancel(self) -> None:
        self._is_cancelled = True

    def _generate_metadata(self, task: Dict[str, Any]) -> Dict[str, str]:
        if not self.ai_config:
            return {}
        provider = self.ai_config.get("provider", "offline")
        api_key = self.ai_config.get("api_key", "")
        model = self.ai_config.get("model", "")
        custom_base_url = self.ai_config.get("custom_base_url", "")
        channel_name = self.ai_config.get("channel_name", "")
        target_language = self.ai_config.get("target_language", "vi")

        raw_f = task.get("file_name") or task.get("story_title") or Path(task["video_path"]).stem
        clean_base = extract_clean_video_title(raw_f)
        if not clean_base or clean_base.lower() in ["video", "audio"]:
            clean_base = clean_story_title(task.get("story_title", ""))
        clean_base = clean_story_title(clean_base)

        ep = task.get("episode_badge") or ""
        ep_idx = task.get("episode_index")
        base_key = clean_base.strip().lower()

        try:
            if base_key not in self._series_cache:
                if provider == "offline":
                    m_data = OfflineSEOAssistant.generate_video_metadata(
                        story_title=clean_base,
                        episode_name="",
                        channel_name=channel_name,
                        episode_index=None,
                        target_language=target_language,
                    )
                elif provider in ["custom", "9router"]:
                    assistant = CustomAIAssistant(api_key, custom_base_url, model)
                    m_data = assistant.generate_video_metadata(
                        story_title=clean_base,
                        episode_name="",
                        channel_name=channel_name,
                        episode_index=None,
                        target_language=target_language,
                    )
                else:
                    assistant = GeminiAssistant(api_key, model)
                    m_data = assistant.generate_video_metadata(
                        story_title=clean_base,
                        episode_name="",
                        channel_name=channel_name,
                        episode_index=None,
                        target_language=target_language,
                    )
                self._series_cache[base_key] = m_data

            master = self._series_cache[base_key]
            master_title = master.get("title", clean_base)
            ch_clean = channel_name.split("(")[0].strip()
            core_title = master_title
            if ch_clean and core_title.endswith(f"| {ch_clean}"):
                core_title = core_title[:-len(f"| {ch_clean}")].strip()
            core_title = re.sub(r"^(?:\[?(?:p\s*\d{1,4}[a-zA-Z]?|(?:tập|tap)\s*\d{1,4}[a-zA-Z]?|(?:phần|phan)\s*\d{1,4}[a-zA-Z]?)\]?)[\s:\-_]+", "", core_title, flags=re.IGNORECASE).strip()
            core_title = re.sub(r"[\s:\-_]+(?:\[?(?:p\s*\d{1,4}[a-zA-Z]?|(?:tập|tap)\s*\d{1,4}[a-zA-Z]?|(?:phần|phan)\s*\d{1,4}[a-zA-Z]?)\]?)$", "", core_title, flags=re.IGNORECASE).strip()

            if ep:
                final_title = f"{core_title} - {ep}"
                if ch_clean and len(f"{final_title} | {ch_clean}") <= 98:
                    final_title = f"{final_title} | {ch_clean}"
            else:
                final_title = f"{core_title} | {ch_clean}" if ch_clean and len(f"{core_title} | {ch_clean}") <= 98 else core_title

            if len(final_title) > 98:
                final_title = final_title[:95] + "..."

            tags_base = master.get("tags", "")
            if ep and ep.lower() not in tags_base.lower():
                tags_base = f"{tags_base}, {ep.lower()}, {core_title.lower()} {ep.lower()}"

            gen_title_opt = self.ai_config.get("gen_title", True)
            gen_desc_opt = self.ai_config.get("gen_desc", True)
            gen_tags_opt = self.ai_config.get("gen_tags", True)
            gen_thumb_opt = self.ai_config.get("gen_thumb", True)

            actual_title = final_title if gen_title_opt else (task.get("title") or clean_base or raw_f)
            return {
                "title": actual_title,
                "description": master.get("description", "") if gen_desc_opt else task.get("description", ""),
                "tags": tags_base.strip(", ") if gen_tags_opt else task.get("tags", ""),
                "thumbnail_badge": ep,
                "thumbnail_highlight": (master.get("thumbnail_highlight", extract_highlight_from_title(core_title))) if gen_thumb_opt else task.get("thumbnail_hl", ""),
                "thumbnail_ai_prompt": master.get("thumbnail_ai_prompt", "") if gen_thumb_opt else task.get("ai_image_prompt", ""),
                "provider_used": master.get("provider_used", provider),
            }
        except Exception as e:
            self.log_sig.emit(f"   ⚠ Lỗi gọi AI SEO ({provider}): {e}")
            fallback_data = OfflineSEOAssistant.generate_video_metadata(
                story_title=clean_base,
                episode_name=ep,
                channel_name=channel_name,
                episode_index=ep_idx,
                target_language=target_language,
            )
            if not self.ai_config.get("gen_title", True):
                fallback_data["title"] = task.get("title") or clean_base or raw_f
            if not self.ai_config.get("gen_desc", True):
                fallback_data["description"] = task.get("description", "")
            if not self.ai_config.get("gen_tags", True):
                fallback_data["tags"] = task.get("tags", "")
            if not self.ai_config.get("gen_thumb", True):
                fallback_data["thumbnail_highlight"] = task.get("thumbnail_hl", "")
                fallback_data["thumbnail_ai_prompt"] = task.get("ai_image_prompt", "")
            return fallback_data

    def _build_thumbnail(self, task: Dict[str, Any]) -> Optional[Path]:
        if not self.thumb_config:
            return None
        mode = self.thumb_config.get("mode", "frame")
        out_dir = Path(self.thumb_config.get("out_dir", "temp"))
        out_dir.mkdir(parents=True, exist_ok=True)
        v_path = Path(task["video_path"])
        row_idx = task.get("row_idx", 0)
        out_thumb = out_dir / f"thumbnail_tap_{row_idx + 1}.jpg"

        bg_img: Optional[Path] = None
        if mode == "frame":
            sec = self.thumb_config.get("frame_sec", 3.0)
            frame_out = out_dir / f"frame_tap_{row_idx + 1}.jpg"
            try:
                bg_img = ThumbnailBuilder.extract_frame_from_video(v_path, time_sec=sec, out_path=frame_out)
            except Exception as ex:
                self.log_sig.emit(f"   ⚠ Không thể trích xuất frame: {ex}")
                bg_img = None
        elif mode == "playlist":
            pl_p = self.thumb_config.get("playlist_thumb")
            if pl_p and Path(pl_p).exists():
                bg_img = Path(pl_p)
        else:
            cust = task.get("custom_thumb_bg")
            if cust and Path(cust).exists():
                bg_img = Path(cust)

        if not bg_img or not bg_img.exists():
            candidates = self.thumb_config.get("candidates", [])
            if candidates:
                bg_img = candidates[row_idx % len(candidates)]

        if not bg_img or not bg_img.exists():
            return None

        badge = task.get("episode_badge") or f"P{row_idx + 1}"
        hl = task.get("thumbnail_hl") or extract_highlight_from_title(task.get("title", ""))
        ch_name = self.thumb_config.get("channel_name", "")
        font_style = task.get("thumb_font") or self.thumb_config.get("font_style", "drama")
        position = task.get("thumb_pos") or self.thumb_config.get("position", "split_lr")
        badge_pos = task.get("thumb_badge_pos") or self.thumb_config.get("badge_position", "top_left")

        enable_badge = bool(self.thumb_config.get("enable_badge", True))
        enable_hl = bool(self.thumb_config.get("enable_highlight", True))

        try:
            return ThumbnailBuilder.create_thumbnail(
                bg_image=bg_img,
                output_path=out_thumb,
                badge_text=badge,
                highlight_title=hl,
                subtitle=ch_name,
                font_style=font_style,
                position=position,
                badge_position=badge_pos,
                enable_badge=enable_badge,
                enable_highlight=enable_hl,
            )
        except Exception as ex:
            self.log_sig.emit(f"   ⚠ Lỗi vẽ thumbnail: {ex}")
            return None

    def run(self) -> None:
        total = len(self.tasks)
        for idx, task in enumerate(self.tasks):
            if self._is_cancelled:
                self.log_sig.emit("⚠ Người dùng đã bấm dừng upload.")
                break

            v_path = task["video_path"]
            row_idx = task.get("row_idx", idx)
            title = task.get("title", "")
            desc = task.get("description", "")
            tags = task.get("tags", "")

            # 1. TỰ ĐỘNG SINH TIÊU ĐỀ & MÔ TẢ SEO (NẾU CHƯA CÓ HOẶC MÔ TẢ TRỐNG)
            if not desc or not desc.strip():
                self.log_sig.emit(f"[{idx+1}/{total}] 🤖 Đang tự động sinh Tiêu đề, Mô tả, Tags SEO...")
                try:
                    meta = self._generate_metadata(task)
                    if meta:
                        if meta.get("title"):
                            title = meta["title"]
                            task["title"] = title
                        if meta.get("description"):
                            desc = meta["description"]
                            task["description"] = desc
                        if meta.get("tags"):
                            tags = meta["tags"]
                            task["tags"] = tags
                        if meta.get("thumbnail_highlight"):
                            task["thumbnail_hl"] = meta["thumbnail_highlight"]
                        self.item_updated_sig.emit(row_idx, {
                            "title": title,
                            "description": desc,
                            "tags": tags,
                        })
                        self.log_sig.emit(f"   ✔ Đã sinh SEO: {title}")
                except Exception as ex_m:
                    self.log_sig.emit(f"   ⚠ Lỗi tự sinh SEO: {ex_m}")

            # 2. TỰ ĐỘNG TẠO THUMBNAIL THEO CHẾ ĐỘ ĐÃ CHỌN
            thumb = task.get("thumbnail_path")
            if not thumb or not Path(thumb).exists():
                self.log_sig.emit(f"[{idx+1}/{total}] 🎨 Đang tự động tạo Thumbnail...")
                try:
                    thumb_res = self._build_thumbnail(task)
                    if thumb_res and Path(thumb_res).exists():
                        thumb = str(thumb_res)
                        task["thumbnail_path"] = thumb
                        self.item_updated_sig.emit(row_idx, {
                            "thumbnail_path": thumb,
                        })
                        self.log_sig.emit(f"   ✔ Đã tạo Thumbnail: {Path(thumb).name}")
                except Exception as ex_t:
                    self.log_sig.emit(f"   ⚠ Lỗi tạo Thumbnail: {ex_t}")

            # 3. TIẾN HÀNH TẢI LÊN YOUTUBE
            privacy = task["privacy_status"]
            publish_at = task.get("publish_at")
            is_premiere = task.get("is_premiere", False)
            playlist_name = task.get("playlist_name", "")
            playlist_id = task.get("playlist_id", None)

            # Thiết lập định danh quốc gia & ngôn ngữ & vị trí
            default_lang = task.get("default_language") or (self.geo_config.get("language_code") if self.geo_config else None)
            default_audio_lang = task.get("default_audio_language") or (self.geo_config.get("audio_language") if self.geo_config else None)
            loc_desc = task.get("location_description") or (self.geo_config.get("location_name") if self.geo_config and self.geo_config.get("enable_geo") else None)
            lat = task.get("latitude") if "latitude" in task else (self.geo_config.get("latitude") if self.geo_config and self.geo_config.get("enable_geo") else None)
            lng = task.get("longitude") if "longitude" in task else (self.geo_config.get("longitude") if self.geo_config and self.geo_config.get("enable_geo") else None)

            self.log_sig.emit(f"[{idx+1}/{total}] 🚀 Bắt đầu tải lên: {Path(v_path).name}")
            self.log_sig.emit(f"   Tiêu đề: {title}")
            if default_lang:
                self.log_sig.emit(f"   🌐 Định danh ngôn ngữ: {default_lang.upper()} | Âm thanh: {(default_audio_lang or default_lang).upper()}")
            if loc_desc:
                self.log_sig.emit(f"   📍 Vị trí địa lý: {loc_desc}")
            if publish_at:
                self.log_sig.emit(f"   Lịch đăng: {publish_at.strftime('%d/%m/%Y %H:%M')}")

            self.item_status_sig.emit(row_idx, "uploading", "Đang tải (0%)")

            try:
                def on_progress(pct: int, msg: str, spd: float) -> None:
                    self.progress_sig.emit(pct, msg, spd)
                    self.item_status_sig.emit(row_idx, "uploading", f"Đang tải ({pct}%)")

                res = self.uploader.upload_video(
                    channel_id=self.channel_id,
                    video_path=v_path,
                    title=title,
                    description=desc,
                    tags=tags,
                    privacy_status=privacy,
                    publish_at=publish_at,
                    is_premiere=is_premiere,
                    default_language=default_lang,
                    default_audio_language=default_audio_lang,
                    location_description=loc_desc,
                    latitude=lat,
                    longitude=lng,
                    thumbnail_path=thumb,
                    playlist_name=playlist_name,
                    playlist_id=playlist_id,
                    progress_cb=on_progress,
                )
                video_url = res.get("video_url", "")
                self.log_sig.emit(f"✔ Hoàn thành: {video_url}")
                self.item_status_sig.emit(row_idx, "success", video_url)
                self.item_finished_sig.emit(row_idx, True, video_url)
            except Exception as e:
                self.log_sig.emit(f"❌ Lỗi tải lên: {e}")
                self.item_status_sig.emit(row_idx, "error", str(e))
                self.item_finished_sig.emit(row_idx, False, str(e))

            # Giãn cách chống Spam an toàn giữa các video trong hàng đợi
            if idx < total - 1 and not self._is_cancelled:
                if self.cooldown_config and self.cooldown_config.get("enabled", False):
                    min_s = int(self.cooldown_config.get("min_sec", 60))
                    max_s = int(self.cooldown_config.get("max_sec", 180))
                    if max_s < min_s:
                        max_s = min_s
                    delay_sec = random.randint(min_s, max_s)
                    self.log_sig.emit(f"⏳ Giãn cách an toàn chống Spam: Nghỉ {delay_sec}s trước khi tải video tiếp theo...")
                    for remaining in range(delay_sec, 0, -1):
                        if self._is_cancelled:
                            break
                        if remaining % 15 == 0 or remaining <= 5:
                            self.log_sig.emit(f"   ⏳ Còn {remaining}s...")
                        time.sleep(1)

        self.all_finished_sig.emit()


class AIImageWorker(QThread):
    finished_sig = Signal(bool, str, str)  # ok, msg, out_path

    def __init__(
        self,
        prompt: str,
        output_path: Path,
        model_name: str = "flux",
        api_key: str = "",
        base_url: str = "",
    ) -> None:
        super().__init__()
        self.prompt = prompt
        self.output_path = output_path
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url

    def run(self) -> None:
        try:
            res = AIImageGenerator.generate_image(
                prompt=self.prompt,
                output_path=self.output_path,
                model_name=self.model_name,
                api_key=self.api_key,
                base_url=self.base_url,
            )
            self.finished_sig.emit(True, "Thành công", str(res))
        except Exception as e:
            self.finished_sig.emit(False, str(e), "")


class BatchAIImageWorker(QThread):
    progress_sig = Signal(int, int, str)
    item_done_sig = Signal(int, bool, str, str)
    all_done_sig = Signal()

    def __init__(
        self,
        tasks: List[Dict[str, Any]],
        model_name: str = "flux",
        api_key: str = "",
        base_url: str = "",
        provider: str = "9router",
        sample_images: Optional[List[Path]] = None,
        auto_stamp: bool = True,
        target_language: str = "vi",
    ) -> None:
        super().__init__()
        self.tasks = tasks
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url
        self.provider = provider
        self.sample_images = sample_images or []
        self.auto_stamp = auto_stamp
        self.target_language = target_language
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        total = len(self.tasks)
        for i, task in enumerate(self.tasks):
            if self._is_cancelled:
                break
            row_idx = task["row_idx"]
            out_p = task["out_path"]
            prompt = task.get("prompt", "").strip()

            if not prompt:
                title = task.get("title", "")
                desc = task.get("desc", "")
                ch_name = task.get("channel_name", "")
                self.progress_sig.emit(i + 1, total, f"Đang tạo prompt AI cho tập {row_idx + 1}...")
                prompt = ThumbnailPromptGenerator.generate_prompt(
                    title=title,
                    description=desc,
                    sample_images=self.sample_images,
                    provider=self.provider,
                    api_key=self.api_key,
                    model=self.model_name,
                    custom_base_url=self.base_url,
                    channel_name=ch_name,
                    target_language=self.target_language,
                )

            self.progress_sig.emit(i + 1, total, f"Đang vẽ ảnh AI tập {row_idx + 1}/{total}...")
            try:
                res = AIImageGenerator.generate_image(
                    prompt=prompt,
                    output_path=out_p,
                    model_name=self.model_name,
                    api_key=self.api_key,
                    base_url=self.base_url,
                )
                if res and Path(res).exists():
                    try:
                        title_val = task.get("title", "")
                        hl_val = task.get("item", {}).get("thumbnail_highlight") or task.get("item", {}).get("thumbnail_hl") or extract_highlight_from_title(title_val)
                        badge_val = task.get("item", {}).get("episode_badge") or f"TẬP {row_idx + 1}"
                        ch_name = task.get("channel_name", "") or "Gã Đạo Tặc"
                        font_st = "drama" if self.sample_images else (task.get("font_style") or "drama")
                        pos_st = task.get("position") or "split_lr"
                        ThumbnailBuilder.create_thumbnail(
                            bg_image=res,
                            output_path=res,
                            badge_text=badge_val,
                            highlight_title=hl_val,
                            subtitle=ch_name,
                            font_style=font_st,
                            position=pos_st,
                        )
                    except Exception as ex_st:
                        print(f"Batch stamp error: {ex_st}")
                self.item_done_sig.emit(row_idx, True, "Thành công", str(res))
            except Exception as e:
                self.item_done_sig.emit(row_idx, False, str(e), "")

        self.all_done_sig.emit()


class YouTubeTab(QWidget):
    """Tab Tải video lên YouTube với Trợ lý AI SEO Đa Kênh, Quản lý Playlist và Thumbnail từng tập."""

    settings_changed = Signal(dict)

    def __init__(self, settings: Dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.auth_mgr = YouTubeAuthManager()
        self.uploader = YouTubeUploader(self.auth_mgr)
        
        # Quản lý danh sách video và metadata từng tập
        self.video_items: List[Dict[str, Any]] = []
        self.current_video_idx: int = -1
        self._current_project_dir: Optional[Path] = None
        self._current_project_media: List[Path] = []
        self.current_thumbnail_path: Optional[Path] = None
        self._playlist_common_thumb: Optional[Path] = None
        self.sample_image_paths: List[Path] = []
        self._is_loading_settings: bool = False

        self._upload_worker: Optional[UploadWorker] = None
        self._oauth_worker: Optional[OAuthWorker] = None
        self._content_worker: Optional[ContentWorker] = None
        self._ai_img_worker: Optional[AIImageWorker] = None
        self._batch_img_worker: Optional[BatchAIImageWorker] = None

        self._init_ui()
        self.load_settings(self.settings)
        self.refresh_channels()
        self.refresh_projects()

    def _init_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # ==========================================
        # 1. KÊNH YOUTUBE
        # ==========================================
        # Box 1: Quản lý kênh
        grp_channel = QGroupBox("1. Kênh YouTube (Đa tài khoản)")
        lay_ch = QVBoxLayout(grp_channel)

        row_ch = QHBoxLayout()
        self.channel_combo = QComboBox()
        self.channel_combo.currentIndexChanged.connect(self._on_channel_selected)
        row_ch.addWidget(self.channel_combo, 1)

        self.add_ch_btn = QPushButton("+ Thêm kênh")
        self.add_ch_btn.clicked.connect(self._add_channel)
        row_ch.addWidget(self.add_ch_btn)

        self.cancel_oauth_btn = QPushButton("❌ Hủy")
        self.cancel_oauth_btn.setToolTip("Hủy tiến trình đăng nhập OAuth trên trình duyệt")
        self.cancel_oauth_btn.setStyleSheet(
            "background-color: #c9302c; color: white; font-weight: bold; padding: 5px 10px;"
        )
        self.cancel_oauth_btn.setVisible(False)
        self.cancel_oauth_btn.clicked.connect(self._cancel_oauth)
        row_ch.addWidget(self.cancel_oauth_btn)

        lay_ch.addLayout(row_ch)

        self.ch_info_label = QLabel("Chưa chọn kênh nào")
        self.ch_info_label.setStyleSheet("color: #666; font-size: 11px;")
        lay_ch.addWidget(self.ch_info_label)

        # ==========================================
        # 2. CHỌN DỰ ÁN & DANH SÁCH VIDEO
        # ==========================================
        grp_project = QGroupBox("2. Chọn Dự án & Danh sách Video các tập")
        lay_proj = QVBoxLayout(grp_project)

        row_proj = QHBoxLayout()
        row_proj.addWidget(QLabel("Dự án:"))
        self.proj_combo = QComboBox()
        self.proj_combo.setEditable(True)
        self.proj_combo.setInsertPolicy(QComboBox.NoInsert)
        self.proj_combo.currentIndexChanged.connect(self._on_project_selected)
        if self.proj_combo.lineEdit():
            self.proj_combo.lineEdit().editingFinished.connect(self._on_project_name_edited)
        row_proj.addWidget(self.proj_combo, 1)
        self.refresh_proj_btn = QPushButton("🔄")
        self.refresh_proj_btn.setToolTip("Làm mới danh sách dự án và video")
        self.refresh_proj_btn.clicked.connect(self.refresh_projects)
        row_proj.addWidget(self.refresh_proj_btn)
        lay_proj.addLayout(row_proj)

        # Bảng video 7 cột chi tiết từng tập kèm trạng thái tải lên
        self.video_table = QTableWidget(0, 7)
        self.video_table.setHorizontalHeaderLabels([
            "Chọn", "Tập", "Tên Video MP4", "Tiêu đề YouTube", "Thumbnail", "Dung lượng", "Trạng thái Tải lên"
        ])
        h_header = self.video_table.horizontalHeader()
        h_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(2, QHeaderView.Interactive)
        h_header.setSectionResizeMode(3, QHeaderView.Stretch)
        h_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(6, QHeaderView.Interactive)
        self.video_table.setColumnWidth(2, 170)
        self.video_table.setColumnWidth(4, 85)
        self.video_table.setColumnWidth(5, 75)
        self.video_table.setColumnWidth(6, 140)
        h_header.setSectionsMovable(True)
        h_header.setHighlightSections(True)
        self.video_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.video_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.video_table.customContextMenuRequested.connect(self._on_table_context_menu)
        self.video_table.cellClicked.connect(self._on_video_clicked)
        self.video_table.cellDoubleClicked.connect(self._on_table_cell_double_clicked)
        self.video_table.cellChanged.connect(self._on_table_cell_changed)
        lay_proj.addWidget(self.video_table)

        # Hàng nút thao tác trạng thái hàng đợi (Pending / Unloaded / Retry)
        row_status_btns = QHBoxLayout()
        self.btn_set_pending = QPushButton("🟡 Đặt Chờ Tải Lên")
        self.btn_set_pending.setStyleSheet("font-weight: bold; color: #f1e05a; background-color: #2b303c; padding: 4px;")
        self.btn_set_pending.setToolTip("Đưa các video được chọn vào hàng đợi tải lên (Status: Pending)")
        self.btn_set_pending.clicked.connect(self._set_selected_pending)

        self.btn_set_unloaded = QPushButton("⚪ Đặt Chưa Tải")
        self.btn_set_unloaded.setStyleSheet("font-weight: bold; color: #8b949e; background-color: #21262d; padding: 4px;")
        self.btn_set_unloaded.setToolTip("Chuyển các video được chọn về trạng thái Chưa Tải (Tạm bỏ qua)")
        self.btn_set_unloaded.clicked.connect(self._set_selected_unloaded)

        self.btn_retry_failed = QPushButton("🔄 Thử Lại Video Lỗi")
        self.btn_retry_failed.setStyleSheet("font-weight: bold; color: #ff7b72; background-color: #3b2327; padding: 4px;")
        self.btn_retry_failed.setToolTip("Tự động chuyển toàn bộ các video bị Lỗi tải lên về Chờ Tải Lên để thử lại")
        self.btn_retry_failed.clicked.connect(self._retry_all_failed)

        row_status_btns.addWidget(self.btn_set_pending)
        row_status_btns.addWidget(self.btn_set_unloaded)
        row_status_btns.addWidget(self.btn_retry_failed)
        lay_proj.addLayout(row_status_btns)

        row_sort_btns = QHBoxLayout()
        self.btn_sort_natural = QPushButton("Sắp xếp tự nhiên (P1, P2...)")
        self.btn_sort_natural.setToolTip("Sắp xếp video thông minh theo số tập: P1 ➔ P2 ➔ P10 ➔ P32")
        self.btn_sort_natural.clicked.connect(self._sort_videos_natural)

        self.btn_sort_az = QPushButton("A ➔ Z")
        self.btn_sort_az.setToolTip("Sắp xếp theo tên file A ➔ Z")
        self.btn_sort_az.clicked.connect(self._sort_videos_az)

        self.btn_sort_za = QPushButton("Z ➔ A")
        self.btn_sort_za.setToolTip("Sắp xếp theo tên file Z ➔ A")
        self.btn_sort_za.clicked.connect(self._sort_videos_za)

        self.btn_move_up = QPushButton("▲ Lên")
        self.btn_move_up.setToolTip("Di chuyển video đang chọn lên trên")
        self.btn_move_up.clicked.connect(self._move_video_up)

        self.btn_move_down = QPushButton("▼ Xuống")
        self.btn_move_down.setToolTip("Di chuyển video đang chọn xuống dưới")
        self.btn_move_down.clicked.connect(self._move_video_down)

        row_sort_btns.addWidget(self.btn_sort_natural)
        row_sort_btns.addWidget(self.btn_sort_az)
        row_sort_btns.addWidget(self.btn_sort_za)
        row_sort_btns.addWidget(self.btn_move_up)
        row_sort_btns.addWidget(self.btn_move_down)
        lay_proj.addLayout(row_sort_btns)

        row_tbl_btns = QHBoxLayout()
        self.select_all_btn = QPushButton("Chọn tất cả")
        self.select_all_btn.clicked.connect(self._select_all_videos)
        self.unselect_all_btn = QPushButton("Bỏ chọn")
        self.unselect_all_btn.clicked.connect(self._unselect_all_videos)
        self.btn_pick_external_videos = QPushButton("📁 Thêm video ngoài...")
        self.btn_pick_external_videos.setToolTip("Nạp thêm video MP4 từ thư mục bất kỳ")
        self.btn_pick_external_videos.clicked.connect(self._pick_external_videos)
        self.btn_tbl_export_csv = QPushButton("📥 Xuất CSV...")
        self.btn_tbl_export_csv.setToolTip("Xuất danh sách video, Tiêu đề, Chữ Thumbnail, Prompt AI, Mô tả, Tags ra file CSV (Excel)")
        self.btn_tbl_export_csv.setStyleSheet("font-weight: bold; background-color: #1f6feb; color: white;")
        self.btn_tbl_export_csv.clicked.connect(self._export_to_csv)
        row_tbl_btns.addWidget(self.select_all_btn)
        row_tbl_btns.addWidget(self.unselect_all_btn)
        row_tbl_btns.addWidget(self.btn_pick_external_videos)
        row_tbl_btns.addWidget(self.btn_tbl_export_csv)
        lay_proj.addLayout(row_tbl_btns)

        # Cụm nửa trên cột trái: Kênh YouTube + Danh sách Video MP4
        left_top_widget = QWidget()
        left_top_layout = QVBoxLayout(left_top_widget)
        left_top_layout.setContentsMargins(0, 0, 0, 0)
        left_top_layout.setSpacing(6)
        left_top_layout.addWidget(grp_channel)
        left_top_layout.addWidget(grp_project, 1)

        # ==========================================
        # 3. TRỢ LÝ AI SEO & METADATA CHI TIẾT
        # ==========================================

        # Box 3: Trợ lý AI SEO Content (Offline / Gemini / Custom)
        grp_ai = QGroupBox("3. Trợ lý AI Tạo Tiêu Đề & SEO (Đa Nhà Cung Cấp)")
        lay_ai = QVBoxLayout(grp_ai)

        row_provider = QHBoxLayout()
        row_provider.addWidget(QLabel("Công cụ AI:"))
        self.ai_provider_combo = QComboBox()
        self.ai_provider_combo.addItem("🔄 9Router Gateway (Xoay Model Trên Máy)", "9router")
        self.ai_provider_combo.addItem("⚡ Offline Smart SEO (Miễn phí 100%, Không cần Key)", "offline")
        self.ai_provider_combo.addItem("🌐 Google Gemini API (Free 1500 req/ngày)", "gemini")
        self.ai_provider_combo.addItem("🛠️ Custom Provider / OpenAI Format (Groq, OpenRouter...)", "custom")
        self.ai_provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        row_provider.addWidget(self.ai_provider_combo, 1)
        lay_ai.addLayout(row_provider)

        row_lang = QHBoxLayout()
        row_lang.addWidget(QLabel("🌐 Ngôn ngữ đích:"))
        self.ai_target_lang_combo = QComboBox()
        self.ai_target_lang_combo.addItem("Tiếng Việt (Vietnam)", "vi")
        self.ai_target_lang_combo.addItem("Tiếng Tagalog / Philippines (Drama)", "tl")
        self.ai_target_lang_combo.addItem("Tiếng Anh (English)", "en")
        self.ai_target_lang_combo.addItem("Tiếng Thái (Thai)", "th")
        self.ai_target_lang_combo.addItem("Tiếng Indonesia (Bahasa)", "id")
        self.ai_target_lang_combo.addItem("Tiếng Tây Ban Nha (Español)", "es")
        self.ai_target_lang_combo.addItem("Tiếng Bồ Đào Nha (Português)", "pt")
        self.ai_target_lang_combo.addItem("Tiếng Nhật (Japanese)", "ja")
        self.ai_target_lang_combo.addItem("Tiếng Hàn (Korean)", "ko")
        self.ai_target_lang_combo.addItem("Tiếng Trung (Chinese)", "zh")
        self.ai_target_lang_combo.currentIndexChanged.connect(self._save_ui_settings)
        row_lang.addWidget(self.ai_target_lang_combo, 1)
        lay_ai.addLayout(row_lang)

        # Container tùy chọn theo Provider
        self.provider_stack = QFrame()
        lay_stack = QVBoxLayout(self.provider_stack)
        lay_stack.setContentsMargins(0, 4, 0, 4)
        lay_stack.setSpacing(4)

        # 0. 9Router Box
        self.box_9router = QFrame()
        lay_9r = QVBoxLayout(self.box_9router)
        lay_9r.setContentsMargins(0, 0, 0, 0)
        lay_9r.setSpacing(4)

        lbl_9r_info = QLabel("🟢 <b>9Router AI Gateway:</b> Đang kết nối port 20128 trên máy. Hỗ trợ xoay vòng nhiều tài khoản & model dự phòng.")
        lbl_9r_info.setStyleSheet("color: #4caf50; font-size: 11px;")
        lay_9r.addWidget(lbl_9r_info)

        row_9r_cfg = QHBoxLayout()
        row_9r_cfg.addWidget(QLabel("Base URL:"))
        self.nine_url_edit = QLineEdit("http://localhost:20128/v1")
        self.nine_url_edit.textChanged.connect(self._save_ui_settings)
        row_9r_cfg.addWidget(self.nine_url_edit, 1)

        row_9r_cfg.addWidget(QLabel("API Key:"))
        self.nine_key_edit = QLineEdit(detect_9router_api_key())
        self.nine_key_edit.setEchoMode(QLineEdit.Password)
        self.nine_key_edit.textChanged.connect(self._save_ui_settings)
        row_9r_cfg.addWidget(self.nine_key_edit, 1)
        lay_9r.addLayout(row_9r_cfg)

        row_9r_model = QHBoxLayout()
        row_9r_model.addWidget(QLabel("Model:"))
        self.nine_model_combo = QComboBox()
        self.nine_model_combo.setEditable(True)
        self.nine_model_combo.addItems([
            "ag/gemini-3.8-flash-high",
            "ag/gemini-3.8-flash-medium",
            "ag/gemini-3.7-flash-high",
            "ag/gemini-3.7-flash-medium",
            "ag/gemini-3.6-flash-high",
            "ag/claude-sonnet-4-6",
            "ag/gpt-oss-120b-medium",
        ])
        self.nine_model_combo.currentIndexChanged.connect(self._save_ui_settings)
        row_9r_model.addWidget(self.nine_model_combo, 1)

        self.btn_refresh_9r_models = QPushButton("🔄 Lấy DS Model")
        self.btn_refresh_9r_models.setToolTip("Lấy toàn bộ danh sách model đang cấu hình trong 9Router")
        self.btn_refresh_9r_models.clicked.connect(self._fetch_9router_models)
        row_9r_model.addWidget(self.btn_refresh_9r_models)
        lay_9r.addLayout(row_9r_model)
        lay_stack.addWidget(self.box_9router)

        # 1. Offline Info
        self.box_offline = QFrame()
        lay_off = QVBoxLayout(self.box_offline)
        lay_off.setContentsMargins(4, 4, 4, 4)
        lbl_off_info = QLabel("💡 <b>Chế độ Offline Thông Minh:</b> Hoàn toàn miễn phí, tự động phân tích tên truyện, phân bổ phụ đề hấp dẫn, sinh mô tả YouTube chuẩn SEO và tạo hashtag riêng cho từng tập.")
        lbl_off_info.setWordWrap(True)
        lbl_off_info.setStyleSheet("color: #4caf50; font-size: 11px;")
        lay_off.addWidget(lbl_off_info)
        lay_stack.addWidget(self.box_offline)

        # 2. Gemini Box
        self.box_gemini = QFrame()
        lay_gem = QVBoxLayout(self.box_gemini)
        lay_gem.setContentsMargins(0, 0, 0, 0)
        lay_gem.setSpacing(4)

        row_gem_key = QHBoxLayout()
        row_gem_key.addWidget(QLabel("Gemini Key:"))
        self.gemini_key_edit = QLineEdit()
        self.gemini_key_edit.setPlaceholderText("Dán Gemini API Key (AIzaSy...)")
        self.gemini_key_edit.setEchoMode(QLineEdit.Password)
        self.gemini_key_edit.textChanged.connect(self._save_ui_settings)
        row_gem_key.addWidget(self.gemini_key_edit, 1)

        self.btn_get_free_key = QPushButton("🌐 Lấy Key Free")
        self.btn_get_free_key.setToolTip("Mở Google AI Studio để lấy API Key miễn phí 1500 lượt/ngày")
        self.btn_get_free_key.clicked.connect(lambda: webbrowser.open("https://aistudio.google.com/app/apikey"))
        row_gem_key.addWidget(self.btn_get_free_key)
        lay_gem.addLayout(row_gem_key)

        row_gem_model = QHBoxLayout()
        row_gem_model.addWidget(QLabel("Model:"))
        self.gemini_model_combo = QComboBox()
        self.gemini_model_combo.addItems(["gemini-2.5-flash", "gemini-1.5-flash", "gemini-1.5-pro"])
        self.gemini_model_combo.currentIndexChanged.connect(self._save_ui_settings)
        row_gem_model.addWidget(self.gemini_model_combo, 1)
        lay_gem.addLayout(row_gem_model)

        lbl_gem_note = QLabel("📌 Lưu ý: Key Google AI Studio bắt đầu bằng 'AIzaSy...'. Không dùng Service Account OAuth Token ('AQ...').")
        lbl_gem_note.setStyleSheet("color: #888; font-size: 10px;")
        lay_gem.addWidget(lbl_gem_note)
        lay_stack.addWidget(self.box_gemini)

        # 3. Custom Provider Box
        self.box_custom = QFrame()
        lay_cust = QVBoxLayout(self.box_custom)
        lay_cust.setContentsMargins(0, 0, 0, 0)
        lay_cust.setSpacing(4)

        row_c_url = QHBoxLayout()
        row_c_url.addWidget(QLabel("Base URL:"))
        self.custom_url_edit = QLineEdit("https://api.groq.com/openai/v1")
        self.custom_url_edit.setPlaceholderText("https://api.groq.com/openai/v1 hoặc https://openrouter.ai/api/v1")
        self.custom_url_edit.textChanged.connect(self._save_ui_settings)
        row_c_url.addWidget(self.custom_url_edit, 1)
        lay_cust.addLayout(row_c_url)

        row_c_key = QHBoxLayout()
        row_c_key.addWidget(QLabel("API Key:"))
        self.custom_key_edit = QLineEdit()
        self.custom_key_edit.setEchoMode(QLineEdit.Password)
        self.custom_key_edit.textChanged.connect(self._save_ui_settings)
        row_c_key.addWidget(self.custom_key_edit, 1)

        row_c_key.addWidget(QLabel("Model:"))
        self.custom_model_edit = QLineEdit("llama-3.3-70b-versatile")
        self.custom_model_edit.setPlaceholderText("llama-3.3-70b-versatile, deepseek/deepseek-chat...")
        self.custom_model_edit.textChanged.connect(self._save_ui_settings)
        row_c_key.addWidget(self.custom_model_edit, 1)
        lay_cust.addLayout(row_c_key)
        lay_stack.addWidget(self.box_custom)

        lay_ai.addWidget(self.provider_stack)

        # Hàng checkbox tùy chọn các thành phần AI sẽ sinh:
        row_ai_opts = QHBoxLayout()
        row_ai_opts.setSpacing(12)

        self.chk_ai_gen_title = QCheckBox("✍️ Tạo Tiêu Đề (Bỏ chọn để giữ nguyên tên video)")
        self.chk_ai_gen_title.setChecked(True)
        self.chk_ai_gen_title.setStyleSheet("font-weight: bold; color: #58a6ff;")
        self.chk_ai_gen_title.setToolTip("Khi bỏ chọn: AI sẽ KHÔNG viết lại tiêu đề, giữ nguyên tên gốc của video")
        self.chk_ai_gen_title.stateChanged.connect(self._on_ai_gen_options_changed)

        self.chk_ai_gen_desc = QCheckBox("📝 Tạo Mô Tả")
        self.chk_ai_gen_desc.setChecked(True)
        self.chk_ai_gen_desc.setToolTip("Tự động phân tích nội dung để viết mô tả video chuẩn SEO")
        self.chk_ai_gen_desc.stateChanged.connect(self._on_ai_gen_options_changed)

        self.chk_ai_gen_tags = QCheckBox("🏷️ Tạo Tags")
        self.chk_ai_gen_tags.setChecked(True)
        self.chk_ai_gen_tags.setToolTip("Tự động sinh bộ thẻ từ khóa & hashtag SEO")
        self.chk_ai_gen_tags.stateChanged.connect(self._on_ai_gen_options_changed)

        self.chk_ai_gen_thumb = QCheckBox("🎨 Tạo Chữ & Prompt Thumbnail")
        self.chk_ai_gen_thumb.setChecked(True)
        self.chk_ai_gen_thumb.setToolTip("Tự động trích xuất chữ nổi bật và Prompt AI cho ảnh Thumbnail")
        self.chk_ai_gen_thumb.stateChanged.connect(self._on_ai_gen_options_changed)

        row_ai_opts.addWidget(self.chk_ai_gen_title)
        row_ai_opts.addWidget(self.chk_ai_gen_desc)
        row_ai_opts.addWidget(self.chk_ai_gen_tags)
        row_ai_opts.addWidget(self.chk_ai_gen_thumb)
        row_ai_opts.addStretch(1)
        lay_ai.addLayout(row_ai_opts)

        row_ai_actions = QHBoxLayout()
        self.btn_batch_ai_gen = QPushButton("✨ Tự Động Sinh Tiêu Đề, Mô Tả & Tags Cho Các Tập Đã Chọn")
        self.btn_batch_ai_gen.setStyleSheet("font-weight: bold; background-color: #2b5797; color: white; padding: 7px; border-radius: 4px;")
        self.btn_batch_ai_gen.clicked.connect(self._generate_all_content)
        row_ai_actions.addWidget(self.btn_batch_ai_gen, 3)

        self.btn_export_csv_ai = QPushButton("📥 Xuất CSV")
        self.btn_export_csv_ai.setStyleSheet("font-weight: bold; background-color: #1f6feb; color: white; padding: 7px 12px; border-radius: 4px;")
        self.btn_export_csv_ai.setToolTip("Xuất danh sách Tiêu đề, Mô tả, Tags, Chữ Thumbnail & Prompt AI ra file CSV (Excel)")
        self.btn_export_csv_ai.clicked.connect(self._export_to_csv)
        row_ai_actions.addWidget(self.btn_export_csv_ai, 1)
        lay_ai.addLayout(row_ai_actions)

        # Box 4: Nội dung Video xuất bản (Theo từng tập)
        grp_meta = QGroupBox("4. Nội dung Video xuất bản (Tập đang chọn)")
        lay_meta = QVBoxLayout(grp_meta)

        row_edit_top = QHBoxLayout()
        self.editing_video_label = QLabel("Đang chỉnh sửa: Chưa chọn tập nào")
        self.editing_video_label.setStyleSheet("color: #4a90e2; font-weight: bold; font-size: 11px;")
        row_edit_top.addWidget(self.editing_video_label, 1)

        self.btn_copy_episode_info = QPushButton("📋 Sao chép Thông tin / Prompt")
        self.btn_copy_episode_info.setToolTip("Sao chép Tiêu đề, Chữ Thumbnail, Prompt AI, Mô tả của tập này vào bộ nhớ tạm (Clipboard)")
        self.btn_copy_episode_info.setStyleSheet("font-size: 11px; font-weight: bold; padding: 2px 8px;")
        self.btn_copy_episode_info.clicked.connect(self._copy_current_episode_info)
        row_edit_top.addWidget(self.btn_copy_episode_info)
        lay_meta.addLayout(row_edit_top)

        row_title_lbl = QHBoxLayout()
        row_title_lbl.addWidget(QLabel("Tiêu đề (Title):"))
        self.title_len_label = QLabel("0/100")
        self.title_len_label.setStyleSheet("color: #888; font-size: 11px;")
        row_title_lbl.addWidget(self.title_len_label, 0, Qt.AlignRight)
        lay_meta.addLayout(row_title_lbl)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Nhập tiêu đề video cho tập này...")
        self.title_edit.textChanged.connect(self._on_title_changed)
        lay_meta.addWidget(self.title_edit)

        lay_meta.addWidget(QLabel("Mô tả (Description):"))
        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("Mô tả tóm tắt nội dung, mốc thời gian, bản quyền và hashtag...")
        self.desc_edit.setFixedHeight(110)
        self.desc_edit.textChanged.connect(self._on_desc_changed)
        lay_meta.addWidget(self.desc_edit)

        lay_meta.addWidget(QLabel("Thẻ từ khóa (Tags):"))
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("tag1, tag2, tag3, truyen audio, kiem hiep...")
        self.tags_edit.textChanged.connect(self._on_tags_changed)
        lay_meta.addWidget(self.tags_edit)

        # 4.3 Định danh Quốc Gia, Bản Địa Hóa & Giãn Cách Chống Spam
        grp_geo = QGroupBox("4.3 Định danh Quốc gia, Bản Địa Hóa & Giãn cách Spam")
        grp_geo.setStyleSheet("QGroupBox { font-weight: bold; color: #58a6ff; }")
        lay_geo = QVBoxLayout(grp_geo)
        lay_geo.setContentsMargins(6, 6, 6, 6)
        lay_geo.setSpacing(6)

        row_geo_top = QHBoxLayout()
        row_geo_top.addWidget(QLabel("Quốc gia mục tiêu:"))
        self.country_combo = QComboBox()
        for c_key, c_info in PRESET_COUNTRIES.items():
            self.country_combo.addItem(c_info["label"], c_key)
        self.country_combo.currentIndexChanged.connect(self._on_country_changed)
        row_geo_top.addWidget(self.country_combo, 1)

        self.btn_translate_single = QPushButton("🌐 Dịch Sang Quốc Gia Này")
        self.btn_translate_single.setStyleSheet("font-weight: bold; background-color: #238636; color: white; padding: 4px 8px; border-radius: 4px;")
        self.btn_translate_single.setToolTip("AI tự động dịch Tiêu đề, Mô tả và Tags của tập đang chọn sang chuẩn ngôn ngữ & văn hóa của quốc gia đã chọn")
        self.btn_translate_single.clicked.connect(self._translate_current_episode)
        row_geo_top.addWidget(self.btn_translate_single)
        lay_geo.addLayout(row_geo_top)

        # Thông tin định vị & ngôn ngữ
        self.lbl_geo_detail = QLabel("Mã ngôn ngữ: tl | Múi giờ: GMT+8 (Manila) | Bản địa: Philippines TV Drama")
        self.lbl_geo_detail.setStyleSheet("color: #7ee787; font-size: 10px; font-style: italic;")
        lay_geo.addWidget(self.lbl_geo_detail)

        row_geo_loc = QHBoxLayout()
        self.chk_enable_geo = QCheckBox("Gắn vị trí địa lý (recordingDetails):")
        self.chk_enable_geo.setChecked(True)
        self.chk_enable_geo.toggled.connect(self._on_geo_toggled)
        row_geo_loc.addWidget(self.chk_enable_geo)

        self.geo_location_edit = QLineEdit("Manila, Philippines")
        self.geo_location_edit.setPlaceholderText("Ví dụ: Manila, Philippines hoặc New York, USA")
        self.geo_location_edit.textChanged.connect(self._save_ui_settings)
        row_geo_loc.addWidget(self.geo_location_edit, 1)
        lay_geo.addLayout(row_geo_loc)

        # Giãn cách chống Spam
        row_spam = QHBoxLayout()
        self.chk_anti_spam = QCheckBox("Giãn cách an toàn chống Spam (Cooldown):")
        self.chk_anti_spam.setChecked(True)
        self.chk_anti_spam.toggled.connect(self._on_anti_spam_toggled)
        row_spam.addWidget(self.chk_anti_spam)

        self.spin_spam_min = QSpinBox()
        self.spin_spam_min.setRange(5, 3600)
        self.spin_spam_min.setValue(60)
        self.spin_spam_min.setSuffix("s")
        self.spin_spam_min.setToolTip("Thời gian nghỉ tối thiểu")
        self.spin_spam_min.valueChanged.connect(self._save_ui_settings)
        row_spam.addWidget(self.spin_spam_min)

        row_spam.addWidget(QLabel("➔"))

        self.spin_spam_max = QSpinBox()
        self.spin_spam_max.setRange(5, 3600)
        self.spin_spam_max.setValue(180)
        self.spin_spam_max.setSuffix("s")
        self.spin_spam_max.setToolTip("Thời gian nghỉ tối đa (ngẫu nhiên)")
        self.spin_spam_max.valueChanged.connect(self._save_ui_settings)
        row_spam.addWidget(self.spin_spam_max)
        lay_geo.addLayout(row_spam)

        lay_meta.addWidget(grp_geo)

        # Cài đặt xuất bản & Lập lịch
        lay_pub = QVBoxLayout()
        row_pub = QHBoxLayout()
        row_pub.addWidget(QLabel("Chế độ:"))
        self.privacy_combo = QComboBox()
        self.privacy_combo.addItems([
            "Lên lịch đăng (Schedule)",
            "Công khai (Public)",
            "Không công khai (Unlisted)",
            "Riêng tư (Private)"
        ])
        self.privacy_combo.currentIndexChanged.connect(self._on_privacy_changed)
        row_pub.addWidget(self.privacy_combo)

        self.premiere_chk = QCheckBox("Công chiếu (Premiere)")
        row_pub.addWidget(self.premiere_chk)
        lay_pub.addLayout(row_pub)

        # Lập lịch giãn cách
        self.schedule_box = QFrame()
        self.schedule_box.setFrameShape(QFrame.StyledPanel)
        lay_sch = QVBoxLayout(self.schedule_box)
        lay_sch.setContentsMargins(6, 6, 6, 6)

        row_sch_1 = QHBoxLayout()
        row_sch_1.addWidget(QLabel("Ngày bắt đầu:"))
        self.sch_date_edit = QDateEdit()
        self.sch_date_edit.setCalendarPopup(True)
        self.sch_date_edit.setDate(datetime.date.today() + datetime.timedelta(days=1))
        row_sch_1.addWidget(self.sch_date_edit)

        row_sch_1.addWidget(QLabel("Số video/ngày:"))
        self.sch_per_day_spin = QSpinBox()
        self.sch_per_day_spin.setRange(1, 10)
        self.sch_per_day_spin.setValue(2)
        row_sch_1.addWidget(self.sch_per_day_spin)
        lay_sch.addLayout(row_sch_1)

        row_sch_2 = QHBoxLayout()
        row_sch_2.addWidget(QLabel("Khung giờ đăng:"))
        self.sch_slots_edit = QLineEdit("11:30, 19:30")
        self.sch_slots_edit.setPlaceholderText("Ví dụ: 11:30, 19:30")
        row_sch_2.addWidget(self.sch_slots_edit)
        lay_sch.addLayout(row_sch_2)
        lay_pub.addWidget(self.schedule_box)

        # Quản lý Playlist với tùy chọn linh hoạt
        grp_pl = QGroupBox("Danh sách phát (Playlist)")
        lay_grp_pl = QVBoxLayout(grp_pl)
        lay_grp_pl.setContentsMargins(6, 6, 6, 6)
        lay_grp_pl.setSpacing(6)

        self.chk_use_playlist = QCheckBox("Đưa video vào Playlist của kênh")
        self.chk_use_playlist.setChecked(False)
        self.chk_use_playlist.toggled.connect(self._on_playlist_chk_toggled)
        lay_grp_pl.addWidget(self.chk_use_playlist)

        self.pl_options_widget = QWidget()
        lay_pl_opt = QVBoxLayout(self.pl_options_widget)
        lay_pl_opt.setContentsMargins(0, 0, 0, 0)
        lay_pl_opt.setSpacing(4)

        # Radio chọn Playlist có sẵn
        row_rad_exist = QHBoxLayout()
        self.rad_existing_pl = QRadioButton("Playlist có sẵn:")
        self.rad_existing_pl.setChecked(True)
        row_rad_exist.addWidget(self.rad_existing_pl)
        self.playlist_combo = QComboBox()
        row_rad_exist.addWidget(self.playlist_combo, 1)
        self.reload_pl_btn = QPushButton("🔄")
        self.reload_pl_btn.setToolTip("Lấy lại toàn bộ danh sách playlist của kênh")
        self.reload_pl_btn.clicked.connect(self._reload_playlists)
        row_rad_exist.addWidget(self.reload_pl_btn)
        lay_pl_opt.addLayout(row_rad_exist)

        # Radio tạo Playlist mới
        row_rad_new = QHBoxLayout()
        self.rad_new_pl = QRadioButton("Tạo Playlist mới:")
        row_rad_new.addWidget(self.rad_new_pl)
        self.new_playlist_edit = QLineEdit()
        self.new_playlist_edit.setPlaceholderText("Nhập tên Playlist mới...")
        row_rad_new.addWidget(self.new_playlist_edit, 1)
        lay_pl_opt.addLayout(row_rad_new)

        self.pl_btn_group = QButtonGroup(self)
        self.pl_btn_group.addButton(self.rad_existing_pl)
        self.pl_btn_group.addButton(self.rad_new_pl)

        self.pl_options_widget.setEnabled(False)
        lay_grp_pl.addWidget(self.pl_options_widget)
        lay_pub.addWidget(grp_pl)

        lay_meta.addLayout(lay_pub)

        # Ghép Cụm 3 & Cụm 4 vào nửa dưới của cột bên trái (bọc trong ScrollArea)
        left_bottom_widget = QWidget()
        left_bottom_layout = QVBoxLayout(left_bottom_widget)
        left_bottom_layout.setContentsMargins(0, 0, 4, 0)
        left_bottom_layout.setSpacing(6)
        left_bottom_layout.addWidget(grp_ai)
        left_bottom_layout.addWidget(grp_meta)

        left_bottom_scroll = QScrollArea()
        left_bottom_scroll.setWidgetResizable(True)
        left_bottom_scroll.setFrameShape(QFrame.NoFrame)
        left_bottom_scroll.setWidget(left_bottom_widget)

        # Splitter dọc bên trái: Nửa trên (Kênh + Danh sách Video), Nửa dưới (AI SEO + Metadata)
        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.setChildrenCollapsible(False)
        left_splitter.addWidget(left_top_widget)
        left_splitter.addWidget(left_bottom_scroll)
        left_splitter.setSizes([380, 420])

        # ==========================================
        # CỘT PHẢI: THUMBNAIL STUDIO & TIẾN TRÌNH UPLOAD
        # ==========================================
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 4, 0)
        right_layout.setSpacing(6)

        # Box 5: Thumbnail Studio
        grp_thumb = QGroupBox("5. Thumbnail Studio (1280x720 Từng Tập)")
        lay_thumb = QVBoxLayout(grp_thumb)
        lay_thumb.setSpacing(6)

        self.thumb_preview = QLabel("Chưa có Thumbnail")
        self.thumb_preview.setAlignment(Qt.AlignCenter)
        self.thumb_preview.setFixedHeight(290)
        self.thumb_preview.setStyleSheet("background-color: #1a1a1a; color: #888; border: 1px solid #444; border-radius: 6px;")
        lay_thumb.addWidget(self.thumb_preview)

        # Bộ chuyển đổi chế độ Thumbnail: Thiết kế Thumbnail vs AI (Coming Soon)
        row_source = QHBoxLayout()
        self.rad_thumb_custom = QRadioButton("🎨 Thiết Kế Thumbnail (Trích xuất Frame / Ảnh có sẵn)")
        self.rad_thumb_custom.setStyleSheet("font-weight: bold; color: #7ee787;")
        self.rad_thumb_custom.setChecked(True)

        self.rad_thumb_ai = QRadioButton("🤖 Tạo Thumbnail bằng AI (Coming Soon ⏳)")
        self.rad_thumb_ai.setStyleSheet("font-weight: bold; color: #888;")
        self.rad_thumb_ai.setEnabled(False)

        self.thumb_source_group = QButtonGroup(self)
        self.thumb_source_group.addButton(self.rad_thumb_custom)
        self.thumb_source_group.addButton(self.rad_thumb_ai)

        row_source.addWidget(self.rad_thumb_custom)
        row_source.addWidget(self.rad_thumb_ai)
        row_source.addStretch(1)
        lay_thumb.addLayout(row_source)

        # -----------------------------------------------
        # KHUNG CHỌN NGUỒN ẢNH NỀN THUMBNAIL
        # -----------------------------------------------
        self.custom_thumb_box = QWidget()
        lay_cust_th = QVBoxLayout(self.custom_thumb_box)
        lay_cust_th.setContentsMargins(0, 2, 0, 2)
        lay_cust_th.setSpacing(6)

        grp_src = QGroupBox("Nguồn ảnh nền Thumbnail:")
        grp_src.setStyleSheet("QGroupBox { font-weight: bold; color: #58a6ff; }")
        lay_src = QVBoxLayout(grp_src)
        lay_src.setSpacing(6)

        # Chế độ 1: Trích xuất Frame từ Video (Khuyên dùng)
        self.rad_src_frame = QRadioButton("🎞 Trích xuất Frame từ Video (Khuyên dùng - Nhanh & Sắc nét 1080p)")
        self.rad_src_frame.setStyleSheet("font-weight: bold; color: #58a6ff;")
        self.rad_src_frame.setChecked(True)
        lay_src.addWidget(self.rad_src_frame)

        self.frame_opt_widget = QWidget()
        lay_fo = QHBoxLayout(self.frame_opt_widget)
        lay_fo.setContentsMargins(20, 0, 0, 0)
        lay_fo.addWidget(QLabel("Chụp tại giây thứ:"))
        self.spin_frame_sec = QDoubleSpinBox()
        self.spin_frame_sec.setRange(0.5, 60.0)
        self.spin_frame_sec.setSingleStep(0.5)
        self.spin_frame_sec.setValue(3.0)
        self.spin_frame_sec.setSuffix(" s")
        self.spin_frame_sec.setStyleSheet("font-weight: bold; color: #58a6ff;")
        lay_fo.addWidget(self.spin_frame_sec)
        lbl_fo_tip = QLabel("(Tự động lấy khung hình ở giây 2s-5s của video làm nền ghép chữ)")
        lbl_fo_tip.setStyleSheet("color: #888; font-size: 10px; font-style: italic;")
        lay_fo.addWidget(lbl_fo_tip, 1)
        lay_src.addWidget(self.frame_opt_widget)

        # Chế độ 2: Dùng 1 ảnh chung cho toàn bộ Playlist
        self.rad_src_playlist = QRadioButton("🖼 Dùng 1 ảnh chung cho toàn bộ Playlist")
        self.rad_src_playlist.setStyleSheet("font-weight: bold; color: #f1e05a;")
        lay_src.addWidget(self.rad_src_playlist)

        self.pl_opt_widget = QWidget()
        lay_po = QHBoxLayout(self.pl_opt_widget)
        lay_po.setContentsMargins(20, 0, 0, 0)
        self.btn_pick_pl_img = QPushButton("📁 Chọn ảnh chung cho Playlist")
        self.btn_pick_pl_img.setStyleSheet("padding: 3px 8px; font-weight: bold;")
        self.btn_pick_pl_img.clicked.connect(self._pick_playlist_thumbnail)
        lay_po.addWidget(self.btn_pick_pl_img)

        self.lbl_pl_img_name = QLabel("Chưa chọn ảnh poster chung")
        self.lbl_pl_img_name.setStyleSheet("color: #888; font-size: 11px;")
        lay_po.addWidget(self.lbl_pl_img_name, 1)
        lay_src.addWidget(self.pl_opt_widget)
        self.pl_opt_widget.setVisible(False)

        # Chế độ 3: Chọn ảnh riêng cho từng tập / Nạp DS ảnh
        self.rad_src_custom = QRadioButton("📂 Chọn ảnh riêng / Nạp danh sách ảnh theo video")
        self.rad_src_custom.setStyleSheet("font-weight: bold; color: #c9d1d9;")
        lay_src.addWidget(self.rad_src_custom)

        self.cust_opt_widget = QWidget()
        lay_co = QHBoxLayout(self.cust_opt_widget)
        lay_co.setContentsMargins(20, 0, 0, 0)
        self.btn_pick_thumb = QPushButton("📁 Chọn ảnh cho tập này")
        self.btn_pick_thumb.clicked.connect(self._pick_custom_thumbnail)
        lay_co.addWidget(self.btn_pick_thumb)

        self.btn_batch_pick_thumbs = QPushButton("📂 Nạp DS ảnh theo thứ tự video")
        self.btn_batch_pick_thumbs.clicked.connect(self._pick_batch_custom_thumbnails)
        lay_co.addWidget(self.btn_batch_pick_thumbs)
        lay_co.addStretch(1)
        lay_src.addWidget(self.cust_opt_widget)
        self.cust_opt_widget.setVisible(False)

        self.thumb_src_group = QButtonGroup(self)
        self.thumb_src_group.addButton(self.rad_src_frame)
        self.thumb_src_group.addButton(self.rad_src_playlist)
        self.thumb_src_group.addButton(self.rad_src_custom)
        self.rad_src_frame.toggled.connect(self._on_thumb_src_mode_changed)
        self.rad_src_playlist.toggled.connect(self._on_thumb_src_mode_changed)
        self.rad_src_custom.toggled.connect(self._on_thumb_src_mode_changed)

        lay_cust_th.addWidget(grp_src)

        # -----------------------------------------------
        # TUỲ CHỈNH CHỮ VÀ BỐ CỤC CHO TẬP ĐANG CHỌN
        # -----------------------------------------------
        # Checkbox & Tuỳ chỉnh Huy hiệu tập
        self.chk_enable_badge = QCheckBox("Chèn Huy hiệu tập (P1, P2...):")
        self.chk_enable_badge.setStyleSheet("font-weight: bold; color: #58a6ff;")
        self.chk_enable_badge.setChecked(True)
        self.chk_enable_badge.toggled.connect(self._on_enable_badge_toggled)
        lay_cust_th.addWidget(self.chk_enable_badge)

        row_badge = QHBoxLayout()
        row_badge.setContentsMargins(15, 0, 0, 0)
        row_badge.addWidget(QLabel("Tên huy hiệu:"))
        self.thumb_badge_edit = QLineEdit("P1")
        self.thumb_badge_edit.textChanged.connect(self._on_badge_changed)
        row_badge.addWidget(self.thumb_badge_edit, 1)

        row_badge.addWidget(QLabel("Vị trí:"))
        self.thumb_badge_pos_combo = QComboBox()
        self.thumb_badge_pos_combo.addItem("📌 Góc Trái Trên", "top_left")
        self.thumb_badge_pos_combo.addItem("📌 Góc Phải Trên", "top_right")
        self.thumb_badge_pos_combo.addItem("📌 Góc Trái Dưới", "bottom_left")
        self.thumb_badge_pos_combo.addItem("📌 Góc Phải Dưới", "bottom_right")
        self.thumb_badge_pos_combo.currentIndexChanged.connect(self._on_thumb_style_or_pos_changed)
        row_badge.addWidget(self.thumb_badge_pos_combo, 1)
        lay_cust_th.addLayout(row_badge)

        # Checkbox & Tuỳ chỉnh Chữ to nổi bật
        self.chk_enable_hl = QCheckBox("Chèn Chữ to nổi bật & Tiêu đề:")
        self.chk_enable_hl.setStyleSheet("font-weight: bold; color: #58a6ff;")
        self.chk_enable_hl.setChecked(True)
        self.chk_enable_hl.toggled.connect(self._on_enable_hl_toggled)
        lay_cust_th.addWidget(self.chk_enable_hl)

        row_hl = QHBoxLayout()
        row_hl.setContentsMargins(15, 0, 0, 0)
        row_hl.addWidget(QLabel("Chữ nổi bật:"))
        self.thumb_hl_edit = QLineEdit("TIÊU ĐỀ NỔI BẬT")
        self.thumb_hl_edit.textChanged.connect(self._on_thumb_hl_changed)
        row_hl.addWidget(self.thumb_hl_edit)
        lay_cust_th.addLayout(row_hl)

        # Hàng chọn phong cách phối font & vị trí bố cục
        row_font_pos = QHBoxLayout()
        row_font_pos.setContentsMargins(15, 0, 0, 0)
        row_font_pos.addWidget(QLabel("Phối Font:"))
        self.thumb_font_combo = QComboBox()
        self.thumb_font_combo.addItem("YouTube Drama / Tâm Lý (Đỏ Cyan + Vàng + Full Episode)", "drama")
        self.thumb_font_combo.addItem("Bút Pháp Kiếm Hiệp (Mềm mại, không thô)", "but_phap")
        self.thumb_font_combo.addItem("Đồng Bộ Cọ Xước (Nhất quán 100%)", "dong_bo")
        self.thumb_font_combo.addItem("Thư Pháp Cổ Trang (Á Đông Bay Bổng)", "thu_phap")
        self.thumb_font_combo.addItem("Cuồng Ma Huyết Thư (Cọ Xước Rỉ Máu)", "huyet_thu")
        self.thumb_font_combo.currentIndexChanged.connect(self._on_thumb_style_or_pos_changed)
        row_font_pos.addWidget(self.thumb_font_combo, 1)

        row_font_pos.addWidget(QLabel("Bố cục:"))
        self.thumb_pos_combo = QComboBox()
        self.thumb_pos_combo.addItem("⚡ Phân Tách Hai Bên: Trái Trên + Phải (Chữ To, Cân Đối)", "split_lr")
        self.thumb_pos_combo.addItem("⚡ Phân Tách Chéo: Trái Trên + Phải Dưới", "split_lb")
        self.thumb_pos_combo.addItem("👉 Dồn Sang Phải: Chữ To Khổng Lồ (Khi NV ở Trái)", "full_right")
        self.thumb_pos_combo.addItem("👈 Dồn Sang Trái: Chữ To Khổng Lồ (Khi NV ở Phải)", "full_left")
        self.thumb_pos_combo.addItem("📌 Gom Gọn Góc Trái Trên (Né Mặt Cổ Điển)", "compact_tl")
        self.thumb_pos_combo.addItem("🛠 Tùy Chỉnh Tọa Độ...", "custom")
        self.thumb_pos_combo.currentIndexChanged.connect(self._on_thumb_style_or_pos_changed)
        row_font_pos.addWidget(self.thumb_pos_combo, 1)
        lay_cust_th.addLayout(row_font_pos)

        # Khung tọa độ tùy chỉnh tự do (khi người dùng muốn tự tay căn chỉnh)
        self.custom_pos_box = QFrame()
        lay_cp = QHBoxLayout(self.custom_pos_box)
        lay_cp.setContentsMargins(0, 0, 0, 0)
        lay_cp.addWidget(QLabel("X (px):"))
        self.thumb_x_spin = QSpinBox()
        self.thumb_x_spin.setRange(0, 1200)
        self.thumb_x_spin.setSingleStep(10)
        self.thumb_x_spin.setValue(16)
        self.thumb_x_spin.valueChanged.connect(self._on_thumb_style_or_pos_changed)
        lay_cp.addWidget(self.thumb_x_spin)

        lay_cp.addWidget(QLabel("Y:"))
        self.thumb_y_spin = QSpinBox()
        self.thumb_y_spin.setRange(0, 650)
        self.thumb_y_spin.setSingleStep(10)
        self.thumb_y_spin.setValue(75)
        self.thumb_y_spin.valueChanged.connect(self._on_thumb_style_or_pos_changed)
        lay_cp.addWidget(self.thumb_y_spin)

        lay_cp.addWidget(QLabel("Cỡ (%):"))
        self.thumb_scale_spin = QSpinBox()
        self.thumb_scale_spin.setRange(40, 150)
        self.thumb_scale_spin.setSingleStep(5)
        self.thumb_scale_spin.setValue(68)
        self.thumb_scale_spin.valueChanged.connect(self._on_thumb_style_or_pos_changed)
        lay_cp.addWidget(self.thumb_scale_spin)

        self.custom_pos_box.setVisible(False)
        lay_cust_th.addWidget(self.custom_pos_box)

        # Nút Ghép Thử Thumbnail Tập Này (chỉ áp dụng tập đang chọn, không reset về mặc định)
        row_single_thumb = QHBoxLayout()
        self.btn_gen_single_thumb = QPushButton("🎨 Ghép Thử Thumbnail Tập Này")
        self.btn_gen_single_thumb.setStyleSheet("font-weight: bold; background-color: #238636; color: white; padding: 7px 14px; border-radius: 4px;")
        self.btn_gen_single_thumb.setToolTip("Trích xuất frame hoặc lấy ảnh nền theo nguồn đã chọn rồi ghép chữ để xem trước")
        self.btn_gen_single_thumb.clicked.connect(self._create_single_thumbnail)
        row_single_thumb.addWidget(self.btn_gen_single_thumb)
        lay_cust_th.addLayout(row_single_thumb)

        lay_thumb.addWidget(self.custom_thumb_box)

        # Box 6: Nút Bắt đầu Upload & Log
        grp_upload = QGroupBox("6. Tiến trình Tải lên YouTube")
        lay_up = QVBoxLayout(grp_upload)

        self.upload_progress = QProgressBar()
        self.upload_progress.setValue(0)
        self.upload_progress.setTextVisible(True)
        lay_up.addWidget(self.upload_progress)

        self.upload_status_label = QLabel("Sẵn sàng.")
        self.upload_status_label.setStyleSheet("color: #555; font-size: 11px;")
        lay_up.addWidget(self.upload_status_label)

        row_up_act = QHBoxLayout()
        self.btn_start_upload = QPushButton("🚀 BẮT ĐẦU TẢI LÊN YOUTUBE")
        self.btn_start_upload.setStyleSheet("font-weight: bold; font-size: 13px; background-color: #28a745; color: white; padding: 10px; border-radius: 4px;")
        self.btn_start_upload.clicked.connect(self._start_upload)
        self.btn_cancel_upload = QPushButton("Dừng")
        self.btn_cancel_upload.setEnabled(False)
        self.btn_cancel_upload.clicked.connect(self._cancel_upload)
        row_up_act.addWidget(self.btn_start_upload, 1)
        row_up_act.addWidget(self.btn_cancel_upload)
        lay_up.addLayout(row_up_act)

        self.upload_log = QTextEdit()
        self.upload_log.setReadOnly(True)
        self.upload_log.setStyleSheet("background-color: #1a1a1a; color: #a9b7c6; font-family: Consolas, monospace; font-size: 11px;")
        lay_up.addWidget(self.upload_log)

        # -----------------------------------------------
        # GHÉP CỘT 2: QSplitter DỌC (70% Thumbnail Studio : 30% Log)
        # -----------------------------------------------
        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.setChildrenCollapsible(False)
        right_splitter.addWidget(grp_thumb)
        right_splitter.addWidget(grp_upload)
        right_splitter.setSizes([680, 240])
        right_splitter.setStretchFactor(0, 7)
        right_splitter.setStretchFactor(1, 3)
        right_layout.addWidget(right_splitter)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setWidget(right_widget)

        # Splitter chính nằm ngang: Cột Trái (Kênh + Video + AI + Meta) | Cột Phải (Thumbnail + Upload)
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setChildrenCollapsible(False)
        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(right_scroll)
        main_splitter.setSizes([640, 560])
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 1)
        main_layout.addWidget(main_splitter)
        self._update_provider_visibility()
        self._update_thumb_source_visibility()

    # ==========================
    # LOGIC: AI PROVIDER UI
    # ==========================
    def _on_provider_changed(self) -> None:
        self._update_provider_visibility()
        self._save_ui_settings()

    def _update_provider_visibility(self) -> None:
        mode = self.ai_provider_combo.currentData()
        self.box_9router.setVisible(mode == "9router")
        self.box_offline.setVisible(mode == "offline")
        self.box_gemini.setVisible(mode == "gemini")
        self.box_custom.setVisible(mode == "custom")

    def _fetch_9router_models(self) -> None:
        url = self.nine_url_edit.text().strip().rstrip("/")
        if not url.endswith("/v1"):
            url += "/v1"
        try:
            import requests
            r = requests.get(f"{url}/models", timeout=5)
            if r.status_code == 200:
                data = r.json().get("data", [])
                models = [m.get("id") for m in data if m.get("id")]
                if models:
                    cur = self.nine_model_combo.currentText()
                    self.nine_model_combo.clear()
                    self.nine_model_combo.addItems(models)
                    idx = self.nine_model_combo.findText(cur)
                    if idx >= 0:
                        self.nine_model_combo.setCurrentIndex(idx)
                    QMessageBox.information(self, "Thành công", f"Đã nạp {len(models)} model từ 9Router!")
                    return
        except Exception as e:
            QMessageBox.warning(self, "Lỗi kết nối 9Router", f"Không thể lấy model từ 9Router:\n{e}\nHãy chắc chắn 9Router đang chạy tại {url}")

    def _on_playlist_chk_toggled(self, checked: bool) -> None:
        self.pl_options_widget.setEnabled(checked)

    # ==========================
    # LOGIC: QUẢN LÝ KÊNH OAUTH
    # ==========================
    def refresh_channels(self) -> None:
        self.channel_combo.clear()
        channels = self.auth_mgr.list_channels()
        for ch in channels:
            self.channel_combo.addItem(f"{ch.get('title')} ({ch.get('channel_id', '')[:8]}...)", ch.get("channel_id"))

        if self.channel_combo.count() == 0:
            self.channel_combo.addItem("Chưa có kênh (Bấm + Thêm kênh)", "")
            self.ch_info_label.setText("Vui lòng bấm '+ Thêm kênh' để kết nối kênh qua OAuth 2.0.")
        else:
            active_id = self.settings.get("youtube_uploader", {}).get("active_channel_id", "")
            idx = self.channel_combo.findData(active_id)
            if idx >= 0:
                self.channel_combo.setCurrentIndex(idx)
            else:
                self.channel_combo.setCurrentIndex(0)
            self._on_channel_selected()

    def _on_channel_selected(self) -> None:
        channel_id = self.channel_combo.currentData()
        if not channel_id:
            self.ch_info_label.setText("Chưa kết nối kênh.")
            return
        ch = self.auth_mgr.get_channel(channel_id)
        if ch:
            self.ch_info_label.setText(f"Kênh: {ch.get('title')} | ID: {channel_id}")
            self._save_ui_settings()
            self._reload_playlists()

    def _add_channel(self) -> None:
        dlg = AddChannelKeyDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return

        self.add_ch_btn.setEnabled(False)
        self.add_ch_btn.setText("Đang mở web...")
        self.cancel_oauth_btn.setVisible(True)
        self.cancel_oauth_btn.setEnabled(True)
        self.ch_info_label.setText("Đang mở trình duyệt xác thực Google OAuth 2.0... (Nhấn '❌ Hủy' nếu muốn dừng)")

        self._oauth_worker = OAuthWorker(
            self.auth_mgr,
            client_id=dlg.client_id,
            client_secret=dlg.client_secret,
            raw_json=dlg.raw_json,
            port=dlg.port,
        )
        self._oauth_worker.finished_auth.connect(self._on_oauth_finished)
        self._oauth_worker.start()

    def _cancel_oauth(self) -> None:
        if self._oauth_worker and self._oauth_worker.isRunning():
            self._oauth_worker.cancel()
            self.cancel_oauth_btn.setEnabled(False)
            self.ch_info_label.setText("⏳ Đang hủy xác thực và đóng cổng mạng...")

    def _on_oauth_finished(self, success: bool, msg: str, ch_info: dict) -> None:
        self.add_ch_btn.setEnabled(True)
        self.add_ch_btn.setText("+ Thêm kênh")
        self.cancel_oauth_btn.setVisible(False)
        self.cancel_oauth_btn.setEnabled(True)
        if success:
            QMessageBox.information(self, "Thành công", msg)
            self.refresh_channels()
        else:
            if "hủy" in msg.lower():
                self.ch_info_label.setText("Đã hủy xác thực kênh theo yêu cầu.")
            else:
                QMessageBox.critical(self, "Lỗi đăng nhập OAuth", f"Không thể xác thực kênh:\n{msg}")
                self.ch_info_label.setText("Lỗi xác thực OAuth.")

    # ==========================
    # LOGIC: DỰ ÁN & DANH SÁCH VIDEO
    # ==========================
    def _on_project_name_edited(self) -> None:
        raw_name = self.proj_combo.currentText().strip()
        if raw_name:
            clean_title = clean_story_title(raw_name)
            self.new_playlist_edit.setText(clean_title)

    def _on_table_cell_changed(self, row: int, col: int) -> None:
        if not hasattr(self, "video_items") or row < 0 or row >= len(self.video_items):
            return
        item = self.video_items[row]
        tbl_it = self.video_table.item(row, col)
        if not tbl_it:
            return

        if col == 0:  # Cột Checkbox Chọn
            chk = tbl_it.checkState()
            st = item.get("upload_status", "unloaded")
            if chk == Qt.Checked and st in ("unloaded", "- Chưa tải"):
                self._update_row_status(row, "pending")
            elif chk == Qt.Unchecked and st in ("pending", "🟡 Chờ tải lên"):
                self._update_row_status(row, "unloaded")
            return

        val = tbl_it.text().strip()

        if col == 1:  # Cột Tập
            item["episode_badge"] = val
            if row == self.current_video_idx:
                self.thumb_badge_edit.blockSignals(True)
                self.thumb_badge_edit.setText(val)
                self.thumb_badge_edit.blockSignals(False)
                badge_prefix = f"[{val}] " if val else ""
                self.editing_video_label.setText(f"Đang chỉnh sửa: {badge_prefix}{item['file_name']}")
        elif col == 3:  # Cột Tiêu đề YouTube
            item["title"] = val
            tbl_it.setToolTip(val)
            if row == self.current_video_idx:
                self.title_edit.blockSignals(True)
                self.title_edit.setText(val)
                self.title_edit.blockSignals(False)
                length = len(val)
                self.title_len_label.setText(f"{length}/100")
                if length > 95:
                    self.title_len_label.setStyleSheet("color: red; font-weight: bold; font-size: 11px;")
                else:
                    self.title_len_label.setStyleSheet("color: #888; font-size: 11px;")

    def _update_row_status(self, row: int, status_key: str, message: str = "", extra_data: str = "") -> None:
        """Cập nhật trạng thái hàng đợi và giao diện của từng video theo chuẩn."""
        if row < 0 or row >= len(self.video_items):
            return
        item = self.video_items[row]
        self.video_table.blockSignals(True)

        chk_item = self.video_table.item(row, 0)
        it_st = self.video_table.item(row, 6)
        if not it_st:
            it_st = QTableWidgetItem()
            it_st.setTextAlignment(Qt.AlignCenter)
            it_st.setFlags(it_st.flags() & ~Qt.ItemIsEditable)
            self.video_table.setItem(row, 6, it_st)

        if status_key == "unloaded":
            item["upload_status"] = "unloaded"
            it_st.setText("- Chưa tải")
            it_st.setForeground(Qt.gray)
            it_st.setToolTip("Video chưa được đưa vào hàng đợi tải lên (Tạm bỏ qua)")
            if chk_item:
                chk_item.setFlags(chk_item.flags() | Qt.ItemIsEnabled)
                chk_item.setCheckState(Qt.Unchecked)

        elif status_key == "pending":
            item["upload_status"] = "pending"
            it_st.setText("🟡 Chờ tải lên")
            it_st.setForeground(Qt.yellow)
            it_st.setToolTip("Video đang trong hàng đợi sẵn sàng tải lên YouTube")
            if chk_item:
                chk_item.setFlags(chk_item.flags() | Qt.ItemIsEnabled)
                chk_item.setCheckState(Qt.Checked)

        elif status_key == "uploading":
            item["upload_status"] = "uploading"
            it_st.setText(f"⏳ {message or 'Đang tải...'}")
            it_st.setForeground(Qt.cyan)
            it_st.setToolTip(f"Tiến trình tải lên: {message}")

        elif status_key == "uploaded":
            item["upload_status"] = "uploaded"
            item["video_url"] = extra_data or item.get("video_url", "")
            it_st.setText("✅ Đã tải (Mở ↗)")
            it_st.setForeground(Qt.green)
            it_st.setToolTip(f"Đã tải lên thành công!\nBấm đúp để mở trên YouTube:\n{item['video_url']}")
            if chk_item:
                chk_item.setCheckState(Qt.Unchecked)
                # Khóa hoàn toàn không cho thao tác chọn đối với video đã tải hoàn thành
                chk_item.setFlags(chk_item.flags() & ~Qt.ItemIsEnabled)

        elif status_key == "error":
            item["upload_status"] = "error"
            item["error_msg"] = message
            it_st.setText("❌ Lỗi tải")
            it_st.setForeground(Qt.red)
            it_st.setToolTip(f"Lỗi tải lên:\n{message}\n\n(Chuột phải hoặc bấm '🔄 Thử lại video lỗi' để tải lại)")
            if chk_item:
                chk_item.setFlags(chk_item.flags() | Qt.ItemIsEnabled)

        self.video_table.blockSignals(False)

    def _set_selected_pending(self) -> None:
        """Đưa các video được chọn vào hàng đợi Chờ Tải Lên."""
        selected_rows = set([idx.row() for idx in self.video_table.selectedIndexes()])
        if not selected_rows:
            selected_rows = set(range(len(self.video_items)))
        count = 0
        for r in selected_rows:
            if 0 <= r < len(self.video_items):
                st = self.video_items[r].get("upload_status", "unloaded")
                if st != "uploaded":
                    self._update_row_status(r, "pending")
                    count += 1
        self._log(f"🟡 Đã đưa {count} video vào hàng đợi [🟡 Chờ tải lên].")

    def _set_selected_unloaded(self) -> None:
        """Chuyển các video được chọn về trạng thái Chưa Tải (Tạm bỏ qua)."""
        selected_rows = set([idx.row() for idx in self.video_table.selectedIndexes()])
        if not selected_rows:
            selected_rows = set(range(len(self.video_items)))
        count = 0
        for r in selected_rows:
            if 0 <= r < len(self.video_items):
                st = self.video_items[r].get("upload_status", "unloaded")
                if st != "uploaded":
                    self._update_row_status(r, "unloaded")
                    count += 1
        self._log(f"⚪ Đã chuyển {count} video về trạng thái [⚪ Chưa tải].")

    def _retry_all_failed(self) -> None:
        """Tự động chuyển toàn bộ các video bị Lỗi tải lên về Chờ Tải Lên."""
        count = 0
        for r, item in enumerate(self.video_items):
            if item.get("upload_status") == "error":
                self._update_row_status(r, "pending")
                count += 1
        if count > 0:
            self._log(f"🔄 Đã đưa {count} video lỗi trở lại hàng đợi [🟡 Chờ tải lên].")
        else:
            QMessageBox.information(self, "Thông báo", "Không có video nào đang ở trạng thái lỗi tải lên.")

    def _on_table_context_menu(self, pos) -> None:
        row = self.video_table.rowAt(pos.y())
        if row < 0 or row >= len(self.video_items):
            return
        item = self.video_items[row]
        menu = QMenu(self)

        act_pending = menu.addAction("🟡 Đặt thành: Chờ tải lên (Đưa vào hàng đợi)")
        act_unloaded = menu.addAction("⚪ Đặt thành: Chưa tải (Tạm bỏ qua)")
        act_retry = menu.addAction("🔄 Thử lại tải lên (Dành cho video lỗi)")

        st = item.get("upload_status", "unloaded")
        if st == "uploaded":
            act_pending.setEnabled(False)
            act_unloaded.setEnabled(False)
            act_retry.setEnabled(False)

        menu.addSeparator()
        act_open_yt = menu.addAction("🌐 Mở xem video trên YouTube")
        act_copy_url = menu.addAction("📋 Sao chép link YouTube")

        video_url = item.get("video_url", "")
        if not (video_url and video_url.startswith("http")):
            act_open_yt.setEnabled(False)
            act_copy_url.setEnabled(False)

        action = menu.exec(self.video_table.viewport().mapToGlobal(pos))
        if action == act_pending:
            self._update_row_status(row, "pending")
        elif action == act_unloaded:
            self._update_row_status(row, "unloaded")
        elif action == act_retry:
            self._update_row_status(row, "pending")
        elif action == act_open_yt and video_url:
            webbrowser.open(video_url)
        elif action == act_copy_url and video_url:
            QApplication.clipboard().setText(video_url)
            self._log(f"📋 Đã sao chép link YouTube: {video_url}")

    def _on_country_changed(self) -> None:
        c_key = self.country_combo.currentData()
        if c_key in PRESET_COUNTRIES:
            c = PRESET_COUNTRIES[c_key]
            l_code = c.get("language_code", "")
            tz = c.get("tz_offset", 7.0)
            culture = c.get("culture", "")
            loc = c.get("location_name", "")
            self.lbl_geo_detail.setText(f"Mã ngôn ngữ: {l_code.upper() or 'Tùy chọn'} | Múi giờ: GMT{tz:+g} | Bản địa: {culture[:50]}...")
            if loc:
                self.geo_location_edit.setText(loc)
            # Tự động đồng bộ dropdown AI Target Language nếu có
            if l_code:
                idx_tl = self.ai_target_lang_combo.findData(l_code)
                if idx_tl >= 0:
                    self.ai_target_lang_combo.blockSignals(True)
                    self.ai_target_lang_combo.setCurrentIndex(idx_tl)
                    self.ai_target_lang_combo.blockSignals(False)
        self._save_ui_settings()

    def _on_geo_toggled(self, checked: bool) -> None:
        self.geo_location_edit.setEnabled(checked)
        self._save_ui_settings()

    def _on_anti_spam_toggled(self, checked: bool) -> None:
        self.spin_spam_min.setEnabled(checked)
        self.spin_spam_max.setEnabled(checked)
        self._save_ui_settings()

    def _translate_current_episode(self) -> None:
        """Dịch 1-click Tiêu đề, Mô tả và Tags của tập đang chọn sang ngôn ngữ của quốc gia mục tiêu."""
        if self.current_video_idx < 0 or self.current_video_idx >= len(self.video_items):
            QMessageBox.warning(self, "Chưa chọn tập", "Vui lòng chọn 1 video/tập trong bảng để dịch.")
            return

        c_key = self.country_combo.currentData()
        c_info = PRESET_COUNTRIES.get(c_key, PRESET_COUNTRIES["ph"])
        target_lang = c_info.get("language_code") or self.ai_target_lang_combo.currentData() or "tl"
        lang_label = c_info.get("label", "Quốc gia đã chọn")

        title = self.title_edit.text().strip()
        desc = self.desc_edit.toPlainText().strip()
        tags = self.tags_edit.text().strip()
        ch_name = self.channel_combo.currentText().split("(")[0].strip()

        if not title:
            QMessageBox.warning(self, "Thiếu tiêu đề", "Video hiện tại chưa có tiêu đề để dịch.")
            return

        provider = self.ai_provider_combo.currentData() or "9router"
        api_key = ""
        model = ""
        custom_url = ""
        if provider == "gemini":
            api_key = self.gemini_key_edit.text().strip()
            model = self.gemini_model_combo.currentText().strip()
        elif provider == "9router":
            api_key = self.nine_key_edit.text().strip()
            model = self.nine_model_combo.currentText().strip()
            custom_url = self.nine_url_edit.text().strip()
        elif provider == "custom":
            api_key = self.custom_key_edit.text().strip()
            model = self.custom_model_edit.text().strip()
            custom_url = self.custom_url_edit.text().strip()

        self._log(f"🌐 Đang dịch tự động Tiêu đề, Mô tả sang {lang_label} ({provider})...")
        self.btn_translate_single.setEnabled(False)
        self.btn_translate_single.setText("⏳ Đang dịch...")
        QApplication.processEvents()

        try:
            res = translate_video_metadata(
                title=title,
                description=desc,
                tags=tags,
                target_language=target_lang,
                provider=provider,
                api_key=api_key,
                model=model,
                custom_base_url=custom_url,
                channel_name=ch_name,
            )
            new_title = res.get("title", title)
            new_desc = res.get("description", desc)
            new_tags = res.get("tags", tags)
            new_hl = res.get("thumbnail_highlight", "")

            self.title_edit.setText(new_title)
            self.desc_edit.setText(new_desc)
            self.tags_edit.setText(new_tags)
            if hasattr(self, "thumb_hl_edit") and new_hl:
                self.thumb_hl_edit.setText(new_hl)

            # Cập nhật trong video_items và bảng
            item = self.video_items[self.current_video_idx]
            item["title"] = new_title
            item["description"] = new_desc
            item["tags"] = new_tags
            if new_hl:
                item["thumbnail_hl"] = new_hl

            it_t = self.video_table.item(self.current_video_idx, 3)
            if it_t:
                it_t.setText(new_title)
                it_t.setToolTip(new_title)

            self._log(f"✔ Đã dịch thành công sang {lang_label}: {new_title}")
        except Exception as e:
            self._log(f"⚠ Lỗi khi dịch metadata: {e}")
            QMessageBox.warning(self, "Lỗi dịch thuật", f"Không thể hoàn thành dịch thuật:\n{e}")
        finally:
            self.btn_translate_single.setEnabled(True)
            self.btn_translate_single.setText("🌐 Dịch Sang Quốc Gia Này")

    def refresh_projects(self) -> None:
        cur_text = self.proj_combo.currentText()
        cur_data = self.proj_combo.currentData()
        self.proj_combo.blockSignals(True)
        self.proj_combo.clear()

        # Thêm mục Mặc định
        self.proj_combo.addItem("Mặc định (Dự án chính)", "")

        projects = SettingsManager.list_projects()
        for p in projects:
            self.proj_combo.addItem(p.name.replace(".avr.json", "").replace(".json", ""), str(p))

        # Nếu trước đó đang chọn thư mục ngoài, giữ lại thư mục đó
        if cur_data and Path(cur_data).is_dir():
            self.proj_combo.insertItem(0, cur_text, cur_data)
            self.proj_combo.setCurrentIndex(0)
        else:
            current_name = self.settings.get("project", {}).get("current_name", "")
            idx = self.proj_combo.findText(current_name)
            if idx >= 0:
                self.proj_combo.setCurrentIndex(idx)
            elif self.proj_combo.count() > 0:
                self.proj_combo.setCurrentIndex(0)
        self.proj_combo.blockSignals(False)
        self._on_project_selected()

    def _on_project_selected(self) -> None:
        proj_path_str = self.proj_combo.currentData()
        output_dir = None
        self._current_project_media = []

        raw_proj_name = self.proj_combo.currentText()
        clean_title = clean_story_title(raw_proj_name)
        self.new_playlist_edit.setText(clean_title)

        is_external = False
        if proj_path_str:
            p_path = Path(proj_path_str)
            if p_path.is_dir():
                output_dir = p_path
                is_external = True
            elif p_path.exists():
                try:
                    p_cfg = SettingsManager.load_project(p_path)
                    out_str = p_cfg.get("export", {}).get("output_folder") or p_cfg.get("project", {}).get("output_folder")
                    if out_str:
                        output_dir = Path(out_str)
                    m_list = p_cfg.get("media_files", [])
                    self._current_project_media = [Path(m) for m in m_list if Path(m).exists()]
                except Exception:
                    pass

        if not output_dir:
            output_dir = Path(self.settings.get("export", {}).get("output_folder", "output"))

        if not output_dir.is_absolute():
            output_dir = Path("D:/auto_video_renderer/auto_video_renderer") / output_dir

        self._current_project_dir = output_dir

        if not output_dir.exists():
            self.video_table.setRowCount(0)
            self.video_items = []
            return

        mp4_files = sorted(list(output_dir.glob("*.mp4")), key=lambda p: natural_sort_key(p.name))
        self._load_mp4_files_into_table(mp4_files, clean_title, is_external=is_external)

    def _load_mp4_files_into_table(self, mp4_files: List[Path], story_title: str, is_external: bool = False) -> None:
        self.video_table.blockSignals(True)
        self.video_items = []
        self.video_table.setRowCount(len(mp4_files))

        for row, f in enumerate(mp4_files):
            # Nhận diện huy hiệu tập: nếu tên file không chứa số tập hợp lệ thì badge = ""
            badge = clean_episode_badge(f.stem, fallback_idx=None)
            sz_mb = f.stat().st_size / (1024 * 1024) if f.exists() else 0.0

            # Kiểm tra xem có sẵn thumbnail trong thư mục không
            thumb_candidate = f.parent / f"thumbnail_tap_{row+1}.jpg"
            if not thumb_candidate.exists():
                thumb_candidate = f.parent / f"{f.stem}.jpg"
            thumb_path = str(thumb_candidate) if thumb_candidate.exists() else None

            # Làm sạch tên video: bóc tách chính xác tên gốc của bộ truyện từ chính tên file
            clean_name = extract_clean_video_title(f.stem)
            if not clean_name or clean_name.lower() in ["video", "audio"]:
                clean_name = clean_story_title(story_title) or f.stem
            else:
                clean_name = clean_story_title(clean_name)

            if badge:
                item_title = f"{clean_name} - {badge}"
            else:
                item_title = clean_name

            if len(item_title) > 95:
                item_title = item_title[:95]

            tag_base = f"{clean_name.lower()}, truyen audio"
            if badge:
                tag_base += f", {badge.lower()}, {clean_name.lower()} {badge.lower()}"

            item_data = {
                "video_path": str(f),
                "file_name": f.name,
                "size_mb": sz_mb,
                "episode_badge": badge,
                "episode_index": row + 1 if badge else None,
                "title": item_title,
                "description": "",
                "tags": tag_base.strip(", "),
                "thumbnail_path": thumb_path,
                "thumbnail_hl": extract_highlight_from_title(item_title),
                "upload_status": "- Chưa tải",
                "video_url": "",
            }
            self.video_items.append(item_data)

            # Col 0: Checkbox
            chk_item = QTableWidgetItem()
            chk_item.setCheckState(Qt.Unchecked)
            chk_item.setData(Qt.UserRole, row)
            chk_item.setFlags(chk_item.flags() & ~Qt.ItemIsEditable)
            self.video_table.setItem(row, 0, chk_item)

            # Col 1: Tập (Cho phép sửa trực tiếp trong bảng)
            it_badge = QTableWidgetItem(badge)
            it_badge.setTextAlignment(Qt.AlignCenter)
            self.video_table.setItem(row, 1, it_badge)

            # Col 2: Tên file (Chỉ đọc)
            it_name = QTableWidgetItem(f.name)
            it_name.setToolTip(f.name)
            it_name.setFlags(it_name.flags() & ~Qt.ItemIsEditable)
            self.video_table.setItem(row, 2, it_name)

            # Col 3: Tiêu đề YouTube (Cho phép sửa trực tiếp trong bảng)
            it_title = QTableWidgetItem(item_title)
            it_title.setToolTip(item_title)
            self.video_table.setItem(row, 3, it_title)

            # Col 4: Thumbnail
            thumb_status = "✔ Đã có" if thumb_path else "Chưa tạo"
            it_thumb = QTableWidgetItem(thumb_status)
            it_thumb.setTextAlignment(Qt.AlignCenter)
            it_thumb.setFlags(it_thumb.flags() & ~Qt.ItemIsEditable)
            if thumb_path:
                it_thumb.setForeground(Qt.green)
            else:
                it_thumb.setForeground(Qt.gray)
            self.video_table.setItem(row, 4, it_thumb)

            # Col 5: Dung lượng
            it_sz = QTableWidgetItem(f"{sz_mb:.1f} MB")
            it_sz.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_sz.setFlags(it_sz.flags() & ~Qt.ItemIsEditable)
            self.video_table.setItem(row, 5, it_sz)

            # Col 6: Trạng thái Tải lên
            it_st = QTableWidgetItem("- Chưa tải")
            it_st.setTextAlignment(Qt.AlignCenter)
            it_st.setFlags(it_st.flags() & ~Qt.ItemIsEditable)
            it_st.setForeground(Qt.gray)
            self.video_table.setItem(row, 6, it_st)

        self.video_table.blockSignals(False)

        if mp4_files:
            self._select_video_row(0)

    def _pick_external_videos(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Chọn danh sách video MP4 cần tải lên", "", "Video (*.mp4 *.mkv *.mov *.avi)"
        )
        if not files:
            return
        mp4_files = sorted([Path(f) for f in files], key=lambda p: natural_sort_key(p.name))
        folder = mp4_files[0].parent
        folder_name = folder.name

        # Đặt tên dự án theo tên thư mục ngoài
        proj_label = f"📁 {folder_name} (Thư mục ngoài)"
        self.proj_combo.blockSignals(True)
        found_idx = -1
        for i in range(self.proj_combo.count()):
            if self.proj_combo.itemData(i) == str(folder):
                found_idx = i
                break
        if found_idx >= 0:
            self.proj_combo.setCurrentIndex(found_idx)
        else:
            self.proj_combo.insertItem(0, proj_label, str(folder))
            self.proj_combo.setCurrentIndex(0)
        self.proj_combo.blockSignals(False)

        self._current_project_dir = folder
        self._load_mp4_files_into_table(mp4_files, story_title=folder_name, is_external=True)

    def _sort_videos_natural(self) -> None:
        if not hasattr(self, "video_items") or not self.video_items:
            return
        self.video_items.sort(key=lambda it: natural_sort_key(it.get("file_name", "")))
        self._reload_video_table_from_items()
        self._log("✔ Đã sắp xếp danh sách video theo thứ tự tự nhiên (P1, P2, P10...)")

    def _sort_videos_az(self) -> None:
        if not hasattr(self, "video_items") or not self.video_items:
            return
        self.video_items.sort(key=lambda it: it.get("file_name", "").lower())
        self._reload_video_table_from_items()
        self._log("✔ Đã sắp xếp danh sách video theo thứ tự A ➔ Z")

    def _sort_videos_za(self) -> None:
        if not hasattr(self, "video_items") or not self.video_items:
            return
        self.video_items.sort(key=lambda it: it.get("file_name", "").lower(), reverse=True)
        self._reload_video_table_from_items()
        self._log("✔ Đã sắp xếp danh sách video theo thứ tự Z ➔ A")

    def _move_video_up(self) -> None:
        if not hasattr(self, "video_items") or not self.video_items:
            return
        row = self.current_video_idx
        if row > 0 and row < len(self.video_items):
            item = self.video_items.pop(row)
            self.video_items.insert(row - 1, item)
            self._reload_video_table_from_items(selected_row=row - 1)

    def _move_video_down(self) -> None:
        if not hasattr(self, "video_items") or not self.video_items:
            return
        row = self.current_video_idx
        if 0 <= row < len(self.video_items) - 1:
            item = self.video_items.pop(row)
            self.video_items.insert(row + 1, item)
            self._reload_video_table_from_items(selected_row=row + 1)

    def _reload_video_table_from_items(self, selected_row: Optional[int] = None) -> None:
        if not hasattr(self, "video_items"):
            return
        self.video_table.blockSignals(True)
        self.video_table.setRowCount(len(self.video_items))
        for row, item_data in enumerate(self.video_items):
            up_st = item_data.get("upload_status", "unloaded")
            is_uploaded = "đã tải" in up_st.lower() or up_st == "uploaded"
            is_pending = "chờ tải" in up_st.lower() or up_st == "pending"

            chk_item = QTableWidgetItem()
            chk_item.setCheckState(Qt.Checked if is_pending else Qt.Unchecked)
            chk_item.setData(Qt.UserRole, row)
            if is_uploaded:
                # Video đã hoàn thành: Khóa hoàn toàn checkbox
                chk_item.setFlags(chk_item.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsEnabled)
            else:
                chk_item.setFlags(chk_item.flags() & ~Qt.ItemIsEditable | Qt.ItemIsEnabled)
            self.video_table.setItem(row, 0, chk_item)

            badge = item_data.get("episode_badge", "")
            it_badge = QTableWidgetItem(badge)
            it_badge.setTextAlignment(Qt.AlignCenter)
            self.video_table.setItem(row, 1, it_badge)

            f_name = item_data.get("file_name", "")
            it_name = QTableWidgetItem(f_name)
            it_name.setToolTip(f_name)
            it_name.setFlags(it_name.flags() & ~Qt.ItemIsEditable)
            self.video_table.setItem(row, 2, it_name)

            it_title = QTableWidgetItem(item_data.get("title", ""))
            it_title.setToolTip(item_data.get("title", ""))
            self.video_table.setItem(row, 3, it_title)

            thumb_path = item_data.get("thumbnail_path")
            thumb_status = "✔ Đã có" if thumb_path else "Chưa tạo"
            it_thumb = QTableWidgetItem(thumb_status)
            it_thumb.setTextAlignment(Qt.AlignCenter)
            it_thumb.setFlags(it_thumb.flags() & ~Qt.ItemIsEditable)
            if thumb_path:
                it_thumb.setForeground(Qt.green)
            else:
                it_thumb.setForeground(Qt.gray)
            self.video_table.setItem(row, 4, it_thumb)

            sz_mb = item_data.get("size_mb", 0.0)
            it_sz = QTableWidgetItem(f"{sz_mb:.1f} MB")
            it_sz.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_sz.setFlags(it_sz.flags() & ~Qt.ItemIsEditable)
            self.video_table.setItem(row, 5, it_sz)

            # Col 6: Trạng thái Tải lên
            v_url = item_data.get("video_url", "")
            it_st = QTableWidgetItem(up_st)
            it_st.setTextAlignment(Qt.AlignCenter)
            it_st.setFlags(it_st.flags() & ~Qt.ItemIsEditable)
            if is_uploaded:
                it_st.setText("✅ Đã tải (Mở ↗)")
                it_st.setForeground(Qt.green)
                if v_url:
                    it_st.setToolTip(f"Bấm đúp để xem trên YouTube:\n{v_url}")
            elif is_pending:
                it_st.setText("🟡 Chờ tải lên")
                it_st.setForeground(Qt.yellow)
                it_st.setToolTip("Video trong hàng đợi sẵn sàng tải lên")
            elif "lỗi" in up_st.lower() or up_st == "error":
                it_st.setText("❌ Lỗi tải")
                it_st.setForeground(Qt.red)
                err = item_data.get("error_msg") or v_url
                if err:
                    it_st.setToolTip(f"Lỗi: {err}\n(Bấm 'Thử lại' hoặc chuột phải để tải lại)")
            elif "đang tải" in up_st.lower() or up_st.startswith("⏳"):
                it_st.setText(up_st)
                it_st.setForeground(Qt.cyan)
            else:
                it_st.setText("- Chưa tải")
                it_st.setForeground(Qt.gray)
            self.video_table.setItem(row, 6, it_st)

        self.video_table.blockSignals(False)

        if len(self.video_items) > 0:
            target_r = selected_row if (selected_row is not None and 0 <= selected_row < len(self.video_items)) else 0
            self._select_video_row(target_r)

    def _select_all_videos(self) -> None:
        self._set_selected_pending()

    def _unselect_all_videos(self) -> None:
        self._set_selected_unloaded()

    def _on_video_clicked(self, row: int, col: int) -> None:
        self._select_video_row(row)

    def _select_video_row(self, row: int) -> None:
        if row < 0 or row >= len(self.video_items):
            return
        self.current_video_idx = row
        item = self.video_items[row]

        badge_val = item.get("episode_badge", "")
        badge_prefix = f"[{badge_val}] " if badge_val else ""
        self.editing_video_label.setText(f"Đang chỉnh sửa: {badge_prefix}{item['file_name']}")

        self.title_edit.blockSignals(True)
        self.title_edit.setText(item.get("title", ""))
        self.title_edit.blockSignals(False)
        self._on_title_changed(item.get("title", ""))

        self.desc_edit.blockSignals(True)
        self.desc_edit.setText(item.get("description", ""))
        self.desc_edit.blockSignals(False)

        self.tags_edit.blockSignals(True)
        self.tags_edit.setText(item.get("tags", ""))
        self.tags_edit.blockSignals(False)

        self.thumb_badge_edit.blockSignals(True)
        self.thumb_badge_edit.setText(badge_val)
        self.thumb_badge_edit.blockSignals(False)

        self.thumb_hl_edit.blockSignals(True)
        saved_hl = item.get("thumbnail_hl")
        if not saved_hl or not item.get("user_edited_hl"):
            saved_hl = extract_highlight_from_title(item.get("title", "") or self.proj_combo.currentText())
            item["thumbnail_hl"] = saved_hl
        self.thumb_hl_edit.setText(saved_hl)
        self.thumb_hl_edit.blockSignals(False)

        # Cập nhật style/bố cục nếu tập này đã có cấu hình riêng
        if item.get("thumb_font"):
            idx_f = self.thumb_font_combo.findData(item["thumb_font"])
            if idx_f >= 0:
                self.thumb_font_combo.blockSignals(True)
                self.thumb_font_combo.setCurrentIndex(idx_f)
                self.thumb_font_combo.blockSignals(False)
        if item.get("thumb_pos"):
            idx_p = self.thumb_pos_combo.findData(item["thumb_pos"])
            if idx_p >= 0:
                self.thumb_pos_combo.blockSignals(True)
                self.thumb_pos_combo.setCurrentIndex(idx_p)
                self.thumb_pos_combo.blockSignals(False)
        if item.get("thumb_badge_pos"):
            idx_bp = self.thumb_badge_pos_combo.findData(item["thumb_badge_pos"])
            if idx_bp >= 0:
                self.thumb_badge_pos_combo.blockSignals(True)
                self.thumb_badge_pos_combo.setCurrentIndex(idx_bp)
                self.thumb_badge_pos_combo.blockSignals(False)

        # Cập nhật preview Thumbnail
        thumb_p = item.get("thumbnail_path")
        if thumb_p and Path(thumb_p).exists():
            self._set_thumbnail_preview(Path(thumb_p))
        else:
            self.thumb_preview.clear()
            badge_note = f"\n({badge_val})" if badge_val else ""
            self.thumb_preview.setText(f"Chưa có Thumbnail{badge_note}\nBấm '🎨 Ghép Thử Thumbnail Tập Này' để tạo preview")
            self.current_thumbnail_path = None

    def _on_title_changed(self, text: str) -> None:
        length = len(text)
        self.title_len_label.setText(f"{length}/100")
        if length > 95:
            self.title_len_label.setStyleSheet("color: red; font-weight: bold; font-size: 11px;")
        else:
            self.title_len_label.setStyleSheet("color: #888; font-size: 11px;")

        if 0 <= self.current_video_idx < len(self.video_items):
            self.video_items[self.current_video_idx]["title"] = text
            tbl_it = self.video_table.item(self.current_video_idx, 3)
            if tbl_it and tbl_it.text() != text:
                self.video_table.blockSignals(True)
                tbl_it.setText(text)
                tbl_it.setToolTip(text)
                self.video_table.blockSignals(False)

            # Tự động phân tích cụm chữ to nổi bật từ tiêu đề nếu người dùng chưa sửa thủ công
            if not self.video_items[self.current_video_idx].get("user_edited_hl"):
                new_hl = extract_highlight_from_title(text)
                self.thumb_hl_edit.blockSignals(True)
                self.thumb_hl_edit.setText(new_hl)
                self.thumb_hl_edit.blockSignals(False)
                self.video_items[self.current_video_idx]["thumbnail_hl"] = new_hl

    def _on_desc_changed(self) -> None:
        if 0 <= self.current_video_idx < len(self.video_items):
            self.video_items[self.current_video_idx]["description"] = self.desc_edit.toPlainText()

    def _on_tags_changed(self, text: str) -> None:
        if 0 <= self.current_video_idx < len(self.video_items):
            self.video_items[self.current_video_idx]["tags"] = text

    def _on_badge_changed(self, text: str) -> None:
        if 0 <= self.current_video_idx < len(self.video_items):
            val = text.strip()
            self.video_items[self.current_video_idx]["episode_badge"] = val
            tbl_it = self.video_table.item(self.current_video_idx, 1)
            if tbl_it and tbl_it.text() != val:
                self.video_table.blockSignals(True)
                tbl_it.setText(val)
                self.video_table.blockSignals(False)

    def _on_thumb_hl_changed(self, text: str) -> None:
        if 0 <= self.current_video_idx < len(self.video_items):
            self.video_items[self.current_video_idx]["thumbnail_hl"] = text.strip()
            self.video_items[self.current_video_idx]["user_edited_hl"] = True

    def _on_thumb_style_or_pos_changed(self) -> None:
        is_custom = (self.thumb_pos_combo.currentData() == "custom")
        self.custom_pos_box.setVisible(is_custom)
        if 0 <= self.current_video_idx < len(self.video_items):
            self.video_items[self.current_video_idx]["thumb_font"] = self.thumb_font_combo.currentData()
            self.video_items[self.current_video_idx]["thumb_pos"] = self.thumb_pos_combo.currentData()
            self.video_items[self.current_video_idx]["thumb_badge_pos"] = self.thumb_badge_pos_combo.currentData()
        self._save_ui_settings()
    def _on_enable_badge_toggled(self, checked: bool) -> None:
        self.thumb_badge_edit.setEnabled(checked)
        self.thumb_badge_pos_combo.setEnabled(checked)
        if not getattr(self, "_is_loading_settings", False):
            self._save_ui_settings()

    def _on_enable_hl_toggled(self, checked: bool) -> None:
        self.thumb_hl_edit.setEnabled(checked)
        self.thumb_font_combo.setEnabled(checked)
        self.thumb_pos_combo.setEnabled(checked)
        self.custom_pos_box.setEnabled(checked and self.thumb_pos_combo.currentData() == "custom")
        if not getattr(self, "_is_loading_settings", False):
            self._save_ui_settings()

    def _on_thumb_src_mode_changed(self) -> None:
        is_frame = self.rad_src_frame.isChecked()
        is_pl = self.rad_src_playlist.isChecked()
        is_cust = self.rad_src_custom.isChecked()

        self.frame_opt_widget.setVisible(is_frame)
        self.pl_opt_widget.setVisible(is_pl)
        self.cust_opt_widget.setVisible(is_cust)
        if not getattr(self, "_is_loading_settings", False):
            self._save_ui_settings()

    def _pick_playlist_thumbnail(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn 1 ảnh poster chung cho toàn bộ Playlist", "", "Hình ảnh (*.jpg *.jpeg *.png *.webp)"
        )
        if path:
            self._playlist_common_thumb = Path(path)
            self.lbl_pl_img_name.setText(f"✔ {self._playlist_common_thumb.name}")
            self.lbl_pl_img_name.setStyleSheet("color: #7ee787; font-weight: bold;")
            self._log(f"✔ Đã chọn ảnh nền chung cho toàn bộ Playlist: {self._playlist_common_thumb.name}")

    def _on_ai_gen_options_changed(self) -> None:
        self._update_ai_btn_text()
        self._save_ui_settings()

    def _update_ai_btn_text(self) -> None:
        if not hasattr(self, "btn_batch_ai_gen") or not hasattr(self, "chk_ai_gen_title"):
            return
        if self.chk_ai_gen_title.isChecked():
            self.btn_batch_ai_gen.setText("✨ Tự Động Sinh Tiêu Đề, Mô Tả & Tags Cho Các Tập Đã Chọn")
        else:
            self.btn_batch_ai_gen.setText("✨ Tự Động Sinh Mô Tả & Tags (Giữ Nguyên Tiêu Đề Gốc Video)")

    # ==========================
    # LOGIC: SINH NỘI DUNG AI
    # ==========================
    def _generate_all_content(self) -> None:
        selected_indices = []
        tasks = []
        raw_story_title = self.proj_combo.currentText()
        clean_title = clean_story_title(raw_story_title)

        for r in range(self.video_table.rowCount()):
            chk_it = self.video_table.item(r, 0)
            if chk_it and chk_it.checkState() == Qt.Checked and r < len(self.video_items):
                item = self.video_items[r]
                selected_indices.append(r)
                bdg = item.get("episode_badge", "")
                tasks.append({
                    "file_name": item.get("file_name", ""),
                    "story_title": clean_title or item.get("title") or item["file_name"],
                    "original_title": item.get("title", ""),
                    "episode_badge": bdg,
                    "episode_index": item.get("episode_index"),
                    "description": item.get("description", ""),
                    "tags": item.get("tags", ""),
                    "thumbnail_hl": item.get("thumbnail_hl", ""),
                    "ai_image_prompt": item.get("ai_image_prompt", ""),
                })

        if not tasks:
            QMessageBox.warning(self, "Chưa chọn video", "Vui lòng tích chọn ít nhất 1 video để tạo nội dung.")
            return

        provider = self.ai_provider_combo.currentData()
        api_key = ""
        model = ""
        custom_url = ""

        if provider == "gemini":
            api_key = self.gemini_key_edit.text().strip()
            model = self.gemini_model_combo.currentText().strip()
            if not api_key:
                QMessageBox.warning(
                    self, "Thiếu Gemini API Key",
                    "Vui lòng nhập Gemini API Key từ Google AI Studio (bấm 'Lấy Key Free') hoặc chuyển sang chế độ 'Offline Smart SEO' để dùng miễn phí không cần Key."
                )
        elif provider == "9router":
            api_key = self.nine_key_edit.text().strip()
            custom_url = self.nine_url_edit.text().strip()
            model = self.nine_model_combo.currentText().strip()
            if not api_key:
                QMessageBox.warning(self, "Thiếu API Key", "Vui lòng nhập API Key từ 9Router.")
                return
        elif provider == "custom":
            api_key = self.custom_key_edit.text().strip()
            custom_url = self.custom_url_edit.text().strip()
            model = self.custom_model_edit.text().strip()
            if not api_key:
                QMessageBox.warning(self, "Thiếu API Key", "Vui lòng nhập API Key cho Custom Provider.")
                return

        ch_name = self.channel_combo.currentText().split("(")[0].strip()

        self.btn_batch_ai_gen.setEnabled(False)
        self.btn_batch_ai_gen.setText(f"⏳ Đang tạo nội dung cho {len(tasks)} tập...")

        target_lang = self.ai_target_lang_combo.currentData() or "vi"
        gen_title = self.chk_ai_gen_title.isChecked()
        gen_desc = self.chk_ai_gen_desc.isChecked()
        gen_tags = self.chk_ai_gen_tags.isChecked()
        gen_thumb = self.chk_ai_gen_thumb.isChecked()

        self._content_worker = ContentWorker(
            provider=provider,
            api_key=api_key,
            model=model,
            custom_base_url=custom_url,
            tasks=tasks,
            channel_name=ch_name,
            target_language=target_lang,
            gen_title=gen_title,
            gen_desc=gen_desc,
            gen_tags=gen_tags,
            gen_thumb=gen_thumb,
        )

        def on_item_finished(task_idx: int, ok: bool, msg: str, data: dict) -> None:
            if task_idx < len(selected_indices):
                row_idx = selected_indices[task_idx]
                if ok and data:
                    item = self.video_items[row_idx]
                    self.video_table.blockSignals(True)
                    if gen_title and "title" in data and data["title"]:
                        item["title"] = data["title"]
                        self.video_table.setItem(row_idx, 3, QTableWidgetItem(data["title"]))
                    if gen_desc and "description" in data:
                        item["description"] = data["description"]
                    if gen_tags and "tags" in data:
                        item["tags"] = data["tags"]
                    if gen_thumb and "thumbnail_badge" in data:
                        raw_bdg = data["thumbnail_badge"]
                        if item.get("episode_badge"):
                            badge = clean_episode_badge(raw_bdg, fallback_idx=None) or item["episode_badge"]
                        else:
                            badge = ""
                        item["episode_badge"] = badge
                        self.video_table.setItem(row_idx, 1, QTableWidgetItem(badge))
                    self.video_table.blockSignals(False)

                    if gen_thumb:
                        hl_val = data.get("thumbnail_highlight")
                        if not hl_val or " - " not in hl_val:
                            hl_val = extract_highlight_from_title(item.get("title", ""))
                        item["thumbnail_hl"] = hl_val
                        item["thumbnail_highlight"] = hl_val
                        item["user_edited_hl"] = False

                        if "thumbnail_ai_prompt" in data and data["thumbnail_ai_prompt"]:
                            item["ai_image_prompt"] = data["thumbnail_ai_prompt"].strip()

                    if row_idx == self.current_video_idx:
                        self._select_video_row(row_idx)
                        self.thumb_hl_edit.blockSignals(True)
                        self.thumb_hl_edit.setText(hl_val)
                        self.thumb_hl_edit.blockSignals(False)

                    bdg_tag = f"[{item['episode_badge']}] " if item.get('episode_badge') else ""
                    self._log(f"✔ Đã tạo nội dung cho {bdg_tag}{item['title']}")
                else:
                    self._log(f"⚠ Lỗi tạo tập {task_idx+1}: {msg}")

        def on_all_finished() -> None:
            self.btn_batch_ai_gen.setEnabled(True)
            self._update_ai_btn_text()
            QMessageBox.information(self, "Hoàn thành", f"Đã sinh xong nội dung SEO chuẩn cho {len(tasks)} tập video!")

        self._content_worker.item_finished_sig.connect(on_item_finished)
        self._content_worker.all_finished_sig.connect(on_all_finished)
        self._content_worker.start()

    # Giữ hàm đơn cho nút bấm cũ nếu cần
    def _generate_with_gemini(self) -> None:
        self._generate_all_content()

    def _copy_current_episode_info(self) -> None:
        if not hasattr(self, "video_items") or self.current_video_idx < 0 or self.current_video_idx >= len(self.video_items):
            QMessageBox.warning(self, "Chưa chọn tập", "Vui lòng chọn 1 tập video trong bảng để sao chép thông tin.")
            return

        item = self.video_items[self.current_video_idx]
        badge = item.get("episode_badge", "")
        title = item.get("title", "")
        thumb_hl = item.get("thumbnail_hl", "")
        prompt = item.get("ai_image_prompt", "")
        desc = item.get("description", "")
        tags = item.get("tags", "")

        lines = []
        if badge:
            lines.append(f"Tập: {badge}")
        lines.append(f"Tiêu đề: {title}")
        if thumb_hl:
            lines.append(f"Chữ nổi bật Thumbnail: {thumb_hl}")
        if prompt:
            lines.append(f"Prompt tạo ảnh AI:\n{prompt}")
        if desc:
            lines.append(f"Mô tả:\n{desc}")
        if tags:
            lines.append(f"Tags: {tags}")

        clipboard_text = "\n\n".join(lines)
        QApplication.clipboard().setText(clipboard_text)
        self._log(f"📋 Đã sao chép toàn bộ thông tin & Prompt của tập {badge or (self.current_video_idx + 1)} vào bộ nhớ tạm.")
        QMessageBox.information(
            self,
            "Đã sao chép",
            f"Đã sao chép thông tin tập {badge or (self.current_video_idx + 1)} vào Clipboard!\nBạn có thể dán (Ctrl+V) ngay sang Midjourney, Photoshop, Canva, v.v."
        )

    def _export_to_csv(self) -> None:
        if not hasattr(self, "video_items") or not self.video_items:
            QMessageBox.warning(self, "Chưa có dữ liệu", "Danh sách video đang trống. Vui lòng chọn dự án hoặc thêm video trước khi xuất CSV.")
            return

        # Kiểm tra các tập đang được tick chọn
        selected_rows = []
        for r in range(self.video_table.rowCount()):
            chk_it = self.video_table.item(r, 0)
            if chk_it and chk_it.checkState() == Qt.Checked and r < len(self.video_items):
                selected_rows.append(r)

        # Nếu không có tập nào tick thì xuất toàn bộ bảng
        if not selected_rows:
            target_indices = list(range(len(self.video_items)))
            scope_desc = f"toàn bộ {len(target_indices)} tập"
        else:
            target_indices = selected_rows
            scope_desc = f"{len(target_indices)} tập đã chọn"

        # Gợi ý tên file mặc định theo tên dự án / truyện
        raw_title = self.proj_combo.currentText().strip() or "youtube_videos"
        safe_title = re.sub(r'[\\/*?:"<>|]', "", raw_title).strip().replace(" ", "_")
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"{safe_title}_metadata_{ts}.csv"

        default_dir = ""
        if getattr(self, "_current_project_dir", None) and self._current_project_dir.exists():
            default_dir = str(self._current_project_dir)
        elif self.video_items and self.video_items[0].get("video_path"):
            default_dir = str(Path(self.video_items[0]["video_path"]).parent)

        initial_path = os.path.join(default_dir, default_filename) if default_dir else default_filename
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Lưu danh sách {scope_desc} ra file CSV",
            initial_path,
            "CSV Files (*.csv);;All Files (*.*)"
        )
        if not file_path:
            return

        try:
            # Ghi file chuẩn utf-8-sig (BOM) để Microsoft Excel trên Windows tự nhận dạng Unicode không bị lỗi font
            with open(file_path, mode="w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                # Header row
                writer.writerow([
                    "STT",
                    "Tập",
                    "Tiêu đề YouTube",
                    "Chữ nổi bật Thumbnail",
                    "Prompt tạo ảnh AI",
                    "Mô tả (Description)",
                    "Thẻ từ khóa (Tags)",
                    "Tên file MP4",
                    "Đường dẫn video",
                    "Ảnh Thumbnail hiện tại",
                ])

                for out_stt, idx in enumerate(target_indices, start=1):
                    item = self.video_items[idx]
                    writer.writerow([
                        out_stt,
                        item.get("episode_badge", ""),
                        item.get("title", ""),
                        item.get("thumbnail_hl", ""),
                        item.get("ai_image_prompt", ""),
                        item.get("description", ""),
                        item.get("tags", ""),
                        item.get("file_name", ""),
                        item.get("video_path", ""),
                        item.get("thumbnail_path", "") or "",
                    ])

            self._log(f"✔ Đã xuất thành công {len(target_indices)} tập ra file CSV: {file_path}")

            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Xuất CSV Thành Công")
            msg_box.setText(f"Đã xuất thành công <b>{len(target_indices)} tập</b> ra file CSV!<br><br><b>Đường dẫn:</b><br><code>{file_path}</code>")
            msg_box.setIcon(QMessageBox.Information)

            btn_open_file = msg_box.addButton("📊 Mở File CSV (Excel)", QMessageBox.ActionRole)
            btn_open_folder = msg_box.addButton("📁 Mở Thư Mục", QMessageBox.ActionRole)
            msg_box.addButton("Đóng", QMessageBox.RejectRole)

            msg_box.exec()

            if msg_box.clickedButton() == btn_open_file:
                try:
                    os.startfile(file_path)
                except Exception as e:
                    QMessageBox.warning(self, "Không thể mở file", f"Lỗi mở file:\n{e}")
            elif msg_box.clickedButton() == btn_open_folder:
                try:
                    os.startfile(os.path.dirname(file_path))
                except Exception as e:
                    QMessageBox.warning(self, "Không thể mở thư mục", f"Lỗi mở thư mục:\n{e}")

        except Exception as e:
            QMessageBox.critical(self, "Lỗi xuất CSV", f"Không thể ghi file CSV:\n{e}")

    # ==========================
    # LOGIC: THUMBNAIL STUDIO
    # ==========================
    def _create_single_thumbnail(self, silent: bool = False) -> None:
        if self.current_video_idx < 0 or self.current_video_idx >= len(self.video_items):
            if not silent:
                QMessageBox.warning(self, "Chưa chọn tập", "Vui lòng chọn 1 tập trong bảng để tạo Thumbnail.")
            return

        item = self.video_items[self.current_video_idx]
        v_path = Path(item.get("video_path", ""))
        out_dir = self._current_project_dir or Path("D:/auto_video_renderer/auto_video_renderer/temp")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_thumb = out_dir / f"thumbnail_tap_{self.current_video_idx+1}.jpg"

        # 1. Xác định ảnh nền theo nguồn đã chọn
        bg_img: Optional[Path] = None
        if self.rad_src_frame.isChecked():
            if v_path.exists():
                try:
                    sec = self.spin_frame_sec.value()
                    frame_out = out_dir / f"frame_tap_{self.current_video_idx+1}.jpg"
                    bg_img = ThumbnailBuilder.extract_frame_from_video(v_path, time_sec=sec, out_path=frame_out)
                except Exception as ex_frame:
                    if not silent:
                        QMessageBox.warning(self, "Lỗi trích xuất frame", f"Không thể trích xuất frame từ video: {ex_frame}")
                    return
            else:
                if not silent:
                    QMessageBox.warning(self, "Lỗi video", f"Không tìm thấy file video: {v_path}")
                return
        elif self.rad_src_playlist.isChecked():
            if self._playlist_common_thumb and Path(self._playlist_common_thumb).exists():
                bg_img = Path(self._playlist_common_thumb)
            else:
                if not silent:
                    QMessageBox.warning(self, "Chưa chọn ảnh Playlist", "Vui lòng bấm '📁 Chọn ảnh chung cho Playlist' trước.")
                return
        else: # rad_src_custom
            if item.get("custom_thumb_bg") and Path(item["custom_thumb_bg"]).exists():
                bg_img = Path(item["custom_thumb_bg"])
            elif item.get("thumbnail_path") and Path(item["thumbnail_path"]).exists():
                bg_img = Path(item["thumbnail_path"])
            else:
                candidates = list(self._current_project_media)
                if not candidates and self._current_project_dir and self._current_project_dir.exists():
                    candidates = sorted(list(self._current_project_dir.glob("*.png")) + list(self._current_project_dir.glob("*.jpg")))
                if not candidates:
                    candidates = [Path(m) for m in self.settings.get("media_files", []) if Path(m).exists()]
                if candidates:
                    bg_img = candidates[self.current_video_idx % len(candidates)]

        if not bg_img or not bg_img.exists():
            if not silent:
                QMessageBox.warning(self, "Thiếu ảnh nền", "Không tìm thấy ảnh nền phù hợp để ghép thumbnail.")
            return

        badge = self.thumb_badge_edit.text().strip() or item.get("episode_badge") or ""
        hl = self.thumb_hl_edit.text().strip() or item.get("thumbnail_hl") or extract_highlight_from_title(item.get("title", "") or self.proj_combo.currentText())
        ch_name = self.channel_combo.currentText().split("(")[0].strip()

        badge_pos = self.thumb_badge_pos_combo.currentData() or "top_left"
        font_style = self.thumb_font_combo.currentData() or "drama"
        position = self.thumb_pos_combo.currentData() or "split_lr"
        pos_x = self.thumb_x_spin.value() if position == "custom" else None
        pos_y = self.thumb_y_spin.value() if position == "custom" else None
        font_scale = (self.thumb_scale_spin.value() / 100.0) if position == "custom" else 0.68

        enable_badge = self.chk_enable_badge.isChecked() if hasattr(self, "chk_enable_badge") else True
        enable_hl = self.chk_enable_hl.isChecked() if hasattr(self, "chk_enable_hl") else True

        try:
            res_path = ThumbnailBuilder.create_thumbnail(
                bg_image=bg_img,
                output_path=out_thumb,
                badge_text=badge,
                highlight_title=hl,
                subtitle=ch_name,
                font_style=font_style,
                position=position,
                pos_x=pos_x,
                pos_y=pos_y,
                font_scale=font_scale,
                badge_position=badge_pos,
                enable_badge=enable_badge,
                enable_highlight=enable_hl,
            )
            item["thumbnail_path"] = str(res_path)
            self._set_thumbnail_preview(res_path)

            it_tb = QTableWidgetItem("✔ Đã tạo")
            it_tb.setTextAlignment(Qt.AlignCenter)
            it_tb.setForeground(Qt.green)
            self.video_table.setItem(self.current_video_idx, 4, it_tb)
            if not silent:
                self._log(f"✔ Đã tạo Thumbnail cho [{badge}]: {res_path.name}")
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "Lỗi tạo Thumbnail", str(e))

    def _on_thumb_source_changed(self) -> None:
        self._update_thumb_source_visibility()

    def _update_thumb_source_visibility(self) -> None:
        if hasattr(self, "custom_thumb_box"):
            self.custom_thumb_box.setVisible(True)
        if hasattr(self, "_on_thumb_src_mode_changed"):
            self._on_thumb_src_mode_changed()

    def _add_sample_images(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Chọn 1 đến 3 ảnh mẫu tham khảo (Vision AI)", "", "Hình ảnh (*.jpg *.jpeg *.png *.webp)"
        )
        if files:
            for f in files:
                p = Path(f)
                if len(self.sample_image_paths) < 3 and p not in self.sample_image_paths:
                    self.sample_image_paths.append(p)
            self._refresh_sample_previews()
            idx_drama = self.thumb_font_combo.findData("drama")
            if idx_drama >= 0:
                self.thumb_font_combo.setCurrentIndex(idx_drama)

    def _clear_sample_images(self) -> None:
        self.sample_image_paths.clear()
        self._refresh_sample_previews()

    def _refresh_sample_previews(self) -> None:
        while self.lay_sample_previews.count():
            it = self.lay_sample_previews.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

        if not self.sample_image_paths:
            lbl = QLabel("Chưa chọn ảnh mẫu (Tùy chọn - AI sẽ vẽ ảnh tự do theo Tiêu đề & Mô tả)")
            lbl.setStyleSheet("color: #888; font-size: 10px; font-style: italic;")
            self.lay_sample_previews.addWidget(lbl)
            return

        for idx, p in enumerate(self.sample_image_paths):
            lbl_img = QLabel()
            lbl_img.setFixedSize(70, 42)
            lbl_img.setStyleSheet("border: 1px solid #58a6ff; border-radius: 4px; background-color: #000;")
            lbl_img.setAlignment(Qt.AlignCenter)
            pix = QPixmap(str(p))
            if not pix.isNull():
                lbl_img.setPixmap(pix.scaled(68, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            lbl_img.setToolTip(f"Ảnh mẫu {idx+1}: {p.name}")
            self.lay_sample_previews.addWidget(lbl_img)
        self.lay_sample_previews.addStretch(1)

    def _generate_ai_prompt(self) -> None:
        if self.current_video_idx < 0 or self.current_video_idx >= len(self.video_items):
            QMessageBox.warning(self, "Chưa chọn tập", "Vui lòng chọn 1 tập video trong bảng để tạo Prompt.")
            return

        item = self.video_items[self.current_video_idx]
        title = item.get("title") or self.title_edit.text() or self.proj_combo.currentText()
        desc = item.get("description") or self.desc_edit.toPlainText()

        provider = self.ai_provider_combo.currentData() or "9router"
        api_key = ""
        model = ""
        custom_url = ""
        if provider == "gemini":
            api_key = self.gemini_key_edit.text().strip()
            model = self.gemini_model_combo.currentText().strip()
        elif provider == "9router":
            api_key = self.nine_key_edit.text().strip()
            model = self.nine_model_combo.currentText().strip()
            custom_url = self.nine_url_edit.text().strip()
        elif provider == "custom":
            api_key = self.custom_key_edit.text().strip()
            model = self.custom_model_edit.text().strip()
            custom_url = self.custom_url_edit.text().strip()

        self.btn_gen_ai_prompt.setEnabled(False)
        self.btn_gen_ai_prompt.setText("⏳ Đang phân tích Vision...")
        QApplication.processEvents()

        channel_name = self.channel_combo.currentText().strip() if self.channel_combo.count() > 0 else ""
        target_lang = self.ai_target_lang_combo.currentData() or "vi"

        try:
            prompt = ThumbnailPromptGenerator.generate_prompt(
                title=title,
                description=desc,
                sample_images=self.sample_image_paths,
                provider=provider,
                api_key=api_key,
                model=model,
                custom_base_url=custom_url,
                channel_name=channel_name,
                target_language=target_lang,
            )
            self.ai_prompt_edit.setPlainText(prompt)
            item["ai_image_prompt"] = prompt
            self._log(f"✔ Đã tạo Prompt AI bám sát ảnh mẫu & tiêu đề cho tập {self.current_video_idx + 1}")
        except Exception as e:
            QMessageBox.warning(self, "Lỗi tạo Prompt", f"Không thể tạo Prompt:\n{e}")
        finally:
            self.btn_gen_ai_prompt.setEnabled(True)
            self.btn_gen_ai_prompt.setText("✨ Phân Tích Vision & Tự Sinh Prompt")

    def _on_ai_prompt_changed(self) -> None:
        if 0 <= self.current_video_idx < len(self.video_items):
            self.video_items[self.current_video_idx]["ai_image_prompt"] = self.ai_prompt_edit.toPlainText().strip()

    def _generate_ai_thumb_single(self) -> None:
        if self.current_video_idx < 0 or self.current_video_idx >= len(self.video_items):
            QMessageBox.warning(self, "Chưa chọn tập", "Vui lòng chọn 1 tập video trong bảng để tạo ảnh Thumbnail AI.")
            return

        item = self.video_items[self.current_video_idx]
        prompt = self.ai_prompt_edit.toPlainText().strip()
        if not prompt or (self.sample_image_paths and "Part 1" not in prompt and "foreground on the right" not in prompt):
            self._generate_ai_prompt()
            prompt = self.ai_prompt_edit.toPlainText().strip()
            if not prompt:
                QMessageBox.warning(self, "Thiếu Prompt", "Vui lòng nhập hoặc sinh Prompt tiếng Anh trước khi tạo ảnh.")
                return

        out_dir = self._current_project_dir or Path("D:/auto_video_renderer/auto_video_renderer/temp")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_thumb = out_dir / f"thumbnail_ai_tap_{self.current_video_idx + 1}.jpg"

        model_id = self.ai_img_model_combo.currentData() or "flux"
        api_key = self.gemini_key_edit.text().strip() if model_id == "imagen-3" else self.custom_key_edit.text().strip()
        base_url = self.custom_url_edit.text().strip()

        self.btn_gen_ai_single.setEnabled(False)
        self.btn_gen_ai_single.setText("⏳ Đang vẽ ảnh AI...")
        cur_idx = self.current_video_idx

        def on_done(ok: bool, msg: str, path_str: str) -> None:
            self.btn_gen_ai_single.setEnabled(True)
            self.btn_gen_ai_single.setText("🎨 Tạo Ảnh AI Cho Tập Này")
            if ok and path_str:
                p = Path(path_str)
                # Tự động lồng chữ Tiếng Việt nghệ thuật & huy hiệu lên thumbnail
                try:
                    title_val = item.get("title", "")
                    hl_val = item.get("thumbnail_highlight") or item.get("thumbnail_hl") or self.thumb_hl_edit.text().strip() or extract_highlight_from_title(title_val)
                    badge_val = item.get("episode_badge") or self.thumb_badge_edit.text().strip() or f"TẬP {cur_idx + 1}"
                    font_st = "drama" if (self.sample_image_paths or self.thumb_font_combo.currentData() in ("drama", None)) else (self.thumb_font_combo.currentData() or "drama")
                    pos_st = self.thumb_pos_combo.currentData() or "split_lr"
                    channel_name = self.channel_combo.currentText().strip() if (hasattr(self, "channel_combo") and self.channel_combo.count() > 0) else "Gã Đạo Tặc"
                    ThumbnailBuilder.create_thumbnail(
                        bg_image=p,
                        output_path=p,
                        badge_text=badge_val,
                        highlight_title=hl_val,
                        subtitle=channel_name,
                        font_style=font_st,
                        position=pos_st,
                    )
                except Exception as ex_st:
                    self._log(f"⚠ Lỗi lồng chữ Tiếng Việt: {ex_st}")
                item["thumbnail_path"] = str(p)
                item["is_ai_thumbnail"] = True
                if cur_idx == self.current_video_idx:
                    self._set_thumbnail_preview(p)
                it_tb = QTableWidgetItem("✔ Đã tạo AI")
                it_tb.setTextAlignment(Qt.AlignCenter)
                it_tb.setForeground(Qt.green)
                self.video_table.setItem(cur_idx, 4, it_tb)
                self._log(f"✔ Đã tạo thành công ảnh Thumbnail AI cho tập {cur_idx + 1}: {p.name}")
                self.rad_thumb_ai.setChecked(True)
                self._update_thumb_source_visibility()
            else:
                QMessageBox.critical(self, "Lỗi tạo ảnh AI", f"Không thể tạo ảnh AI:\n{msg}")
                self._log(f"❌ Lỗi tạo ảnh AI tập {cur_idx + 1}: {msg}")

        self._ai_img_worker = AIImageWorker(
            prompt=prompt,
            output_path=out_thumb,
            model_name=model_id,
            api_key=api_key,
            base_url=base_url,
        )
        self._ai_img_worker.finished_sig.connect(on_done)
        self._ai_img_worker.start()

    def _generate_ai_thumb_batch(self) -> None:
        if not self.video_items:
            QMessageBox.warning(self, "Chưa có video", "Không có video nào trong danh sách để tạo Thumbnail AI.")
            return

        selected_indices = [
            r for r in range(self.video_table.rowCount())
            if self.video_table.item(r, 0) and self.video_table.item(r, 0).checkState() == Qt.Checked
        ]
        if not selected_indices:
            QMessageBox.warning(self, "Chưa chọn video", "Vui lòng tích chọn ít nhất 1 video để tạo ảnh AI.")
            return

        out_dir = self._current_project_dir or Path("D:/auto_video_renderer/auto_video_renderer/temp")
        out_dir.mkdir(parents=True, exist_ok=True)

        ch_name_str = self.channel_combo.currentText().strip() if self.channel_combo.count() > 0 else ""
        tasks = []
        for r_idx in selected_indices:
            it = self.video_items[r_idx]
            p_file = out_dir / f"thumbnail_ai_tap_{r_idx + 1}.jpg"
            tasks.append({
                "row_idx": r_idx,
                "item": it,
                "out_path": p_file,
                "prompt": it.get("ai_image_prompt", ""),
                "title": it.get("title", ""),
                "desc": it.get("description", ""),
                "channel_name": ch_name_str,
                "font_style": "drama" if self.sample_image_paths else (self.thumb_font_combo.currentData() or "drama"),
                "position": self.thumb_pos_combo.currentData() or "split_lr",
            })

        model_id = self.ai_img_model_combo.currentData() or "flux"
        api_key = self.gemini_key_edit.text().strip() if model_id == "imagen-3" else self.custom_key_edit.text().strip()
        base_url = self.custom_url_edit.text().strip()
        provider = self.ai_provider_combo.currentData() or "9router"

        self.btn_gen_ai_batch.setEnabled(False)
        self.btn_gen_ai_batch.setText(f"⏳ Đang vẽ ảnh AI cho {len(tasks)} tập...")

        def on_progress(cur: int, tot: int, text: str) -> None:
            self._log(f"[{cur}/{tot}] {text}")

        def on_item_done(row_idx: int, ok: bool, msg: str, path_str: str) -> None:
            if ok and path_str:
                p = Path(path_str)
                self.video_items[row_idx]["thumbnail_path"] = str(p)
                self.video_items[row_idx]["is_ai_thumbnail"] = True
                it_tb = QTableWidgetItem("✔ Đã tạo AI")
                it_tb.setTextAlignment(Qt.AlignCenter)
                it_tb.setForeground(Qt.green)
                self.video_table.setItem(row_idx, 4, it_tb)
                if row_idx == self.current_video_idx:
                    self._set_thumbnail_preview(p)
                self._log(f"✔ Đã tạo Thumbnail AI tập {row_idx + 1}: {p.name}")
            else:
                self._log(f"❌ Lỗi tạo Thumbnail AI tập {row_idx + 1}: {msg}")

        def on_all_done() -> None:
            self.btn_gen_ai_batch.setEnabled(True)
            self.btn_gen_ai_batch.setText("🚀 Tự Động Tạo Ảnh AI Cho Tất Cả Tập Đã Chọn")
            QMessageBox.information(self, "Hoàn thành", f"Đã hoàn thành tạo ảnh Thumbnail AI cho {len(tasks)} tập video!")

        auto_stamp = True
        target_lang = self.ai_target_lang_combo.currentData() or "vi"
        self._batch_img_worker = BatchAIImageWorker(
            tasks=tasks,
            model_name=model_id,
            api_key=api_key,
            base_url=base_url,
            provider=provider,
            sample_images=self.sample_image_paths,
            auto_stamp=bool(auto_stamp),
            target_language=target_lang,
        )
        self._batch_img_worker.progress_sig.connect(on_progress)
        self._batch_img_worker.item_done_sig.connect(on_item_done)
        self._batch_img_worker.all_done_sig.connect(on_all_done)
        self._batch_img_worker.start()

    def _pick_batch_custom_thumbnails(self) -> None:
        if not self.video_items:
            QMessageBox.warning(self, "Chưa có video", "Không có video nào trong danh sách để gán ảnh.")
            return

        files, _ = QFileDialog.getOpenFileNames(
            self, "Chọn danh sách ảnh có sẵn theo thứ tự video", "", "Hình ảnh (*.jpg *.jpeg *.png *.webp)"
        )
        if not files:
            return

        # Sắp xếp tự nhiên (natural sort: tap_1.jpg, tap_2.jpg, tap_10.jpg)
        import re
        def natural_key(p_str: str):
            stem = Path(p_str).stem.lower()
            return [int(text) if text.isdigit() else text for text in re.split(r'(\d+)', stem)]

        sorted_files = sorted(files, key=natural_key)

        count = 0
        for i, f_path in enumerate(sorted_files):
            if i < len(self.video_items):
                p = Path(f_path)
                self.video_items[i]["thumbnail_path"] = str(p)
                self.video_items[i]["is_ai_thumbnail"] = False
                it_tb = QTableWidgetItem("✔ Đã có")
                it_tb.setTextAlignment(Qt.AlignCenter)
                it_tb.setForeground(Qt.green)
                self.video_table.setItem(i, 4, it_tb)
                count += 1

        if 0 <= self.current_video_idx < len(self.video_items):
            cur_p = self.video_items[self.current_video_idx].get("thumbnail_path")
            if cur_p and Path(cur_p).exists():
                self._set_thumbnail_preview(Path(cur_p))

        self._log(f"✔ Đã nạp và gán {count} ảnh có sẵn khớp 1-1 theo thứ tự video trong danh sách.")
        QMessageBox.information(
            self, "Thành công",
            f"Đã nạp và tự động sắp xếp {count} ảnh có sẵn khớp chính xác theo thứ tự các tập video!"
        )

    def _pick_custom_thumbnail(self) -> None:
        if self.current_video_idx < 0 or self.current_video_idx >= len(self.video_items):
            QMessageBox.warning(self, "Chưa chọn tập", "Vui lòng chọn 1 tập trong bảng để gắn Thumbnail.")
            return

        path, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh Thumbnail", "", "Hình ảnh (*.jpg *.jpeg *.png *.webp)")
        if path:
            p = Path(path)
            self.video_items[self.current_video_idx]["thumbnail_path"] = str(p)
            self.video_items[self.current_video_idx]["is_ai_thumbnail"] = False
            self._set_thumbnail_preview(p)
            it_tb = QTableWidgetItem("✔ Đã chọn")
            it_tb.setTextAlignment(Qt.AlignCenter)
            it_tb.setForeground(Qt.green)
            self.video_table.setItem(self.current_video_idx, 4, it_tb)

    def _set_thumbnail_preview(self, path: Path) -> None:
        self.current_thumbnail_path = path
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            lbl_w = max(self.thumb_preview.width() - 8, 480)
            lbl_h = max(self.thumb_preview.height() - 8, 270)
            scaled = pixmap.scaled(lbl_w, lbl_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.thumb_preview.setPixmap(scaled)

    def _on_privacy_changed(self, idx: int) -> None:
        self.schedule_box.setVisible(idx == 0)

    def _reload_playlists(self) -> None:
        ch_id = self.channel_combo.currentData()
        if not ch_id:
            return
        self.playlist_combo.clear()
        pls = self.uploader.list_playlists(ch_id)
        for p in pls:
            self.playlist_combo.addItem(p["title"], p["id"])

    # ==========================
    # LOGIC: UPLOAD PIPELINE
    # ==========================
    def _start_upload(self) -> None:
        ch_id = self.channel_combo.currentData()
        if not ch_id:
            QMessageBox.warning(self, "Chưa chọn kênh", "Vui lòng chọn hoặc thêm kênh YouTube trước khi đăng.")
            return

        selected_tasks_info = []
        for r in range(self.video_table.rowCount()):
            if r >= len(self.video_items):
                continue
            item = self.video_items[r]
            st = str(item.get("upload_status", "unloaded")).lower()
            it = self.video_table.item(r, 0)
            is_checked = (it is not None and it.checkState() == Qt.Checked)

            # Bỏ qua tuyệt đối các video đã tải hoàn thành để tránh spam/trùng lặp
            if "uploaded" in st or "đã tải" in st:
                continue

            # Điều kiện đưa vào hàng đợi: có trạng thái Pending HOẶC được Checkbox tích chọn
            if "pending" in st or "chờ tải" in st or is_checked:
                selected_tasks_info.append((r, item))

        if not selected_tasks_info:
            QMessageBox.warning(
                self, "Không có video chờ tải",
                "Không tìm thấy video nào ở trạng thái '🟡 Chờ tải lên'.\n\n"
                "👉 Hãy tích chọn video hoặc bấm '🟡 Đặt Chờ Tải Lên' để đưa video vào hàng đợi tải lên."
            )
            return

        # Chuẩn bị cấu hình Định danh Quốc gia (Geo-Targeting & Localization)
        c_key = self.country_combo.currentData() or "ph"
        c_info = PRESET_COUNTRIES.get(c_key, PRESET_COUNTRIES.get("ph", {}))
        geo_config = {
            "country_key": c_key,
            "language_code": c_info.get("language_code", "tl"),
            "audio_language": c_info.get("audio_language", "tl"),
            "tz_offset": c_info.get("tz_offset", 8.0),
            "enable_geo": self.chk_enable_geo.isChecked(),
            "location_name": self.geo_location_edit.text().strip() or c_info.get("location_name", ""),
            "latitude": c_info.get("latitude"),
            "longitude": c_info.get("longitude"),
        }

        # Chuẩn bị cấu hình Giãn cách chống Spam (Cooldown)
        cooldown_config = {
            "enabled": self.chk_anti_spam.isChecked(),
            "min_sec": self.spin_spam_min.value(),
            "max_sec": self.spin_spam_max.value(),
        }

        privacy_idx = self.privacy_combo.currentIndex()
        privacy_status = "schedule" if privacy_idx == 0 else (
            "public" if privacy_idx == 1 else ("unlisted" if privacy_idx == 2 else "private")
        )

        schedule_dts = []
        if privacy_status == "schedule":
            start_date = self.sch_date_edit.date().toPython()
            time_slots = [s.strip() for s in self.sch_slots_edit.text().split(",") if s.strip()]
            schedule_dts = YouTubeUploader.calculate_schedule_slots(
                start_date, time_slots, len(selected_tasks_info),
                tz_offset_hours=geo_config["tz_offset"]
            )

        # Xác định tùy chọn Playlist
        pl_name = None
        pl_id = None
        if self.chk_use_playlist.isChecked():
            if self.rad_existing_pl.isChecked():
                pl_id = self.playlist_combo.currentData()
            else:
                pl_name = self.new_playlist_edit.text().strip()
                if not pl_name:
                    pl_name = clean_story_title(self.proj_combo.currentText())

        is_premiere = self.premiere_chk.isChecked()
        ch_name = self.channel_combo.currentText().split("(")[0].strip()

        # Chuẩn bị cấu hình AI SEO tự động
        provider = self.ai_provider_combo.currentData() or "offline"
        api_key = ""
        model = ""
        custom_url = ""
        if provider == "gemini":
            api_key = self.gemini_key_edit.text().strip()
            model = self.gemini_model_combo.currentText().strip()
        elif provider == "9router":
            api_key = self.nine_key_edit.text().strip()
            model = self.nine_model_combo.currentText().strip()
            custom_url = self.nine_url_edit.text().strip()
        elif provider == "custom":
            api_key = self.custom_key_edit.text().strip()
            model = self.custom_model_edit.text().strip()
            custom_url = self.custom_url_edit.text().strip()

        target_lang = self.ai_target_lang_combo.currentData() or "vi"
        ai_config = {
            "provider": provider,
            "api_key": api_key,
            "model": model,
            "custom_base_url": custom_url,
            "channel_name": ch_name,
            "target_language": target_lang,
            "gen_title": self.chk_ai_gen_title.isChecked() if hasattr(self, "chk_ai_gen_title") else True,
            "gen_desc": self.chk_ai_gen_desc.isChecked() if hasattr(self, "chk_ai_gen_desc") else True,
            "gen_tags": self.chk_ai_gen_tags.isChecked() if hasattr(self, "chk_ai_gen_tags") else True,
            "gen_thumb": self.chk_ai_gen_thumb.isChecked() if hasattr(self, "chk_ai_gen_thumb") else True,
        }

        # Chuẩn bị cấu hình Thumbnail tự động
        src_mode = "frame" if self.rad_src_frame.isChecked() else (
            "playlist" if self.rad_src_playlist.isChecked() else "custom"
        )
        candidates = list(self._current_project_media)
        if not candidates and self._current_project_dir and self._current_project_dir.exists():
            candidates = sorted(list(self._current_project_dir.glob("*.png")) + list(self._current_project_dir.glob("*.jpg")))
        if not candidates:
            global_media = self.settings.get("media_files", [])
            candidates = [Path(m) for m in global_media if Path(m).exists()]

        out_dir = self._current_project_dir or Path("D:/auto_video_renderer/auto_video_renderer/temp")
        out_dir.mkdir(parents=True, exist_ok=True)

        thumb_config = {
            "mode": src_mode,
            "frame_sec": self.spin_frame_sec.value(),
            "playlist_thumb": self._playlist_common_thumb,
            "channel_name": ch_name,
            "font_style": self.thumb_font_combo.currentData() or "drama",
            "position": self.thumb_pos_combo.currentData() or "split_lr",
            "badge_position": self.thumb_badge_pos_combo.currentData() or "top_left",
            "enable_badge": self.chk_enable_badge.isChecked() if hasattr(self, "chk_enable_badge") else True,
            "enable_highlight": self.chk_enable_hl.isChecked() if hasattr(self, "chk_enable_hl") else True,
            "out_dir": out_dir,
            "candidates": candidates,
        }

        tasks: List[Dict[str, Any]] = []
        for idx, (r, item) in enumerate(selected_tasks_info):
            pub_at = schedule_dts[idx] if schedule_dts else None
            tasks.append({
                "row_idx": r,
                "video_path": item["video_path"],
                "file_name": item["file_name"],
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "tags": item.get("tags", ""),
                "episode_badge": item.get("episode_badge", ""),
                "episode_index": item.get("episode_index"),
                "thumbnail_path": item.get("thumbnail_path"),
                "thumbnail_hl": item.get("thumbnail_hl"),
                "custom_thumb_bg": item.get("custom_thumb_bg"),
                "thumb_font": item.get("thumb_font"),
                "thumb_pos": item.get("thumb_pos"),
                "thumb_badge_pos": item.get("thumb_badge_pos"),
                "privacy_status": privacy_status,
                "publish_at": pub_at,
                "is_premiere": is_premiere,
                "playlist_name": pl_name or "",
                "playlist_id": pl_id,
            })

        self.btn_start_upload.setEnabled(False)
        self.btn_cancel_upload.setEnabled(True)
        self.upload_progress.setValue(0)
        self._log(f"🚀 Bắt đầu tiến trình tự động tải lên {len(tasks)} video lên kênh {self.channel_combo.currentText()}...")
        mode_desc = "Trích xuất frame từ video" if src_mode == "frame" else ("1 ảnh poster cho playlist" if src_mode == "playlist" else "Ảnh riêng")
        self._log(f"   ℹ Chế độ Thumbnail: {mode_desc}")
        self._log(f"   🌏 Quốc gia mục tiêu: {c_info.get('label', c_key)} (Mã ngôn ngữ: {geo_config['language_code'].upper()})")
        if geo_config["enable_geo"]:
            self._log(f"   📍 Vị trí địa lý (recordingDetails): {geo_config['location_name']}")
        if cooldown_config["enabled"]:
            self._log(f"   🛡 Giãn cách chống Spam (Cooldown): {cooldown_config['min_sec']}s - {cooldown_config['max_sec']}s ngẫu nhiên giữa các video")

        if self.chk_use_playlist.isChecked():
            if pl_id:
                self._log(f"   📂 Playlist: {self.playlist_combo.currentText()} (ID: {pl_id})")
            else:
                self._log(f"   📂 Playlist mới sẽ tạo: {pl_name}")

        self._upload_worker = UploadWorker(
            uploader=self.uploader,
            tasks=tasks,
            channel_id=ch_id,
            ai_config=ai_config,
            thumb_config=thumb_config,
            geo_config=geo_config,
            cooldown_config=cooldown_config,
        )
        self._upload_worker.progress_sig.connect(self._on_upload_progress)
        self._upload_worker.log_sig.connect(self._log)
        self._upload_worker.item_status_sig.connect(self._on_upload_item_status)
        self._upload_worker.item_updated_sig.connect(self._on_upload_item_updated)
        self._upload_worker.all_finished_sig.connect(self._on_upload_all_finished)
        self._upload_worker.start()

    def _on_upload_item_status(self, row_idx: int, status_type: str, status_val: str) -> None:
        if row_idx < 0 or row_idx >= len(self.video_items):
            return
        if status_type == "uploading":
            self._update_row_status(row_idx, "uploading", message=status_val)
        elif status_type == "success":
            self._update_row_status(row_idx, "uploaded", extra_data=status_val)
        elif status_type == "error":
            self._update_row_status(row_idx, "error", message=status_val)

    def _on_table_cell_double_clicked(self, row: int, col: int) -> None:
        if col == 6 and 0 <= row < len(self.video_items):
            url = self.video_items[row].get("video_url")
            if url and url.startswith("http"):
                try:
                    webbrowser.open(url)
                    self._log(f"🌐 Đang mở video YouTube trên trình duyệt: {url}")
                except Exception as e:
                    self._log(f"⚠ Không thể mở trình duyệt: {e}")

    def _on_upload_item_updated(self, row_idx: int, data: dict) -> None:
        if row_idx < 0 or row_idx >= len(self.video_items):
            return
        item = self.video_items[row_idx]
        self.video_table.blockSignals(True)
        if "title" in data:
            item["title"] = data["title"]
            it_t = self.video_table.item(row_idx, 3)
            if it_t:
                it_t.setText(data["title"])
                it_t.setToolTip(data["title"])
        if "description" in data:
            item["description"] = data["description"]
        if "tags" in data:
            item["tags"] = data["tags"]
        if "thumbnail_path" in data:
            item["thumbnail_path"] = data["thumbnail_path"]
            it_tb = QTableWidgetItem("✔ Đã tạo")
            it_tb.setTextAlignment(Qt.AlignCenter)
            it_tb.setForeground(Qt.green)
            self.video_table.setItem(row_idx, 4, it_tb)
            if row_idx == self.current_video_idx:
                self._set_thumbnail_preview(Path(data["thumbnail_path"]))
        self.video_table.blockSignals(False)

        if row_idx == self.current_video_idx:
            if "title" in data:
                self.title_edit.setText(data["title"])
            if "description" in data:
                self.desc_edit.setText(data["description"])
            if "tags" in data:
                self.tags_edit.setText(data["tags"])

    def _on_upload_progress(self, pct: int, msg: str, spd: float) -> None:
        self.upload_progress.setValue(pct)
        spd_text = f" | Tốc độ: {spd:.2f} MB/s" if spd > 0 else ""
        self.upload_status_label.setText(f"{msg}{spd_text}")

    def _on_upload_all_finished(self) -> None:
        self.btn_start_upload.setEnabled(True)
        self.btn_cancel_upload.setEnabled(False)
        self.upload_status_label.setText("Hoàn tất toàn bộ tác vụ tải lên.")
        self._log("🎉 Tất cả video đã được xử lý xong!")
        QMessageBox.information(self, "Hoàn tất", "Đã tải lên toàn bộ video được chọn!")

    def _cancel_upload(self) -> None:
        if self._upload_worker:
            self._upload_worker.cancel()
            self._log("⏳ Đang dừng tác vụ upload...")

    def _log(self, msg: str) -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.upload_log.append(f"[{ts}] {msg}")

    # ==========================
    # SETTINGS PERSISTENCE
    # ==========================
    def _save_ui_settings(self) -> None:
        if getattr(self, "_is_loading_settings", False):
            return
        yt_cfg = self.settings.setdefault("youtube_uploader", {})
        yt_cfg["ai_provider"] = self.ai_provider_combo.currentData() or "offline"
        yt_cfg["ai_target_lang"] = self.ai_target_lang_combo.currentData() or "vi"
        yt_cfg["ai_gen_title"] = self.chk_ai_gen_title.isChecked()
        yt_cfg["ai_gen_desc"] = self.chk_ai_gen_desc.isChecked()
        yt_cfg["ai_gen_tags"] = self.chk_ai_gen_tags.isChecked()
        yt_cfg["ai_gen_thumb"] = self.chk_ai_gen_thumb.isChecked()
        yt_cfg["9router_base_url"] = self.nine_url_edit.text().strip()
        yt_cfg["9router_api_key"] = self.nine_key_edit.text().strip()
        yt_cfg["9router_model"] = self.nine_model_combo.currentText().strip()
        yt_cfg["gemini_api_key"] = self.gemini_key_edit.text().strip()
        yt_cfg["gemini_model"] = self.gemini_model_combo.currentText().strip()
        yt_cfg["custom_base_url"] = self.custom_url_edit.text().strip()
        yt_cfg["custom_api_key"] = self.custom_key_edit.text().strip()
        yt_cfg["custom_model"] = self.custom_model_edit.text().strip()
        yt_cfg["active_channel_id"] = self.channel_combo.currentData() or ""
        yt_cfg["schedule_videos_per_day"] = self.sch_per_day_spin.value()
        yt_cfg["schedule_time_slots"] = self.sch_slots_edit.text().strip()
        yt_cfg["is_premiere"] = self.premiere_chk.isChecked()
        yt_cfg["use_playlist"] = self.chk_use_playlist.isChecked()
        yt_cfg["playlist_mode"] = "existing" if self.rad_existing_pl.isChecked() else "new"
        yt_cfg["thumb_src_mode"] = "frame" if self.rad_src_frame.isChecked() else ("playlist" if self.rad_src_playlist.isChecked() else "custom")
        yt_cfg["thumb_frame_sec"] = self.spin_frame_sec.value()
        yt_cfg["thumb_enable_badge"] = self.chk_enable_badge.isChecked()
        yt_cfg["thumb_enable_hl"] = self.chk_enable_hl.isChecked()
        yt_cfg["thumb_badge_pos"] = self.thumb_badge_pos_combo.currentData() or "top_left"
        yt_cfg["thumb_font_style"] = self.thumb_font_combo.currentData() or "drama"
        yt_cfg["thumb_position"] = self.thumb_pos_combo.currentData() or "split_lr"
        yt_cfg["thumb_x"] = self.thumb_x_spin.value()
        yt_cfg["thumb_y"] = self.thumb_y_spin.value()
        yt_cfg["thumb_scale"] = self.thumb_scale_spin.value()
        # Lưu cấu hình Quốc gia & Chống Spam
        yt_cfg["target_country"] = self.country_combo.currentData() or "ph"
        yt_cfg["enable_geo"] = self.chk_enable_geo.isChecked()
        yt_cfg["geo_location"] = self.geo_location_edit.text().strip()
        yt_cfg["enable_anti_spam"] = self.chk_anti_spam.isChecked()
        yt_cfg["anti_spam_min"] = self.spin_spam_min.value()
        yt_cfg["anti_spam_max"] = self.spin_spam_max.value()
        self.settings_changed.emit(self.settings)

    def load_settings(self, settings: Dict[str, Any]) -> None:
        self._is_loading_settings = True
        try:
            self.settings = settings
            yt_cfg = settings.get("youtube_uploader", {}) or {}

            provider = yt_cfg.get("ai_provider", "9router")
            idx_p = self.ai_provider_combo.findData(provider)
            if idx_p >= 0:
                self.ai_provider_combo.setCurrentIndex(idx_p)

            target_lang = yt_cfg.get("ai_target_lang", "vi")
            idx_tl = self.ai_target_lang_combo.findData(target_lang)
            if idx_tl >= 0:
                self.ai_target_lang_combo.setCurrentIndex(idx_tl)

            if "ai_gen_title" in yt_cfg:
                self.chk_ai_gen_title.setChecked(bool(yt_cfg.get("ai_gen_title", True)))
            if "ai_gen_desc" in yt_cfg:
                self.chk_ai_gen_desc.setChecked(bool(yt_cfg.get("ai_gen_desc", True)))
            if "ai_gen_tags" in yt_cfg:
                self.chk_ai_gen_tags.setChecked(bool(yt_cfg.get("ai_gen_tags", True)))
            if "ai_gen_thumb" in yt_cfg:
                self.chk_ai_gen_thumb.setChecked(bool(yt_cfg.get("ai_gen_thumb", True)))
            self._update_ai_btn_text()

            if yt_cfg.get("9router_base_url"):
                self.nine_url_edit.setText(yt_cfg.get("9router_base_url"))
            if yt_cfg.get("9router_api_key"):
                self.nine_key_edit.setText(yt_cfg.get("9router_api_key"))
            if yt_cfg.get("9router_model"):
                m_idx = self.nine_model_combo.findText(yt_cfg.get("9router_model"))
                if m_idx >= 0:
                    self.nine_model_combo.setCurrentIndex(m_idx)
                else:
                    self.nine_model_combo.setEditText(yt_cfg.get("9router_model"))

            if yt_cfg.get("gemini_api_key"):
                self.gemini_key_edit.setText(yt_cfg.get("gemini_api_key"))
            if yt_cfg.get("gemini_model"):
                m_idx = self.gemini_model_combo.findText(yt_cfg.get("gemini_model"))
                if m_idx >= 0:
                    self.gemini_model_combo.setCurrentIndex(m_idx)
            if yt_cfg.get("custom_base_url"):
                self.custom_url_edit.setText(yt_cfg.get("custom_base_url"))
            if yt_cfg.get("custom_api_key"):
                self.custom_key_edit.setText(yt_cfg.get("custom_api_key"))
            if yt_cfg.get("custom_model"):
                self.custom_model_edit.setText(yt_cfg.get("custom_model"))

            if yt_cfg.get("schedule_videos_per_day"):
                self.sch_per_day_spin.setValue(int(yt_cfg.get("schedule_videos_per_day", 2)))
            if yt_cfg.get("schedule_time_slots"):
                self.sch_slots_edit.setText(str(yt_cfg.get("schedule_time_slots", "11:30, 19:30")))

            self.premiere_chk.setChecked(bool(yt_cfg.get("is_premiere", False)))

            use_pl = bool(yt_cfg.get("use_playlist", False))
            self.chk_use_playlist.setChecked(use_pl)
            if yt_cfg.get("playlist_mode") == "new":
                self.rad_new_pl.setChecked(True)
            else:
                self.rad_existing_pl.setChecked(True)

            # Cấu hình Thumbnail Studio
            thumb_src = yt_cfg.get("thumb_src_mode", "frame")
            if thumb_src == "playlist":
                self.rad_src_playlist.setChecked(True)
            elif thumb_src == "custom":
                self.rad_src_custom.setChecked(True)
            else:
                self.rad_src_frame.setChecked(True)
            self._on_thumb_src_mode_changed()

            if yt_cfg.get("thumb_frame_sec"):
                try:
                    self.spin_frame_sec.setValue(float(yt_cfg.get("thumb_frame_sec", 3.0)))
                except Exception:
                    pass

            if "thumb_enable_badge" in yt_cfg:
                self.chk_enable_badge.setChecked(bool(yt_cfg["thumb_enable_badge"]))
                self._on_enable_badge_toggled(self.chk_enable_badge.isChecked())
            if "thumb_enable_hl" in yt_cfg:
                self.chk_enable_hl.setChecked(bool(yt_cfg["thumb_enable_hl"]))
                self._on_enable_hl_toggled(self.chk_enable_hl.isChecked())

            badge_pos = yt_cfg.get("thumb_badge_pos", "top_left")
            idx_bp = self.thumb_badge_pos_combo.findData(badge_pos)
            if idx_bp >= 0:
                self.thumb_badge_pos_combo.setCurrentIndex(idx_bp)

            font_style = yt_cfg.get("thumb_font_style", "drama")
            idx_fs = self.thumb_font_combo.findData(font_style)
            if idx_fs >= 0:
                self.thumb_font_combo.setCurrentIndex(idx_fs)

            pos = yt_cfg.get("thumb_position", "split_lr")
            if pos in ("top_left", "compact_tl"):
                pos = "compact_tl"
            elif pos in ("right", "full_right"):
                pos = "full_right"
            idx_pos = self.thumb_pos_combo.findData(pos)
            if idx_pos >= 0:
                self.thumb_pos_combo.setCurrentIndex(idx_pos)

            if yt_cfg.get("thumb_x") is not None:
                self.thumb_x_spin.setValue(int(yt_cfg["thumb_x"]))
            if yt_cfg.get("thumb_y") is not None:
                self.thumb_y_spin.setValue(int(yt_cfg["thumb_y"]))
            if yt_cfg.get("thumb_scale") is not None:
                self.thumb_scale_spin.setValue(int(yt_cfg["thumb_scale"]))
            self.custom_pos_box.setVisible(pos == "custom")

            # Cấu hình Quốc gia & Chống Spam
            target_country = yt_cfg.get("target_country", "ph")
            idx_c = self.country_combo.findData(target_country)
            if idx_c >= 0:
                self.country_combo.setCurrentIndex(idx_c)
            if "enable_geo" in yt_cfg:
                self.chk_enable_geo.setChecked(bool(yt_cfg["enable_geo"]))
                self._on_geo_toggled(bool(yt_cfg["enable_geo"]))
            if yt_cfg.get("geo_location"):
                self.geo_location_edit.setText(str(yt_cfg["geo_location"]))
            if "enable_anti_spam" in yt_cfg:
                self.chk_anti_spam.setChecked(bool(yt_cfg["enable_anti_spam"]))
                self._on_anti_spam_toggled(bool(yt_cfg["enable_anti_spam"]))
            if yt_cfg.get("anti_spam_min") is not None:
                self.spin_spam_min.setValue(int(yt_cfg["anti_spam_min"]))
            if yt_cfg.get("anti_spam_max") is not None:
                self.spin_spam_max.setValue(int(yt_cfg["anti_spam_max"]))
        finally:
            self._is_loading_settings = False

