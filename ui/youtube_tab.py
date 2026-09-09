from __future__ import annotations

import datetime
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTextEdit,
    QPushButton, QComboBox, QSpinBox, QDateEdit, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox, QProgressBar,
    QGroupBox, QSplitter, QFrame, QDialog, QTabWidget
)


from core.gemini_assistant import GeminiAssistant
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
        self.port = 8080
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
        self.uri_display = QLineEdit("http://localhost:8080/")
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
        self.port_spin.setValue(8080)
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
        port: int = 8080,
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


class GeminiWorker(QThread):
    finished_gemini = Signal(bool, str, dict)

    def __init__(self, api_key: str, model: str, title: str, ep: str, extra: str, ch_name: str) -> None:
        super().__init__()
        self.assistant = GeminiAssistant(api_key, model)
        self.title = title
        self.ep = ep
        self.extra = extra
        self.ch_name = ch_name

    def run(self) -> None:
        try:
            data = self.assistant.generate_video_metadata(self.title, self.ep, self.extra, self.ch_name)
            self.finished_gemini.emit(True, "Sinh nội dung thành công!", data)
        except Exception as e:
            self.finished_gemini.emit(False, str(e), {})


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
            playlist = task.get("playlist", "")

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
                    playlist_name=playlist,
                    progress_cb=on_progress,
                )
                video_url = res.get("video_url", "")
                self.log_sig.emit(f"✔ Hoàn thành: {video_url}")
                self.item_finished_sig.emit(idx, True, video_url)
            except Exception as e:
                self.log_sig.emit(f"❌ Lỗi tải lên: {e}")
                self.item_finished_sig.emit(idx, False, str(e))

        self.all_finished_sig.emit()


class YouTubeTab(QWidget):
    """Tab Tải video lên YouTube với Trợ lý Gemini AI và Quản lý Đa Kênh."""

    settings_changed = Signal(dict)

    def __init__(self, settings: Dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.auth_mgr = YouTubeAuthManager()
        self.uploader = YouTubeUploader(self.auth_mgr)
        self.current_thumbnail_path: Optional[Path] = None
        self._upload_worker: Optional[UploadWorker] = None
        self._oauth_worker: Optional[OAuthWorker] = None
        self._gemini_worker: Optional[GeminiWorker] = None

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

        # Box 2: Chọn Dự án & Danh sách Video MP4
        grp_project = QGroupBox("2. Chọn Dự án & Video cần đăng")
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

        # Bảng video
        self.video_table = QTableWidget(0, 3)
        self.video_table.setHorizontalHeaderLabels(["Chọn", "Tên Video", "Dung lượng"])
        self.video_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.video_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.video_table.cellClicked.connect(self._on_video_clicked)
        lay_proj.addWidget(self.video_table)

        row_tbl_btns = QHBoxLayout()
        self.select_all_btn = QPushButton("Chọn tất cả")
        self.select_all_btn.clicked.connect(self._select_all_videos)
        self.unselect_all_btn = QPushButton("Bỏ chọn")
        self.unselect_all_btn.clicked.connect(self._unselect_all_videos)
        row_tbl_btns.addWidget(self.select_all_btn)
        row_tbl_btns.addWidget(self.unselect_all_btn)
        lay_proj.addLayout(row_tbl_btns)

        left_layout.addWidget(grp_project, 1)
        splitter.addWidget(left_widget)

        # ==========================================
        # CỘT 2: TRỢ LÝ GEMINI AI & METADATA
        # ==========================================
        mid_widget = QWidget()
        mid_layout = QVBoxLayout(mid_widget)
        mid_layout.setContentsMargins(0, 0, 0, 0)
        mid_layout.setSpacing(8)

        # Box 3: Trợ lý Gemini
        grp_gemini = QGroupBox("3. Trợ lý Gemini AI Content")
        lay_gemini = QVBoxLayout(grp_gemini)

        row_gem_key = QHBoxLayout()
        row_gem_key.addWidget(QLabel("Gemini Key:"))
        self.gemini_key_edit = QLineEdit()
        self.gemini_key_edit.setPlaceholderText("Dán Gemini API Key từ AI Studio...")
        self.gemini_key_edit.setEchoMode(QLineEdit.Password)
        self.gemini_key_edit.textChanged.connect(self._save_ui_settings)
        row_gem_key.addWidget(self.gemini_key_edit)
        lay_gemini.addLayout(row_gem_key)

        self.btn_gemini_gen = QPushButton("✨ Gemini Tự Động Sinh Tiêu Đề, Mô Tả & Tags")
        self.btn_gemini_gen.setStyleSheet("font-weight: bold; background-color: #2b5797; color: white; padding: 6px;")
        self.btn_gemini_gen.clicked.connect(self._generate_with_gemini)
        lay_gemini.addWidget(self.btn_gemini_gen)
        mid_layout.addWidget(grp_gemini)

        # Box 4: Nội dung Video (Metadata)
        grp_meta = QGroupBox("4. Nội dung Video xuất bản")
        lay_meta = QVBoxLayout(grp_meta)

        row_title_lbl = QHBoxLayout()
        row_title_lbl.addWidget(QLabel("Tiêu đề (Title):"))
        self.title_len_label = QLabel("0/100")
        self.title_len_label.setStyleSheet("color: #888; font-size: 11px;")
        row_title_lbl.addWidget(self.title_len_label, 0, Qt.AlignRight)
        lay_meta.addLayout(row_title_lbl)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Nhập tiêu đề video...")
        self.title_edit.textChanged.connect(self._on_title_changed)
        lay_meta.addWidget(self.title_edit)

        lay_meta.addWidget(QLabel("Mô tả (Description):"))
        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("Mô tả tóm tắt nội dung, mốc thời gian, bản quyền và hashtag...")
        self.desc_edit.setFixedHeight(120)
        lay_meta.addWidget(self.desc_edit)

        lay_meta.addWidget(QLabel("Thẻ từ khóa (Tags):"))
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("tag1, tag2, tag3, truyen audio, kiem hiep...")
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

        # Playlist
        row_pl = QHBoxLayout()
        row_pl.addWidget(QLabel("Playlist:"))
        self.playlist_combo = QComboBox()
        self.playlist_combo.setEditable(True)
        self.playlist_combo.setPlaceholderText("Chọn hoặc nhập tên Playlist mới...")
        row_pl.addWidget(self.playlist_combo, 1)
        self.reload_pl_btn = QPushButton("🔄")
        self.reload_pl_btn.clicked.connect(self._reload_playlists)
        row_pl.addWidget(self.reload_pl_btn)
        lay_pub.addLayout(row_pl)

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
        grp_thumb = QGroupBox("5. Thumbnail Studio (1280x720)")
        lay_thumb = QVBoxLayout(grp_thumb)

        self.thumb_preview = QLabel("Chưa có Thumbnail")
        self.thumb_preview.setAlignment(Qt.AlignCenter)
        self.thumb_preview.setFixedHeight(180)
        self.thumb_preview.setStyleSheet("background-color: #1e1e1e; color: #888; border: 1px solid #444; border-radius: 4px;")
        lay_thumb.addWidget(self.thumb_preview)

        row_badge = QHBoxLayout()
        row_badge.addWidget(QLabel("Huy hiệu:"))
        self.thumb_badge_edit = QLineEdit("TẬP 1")
        row_badge.addWidget(self.thumb_badge_edit)
        lay_thumb.addLayout(row_badge)

        row_hl = QHBoxLayout()
        row_hl.addWidget(QLabel("Chữ to:"))
        self.thumb_hl_edit = QLineEdit("TIÊU ĐỀ NỔI BẬT")
        row_hl.addWidget(self.thumb_hl_edit)
        lay_thumb.addLayout(row_hl)

        row_thumb_btns = QHBoxLayout()
        self.btn_gen_thumb = QPushButton("🎨 Tự Tạo Thumbnail")
        self.btn_gen_thumb.setStyleSheet("font-weight: bold; background-color: #d9534f; color: white;")
        self.btn_gen_thumb.clicked.connect(self._create_auto_thumbnail)
        self.btn_pick_thumb = QPushButton("📁 Chọn ảnh có sẵn")
        self.btn_pick_thumb.clicked.connect(self._pick_custom_thumbnail)
        row_thumb_btns.addWidget(self.btn_gen_thumb)
        row_thumb_btns.addWidget(self.btn_pick_thumb)
        lay_thumb.addLayout(row_thumb_btns)

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
        self.btn_start_upload.setStyleSheet("font-weight: bold; font-size: 13px; background-color: #28a745; color: white; padding: 10px;")
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

        splitter.setSizes([340, 460, 420])
        main_layout.addWidget(splitter)

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
            self.ch_info_label.setText("Vui lòng thêm file client_secret.json để kết nối kênh.")
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
    # LOGIC: DỰ ÁN & VIDEO MP4
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

        if proj_path_str and Path(proj_path_str).exists():
            try:
                p_cfg = SettingsManager.load_project(Path(proj_path_str))
                out_str = p_cfg.get("export", {}).get("output_folder") or p_cfg.get("project", {}).get("output_folder")
                if out_str:
                    output_dir = Path(out_str)
            except Exception:
                pass

        if not output_dir:
            output_dir = Path(self.settings.get("export", {}).get("output_folder", "output"))

        # Nếu đường dẫn output tương đối, chuyển thành tuyệt đối
        if not output_dir.is_absolute():
            output_dir = Path("D:/auto_video_renderer/auto_video_renderer") / output_dir

        if not output_dir.exists():
            self.video_table.setRowCount(0)
            return

        mp4_files = sorted(list(output_dir.glob("*.mp4")), key=lambda p: p.name)
        self.video_table.setRowCount(len(mp4_files))
        for row, f in enumerate(mp4_files):
            # Checkbox item
            chk_item = QTableWidgetItem()
            chk_item.setCheckState(Qt.Checked)
            chk_item.setData(Qt.UserRole, str(f))
            self.video_table.setItem(row, 0, chk_item)

            # Tên video
            self.video_table.setItem(row, 1, QTableWidgetItem(f.name))

            # Dung lượng
            sz_mb = f.stat().st_size / (1024 * 1024)
            self.video_table.setItem(row, 2, QTableWidgetItem(f"{sz_mb:.1f} MB"))

        # Tự động chọn video đầu tiên để hiển thị gợi ý
        if mp4_files:
            self._on_video_clicked(0, 1)

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
        it = self.video_table.item(row, 0)
        if not it:
            return
        video_path = Path(it.data(Qt.UserRole))
        # Gợi ý tiêu đề từ tên file
        raw_name = video_path.stem
        self.title_edit.setText(raw_name)

        # Tìm số tập nếu có
        match = re.search(r"(tập\s*\d+|p\d+|chương\s*\d+)", raw_name, re.IGNORECASE)
        if match:
            self.thumb_badge_edit.setText(match.group(0).upper())
        else:
            self.thumb_badge_edit.setText(f"TẬP {row+1}")

        # Rút gọn chữ to cho thumbnail
        words = raw_name.split()
        short_title = " ".join(words[:5]) if len(words) >= 5 else raw_name
        self.thumb_hl_edit.setText(short_title.upper())

    # ==========================
    # LOGIC: GEMINI AI
    # ==========================
    def _generate_with_gemini(self) -> None:
        key = self.gemini_key_edit.text().strip()
        if not key:
            QMessageBox.warning(self, "Thiếu Gemini Key", "Vui lòng nhập Gemini API Key để sử dụng tính năng này.")
            return

        story_title = self.proj_combo.currentText() or self.title_edit.text()
        badge = self.thumb_badge_edit.text()
        ch_name = self.channel_combo.currentText()

        self.btn_gemini_gen.setEnabled(False)
        self.btn_gemini_gen.setText("⏳ Gemini đang sáng tạo nội dung...")

        model = self.settings.get("youtube_uploader", {}).get("gemini_model", "gemini-2.0-flash")
        self._gemini_worker = GeminiWorker(key, model, story_title, badge, "", ch_name)
        self._gemini_worker.finished_gemini.connect(self._on_gemini_finished)
        self._gemini_worker.start()

    def _on_gemini_finished(self, success: bool, msg: str, data: dict) -> None:
        self.btn_gemini_gen.setEnabled(True)
        self.btn_gemini_gen.setText("✨ Gemini Tự Động Sinh Tiêu Đề, Mô Tả & Tags")
        if success:
            if "title" in data:
                self.title_edit.setText(data["title"])
            if "description" in data:
                self.desc_edit.setText(data["description"])
            if "tags" in data:
                self.tags_edit.setText(data["tags"])
            if "thumbnail_badge" in data:
                self.thumb_badge_edit.setText(data["thumbnail_badge"])
            if "thumbnail_highlight" in data:
                self.thumb_hl_edit.setText(data["thumbnail_highlight"])
            self._log("✔ Gemini đã tự động sinh trọn bộ metadata chuẩn SEO!")
        else:
            QMessageBox.critical(self, "Lỗi Gemini", f"Không thể gọi Gemini API:\n{msg}")

    def _on_title_changed(self, text: str) -> None:
        length = len(text)
        self.title_len_label.setText(f"{length}/100")
        if length > 95:
            self.title_len_label.setStyleSheet("color: red; font-weight: bold; font-size: 11px;")
        else:
            self.title_len_label.setStyleSheet("color: #888; font-size: 11px;")

    def _on_privacy_changed(self, idx: int) -> None:
        # 0: Schedule, 1: Public, 2: Unlisted, 3: Private
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
    # LOGIC: THUMBNAIL STUDIO
    # ==========================
    def _create_auto_thumbnail(self) -> None:
        # Lấy ảnh mẫu từ media_files trong cấu hình hoặc một ảnh temp có sẵn
        bg_candidate = None
        media_files = self.settings.get("media_files", [])
        for m in media_files:
            mp = Path(m)
            if mp.exists() and mp.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]:
                bg_candidate = mp
                break

        if not bg_candidate:
            # Tìm ảnh trong assets hoặc temp
            asset_img = Path("D:/auto_video_renderer/auto_video_renderer/temp/preview_fx_bubbles.png")
            if asset_img.exists():
                bg_candidate = asset_img

        if not bg_candidate:
            QMessageBox.warning(self, "Chưa có ảnh nền", "Vui lòng chọn ảnh Thumbnail từ máy hoặc nạp ảnh vào danh sách media.")
            return

        out_thumb = Path("D:/auto_video_renderer/auto_video_renderer/temp") / f"thumb_{int(datetime.datetime.now().timestamp())}.jpg"
        badge = self.thumb_badge_edit.text().strip()
        hl = self.thumb_hl_edit.text().strip()

        try:
            res_path = ThumbnailBuilder.create_thumbnail(
                bg_image=bg_candidate,
                output_path=out_thumb,
                badge_text=badge,
                highlight_title=hl
            )
            self._set_thumbnail_preview(res_path)
            self._log(f"✔ Đã tạo Thumbnail tự động: {res_path.name}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi tạo Thumbnail", str(e))

    def _pick_custom_thumbnail(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh Thumbnail", "", "Hình ảnh (*.jpg *.jpeg *.png *.webp)")
        if path:
            self._set_thumbnail_preview(Path(path))

    def _set_thumbnail_preview(self, path: Path) -> None:
        self.current_thumbnail_path = path
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            scaled = pixmap.scaled(self.thumb_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.thumb_preview.setPixmap(scaled)

    # ==========================
    # LOGIC: UPLOAD PIPELINE
    # ==========================
    def _start_upload(self) -> None:
        ch_id = self.channel_combo.currentData()
        if not ch_id:
            QMessageBox.warning(self, "Chưa chọn kênh", "Vui lòng chọn hoặc thêm kênh YouTube trước khi đăng.")
            return

        # Gom danh sách video được tích chọn
        selected_videos: List[Path] = []
        for r in range(self.video_table.rowCount()):
            it = self.video_table.item(r, 0)
            if it and it.checkState() == Qt.Checked:
                selected_videos.append(Path(it.data(Qt.UserRole)))

        if not selected_videos:
            QMessageBox.warning(self, "Chưa chọn video", "Hãy tích chọn ít nhất 1 video trong bảng để tải lên.")
            return

        # Tính toán lịch đăng nếu chọn Schedule
        privacy_idx = self.privacy_combo.currentIndex()
        privacy_status = "schedule" if privacy_idx == 0 else (
            "public" if privacy_idx == 1 else ("unlisted" if privacy_idx == 2 else "private")
        )

        schedule_dts = []
        if privacy_status == "schedule":
            start_date = self.sch_date_edit.date().toPython()
            time_slots = [s.strip() for s in self.sch_slots_edit.text().split(",") if s.strip()]
            schedule_dts = YouTubeUploader.calculate_schedule_slots(start_date, time_slots, len(selected_videos))

        tasks: List[Dict[str, Any]] = []
        base_title = self.title_edit.text().strip()
        base_desc = self.desc_edit.toPlainText().strip()
        base_tags = self.tags_edit.text().strip()
        playlist_name = self.playlist_combo.currentText().strip()
        is_premiere = self.premiere_chk.isChecked()

        for idx, v_path in enumerate(selected_videos):
            t_title = base_title if len(selected_videos) == 1 else f"{base_title} (Tập {idx+1})"
            pub_at = schedule_dts[idx] if schedule_dts else None
            tasks.append({
                "video_path": str(v_path),
                "title": t_title[:100],
                "description": base_desc,
                "tags": base_tags,
                "privacy_status": privacy_status,
                "publish_at": pub_at,
                "is_premiere": is_premiere,
                "thumbnail_path": str(self.current_thumbnail_path) if self.current_thumbnail_path else None,
                "playlist": playlist_name,
            })

        self.btn_start_upload.setEnabled(False)
        self.btn_cancel_upload.setEnabled(True)
        self.upload_progress.setValue(0)
        self._log(f"🚀 Bắt đầu quá trình tải lên {len(tasks)} video lên kênh {self.channel_combo.currentText()}...")

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
        yt_cfg["gemini_api_key"] = self.gemini_key_edit.text().strip()
        yt_cfg["active_channel_id"] = self.channel_combo.currentData() or ""
        yt_cfg["schedule_videos_per_day"] = self.sch_per_day_spin.value()
        yt_cfg["schedule_time_slots"] = self.sch_slots_edit.text().strip()
        yt_cfg["is_premiere"] = self.premiere_chk.isChecked()
        self.settings_changed.emit(self.settings)

    def load_settings(self, settings: Dict[str, Any]) -> None:
        self.settings = settings
        yt_cfg = settings.get("youtube_uploader", {}) or {}
        if yt_cfg.get("gemini_api_key"):
            self.gemini_key_edit.setText(yt_cfg.get("gemini_api_key"))
        if yt_cfg.get("schedule_videos_per_day"):
            self.sch_per_day_spin.setValue(int(yt_cfg.get("schedule_videos_per_day", 2)))
        if yt_cfg.get("schedule_time_slots"):
            self.sch_slots_edit.setText(str(yt_cfg.get("schedule_time_slots", "11:30, 19:30")))
        self.premiere_chk.setChecked(bool(yt_cfg.get("is_premiere", False)))
