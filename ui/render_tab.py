from __future__ import annotations

import copy
import os
import random
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PySide6.QtCore import QThread, Signal, Slot, QTimer, Qt, QUrl
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
    QTextEdit, QProgressBar, QMessageBox, QAbstractItemView, QGroupBox, QListWidget,
    QFileDialog, QCheckBox, QLabel, QSlider, QFrame, QSplitter, QHeaderView
)

from core.media_utils import (
    AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS,
    get_duration_seconds, seconds_to_hhmmss, is_image, is_video
)
from core.paths import find_binary
from core.render_engine import RenderEngine, RenderResult


def natural_sort_key(s: str) -> list:
    """Tách số và chữ để sắp xếp tự nhiên: P1, P2, ... P9, P10, P32 thay vì P1, P10, P2."""
    name = Path(s).name
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


class DurationLoaderThread(QThread):
    duration_loaded = Signal(int, str)  # row, duration_str

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.queue: List[Tuple[int, str]] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def add_tasks(self, tasks: List[Tuple[int, str]]) -> None:
        with self._lock:
            self.queue.extend(tasks)
        if not self.isRunning():
            self._stop_event.clear()
            self.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            self.queue.clear()

    def run(self) -> None:
        while not self._stop_event.is_set():
            task = None
            with self._lock:
                if self.queue:
                    task = self.queue.pop(0)
            if not task:
                break
            row, audio_path = task
            try:
                sec = get_duration_seconds(audio_path)
                dur_str = seconds_to_hhmmss(sec)
            except Exception:
                dur_str = "--:--"
            if not self._stop_event.is_set():
                self.duration_loaded.emit(row, dur_str)


class RenderWorker(QThread):
    log_signal = Signal(str)
    row_update_signal = Signal(int, str, str, int, str)
    row_started_signal = Signal(int)
    row_finished_signal = Signal(int)
    finished_signal = Signal()

    def __init__(self, settings: Dict[str, Any], rows: List[int], audio_files: List[str]) -> None:
        super().__init__()
        self.settings = settings
        self.rows = rows
        self.audio_files = audio_files
        self.cancel_event = threading.Event()

    def stop(self) -> None:
        self.cancel_event.set()

    def _max_workers(self) -> int:
        perf = self.settings.get("performance", {}) or {}
        try:
            return max(1, min(10, int(perf.get("max_parallel_jobs", 1))))
        except Exception:
            return 1

    def _render_one(self, row: int, audio: str, bgm_file: str = "") -> Tuple[int, RenderResult]:
        def log(msg: str, row=row) -> None:
            self.log_signal.emit(f"[Dòng {row + 1}] {msg}")

        def progress(percent: int, stage: str, row=row) -> None:
            self.row_update_signal.emit(row, "Đang chạy", stage, percent, "")

        self.row_started_signal.emit(row)
        self.row_update_signal.emit(row, "Đang chạy", "Bắt đầu", 0, "")
        self.log_signal.emit(f"[Dòng {row + 1}] Bắt đầu render: {audio}")
        job_settings = copy.deepcopy(self.settings)
        if bgm_file:
            job_settings.setdefault("background_music", {})["selected_file"] = bgm_file
        engine = RenderEngine(job_settings, log=log, progress=progress, cancel_event=self.cancel_event)
        result = engine.render_audio(audio)
        self.row_finished_signal.emit(row)
        return row, result

    def _build_bgm_assignments(self, total: int) -> List[str]:
        bgm_cfg = self.settings.get("background_music", {}) or {}
        if not bgm_cfg.get("enabled"):
            return [""] * total
        files = [str(f).strip() for f in (bgm_cfg.get("files") or []) if str(f).strip()]
        legacy_file = str(bgm_cfg.get("file", "")).strip()
        if legacy_file and legacy_file not in files:
            files.append(legacy_file)
        if not files:
            return [""] * total

        shuffle = bool(bgm_cfg.get("shuffle", True))
        avoid_repeat = bool(bgm_cfg.get("avoid_repeat", True))
        assignments: List[str] = []
        last = ""
        rng = random.Random()
        while len(assignments) < total:
            cycle = files[:]
            if shuffle:
                rng.shuffle(cycle)
            if avoid_repeat and last and len(cycle) > 1 and cycle[0] == last:
                cycle = cycle[1:] + cycle[:1]
            for file in cycle:
                if len(assignments) >= total:
                    break
                assignments.append(file)
                last = file
        if files:
            self.log_signal.emit(f"Đã phân bổ {len(assignments)} nhạc nền cho queue từ {len(files)} file.")
        return assignments

    def run(self) -> None:
        max_workers = self._max_workers()
        self.log_signal.emit(f"Bắt đầu queue với {max_workers} luồng render song song.")
        bgm_assignments = self._build_bgm_assignments(len(self.audio_files))
        delete_audio = bool(self.settings.get("delete_audio_after_render", False))
        futures = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for idx, (row, audio) in enumerate(zip(self.rows, self.audio_files)):
                if self.cancel_event.is_set():
                    self.row_update_signal.emit(row, "Đã dừng", "Dừng bởi người dùng", 0, "")
                    continue
                futures.append(executor.submit(self._render_one, row, audio, bgm_assignments[idx] if idx < len(bgm_assignments) else ""))
            for future in as_completed(futures):
                try:
                    row, result = future.result()
                    if result.success:
                        self.row_update_signal.emit(row, "Hoàn thành", "Xong", 100, str(result.output_file))
                        self.log_signal.emit(f"[Dòng {row + 1}] Hoàn thành: {result.output_file}")

                        if delete_audio:
                            try:
                                audio_p = Path(result.audio_file)
                                if audio_p.exists():
                                    audio_p.unlink(missing_ok=True)
                                    self.log_signal.emit(f"[Dòng {row + 1}] 🗑 Đã xóa file MP3 nguồn: {audio_p.name}")
                            except Exception as ex_del:
                                self.log_signal.emit(f"[Dòng {row + 1}] ⚠️ Không thể xóa file MP3 nguồn ({result.audio_file}): {ex_del}")
                    else:
                        status = "Đã dừng" if self.cancel_event.is_set() else "Lỗi"
                        self.row_update_signal.emit(row, status, result.message, 0, "")
                        self.log_signal.emit(f"[Dòng {row + 1}] {status}: {result.message}")
                except Exception as exc:
                    self.log_signal.emit(f"Lỗi worker: {exc}")
        self.finished_signal.emit()


class RenderTab(QWidget):
    project_requested = Signal()
    render_lock_changed = Signal(bool)
    settings_changed = Signal(dict)

    def __init__(self, settings: Dict[str, Any]) -> None:
        super().__init__()
        self.settings = settings
        self._lock_sync = False
        self.worker: RenderWorker | None = None
        self.duration_loader = DurationLoaderThread(self)
        self.duration_loader.duration_loaded.connect(self._on_duration_loaded)
        self.row_start_times: Dict[int, float] = {}
        self.row_elapsed_final: Dict[int, float] = {}
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_elapsed_times)

        # Audio Player (Nghe thử)
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(self._on_player_position_changed)
        self.player.durationChanged.connect(self._on_player_duration_changed)
        self.player.playbackStateChanged.connect(self._on_player_state_changed)
        self._is_seeking = False

        self._ffmpeg_bin = ""

        self._build_ui()
        self.load_settings(settings)

    def _ffmpeg_path(self) -> str:
        if not self._ffmpeg_bin:
            try:
                self._ffmpeg_bin = find_binary("ffmpeg.exe")
            except Exception:
                self._ffmpeg_bin = find_binary("ffmpeg")
        return self._ffmpeg_bin

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ====================================================
        # 1. KHU VỰC TRÊN: 3 CỘT (AUDIO, NGHE THỬ, MEDIA & PREVIEW)
        # ====================================================
        top_layout = QHBoxLayout()
        top_layout.setSpacing(10)

        # --- Cột 1: Danh sách Audio chính & Sắp xếp ---
        audio_group = QGroupBox("1. Danh sách Audio chính")
        audio_layout = QVBoxLayout(audio_group)
        audio_layout.setContentsMargins(8, 8, 8, 8)
        audio_layout.setSpacing(6)

        self.audio_list = QListWidget()
        self.audio_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.audio_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.audio_list.setDefaultDropAction(Qt.MoveAction)
        self.audio_list.setMaximumHeight(135)
        self.audio_list.itemClicked.connect(self._on_audio_item_clicked)
        audio_layout.addWidget(self.audio_list)

        # Hàng công cụ sắp xếp
        sort_row = QHBoxLayout()
        self.audio_count_label = QLabel("Tổng: 0 audio")
        self.audio_count_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 11px;")
        self.btn_sort_natural = QPushButton("Sắp xếp tự nhiên (P1, P2...)")
        self.btn_sort_natural.setToolTip("Sắp xếp thông minh theo số tập P1 ➔ P2 ➔ P10 ➔ P32")
        self.btn_sort_natural.clicked.connect(self._sort_audio_natural)
        self.btn_sort_az = QPushButton("A➔Z")
        self.btn_sort_az.clicked.connect(self._sort_audio_az)
        self.btn_sort_za = QPushButton("Z➔A")
        self.btn_sort_za.clicked.connect(self._sort_audio_za)
        self.btn_audio_up = QPushButton("▲")
        self.btn_audio_up.setToolTip("Đưa mục chọn lên trên")
        self.btn_audio_up.clicked.connect(self._move_audio_up)
        self.btn_audio_down = QPushButton("▼")
        self.btn_audio_down.setToolTip("Đưa mục chọn xuống dưới")
        self.btn_audio_down.clicked.connect(self._move_audio_down)

        sort_row.addWidget(self.audio_count_label)
        sort_row.addStretch(1)
        sort_row.addWidget(self.btn_sort_natural)
        sort_row.addWidget(self.btn_sort_az)
        sort_row.addWidget(self.btn_sort_za)
        sort_row.addWidget(self.btn_audio_up)
        sort_row.addWidget(self.btn_audio_down)
        audio_layout.addLayout(sort_row)

        # Hàng nút thêm xóa audio
        audio_btns = QHBoxLayout()
        self.add_audio_btn = QPushButton("Thêm audio từ máy")
        self.remove_audio_btn = QPushButton("Xóa chọn")
        self.clear_audio_btn = QPushButton("Xóa hết")
        self.add_audio_btn.clicked.connect(self._choose_and_add_audio)
        self.remove_audio_btn.clicked.connect(lambda: self._remove_selected_items(self.audio_list))
        self.clear_audio_btn.clicked.connect(self._clear_audio_list)

        audio_btns.addStretch(1)
        audio_btns.addWidget(self.add_audio_btn)
        audio_btns.addWidget(self.remove_audio_btn)
        audio_btns.addWidget(self.clear_audio_btn)
        audio_layout.addLayout(audio_btns)

        top_layout.addWidget(audio_group, 4)

        # --- Cột 2: Trình Nghe thử Audio ---
        player_group = QGroupBox("2. Nghe thử Audio (Player)")
        player_layout = QVBoxLayout(player_group)
        player_layout.setContentsMargins(8, 8, 8, 8)
        player_layout.setSpacing(6)

        self.audio_track_label = QLabel("Chọn một audio bên trái để nghe thử...")
        self.audio_track_label.setWordWrap(True)
        self.audio_track_label.setStyleSheet("color: #d4d4d4; font-weight: bold; font-size: 11px;")
        player_layout.addWidget(self.audio_track_label)

        # Slider tua
        self.audio_seek_slider = QSlider(Qt.Horizontal)
        self.audio_seek_slider.setRange(0, 1000)
        self.audio_seek_slider.sliderMoved.connect(self._on_seek_slider_moved)
        self.audio_seek_slider.sliderReleased.connect(self._on_seek_slider_released)
        player_layout.addWidget(self.audio_seek_slider)

        time_row = QHBoxLayout()
        self.audio_time_label = QLabel("00:00 / 00:00")
        self.audio_time_label.setStyleSheet("color: #888; font-size: 11px;")
        time_row.addWidget(self.audio_time_label)
        time_row.addStretch(1)
        player_layout.addLayout(time_row)

        ctrl_row = QHBoxLayout()
        self.play_btn = QPushButton("▶ Phát")
        self.play_btn.clicked.connect(self._toggle_playback)
        self.stop_playback_btn = QPushButton("⏹ Dừng")
        self.stop_playback_btn.clicked.connect(self._stop_playback)

        vol_label = QLabel("🔊")
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(80)
        self.vol_slider.setMaximumWidth(80)
        self.vol_slider.valueChanged.connect(lambda val: self.audio_output.setVolume(val / 100.0))

        ctrl_row.addWidget(self.play_btn)
        ctrl_row.addWidget(self.stop_playback_btn)
        ctrl_row.addSpacing(10)
        ctrl_row.addWidget(vol_label)
        ctrl_row.addWidget(self.vol_slider)
        ctrl_row.addStretch(1)
        player_layout.addLayout(ctrl_row)
        player_layout.addStretch(1)

        top_layout.addWidget(player_group, 3)

        # --- Cột 3: Danh sách Media & Xem trước Media ---
        media_group = QGroupBox("3. Media & Xem trước (Ảnh/Video)")
        media_layout = QVBoxLayout(media_group)
        media_layout.setContentsMargins(8, 8, 8, 8)
        media_layout.setSpacing(6)

        media_top_split = QHBoxLayout()
        # Danh sách Media
        media_list_box = QVBoxLayout()
        self.media_list = QListWidget()
        self.media_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.media_list.setMaximumHeight(100)
        self.media_list.itemClicked.connect(self._on_media_item_clicked)
        media_list_box.addWidget(self.media_list)

        media_opts = QHBoxLayout()
        self.media_count_label = QLabel("0 media")
        self.media_count_label.setStyleSheet("color: #888; font-size: 11px;")
        self.shuffle_checkbox = QCheckBox("Xáo trộn")
        self.shuffle_checkbox.setChecked(True)
        self.avoid_repeat_checkbox = QCheckBox("Tránh trùng")
        self.avoid_repeat_checkbox.setChecked(True)
        self.shuffle_checkbox.stateChanged.connect(self._on_media_options_changed)
        self.avoid_repeat_checkbox.stateChanged.connect(self._on_media_options_changed)

        media_opts.addWidget(self.media_count_label)
        media_opts.addWidget(self.shuffle_checkbox)
        media_opts.addWidget(self.avoid_repeat_checkbox)
        media_list_box.addLayout(media_opts)

        media_btns = QHBoxLayout()
        self.add_media_btn = QPushButton("Thêm media")
        self.remove_media_btn = QPushButton("Xóa chọn")
        self.clear_media_btn = QPushButton("Xóa hết")
        self.add_media_btn.clicked.connect(self._choose_and_add_media)
        self.remove_media_btn.clicked.connect(lambda: self._remove_selected_items(self.media_list))
        self.clear_media_btn.clicked.connect(self._clear_media_list)

        media_btns.addWidget(self.add_media_btn)
        media_btns.addWidget(self.remove_media_btn)
        media_btns.addWidget(self.clear_media_btn)
        media_list_box.addLayout(media_btns)

        media_top_split.addLayout(media_list_box, 1)

        # Khung Preview Thumbnail Media
        preview_box = QVBoxLayout()
        self.media_preview_label = QLabel("Preview")
        self.media_preview_label.setFixedSize(130, 95)
        self.media_preview_label.setAlignment(Qt.AlignCenter)
        self.media_preview_label.setStyleSheet(
            "background-color: #1a1a24; border: 1px solid #333; border-radius: 4px; color: #666;"
        )
        preview_box.addWidget(self.media_preview_label)

        self.media_info_label = QLabel("Chưa chọn")
        self.media_info_label.setStyleSheet("color: #888; font-size: 10px;")
        self.media_info_label.setWordWrap(True)
        preview_box.addWidget(self.media_info_label)
        preview_box.addStretch(1)

        media_top_split.addLayout(preview_box)
        media_layout.addLayout(media_top_split)

        top_layout.addWidget(media_group, 4)
        root.addLayout(top_layout)

        # Lắng nghe thay đổi danh sách
        self.audio_list.model().rowsInserted.connect(self._on_audio_list_rows_changed)
        self.audio_list.model().rowsRemoved.connect(self._on_audio_list_rows_changed)
        self.media_list.model().rowsInserted.connect(self._on_media_list_rows_changed)
        self.media_list.model().rowsRemoved.connect(self._on_media_list_rows_changed)

        # ====================================================
        # 2. KHU VỰC DƯỚI: ĐIỀU KHIỂN & HÀNG ĐỢI RENDER (QUEUE)
        # ====================================================
        buttons = QHBoxLayout()
        self.run_btn = QPushButton("▶ Chạy render")
        self.run_btn.setStyleSheet("font-weight: bold; font-size: 13px; padding: 6px 16px; background-color: #2e7d32; color: white; border-radius: 4px;")
        self.stop_btn = QPushButton("⏹ Dừng")
        self.stop_btn.setStyleSheet("font-weight: bold; padding: 6px 14px;")
        self.project_btn = QPushButton("📁 Dự án")
        self.change_out_btn = QPushButton("📂 Đổi thư mục xuất")
        self.change_out_btn.clicked.connect(self._change_output_folder)

        self.chk_delete_audio_after_render = QCheckBox("🗑 Xóa file MP3 nguồn khi render xong")
        self.chk_delete_audio_after_render.setToolTip("Khi render video hoàn tất thành công, tự động xóa file MP3 audio nguồn để giải phóng dung lượng ổ đĩa.")
        self.chk_delete_audio_after_render.setStyleSheet("color: #ff9800; font-weight: bold; font-size: 11px;")
        self.chk_delete_audio_after_render.stateChanged.connect(self._on_render_options_changed)

        self.project_info_label = QLabel("Dự án: Chưa lưu")
        self.project_info_label.setStyleSheet("color: #2e7d32; font-weight: bold; font-size: 11px;")
        self.out_info_label = QLabel("")
        self.out_info_label.setStyleSheet("color: #777; font-size: 11px;")
        self.remove_btn = QPushButton("Xóa dòng trong queue")
        self.clear_btn = QPushButton("Xóa tất cả queue")

        self.run_btn.clicked.connect(self.start_render)
        self.stop_btn.clicked.connect(self.stop_render)
        self.project_btn.clicked.connect(self.project_requested.emit)
        self.remove_btn.clicked.connect(self.remove_selected)
        self.clear_btn.clicked.connect(self.clear_rows)

        buttons.addWidget(self.run_btn)
        buttons.addWidget(self.stop_btn)
        buttons.addWidget(self.project_btn)
        buttons.addWidget(self.change_out_btn)
        buttons.addWidget(self.project_info_label)
        buttons.addWidget(self.out_info_label)
        buttons.addSpacing(10)
        buttons.addWidget(self.chk_delete_audio_after_render)
        buttons.addSpacing(15)
        buttons.addWidget(self.remove_btn)
        buttons.addWidget(self.clear_btn)
        buttons.addStretch(1)
        root.addLayout(buttons)

        # Bảng Queue
        self.table = QTableWidget(0, 7)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setHorizontalHeaderLabels(["Audio", "Thời lượng", "Trạng thái", "Giai đoạn", "Tiến trình", "Thời gian chạy", "Video xuất"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(4, 90)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        root.addWidget(self.table, 2)

        # Khung Log Render
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(140)
        root.addWidget(self.log_box, 1)

    # ------------------ Audio Player (Nghe thử) ------------------

    def _on_audio_item_clicked(self, item) -> None:
        if not item:
            return
        fpath = item.text().strip()
        p = Path(fpath)
        if not p.exists():
            self.audio_track_label.setText(f"File không tồn tại: {p.name}")
            return
        self.audio_track_label.setText(f"🎵 {p.name}")
        self.player.setSource(QUrl.fromLocalFile(str(p)))
        self.play_btn.setText("▶ Phát")

    def _toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.play_btn.setText("▶ Tiếp tục")
        else:
            if not self.player.source().isValid() or self.player.source().isEmpty():
                # Tự chọn dòng đầu nếu có
                if self.audio_list.count() > 0:
                    self.audio_list.setCurrentRow(0)
                    self._on_audio_item_clicked(self.audio_list.currentItem())
                else:
                    return
            self.player.play()
            self.play_btn.setText("⏸ Tạm dừng")

    def _stop_playback(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())
        self.play_btn.setText("▶ Phát")
        self.audio_seek_slider.setValue(0)
        self.audio_time_label.setText("00:00 / 00:00")

    def _on_player_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setText("⏸ Tạm dừng")
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self.play_btn.setText("▶ Tiếp tục")
        else:
            self.play_btn.setText("▶ Phát")

    def _on_player_position_changed(self, position_ms: int) -> None:
        if not self._is_seeking and self.player.duration() > 0:
            val = int((position_ms / self.player.duration()) * 1000)
            self.audio_seek_slider.setValue(val)
        cur_sec = position_ms // 1000
        tot_sec = self.player.duration() // 1000
        self.audio_time_label.setText(f"{seconds_to_hhmmss(cur_sec)} / {seconds_to_hhmmss(tot_sec)}")

    def _on_player_duration_changed(self, duration_ms: int) -> None:
        tot_sec = duration_ms // 1000
        self.audio_time_label.setText(f"00:00 / {seconds_to_hhmmss(tot_sec)}")

    def _on_seek_slider_moved(self, value: int) -> None:
        self._is_seeking = True

    def _on_seek_slider_released(self) -> None:
        if self.player.duration() > 0:
            target_ms = int((self.audio_seek_slider.value() / 1000.0) * self.player.duration())
            self.player.setPosition(target_ms)
        self._is_seeking = False

    # ------------------ Media Preview ------------------

    def _on_media_item_clicked(self, item) -> None:
        if not item:
            return
        fpath = item.text().strip()
        p = Path(fpath)
        if not p.exists():
            self.media_preview_label.setText("Không tồn tại")
            self.media_info_label.setText("")
            return

        ext = p.suffix.lower()
        if is_image(p):
            pm = QPixmap(str(p))
            if not pm.isNull():
                scaled = pm.scaled(self.media_preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.media_preview_label.setPixmap(scaled)
                size_mb = p.stat().st_size / (1024 * 1024)
                self.media_info_label.setText(f"{pm.width()}x{pm.height()} | Ảnh {ext.upper()} | {size_mb:.1f}MB")
            else:
                self.media_preview_label.setText("Lỗi đọc ảnh")
        elif is_video(p):
            try:
                ffmpeg = self._ffmpeg_path()
                cmd = [ffmpeg, "-ss", "0.5", "-i", str(p), "-vframes", "1", "-f", "image2", "-c:v", "mjpeg", "pipe:1"]
                res = subprocess.run(cmd, capture_output=True)
                pm = QPixmap()
                if pm.loadFromData(res.stdout):
                    scaled = pm.scaled(self.media_preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self.media_preview_label.setPixmap(scaled)
                    dur = get_duration_seconds(p)
                    self.media_info_label.setText(f"{pm.width()}x{pm.height()} | Video | {seconds_to_hhmmss(dur)}")
                else:
                    self.media_preview_label.setText(f"Video\n{ext}")
                    self.media_info_label.setText(p.name[:20])
            except Exception:
                self.media_preview_label.setText(f"Video\n{ext}")
                self.media_info_label.setText(p.name[:20])

    # ------------------ Sắp xếp Audio ------------------

    def _sort_audio_natural(self) -> None:
        audios = [self.audio_list.item(i).text() for i in range(self.audio_list.count())]
        audios.sort(key=natural_sort_key)
        self._reload_audio_items(audios)

    def _sort_audio_az(self) -> None:
        audios = [self.audio_list.item(i).text() for i in range(self.audio_list.count())]
        audios.sort(key=lambda s: Path(s).name.lower())
        self._reload_audio_items(audios)

    def _sort_audio_za(self) -> None:
        audios = [self.audio_list.item(i).text() for i in range(self.audio_list.count())]
        audios.sort(key=lambda s: Path(s).name.lower(), reverse=True)
        self._reload_audio_items(audios)

    def _move_audio_up(self) -> None:
        row = self.audio_list.currentRow()
        if row > 0:
            item = self.audio_list.takeItem(row)
            self.audio_list.insertItem(row - 1, item)
            self.audio_list.setCurrentRow(row - 1)
            self._sync_audio_settings()

    def _move_audio_down(self) -> None:
        row = self.audio_list.currentRow()
        if 0 <= row < self.audio_list.count() - 1:
            item = self.audio_list.takeItem(row)
            self.audio_list.insertItem(row + 1, item)
            self.audio_list.setCurrentRow(row + 1)
            self._sync_audio_settings()

    def _reload_audio_items(self, audios: List[str]) -> None:
        self._lock_sync = True
        self.audio_list.clear()
        for a in audios:
            self.audio_list.addItem(a)
        self.audio_count_label.setText(f"Tổng: {len(audios)} audio")
        self._sync_audio_settings()
        self._lock_sync = False

    # ------------------ Xử lý File Audio & Media ------------------

    def _choose_and_add_audio(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(AUDIO_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn file audio", "", f"Audio ({exts})")
        if files:
            self.add_audio_files(files)

    def _choose_and_add_media(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTENSIONS | VIDEO_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn ảnh/video", "", f"Media ({exts})")
        if files:
            self._add_unique_to_list(self.media_list, files)
            self._sync_media_settings()
            if self.media_list.count() > 0 and not self.media_list.currentItem():
                self.media_list.setCurrentRow(0)
                self._on_media_item_clicked(self.media_list.currentItem())

    def _remove_selected_items(self, list_widget: QListWidget) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Đang render", "Không thể xóa file khi đang render.")
            return
        rows = sorted({list_widget.row(item) for item in list_widget.selectedItems()}, reverse=True)
        for row in rows:
            list_widget.takeItem(row)
        if list_widget is self.audio_list and list_widget.count() == 0:
            self._clear_audio_list()

    def _clear_audio_list(self) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Đang render", "Không thể xóa danh sách khi đang render.")
            return
        self.duration_loader.stop()
        self.audio_list.clear()
        self._stop_playback()
        self.audio_track_label.setText("Chưa chọn file audio")
        self.audio_time_label.setText("00:00 / 00:00")
        self.audio_seek_slider.setValue(0)
        self.audio_count_label.setText("Tổng: 0 audio")
        self.table.setRowCount(0)
        self._sync_audio_settings()

    def _clear_media_list(self) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Đang render", "Không thể xóa danh sách khi đang render.")
            return
        self.media_list.clear()
        self.media_preview_label.setText("Preview")
        self.media_info_label.setText("")

    @staticmethod
    def _add_unique_to_list(list_widget: QListWidget, files: List[str]) -> List[str]:
        existing = {list_widget.item(i).text() for i in range(list_widget.count())}
        added = []
        for f in files:
            f_clean = str(f).strip()
            if f_clean and f_clean not in existing:
                list_widget.addItem(f_clean)
                existing.add(f_clean)
                added.append(f_clean)
        return added

    @Slot(str)
    def add_audio_file(self, file_path: str) -> None:
        self.add_audio_files([file_path])

    @Slot(list)
    def add_audio_files(self, file_paths: List[str]) -> None:
        added = self._add_unique_to_list(self.audio_list, file_paths)
        if added:
            self._sync_audio_settings()

    def _on_audio_list_rows_changed(self) -> None:
        self.audio_count_label.setText(f"Tổng: {self.audio_list.count()} audio")
        if not self._lock_sync:
            self._sync_audio_settings()

    def _on_media_list_rows_changed(self) -> None:
        self.media_count_label.setText(f"{self.media_list.count()} media")
        if not self._lock_sync:
            self._sync_media_settings()

    def _on_media_options_changed(self) -> None:
        if not self._lock_sync:
            self._sync_media_settings()

    def _on_render_options_changed(self) -> None:
        if not self._lock_sync:
            self.settings["delete_audio_after_render"] = self.chk_delete_audio_after_render.isChecked()
            self.settings_changed.emit(self.settings)

    def _sync_audio_settings(self) -> None:
        audios = [self.audio_list.item(i).text() for i in range(self.audio_list.count())]
        self.settings["audio_files"] = audios
        self._populate_table_from_list(audios)
        self.settings_changed.emit(self.settings)

    def _sync_media_settings(self) -> None:
        medias = [self.media_list.item(i).text() for i in range(self.media_list.count())]
        self.settings["media_files"] = medias
        self.settings["shuffle_media"] = self.shuffle_checkbox.isChecked()
        self.settings["avoid_repeat"] = self.avoid_repeat_checkbox.isChecked()
        self.settings_changed.emit(self.settings)

    def _populate_table_from_list(self, audio_files: List[str]) -> None:
        if self.worker and self.worker.isRunning():
            return
        current = [str(self.table.item(r, 0).data(Qt.UserRole) or self.table.item(r, 0).text()) for r in range(self.table.rowCount()) if self.table.item(r, 0)]
        if current == audio_files:
            return
        self.table.setRowCount(0)
        self.row_start_times.clear()
        self.row_elapsed_final.clear()

        # Nạp hàng loạt ngay lập tức (không đơ máy)
        tasks: List[Tuple[int, str]] = []
        for row_idx, audio in enumerate(audio_files):
            self.add_audio_row_fast(row_idx, audio)
            tasks.append((row_idx, audio))

        # Đọc thời lượng ngầm
        if tasks:
            self.duration_loader.add_tasks(tasks)

    def add_audio_row_fast(self, row: int, audio: str) -> None:
        self.table.insertRow(row)
        name_item = QTableWidgetItem(Path(audio).name)
        name_item.setData(Qt.UserRole, audio)
        name_item.setToolTip(audio)
        self.table.setItem(row, 0, name_item)
        self.table.setItem(row, 1, QTableWidgetItem("Đang đọc..."))
        self.table.setItem(row, 2, QTableWidgetItem("Chưa chạy"))
        self.table.setItem(row, 3, QTableWidgetItem("Chờ"))
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(0)
        self.table.setCellWidget(row, 4, progress)
        self.table.setItem(row, 5, QTableWidgetItem("00:00"))
        ph_item = QTableWidgetItem("-")
        ph_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 6, ph_item)

    @Slot(int, str)
    def _on_duration_loaded(self, row: int, dur_str: str) -> None:
        if row < self.table.rowCount():
            self.table.setItem(row, 1, QTableWidgetItem(dur_str))

    # ------------------ Render Queue & Operations ------------------

    @Slot(dict)
    def update_settings(self, settings: Dict[str, Any]) -> None:
        self.settings.update(settings)
        self._update_project_labels()

    def _change_output_folder(self) -> None:
        current = self.settings.get("export", {}).get("output_folder", "") or self.settings.get("project", {}).get("output_folder", "")
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất video", current)
        if folder:
            self.settings.setdefault("export", {})["output_folder"] = folder
            self.settings.setdefault("project", {})["output_folder"] = folder
            self._update_project_labels()
            self.settings_changed.emit(self.settings)

    def _update_project_labels(self) -> None:
        p_name = self.settings.get("project", {}).get("current_name") or "Chưa lưu"
        self.project_info_label.setText(f"Dự án: {p_name}")
        out = self.settings.get("export", {}).get("output_folder") or "output"
        disp = out if len(out) <= 35 else f"...{out[-30:]}"
        self.out_info_label.setText(f"Xuất: {disp}")
        self.out_info_label.setToolTip(f"Thư mục xuất video: {out}")

    def load_settings(self, settings: Dict[str, Any]) -> None:
        self._lock_sync = True
        self.settings = settings
        self._update_project_labels()

        self.audio_list.clear()
        self.media_list.clear()

        audio_files = settings.get("audio_files", []) or []
        for a in audio_files:
            if a:
                self.audio_list.addItem(str(a))

        media_files = settings.get("media_files", []) or []
        for m in media_files:
            if m:
                self.media_list.addItem(str(m))

        self.shuffle_checkbox.setChecked(bool(settings.get("shuffle_media", True)))
        self.avoid_repeat_checkbox.setChecked(bool(settings.get("avoid_repeat", True)))
        self.chk_delete_audio_after_render.setChecked(bool(settings.get("delete_audio_after_render", False)))

        self.audio_count_label.setText(f"Tổng: {self.audio_list.count()} audio")
        self.media_count_label.setText(f"{self.media_list.count()} media")

        self._populate_table_from_list(audio_files)

        if self.media_list.count() > 0:
            self.media_list.setCurrentRow(0)
            self._on_media_item_clicked(self.media_list.currentItem())

        self._lock_sync = False

    def selected_rows(self) -> List[int]:
        return sorted({index.row() for index in self.table.selectedIndexes()})

    def start_render(self) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Đang render", "Tool đang render, hãy dừng hoặc đợi hoàn thành.")
            return

        self._stop_playback()

        media_files = [self.media_list.item(i).text() for i in range(self.media_list.count())]
        if not media_files:
            QMessageBox.warning(self, "Thiếu media", "Bạn chưa chọn ảnh/video nền trong danh sách Media.")
            return
        self.settings["media_files"] = media_files
        self.settings["delete_audio_after_render"] = self.chk_delete_audio_after_render.isChecked()

        rows = self.selected_rows() or list(range(self.table.rowCount()))
        audio_files = [str(self.table.item(row, 0).data(Qt.UserRole) or self.table.item(row, 0).text()) for row in rows]
        if not audio_files:
            QMessageBox.warning(self, "Thiếu audio", "Chưa có audio nào để render. Hãy thêm audio từ máy hoặc cào từ tab Cào MP3.")
            return

        for row in rows:
            self.update_row(row, "Chờ chạy", "Đợi trong queue", 0, "")
            self.row_elapsed_final.pop(row, None)
            self.table.setItem(row, 5, QTableWidgetItem("00:00"))
            ph_item = QTableWidgetItem("-")
            ph_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 6, ph_item)

        self.worker = RenderWorker(self.settings, rows, audio_files)
        self.worker.log_signal.connect(self.append_log)
        self.worker.row_update_signal.connect(self.update_row)
        self.worker.row_started_signal.connect(self.mark_row_started)
        self.worker.row_finished_signal.connect(self.mark_row_finished)
        self.worker.finished_signal.connect(self.render_finished)

        self.run_btn.setEnabled(False)
        self.project_btn.setEnabled(False)
        self.render_lock_changed.emit(True)
        self.timer.start(1000)
        self.worker.start()

    def stop_render(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.append_log("Đã yêu cầu dừng. Các tiến trình FFmpeg đang chạy sẽ được kết thúc an toàn.")

    @Slot()
    def render_finished(self) -> None:
        self.run_btn.setEnabled(True)
        self.project_btn.setEnabled(True)
        self.timer.stop()
        self.update_elapsed_times()
        self.render_lock_changed.emit(False)
        self.append_log("Queue render đã kết thúc.")

    @Slot(int)
    def mark_row_started(self, row: int) -> None:
        self.row_start_times[row] = time.time()

    @Slot(int)
    def mark_row_finished(self, row: int) -> None:
        start = self.row_start_times.pop(row, None)
        if start is not None:
            self.row_elapsed_final[row] = time.time() - start
        self.update_elapsed_times()

    def update_elapsed_times(self) -> None:
        now = time.time()
        for row in range(self.table.rowCount()):
            if row in self.row_start_times:
                elapsed = now - self.row_start_times[row]
            elif row in self.row_elapsed_final:
                elapsed = self.row_elapsed_final[row]
            else:
                elapsed = 0
            self.table.setItem(row, 5, QTableWidgetItem(seconds_to_hhmmss(elapsed)))

    @Slot(str)
    def append_log(self, message: str) -> None:
        t = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{t}] {message}")

    @Slot(int, str, str, int, str)
    def update_row(self, row: int, status: str, stage: str, percent: int, output: str = "") -> None:
        if row >= self.table.rowCount():
            return
        self.table.setItem(row, 2, QTableWidgetItem(status))
        self.table.setItem(row, 3, QTableWidgetItem(stage))
        bar = self.table.cellWidget(row, 4)
        if isinstance(bar, QProgressBar):
            bar.setValue(percent)
        if output:
            out_path = Path(output)
            cell_widget = QWidget()
            layout = QHBoxLayout(cell_widget)
            layout.setContentsMargins(4, 2, 4, 2)
            layout.setSpacing(4)

            btn_play = QPushButton("▶ Xem")
            btn_play.setStyleSheet(
                "font-weight: bold; background-color: #0288d1; color: white; padding: 2px 8px; border-radius: 3px;"
            )
            btn_play.setToolTip(f"Mở phát video: {out_path.name}")
            btn_play.clicked.connect(lambda _, p=str(out_path): self._open_video_file(p))

            btn_folder = QPushButton("📁")
            btn_folder.setStyleSheet("font-weight: bold; padding: 2px 6px; border-radius: 3px;")
            btn_folder.setToolTip(f"Mở thư mục chứa file: {out_path.parent}")
            btn_folder.clicked.connect(lambda _, p=str(out_path): self._open_video_folder(p))

            layout.addWidget(btn_play)
            layout.addWidget(btn_folder)
            self.table.setCellWidget(row, 6, cell_widget)

    def _open_video_file(self, path_str: str) -> None:
        p = Path(path_str)
        if p.exists():
            try:
                os.startfile(str(p))
            except Exception as exc:
                QMessageBox.warning(self, "Không mở được video", f"Lỗi: {exc}")
        else:
            QMessageBox.warning(self, "File không tồn tại", f"Không tìm thấy file: {path_str}")

    def _open_video_folder(self, path_str: str) -> None:
        p = Path(path_str)
        if p.exists():
            try:
                subprocess.Popen(f'explorer /select,"{p.resolve()}"')
            except Exception as exc:
                QMessageBox.warning(self, "Không mở được thư mục", f"Lỗi: {exc}")
        elif p.parent.exists():
            try:
                os.startfile(str(p.parent))
            except Exception as exc:
                QMessageBox.warning(self, "Không mở được thư mục", f"Lỗi: {exc}")
        else:
            QMessageBox.warning(self, "Thư mục không tồn tại", f"Không tìm thấy: {p.parent}")

    def remove_selected(self) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Đang render", "Không thể xóa dòng khi đang render.")
            return
        rows = self.selected_rows()
        for row in reversed(rows):
            self.table.removeRow(row)
            if row < self.audio_list.count():
                self.audio_list.takeItem(row)
        self.row_start_times.clear()
        self.row_elapsed_final.clear()
        self._sync_audio_settings()

    def clear_rows(self) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Đang render", "Không thể xóa danh sách khi đang render.")
            return
        self.table.setRowCount(0)
        self.audio_list.clear()
        self.row_start_times.clear()
        self.row_elapsed_final.clear()
        self._stop_playback()
        self._sync_audio_settings()
