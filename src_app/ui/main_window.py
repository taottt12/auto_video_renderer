from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QMessageBox, QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QLineEdit, QLabel, QFileDialog, QWidget, QComboBox
)

from core.settings import SettingsManager, PROJECTS_DIR
from .crawler_tab import CrawlerTab
from .setting_tab import SettingTab
from .layout_tab import LayoutStudioTab
from .render_tab import RenderTab
from .youtube_tab import YouTubeTab


class ProjectDialog(QDialog):
    def __init__(self, parent: QMainWindow, settings: Dict[str, Any]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quản lý dự án")
        self.resize(560, 420)
        self.settings = settings
        self.selected_path: Path | None = None
        self.action: str = ""
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"Folder dự án mặc định: {PROJECTS_DIR}"))
        name_row = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Nhập tên dự án mới hoặc tên để ghi đè")
        current = self.settings.get("project", {}).get("current_name", "")
        if current:
            self.name_edit.setText(current)
        name_row.addWidget(QLabel("Tên dự án:"))
        name_row.addWidget(self.name_edit)
        root.addLayout(name_row)

        out_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        current_out = self.settings.get("export", {}).get("output_folder", "") or self.settings.get("project", {}).get("output_folder", "")
        self.output_edit.setText(current_out)
        self.output_edit.setPlaceholderText("Chọn thư mục lưu video render của dự án...")
        self.choose_output_btn = QPushButton("Chọn thư mục...")
        self.choose_output_btn.clicked.connect(self._choose_output_folder)
        out_row.addWidget(QLabel("Thư mục xuất video:"))
        out_row.addWidget(self.output_edit, 1)
        out_row.addWidget(self.choose_output_btn)
        root.addLayout(out_row)

        self.project_list = QListWidget()
        self.project_list.itemClicked.connect(self._on_item_clicked)
        root.addWidget(self.project_list)

        buttons = QHBoxLayout()
        self.save_btn = QPushButton("Lưu / Ghi đè")
        self.open_btn = QPushButton("Mở dự án đã chọn")
        self.delete_btn = QPushButton("Xóa dự án")
        self.import_btn = QPushButton("Mở từ file khác")
        self.close_btn = QPushButton("Đóng")
        for b in (self.save_btn, self.open_btn, self.delete_btn, self.import_btn, self.close_btn):
            buttons.addWidget(b)
        root.addLayout(buttons)

        self.save_btn.clicked.connect(self.save_action)
        self.open_btn.clicked.connect(self.open_action)
        self.delete_btn.clicked.connect(self.delete_action)
        self.import_btn.clicked.connect(self.import_action)
        self.close_btn.clicked.connect(self.reject)

    def _choose_output_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất video của dự án", self.output_edit.text().strip())
        if folder:
            self.output_edit.setText(folder)

    def _on_item_clicked(self, item) -> None:
        if not item:
            return
        p_path = PROJECTS_DIR / item.text()
        if p_path.exists():
            try:
                cfg = SettingsManager.load_project(p_path)
                p_name = cfg.get("project", {}).get("current_name", item.text().replace(".avr.json", "").replace(".json", ""))
                p_out = cfg.get("export", {}).get("output_folder") or cfg.get("project", {}).get("output_folder", "")
                self.name_edit.setText(p_name)
                if p_out:
                    self.output_edit.setText(p_out)
            except Exception:
                pass

    def refresh(self) -> None:
        self.project_list.clear()
        for path in SettingsManager.list_projects():
            self.project_list.addItem(path.name)

    def _current_project_path(self) -> Path | None:
        item = self.project_list.currentItem()
        if not item:
            return None
        return PROJECTS_DIR / item.text()

    def save_action(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Thiếu tên", "Hãy nhập tên dự án trước khi lưu.")
            return
        out_folder = self.output_edit.text().strip()
        if out_folder:
            self.settings.setdefault("export", {})["output_folder"] = out_folder
            self.settings.setdefault("project", {})["output_folder"] = out_folder
        self.settings.setdefault("project", {})["current_name"] = name
        self.selected_path = SettingsManager.project_path(name)
        self.settings["project"]["current_path"] = str(self.selected_path)
        SettingsManager.save_project(self.selected_path, self.settings)
        self.action = "save"
        self.accept()

    def open_action(self) -> None:
        path = self._current_project_path()
        if not path:
            QMessageBox.warning(self, "Chưa chọn", "Hãy chọn một dự án trong danh sách.")
            return
        self.selected_path = path
        self.action = "open"
        self.accept()

    def delete_action(self) -> None:
        path = self._current_project_path()
        if not path:
            QMessageBox.warning(self, "Chưa chọn", "Hãy chọn dự án cần xóa.")
            return
        if QMessageBox.question(self, "Xóa dự án", f"Xóa dự án này?\n{path.name}") == QMessageBox.Yes:
            path.unlink(missing_ok=True)
            self.refresh()

    def import_action(self) -> None:
        file, _ = QFileDialog.getOpenFileName(self, "Mở dự án từ file", "", "Auto Video Renderer Project (*.avr.json *.json)")
        if file:
            self.selected_path = Path(file)
            self.action = "open"
            self.accept()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Auto Video Renderer")
        self.resize(1280, 840)

        self.settings_manager = SettingsManager()
        self.settings: Dict[str, Any] = self.settings_manager.load()
        active_project = SettingsManager.resolve_current_project(self.settings)
        if active_project:
            self.settings = SettingsManager.load_project(
                active_project,
                self.settings,
                migrate_legacy_crawler=True,
            )
            SettingsManager.save_project(active_project, self.settings)
        # One-time/ongoing migration: keep only app-scoped values in config.json
        # and move credentials to the ignored local secrets store.
        self.settings_manager.save(self.settings)

        self.tabs = QTabWidget()
        self.crawler_tab = CrawlerTab(self.settings)
        self.setting_tab = SettingTab(self.settings)
        self.layout_tab = LayoutStudioTab(self.settings)
        self.render_tab = RenderTab(self.settings)
        self.youtube_tab = YouTubeTab(self.settings)

        self.tabs.addTab(self.crawler_tab, "Cào MP3")
        self.tabs.addTab(self.setting_tab, "Cấu hình dự án")
        self.tabs.addTab(self.layout_tab, "Studio Layout")
        self.tabs.addTab(self.render_tab, "Render")
        self.tabs.addTab(self.youtube_tab, "Đăng YouTube")
        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(8, 8, 8, 8)
        shell_layout.setSpacing(6)
        project_bar = QHBoxLayout()
        project_bar.addWidget(QLabel("<b>Dự án đang làm:</b>"))
        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(360)
        self.project_combo.currentIndexChanged.connect(self._on_project_combo_changed)
        project_bar.addWidget(self.project_combo, 1)
        self.new_project_btn = QPushButton("Tạo dự án mới")
        self.new_project_btn.clicked.connect(self.create_new_project)
        project_bar.addWidget(self.new_project_btn)
        self.manage_project_btn = QPushButton("Quản lý dự án")
        self.manage_project_btn.clicked.connect(self.open_project_dialog)
        project_bar.addWidget(self.manage_project_btn)
        self.project_save_state = QLabel("Đã lưu tự động")
        self.project_save_state.setStyleSheet("color: #2e7d32; font-weight: bold;")
        project_bar.addWidget(self.project_save_state)
        shell_layout.addLayout(project_bar)
        shell_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(shell)
        self._refresh_project_combo()

        # Kết nối sự kiện giữa các tab
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.crawler_tab.settings_changed.connect(self.on_settings_changed)
        self.crawler_tab.audio_downloaded.connect(self._on_crawler_audio_downloaded)
        self.crawler_tab.audio_batch_downloaded.connect(self._on_crawler_audio_batch_downloaded)

        self.setting_tab.settings_changed.connect(self.on_settings_changed)
        self.layout_tab.settings_changed.connect(self.on_settings_changed)
        self.render_tab.settings_changed.connect(self.on_settings_changed)
        self.youtube_tab.settings_changed.connect(self.on_settings_changed)

        self.render_tab.project_requested.connect(self.open_project_dialog)
        self.render_tab.render_lock_changed.connect(self.setting_tab.set_locked)
        self.render_tab.render_lock_changed.connect(lambda locked: self.layout_tab.setEnabled(not locked))
        self.render_tab.render_lock_changed.connect(lambda locked: self.crawler_tab.setEnabled(not locked))
        self._update_project_context_ui()

    def _refresh_project_combo(self) -> None:
        current_path = str((self.settings.get("project", {}) or {}).get("current_path", "") or "")
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItem("— Chưa chọn dự án —", "")
        for path in SettingsManager.list_projects():
            self.project_combo.addItem(path.stem.replace(".avr", ""), str(path))
        idx = self.project_combo.findData(current_path)
        self.project_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.project_combo.blockSignals(False)

    def _update_project_context_ui(self) -> None:
        project = self.settings.get("project", {}) or {}
        active = bool(project.get("current_path") and Path(str(project.get("current_path"))).exists())
        self.crawler_tab.set_project_context(
            str(project.get("current_name", "") or ""),
            str(project.get("current_path", "") or ""),
        )
        # Project-scoped editors stay disabled until their destination is
        # explicit. YouTube remains available because it can select a project
        # or an external output folder independently.
        self.tabs.setTabEnabled(1, active)
        self.tabs.setTabEnabled(2, active)
        self.tabs.setTabEnabled(3, active)

    def _load_project_path(self, path: Path, show_message: bool = False) -> None:
        global_settings = self.settings_manager.load()
        self.settings = SettingsManager.load_project(path, global_settings)
        self.settings.setdefault("project", {})["current_name"] = path.stem.replace(".avr", "")
        self.settings["project"]["current_path"] = str(path)
        SettingsManager.save_project(path, self.settings)
        self.settings_manager.save(self.settings)
        self.crawler_tab.load_settings(self.settings)
        self.setting_tab.load_settings(self.settings)
        self.layout_tab.update_settings(self.settings)
        self.render_tab.load_settings(self.settings)
        self.youtube_tab.load_settings(self.settings)
        self.youtube_tab.refresh_projects()
        self._refresh_project_combo()
        self._update_project_context_ui()
        if show_message:
            QMessageBox.information(self, "Đã mở", f"Đã mở dự án:\n{path.name}")

    def _on_project_combo_changed(self, _index: int) -> None:
        path_str = self.project_combo.currentData()
        if path_str:
            self._load_project_path(Path(path_str))
        elif (self.settings.get("project", {}) or {}).get("current_path"):
            self._refresh_project_combo()

    def _has_active_project(self) -> bool:
        path = str((self.settings.get("project", {}) or {}).get("current_path", "") or "")
        return bool(path and Path(path).exists())

    def _on_crawler_audio_downloaded(self, path: str) -> None:
        if self._has_active_project():
            self.render_tab.add_audio_file(path)

    def _on_crawler_audio_batch_downloaded(self, paths: list) -> None:
        if self._has_active_project():
            self.render_tab.add_audio_files(paths)
        elif paths:
            QMessageBox.warning(
                self,
                "Chưa chọn dự án",
                "MP3 đã tải xong nhưng chưa được thêm vào Render. Hãy chọn hoặc tạo dự án trước, rồi nạp MP3 vào dự án.",
            )

    def create_new_project(self) -> None:
        blank = self.settings_manager.load()
        blank["audio_files"] = []
        blank["media_files"] = []
        blank["render_queue"] = []
        blank["audio_crawler_project"] = {
            "initialized": True,
            "mode": "playlist",
            "video_urls": "",
            "playlist_url": "",
            "playlist_limit": 100,
            "channel_url": "",
            "channel_limit": 50,
            "channel_order": "newest_first",
            "channel_date_filter": "all",
            "channel_date_from": "",
            "channel_date_to": "",
            "save_folder": "",
            "auto_add_to_audio_list": True,
            "direct_crawl": True,
            "only_new": True,
            "audio_trim": {
                "enabled": False,
                "mode": "remove_segment",
                "start_time": "00:00:00",
                "end_time": "00:00:10",
            },
            "history": {},
        }
        blank["project"] = {"current_name": "", "current_path": ""}
        dlg = ProjectDialog(self, blank)
        dlg.name_edit.clear()
        dlg.setWindowTitle("Tạo dự án mới")
        if dlg.exec() != QDialog.Accepted or dlg.action != "save" or not dlg.selected_path:
            self._refresh_project_combo()
            return
        self.settings = blank
        self.settings.setdefault("project", {})["current_name"] = dlg.selected_path.stem.replace(".avr", "")
        self.settings["project"]["current_path"] = str(dlg.selected_path)
        out_folder = dlg.output_edit.text().strip()
        if out_folder:
            self.settings.setdefault("export", {})["output_folder"] = out_folder
            self.settings["project"]["output_folder"] = out_folder
        SettingsManager.save_project(dlg.selected_path, self.settings)
        self._load_project_path(dlg.selected_path)
        QMessageBox.information(self, "Đã tạo", f"Đã tạo dự án mới:\n{dlg.selected_path.name}")

    def _on_tab_changed(self, index: int) -> None:
        current_widget = self.tabs.widget(index)
        if current_widget == self.render_tab:
            self.render_tab.update_settings(self.settings)
        elif current_widget == self.layout_tab:
            self.layout_tab._reload_presets()
            self.layout_tab.update_settings(self.settings)

    def on_settings_changed(self, settings: Dict[str, Any]) -> None:
        self.settings.update(settings)
        self.settings_manager.save(self.settings)
        curr_p_path = self.settings.get("project", {}).get("current_path")
        if curr_p_path and Path(curr_p_path).exists():
            try:
                SettingsManager.save_project(Path(curr_p_path), self.settings)
            except Exception:
                pass

        self.setting_tab.settings = self.settings
        self.crawler_tab.settings = self.settings
        self.render_tab.update_settings(self.settings)
        if self.sender() != self.layout_tab:
            self.layout_tab.update_settings(self.settings)
        if self.sender() != self.setting_tab and hasattr(self.setting_tab, "output_edit"):
            out_folder = self.settings.get("project", {}).get("output_folder") or self.settings.get("export", {}).get("output_folder")
            if out_folder and self.setting_tab.output_edit.text() != out_folder:
                self.setting_tab.output_edit.blockSignals(True)
                self.setting_tab.output_edit.setText(out_folder)
                self.setting_tab.output_edit.blockSignals(False)
        if self.sender() != self.youtube_tab:
            self.youtube_tab.load_settings(self.settings)
        self._update_project_context_ui()

    def open_project_dialog(self) -> None:
        dlg = ProjectDialog(self, self.settings)
        if dlg.exec() != QDialog.Accepted or not dlg.selected_path:
            self._refresh_project_combo()
            self._update_project_context_ui()
            return
        try:
            if dlg.action == "save":
                self.settings.setdefault("project", {})
                self.settings["project"]["current_name"] = dlg.selected_path.stem.replace(".avr", "")
                self.settings["project"]["current_path"] = str(dlg.selected_path)
                out_folder = dlg.output_edit.text().strip()
                if out_folder:
                    self.settings.setdefault("export", {})["output_folder"] = out_folder
                    self.settings["project"]["output_folder"] = out_folder
                SettingsManager.save_project(dlg.selected_path, self.settings)
                self.settings_manager.save(self.settings)
                self.setting_tab.load_settings(self.settings)
                self.layout_tab.update_settings(self.settings)
                self.render_tab.update_settings(self.settings)
                self.youtube_tab.load_settings(self.settings)
                self.youtube_tab.refresh_projects()
                self._refresh_project_combo()
                self._update_project_context_ui()
                QMessageBox.information(self, "Đã lưu", f"Đã lưu dự án:\n{dlg.selected_path.name}")
            elif dlg.action == "open":
                self._load_project_path(dlg.selected_path, show_message=True)
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi", f"Không xử lý được dự án: {exc}")

    def closeEvent(self, event) -> None:
        try:
            if hasattr(self, "render_tab"):
                self.render_tab.cleanup()
        except Exception:
            pass
        super().closeEvent(event)
