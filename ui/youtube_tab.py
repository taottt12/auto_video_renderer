from __future__ import annotations

import datetime
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import webbrowser
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTextEdit,
    QPushButton, QComboBox, QSpinBox, QDateEdit, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox, QProgressBar,
    QGroupBox, QSplitter, QFrame, QDialog, QTabWidget, QRadioButton, QButtonGroup
)

from core.gemini_assistant import (
    GeminiAssistant, OfflineSEOAssistant, CustomAIAssistant,
    clean_story_title, clean_episode_badge
)
from core.settings import PROJECTS_DIR, SettingsManager
from core.thumbnail_builder import ThumbnailBuilder
from core.youtube_auth import YouTubeAuthManager
from core.youtube_uploader import YouTubeUploader


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
    ) -> None:
        super().__init__()
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.custom_base_url = custom_base_url
        self.tasks = tasks
        self.channel_name = channel_name
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        for idx, task in enumerate(self.tasks):
            if self._is_cancelled:
                break
            story_title = task.get("story_title", "")
            ep = task.get("episode_badge", f"TẬP {idx+1}")
            ep_idx = task.get("episode_index", idx + 1)
            try:
                if self.provider == "offline":
                    data = OfflineSEOAssistant.generate_video_metadata(
                        story_title=story_title,
                        episode_name=ep,
                        channel_name=self.channel_name,
                        episode_index=ep_idx,
                    )
                elif self.provider in ["custom", "9router"]:
                    assistant = CustomAIAssistant(self.api_key, self.custom_base_url, self.model)
                    data = assistant.generate_video_metadata(
                        story_title=story_title,
                        episode_name=ep,
                        channel_name=self.channel_name,
                        episode_index=ep_idx,
                    )
                else:
                    assistant = GeminiAssistant(self.api_key, self.model)
                    data = assistant.generate_video_metadata(
                        story_title=story_title,
                        episode_name=ep,
                        channel_name=self.channel_name,
                        episode_index=ep_idx,
                    )
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
    all_finished_sig = Signal()

    def __init__(
        self,
        uploader: YouTubeUploader,
        tasks: List[Dict[str, Any]],
        channel_id: str,
    ) -> None:
        super().__init__()
        self.uploader = uploader
        self.tasks = tasks
        self.channel_id = channel_id
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        total = len(self.tasks)
        for idx, task in enumerate(self.tasks):
            if self._is_cancelled:
                self.log_sig.emit("⚠ Người dùng đã bấm dừng upload.")
                break

            v_path = task["video_path"]
            title = task["title"]
            desc = task["description"]
            tags = task["tags"]
            privacy = task["privacy_status"]
            publish_at = task.get("publish_at")
            is_premiere = task.get("is_premiere", False)
            thumb = task.get("thumbnail_path")
            playlist_name = task.get("playlist_name", "")
            playlist_id = task.get("playlist_id", None)

            self.log_sig.emit(f"[{idx+1}/{total}] Bắt đầu tải lên: {Path(v_path).name}")
            self.log_sig.emit(f"   Tiêu đề: {title}")
            if publish_at:
                self.log_sig.emit(f"   Lịch đăng: {publish_at.strftime('%d/%m/%Y %H:%M')}")

            try:
                def on_progress(pct: int, msg: str, spd: float) -> None:
                    self.progress_sig.emit(pct, msg, spd)

                res = self.uploader.upload_video(
                    channel_id=self.channel_id,
                    video_path=v_path,
                    title=title,
                    description=desc,
                    tags=tags,
                    privacy_status=privacy,
                    publish_at=publish_at,
                    is_premiere=is_premiere,
                    thumbnail_path=thumb,
                    playlist_name=playlist_name,
                    playlist_id=playlist_id,
                    progress_cb=on_progress,
                )
                video_url = res.get("video_url", "")
                self.log_sig.emit(f"✔ Hoàn thành: {video_url}")
                self.item_finished_sig.emit(idx, True, video_url)
            except Exception as e:
                self.log_sig.emit(f"❌ Lỗi tải lên: {e}")
                self.item_finished_sig.emit(idx, False, str(e))

        self.all_finished_sig.emit()


def detect_9router_api_key() -> str:
    """Tự động đọc API Key sẵn có từ cơ sở dữ liệu 9Router cục bộ."""
    try:
        db_path = Path.home() / "AppData/Roaming/9router/db/data.sqlite"
        if db_path.exists():
            import sqlite3
            with sqlite3.connect(str(db_path)) as conn:
                cur = conn.cursor()
                cur.execute("SELECT key FROM apiKeys ORDER BY rowid DESC LIMIT 1;")
                r = cur.fetchone()
                if r and r[0]:
                    return r[0]
    except Exception:
        pass
    return ""


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

        self._upload_worker: Optional[UploadWorker] = None
        self._oauth_worker: Optional[OAuthWorker] = None
        self._content_worker: Optional[ContentWorker] = None

        self._init_ui()
        self.load_settings(self.settings)
        self.refresh_channels()
        self.refresh_projects()

    def _init_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        splitter = QSplitter(Qt.Horizontal)

        # ==========================================
        # CỘT 1: KÊNH YOUTUBE & DANH SÁCH VIDEO DỰ ÁN
        # ==========================================
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

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
        left_layout.addWidget(grp_channel)

        # Box 2: Chọn Dự án & Danh sách Video MP4 từng tập
        grp_project = QGroupBox("2. Chọn Dự án & Danh sách Video các tập")
        lay_proj = QVBoxLayout(grp_project)

        row_proj = QHBoxLayout()
        row_proj.addWidget(QLabel("Dự án:"))
        self.proj_combo = QComboBox()
        self.proj_combo.currentIndexChanged.connect(self._on_project_selected)
        row_proj.addWidget(self.proj_combo, 1)
        self.refresh_proj_btn = QPushButton("🔄")
        self.refresh_proj_btn.setToolTip("Làm mới danh sách dự án và video")
        self.refresh_proj_btn.clicked.connect(self.refresh_projects)
        row_proj.addWidget(self.refresh_proj_btn)
        lay_proj.addLayout(row_proj)

        # Bảng video 6 cột chi tiết từng tập
        self.video_table = QTableWidget(0, 6)
        self.video_table.setHorizontalHeaderLabels([
            "Chọn", "Tập", "Tên Video MP4", "Tiêu đề YouTube", "Thumbnail", "Dung lượng"
        ])
        h_header = self.video_table.horizontalHeader()
        h_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(3, QHeaderView.Stretch)
        h_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.video_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.video_table.cellClicked.connect(self._on_video_clicked)
        lay_proj.addWidget(self.video_table)

        row_tbl_btns = QHBoxLayout()
        self.select_all_btn = QPushButton("Chọn tất cả")
        self.select_all_btn.clicked.connect(self._select_all_videos)
        self.unselect_all_btn = QPushButton("Bỏ chọn")
        self.unselect_all_btn.clicked.connect(self._unselect_all_videos)
        self.btn_pick_external_videos = QPushButton("📁 Thêm video ngoài...")
        self.btn_pick_external_videos.setToolTip("Nạp thêm video MP4 từ thư mục bất kỳ")
        self.btn_pick_external_videos.clicked.connect(self._pick_external_videos)
        row_tbl_btns.addWidget(self.select_all_btn)
        row_tbl_btns.addWidget(self.unselect_all_btn)
        row_tbl_btns.addWidget(self.btn_pick_external_videos)
        lay_proj.addLayout(row_tbl_btns)

        left_layout.addWidget(grp_project, 1)
        splitter.addWidget(left_widget)

        # ==========================================
        # CỘT 2: TRỢ LÝ AI SEO & METADATA CHI TIẾT
        # ==========================================
        mid_widget = QWidget()
        mid_layout = QVBoxLayout(mid_widget)
        mid_layout.setContentsMargins(0, 0, 0, 0)
        mid_layout.setSpacing(8)

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

        self.btn_batch_ai_gen = QPushButton("✨ Tự Động Sinh Tiêu Đề, Mô Tả & Tags Cho Các Tập Đã Chọn")
        self.btn_batch_ai_gen.setStyleSheet("font-weight: bold; background-color: #2b5797; color: white; padding: 7px; border-radius: 4px;")
        self.btn_batch_ai_gen.clicked.connect(self._generate_all_content)
        lay_ai.addWidget(self.btn_batch_ai_gen)
        mid_layout.addWidget(grp_ai)

        # Box 4: Nội dung Video xuất bản (Theo từng tập)
        grp_meta = QGroupBox("4. Nội dung Video xuất bản (Tập đang chọn)")
        lay_meta = QVBoxLayout(grp_meta)

        self.editing_video_label = QLabel("Đang chỉnh sửa: Chưa chọn tập nào")
        self.editing_video_label.setStyleSheet("color: #4a90e2; font-weight: bold; font-size: 11px;")
        lay_meta.addWidget(self.editing_video_label)

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
        mid_layout.addWidget(grp_meta, 1)
        splitter.addWidget(mid_widget)

        # ==========================================
        # CỘT 3: THUMBNAIL STUDIO & TIẾN TRÌNH UPLOAD
        # ==========================================
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # Box 5: Thumbnail Studio
        grp_thumb = QGroupBox("5. Thumbnail Studio (1280x720 Từng Tập)")
        lay_thumb = QVBoxLayout(grp_thumb)

        self.thumb_preview = QLabel("Chưa có Thumbnail")
        self.thumb_preview.setAlignment(Qt.AlignCenter)
        self.thumb_preview.setFixedHeight(180)
        self.thumb_preview.setStyleSheet("background-color: #1e1e1e; color: #888; border: 1px solid #444; border-radius: 4px;")
        lay_thumb.addWidget(self.thumb_preview)

        row_badge = QHBoxLayout()
        row_badge.addWidget(QLabel("Huy hiệu tập:"))
        self.thumb_badge_edit = QLineEdit("P1")
        self.thumb_badge_edit.textChanged.connect(self._on_badge_changed)
        row_badge.addWidget(self.thumb_badge_edit)

        row_badge.addWidget(QLabel("Chữ to nổi bật:"))
        self.thumb_hl_edit = QLineEdit("TIÊU ĐỀ NỔI BẬT")
        self.thumb_hl_edit.textChanged.connect(self._on_thumb_hl_changed)
        row_badge.addWidget(self.thumb_hl_edit)
        lay_thumb.addLayout(row_badge)

        self.btn_gen_all_thumbs = QPushButton("🎨 Tự Tạo Thumbnail Cho Tất Cả Tập (Mỗi tập 1 ảnh)")
        self.btn_gen_all_thumbs.setStyleSheet("font-weight: bold; background-color: #d9534f; color: white; padding: 6px; border-radius: 4px;")
        self.btn_gen_all_thumbs.clicked.connect(self._create_all_thumbnails)
        lay_thumb.addWidget(self.btn_gen_all_thumbs)

        row_single_thumb = QHBoxLayout()
        self.btn_gen_single_thumb = QPushButton("🎨 Tạo Thumbnail Tập Này")
        self.btn_gen_single_thumb.clicked.connect(self._create_single_thumbnail)
        self.btn_pick_thumb = QPushButton("📁 Chọn ảnh có sẵn")
        self.btn_pick_thumb.clicked.connect(self._pick_custom_thumbnail)
        row_single_thumb.addWidget(self.btn_gen_single_thumb)
        row_single_thumb.addWidget(self.btn_pick_thumb)
        lay_thumb.addLayout(row_single_thumb)

        right_layout.addWidget(grp_thumb)

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

        right_layout.addWidget(grp_upload, 1)
        splitter.addWidget(right_widget)

        splitter.setSizes([350, 470, 420])
        main_layout.addWidget(splitter)
        self._update_provider_visibility()

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
    def refresh_projects(self) -> None:
        self.proj_combo.clear()
        projects = SettingsManager.list_projects()
        for p in projects:
            self.proj_combo.addItem(p.name.replace(".avr.json", "").replace(".json", ""), str(p))

        current_name = self.settings.get("project", {}).get("current_name", "")
        idx = self.proj_combo.findText(current_name)
        if idx >= 0:
            self.proj_combo.setCurrentIndex(idx)
        elif self.proj_combo.count() > 0:
            self.proj_combo.setCurrentIndex(0)
        self._on_project_selected()

    def _on_project_selected(self) -> None:
        proj_path_str = self.proj_combo.currentData()
        output_dir = None
        self._current_project_media = []

        raw_proj_name = self.proj_combo.currentText()
        clean_title = clean_story_title(raw_proj_name)
        self.new_playlist_edit.setText(clean_title)

        if proj_path_str and Path(proj_path_str).exists():
            try:
                p_cfg = SettingsManager.load_project(Path(proj_path_str))
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

        mp4_files = sorted(list(output_dir.glob("*.mp4")), key=lambda p: p.name)
        self._load_mp4_files_into_table(mp4_files, clean_title)

    def _load_mp4_files_into_table(self, mp4_files: List[Path], story_title: str) -> None:
        self.video_items = []
        self.video_table.setRowCount(len(mp4_files))

        for row, f in enumerate(mp4_files):
            badge = clean_episode_badge(f.stem, row + 1)
            sz_mb = f.stat().st_size / (1024 * 1024) if f.exists() else 0.0

            # Kiểm tra xem có sẵn thumbnail trong thư mục không
            thumb_candidate = f.parent / f"thumbnail_tap_{row+1}.jpg"
            if not thumb_candidate.exists():
                thumb_candidate = f.parent / f"{f.stem}.jpg"
            thumb_path = str(thumb_candidate) if thumb_candidate.exists() else None

            # Sinh tiêu đề mặc định đẹp cho từng tập
            item_title = f"{badge}: {story_title}" if story_title else f.stem
            if len(item_title) > 95:
                item_title = item_title[:95]

            item_data = {
                "video_path": str(f),
                "file_name": f.name,
                "size_mb": sz_mb,
                "episode_badge": badge,
                "episode_index": row + 1,
                "title": item_title,
                "description": "",
                "tags": f"{story_title.lower()}, truyen audio, kiem hiep, {badge.lower()}",
                "thumbnail_path": thumb_path,
                "thumbnail_hl": clean_story_title(story_title or f.stem).upper(),
            }
            self.video_items.append(item_data)

            # Col 0: Checkbox
            chk_item = QTableWidgetItem()
            chk_item.setCheckState(Qt.Checked)
            chk_item.setData(Qt.UserRole, row)
            self.video_table.setItem(row, 0, chk_item)

            # Col 1: Tập
            it_badge = QTableWidgetItem(badge)
            it_badge.setTextAlignment(Qt.AlignCenter)
            self.video_table.setItem(row, 1, it_badge)

            # Col 2: Tên file
            self.video_table.setItem(row, 2, QTableWidgetItem(f.name))

            # Col 3: Tiêu đề YouTube
            self.video_table.setItem(row, 3, QTableWidgetItem(item_title))

            # Col 4: Thumbnail
            thumb_status = "✔ Đã có" if thumb_path else "Chưa tạo"
            it_thumb = QTableWidgetItem(thumb_status)
            it_thumb.setTextAlignment(Qt.AlignCenter)
            if thumb_path:
                it_thumb.setForeground(Qt.green)
            else:
                it_thumb.setForeground(Qt.gray)
            self.video_table.setItem(row, 4, it_thumb)

            # Col 5: Dung lượng
            it_sz = QTableWidgetItem(f"{sz_mb:.1f} MB")
            it_sz.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.video_table.setItem(row, 5, it_sz)

        if mp4_files:
            self._select_video_row(0)

    def _pick_external_videos(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Chọn danh sách video MP4 cần tải lên", "", "Video (*.mp4 *.mkv *.mov)"
        )
        if not files:
            return
        mp4_files = [Path(f) for f in files]
        story_title = clean_story_title(self.proj_combo.currentText())
        self._load_mp4_files_into_table(mp4_files, story_title)

    def _select_all_videos(self) -> None:
        for r in range(self.video_table.rowCount()):
            it = self.video_table.item(r, 0)
            if it:
                it.setCheckState(Qt.Checked)

    def _unselect_all_videos(self) -> None:
        for r in range(self.video_table.rowCount()):
            it = self.video_table.item(r, 0)
            if it:
                it.setCheckState(Qt.Unchecked)

    def _on_video_clicked(self, row: int, col: int) -> None:
        self._select_video_row(row)

    def _select_video_row(self, row: int) -> None:
        if row < 0 or row >= len(self.video_items):
            return
        self.current_video_idx = row
        item = self.video_items[row]

        self.editing_video_label.setText(f"Đang chỉnh sửa: [{item['episode_badge']}] {item['file_name']}")
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
        self.thumb_badge_edit.setText(item.get("episode_badge", f"P{row+1}"))
        self.thumb_badge_edit.blockSignals(False)

        self.thumb_hl_edit.blockSignals(True)
        saved_hl = item.get("thumbnail_hl")
        if saved_hl:
            self.thumb_hl_edit.setText(saved_hl)
        else:
            default_hl = clean_story_title(item.get("title", "") or self.proj_combo.currentText())
            self.thumb_hl_edit.setText(default_hl.upper())
            item["thumbnail_hl"] = default_hl.upper()
        self.thumb_hl_edit.blockSignals(False)

        # Cập nhật preview Thumbnail
        thumb_p = item.get("thumbnail_path")
        if thumb_p and Path(thumb_p).exists():
            self._set_thumbnail_preview(Path(thumb_p))
        else:
            self.thumb_preview.clear()
            self.thumb_preview.setText(f"Chưa có Thumbnail\n({item['episode_badge']})")
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
            if tbl_it:
                tbl_it.setText(text)

    def _on_desc_changed(self) -> None:
        if 0 <= self.current_video_idx < len(self.video_items):
            self.video_items[self.current_video_idx]["description"] = self.desc_edit.toPlainText()

    def _on_tags_changed(self, text: str) -> None:
        if 0 <= self.current_video_idx < len(self.video_items):
            self.video_items[self.current_video_idx]["tags"] = text

    def _on_badge_changed(self, text: str) -> None:
        if 0 <= self.current_video_idx < len(self.video_items):
            self.video_items[self.current_video_idx]["episode_badge"] = text
            tbl_it = self.video_table.item(self.current_video_idx, 1)
            if tbl_it:
                tbl_it.setText(text)

    def _on_thumb_hl_changed(self, text: str) -> None:
        if 0 <= self.current_video_idx < len(self.video_items):
            self.video_items[self.current_video_idx]["thumbnail_hl"] = text

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
                tasks.append({
                    "story_title": clean_title or item["file_name"],
                    "episode_badge": item.get("episode_badge", f"TẬP {r+1}"),
                    "episode_index": item.get("episode_index", r + 1),
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

        self._content_worker = ContentWorker(
            provider=provider,
            api_key=api_key,
            model=model,
            custom_base_url=custom_url,
            tasks=tasks,
            channel_name=ch_name,
        )

        def on_item_finished(task_idx: int, ok: bool, msg: str, data: dict) -> None:
            if task_idx < len(selected_indices):
                row_idx = selected_indices[task_idx]
                if ok and data:
                    item = self.video_items[row_idx]
                    if "title" in data:
                        item["title"] = data["title"]
                        self.video_table.setItem(row_idx, 3, QTableWidgetItem(data["title"]))
                    if "description" in data:
                        item["description"] = data["description"]
                    if "tags" in data:
                        item["tags"] = data["tags"]
                    if "thumbnail_badge" in data:
                        badge = clean_episode_badge(data["thumbnail_badge"], row_idx + 1)
                        item["episode_badge"] = badge
                        self.video_table.setItem(row_idx, 1, QTableWidgetItem(badge))
                    if "thumbnail_highlight" in data and data["thumbnail_highlight"]:
                        item["thumbnail_hl"] = data["thumbnail_highlight"].strip().upper()

                    if row_idx == self.current_video_idx:
                        self._select_video_row(row_idx)

                    self._log(f"✔ Đã tạo nội dung cho [{item['episode_badge']}]: {item['title']}")
                else:
                    self._log(f"⚠ Lỗi tạo tập {task_idx+1}: {msg}")

        def on_all_finished() -> None:
            self.btn_batch_ai_gen.setEnabled(True)
            self.btn_batch_ai_gen.setText("✨ Tự Động Sinh Tiêu Đề, Mô Tả & Tags Cho Các Tập Đã Chọn")
            QMessageBox.information(self, "Hoàn thành", f"Đã sinh xong nội dung SEO chuẩn cho {len(tasks)} tập video!")

        self._content_worker.item_finished_sig.connect(on_item_finished)
        self._content_worker.all_finished_sig.connect(on_all_finished)
        self._content_worker.start()

    # Giữ hàm đơn cho nút bấm cũ nếu cần
    def _generate_with_gemini(self) -> None:
        self._generate_all_content()

    # ==========================
    # LOGIC: THUMBNAIL STUDIO TỪNG TẬP
    # ==========================
    def _create_all_thumbnails(self) -> None:
        if not self.video_items:
            QMessageBox.warning(self, "Chưa có video", "Không có video nào trong danh sách để tạo Thumbnail.")
            return

        # Tìm các ảnh minh họa nội dung truyện từ project media_files
        candidates = list(self._current_project_media)
        if not candidates and self._current_project_dir and self._current_project_dir.exists():
            candidates = sorted(list(self._current_project_dir.glob("*.png")) + list(self._current_project_dir.glob("*.jpg")))

        if not candidates:
            global_media = self.settings.get("media_files", [])
            candidates = [Path(m) for m in global_media if Path(m).exists()]

        raw_story_title = self.proj_combo.currentText()
        clean_title = clean_story_title(raw_story_title).upper()
        ch_name = self.channel_combo.currentText().split("(")[0].strip()

        out_dir = self._current_project_dir or Path("D:/auto_video_renderer/auto_video_renderer/temp")
        out_dir.mkdir(parents=True, exist_ok=True)

        count = 0
        for idx, item in enumerate(self.video_items):
            badge = item.get("episode_badge", f"P{idx+1}")
            bg_img = candidates[idx % len(candidates)] if candidates else Path("temp/preview_fx_bubbles.png")
            out_thumb = out_dir / f"thumbnail_tap_{idx+1}.jpg"

            # Tự động lấy chữ to nổi bật cho thumbnail từ tên truyện/tiêu đề video
            hl_text = item.get("thumbnail_hl") or clean_story_title(item.get("title", "") or raw_story_title).upper()

            try:
                thumb_res = ThumbnailBuilder.create_thumbnail(
                    bg_image=bg_img,
                    output_path=out_thumb,
                    badge_text=badge,
                    highlight_title=hl_text,
                    subtitle=ch_name,
                )
                item["thumbnail_path"] = str(thumb_res)
                
                # Cập nhật ô hiển thị Thumbnail trong bảng
                it_tb = QTableWidgetItem("✔ Đã tạo")
                it_tb.setTextAlignment(Qt.AlignCenter)
                it_tb.setForeground(Qt.green)
                self.video_table.setItem(idx, 4, it_tb)

                if idx == self.current_video_idx:
                    self._set_thumbnail_preview(thumb_res)
                count += 1
            except Exception as e:
                self._log(f"❌ Lỗi tạo Thumbnail tập {idx+1}: {e}")

        self._log(f"🎨 Đã tự động tạo trọn bộ {count} Thumbnail chất lượng cao 1280x720 cho từng tập!")
        QMessageBox.information(self, "Thumbnail hoàn tất", f"Đã tạo thành công {count} Thumbnail chuẩn 1280x720 cho các tập!")

    def _create_single_thumbnail(self) -> None:
        if self.current_video_idx < 0 or self.current_video_idx >= len(self.video_items):
            QMessageBox.warning(self, "Chưa chọn tập", "Vui lòng chọn 1 tập trong bảng để tạo Thumbnail.")
            return

        item = self.video_items[self.current_video_idx]
        candidates = list(self._current_project_media)
        if not candidates and self._current_project_dir and self._current_project_dir.exists():
            candidates = sorted(list(self._current_project_dir.glob("*.png")) + list(self._current_project_dir.glob("*.jpg")))
        if not candidates:
            candidates = [Path(m) for m in self.settings.get("media_files", []) if Path(m).exists()]

        bg_img = candidates[self.current_video_idx % len(candidates)] if candidates else Path("temp/preview_fx_bubbles.png")
        out_dir = self._current_project_dir or Path("D:/auto_video_renderer/auto_video_renderer/temp")
        out_thumb = out_dir / f"thumbnail_tap_{self.current_video_idx+1}.jpg"

        badge = self.thumb_badge_edit.text().strip() or item.get("episode_badge", f"P{self.current_video_idx+1}")
        hl = self.thumb_hl_edit.text().strip() or item.get("thumbnail_hl") or clean_story_title(item.get("title", "") or self.proj_combo.currentText()).upper()
        ch_name = self.channel_combo.currentText().split("(")[0].strip()

        try:
            res_path = ThumbnailBuilder.create_thumbnail(
                bg_image=bg_img,
                output_path=out_thumb,
                badge_text=badge,
                highlight_title=hl,
                subtitle=ch_name,
            )
            item["thumbnail_path"] = str(res_path)
            self._set_thumbnail_preview(res_path)

            it_tb = QTableWidgetItem("✔ Đã tạo")
            it_tb.setTextAlignment(Qt.AlignCenter)
            it_tb.setForeground(Qt.green)
            self.video_table.setItem(self.current_video_idx, 4, it_tb)
            self._log(f"✔ Đã tạo Thumbnail cho [{badge}]: {res_path.name}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi tạo Thumbnail", str(e))

    def _pick_custom_thumbnail(self) -> None:
        if self.current_video_idx < 0 or self.current_video_idx >= len(self.video_items):
            QMessageBox.warning(self, "Chưa chọn tập", "Vui lòng chọn 1 tập trong bảng để gắn Thumbnail.")
            return

        path, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh Thumbnail", "", "Hình ảnh (*.jpg *.jpeg *.png *.webp)")
        if path:
            p = Path(path)
            self.video_items[self.current_video_idx]["thumbnail_path"] = str(p)
            self._set_thumbnail_preview(p)
            it_tb = QTableWidgetItem("✔ Đã chọn")
            it_tb.setTextAlignment(Qt.AlignCenter)
            it_tb.setForeground(Qt.green)
            self.video_table.setItem(self.current_video_idx, 4, it_tb)

    def _set_thumbnail_preview(self, path: Path) -> None:
        self.current_thumbnail_path = path
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            scaled = pixmap.scaled(self.thumb_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
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
            it = self.video_table.item(r, 0)
            if it and it.checkState() == Qt.Checked and r < len(self.video_items):
                selected_tasks_info.append(self.video_items[r])

        if not selected_tasks_info:
            QMessageBox.warning(self, "Chưa chọn video", "Hãy tích chọn ít nhất 1 video trong bảng để tải lên.")
            return

        privacy_idx = self.privacy_combo.currentIndex()
        privacy_status = "schedule" if privacy_idx == 0 else (
            "public" if privacy_idx == 1 else ("unlisted" if privacy_idx == 2 else "private")
        )

        schedule_dts = []
        if privacy_status == "schedule":
            start_date = self.sch_date_edit.date().toPython()
            time_slots = [s.strip() for s in self.sch_slots_edit.text().split(",") if s.strip()]
            schedule_dts = YouTubeUploader.calculate_schedule_slots(start_date, time_slots, len(selected_tasks_info))

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
        tasks: List[Dict[str, Any]] = []

        # Chuẩn bị tư liệu ảnh nếu cần tạo Thumbnail tự động cho video chưa có
        candidates = list(self._current_project_media)
        if not candidates and self._current_project_dir and self._current_project_dir.exists():
            candidates = sorted(list(self._current_project_dir.glob("*.png")) + list(self._current_project_dir.glob("*.jpg")))
        if not candidates:
            global_media = self.settings.get("media_files", [])
            candidates = [Path(m) for m in global_media if Path(m).exists()]

        out_dir = self._current_project_dir or Path("D:/auto_video_renderer/auto_video_renderer/temp")
        out_dir.mkdir(parents=True, exist_ok=True)
        raw_story_title = self.proj_combo.currentText()
        ch_name = self.channel_combo.currentText().split("(")[0].strip()

        for idx, item in enumerate(selected_tasks_info):
            # TỰ ĐỘNG TẠO THUMBNAIL KIẾM HIỆP NẾU CHƯA CÓ
            thumb_path = item.get("thumbnail_path")
            if not thumb_path or not Path(thumb_path).exists():
                ep_idx = item.get("episode_index", idx + 1)
                badge = item.get("episode_badge") or f"P{ep_idx}"
                bg_img = candidates[(ep_idx - 1) % len(candidates)] if candidates else Path("temp/preview_fx_bubbles.png")
                out_thumb = out_dir / f"thumbnail_tap_{ep_idx}.jpg"
                hl_text = item.get("thumbnail_hl") or clean_story_title(item.get("title", "") or raw_story_title).upper()
                try:
                    thumb_res = ThumbnailBuilder.create_thumbnail(
                        bg_image=bg_img,
                        output_path=out_thumb,
                        badge_text=badge,
                        highlight_title=hl_text,
                        subtitle=ch_name,
                    )
                    thumb_path = str(thumb_res)
                    item["thumbnail_path"] = thumb_path
                    # Cập nhật ô hiển thị trong bảng
                    for r, v in enumerate(self.video_items):
                        if v.get("video_path") == item.get("video_path"):
                            it_tb = QTableWidgetItem("✔ Đã tạo")
                            it_tb.setTextAlignment(Qt.AlignCenter)
                            it_tb.setForeground(Qt.green)
                            self.video_table.setItem(r, 4, it_tb)
                            break
                    self._log(f"🎨 [Tự Động Tạo] Đã tạo Thumbnail Kiếm Hiệp cho [{badge}]: {out_thumb.name}")
                except Exception as e:
                    self._log(f"⚠ Không thể tự tạo thumbnail tập {ep_idx}: {e}")

            pub_at = schedule_dts[idx] if schedule_dts else None
            tasks.append({
                "video_path": item["video_path"],
                "title": (item.get("title") or item["file_name"])[:100],
                "description": item.get("description", ""),
                "tags": item.get("tags", ""),
                "privacy_status": privacy_status,
                "publish_at": pub_at,
                "is_premiere": is_premiere,
                "thumbnail_path": thumb_path,
                "playlist_name": pl_name or "",
                "playlist_id": pl_id,
            })

        self.btn_start_upload.setEnabled(False)
        self.btn_cancel_upload.setEnabled(True)
        self.upload_progress.setValue(0)
        self._log(f"🚀 Bắt đầu tải lên {len(tasks)} video lên kênh {self.channel_combo.currentText()}...")
        if self.chk_use_playlist.isChecked():
            if pl_id:
                self._log(f"   📂 Playlist: {self.playlist_combo.currentText()} (ID: {pl_id})")
            else:
                self._log(f"   📂 Playlist mới sẽ tạo: {pl_name}")
        else:
            self._log("   ℹ Không thêm vào Playlist (đăng video độc lập).")

        self._upload_worker = UploadWorker(self.uploader, tasks, ch_id)
        self._upload_worker.progress_sig.connect(self._on_upload_progress)
        self._upload_worker.log_sig.connect(self._log)
        self._upload_worker.all_finished_sig.connect(self._on_upload_all_finished)
        self._upload_worker.start()

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
        yt_cfg = self.settings.setdefault("youtube_uploader", {})
        yt_cfg["ai_provider"] = self.ai_provider_combo.currentData() or "offline"
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
        self.settings_changed.emit(self.settings)

    def load_settings(self, settings: Dict[str, Any]) -> None:
        self.settings = settings
        yt_cfg = settings.get("youtube_uploader", {}) or {}

        provider = yt_cfg.get("ai_provider", "9router")
        idx_p = self.ai_provider_combo.findData(provider)
        if idx_p >= 0:
            self.ai_provider_combo.setCurrentIndex(idx_p)

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

