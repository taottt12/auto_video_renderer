from __future__ import annotations

import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import Signal, Qt, QDate, QThread, Slot
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton,
    QFileDialog, QCheckBox, QComboBox, QSpinBox,
    QLineEdit, QFormLayout, QTextEdit, QLabel,
    QStackedWidget, QDateEdit, QProgressBar, QMessageBox, QApplication,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QScrollArea,
    QSizePolicy
)

from core.audio_crawler import run_crawler, extract_entry_list, normalize_channel_url


class AdaptiveStackedWidget(QStackedWidget):
    """QStackedWidget tự động co giãn chiều cao theo widget đang hiển thị để tránh khoảng trắng thừa."""

    def sizeHint(self):
        cur = self.currentWidget()
        if cur:
            return cur.sizeHint()
        return super().sizeHint()

    def minimumSizeHint(self):
        cur = self.currentWidget()
        if cur:
            return cur.minimumSizeHint()
        return super().minimumSizeHint()


class ScanVideoListThread(QThread):
    scanned_signal = Signal(list)
    log_signal = Signal(str)
    error_signal = Signal(str)

    def __init__(self, crawler_cfg: Dict[str, Any]) -> None:
        super().__init__()
        self.crawler_cfg = crawler_cfg
        self.cancel_event = threading.Event()

    def stop(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            mode = str(self.crawler_cfg.get("mode") or "playlist")
            if mode == "playlist":
                url = str(self.crawler_cfg.get("playlist_url") or "").strip()
                # Quét danh sách không giới hạn (limit=0) để nạp đầy đủ các tập cho người dùng chọn
                items = extract_entry_list(
                    url=url,
                    limit=0,
                    log=self.log_signal.emit,
                    cancel_event=self.cancel_event,
                )
            elif mode == "channel":
                url = normalize_channel_url(str(self.crawler_cfg.get("channel_url") or "").strip())
                order = str(self.crawler_cfg.get("channel_order") or "newest_first")
                date_filter = str(self.crawler_cfg.get("channel_date_filter") or "all")
                date_from = str(self.crawler_cfg.get("channel_date_from") or "")
                date_to = str(self.crawler_cfg.get("channel_date_to") or "")
                # Quét danh sách không giới hạn (limit=0)
                items = extract_entry_list(
                    url=url,
                    limit=0,
                    order=order,
                    date_filter=date_filter,
                    date_from=date_from,
                    date_to=date_to,
                    log=self.log_signal.emit,
                    cancel_event=self.cancel_event,
                )
            else:
                items = []
            self.scanned_signal.emit(items)
        except Exception as exc:
            self.error_signal.emit(str(exc))


class AudioCrawlerThread(QThread):
    log_signal = Signal(str)
    progress_signal = Signal(int, int, str)
    file_downloaded_signal = Signal(str)
    finished_signal = Signal(list)
    error_signal = Signal(str)

    def __init__(self, crawler_cfg: Dict[str, Any]) -> None:
        super().__init__()
        self.crawler_cfg = crawler_cfg
        self.cancel_event = threading.Event()

    def stop(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            files = run_crawler(
                crawler_cfg=self.crawler_cfg,
                log=self.log_signal.emit,
                progress=self.progress_signal.emit,
                cancel_event=self.cancel_event,
                on_file_downloaded=self.file_downloaded_signal.emit,
            )
            self.finished_signal.emit(files)
        except Exception as exc:
            self.error_signal.emit(str(exc))


class CrawlerTab(QWidget):
    settings_changed = Signal(dict)
    audio_downloaded = Signal(str)
    audio_batch_downloaded = Signal(list)

    def __init__(self, settings: Dict[str, Any]) -> None:
        super().__init__()
        self.settings = settings
        self._lock_emit = False
        self._crawler_thread: AudioCrawlerThread | None = None
        self._scan_thread: ScanVideoListThread | None = None
        self._scanned_videos: List[Dict[str, Any]] = []
        self._lock_table_event = False
        self._build_ui()
        self.load_settings(settings)

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(12)

        # ==========================================
        # CỘT TRÁI: CẤU HÌNH & ĐIỀU KHIỂN CÀO
        # ==========================================
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        # 1. GroupBox Thiết lập nguồn cào
        cfg_group = QGroupBox("Cấu hình Cào MP3 từ Mạng")
        cfg_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        cfg_layout = QVBoxLayout(cfg_group)
        cfg_layout.setContentsMargins(8, 6, 8, 6)
        cfg_layout.setSpacing(5)

        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignRight)
        form_layout.setVerticalSpacing(4)
        form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        # Nền tảng
        self.platform_combo = QComboBox()
        self.platform_combo.addItem("YouTube", "youtube")
        self.platform_combo.addItem("Facebook (Sắp hỗ trợ)", "facebook")
        self.platform_combo.addItem("TikTok (Sắp hỗ trợ)", "tiktok")
        form_layout.addRow("Nền tảng:", self.platform_combo)

        # Thư mục lưu
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Chọn folder lưu file MP3 sau khi tải...")
        self.browse_folder_btn = QPushButton("Chọn...")
        self.browse_folder_btn.clicked.connect(self._choose_save_folder)
        self.open_folder_btn = QPushButton("Mở")
        self.open_folder_btn.clicked.connect(self._open_save_folder)
        folder_row.addWidget(self.folder_edit)
        folder_row.addWidget(self.browse_folder_btn)
        folder_row.addWidget(self.open_folder_btn)
        form_layout.addRow("Thư mục lưu:", folder_row)

        # Tự động nạp sang Render
        self.auto_add_checkbox = QCheckBox("Tự động chuyển file MP3 đã cào sang tab Render")
        self.auto_add_checkbox.setChecked(True)
        form_layout.addRow("", self.auto_add_checkbox)

        # Cào trực tiếp toàn bộ hay xem trước
        self.direct_crawl_checkbox = QCheckBox("Cào trực tiếp toàn bộ (Không cần quét xem trước)")
        self.direct_crawl_checkbox.setChecked(True)
        self.direct_crawl_checkbox.stateChanged.connect(self._on_direct_crawl_toggled)
        form_layout.addRow("", self.direct_crawl_checkbox)

        # Chế độ cào
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Cào từ Video (nhập danh sách link)", "video")
        self.mode_combo.addItem("Cào từ Danh sách phát (Playlist)", "playlist")
        self.mode_combo.addItem("Cào tất cả video của Kênh (Channel)", "channel")
        form_layout.addRow("Chế độ cào:", self.mode_combo)

        cfg_layout.addLayout(form_layout)

        # Stack chế độ
        self.mode_stack = AdaptiveStackedWidget()
        self.mode_stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        # --- Trang 0: Video đơn lẻ ---
        page_video = QWidget()
        page_video.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        page_video_layout = QVBoxLayout(page_video)
        page_video_layout.setContentsMargins(0, 4, 0, 0)
        page_video_layout.addWidget(QLabel("Danh sách URL video (mỗi hàng 1 link YouTube):"))
        self.video_urls_edit = QTextEdit()
        self.video_urls_edit.setPlaceholderText("https://www.youtube.com/watch?v=...\nhttps://youtu.be/...\nhttps://www.youtube.com/shorts/...")
        self.video_urls_edit.setMinimumHeight(80)
        page_video_layout.addWidget(self.video_urls_edit)
        self.mode_stack.addWidget(page_video)

        # --- Trang 1: Playlist ---
        page_playlist = QWidget()
        page_playlist.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        page_playlist_form = QFormLayout(page_playlist)
        page_playlist_form.setContentsMargins(0, 2, 0, 0)
        page_playlist_form.setVerticalSpacing(4)
        self.playlist_url_edit = QLineEdit()
        self.playlist_url_edit.setPlaceholderText("https://www.youtube.com/playlist?list=...")
        self.playlist_limit_label = QLabel("Số lượng tối đa:")
        self.playlist_limit_spin = QSpinBox()
        self.playlist_limit_spin.setRange(0, 10000)
        self.playlist_limit_spin.setValue(0)
        self.playlist_limit_spin.setSpecialValueText("Tất cả video")
        page_playlist_form.addRow("URL Playlist:", self.playlist_url_edit)
        page_playlist_form.addRow(self.playlist_limit_label, self.playlist_limit_spin)
        self.mode_stack.addWidget(page_playlist)

        # --- Trang 2: Channel ---
        page_channel = QWidget()
        page_channel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        page_channel_form = QFormLayout(page_channel)
        page_channel_form.setContentsMargins(0, 2, 0, 0)
        page_channel_form.setVerticalSpacing(4)
        self.channel_url_edit = QLineEdit()
        self.channel_url_edit.setPlaceholderText("https://www.youtube.com/@TenKenh hoặc URL kênh")
        self.channel_limit_label = QLabel("Số lượng cào:")
        self.channel_limit_spin = QSpinBox()
        self.channel_limit_spin.setRange(0, 10000)
        self.channel_limit_spin.setValue(50)
        self.channel_limit_spin.setSpecialValueText("Tất cả video")

        self.channel_order_combo = QComboBox()
        self.channel_order_combo.addItem("Mới nhất ➔ Cũ nhất", "newest_first")
        self.channel_order_combo.addItem("Cũ nhất ➔ Mới nhất", "oldest_first")

        self.channel_date_combo = QComboBox()
        self.channel_date_combo.addItem("Tất cả thời gian", "all")
        self.channel_date_combo.addItem("7 ngày gần nhất", "7d")
        self.channel_date_combo.addItem("30 ngày gần nhất", "30d")
        self.channel_date_combo.addItem("3 tháng gần nhất", "90d")
        self.channel_date_combo.addItem("1 năm gần nhất", "365d")
        self.channel_date_combo.addItem("Tùy chọn khoảng ngày", "custom")

        self.custom_date_widget = QWidget()
        date_row = QHBoxLayout(self.custom_date_widget)
        date_row.setContentsMargins(0, 0, 0, 0)
        self.date_from_edit = QDateEdit()
        self.date_from_edit.setCalendarPopup(True)
        self.date_from_edit.setDate(QDate.currentDate().addDays(-30))
        self.date_to_edit = QDateEdit()
        self.date_to_edit.setCalendarPopup(True)
        self.date_to_edit.setDate(QDate.currentDate())
        date_row.addWidget(QLabel("Từ:"))
        date_row.addWidget(self.date_from_edit)
        date_row.addWidget(QLabel("Đến:"))
        date_row.addWidget(self.date_to_edit)
        self.custom_date_widget.setVisible(False)

        page_channel_form.addRow("URL Kênh:", self.channel_url_edit)
        page_channel_form.addRow(self.channel_limit_label, self.channel_limit_spin)
        page_channel_form.addRow("Thứ tự video:", self.channel_order_combo)
        page_channel_form.addRow("Thời gian cào:", self.channel_date_combo)
        page_channel_form.addRow("", self.custom_date_widget)
        self.mode_stack.addWidget(page_channel)

        cfg_layout.addWidget(self.mode_stack)

        # Section: Cắt đoạn Audio sau khi tải (Audio Trimming)
        trim_box = QGroupBox("Cắt đoạn Audio sau khi tải (Audio Trimming)")
        trim_layout = QVBoxLayout(trim_box)
        trim_layout.setContentsMargins(8, 6, 8, 6)
        trim_layout.setSpacing(4)

        self.trim_enabled_cb = QCheckBox("Bật tự động cắt đoạn Audio sau khi tải về")
        self.trim_enabled_cb.setStyleSheet("font-weight: bold;")
        self.trim_enabled_cb.toggled.connect(self._on_trim_enabled_toggled)
        trim_layout.addWidget(self.trim_enabled_cb)

        trim_form = QFormLayout()
        trim_form.setLabelAlignment(Qt.AlignRight)
        trim_form.setVerticalSpacing(3)

        self.trim_mode_combo = QComboBox()
        self.trim_mode_combo.addItem("Cắt bỏ đoạn chỉ định (VD: Bỏ 10s intro 00:00 -> 00:10)", "remove_segment")
        self.trim_mode_combo.addItem("Cắt lấy đoạn (Chỉ giữ từ Thời gian bắt đầu đến Kết thúc)", "keep_segment")
        trim_form.addRow("Chế độ cắt:", self.trim_mode_combo)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Từ:"))
        self.trim_start_edit = QLineEdit("00:00:00")
        self.trim_start_edit.setPlaceholderText("00:00:00")
        time_row.addWidget(self.trim_start_edit)

        time_row.addWidget(QLabel("Đến:"))
        self.trim_end_edit = QLineEdit("00:00:10")
        self.trim_end_edit.setPlaceholderText("00:00:10 hoặc 0/để trống")
        time_row.addWidget(self.trim_end_edit)
        trim_form.addRow("Khoảng thời gian:", time_row)

        trim_layout.addLayout(trim_form)

        trim_hint = QLabel("💡 Hỗ trợ: HH:MM:SS (00:00:10), MM:SS (00:10), hoặc số giây (10). Cắt xong mới nạp vào Render.")
        trim_hint.setStyleSheet("color: #888; font-size: 10px; font-style: italic;")
        trim_layout.addWidget(trim_hint)

        cfg_layout.addWidget(trim_box)
        left_layout.addWidget(cfg_group)

        # 2. GroupBox Xem trước danh sách & Chọn tập (Range Selector)
        self.preview_group = QGroupBox("Danh sách Video quét được & Chọn tập cần cào")
        preview_layout = QVBoxLayout(self.preview_group)
        preview_layout.setContentsMargins(8, 6, 8, 6)
        preview_layout.setSpacing(4)

        scan_row = QHBoxLayout()
        self.scan_btn = QPushButton("🔍 Quét danh sách video")
        self.scan_btn.setStyleSheet("font-weight: bold; padding: 5px 12px; background-color: #0288d1; color: white;")
        self.scan_btn.clicked.connect(self._start_scan)
        self.scan_status_label = QLabel("Chưa quét danh sách.")
        self.scan_status_label.setStyleSheet("color: #888; font-size: 11px;")
        scan_row.addWidget(self.scan_btn)
        scan_row.addWidget(self.scan_status_label, 1)
        preview_layout.addLayout(scan_row)

        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("Từ tập:"))
        self.range_from_spin = QSpinBox()
        self.range_from_spin.setRange(1, 1)
        self.range_from_spin.setValue(1)
        range_row.addWidget(self.range_from_spin)

        range_row.addWidget(QLabel("Đến tập:"))
        self.range_to_spin = QSpinBox()
        self.range_to_spin.setRange(1, 1)
        self.range_to_spin.setValue(1)
        range_row.addWidget(self.range_to_spin)

        self.apply_range_btn = QPushButton("Áp dụng chọn")
        self.apply_range_btn.clicked.connect(self._apply_range_selection)
        range_row.addWidget(self.apply_range_btn)

        self.select_all_btn = QPushButton("Chọn tất cả")
        self.select_all_btn.clicked.connect(self._select_all_videos)
        range_row.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Bỏ chọn")
        self.deselect_all_btn.clicked.connect(self._deselect_all_videos)
        range_row.addWidget(self.deselect_all_btn)

        self.remove_scanned_btn = QPushButton("Xóa chọn")
        self.remove_scanned_btn.clicked.connect(self._remove_selected_scanned_items)
        range_row.addWidget(self.remove_scanned_btn)

        self.clear_scanned_btn = QPushButton("Xóa hết")
        self.clear_scanned_btn.clicked.connect(self._clear_scanned_items)
        range_row.addWidget(self.clear_scanned_btn)

        self.selected_count_label = QLabel("Đã chọn: 0/0")
        self.selected_count_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        range_row.addWidget(self.selected_count_label)
        preview_layout.addLayout(range_row)

        self.preview_table = QTableWidget(0, 3)
        self.preview_table.setHorizontalHeaderLabels(["Tập / Chọn", "Tiêu đề video", "Thời lượng"])
        self.preview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.preview_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview_table.setMinimumHeight(100)
        self.preview_table.setMaximumHeight(140)
        self.preview_table.itemChanged.connect(self._on_table_item_changed)
        preview_layout.addWidget(self.preview_table)

        filter_note = QLabel("🛡 Đã tự động lọc bỏ video khóa hội viên (Members-only), video riêng tư và chưa công chiếu.")
        filter_note.setStyleSheet("color: #888; font-size: 10px; font-style: italic;")
        preview_layout.addWidget(filter_note)

        left_layout.addWidget(self.preview_group)

        # 3. GroupBox Điều khiển tác vụ & Tiến trình
        action_group = QGroupBox("Điều khiển tác vụ")
        action_layout = QVBoxLayout(action_group)
        action_layout.setContentsMargins(8, 6, 8, 6)
        action_layout.setSpacing(5)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("▶ Bắt đầu cào MP3")
        self.start_btn.setStyleSheet("font-weight: bold; font-size: 12px; padding: 6px 14px; background-color: #2e7d32; color: white;")
        self.start_btn.clicked.connect(self._start_or_stop_crawler)

        self.stop_btn = QPushButton("⏹ Dừng cào")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("font-weight: bold; padding: 6px 14px;")
        self.stop_btn.clicked.connect(self._stop_crawler)

        self.transfer_all_btn = QPushButton("➔ Chuyển toàn bộ sang Render")
        self.transfer_all_btn.setStyleSheet("font-weight: bold; padding: 6px 12px;")
        self.transfer_all_btn.clicked.connect(self._transfer_all_to_render)

        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.transfer_all_btn)
        action_layout.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        action_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Sẵn sàng.")
        self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        action_layout.addWidget(self.status_label)

        left_layout.addWidget(action_group)
        left_layout.addStretch(1)

        # ==========================================
        # CỘT PHẢI: KHUNG LOG CHUYÊN BIỆT & RỘNG RÃI
        # ==========================================
        right_group = QGroupBox("Nhật ký cào MP3 (Real-time Log)")
        right_layout = QVBoxLayout(right_group)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(8)

        log_tools = QHBoxLayout()
        self.log_info_label = QLabel("Theo dõi tiến trình tải, trích xuất FFmpeg và lỗi chi tiết:")
        self.clear_log_btn = QPushButton("Xóa log")
        self.clear_log_btn.clicked.connect(self._clear_log)
        self.copy_log_btn = QPushButton("Sao chép log")
        self.copy_log_btn.clicked.connect(self._copy_log)

        log_tools.addWidget(self.log_info_label, 1)
        log_tools.addWidget(self.copy_log_btn)
        log_tools.addWidget(self.clear_log_btn)
        right_layout.addLayout(log_tools)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        log_font = QFont("Consolas", 10)
        log_font.setStyleHint(QFont.Monospace)
        self.log_box.setFont(log_font)
        self.log_box.setStyleSheet(
            "background-color: #1e1e1e; color: #d4d4d4; border-radius: 4px; padding: 6px;"
        )
        right_layout.addWidget(self.log_box, 1)

        scroll_left = QScrollArea()
        scroll_left.setWidgetResizable(True)
        scroll_left.setFrameShape(QScrollArea.NoFrame)
        scroll_left.setWidget(left_widget)

        main_layout.addWidget(scroll_left, 5)
        main_layout.addWidget(right_group, 5)

        # Signals kết nối UI
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.channel_date_combo.currentIndexChanged.connect(
            lambda: self.custom_date_widget.setVisible(self.channel_date_combo.currentData() == "custom")
        )

        self._connect_change_events(
            self.platform_combo, self.folder_edit, self.auto_add_checkbox,
            self.direct_crawl_checkbox,
            self.mode_combo, self.video_urls_edit, self.playlist_url_edit,
            self.playlist_limit_spin, self.channel_url_edit, self.channel_limit_spin,
            self.channel_order_combo, self.channel_date_combo,
            self.date_from_edit, self.date_to_edit,
            self.trim_enabled_cb, self.trim_mode_combo, self.trim_start_edit, self.trim_end_edit
        )

    def _connect_change_events(self, *widgets: Any) -> None:
        for w in widgets:
            if hasattr(w, "stateChanged"):
                w.stateChanged.connect(self._emit)
            elif hasattr(w, "currentIndexChanged"):
                w.currentIndexChanged.connect(self._emit)
            elif hasattr(w, "valueChanged"):
                w.valueChanged.connect(self._emit)
            elif hasattr(w, "textChanged"):
                w.textChanged.connect(self._emit)

    def _on_mode_changed(self, index: int) -> None:
        self.mode_stack.setCurrentIndex(index)
        self.mode_stack.updateGeometry()
        mode = self.mode_combo.currentData() or "video"
        is_batch_mode = mode in ["playlist", "channel"]
        self.direct_crawl_checkbox.setVisible(is_batch_mode)
        self._on_direct_crawl_toggled()
        self._emit()

    def _on_direct_crawl_toggled(self) -> None:
        direct = self.direct_crawl_checkbox.isChecked()
        mode = self.mode_combo.currentData() or "video"
        is_batch_mode = mode in ["playlist", "channel"]

        # Ẩn số lượng tối đa khi KHÔNG cào trực tiếp để khỏi đụng và gây hiểu lầm
        show_limit = direct and is_batch_mode
        if hasattr(self, "playlist_limit_label"):
            self.playlist_limit_label.setVisible(show_limit)
            self.playlist_limit_spin.setVisible(show_limit)
        if hasattr(self, "channel_limit_label"):
            self.channel_limit_label.setVisible(show_limit)
            self.channel_limit_spin.setVisible(show_limit)

        # Bảng xem trước & chọn tập: chỉ hiện khi KHÔNG cào trực tiếp và ở chế độ playlist/channel
        show_preview = (not direct) and is_batch_mode
        self.preview_group.setVisible(show_preview)
        self.preview_group.setEnabled(show_preview)
        self.mode_stack.updateGeometry()
        self._emit()

    def _start_scan(self) -> None:
        cfg = self.collect_settings().get("audio_crawler", {})
        mode = cfg.get("mode", "playlist")
        if mode == "playlist" and not cfg.get("playlist_url", "").strip():
            QMessageBox.warning(self, "Thiếu liên kết", "Vui lòng nhập URL Danh sách phát (Playlist) để quét.")
            return
        elif mode == "channel" and not cfg.get("channel_url", "").strip():
            QMessageBox.warning(self, "Thiếu liên kết", "Vui lòng nhập URL Kênh YouTube (Channel) để quét.")
            return

        self.scan_btn.setEnabled(False)
        self.scan_status_label.setText("Đang quét danh sách video từ YouTube...")
        self.append_log("🔍 Bắt đầu quét danh sách video (tự động loại bỏ video hội viên/khóa)...")

        self._scan_thread = ScanVideoListThread(cfg)
        self._scan_thread.log_signal.connect(self.append_log)
        self._scan_thread.scanned_signal.connect(self._on_scan_finished)
        self._scan_thread.error_signal.connect(self._on_scan_error)
        self._scan_thread.start()

    @Slot(list)
    def _on_scan_finished(self, items: List[Dict[str, Any]]) -> None:
        self.scan_btn.setEnabled(True)
        self._scanned_videos = list(items)
        n = len(items)
        self.scan_status_label.setText(f"Đã tìm thấy {n} video hợp lệ.")
        self.append_log(f"🔍 Quét hoàn tất: {n} video hợp lệ sẵn sàng.")

        self._lock_table_event = True
        self.preview_table.setRowCount(0)
        self.range_from_spin.setRange(1, max(1, n))
        self.range_to_spin.setRange(1, max(1, n))
        self.range_from_spin.setValue(1)
        self.range_to_spin.setValue(max(1, n))

        for idx, item in enumerate(items):
            r = self.preview_table.rowCount()
            self.preview_table.insertRow(r)

            check_item = QTableWidgetItem(f"Tập {idx + 1}")
            check_item.setCheckState(Qt.Checked)
            check_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            self.preview_table.setItem(r, 0, check_item)

            title_item = QTableWidgetItem(item.get("title", ""))
            title_item.setToolTip(item.get("title", ""))
            self.preview_table.setItem(r, 1, title_item)

            dur_item = QTableWidgetItem(item.get("duration_str", "--:--"))
            dur_item.setTextAlignment(Qt.AlignCenter)
            self.preview_table.setItem(r, 2, dur_item)

        self._lock_table_event = False
        self._update_selected_count()

    @Slot(str)
    def _on_scan_error(self, err_msg: str) -> None:
        self.scan_btn.setEnabled(True)
        self.scan_status_label.setText("Lỗi khi quét danh sách.")
        self.append_log(f"❌ Lỗi quét danh sách: {err_msg}")
        QMessageBox.critical(self, "Lỗi quét video", f"Không thể quét danh sách video:\n{err_msg}")

    def _apply_range_selection(self) -> None:
        total = self.preview_table.rowCount()
        if total == 0:
            return
        start = self.range_from_spin.value()
        end = self.range_to_spin.value()
        if start > end:
            start, end = end, start

        self._lock_table_event = True
        for r in range(total):
            item = self.preview_table.item(r, 0)
            if item:
                state = Qt.Checked if (start <= r + 1 <= end) else Qt.Unchecked
                item.setCheckState(state)
        self._lock_table_event = False
        self._update_selected_count()

    def _select_all_videos(self) -> None:
        self._lock_table_event = True
        for r in range(self.preview_table.rowCount()):
            item = self.preview_table.item(r, 0)
            if item:
                item.setCheckState(Qt.Checked)
        self._lock_table_event = False
        self._update_selected_count()

    def _deselect_all_videos(self) -> None:
        self._lock_table_event = True
        for r in range(self.preview_table.rowCount()):
            item = self.preview_table.item(r, 0)
            if item:
                item.setCheckState(Qt.Unchecked)
        self._lock_table_event = False
        self._update_selected_count()

    def _remove_selected_scanned_items(self) -> None:
        """Xóa các video được tích chọn (hoặc được highlight) khỏi bảng danh sách đã quét."""
        total = self.preview_table.rowCount()
        if total == 0:
            return

        # 1. Ưu tiên cao nhất: Tìm tất cả các dòng ĐÃ TÍCH CHỌN checkbox (Qt.Checked)
        checked_rows = []
        for r in range(total):
            item = self.preview_table.item(r, 0)
            if item and item.checkState() == Qt.Checked:
                checked_rows.append(r)

        # 2. Nếu có dòng tích chọn checkbox, dùng danh sách này. Nếu không, mới lấy dòng đang bôi đen bằng chuột
        if checked_rows:
            rows_to_delete = checked_rows
        else:
            rows_to_delete = list({idx.row() for idx in self.preview_table.selectionModel().selectedRows()})

        if not rows_to_delete:
            QMessageBox.information(self, "Chưa chọn dòng", "Vui lòng tích chọn các video cần xóa khỏi danh sách.")
            return

        self._lock_table_event = True
        try:
            # Xóa từ dưới lên để không bị lệch chỉ số index
            for r in sorted(rows_to_delete, reverse=True):
                if 0 <= r < len(self._scanned_videos):
                    self._scanned_videos.pop(r)
                self.preview_table.removeRow(r)

            # Cập nhật lại số thứ tự Tập 1, Tập 2,...
            new_total = self.preview_table.rowCount()
            for r in range(new_total):
                item = self.preview_table.item(r, 0)
                if item:
                    item.setText(f"Tập {r + 1}")

            self.range_from_spin.setRange(1, max(1, new_total))
            self.range_to_spin.setRange(1, max(1, new_total))
            self.range_from_spin.setValue(1)
            self.range_to_spin.setValue(max(1, new_total))
        finally:
            self._lock_table_event = False

        self._update_selected_count()
        self.scan_status_label.setText(f"Còn lại {self.preview_table.rowCount()} video trong danh sách.")

    def _clear_scanned_items(self) -> None:
        """Xóa toàn bộ danh sách đã quét."""
        if self.preview_table.rowCount() == 0:
            return
        self._lock_table_event = True
        self._scanned_videos.clear()
        self.preview_table.setRowCount(0)
        self.range_from_spin.setRange(1, 1)
        self.range_to_spin.setRange(1, 1)
        self.range_from_spin.setValue(1)
        self.range_to_spin.setValue(1)
        self._lock_table_event = False
        self._update_selected_count()
        self.scan_status_label.setText("Đã xóa sạch danh sách video.")

    def _on_trim_enabled_toggled(self) -> None:
        enabled = self.trim_enabled_cb.isChecked()
        self.trim_mode_combo.setEnabled(enabled)
        self.trim_start_edit.setEnabled(enabled)
        self.trim_end_edit.setEnabled(enabled)
        self._emit()

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        if not self._lock_table_event and item.column() == 0:
            self._update_selected_count()

    def _update_selected_count(self) -> None:
        total = self.preview_table.rowCount()
        selected = 0
        for r in range(total):
            item = self.preview_table.item(r, 0)
            if item and item.checkState() == Qt.Checked:
                selected += 1
        self.selected_count_label.setText(f"Đã chọn: {selected}/{total}")

    def _choose_save_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu MP3")
        if folder:
            self.folder_edit.setText(folder)
            self._emit()

    def _open_save_folder(self) -> None:
        folder = self.folder_edit.text().strip()
        if not folder or not os.path.exists(folder):
            QMessageBox.warning(self, "Thư mục không tồn tại", f"Thư mục sau chưa tồn tại hoặc chưa được chọn:\n{folder}")
            return
        try:
            os.startfile(folder)
        except Exception as exc:
            QMessageBox.information(self, "Lỗi mở folder", f"Không thể mở folder: {exc}")

    def _clear_log(self) -> None:
        self.log_box.clear()

    def _copy_log(self) -> None:
        text = self.log_box.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.append_log("[Thông báo] Đã sao chép toàn bộ nhật ký vào clipboard.")

    @Slot(str)
    def append_log(self, message: str) -> None:
        t = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{t}] {message}")
        self.log_box.moveCursor(QTextCursor.End)

    def _start_or_stop_crawler(self) -> None:
        if self._crawler_thread and self._crawler_thread.isRunning():
            self._stop_crawler()
            return
        self._start_crawler()

    def _start_crawler(self) -> None:
        cfg = self.collect_settings().get("audio_crawler", {})
        folder = cfg.get("save_folder", "").strip()
        if not folder:
            QMessageBox.warning(self, "Thiếu thư mục lưu", "Vui lòng chọn thư mục lưu file MP3 trước khi cào.")
            return

        mode = cfg.get("mode", "video")
        if mode == "video" and not cfg.get("video_urls", "").strip():
            QMessageBox.warning(self, "Thiếu liên kết", "Vui lòng nhập ít nhất 1 đường link YouTube để cào.")
            return
        elif mode == "playlist" and not cfg.get("playlist_url", "").strip():
            QMessageBox.warning(self, "Thiếu liên kết", "Vui lòng nhập URL Danh sách phát (Playlist).")
            return
        elif mode == "channel" and not cfg.get("channel_url", "").strip():
            QMessageBox.warning(self, "Thiếu liên kết", "Vui lòng nhập URL Kênh YouTube (Channel).")
            return

        if mode in ["playlist", "channel"] and not self.direct_crawl_checkbox.isChecked():
            selected_targets = []
            for r in range(self.preview_table.rowCount()):
                item = self.preview_table.item(r, 0)
                if item and item.checkState() == Qt.Checked:
                    if r < len(self._scanned_videos):
                        selected_targets.append(self._scanned_videos[r])

            if not selected_targets:
                if self.preview_table.rowCount() == 0:
                    QMessageBox.warning(
                        self, "Chưa quét video",
                        "Vui lòng bấm '🔍 Quét danh sách video' để xem trước và chọn tập cần cào, hoặc tích chọn 'Cào trực tiếp toàn bộ'."
                    )
                    return
                else:
                    QMessageBox.warning(
                        self, "Chưa chọn video",
                        "Vui lòng tích chọn ít nhất 1 video trong bảng danh sách để cào."
                    )
                    return
            cfg["selected_targets"] = selected_targets

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("Đang khởi tạo trình cào MP3...")
        self.append_log("══════════════════════════════════════════════════════")
        self.append_log("🚀 Bắt đầu phiên cào MP3 mới...")

        self._crawler_thread = AudioCrawlerThread(cfg)
        self._crawler_thread.log_signal.connect(self.append_log)
        self._crawler_thread.progress_signal.connect(self._on_progress)
        self._crawler_thread.file_downloaded_signal.connect(self._on_file_downloaded)
        self._crawler_thread.finished_signal.connect(self._on_finished)
        self._crawler_thread.error_signal.connect(self._on_error)
        self._crawler_thread.start()

    def _stop_crawler(self) -> None:
        if self._crawler_thread and self._crawler_thread.isRunning():
            self.stop_btn.setEnabled(False)
            self.status_label.setText("Đang yêu cầu dừng tác vụ...")
            self.append_log("⏹ Người dùng bấm dừng. Đang dọn dẹp các tiến trình...")
            self._crawler_thread.stop()

    @Slot(int, int, str)
    def _on_progress(self, cur: int, total: int, txt: str) -> None:
        if total > 0:
            pct = int((cur / total) * 100)
            self.progress_bar.setValue(pct)
        self.status_label.setText(txt)

    @Slot(str)
    def _on_file_downloaded(self, fpath: str) -> None:
        if self.auto_add_checkbox.isChecked():
            self.audio_downloaded.emit(fpath)

    @Slot(list)
    def _on_finished(self, files: list) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText(f"Hoàn thành! Đã cào {len(files)} file.")
        self.append_log(f"🏁 Hoàn tất quá trình cào! Tổng cộng: {len(files)} file MP3 đã sẵn sàng.")
        self.append_log("══════════════════════════════════════════════════════")
        if self.auto_add_checkbox.isChecked() and files:
            self.audio_batch_downloaded.emit(files)
            self.append_log(f"➔ Đã tự động chuyển {len(files)} file MP3 sang tab Render.")

        QMessageBox.information(
            self, "Cào MP3 Hoàn Tất",
            f"Đã hoàn thành phiên cào MP3!\n"
            f"Số file tải thành công: {len(files)}\n"
            f"Thư mục lưu: {self.folder_edit.text()}"
        )

    @Slot(str)
    def _on_error(self, err_msg: str) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Gặp lỗi trong quá trình cào.")
        self.append_log(f"❌ LỖI NGHIÊM TRỌNG: {err_msg}")
        QMessageBox.critical(self, "Lỗi cào MP3", f"Gặp lỗi khi cào audio:\n{err_msg}")

    def _transfer_all_to_render(self) -> None:
        folder = self.folder_edit.text().strip()
        if not folder or not os.path.exists(folder):
            QMessageBox.warning(self, "Thư mục không tồn tại", "Thư mục lưu hiện tại không tồn tại.")
            return

        mp3_files = sorted([
            str(p) for p in Path(folder).glob("*.mp3")
            if p.is_file() and p.stat().st_size > 1024
        ])

        if not mp3_files:
            QMessageBox.information(self, "Không tìm thấy file", f"Không có file .mp3 hợp lệ nào trong:\n{folder}")
            return

        reply = QMessageBox.question(
            self,
            "Xác nhận chuyển sang Render",
            f"Tìm thấy {len(mp3_files)} file MP3 trong thư mục:\n{folder}\n\nBạn có muốn chuyển toàn bộ vào danh sách tab Render không?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            self.append_log("Đã hủy chuyển file sang tab Render theo lựa chọn của bạn.")
            return

        self.audio_batch_downloaded.emit(mp3_files)
        self.append_log(f"➔ Đã chuyển {len(mp3_files)} file MP3 từ thư mục sang danh sách tab Render.")
        QMessageBox.information(self, "Đã chuyển", f"Đã nạp {len(mp3_files)} file MP3 vào danh sách Render thành công!")

    def collect_settings(self) -> Dict[str, Any]:
        settings = dict(self.settings)
        crawler_settings = {
            "platform": self.platform_combo.currentData() or "youtube",
            "save_folder": self.folder_edit.text().strip(),
            "auto_add_to_audio_list": self.auto_add_checkbox.isChecked(),
            "direct_crawl": self.direct_crawl_checkbox.isChecked(),
            "mode": self.mode_combo.currentData() or "video",
            "video_urls": self.video_urls_edit.toPlainText().strip(),
            "playlist_url": self.playlist_url_edit.text().strip(),
            "playlist_limit": self.playlist_limit_spin.value(),
            "channel_url": self.channel_url_edit.text().strip(),
            "channel_limit": self.channel_limit_spin.value(),
            "channel_order": self.channel_order_combo.currentData() or "newest_first",
            "channel_date_filter": self.channel_date_combo.currentData() or "all",
            "channel_date_from": self.date_from_edit.date().toString("yyyy-MM-dd"),
            "channel_date_to": self.date_to_edit.date().toString("yyyy-MM-dd"),
            "audio_trim": {
                "enabled": self.trim_enabled_cb.isChecked(),
                "mode": self.trim_mode_combo.currentData() or "remove_segment",
                "start_time": self.trim_start_edit.text().strip(),
                "end_time": self.trim_end_edit.text().strip(),
            },
        }
        settings["audio_crawler"] = crawler_settings
        return settings

    def load_settings(self, settings: Dict[str, Any]) -> None:
        self._lock_emit = True
        self.settings = settings
        crawler_cfg = settings.get("audio_crawler", {}) or {}

        self._set_combo_by_data(self.platform_combo, crawler_cfg.get("platform", "youtube"))
        self.folder_edit.setText(str(crawler_cfg.get("save_folder", "")))
        self.auto_add_checkbox.setChecked(bool(crawler_cfg.get("auto_add_to_audio_list", True)))
        self.direct_crawl_checkbox.setChecked(bool(crawler_cfg.get("direct_crawl", True)))
        self._set_combo_by_data(self.mode_combo, crawler_cfg.get("mode", "video"))
        self.mode_stack.setCurrentIndex(self.mode_combo.currentIndex())
        self.video_urls_edit.setPlainText(str(crawler_cfg.get("video_urls", "")))
        self.playlist_url_edit.setText(str(crawler_cfg.get("playlist_url", "")))
        self.playlist_limit_spin.setValue(int(crawler_cfg.get("playlist_limit", 0)))
        self.channel_url_edit.setText(str(crawler_cfg.get("channel_url", "")))
        self.channel_limit_spin.setValue(int(crawler_cfg.get("channel_limit", 50)))
        self._set_combo_by_data(self.channel_order_combo, crawler_cfg.get("channel_order", "newest_first"))
        self._set_combo_by_data(self.channel_date_combo, crawler_cfg.get("channel_date_filter", "all"))

        trim_cfg = crawler_cfg.get("audio_trim", {}) or {}
        self.trim_enabled_cb.setChecked(bool(trim_cfg.get("enabled", False)))
        self._set_combo_by_data(self.trim_mode_combo, trim_cfg.get("mode", "remove_segment"))
        self.trim_start_edit.setText(str(trim_cfg.get("start_time", "00:00:00")))
        self.trim_end_edit.setText(str(trim_cfg.get("end_time", "00:00:10")))
        self._on_trim_enabled_toggled()

        is_custom = (self.channel_date_combo.currentData() == "custom")
        self.custom_date_widget.setVisible(is_custom)

        d_from_str = crawler_cfg.get("channel_date_from", "")
        if d_from_str:
            d_from = QDate.fromString(d_from_str, "yyyy-MM-dd")
            if d_from.isValid():
                self.date_from_edit.setDate(d_from)
        d_to_str = crawler_cfg.get("channel_date_to", "")
        if d_to_str:
            d_to = QDate.fromString(d_to_str, "yyyy-MM-dd")
            if d_to.isValid():
                self.date_to_edit.setDate(d_to)

        self._on_direct_crawl_toggled()
        self._on_mode_changed(self.mode_combo.currentIndex())
        self._lock_emit = False

    @staticmethod
    def _set_combo_by_data(combo: QComboBox, value: Any) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    def _emit(self, *args: Any) -> None:
        if self._lock_emit:
            return
        settings = self.collect_settings()
        self.settings = settings
        self.settings_changed.emit(settings)
