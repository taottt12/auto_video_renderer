from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QMessageBox, QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QLineEdit, QLabel, QFileDialog
)

from core.settings import SettingsManager, PROJECTS_DIR
from .crawler_tab import CrawlerTab
from .setting_tab import SettingTab
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

        self.tabs = QTabWidget()
        self.crawler_tab = CrawlerTab(self.settings)
        self.setting_tab = SettingTab(self.settings)
        self.render_tab = RenderTab(self.settings)
        self.youtube_tab = YouTubeTab(self.settings)

        self.tabs.addTab(self.crawler_tab, "Cào MP3")
        self.tabs.addTab(self.setting_tab, "Setting")
        self.tabs.addTab(self.render_tab, "Render")
        self.tabs.addTab(self.youtube_tab, "Đăng YouTube")
        self.setCentralWidget(self.tabs)

        # Kết nối sự kiện giữa các tab
        self.crawler_tab.settings_changed.connect(self.on_settings_changed)
        self.crawler_tab.audio_downloaded.connect(self.render_tab.add_audio_file)
        self.crawler_tab.audio_batch_downloaded.connect(self.render_tab.add_audio_files)

        self.setting_tab.settings_changed.connect(self.on_settings_changed)
        self.render_tab.settings_changed.connect(self.on_settings_changed)
        self.youtube_tab.settings_changed.connect(self.on_settings_changed)

        self.render_tab.project_requested.connect(self.open_project_dialog)
        self.render_tab.render_lock_changed.connect(self.setting_tab.set_locked)
        self.render_tab.render_lock_changed.connect(lambda locked: self.crawler_tab.setEnabled(not locked))

    def on_settings_changed(self, settings: Dict[str, Any]) -> None:
        self.settings.update(settings)
        self.settings_manager.save(self.settings)
        self.render_tab.update_settings(self.settings)
        self.youtube_tab.load_settings(self.settings)

    def open_project_dialog(self) -> None:
        dlg = ProjectDialog(self, self.settings)
        if dlg.exec() != QDialog.Accepted or not dlg.selected_path:
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
                self.render_tab.update_settings(self.settings)
                self.youtube_tab.load_settings(self.settings)
                self.youtube_tab.refresh_projects()
                QMessageBox.information(self, "Đã lưu", f"Đã lưu dự án:\n{dlg.selected_path.name}")
            elif dlg.action == "open":
                self.settings = SettingsManager.load_project(dlg.selected_path)
                self.settings.setdefault("project", {})
                self.settings["project"]["current_name"] = dlg.selected_path.stem.replace(".avr", "")
                self.settings["project"]["current_path"] = str(dlg.selected_path)
                self.settings_manager.save(self.settings)
                self.crawler_tab.load_settings(self.settings)
                self.setting_tab.load_settings(self.settings)
                self.render_tab.load_settings(self.settings)
                self.youtube_tab.load_settings(self.settings)
                self.youtube_tab.refresh_projects()
                QMessageBox.information(self, "Đã mở", f"Đã mở dự án:\n{dlg.selected_path.name}")
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi", f"Không xử lý được dự án: {exc}")
