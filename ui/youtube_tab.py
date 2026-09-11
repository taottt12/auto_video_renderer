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
    QGroupBox, QSplitter, QFrame, QDialog, QTabWidget, QRadioButton, QButtonGroup,
    QScrollArea
)

from core.gemini_assistant import (
    GeminiAssistant, OfflineSEOAssistant, CustomAIAssistant,
    clean_story_title, clean_episode_badge, extract_clean_video_title,
    to_hashtag, format_tags_string
)
from core.settings import PROJECTS_DIR, SettingsManager
from core.thumbnail_builder import ThumbnailBuilder
from core.youtube_auth import YouTubeAuthManager
from core.youtube_uploader import YouTubeUploader


class AspectRatioLabel(QLabel):
    """QLabel duy trì tỷ lệ 16:9 của Thumbnail YouTube và luôn giãn sát mép 2 bên, không có viền đen thừa."""

    def __init__(self, text: str = "Chưa có Thumbnail", parent=None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(140)
        self._orig_pixmap: Optional[QPixmap] = None
        self.setStyleSheet("background-color: #1e1e1e; color: #888; border: 1px solid #444; border-radius: 4px;")

    def set_thumbnail_pixmap(self, pixmap: QPixmap) -> None:
        self._orig_pixmap = pixmap
        self._update_display()

    def clear_thumbnail(self, placeholder: str = "Chưa có Thumbnail") -> None:
        self._orig_pixmap = None
        self.clear()
        self.setText(placeholder)
        self.setFixedHeight(180)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_display()

    def _update_display(self) -> None:
        if self._orig_pixmap and not self._orig_pixmap.isNull():
            w = max(120, self.width())
            h = int(w * 9 / 16)
            self.setFixedHeight(h)
            scaled = self._orig_pixmap.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self.setPixmap(scaled)


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
            ep = task.get("episode_badge") if task.get("episode_badge") is not None else ""
            ep_idx = task.get("episode_index")
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
        overall_layout = QVBoxLayout(self)
        overall_layout.setContentsMargins(8, 8, 8, 8)
        overall_layout.setSpacing(6)

        # Thanh công cụ trên cùng với bộ chuyển đổi bố cục Studio
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 2)
        lbl_studio = QLabel("🎬 <b>STUDIO ĐĂNG YOUTUBE & QUẢN LÝ VIDEO ĐA KÊNH</b>")
        lbl_studio.setStyleSheet("font-size: 13px; color: #4a90e2;")
        top_bar.addWidget(lbl_studio)
        top_bar.addStretch()

        top_bar.addWidget(QLabel("Bố cục Studio:"))
        self.layout_mode_combo = QComboBox()
        self.layout_mode_combo.addItem("📐 3 Cột Song Song (Studio Chuẩn)", "3_col")
        self.layout_mode_combo.addItem("📐 2 Cột Rộng Rãi (Danh Sách Dài)", "2_col")
        self.layout_mode_combo.currentIndexChanged.connect(self._on_layout_mode_changed)
        top_bar.addWidget(self.layout_mode_combo)
        overall_layout.addLayout(top_bar)

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

        # Bảng video 6 cột chi tiết từng tập
        self.video_table = QTableWidget(0, 6)
        self.video_table.setHorizontalHeaderLabels([
            "Chọn", "Tập", "Tên Video MP4", "Tiêu đề YouTube", "Thumbnail", "Dung lượng"
        ])
        h_header = self.video_table.horizontalHeader()
        h_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(2, QHeaderView.Interactive)
        h_header.setSectionResizeMode(3, QHeaderView.Stretch)
        h_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.video_table.setColumnWidth(0, 45)
        self.video_table.setColumnWidth(1, 55)
        self.video_table.setColumnWidth(2, 280)
        self.video_table.setColumnWidth(4, 80)
        self.video_table.setColumnWidth(5, 80)
        h_header.setSectionsMovable(True)
        h_header.setHighlightSections(True)
        self.video_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.video_table.cellClicked.connect(self._on_video_clicked)
        self.video_table.cellChanged.connect(self._on_table_cell_changed)
        lay_proj.addWidget(self.video_table)

        row_tbl_btns = QHBoxLayout()
        self.select_all_btn = QPushButton("Chọn tất cả")
        self.select_all_btn.setFixedHeight(28)
        self.select_all_btn.setFixedWidth(90)
        self.select_all_btn.clicked.connect(self._select_all_videos)

        self.unselect_all_btn = QPushButton("Bỏ chọn")
        self.unselect_all_btn.setFixedHeight(28)
        self.unselect_all_btn.setFixedWidth(80)
        self.unselect_all_btn.clicked.connect(self._unselect_all_videos)

        self.btn_pick_external_videos = QPushButton("📁 Thêm video ngoài...")
        self.btn_pick_external_videos.setFixedHeight(28)
        self.btn_pick_external_videos.setFixedWidth(160)
        self.btn_pick_external_videos.setToolTip("Nạp thêm video MP4 từ thư mục bất kỳ")
        self.btn_pick_external_videos.clicked.connect(self._pick_external_videos)

        row_tbl_btns.addWidget(self.select_all_btn)
        row_tbl_btns.addWidget(self.unselect_all_btn)
        row_tbl_btns.addWidget(self.btn_pick_external_videos)
        row_tbl_btns.addStretch()
        lay_proj.addLayout(row_tbl_btns)

        # Cụm Kênh YouTube + Danh sách Video MP4
        self.left_top_widget = QWidget()
        left_top_layout = QVBoxLayout(self.left_top_widget)
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

        # Box 4: Nội dung Video xuất bản (Theo từng tập)
        grp_meta = QGroupBox("4. Nội dung Video xuất bản (Tập đang chọn)")
        lay_meta = QVBoxLayout(grp_meta)

        self.editing_video_label = QLabel("Đang chỉnh sửa: Chưa chọn tập nào")
        self.editing_video_label.setStyleSheet("color: #4a90e2; font-weight: bold; font-size: 11px;")
        lay_meta.addWidget(self.editing_video_label)

        row_title_lbl = QHBoxLayout()
        row_title_lbl.addWidget(QLabel("Tiêu đề (Title):"))
        self.btn_ai_rewrite_title = QPushButton("✨ AI Viết Lại Tiêu Đề Cuốn Hút")
        self.btn_ai_rewrite_title.setStyleSheet("font-size: 11px; padding: 2px 8px; font-weight: bold; background-color: #0288d1; color: white; border-radius: 3px;")
        self.btn_ai_rewrite_title.setToolTip("Dùng AI tự động phân tích và viết lại tiêu đề thành câu hook giật gân, cuốn hút người xem")
        self.btn_ai_rewrite_title.clicked.connect(self._ai_rewrite_current_title)
        row_title_lbl.addWidget(self.btn_ai_rewrite_title)
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

        # Ghép Cụm 3 & Cụm 4 vào khu vực AI SEO & Nội dung xuất bản (bọc trong ScrollArea)
        left_bottom_widget = QWidget()
        left_bottom_layout = QVBoxLayout(left_bottom_widget)
        left_bottom_layout.setContentsMargins(0, 0, 4, 0)
        left_bottom_layout.setSpacing(6)
        left_bottom_layout.addWidget(grp_ai)
        left_bottom_layout.addWidget(grp_meta)

        self.left_bottom_scroll = QScrollArea()
        self.left_bottom_scroll.setWidgetResizable(True)
        self.left_bottom_scroll.setFrameShape(QFrame.NoFrame)
        self.left_bottom_scroll.setWidget(left_bottom_widget)

        # Splitter dọc dự phòng cho chế độ 2 cột
        self.left_splitter = QSplitter(Qt.Vertical)
        self.left_splitter.setChildrenCollapsible(False)

        # ==========================================
        # CỘT PHẢI: THUMBNAIL STUDIO & TIẾN TRÌNH UPLOAD
        # ==========================================
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 4, 0)
        right_layout.setSpacing(8)

        # Box 5: Thumbnail Studio
        grp_thumb = QGroupBox("5. Thumbnail Studio (1280x720 Từng Tập)")
        lay_thumb = QVBoxLayout(grp_thumb)

        # Preview tự động canh sát mép 2 bên tỷ lệ chuẩn 16:9
        self.thumb_preview = AspectRatioLabel("Chưa có Thumbnail")
        lay_thumb.addWidget(self.thumb_preview)

        # Hàng 1: Chế độ vẽ & Nút Quét Chữ Tự Động
        row_mode = QHBoxLayout()
        row_mode.addWidget(QLabel("Chế độ:"))
        self.thumb_mode_combo = QComboBox()
        self.thumb_mode_combo.addItem("🔍 Tự động quét (Ảnh có chữ -> Chỉ đóng Huy hiệu)", "auto")
        self.thumb_mode_combo.addItem("🏷️ Chỉ đóng Huy hiệu tập (Ảnh ĐÃ CÓ CHỮ SẴN)", "badge_only")
        self.thumb_mode_combo.addItem("🌟 Vẽ đầy đủ (Huy hiệu + Tiêu đề nghệ thuật)", "full")
        self.thumb_mode_combo.currentIndexChanged.connect(self._on_thumb_mode_changed)
        row_mode.addWidget(self.thumb_mode_combo, 1)

        self.btn_scan_img = QPushButton("🔍 Quét ảnh")
        self.btn_scan_img.setToolTip("Quét nhanh xem ảnh nền của tập này đã có sẵn chữ hay là ảnh mộc")
        self.btn_scan_img.setStyleSheet("padding: 3px 8px; font-weight: bold;")
        self.btn_scan_img.clicked.connect(self._scan_current_image)
        row_mode.addWidget(self.btn_scan_img)
        lay_thumb.addLayout(row_mode)

        # Nhãn hiển thị kết quả quét / trạng thái
        self.lbl_scan_info = QLabel("💡 Tự động quét sẽ phát hiện chữ có sẵn trên ảnh để tránh vẽ đè tiêu đề.")
        self.lbl_scan_info.setStyleSheet("color: #64b5f6; font-size: 10px;")
        self.lbl_scan_info.setWordWrap(True)
        lay_thumb.addWidget(self.lbl_scan_info)

        # Hàng 2: Huy hiệu tập & Vị trí đặt Huy hiệu
        row_badge = QHBoxLayout()
        row_badge.addWidget(QLabel("Huy hiệu tập:"))
        self.thumb_badge_edit = QLineEdit("P1")
        self.thumb_badge_edit.textChanged.connect(self._on_badge_changed)
        row_badge.addWidget(self.thumb_badge_edit, 1)

        row_badge.addWidget(QLabel("Vị trí Huy hiệu:"))
        self.thumb_badge_pos_combo = QComboBox()
        self.thumb_badge_pos_combo.addItem("📌 Góc Trái Trên", "top_left")
        self.thumb_badge_pos_combo.addItem("📌 Góc Phải Trên", "top_right")
        self.thumb_badge_pos_combo.addItem("📌 Góc Trái Dưới", "bottom_left")
        self.thumb_badge_pos_combo.addItem("📌 Góc Phải Dưới", "bottom_right")
        self.thumb_badge_pos_combo.currentIndexChanged.connect(self._on_thumb_style_or_pos_changed)
        row_badge.addWidget(self.thumb_badge_pos_combo, 1)
        lay_thumb.addLayout(row_badge)

        # Container cho Cụm Tiêu Đề Nghệ Thuật (tự ẩn/hiện theo chế độ)
        self.full_title_box = QWidget()
        lay_ft = QVBoxLayout(self.full_title_box)
        lay_ft.setContentsMargins(0, 0, 0, 0)
        lay_ft.setSpacing(6)

        row_hl = QHBoxLayout()
        row_hl.addWidget(QLabel("Chữ to nổi bật:"))
        self.thumb_hl_edit = QLineEdit("TIÊU ĐỀ NỔI BẬT")
        self.thumb_hl_edit.textChanged.connect(self._on_thumb_hl_changed)
        row_hl.addWidget(self.thumb_hl_edit)
        lay_ft.addLayout(row_hl)

        # Hàng chọn phong cách phối font & vị trí né mặt nhân vật
        row_font_pos = QHBoxLayout()
        row_font_pos.addWidget(QLabel("Phối Font:"))
        self.thumb_font_combo = QComboBox()
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
        lay_ft.addLayout(row_font_pos)

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
        lay_ft.addWidget(self.custom_pos_box)
        lay_thumb.addWidget(self.full_title_box)

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

        # Hàng công cụ nâng cao: AI Render ảnh nghệ thuật & Chụp từ video gốc
        row_ai_thumb = QHBoxLayout()
        self.btn_ai_render_thumb = QPushButton("✨ AI Render Ảnh Cuốn Hút (FLUX)")
        self.btn_ai_render_thumb.setStyleSheet("font-weight: bold; background-color: #6200ea; color: white; padding: 6px; border-radius: 4px;")
        self.btn_ai_render_thumb.setToolTip("Dùng AI FLUX vẽ ảnh bìa nghệ thuật mới hoàn toàn, siêu nét chuẩn 1280x720")
        self.btn_ai_render_thumb.clicked.connect(self._generate_ai_thumbnail_art)

        self.btn_extract_frame = QPushButton("📸 Chụp Ảnh Từ Video (FFmpeg)")
        self.btn_extract_frame.setStyleSheet("font-weight: bold; background-color: #00796b; color: white; padding: 6px; border-radius: 4px;")
        self.btn_extract_frame.setToolTip("Trích xuất khung hình độ nét cao trực tiếp từ video gốc")
        self.btn_extract_frame.clicked.connect(self._extract_frame_from_current_video)

        row_ai_thumb.addWidget(self.btn_ai_render_thumb)
        row_ai_thumb.addWidget(self.btn_extract_frame)
        lay_thumb.addLayout(row_ai_thumb)

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

        self.right_scroll = QScrollArea()
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setFrameShape(QFrame.NoFrame)
        self.right_scroll.setWidget(right_widget)

        # Splitter chính: Hỗ trợ linh hoạt chuyển đổi giữa 3 cột song song và 2 cột rộng
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        overall_layout.addWidget(self.main_splitter, 1)

        # Mặc định kích hoạt chế độ 3 Cột Song Song hiện đại
        self._apply_layout_mode("3_col")
        self._update_provider_visibility()

    # ==========================
    # LOGIC: BỐ CỤC STUDIO (3 CỘT / 2 CỘT)
    # ==========================
    def _on_layout_mode_changed(self) -> None:
        mode = self.layout_mode_combo.currentData() or "3_col"
        self._apply_layout_mode(mode)
        self._save_ui_settings()

    def _apply_layout_mode(self, mode: str) -> None:
        self.left_top_widget.setParent(None)
        self.left_bottom_scroll.setParent(None)
        self.right_scroll.setParent(None)
        self.left_splitter.setParent(None)

        if mode == "3_col":
            self.left_splitter.setVisible(False)
            self.main_splitter.addWidget(self.left_top_widget)
            self.main_splitter.addWidget(self.left_bottom_scroll)
            self.main_splitter.addWidget(self.right_scroll)

            self.left_top_widget.setMinimumWidth(320)
            self.left_bottom_scroll.setMinimumWidth(320)
            self.right_scroll.setMinimumWidth(320)

            self.main_splitter.setSizes([420, 440, 420])
            self.main_splitter.setStretchFactor(0, 3)
            self.main_splitter.setStretchFactor(1, 3)
            self.main_splitter.setStretchFactor(2, 3)
        else:
            self.left_splitter.setVisible(True)
            self.left_splitter.addWidget(self.left_top_widget)
            self.left_splitter.addWidget(self.left_bottom_scroll)
            self.left_splitter.setSizes([380, 420])

            self.main_splitter.addWidget(self.left_splitter)
            self.main_splitter.addWidget(self.right_scroll)

            self.left_splitter.setMinimumWidth(340)
            self.right_scroll.setMinimumWidth(340)

            self.main_splitter.setSizes([750, 450])
            self.main_splitter.setStretchFactor(0, 3)
            self.main_splitter.setStretchFactor(1, 2)

        QTimer.singleShot(50, self._refresh_current_preview)

    def _refresh_current_preview(self) -> None:
        if self.current_thumbnail_path and self.current_thumbnail_path.exists():
            self._set_thumbnail_preview(self.current_thumbnail_path)

    def _ai_rewrite_current_title(self) -> None:
        if self.current_video_idx < 0 or self.current_video_idx >= len(self.video_items):
            QMessageBox.warning(self, "Chưa chọn video", "Vui lòng chọn 1 video để viết lại tiêu đề.")
            return

        item = self.video_items[self.current_video_idx]
        cur_title = self.title_edit.text().strip() or item.get("file_name", "")
        badge = item.get("episode_badge", "")

        new_title = OfflineSEOAssistant.enhance_catchy_title(cur_title)
        if badge and not new_title.upper().startswith(f"{badge.upper()}:"):
            new_title = f"{badge}: {new_title}"

        self.title_edit.setText(new_title[:95])
        self._log(f"✨ [AI Viết Lại Tiêu Đề]: {new_title}")

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

        if "(Thư mục ngoài)" in raw_proj_name:
            is_external = True
            self._current_project_media = []
        self._is_external_project = is_external

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

            # Làm sạch tên video: bỏ ID dài, bỏ _vi_xuly...
            clean_name = extract_clean_video_title(f.stem)
            if not clean_name:
                clean_name = f.stem

            if is_external:
                # Video mở ngoài: Tự động dùng AI viết lại tiêu đề cuốn hút nếu tiêu đề cụt lủn hoặc chưa rành mạch
                catchy_title = OfflineSEOAssistant.enhance_catchy_title(clean_name)
                if badge:
                    item_title = f"{badge}: {catchy_title}"
                else:
                    item_title = catchy_title

                # Tự động trích xuất khung hình từ video làm thumbnail nếu chưa có ảnh
                if not thumb_path:
                    try:
                        thumb_candidate = f.parent / f"frame_{f.stem}.jpg"
                        if not thumb_candidate.exists():
                            ThumbnailBuilder.extract_video_frame(f, thumb_candidate, timestamp_sec=3.0)
                        if thumb_candidate.exists():
                            thumb_path = str(thumb_candidate)
                    except Exception:
                        pass
            else:
                # Dự án nội bộ
                if clean_name and clean_name.lower() != story_title.lower() and clean_name.lower() != "video":
                    if badge:
                        item_title = f"{badge}: {clean_name}"
                    else:
                        item_title = clean_name
                else:
                    if badge:
                        item_title = f"{badge}: {story_title}"
                    else:
                        item_title = story_title or clean_name

            if len(item_title) > 95:
                item_title = item_title[:95]

            # Thẻ tags: Bắt buộc định dạng #tagkhongdau, #tagkhongcach
            tag_list = [clean_name, story_title or "video", "truyen audio"]
            if badge:
                tag_list.append(badge)
            formatted_tags = format_tags_string(tag_list)

            item_data = {
                "video_path": str(f),
                "file_name": f.name,
                "size_mb": sz_mb,
                "episode_badge": badge,
                "episode_index": row + 1 if badge else None,
                "title": item_title,
                "description": "",
                "tags": formatted_tags,
                "thumbnail_path": thumb_path,
                "thumbnail_hl": (clean_name or story_title or f.stem).upper()[:40],
            }
            self.video_items.append(item_data)

            # Col 0: Checkbox
            chk_item = QTableWidgetItem()
            chk_item.setCheckState(Qt.Checked)
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

        self.video_table.blockSignals(False)

        if mp4_files:
            self._select_video_row(0)

    def _pick_external_videos(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Chọn danh sách video MP4 cần tải lên", "", "Video (*.mp4 *.mkv *.mov *.avi)"
        )
        if not files:
            return
        mp4_files = [Path(f) for f in files]
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
        self._is_external_project = True
        self._current_project_media = []
        self._load_mp4_files_into_table(mp4_files, story_title=folder_name, is_external=True)

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
        if saved_hl:
            self.thumb_hl_edit.setText(saved_hl)
        else:
            default_hl = clean_story_title(item.get("title", "") or self.proj_combo.currentText())
            self.thumb_hl_edit.setText(default_hl.upper()[:40])
            item["thumbnail_hl"] = default_hl.upper()[:40]
        self.thumb_hl_edit.blockSignals(False)

        # Cập nhật preview Thumbnail
        thumb_p = item.get("thumbnail_path")
        if thumb_p and Path(thumb_p).exists():
            self._set_thumbnail_preview(Path(thumb_p))
        else:
            badge_note = f"\n({badge_val})" if badge_val else ""
            self.thumb_preview.clear_thumbnail(f"Chưa có Thumbnail{badge_note}")
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

    def _on_thumb_style_or_pos_changed(self) -> None:
        is_custom = (self.thumb_pos_combo.currentData() == "custom")
        self.custom_pos_box.setVisible(is_custom)
        self._save_ui_settings()
        if 0 <= self.current_video_idx < len(self.video_items):
            self._create_single_thumbnail(silent=True)

    def _on_thumb_mode_changed(self) -> None:
        mode = self.thumb_mode_combo.currentData() or "auto"
        is_badge_only = (mode == "badge_only")
        self.full_title_box.setVisible(not is_badge_only)
        if is_badge_only:
            self.lbl_scan_info.setText("🏷️ Chế độ Chỉ Đóng Huy Hiệu: Giữ nguyên 100% ảnh gốc, không vẽ đè tiêu đề.")
        elif mode == "full":
            self.lbl_scan_info.setText("🌟 Chế độ Vẽ Đầy Đủ: Vẽ cả Huy hiệu tập + Tiêu đề nghệ thuật kiếm hiệp.")
        else:
            self.lbl_scan_info.setText("🔍 Chế độ Tự Động Quét: Tự nhận diện ảnh có chữ -> Chỉ đóng Huy hiệu tập.")
        self._save_ui_settings()
        if 0 <= self.current_video_idx < len(self.video_items):
            self._create_single_thumbnail(silent=True)

    def _scan_current_image(self) -> None:
        if self.current_video_idx < 0 or self.current_video_idx >= len(self.video_items):
            QMessageBox.warning(self, "Chưa chọn tập", "Vui lòng chọn 1 tập trong bảng danh sách để quét ảnh.")
            return
        candidates = list(self._current_project_media)
        if not candidates and self._current_project_dir and self._current_project_dir.exists():
            candidates = sorted(list(self._current_project_dir.glob("*.png")) + list(self._current_project_dir.glob("*.jpg")))
        if not candidates:
            candidates = [Path(m) for m in self.settings.get("media_files", []) if Path(m).exists()]

        bg_img = candidates[self.current_video_idx % len(candidates)] if candidates else None
        if not bg_img or not bg_img.exists():
            QMessageBox.warning(self, "Không tìm thấy ảnh", "Chưa có file ảnh nền nào cho tập này để quét.")
            return

        has_text, info = ThumbnailBuilder.detect_text_in_image(bg_img)
        if has_text:
            msg = (
                f"🔍 KẾT QUẢ QUÉT: Ảnh của tập này ĐÃ CÓ CHỮ TIÊU ĐỀ SẴN!\n"
                f"({info})\n\n"
                f"💡 Khuyên dùng: Chế độ 'Chỉ đóng Huy hiệu tập' sẽ giữ trọn 100% hình gốc và không bị đè chữ làm xấu ảnh."
            )
            self.lbl_scan_info.setText("🔍 Phát hiện ảnh ĐÃ CÓ SẴN CHỮ: Khuyên dùng Chỉ Đóng Huy Hiệu.")
            idx = self.thumb_mode_combo.findData("badge_only")
            if idx >= 0:
                self.thumb_mode_combo.setCurrentIndex(idx)
            QMessageBox.information(self, "Kết quả quét ảnh", msg)
        else:
            msg = (
                f"🌟 KẾT QUẢ QUÉT: Ảnh mộc, CHƯA CÓ CHỮ TIÊU ĐỀ!\n"
                f"({info})\n\n"
                f"💡 Bạn có thể dùng chế độ 'Vẽ đầy đủ' để tạo chữ kiếm hiệp nghệ thuật hoành tráng."
            )
            self.lbl_scan_info.setText("🌟 Ảnh mộc chưa có chữ: Vẽ đầy đủ nghệ thuật.")
            QMessageBox.information(self, "Kết quả quét ảnh", msg)

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
                    "story_title": item.get("title") or clean_title or item["file_name"],
                    "episode_badge": bdg,
                    "episode_index": item.get("episode_index"),
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
                    self.video_table.blockSignals(True)
                    if "title" in data:
                        item["title"] = data["title"]
                        self.video_table.setItem(row_idx, 3, QTableWidgetItem(data["title"]))
                    if "description" in data:
                        item["description"] = data["description"]
                    if "tags" in data:
                        item["tags"] = data["tags"]
                    if "thumbnail_badge" in data:
                        raw_bdg = data["thumbnail_badge"]
                        if item.get("episode_badge"):
                            badge = clean_episode_badge(raw_bdg, fallback_idx=None) or item["episode_badge"]
                        else:
                            badge = ""
                        item["episode_badge"] = badge
                        self.video_table.setItem(row_idx, 1, QTableWidgetItem(badge))
                    self.video_table.blockSignals(False)

                    if "thumbnail_highlight" in data and data["thumbnail_highlight"]:
                        item["thumbnail_hl"] = data["thumbnail_highlight"].strip().upper()

                    if row_idx == self.current_video_idx:
                        self._select_video_row(row_idx)

                    bdg_tag = f"[{item['episode_badge']}] " if item.get('episode_badge') else ""
                    self._log(f"✔ Đã tạo nội dung cho {bdg_tag}{item['title']}")
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

        mode = self.thumb_mode_combo.currentData() or "auto"
        badge_pos = self.thumb_badge_pos_combo.currentData() or "top_left"
        font_style = self.thumb_font_combo.currentData() or "but_phap"
        position = self.thumb_pos_combo.currentData() or "split_lr"
        pos_x = self.thumb_x_spin.value() if position == "custom" else None
        pos_y = self.thumb_y_spin.value() if position == "custom" else None
        font_scale = (self.thumb_scale_spin.value() / 100.0) if position == "custom" else 0.68

        count = 0
        badge_only_count = 0
        for idx, item in enumerate(self.video_items):
            badge = item.get("episode_badge") if item.get("episode_badge") is not None else ""
            out_thumb = out_dir / f"thumbnail_tap_{idx+1}.jpg"

            # Xác định ảnh nền: Nếu là thư mục ngoài, dùng frame video hoặc thumbnail đã có, không lấy ảnh truyện cũ
            if self._is_external_project:
                v_p = Path(item["video_path"])
                base_frame = out_dir / f"frame_{v_p.stem}.jpg"
                if not base_frame.exists():
                    try:
                        ThumbnailBuilder.extract_video_frame(v_p, base_frame, 3.0)
                    except Exception:
                        pass
                if base_frame.exists():
                    bg_img = base_frame
                elif item.get("thumbnail_path") and Path(item["thumbnail_path"]).exists():
                    bg_img = Path(item["thumbnail_path"])
                else:
                    bg_img = Path("temp/preview_fx_bubbles.png")
            else:
                bg_img = candidates[idx % len(candidates)] if candidates else Path("temp/preview_fx_bubbles.png")

            # Xác định badge_only theo chế độ đã chọn
            is_badge_only = False
            if mode == "badge_only":
                is_badge_only = True
            elif mode == "auto":
                has_text, info = ThumbnailBuilder.detect_text_in_image(bg_img)
                if has_text:
                    is_badge_only = True
                    bdg_info = f"[{badge}]" if badge else "Huy hiệu"
                    self._log(f"🔍 [Tập {idx+1}] Ảnh ĐÃ CÓ CHỮ SẴN ({info}) -> Tự động chỉ đóng {bdg_info}.")
                else:
                    is_badge_only = False
            else:
                is_badge_only = False

            if is_badge_only:
                badge_only_count += 1

            # Tự động lấy chữ to nổi bật cho thumbnail từ tên truyện/tiêu đề video
            hl_text = item.get("thumbnail_hl") or clean_story_title(item.get("title", "") or raw_story_title).upper()

            try:
                thumb_res = ThumbnailBuilder.create_thumbnail(
                    bg_image=bg_img,
                    output_path=out_thumb,
                    badge_text=badge,
                    highlight_title=hl_text,
                    subtitle=ch_name,
                    font_style=font_style,
                    position=position,
                    pos_x=pos_x,
                    pos_y=pos_y,
                    font_scale=font_scale,
                    badge_only=is_badge_only,
                    badge_position=badge_pos,
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

        log_msg = f"🎨 Đã tạo {count} Thumbnail 1280x720 (trong đó {badge_only_count} tập chỉ đóng Huy hiệu né đè chữ)."
        self._log(log_msg)
        QMessageBox.information(self, "Thumbnail hoàn tất", log_msg)

    def _create_single_thumbnail(self, silent: bool = False) -> None:
        if self.current_video_idx < 0 or self.current_video_idx >= len(self.video_items):
            if not silent:
                QMessageBox.warning(self, "Chưa chọn tập", "Vui lòng chọn 1 tập trong bảng để tạo Thumbnail.")
            return

        item = self.video_items[self.current_video_idx]
        candidates = list(self._current_project_media)
        if not candidates and self._current_project_dir and self._current_project_dir.exists():
            candidates = sorted(list(self._current_project_dir.glob("*.png")) + list(self._current_project_dir.glob("*.jpg")))
        if not candidates:
            candidates = [Path(m) for m in self.settings.get("media_files", []) if Path(m).exists()]

        out_dir = self._current_project_dir or Path("D:/auto_video_renderer/auto_video_renderer/temp")
        out_thumb = out_dir / f"thumbnail_tap_{self.current_video_idx+1}.jpg"

        if self._is_external_project:
            v_p = Path(item["video_path"])
            base_frame = out_dir / f"frame_{v_p.stem}.jpg"
            if not base_frame.exists():
                try:
                    ThumbnailBuilder.extract_video_frame(v_p, base_frame, 3.0)
                except Exception:
                    pass
            if base_frame.exists():
                bg_img = base_frame
            elif item.get("thumbnail_path") and Path(item["thumbnail_path"]).exists():
                bg_img = Path(item["thumbnail_path"])
            else:
                bg_img = Path("temp/preview_fx_bubbles.png")
        else:
            bg_img = candidates[self.current_video_idx % len(candidates)] if candidates else Path("temp/preview_fx_bubbles.png")

        badge = self.thumb_badge_edit.text().strip()
        if not badge and item.get("episode_badge") is not None:
            badge = item.get("episode_badge", "")
        hl = self.thumb_hl_edit.text().strip() or item.get("thumbnail_hl") or clean_story_title(item.get("title", "") or self.proj_combo.currentText()).upper()
        ch_name = self.channel_combo.currentText().split("(")[0].strip()

        mode = self.thumb_mode_combo.currentData() or "auto"
        badge_pos = self.thumb_badge_pos_combo.currentData() or "top_left"
        is_badge_only = False
        if mode == "badge_only":
            is_badge_only = True
        elif mode == "auto":
            has_text, info = ThumbnailBuilder.detect_text_in_image(bg_img)
            if has_text:
                is_badge_only = True
                self.lbl_scan_info.setText(f"🔍 Đã quét: Ảnh ĐÃ CÓ CHỮ SẴN ({info}) ➔ Chỉ đóng Huy hiệu [{badge}].")
            else:
                is_badge_only = False
                self.lbl_scan_info.setText(f"🌟 Đã quét: Ảnh mộc chưa có chữ ({info}) ➔ Vẽ đầy đủ Tiêu đề + Huy hiệu.")
        else:
            is_badge_only = False

        font_style = self.thumb_font_combo.currentData() or "but_phap"
        position = self.thumb_pos_combo.currentData() or "split_lr"
        pos_x = self.thumb_x_spin.value() if position == "custom" else None
        pos_y = self.thumb_y_spin.value() if position == "custom" else None
        font_scale = (self.thumb_scale_spin.value() / 100.0) if position == "custom" else 0.68

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
                badge_only=is_badge_only,
                badge_position=badge_pos,
            )
            item["thumbnail_path"] = str(res_path)
            self._set_thumbnail_preview(res_path)

            it_tb = QTableWidgetItem("✔ Đã tạo")
            it_tb.setTextAlignment(Qt.AlignCenter)
            it_tb.setForeground(Qt.green)
            self.video_table.setItem(self.current_video_idx, 4, it_tb)
            if not silent:
                note_mode = " (Chỉ đóng Huy hiệu)" if is_badge_only else " (Đầy đủ tiêu đề)"
                self._log(f"✔ Đã tạo Thumbnail cho [{badge}]: {res_path.name}{note_mode}")
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "Lỗi tạo Thumbnail", str(e))

    def _create_single_thumbnail_with_base(self, base_img_path: Path) -> None:
        """Tạo thumbnail với ảnh nền tùy biến (ảnh AI hoặc ảnh frame từ video)."""
        if self.current_video_idx < 0 or self.current_video_idx >= len(self.video_items):
            return

        item = self.video_items[self.current_video_idx]
        out_dir = self._current_project_dir or Path("D:/auto_video_renderer/auto_video_renderer/temp")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_thumb = out_dir / f"thumbnail_tap_{self.current_video_idx+1}.jpg"

        badge = self.thumb_badge_edit.text().strip()
        if not badge and item.get("episode_badge") is not None:
            badge = item.get("episode_badge", "")
        hl = self.thumb_hl_edit.text().strip() or item.get("thumbnail_hl") or clean_story_title(item.get("title", "") or self.proj_combo.currentText()).upper()
        ch_name = self.channel_combo.currentText().split("(")[0].strip()

        mode = self.thumb_mode_combo.currentData() or "auto"
        badge_pos = self.thumb_badge_pos_combo.currentData() or "top_left"
        is_badge_only = False
        if mode == "badge_only":
            is_badge_only = True
        elif mode == "auto":
            has_text, info = ThumbnailBuilder.detect_text_in_image(base_img_path)
            is_badge_only = has_text
            if has_text:
                self.lbl_scan_info.setText(f"🔍 Đã quét: Ảnh ĐÃ CÓ CHỮ SẴN ({info}) ➔ Chỉ đóng Huy hiệu [{badge}].")
            else:
                self.lbl_scan_info.setText(f"🌟 Đã quét: Ảnh mộc chưa có chữ ({info}) ➔ Vẽ đầy đủ Tiêu đề + Huy hiệu.")
        else:
            is_badge_only = False

        font_style = self.thumb_font_combo.currentData() or "but_phap"
        position = self.thumb_pos_combo.currentData() or "split_lr"
        pos_x = self.thumb_x_spin.value() if position == "custom" else None
        pos_y = self.thumb_y_spin.value() if position == "custom" else None
        font_scale = (self.thumb_scale_spin.value() / 100.0) if position == "custom" else 0.68

        try:
            res_path = ThumbnailBuilder.create_thumbnail(
                bg_image=base_img_path,
                output_path=out_thumb,
                badge_text=badge,
                highlight_title=hl,
                subtitle=ch_name,
                font_style=font_style,
                position=position,
                pos_x=pos_x,
                pos_y=pos_y,
                font_scale=font_scale,
                badge_only=is_badge_only,
                badge_position=badge_pos,
            )
            item["thumbnail_path"] = str(res_path)
            self._set_thumbnail_preview(res_path)

            it_tb = QTableWidgetItem("✔ Đã tạo")
            it_tb.setTextAlignment(Qt.AlignCenter)
            it_tb.setForeground(Qt.green)
            self.video_table.setItem(self.current_video_idx, 4, it_tb)
            self._log(f"✔ Đã tạo Thumbnail từ nguồn ảnh mới: {res_path.name}")
        except Exception as e:
            self._log(f"❌ Lỗi tạo Thumbnail từ ảnh mới: {e}")

    def _generate_ai_thumbnail_art(self) -> None:
        """Sinh ảnh nghệ thuật chất lượng cao từ AI FLUX (Pollinations.ai) miễn phí hoàn toàn."""
        if self.current_video_idx < 0 or self.current_video_idx >= len(self.video_items):
            QMessageBox.warning(self, "Chưa chọn video", "Vui lòng chọn 1 video trong bảng để vẽ ảnh AI.")
            return

        item = self.video_items[self.current_video_idx]
        title_prompt = item.get("title") or self.proj_combo.currentText()
        clean_p = extract_clean_video_title(title_prompt)

        out_dir = self._current_project_dir or Path("D:/auto_video_renderer/auto_video_renderer/temp")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_art = out_dir / f"ai_art_tap_{self.current_video_idx+1}.jpg"

        self.btn_ai_render_thumb.setEnabled(False)
        self.btn_ai_render_thumb.setText("⏳ Đang vẽ ảnh AI FLUX...")
        QApplication.processEvents()

        try:
            art_file = ThumbnailBuilder.generate_ai_thumbnail_image(clean_p, out_art)
            self._log(f"✨ [AI Render] Đã vẽ ảnh nghệ thuật thành công: {art_file.name}")
            self._create_single_thumbnail_with_base(art_file)
            QMessageBox.information(self, "AI Vẽ Ảnh Thành Công", f"Đã render xong ảnh Thumbnail nghệ thuật từ AI FLUX:\n{art_file.name}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi AI Render", f"Không thể tạo ảnh AI: {e}")
            self._log(f"❌ Lỗi AI Render: {e}")
        finally:
            self.btn_ai_render_thumb.setEnabled(True)
            self.btn_ai_render_thumb.setText("✨ AI Render Ảnh Cuốn Hút (FLUX)")

    def _extract_frame_from_current_video(self) -> None:
        """Trích xuất khung hình độ nét cao trực tiếp từ video bằng FFmpeg."""
        if self.current_video_idx < 0 or self.current_video_idx >= len(self.video_items):
            QMessageBox.warning(self, "Chưa chọn video", "Vui lòng chọn 1 video để chụp khung hình.")
            return

        item = self.video_items[self.current_video_idx]
        v_path = Path(item["video_path"])
        if not v_path.exists():
            QMessageBox.warning(self, "File không tồn tại", f"Không tìm thấy file video:\n{v_path}")
            return

        out_dir = self._current_project_dir or Path("D:/auto_video_renderer/auto_video_renderer/temp")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_frame = out_dir / f"frame_{v_path.stem}.jpg"

        try:
            frame_path = ThumbnailBuilder.extract_video_frame(v_path, out_frame, timestamp_sec=3.0)
            self._log(f"📸 [FFmpeg] Đã chụp khung hình từ video: {frame_path.name}")
            self._create_single_thumbnail_with_base(frame_path)
            QMessageBox.information(self, "Chụp Khung Hình Hoàn Tất", f"Đã trích xuất khung hình từ video thành công:\n{frame_path.name}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi chụp khung hình", f"Không thể trích xuất khung hình: {e}")
            self._log(f"❌ Lỗi FFmpeg trích khung hình: {e}")

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
            self.thumb_preview.set_thumbnail_pixmap(pixmap)

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

        font_style = self.thumb_font_combo.currentData() or "but_phap"
        position = self.thumb_pos_combo.currentData() or "split_lr"
        pos_x = self.thumb_x_spin.value() if position == "custom" else None
        pos_y = self.thumb_y_spin.value() if position == "custom" else None
        font_scale = (self.thumb_scale_spin.value() / 100.0) if position == "custom" else 0.68
        thumb_mode = self.thumb_mode_combo.currentData() or "auto"
        badge_pos = self.thumb_badge_pos_combo.currentData() or "top_left"

        for idx, item in enumerate(selected_tasks_info):
            # TỰ ĐỘNG TẠO THUMBNAIL KIẾM HIỆP NẾU CHƯA CÓ
            thumb_path = item.get("thumbnail_path")
            if not thumb_path or not Path(thumb_path).exists():
                ep_idx = item.get("episode_index")
                badge = item.get("episode_badge") if item.get("episode_badge") is not None else ""
                if self._is_external_project:
                    v_p = Path(item["video_path"])
                    base_frame = out_dir / f"frame_{v_p.stem}.jpg"
                    if not base_frame.exists():
                        try:
                            ThumbnailBuilder.extract_video_frame(v_p, base_frame, 3.0)
                        except Exception:
                            pass
                    bg_img = base_frame if base_frame.exists() else Path("temp/preview_fx_bubbles.png")
                else:
                    bg_idx = (ep_idx - 1) if (ep_idx is not None and ep_idx > 0) else idx
                    bg_img = candidates[bg_idx % len(candidates)] if candidates else Path("temp/preview_fx_bubbles.png")
                thumb_suffix = f"tap_{ep_idx}" if ep_idx is not None else f"video_{idx+1}"
                out_thumb = out_dir / f"thumbnail_{thumb_suffix}.jpg"
                hl_text = item.get("thumbnail_hl") or clean_story_title(item.get("title", "") or raw_story_title).upper()

                is_badge_only = False
                if thumb_mode == "badge_only":
                    is_badge_only = True
                elif thumb_mode == "auto":
                    has_text, _ = ThumbnailBuilder.detect_text_in_image(bg_img)
                    is_badge_only = has_text
                else:
                    is_badge_only = False

                try:
                    thumb_res = ThumbnailBuilder.create_thumbnail(
                        bg_image=bg_img,
                        output_path=out_thumb,
                        badge_text=badge,
                        highlight_title=hl_text,
                        subtitle=ch_name,
                        font_style=font_style,
                        position=position,
                        pos_x=pos_x,
                        pos_y=pos_y,
                        font_scale=font_scale,
                        badge_only=is_badge_only,
                        badge_position=badge_pos,
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
                    self._log(f"🎨 [Tự Động Tạo] Đã tạo Thumbnail cho [{badge}]: {out_thumb.name}")
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
        yt_cfg["thumb_mode"] = self.thumb_mode_combo.currentData() or "auto"
        yt_cfg["thumb_badge_pos"] = self.thumb_badge_pos_combo.currentData() or "top_left"
        yt_cfg["thumb_font_style"] = self.thumb_font_combo.currentData() or "but_phap"
        yt_cfg["thumb_position"] = self.thumb_pos_combo.currentData() or "split_lr"
        yt_cfg["thumb_x"] = self.thumb_x_spin.value()
        yt_cfg["thumb_y"] = self.thumb_y_spin.value()
        yt_cfg["thumb_scale"] = self.thumb_scale_spin.value()
        yt_cfg["layout_mode"] = self.layout_mode_combo.currentData() or "3_col"
        self.settings_changed.emit(self.settings)

    def load_settings(self, settings: Dict[str, Any]) -> None:
        self.settings = settings
        yt_cfg = settings.get("youtube_uploader", {}) or {}

        l_mode = yt_cfg.get("layout_mode", "3_col")
        idx_lm = self.layout_mode_combo.findData(l_mode)
        if idx_lm >= 0:
            self.layout_mode_combo.setCurrentIndex(idx_lm)

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

        # Cấu hình Thumbnail Kiếm Hiệp
        thumb_mode = yt_cfg.get("thumb_mode", "auto")
        idx_tm = self.thumb_mode_combo.findData(thumb_mode)
        if idx_tm >= 0:
            self.thumb_mode_combo.setCurrentIndex(idx_tm)

        badge_pos = yt_cfg.get("thumb_badge_pos", "top_left")
        idx_bp = self.thumb_badge_pos_combo.findData(badge_pos)
        if idx_bp >= 0:
            self.thumb_badge_pos_combo.setCurrentIndex(idx_bp)

        font_style = yt_cfg.get("thumb_font_style", "but_phap")
        if font_style == "co_phong":
            font_style = "but_phap"
        idx_fs = self.thumb_font_combo.findData(font_style)
        if idx_fs >= 0:
            self.thumb_font_combo.setCurrentIndex(idx_fs)

        position = yt_cfg.get("thumb_position", "split_lr")
        if position in ("top_left", "compact_tl"):
            position = "compact_tl"
        elif position in ("right", "full_right"):
            position = "full_right"
        idx_pos = self.thumb_pos_combo.findData(position)
        if idx_pos >= 0:
            self.thumb_pos_combo.setCurrentIndex(idx_pos)

        if "thumb_x" in yt_cfg:
            self.thumb_x_spin.setValue(int(yt_cfg["thumb_x"]))
        if "thumb_y" in yt_cfg:
            self.thumb_y_spin.setValue(int(yt_cfg["thumb_y"]))
        if "thumb_scale" in yt_cfg:
            self.thumb_scale_spin.setValue(int(yt_cfg["thumb_scale"]))
        self.custom_pos_box.setVisible(position == "custom")

