from __future__ import annotations

import copy
import json
import math
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QRect, QRectF, QPoint, QPointF, Signal, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFont, QFontMetrics,
    QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QMovie, QImage
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QPushButton,
    QListWidget, QListWidgetItem, QFileDialog, QInputDialog, QCheckBox, QComboBox,
    QSpinBox, QDoubleSpinBox, QLineEdit, QFormLayout, QScrollArea,
    QTextEdit, QPlainTextEdit, QFontComboBox, QMenu, QColorDialog, QToolButton, QLabel, QSplitter, QMessageBox,
    QSlider, QFrame
)

from ..core.paths import LAYOUTS_DIR, PRESETS_DIR
from ..core.layout_renderer import LayoutRenderer
LAYOUT_PRESETS_DIR = LAYOUTS_DIR

TEXT_MOTIONS: Tuple[Tuple[str, str], ...] = (
    ("Tĩnh (Không chuyển động)", "none"),
    ("🦘 Nhảy từng từ (Word Bounce)", "word_bounce"),
    ("💃 Nhảy từng chữ TikTok (Letter Bounce)", "letter_bounce"),
    ("🔄 Nghiêng chữ xen kẽ (Rotate Letters)", "rotate_letters"),
    ("🎤 Karaoke / Sáng từng từ (Karaoke Bounce)", "karaoke_bounce"),
    ("〰️ Lượn sóng từng chữ (Wave)", "wave"),
    ("🪐 Xoay tròn từng chữ (Orbit Letters)", "orbit_letters"),
    ("🚩 Vẫy cờ nhịp nhàng (Flag Wave)", "flag_wave"),
    ("💓 Đập thình thịch (Heartbeat)", "heartbeat"),
    ("🔥 Nhịp thở viền sáng (Glow Pulse)", "glow_pulse"),
    ("🌈 Viền đổi màu cầu vồng (Rainbow Border)", "rainbow_border"),
)

IMAGE_MOTIONS: Tuple[Tuple[str, str], ...] = (
    ("Tĩnh (Không chuyển động)", "none"),
    ("🌊 Bồng bềnh nhẹ (Floating 5px)", "float"),
    ("💓 Co giãn nhịp thở (Pulse)", "pulse"),
    ("🕰️ Đu đưa con lắc (Pendulum Swing)", "pendulum"),
    ("💥 Giật nhịp nhạc (Shake On Beat)", "shake_beat"),
    ("📳 Rung nhẹ chống mỏi mắt (Earthquake 1-2px)", "earthquake_gentle"),
)


class LayoutCanvasWidget(QWidget):
    """Màn hình Canvas tương tác trực quan cho phép kéo thả, di chuyển và co giãn các Layer."""

    layer_selected = Signal(int)
    layer_changed = Signal(int, dict)

    HANDLE_SIZE = 8

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 320)
        self.setMouseTracking(True)

        self.ratio_w: float = 16.0
        self.ratio_h: float = 9.0

        self.layers: List[Dict[str, Any]] = []
        self.selected_idx: int = -1
        self.preview_title: str = "NALAKA A PAGKWARTAAN"

        self.pixmap_cache: Dict[str, QPixmap] = {}
        self.movie_cache: Dict[str, QMovie] = {}

        # Render cache & dirty tracking
        self._cached_pixmap: Optional[QPixmap] = None
        self._dirty: bool = True

        # Drag state
        self._drag_mode: Optional[str] = None  # 'move', 'nw', 'ne', 'sw', 'se', 'n', 's', 'w', 'e'
        self._drag_start_pos = QPoint()
        self._drag_start_box: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        self._canvas_rect = QRect()

        # Animation timer for live badges & GIF preview (only runs when needed)
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._on_anim_tick)
        self._anim_t: float = 0.0

    def mark_dirty(self) -> None:
        self._dirty = True
        self.update()

    def _has_animated_layers(self) -> bool:
        for l in self.layers:
            if not l.get("enabled", True):
                continue
            l_type = str(l.get("type", "")).lower()
            fp = str(l.get("file_path", "")).lower()
            if l_type in {"gif", "reaction"} or fp.endswith(".gif"):
                return True
            in_eff = str(l.get("in_effect", "none")).lower()
            out_eff = str(l.get("out_effect", "none")).lower()
            mot_eff = str(l.get("motion_effect", "none")).lower()
            if in_eff != "none" or out_eff != "none" or (mot_eff != "none" and mot_eff != "static"):
                return True
        return False

    def _on_anim_tick(self) -> None:
        if not self._has_animated_layers():
            self._anim_timer.stop()
            return
        self._anim_t += 0.04
        self.mark_dirty()

    def set_aspect_ratio(self, width: int = 1920, height: int = 1080) -> None:
        if width > 0 and height > 0:
            self.ratio_w = float(width)
            self.ratio_h = float(height)
        else:
            self.ratio_w, self.ratio_h = 16.0, 9.0
        self.mark_dirty()

    def set_layers(self, layers: List[Dict[str, Any]], selected_idx: int = -1) -> None:
        self.layers = layers
        self.selected_idx = selected_idx
        # Preload pixmaps & movies
        for l in self.layers:
            fp = str(l.get("file_path", "")).strip()
            l_type = str(l.get("type", "")).lower()
            if fp and os.path.exists(fp):
                if l_type in {"gif", "reaction"} or fp.lower().endswith(".gif"):
                    if fp not in self.movie_cache:
                        movie = QMovie(fp)
                        movie.frameChanged.connect(lambda _: self.mark_dirty())
                        movie.start()
                        self.movie_cache[fp] = movie
                elif fp not in self.pixmap_cache:
                    self.pixmap_cache[fp] = QPixmap(fp)

        if self._has_animated_layers():
            if not self._anim_timer.isActive():
                self._anim_timer.start(40)
        else:
            if self._anim_timer.isActive():
                self._anim_timer.stop()

        self.mark_dirty()

    def _get_pixmap(self, file_path: str, is_gif: bool = False) -> Optional[QPixmap]:
        if not file_path:
            return None
        if is_gif or file_path.lower().endswith(".gif"):
            if file_path not in self.movie_cache and os.path.exists(file_path):
                movie = QMovie(file_path)
                movie.frameChanged.connect(lambda _: self.update())
                movie.start()
                self.movie_cache[file_path] = movie
            movie = self.movie_cache.get(file_path)
            if movie and movie.isValid():
                cur_pix = movie.currentPixmap()
                if cur_pix and not cur_pix.isNull():
                    return cur_pix
        if file_path not in self.pixmap_cache:
            if os.path.exists(file_path):
                self.pixmap_cache[file_path] = QPixmap(file_path)
            else:
                return None
        pm = self.pixmap_cache.get(file_path)
        return pm if (pm and not pm.isNull()) else None

    def _compute_canvas_rect(self) -> QRect:
        avail_w = max(10, self.width() - 32)
        avail_h = max(10, self.height() - 32)
        scale = min(avail_w / self.ratio_w, avail_h / self.ratio_h)
        cw = max(100, int(self.ratio_w * scale))
        ch = max(100, int(self.ratio_h * scale))
        cx = (self.width() - cw) // 2
        cy = (self.height() - ch) // 2
        return QRect(cx, cy, cw, ch)

    def _norm_to_canvas(self, bx: float, by: float, bw: float, bh: float) -> QRect:
        cr = self._canvas_rect
        px = cr.x() + int(bx * cr.width())
        py = cr.y() + int(by * cr.height())
        pw = max(4, int(bw * cr.width()))
        ph = max(4, int(bh * cr.height()))
        return QRect(px, py, pw, ph)

    def _canvas_to_norm(self, rx: int, ry: int, rw: int, rh: int) -> Tuple[float, float, float, float]:
        cr = self._canvas_rect
        if cr.width() <= 0 or cr.height() <= 0:
            return 0.0, 0.0, 0.2, 0.2
        bx = max(-1.0, min(1.5, (rx - cr.x()) / cr.width()))
        by = max(-1.0, min(1.5, (ry - cr.y()) / cr.height()))
        bw = max(0.01, min(2.0, rw / cr.width()))
        bh = max(0.01, min(2.0, rh / cr.height()))
        return round(bx, 4), round(by, 4), round(bw, 4), round(bh, 4)

    def _get_handles(self, rect: QRect) -> Dict[str, QRect]:
        hs = self.HANDLE_SIZE
        hs2 = hs // 2
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        return {
            "nw": QRect(x - hs2, y - hs2, hs, hs),
            "n": QRect(x + w // 2 - hs2, y - hs2, hs, hs),
            "ne": QRect(x + w - hs2, y - hs2, hs, hs),
            "e": QRect(x + w - hs2, y + h // 2 - hs2, hs, hs),
            "se": QRect(x + w - hs2, y + h - hs2, hs, hs),
            "s": QRect(x + w // 2 - hs2, y + h - hs2, hs, hs),
            "sw": QRect(x - hs2, y + h - hs2, hs, hs),
            "w": QRect(x - hs2, y + h // 2 - hs2, hs, hs),
        }

    def _get_hit_handle(self, pos: QPoint, rect: QRect) -> Optional[str]:
        handles = self._get_handles(rect)
        for name, h_rect in handles.items():
            if h_rect.contains(pos):
                return name
        return None

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        self._canvas_rect = self._compute_canvas_rect()
        cr = self._canvas_rect

        # 1. Vẽ nền Canvas (mô phỏng màn hình video)
        painter.fillRect(self.rect(), QColor("#121218"))
        painter.fillRect(cr, QColor("#1e1e28"))

        # 2. Render Canvas thông qua LayoutRenderer (Single Source of Truth - Chuẩn xác 100% WYSIWYG)
        if self._dirty or self._cached_pixmap is None:
            try:
                canvas_pil, _ = LayoutRenderer.render_canvas(
                    self.layers,
                    width=1920,
                    height=1080,
                    audio_title=self.preview_title,
                    preview_mode=True,
                    anim_t=self._anim_t
                )
                if canvas_pil:
                    data = canvas_pil.tobytes("raw", "RGBA")
                    qimg = QImage(data, 1920, 1080, QImage.Format_RGBA8888)
                    self._cached_pixmap = QPixmap.fromImage(qimg)
                    self._dirty = False
            except Exception as e:
                self._cached_pixmap = None
                self._dirty = False
                painter.setPen(QColor("#ff5555"))
                painter.drawText(cr, Qt.AlignCenter, f"Lỗi hiển thị Preview: {e}")

        if self._cached_pixmap and not self._cached_pixmap.isNull():
            painter.drawPixmap(cr, self._cached_pixmap)

        # 3. Đường lưới trung tâm snap
        painter.setPen(QPen(QColor(255, 255, 255, 30), 1, Qt.DashLine))
        painter.drawLine(cr.x() + cr.width() // 2, cr.y(), cr.x() + cr.width() // 2, cr.y() + cr.height())
        painter.drawLine(cr.x(), cr.y() + cr.height() // 2, cr.x() + cr.width(), cr.y() + cr.height() // 2)

        # Viền canvas
        painter.setPen(QPen(QColor("#4f526b"), 2))
        painter.drawRect(cr)

        # 3. Vẽ Khung Bounding Box cho Layer đang được chọn (Vẽ ngoài clip để luôn nhìn thấy và nắm kéo được)
        if 0 <= self.selected_idx < len(self.layers):
            s_layer = self.layers[self.selected_idx]
            bx = float(s_layer.get("box_x", 0.0))
            by = float(s_layer.get("box_y", 0.0))
            bw = float(s_layer.get("box_w", 0.3))
            bh = float(s_layer.get("box_h", 0.2))
            s_rect = self._norm_to_canvas(bx, by, bw, bh)

            # Khung viền chọn
            painter.setPen(QPen(QColor("#00ffcc"), 2, Qt.SolidLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(s_rect)

            # 8 nút handles
            handles = self._get_handles(s_rect)
            painter.setBrush(QBrush(QColor("#00ffcc")))
            painter.setPen(QPen(QColor("#000000"), 1))
            for h_rect in handles.values():
                painter.drawRect(h_rect)

            # Nhãn tên Layer
            name = re.sub(r"[\U00010000-\U0010ffff]", "", str(s_layer.get("name", "Layer"))).strip() or "Layer"
            font = QFont("Segoe UI", 8, QFont.Bold)
            fm = QFontMetrics(font)
            text_w = fm.horizontalAdvance(name)
            tag_rect = QRect(s_rect.x(), max(cr.y(), s_rect.y() - 20), max(60, text_w + 14), 18)
            painter.fillRect(tag_rect, QColor(0, 255, 204, 220))
            painter.setPen(QPen(QColor("#000000")))
            painter.setFont(font)
            painter.drawText(tag_rect, Qt.AlignCenter, name)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return

        pos = event.pos()

        # 1. Kiểm tra bấm vào handle của layer đang chọn
        if 0 <= self.selected_idx < len(self.layers):
            s_layer = self.layers[self.selected_idx]
            if not s_layer.get("locked", False):
                bx = float(s_layer.get("box_x", 0.0))
                by = float(s_layer.get("box_y", 0.0))
                bw = float(s_layer.get("box_w", 0.3))
                bh = float(s_layer.get("box_h", 0.2))
                s_rect = self._norm_to_canvas(bx, by, bw, bh)
                handle = self._get_hit_handle(pos, s_rect)
                if handle:
                    self._drag_mode = handle
                    self._drag_start_pos = pos
                    self._drag_start_box = (bx, by, bw, bh)
                    return
                if s_rect.contains(pos):
                    self._drag_mode = "move"
                    self._drag_start_pos = pos
                    self._drag_start_box = (bx, by, bw, bh)
                    return

        # 2. Tìm layer dưới con trỏ (theo thứ tự từ trên xuống dưới Z-Index)
        clicked_idx = -1
        for idx in reversed(range(len(self.layers))):
            layer = self.layers[idx]
            if not layer.get("enabled", True):
                continue
            bx = float(layer.get("box_x", 0.0))
            by = float(layer.get("box_y", 0.0))
            bw = float(layer.get("box_w", 0.3))
            bh = float(layer.get("box_h", 0.2))
            l_rect = self._norm_to_canvas(bx, by, bw, bh)
            if l_rect.contains(pos):
                clicked_idx = idx
                break

        if clicked_idx != -1:
            self.selected_idx = clicked_idx
            self.layer_selected.emit(self.selected_idx)
            layer = self.layers[self.selected_idx]
            if not layer.get("locked", False):
                bx = float(layer.get("box_x", 0.0))
                by = float(layer.get("box_y", 0.0))
                bw = float(layer.get("box_w", 0.3))
                bh = float(layer.get("box_h", 0.2))
                self._drag_mode = "move"
                self._drag_start_pos = pos
                self._drag_start_box = (bx, by, bw, bh)
        else:
            self.selected_idx = -1
            self.layer_selected.emit(-1)

        self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.pos()
        cr = self._canvas_rect

        if self._drag_mode and 0 <= self.selected_idx < len(self.layers):
            sbx, sby, sbw, sbh = self._drag_start_box
            dx_norm = (pos.x() - self._drag_start_pos.x()) / max(1, cr.width())
            dy_norm = (pos.y() - self._drag_start_pos.y()) / max(1, cr.height())

            cur_layer = self.layers[self.selected_idx]

            if self._drag_mode == "move":
                nbx = max(-1.0, min(1.5, sbx + dx_norm))
                nby = max(-1.0, min(1.5, sby + dy_norm))
                cur_layer["box_x"] = round(nbx, 4)
                cur_layer["box_y"] = round(nby, 4)
            else:
                # Resize handles
                nbx, nby, nbw, nbh = sbx, sby, sbw, sbh
                if "w" in self._drag_mode:
                    nbx = max(-1.0, min(sbx + sbw - 0.01, sbx + dx_norm))
                    nbw = max(0.01, min(2.0, sbw + (sbx - nbx)))
                if "e" in self._drag_mode:
                    nbw = max(0.01, min(2.0, sbw + dx_norm))
                if "n" in self._drag_mode:
                    nby = max(-1.0, min(sby + sbh - 0.01, sby + dy_norm))
                    nbh = max(0.01, min(2.0, sbh + (sby - nby)))
                if "s" in self._drag_mode:
                    nbh = max(0.01, min(2.0, sbh + dy_norm))

                cur_layer["box_x"] = round(nbx, 4)
                cur_layer["box_y"] = round(nby, 4)
                cur_layer["box_w"] = round(nbw, 4)
                cur_layer["box_h"] = round(nbh, 4)

            self.layer_changed.emit(self.selected_idx, cur_layer)
            self.mark_dirty()
            return

        # Cập nhật con trỏ chuột khi hover
        if 0 <= self.selected_idx < len(self.layers):
            s_layer = self.layers[self.selected_idx]
            bx = float(s_layer.get("box_x", 0.0))
            by = float(s_layer.get("box_y", 0.0))
            bw = float(s_layer.get("box_w", 0.3))
            bh = float(s_layer.get("box_h", 0.2))
            s_rect = self._norm_to_canvas(bx, by, bw, bh)
            handle = self._get_hit_handle(pos, s_rect)
            cursor_map = {
                "nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
                "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor,
                "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
                "w": Qt.SizeHorCursor, "e": Qt.SizeHorCursor,
            }
            if handle in cursor_map:
                self.setCursor(cursor_map[handle])
                return
            if s_rect.contains(pos):
                self.setCursor(Qt.SizeAllCursor)
                return

        self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_mode = None
        self.update()


class LayoutStudioTab(QWidget):
    """Tab Studio Layout & Hiệu ứng Đa tầng."""

    settings_changed = Signal(dict)

    PRESET_TEMPLATES = {
        "default": {
            "name": "📌 Mẫu Mặc Định (Đang chỉnh sửa)",
            "layers": []
        },
        "livestream_drama": {
            "name": "📻 Mẫu Livestream Radio Drama (Chuẩn ảnh mẫu)",
            "layers": [
                {
                    "id": "live_badge",
                    "name": "🔴 Huy hiệu Live (Top Left)",
                    "type": "live_badge",
                    "file_path": "",
                    "enabled": True,
                    "locked": False,
                    "box_x": 0.03, "box_y": 0.03, "box_w": 0.16, "box_h": 0.06,
                    "opacity": 1.0, "blend_mode": "alpha"
                },
                {
                    "id": "channel_avatar",
                    "name": "🎙️ Avatar Tròn Kênh (Top Left)",
                    "type": "image",
                    "file_path": "",
                    "enabled": True,
                    "locked": False,
                    "box_x": 0.03, "box_y": 0.10, "box_w": 0.09, "box_h": 0.16,
                    "opacity": 1.0, "blend_mode": "alpha"
                },
                {
                    "id": "channel_logo",
                    "name": "🏷️ Logo Kênh Radio (Top Right)",
                    "type": "image",
                    "file_path": "",
                    "enabled": True,
                    "locked": False,
                    "box_x": 0.70, "box_y": 0.03, "box_w": 0.27, "box_h": 0.14,
                    "opacity": 1.0, "blend_mode": "alpha"
                },
                {
                    "id": "story_title",
                    "name": "📖 Khung Tiêu Đề Tập Truyện (Top Center)",
                    "type": "text",
                    "text_content": "Tập Truyện Kể Đêm Khuya Hay Nhất",
                    "file_path": "",
                    "enabled": True,
                    "locked": False,
                    "box_x": 0.18, "box_y": 0.18, "box_w": 0.64, "box_h": 0.14,
                    "opacity": 1.0, "blend_mode": "alpha",
                    "font_size": 26, "font_color": "#FFCC00", "outline_color": "#880088",
                    "bg_box_enabled": True, "bg_box_color": "#220033", "bg_box_opacity": 0.75
                },
                {
                    "id": "floating_hearts",
                    "name": "💖 Hiệu ứng Tim Bay (Center Right)",
                    "type": "gif",
                    "file_path": "",
                    "enabled": True,
                    "locked": False,
                    "box_x": 0.82, "box_y": 0.40, "box_w": 0.15, "box_h": 0.35,
                    "opacity": 0.9, "blend_mode": "alpha"
                },
                {
                    "id": "footer_banner",
                    "name": "❄️ Banner Dưới (Lower Third)",
                    "type": "image",
                    "file_path": "",
                    "enabled": True,
                    "locked": False,
                    "box_x": 0.0, "box_y": 0.82, "box_w": 1.0, "box_h": 0.18,
                    "opacity": 1.0, "blend_mode": "alpha"
                }
            ]
        },
        "podcast_night": {
            "name": "🎙️ Mẫu Podcast / Kể Chuyện Đêm Khuya",
            "layers": [
                {
                    "id": "watermark",
                    "name": "💧 Watermark Bản Quyền Kênh",
                    "type": "image",
                    "file_path": "",
                    "enabled": True,
                    "locked": False,
                    "box_x": 0.0, "box_y": 0.0, "box_w": 1.0, "box_h": 1.0,
                    "opacity": 0.20, "blend_mode": "alpha"
                },
                {
                    "id": "logo",
                    "name": "🏷️ Logo Kênh (Góc trên phải)",
                    "type": "image",
                    "file_path": "",
                    "enabled": True,
                    "locked": False,
                    "box_x": 0.82, "box_y": 0.04, "box_w": 0.14, "box_h": 0.14,
                    "opacity": 1.0, "blend_mode": "alpha"
                }
            ]
        },
        "custom": {
            "name": "🎨 Mẫu Trống (Tự Thiết Kế)",
            "layers": []
        }
    }

    def __init__(self, settings: Dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._updating = False
        self._init_data()
        self._build_ui()
        self._sync_to_ui()

    def _init_data(self) -> None:
        if "layout_studio" not in self.settings:
            self.settings["layout_studio"] = {
                "enabled": True,
                "selected_preset": "default",
                "layers": [],
                "custom_presets": {}
            }
        # Migration: nếu layers trống nhưng config có logo hoặc watermark thì tạo layer mặc định
        layers = self.settings["layout_studio"].get("layers", [])
        if not layers:
            wm_file = str(self.settings.get("watermark_file", "")).strip()
            if self.settings.get("watermark_enabled") and wm_file:
                layers.append({
                    "id": "wm_" + uuid.uuid4().hex[:6],
                    "name": "💧 Watermark Kênh",
                    "type": "watermark",
                    "file_path": wm_file,
                    "enabled": True,
                    "locked": False,
                    "box_x": 0.0, "box_y": 0.0, "box_w": 1.0, "box_h": 1.0,
                    "opacity": float(self.settings.get("watermark_opacity", 0.2)),
                    "blend_mode": "alpha"
                })
            lg_file = str(self.settings.get("logo_file", "")).strip()
            if self.settings.get("logo_enabled") and lg_file:
                layers.append({
                    "id": "lg_" + uuid.uuid4().hex[:6],
                    "name": "🏷️ Logo Kênh",
                    "type": "logo",
                    "file_path": lg_file,
                    "enabled": True,
                    "locked": False,
                    "box_x": 0.82, "box_y": 0.04, "box_w": 0.14, "box_h": 0.14,
                    "opacity": 1.0,
                    "blend_mode": "alpha"
                })
            self.settings["layout_studio"]["layers"] = layers

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        splitter = QSplitter(Qt.Horizontal)

        # ==========================================
        # CỘT TRÁI: LIVE CANVAS & TOOLBAR
        # ==========================================
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # Top Toolbar: Preset selector + Ratio selector
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("<b>Mẫu Bố Cục (Preset):</b>"))
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(220)
        self._reload_presets()
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        top_bar.addWidget(self.preset_combo, 1)

        self.apply_preset_btn = QPushButton("Áp Dụng Mẫu")
        self.apply_preset_btn.clicked.connect(self._apply_current_preset)
        top_bar.addWidget(self.apply_preset_btn)

        self.save_preset_btn = QPushButton("💾 Lưu Mẫu")
        self.save_preset_btn.setToolTip("Lưu/ghi đè các thay đổi vào mẫu đang chọn")
        self.save_preset_btn.clicked.connect(self._quick_save_preset)
        top_bar.addWidget(self.save_preset_btn)

        self.save_as_preset_btn = QPushButton("➕ Lưu Mẫu Mới")
        self.save_as_preset_btn.setToolTip("Lưu bố cục hiện tại thành mẫu mới vào presets/layouts/")
        self.save_as_preset_btn.clicked.connect(self._save_custom_preset)
        top_bar.addWidget(self.save_as_preset_btn)

        self.delete_preset_btn = QPushButton("🗑 Xóa Mẫu")
        self.delete_preset_btn.setToolTip("Xóa mẫu bố cục tùy chỉnh đã lưu")
        self.delete_preset_btn.clicked.connect(self._delete_custom_preset)
        top_bar.addWidget(self.delete_preset_btn)

        left_layout.addLayout(top_bar)

        # Preview Title Bar: Nhập tiêu đề mẫu xem trước chuẩn xác
        preview_title_bar = QHBoxLayout()
        preview_title_bar.addWidget(QLabel("<b>📝 Tiêu Đề Mẫu:</b>"))
        self.preview_title_edit = QLineEdit()
        self.preview_title_edit.setPlaceholderText("Nhập tiêu đề mẫu để xem trước bẻ dòng và cỡ chữ thực tế...")
        self.preview_title_edit.setText("NALAKA A PAGKWARTAAN")
        self.preview_title_edit.textChanged.connect(self._on_preview_title_changed)
        preview_title_bar.addWidget(self.preview_title_edit, 1)

        self.btn_sample_long = QPushButton("📜 Mẫu Dài")
        self.btn_sample_long.setToolTip("Xem thử với tiêu đề dài 2 dòng")
        self.btn_sample_long.clicked.connect(lambda: self.preview_title_edit.setText("NALAKA A PAGKWARTAAN"))
        preview_title_bar.addWidget(self.btn_sample_long)

        self.btn_sample_short = QPushButton("🔤 Mẫu Ngắn")
        self.btn_sample_short.setToolTip("Xem thử với tiêu đề ngắn 1 dòng")
        self.btn_sample_short.clicked.connect(lambda: self.preview_title_edit.setText("TẬP 1: MỞ ĐẦU"))
        preview_title_bar.addWidget(self.btn_sample_short)

        left_layout.addLayout(preview_title_bar)

        # Canvas tương tác kéo thả
        self.canvas = LayoutCanvasWidget()
        self.canvas.layer_selected.connect(self._on_canvas_layer_selected)
        self.canvas.layer_changed.connect(self._on_canvas_layer_changed)
        left_layout.addWidget(self.canvas, 1)

        # Bottom Canvas Toolbar
        bot_bar = QHBoxLayout()
        self.ratio_label = QLabel("Tỉ lệ: 16:9 (1920x1080)")
        bot_bar.addWidget(self.ratio_label)
        bot_bar.addStretch()
        self.hint_label = QLabel("💡 <i>Click vào phần tử trên Canvas để kéo thả di chuyển hoặc kéo 8 nút góc để co giãn kích thước.</i>")
        bot_bar.addWidget(self.hint_label)
        left_layout.addLayout(bot_bar)

        splitter.addWidget(left_widget)

        # ==========================================
        # CỘT PHẢI: QUẢN LÝ LAYER (LAYER MANAGER & INSPECTOR)
        # ==========================================
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # Group 1: Danh sách Layers
        layer_group = QGroupBox("Danh Sách Lớp (Layer Stack - Z-Index)")
        lg_layout = QVBoxLayout(layer_group)

        # Nút thêm các loại layer
        add_btn_row = QHBoxLayout()
        self.add_img_btn = QPushButton("➕ Ảnh (PNG/JPG)")
        self.add_gif_btn = QPushButton("➕ GIF Động")
        self.add_mask_btn = QPushButton("➕ Video Mask")
        self.add_text_btn = QPushButton("➕ Tiêu Đề Text")
        self.add_sub_btn = QPushButton("➕ Khung Phụ Đề (Sub)")
        self.add_live_btn = QPushButton("➕ Huy Hiệu LIVE")

        self.add_img_btn.clicked.connect(lambda: self._add_layer("image"))
        self.add_gif_btn.clicked.connect(lambda: self._add_layer("gif"))
        self.add_mask_btn.clicked.connect(lambda: self._add_layer("video_mask"))
        self.add_text_btn.clicked.connect(lambda: self._add_layer("text"))
        self.add_sub_btn.clicked.connect(lambda: self._add_layer("subtitle"))
        self.add_live_btn.clicked.connect(lambda: self._add_layer("live_badge"))

        add_btn_row.addWidget(self.add_img_btn)
        add_btn_row.addWidget(self.add_gif_btn)
        add_btn_row.addWidget(self.add_mask_btn)
        add_btn_row.addWidget(self.add_text_btn)
        add_btn_row.addWidget(self.add_sub_btn)
        add_btn_row.addWidget(self.add_live_btn)
        lg_layout.addLayout(add_btn_row)

        self.layer_list = QListWidget()
        self.layer_list.currentRowChanged.connect(self._on_layer_row_changed)
        lg_layout.addWidget(self.layer_list, 1)

        # Nút điều khiển danh sách layer
        ctrl_btn_row = QHBoxLayout()
        self.btn_top = QPushButton("⏫ Đỉnh cùng")
        self.btn_top.setToolTip("Đưa lớp lên trên cùng (Foreground)")
        self.btn_up = QPushButton("▲ Lên")
        self.btn_up.setToolTip("Đưa lớp lên 1 bậc")
        self.btn_down = QPushButton("▼ Xuống")
        self.btn_down.setToolTip("Đưa lớp xuống 1 bậc")
        self.btn_bot = QPushButton("⏬ Đáy cùng (Lớp nền)")
        self.btn_bot.setToolTip("Đưa lớp ảnh/video nền xuống đáy cùng (Z-Index = 0)")
        self.btn_dup = QPushButton("📋 Nhân bản")
        self.btn_del = QPushButton("🗑️ Xóa lớp")

        self.btn_top.clicked.connect(self._move_layer_to_top)
        self.btn_up.clicked.connect(self._move_layer_up)
        self.btn_down.clicked.connect(self._move_layer_down)
        self.btn_bot.clicked.connect(self._move_layer_to_bottom)
        self.btn_dup.clicked.connect(self._duplicate_layer)
        self.btn_del.clicked.connect(self._delete_layer)

        ctrl_btn_row.addWidget(self.btn_top)
        ctrl_btn_row.addWidget(self.btn_up)
        ctrl_btn_row.addWidget(self.btn_down)
        ctrl_btn_row.addWidget(self.btn_bot)
        ctrl_btn_row.addWidget(self.btn_dup)
        ctrl_btn_row.addWidget(self.btn_del)
        lg_layout.addLayout(ctrl_btn_row)

        right_layout.addWidget(layer_group, 1)

        # Group 2: Bảng Thuộc Tính Layer Đang Chọn (Inspector)
        self.prop_group = QGroupBox("Thuộc Tính Lớp Đã Chọn")
        prop_layout = QFormLayout(self.prop_group)

        self.prop_name_edit = QLineEdit()
        self.prop_name_edit.textEdited.connect(self._on_prop_edited)
        prop_layout.addRow("Tên Lớp:", self.prop_name_edit)

        # File path picker
        file_row = QHBoxLayout()
        self.prop_file_edit = QLineEdit()
        self.prop_file_edit.textEdited.connect(self._on_prop_edited)
        self.prop_file_btn = QPushButton("Chọn File...")
        self.prop_file_btn.clicked.connect(self._choose_layer_file)
        file_row.addWidget(self.prop_file_edit, 1)
        file_row.addWidget(self.prop_file_btn)
        self.file_row_widget = QWidget()
        self.file_row_widget.setLayout(file_row)
        prop_layout.addRow("Đường dẫn File:", self.file_row_widget)

        # Checkbox Enabled & Locked
        state_row = QHBoxLayout()
        self.prop_enabled_chk = QCheckBox("Hiển thị (Bật)")
        self.prop_locked_chk = QCheckBox("Khóa vị trí (Tránh bấm nhầm)")
        self.prop_enabled_chk.toggled.connect(self._on_prop_edited)
        self.prop_locked_chk.toggled.connect(self._on_prop_edited)
        state_row.addWidget(self.prop_enabled_chk)
        state_row.addWidget(self.prop_locked_chk)
        prop_layout.addRow("Trạng thái:", state_row)

        # Opacity
        op_row = QHBoxLayout()
        self.prop_opacity_slider = QSlider(Qt.Horizontal)
        self.prop_opacity_slider.setRange(0, 100)
        self.prop_opacity_slider.setValue(100)
        self.prop_opacity_label = QLabel("100%")
        self.prop_opacity_slider.valueChanged.connect(self._on_opacity_changed)
        op_row.addWidget(self.prop_opacity_slider, 1)
        op_row.addWidget(self.prop_opacity_label)
        prop_layout.addRow("Độ Mờ (Opacity):", op_row)

        # Blend mode
        self.prop_blend_combo = QComboBox()
        self.prop_blend_combo.addItem("Mặc định (Alpha trong suốt)", "alpha")
        self.prop_blend_combo.addItem("Lọc phông đen (Colorkey Black - Cho Hạt rơi/Khói)", "colorkey_black")
        self.prop_blend_combo.currentIndexChanged.connect(self._on_prop_edited)
        prop_layout.addRow("Chế độ hòa trộn:", self.prop_blend_combo)

        # Chế độ co giãn ảnh/GIF (Scale Mode)
        self.scale_mode_row_widget = QWidget()
        sm_layout = QHBoxLayout(self.scale_mode_row_widget)
        sm_layout.setContentsMargins(0, 0, 0, 0)
        self.prop_scale_mode_combo = QComboBox()
        self.prop_scale_mode_combo.addItem("Khớp vừa khít khung kéo (Stretch to Frame - Mặc định)", "stretch")
        self.prop_scale_mode_combo.addItem("Giữ nguyên tỉ lệ ảnh (Fit Inside)", "fit")
        self.prop_scale_mode_combo.addItem("Cắt lấp đầy khung (Fill & Crop)", "crop")
        self.prop_scale_mode_combo.currentIndexChanged.connect(self._on_prop_edited)
        sm_layout.addWidget(self.prop_scale_mode_combo)
        prop_layout.addRow("Co giãn Khung:", self.scale_mode_row_widget)

        # Biến đổi ảnh (Rotation & Flip Horizontal / Vertical)
        self.img_transform_row_widget = QWidget()
        it_layout = QHBoxLayout(self.img_transform_row_widget)
        it_layout.setContentsMargins(0, 0, 0, 0)
        it_layout.setSpacing(6)

        it_layout.addWidget(QLabel("Xoay:"))
        self.prop_rotation_spin = QSpinBox()
        self.prop_rotation_spin.setRange(-180, 180)
        self.prop_rotation_spin.setValue(0)
        self.prop_rotation_spin.setSuffix("°")
        self.prop_rotation_spin.valueChanged.connect(lambda: self._on_prop_edited())
        it_layout.addWidget(self.prop_rotation_spin)

        self.prop_flip_h_btn = QPushButton("↔ Lật Ngang")
        self.prop_flip_h_btn.setCheckable(True)
        self.prop_flip_h_btn.toggled.connect(lambda: self._on_prop_edited())
        it_layout.addWidget(self.prop_flip_h_btn)

        self.prop_flip_v_btn = QPushButton("↕ Lật Dọc")
        self.prop_flip_v_btn.setCheckable(True)
        self.prop_flip_v_btn.toggled.connect(lambda: self._on_prop_edited())
        it_layout.addWidget(self.prop_flip_v_btn)

        prop_layout.addRow("Xoay & Lật ảnh:", self.img_transform_row_widget)

        # Text & Subtitle properties (hiện khi layer type == 'text' hoặc 'subtitle')
        self.text_props_widget = QWidget()
        tp_layout = QFormLayout(self.text_props_widget)
        tp_layout.setContentsMargins(0, 0, 0, 0)
        tp_layout.setSpacing(6)

        text_content_container = QWidget()
        tc_layout = QVBoxLayout(text_content_container)
        tc_layout.setContentsMargins(0, 0, 0, 0)
        tc_layout.setSpacing(4)

        self.prop_text_content = QPlainTextEdit()
        self.prop_text_content.setFixedHeight(75)
        self.prop_text_content.setPlaceholderText("Nhập nội dung chữ... Hoặc nhập {title} để tự động lấy tên video khi render SLL")
        self.prop_text_content.textChanged.connect(self._on_prop_edited)
        tc_layout.addWidget(self.prop_text_content)

        # Thanh nút hỗ trợ chèn biến số động
        self.tag_helper_widget = QWidget()
        th_layout = QHBoxLayout(self.tag_helper_widget)
        th_layout.setContentsMargins(0, 0, 0, 0)
        th_layout.setSpacing(6)

        self.btn_insert_title_tag = QPushButton("➕ Chèn {Tên Video}")
        self.btn_insert_title_tag.setToolTip("Chèn thẻ biến {title} để tự động lấy tên file Video/Audio khi render hàng loạt (SLL)")
        self.btn_insert_title_tag.setStyleSheet("background-color: #2b3d52; color: #5dade2; font-weight: bold; border-radius: 4px; padding: 3px 8px; font-size: 11px;")
        self.btn_insert_title_tag.clicked.connect(self._insert_title_tag)

        self.lbl_tag_hint = QLabel("<span style='color:#8899a6; font-size:11px;'>⚡ Tự động đổi theo tên file khi render SLL</span>")
        th_layout.addWidget(self.btn_insert_title_tag)
        th_layout.addWidget(self.lbl_tag_hint, 1)
        tc_layout.addWidget(self.tag_helper_widget)

        tp_layout.addRow("Nội dung chữ:", text_content_container)

        # Hàng Kiểu Hiển Thị Phụ Đề (Dành riêng cho Layer Subtitle)
        self.sub_mode_row_widget = QWidget()
        sm_layout = QVBoxLayout(self.sub_mode_row_widget)
        sm_layout.setContentsMargins(0, 0, 0, 0)
        sm_layout.setSpacing(4)

        self.prop_sub_mode_combo = QComboBox()
        self.prop_sub_mode_combo.addItem("📜 Cuộn 2 dòng (Truyện dài / Podcast)", "rolling_2line")
        self.prop_sub_mode_combo.addItem("🎬 Chuẩn điện ảnh (Cụm câu hoàn chỉnh + Giữ đệm 2.5s)", "cinema_hold")
        self.prop_sub_mode_combo.addItem("✨ Karaoke Highlight (Shorts / TikTok)", "karaoke_highlight")
        self.prop_sub_mode_combo.currentIndexChanged.connect(self._on_prop_sub_mode_changed)
        sm_layout.addWidget(self.prop_sub_mode_combo)

        self.prop_sub_highlight_widget = QWidget()
        hl_layout = QHBoxLayout(self.prop_sub_highlight_widget)
        hl_layout.setContentsMargins(0, 0, 0, 0)
        self.prop_sub_highlight_btn = QPushButton("🎨 Chọn Màu Highlight...")
        self.prop_sub_highlight_btn.clicked.connect(lambda: self._open_color_dialog("highlight_color", "Màu Highlight Karaoke"))
        hl_layout.addWidget(QLabel("Màu Highlight Karaoke:"))
        hl_layout.addWidget(self.prop_sub_highlight_btn, 1)
        sm_layout.addWidget(self.prop_sub_highlight_widget)

        tp_layout.addRow("Kiểu phụ đề:", self.sub_mode_row_widget)

        # Hàng Kiểu Chữ (Font Family + Font Size + Bold + Italic + Align)
        font_row = QHBoxLayout()
        self.prop_font_combo = QFontComboBox()
        self.prop_font_combo.currentFontChanged.connect(lambda: self._on_prop_edited())

        self.prop_font_size_spin = QSpinBox()
        self.prop_font_size_spin.setRange(8, 300)
        self.prop_font_size_spin.setValue(32)
        self.prop_font_size_spin.setSuffix(" px")
        self.prop_font_size_spin.valueChanged.connect(lambda: self._on_prop_edited())

        self.prop_bold_btn = QPushButton("B")
        self.prop_bold_btn.setCheckable(True)
        self.prop_bold_btn.setFixedWidth(28)
        self.prop_bold_btn.setStyleSheet("font-weight: bold; font-size: 13px;")
        self.prop_bold_btn.toggled.connect(lambda: self._on_prop_edited())

        self.prop_italic_combo = QComboBox()
        self.prop_italic_combo.addItem("I Thẳng", "none")
        self.prop_italic_combo.addItem("I Nghiêng Phải", "right")
        self.prop_italic_combo.addItem("I Nghiêng Trái", "left")
        self.prop_italic_combo.setStyleSheet("font-style: italic; font-size: 12px;")
        self.prop_italic_combo.currentIndexChanged.connect(lambda: self._on_prop_edited())

        self.prop_align_combo = QComboBox()
        self.prop_align_combo.addItem("Căn Giữa", "center")
        self.prop_align_combo.addItem("Căn Trái", "left")
        self.prop_align_combo.addItem("Căn Phải", "right")
        self.prop_align_combo.currentIndexChanged.connect(lambda: self._on_prop_edited())

        font_row.addWidget(self.prop_font_combo, 1)
        font_row.addWidget(self.prop_font_size_spin)
        font_row.addWidget(self.prop_bold_btn)
        font_row.addWidget(self.prop_italic_combo)
        font_row.addWidget(self.prop_align_combo)
        tp_layout.addRow("Kiểu chữ & Cỡ:", font_row)

        # Màu Chữ
        color_row = QHBoxLayout()
        self.prop_text_color_btn = QPushButton("🎨 Chọn Màu Chữ...")
        self.prop_text_color_btn.clicked.connect(lambda: self._open_color_dialog("font_color", "Màu chữ"))
        color_row.addWidget(self.prop_text_color_btn, 1)
        tp_layout.addRow("Màu chữ:", color_row)

        # Viền Chữ (Outline Color + None button + Outline Width)
        outline_row = QHBoxLayout()
        self.prop_text_outline_btn = QPushButton("🎨 Chọn Màu Viền...")
        self.prop_text_outline_btn.clicked.connect(lambda: self._open_color_dialog("outline_color", "Màu viền"))
        self.prop_outline_none_btn = QPushButton("🚫 None (Không viền)")
        self.prop_outline_none_btn.clicked.connect(lambda: self._set_color_none("outline_color"))

        self.prop_outline_width_spin = QDoubleSpinBox()
        self.prop_outline_width_spin.setRange(0.0, 30.0)
        self.prop_outline_width_spin.setSingleStep(0.5)
        self.prop_outline_width_spin.setValue(2.0)
        self.prop_outline_width_spin.setSuffix(" px")
        self.prop_outline_width_spin.valueChanged.connect(lambda: self._on_prop_edited())

        outline_row.addWidget(self.prop_text_outline_btn, 1)
        outline_row.addWidget(self.prop_outline_none_btn)
        outline_row.addWidget(QLabel("Dày:"))
        outline_row.addWidget(self.prop_outline_width_spin)
        tp_layout.addRow("Viền chữ (px):", outline_row)

        # Nền Box (Bg Color + None button + Bo góc + Độ mờ)
        bg_row = QHBoxLayout()
        self.prop_text_bg_btn = QPushButton("🎨 Chọn Màu Nền Box...")
        self.prop_text_bg_btn.clicked.connect(lambda: self._open_color_dialog("bg_box_color", "Màu nền Box"))
        self.prop_bg_none_btn = QPushButton("🚫 None (Không nền)")
        self.prop_bg_none_btn.clicked.connect(lambda: self._set_color_none("bg_box_color"))

        self.prop_box_radius_spin = QSpinBox()
        self.prop_box_radius_spin.setRange(0, 100)
        self.prop_box_radius_spin.setValue(8)
        self.prop_box_radius_spin.setSuffix(" px")
        self.prop_box_radius_spin.valueChanged.connect(lambda: self._on_prop_edited())

        self.prop_bg_opacity_spin = QSpinBox()
        self.prop_bg_opacity_spin.setRange(0, 100)
        self.prop_bg_opacity_spin.setValue(50)
        self.prop_bg_opacity_spin.setSuffix(" %")
        self.prop_bg_opacity_spin.valueChanged.connect(lambda: self._on_prop_edited())

        bg_row.addWidget(self.prop_text_bg_btn, 1)
        bg_row.addWidget(self.prop_bg_none_btn)
        bg_row.addWidget(QLabel("Bo góc:"))
        bg_row.addWidget(self.prop_box_radius_spin)
        bg_row.addWidget(QLabel("Độ mờ:"))
        bg_row.addWidget(self.prop_bg_opacity_spin)
        tp_layout.addRow("Nền Box & Bo góc:", bg_row)

        # Tự động co nhỏ chữ khi tràn khung (Auto Fit Title / Text)
        self.prop_auto_fit_chk = QCheckBox("Tự động co nhỏ cỡ chữ khi tràn khung (Auto Fit)")
        self.prop_auto_fit_chk.setChecked(True)
        self.prop_auto_fit_chk.setToolTip("Khi BẬT: Tự động wrap từ ngữ và hạ cỡ chữ nếu cần để chữ nằm vừa vặn trong khung.\nKhi TẮT: Giữ nguyên 100% kích thước Font chữ đã chọn (vẫn tự động xuống dòng trong khung).")
        self.prop_auto_fit_chk.toggled.connect(lambda: self._on_prop_edited())
        tp_layout.addRow("Tối ưu cỡ chữ:", self.prop_auto_fit_chk)

        prop_layout.addRow(self.text_props_widget)

        # Nhóm Hiệu ứng & Chuyển động (In / Out / Motion Effect cho Text & Ảnh)
        self.anim_props_widget = QWidget()
        ap_layout = QFormLayout(self.anim_props_widget)
        ap_layout.setContentsMargins(0, 0, 0, 0)
        ap_layout.setSpacing(6)

        # Hàng Hiệu ứng Vào (In Effect) + Thời lượng (Duration)
        in_row = QHBoxLayout()
        self.prop_in_effect_combo = QComboBox()
        self.prop_in_effect_combo.addItem("Hiện ngay (Không hiệu ứng)", "none")
        self.prop_in_effect_combo.addItem("✨ Mờ dần vào (Fade In)", "fade_in")
        self.prop_in_effect_combo.addItem("⬅️ Trượt từ Trái sang (Slide Left)", "slide_left")
        self.prop_in_effect_combo.addItem("➡️ Trượt từ Phải sang (Slide Right)", "slide_right")
        self.prop_in_effect_combo.addItem("⬆️ Trượt từ Dưới lên (Slide Up)", "slide_up")
        self.prop_in_effect_combo.addItem("⬇️ Trượt từ Trên xuống (Slide Down)", "slide_down")
        self.prop_in_effect_combo.addItem("🔍 Phóng to vào (Zoom In)", "zoom_in")
        self.prop_in_effect_combo.currentIndexChanged.connect(lambda: self._on_prop_edited())

        self.prop_in_dur_spin = QDoubleSpinBox()
        self.prop_in_dur_spin.setRange(0.2, 5.0)
        self.prop_in_dur_spin.setSingleStep(0.1)
        self.prop_in_dur_spin.setValue(0.8)
        self.prop_in_dur_spin.setSuffix(" s")
        self.prop_in_dur_spin.valueChanged.connect(lambda: self._on_prop_edited())

        in_row.addWidget(self.prop_in_effect_combo, 2)
        in_row.addWidget(QLabel("Thời lượng:"))
        in_row.addWidget(self.prop_in_dur_spin, 1)
        ap_layout.addRow("Hiệu ứng Vào (In):", in_row)

        # Hàng Hiệu ứng Ra (Out Effect) + Chuyển động (Motion)
        out_row = QHBoxLayout()
        self.prop_out_effect_combo = QComboBox()
        self.prop_out_effect_combo.addItem("Giữ đến hết (Không hiệu ứng)", "none")
        self.prop_out_effect_combo.addItem("💨 Mờ dần ở cuối (Fade Out)", "fade_out")
        self.prop_out_effect_combo.addItem("⬇️ Trượt biến mất xuống (Slide Down)", "slide_down")
        self.prop_out_effect_combo.addItem("⬅️ Trượt biến mất sang trái", "slide_left")
        self.prop_out_effect_combo.addItem("➡️ Trượt biến mất sang phải", "slide_right")
        self.prop_out_effect_combo.currentIndexChanged.connect(lambda: self._on_prop_edited())

        self.prop_motion_combo = QComboBox()
        for label, val in TEXT_MOTIONS:
            self.prop_motion_combo.addItem(label, val)
        self.prop_motion_combo.currentIndexChanged.connect(lambda: self._on_prop_edited())

        out_row.addWidget(self.prop_out_effect_combo, 1)
        out_row.addWidget(QLabel("Chuyển động:"))
        out_row.addWidget(self.prop_motion_combo, 1)
        ap_layout.addRow("Hiệu ứng Ra & Động:", out_row)

        prop_layout.addRow(self.anim_props_widget)

        # Coordinates Display (X, Y, W, H %)
        coord_row = QHBoxLayout()
        self.spin_x = QDoubleSpinBox()
        self.spin_x.setRange(-100.0, 150.0)
        self.spin_x.setSingleStep(0.5)
        self.spin_x.setDecimals(1)
        self.spin_x.setSuffix("%")
        self.spin_y = QDoubleSpinBox()
        self.spin_y.setRange(-100.0, 150.0)
        self.spin_y.setSingleStep(0.5)
        self.spin_y.setDecimals(1)
        self.spin_y.setSuffix("%")
        self.spin_w = QDoubleSpinBox()
        self.spin_w.setRange(0.5, 200.0)
        self.spin_w.setSingleStep(0.5)
        self.spin_w.setDecimals(1)
        self.spin_w.setSuffix("%")
        self.spin_h = QDoubleSpinBox()
        self.spin_h.setRange(0.5, 200.0)
        self.spin_h.setSingleStep(0.5)
        self.spin_h.setDecimals(1)
        self.spin_h.setSuffix("%")

        for sp in (self.spin_x, self.spin_y, self.spin_w, self.spin_h):
            sp.valueChanged.connect(self._on_coord_spin_changed)

        coord_row.addWidget(QLabel("X:"))
        coord_row.addWidget(self.spin_x)
        coord_row.addWidget(QLabel("Y:"))
        coord_row.addWidget(self.spin_y)
        coord_row.addWidget(QLabel("Rộng:"))
        coord_row.addWidget(self.spin_w)
        coord_row.addWidget(QLabel("Cao:"))
        coord_row.addWidget(self.spin_h)
        prop_layout.addRow("Tọa độ & Kích thước:", coord_row)

        right_layout.addWidget(self.prop_group)
        splitter.addWidget(right_widget)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter)

    def _get_layers(self) -> List[Dict[str, Any]]:
        return self.settings.get("layout_studio", {}).get("layers", [])

    def _sync_to_ui(self) -> None:
        self._updating = True
        export_cfg = self.settings.get("export", {})
        width = int(export_cfg.get("width", 1920))
        height = int(export_cfg.get("height", 1080))
        self.canvas.set_aspect_ratio(width, height)
        self.ratio_label.setText(f"Tỉ lệ: {export_cfg.get('ratio', '16:9')} ({width}x{height})")

        layers = self._get_layers()
        self.layer_list.clear()
        for idx, layer in enumerate(layers):
            item = QListWidgetItem(self._format_layer_item_text(layer, idx))
            self.layer_list.addItem(item)

        cur_idx = self.canvas.selected_idx
        if 0 <= cur_idx < len(layers):
            self.layer_list.setCurrentRow(cur_idx)
            self._update_inspector(layers[cur_idx])
        else:
            self.prop_group.setEnabled(False)

        self.canvas.set_layers(layers, cur_idx)
        self._updating = False

    def _format_layer_item_text(self, layer: Dict[str, Any], idx: int = 0) -> str:
        name = layer.get("name", f"Layer {idx+1}")
        l_type = layer.get("type", "image")
        icons = {
            "image": "🖼️", "gif": "🎬", "video_mask": "📽️",
            "text": "📝", "subtitle": "💬", "live_badge": "🔴",
            "watermark": "💧", "logo": "🏷️"
        }
        icon = icons.get(l_type, "🖼️")
        status = "" if layer.get("enabled", True) else " [Ẩn]"
        lock = " 🔒" if layer.get("locked", False) else ""
        return f"{icon} {name}{status}{lock}"

    def _update_color_buttons_display(self, layer: Dict[str, Any]) -> None:
        # Font Color
        fc = str(layer.get("font_color", "#FFFFFF")).strip()
        self.prop_text_color_btn.setText(f"Màu chữ: {fc}")
        if fc.startswith("#"):
            text_c = "#000000" if self._is_light_color(fc) else "#FFFFFF"
            self.prop_text_color_btn.setStyleSheet(f"background-color: {fc}; color: {text_c}; font-weight: bold; border-radius: 4px; padding: 4px;")
        else:
            self.prop_text_color_btn.setStyleSheet("")

        # Outline Color
        oc = str(layer.get("outline_color", "#000000")).strip()
        if oc.lower() in {"none", "transparent", ""}:
            self.prop_text_outline_btn.setText("Màu viền: [🚫 Không viền]")
            self.prop_text_outline_btn.setStyleSheet("color: #888888; font-style: italic; border-radius: 4px; padding: 4px;")
        else:
            self.prop_text_outline_btn.setText(f"Màu viền: {oc}")
            if oc.startswith("#"):
                text_c = "#000000" if self._is_light_color(oc) else "#FFFFFF"
                self.prop_text_outline_btn.setStyleSheet(f"background-color: {oc}; color: {text_c}; font-weight: bold; border-radius: 4px; padding: 4px;")
            else:
                self.prop_text_outline_btn.setStyleSheet("")

        # Bg Box Color
        bg = str(layer.get("bg_box_color", "#000000")).strip()
        bg_enabled = bool(layer.get("bg_box_enabled", True))
        if not bg_enabled or bg.lower() in {"none", "transparent", ""}:
            self.prop_text_bg_btn.setText("Màu nền: [🚫 Không nền]")
            self.prop_text_bg_btn.setStyleSheet("color: #888888; font-style: italic; border-radius: 4px; padding: 4px;")
        else:
            self.prop_text_bg_btn.setText(f"Màu nền: {bg}")
            if bg.startswith("#"):
                text_c = "#000000" if self._is_light_color(bg) else "#FFFFFF"
                self.prop_text_bg_btn.setStyleSheet(f"background-color: {bg}; color: {text_c}; font-weight: bold; border-radius: 4px; padding: 4px;")
            else:
                self.prop_text_bg_btn.setStyleSheet("")

        # Highlight Color (cho Subtitle Karaoke)
        hl = str(layer.get("highlight_color", "#FFE600")).strip()
        self.prop_sub_highlight_btn.setText(f"Màu Highlight: {hl}")
        if hl.startswith("#"):
            text_c = "#000000" if self._is_light_color(hl) else "#FFFFFF"
            self.prop_sub_highlight_btn.setStyleSheet(f"background-color: {hl}; color: {text_c}; font-weight: bold; border-radius: 4px; padding: 4px;")
        else:
            self.prop_sub_highlight_btn.setStyleSheet("")

    @staticmethod
    def _is_light_color(hex_str: str) -> bool:
        try:
            h = hex_str.lstrip("#")
            if len(h) >= 6:
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                return (r * 299 + g * 587 + b * 114) / 1000 > 128
        except Exception:
            pass
        return False

    def _insert_title_tag(self) -> None:
        """Chèn biến {title} vào ô nội dung chữ để tự động lấy tên video/audio khi render hàng loạt."""
        cursor = self.prop_text_content.textCursor()
        cursor.insertText("{title}")
        self.prop_text_content.setFocus()

    def _on_prop_sub_mode_changed(self) -> None:
        sm_mode = self.prop_sub_mode_combo.currentData()
        self.prop_sub_highlight_widget.setVisible(sm_mode == "karaoke_highlight")
        self._on_prop_edited()

    def _update_inspector(self, layer: Dict[str, Any]) -> None:
        self.prop_group.setEnabled(True)
        self.prop_name_edit.blockSignals(True)
        self.prop_name_edit.setText(layer.get("name", ""))
        self.prop_name_edit.blockSignals(False)

        self.prop_file_edit.blockSignals(True)
        self.prop_file_edit.setText(layer.get("file_path", ""))
        self.prop_file_edit.blockSignals(False)

        self.prop_enabled_chk.blockSignals(True)
        self.prop_enabled_chk.setChecked(layer.get("enabled", True))
        self.prop_enabled_chk.blockSignals(False)

        self.prop_locked_chk.blockSignals(True)
        self.prop_locked_chk.setChecked(layer.get("locked", False))
        self.prop_locked_chk.blockSignals(False)

        op = int(float(layer.get("opacity", 1.0) if layer.get("opacity") is not None else 1.0) * 100)
        self.prop_opacity_slider.blockSignals(True)
        self.prop_opacity_slider.setValue(op)
        self.prop_opacity_label.setText(f"{op}%")
        self.prop_opacity_slider.blockSignals(False)

        b_idx = self.prop_blend_combo.findData(layer.get("blend_mode", "alpha"))
        if b_idx >= 0:
            self.prop_blend_combo.blockSignals(True)
            self.prop_blend_combo.setCurrentIndex(b_idx)
            self.prop_blend_combo.blockSignals(False)

        sm_idx = self.prop_scale_mode_combo.findData(layer.get("scale_mode", "stretch"))
        self.prop_scale_mode_combo.blockSignals(True)
        if sm_idx >= 0:
            self.prop_scale_mode_combo.setCurrentIndex(sm_idx)
        else:
            self.prop_scale_mode_combo.setCurrentIndex(0)
        self.prop_scale_mode_combo.blockSignals(False)

        l_type = layer.get("type", "image")
        is_img_like = l_type in {"image", "gif", "video_mask", "banner", "logo", "watermark", "chat_bubble", "reaction"}
        self.file_row_widget.setVisible(l_type in {"image", "gif", "video_mask", "banner", "logo", "watermark"})
        self.scale_mode_row_widget.setVisible(is_img_like)
        self.img_transform_row_widget.setVisible(is_img_like)
        self.text_props_widget.setVisible(l_type in {"text", "subtitle"})

        if is_img_like:
            self.prop_rotation_spin.blockSignals(True)
            self.prop_rotation_spin.setValue(int(layer.get("rotation", 0) or 0))
            self.prop_rotation_spin.blockSignals(False)

            self.prop_flip_h_btn.blockSignals(True)
            self.prop_flip_h_btn.setChecked(bool(layer.get("flip_h", False)))
            self.prop_flip_h_btn.blockSignals(False)

            self.prop_flip_v_btn.blockSignals(True)
            self.prop_flip_v_btn.setChecked(bool(layer.get("flip_v", False)))
            self.prop_flip_v_btn.blockSignals(False)

        # Hiển thị nhóm hiệu ứng In/Out/Motion chỉ cho Text và các loại Ảnh
        can_animate = l_type in {"text", "image", "banner", "logo", "watermark", "chat_bubble"}
        self.anim_props_widget.setVisible(can_animate)

        if can_animate:
            in_eff = layer.get("in_effect", "none")
            in_idx = self.prop_in_effect_combo.findData(in_eff)
            self.prop_in_effect_combo.blockSignals(True)
            self.prop_in_effect_combo.setCurrentIndex(max(0, in_idx))
            self.prop_in_effect_combo.blockSignals(False)

            self.prop_in_dur_spin.blockSignals(True)
            self.prop_in_dur_spin.setValue(float(layer.get("in_duration", 0.8) or 0.8))
            self.prop_in_dur_spin.blockSignals(False)

            out_eff = layer.get("out_effect", "none")
            out_idx = self.prop_out_effect_combo.findData(out_eff)
            self.prop_out_effect_combo.blockSignals(True)
            self.prop_out_effect_combo.setCurrentIndex(max(0, out_idx))
            self.prop_out_effect_combo.blockSignals(False)

            is_text_layer = (l_type in {"text", "subtitle"})
            current_motion_items = TEXT_MOTIONS if is_text_layer else IMAGE_MOTIONS
            self.prop_motion_combo.blockSignals(True)
            self.prop_motion_combo.clear()
            for label, val in current_motion_items:
                self.prop_motion_combo.addItem(label, val)

            mot_eff = str(layer.get("motion_effect", "none") or "none")
            mot_idx = self.prop_motion_combo.findData(mot_eff)
            if mot_idx < 0:
                mot_idx = self.prop_motion_combo.findData("none")
            self.prop_motion_combo.setCurrentIndex(max(0, mot_idx))
            self.prop_motion_combo.blockSignals(False)

        if l_type in {"text", "subtitle"}:
            self.tag_helper_widget.setVisible(l_type == "text")
            if l_type == "subtitle":
                self.sub_mode_row_widget.setVisible(True)
                self.prop_sub_mode_combo.blockSignals(True)
                sm_mode = str(layer.get("sub_mode", "rolling_2line") or "rolling_2line")
                sm_i = self.prop_sub_mode_combo.findData(sm_mode)
                if sm_i >= 0:
                    self.prop_sub_mode_combo.setCurrentIndex(sm_i)
                self.prop_sub_mode_combo.blockSignals(False)
                self.prop_sub_highlight_widget.setVisible(sm_mode == "karaoke_highlight")
            else:
                self.sub_mode_row_widget.setVisible(False)

            self.prop_text_content.blockSignals(True)
            if l_type == "subtitle":
                self.prop_text_content.setPlaceholderText("💬 Phụ đề mẫu (Live Preview): Vùng này sẽ tự động thay thế bằng phụ đề khi render")
            else:
                self.prop_text_content.setPlaceholderText("Nhập nội dung chữ... Hoặc nhập {title} để tự động lấy tên video khi render SLL")
            self.prop_text_content.setPlainText(str(layer.get("text_content", "")))
            self.prop_text_content.blockSignals(False)

            self.prop_font_combo.blockSignals(True)
            f_name = str(layer.get("font_name", "Arial") or "Arial")
            self.prop_font_combo.setCurrentFont(QFont(f_name))
            self.prop_font_combo.blockSignals(False)

            self.prop_font_size_spin.blockSignals(True)
            self.prop_font_size_spin.setValue(int(layer.get("font_size", 32 if l_type == "text" else 38) or 32))
            self.prop_font_size_spin.blockSignals(False)

            self.prop_bold_btn.blockSignals(True)
            self.prop_bold_btn.setChecked(bool(layer.get("bold", True)))
            self.prop_bold_btn.blockSignals(False)

            raw_italic_mode = layer.get("italic_mode")
            if not raw_italic_mode:
                raw_italic_mode = "right" if layer.get("italic", False) else "none"
            self.prop_italic_combo.blockSignals(True)
            it_idx = self.prop_italic_combo.findData(raw_italic_mode)
            self.prop_italic_combo.setCurrentIndex(max(0, it_idx))
            self.prop_italic_combo.blockSignals(False)

            self.prop_align_combo.blockSignals(True)
            a_idx = self.prop_align_combo.findData(layer.get("align", "center"))
            if a_idx >= 0:
                self.prop_align_combo.setCurrentIndex(a_idx)
            self.prop_align_combo.blockSignals(False)

            self.prop_auto_fit_chk.blockSignals(True)
            self.prop_auto_fit_chk.setChecked(bool(layer.get("auto_fit", True)))
            self.prop_auto_fit_chk.blockSignals(False)

            self.prop_outline_width_spin.blockSignals(True)
            self.prop_outline_width_spin.setValue(float(layer.get("outline_width", 2.0 if l_type == "text" else 2.5) or 2.0))
            self.prop_outline_width_spin.blockSignals(False)

            self.prop_box_radius_spin.blockSignals(True)
            self.prop_box_radius_spin.setValue(int(layer.get("box_radius", 8 if l_type == "text" else 6) or 8))
            self.prop_box_radius_spin.blockSignals(False)

            self.prop_bg_opacity_spin.blockSignals(True)
            self.prop_bg_opacity_spin.setValue(int(float(layer.get("bg_box_opacity", 0.5) if layer.get("bg_box_opacity") is not None else 0.5) * 100))
            self.prop_bg_opacity_spin.blockSignals(False)

            self._update_color_buttons_display(layer)

        self.spin_x.blockSignals(True)
        self.spin_y.blockSignals(True)
        self.spin_w.blockSignals(True)
        self.spin_h.blockSignals(True)
        self.spin_x.setValue(float(layer.get("box_x", 0.0)) * 100)
        self.spin_y.setValue(float(layer.get("box_y", 0.0)) * 100)
        self.spin_w.setValue(float(layer.get("box_w", 0.3)) * 100)
        self.spin_h.setValue(float(layer.get("box_h", 0.2)) * 100)
        self.spin_x.blockSignals(False)
        self.spin_y.blockSignals(False)
        self.spin_w.blockSignals(False)
        self.spin_h.blockSignals(False)

    def _on_layer_row_changed(self, row: int) -> None:
        if self._updating:
            return
        layers = self._get_layers()
        if 0 <= row < len(layers):
            self.canvas.selected_idx = row
            self.canvas.update()
            self._update_inspector(layers[row])
        else:
            self.canvas.selected_idx = -1
            self.canvas.update()
            self.prop_group.setEnabled(False)

    def _on_canvas_layer_selected(self, idx: int) -> None:
        if self._updating:
            return
        self._updating = True
        if 0 <= idx < self.layer_list.count():
            self.layer_list.setCurrentRow(idx)
            layers = self._get_layers()
            self._update_inspector(layers[idx])
        else:
            self.layer_list.setCurrentRow(-1)
            self.prop_group.setEnabled(False)
        self._updating = False

    def _on_canvas_layer_changed(self, idx: int, layer: Dict[str, Any]) -> None:
        layers = self._get_layers()
        if 0 <= idx < len(layers):
            layers[idx] = layer
            self._updating = True
            self.spin_x.setValue(float(layer.get("box_x", 0.0)) * 100)
            self.spin_y.setValue(float(layer.get("box_y", 0.0)) * 100)
            self.spin_w.setValue(float(layer.get("box_w", 0.3)) * 100)
            self.spin_h.setValue(float(layer.get("box_h", 0.2)) * 100)
            self._updating = False

            if layer.get("type") == "subtitle":
                sub_cfg = self.settings.setdefault("subtitle", {})
                sub_cfg["box_x"] = float(layer.get("box_x", 0.15))
                sub_cfg["box_y"] = float(layer.get("box_y", 0.70))
                sub_cfg["box_w"] = float(layer.get("box_w", 0.70))
                sub_cfg["box_h"] = float(layer.get("box_h", 0.20))

            self.settings_changed.emit(self.settings)

    def _on_coord_spin_changed(self) -> None:
        if self._updating:
            return
        layers = self._get_layers()
        idx = self.layer_list.currentRow()
        if 0 <= idx < len(layers):
            layers[idx]["box_x"] = round(self.spin_x.value() / 100.0, 4)
            layers[idx]["box_y"] = round(self.spin_y.value() / 100.0, 4)
            layers[idx]["box_w"] = round(self.spin_w.value() / 100.0, 4)
            layers[idx]["box_h"] = round(self.spin_h.value() / 100.0, 4)
            if layers[idx].get("type") == "subtitle":
                sub_cfg = self.settings.setdefault("subtitle", {})
                sub_cfg["box_x"] = layers[idx]["box_x"]
                sub_cfg["box_y"] = layers[idx]["box_y"]
                sub_cfg["box_w"] = layers[idx]["box_w"]
                sub_cfg["box_h"] = layers[idx]["box_h"]
            self.canvas.set_layers(layers, idx)
            self.settings_changed.emit(self.settings)

    def _on_preview_title_changed(self, text: str) -> None:
        self.canvas.preview_title = text.strip()
        self.canvas.mark_dirty()

    def _on_opacity_changed(self, val: int) -> None:
        self.prop_opacity_label.setText(f"{val}%")
        if self._updating:
            return
        layers = self._get_layers()
        idx = self.layer_list.currentRow()
        if 0 <= idx < len(layers):
            layers[idx]["opacity"] = round(val / 100.0, 2)
            self.canvas.set_layers(layers, idx)
            self.settings_changed.emit(self.settings)

    def _on_prop_edited(self) -> None:
        if self._updating:
            return
        layers = self._get_layers()
        idx = self.layer_list.currentRow()
        if 0 <= idx < len(layers):
            layer = layers[idx]
            # Giữ nguyên dấu cách, không .strip() name
            layer["name"] = self.prop_name_edit.text()
            layer["file_path"] = self.prop_file_edit.text().strip()
            layer["enabled"] = self.prop_enabled_chk.isChecked()
            layer["locked"] = self.prop_locked_chk.isChecked()
            layer["blend_mode"] = self.prop_blend_combo.currentData()
            layer["scale_mode"] = self.prop_scale_mode_combo.currentData() or "stretch"

            l_type = layer.get("type")
            is_img_like = l_type in {"image", "gif", "video_mask", "banner", "logo", "watermark", "chat_bubble", "reaction"}
            if is_img_like:
                layer["rotation"] = self.prop_rotation_spin.value()
                layer["flip_h"] = self.prop_flip_h_btn.isChecked()
                layer["flip_v"] = self.prop_flip_v_btn.isChecked()

            if l_type in {"text", "subtitle"}:
                layer["text_content"] = self.prop_text_content.toPlainText()
                layer["font_name"] = self.prop_font_combo.currentFont().family()
                layer["font_size"] = self.prop_font_size_spin.value()
                layer["bold"] = self.prop_bold_btn.isChecked()
                it_mode = self.prop_italic_combo.currentData() or "none"
                layer["italic_mode"] = it_mode
                layer["italic"] = (it_mode != "none")
                layer["align"] = self.prop_align_combo.currentData() or "center"
                layer["auto_fit"] = self.prop_auto_fit_chk.isChecked()
                layer["outline_width"] = self.prop_outline_width_spin.value()
                layer["box_radius"] = self.prop_box_radius_spin.value()
                layer["bg_box_opacity"] = round(self.prop_bg_opacity_spin.value() / 100.0, 2)

                if l_type == "subtitle":
                    layer["sub_mode"] = self.prop_sub_mode_combo.currentData() or "rolling_2line"
                    layer["highlight_color"] = layer.get("highlight_color", "#FFE600")
                    sub_cfg = self.settings.setdefault("subtitle", {})
                    sub_cfg["box_x"] = float(layer.get("box_x", 0.15))
                    sub_cfg["box_y"] = float(layer.get("box_y", 0.70))
                    sub_cfg["box_w"] = float(layer.get("box_w", 0.70))
                    sub_cfg["box_h"] = float(layer.get("box_h", 0.20))
                    sub_cfg["font_family"] = layer["font_name"]
                    sub_cfg["font_size"] = layer["font_size"]
                    sub_cfg["font_color"] = layer.get("font_color", "#FFFFFF")
                    sub_cfg["highlight_color"] = layer["highlight_color"]
                    sub_cfg["outline_color"] = layer.get("outline_color", "#000000")
                    sub_cfg["outline_width"] = layer["outline_width"]
                    sub_cfg["bold"] = layer["bold"]
                    sub_cfg["italic"] = layer["italic"]
                    sub_cfg["italic_mode"] = layer["italic_mode"]
                    sub_cfg["align"] = layer["align"]
                    sub_cfg["sub_mode"] = layer["sub_mode"]
                    sub_cfg["enabled"] = layer["enabled"]

            # Lưu thuộc tính hiệu ứng In/Out/Motion cho Text & Ảnh
            can_animate = l_type in {"text", "image", "banner", "logo", "watermark", "chat_bubble"}
            if can_animate:
                layer["in_effect"] = self.prop_in_effect_combo.currentData() or "none"
                layer["in_duration"] = self.prop_in_dur_spin.value()
                layer["out_effect"] = self.prop_out_effect_combo.currentData() or "none"
                layer["motion_effect"] = self.prop_motion_combo.currentData() or "none"

            item = self.layer_list.item(idx)
            if item:
                item.setText(self._format_layer_item_text(layer, idx))

            self.canvas.set_layers(layers, idx)
            self.settings_changed.emit(self.settings)

    def _choose_layer_file(self) -> None:
        layers = self._get_layers()
        idx = self.layer_list.currentRow()
        if 0 <= idx < len(layers):
            l_type = layers[idx].get("type", "image")
            filter_str = "All Supported (*.png *.jpg *.jpeg *.webp *.gif *.mp4 *.mov);;Images (*.png *.jpg *.jpeg *.webp);;GIF (*.gif);;Videos (*.mp4 *.mov)"
            if l_type == "gif":
                filter_str = "GIF (*.gif)"
            elif l_type == "video_mask":
                filter_str = "Videos (*.mp4 *.mov)"

            file_path, _ = QFileDialog.getOpenFileName(self, "Chọn File cho Layer", self.prop_file_edit.text(), filter_str)
            if file_path:
                self.prop_file_edit.setText(file_path)
                self._on_prop_edited()

    def _open_color_dialog(self, key: str, label_name: str) -> None:
        layers = self._get_layers()
        idx = self.layer_list.currentRow()
        if 0 <= idx < len(layers):
            layer = layers[idx]
            original_val = str(layer.get(key, "#FFFFFF")).strip()
            if original_val.lower() in {"none", "transparent", ""}:
                init_color = QColor("#FFFFFF" if key == "font_color" else "#000000")
            else:
                init_color = QColor(original_val)
                if not init_color.isValid():
                    init_color = QColor("#FFFFFF")

            dlg = QColorDialog(init_color, self)
            dlg.setWindowTitle(f"Chọn {label_name}")
            dlg.setOption(QColorDialog.ShowAlphaChannel, True)

            def on_color_live_changed(c: QColor) -> None:
                if c.isValid():
                    layer[key] = c.name()
                    if key == "bg_box_color":
                        layer["bg_box_enabled"] = True
                    self._update_color_buttons_display(layer)
                    self.canvas.update()

            dlg.currentColorChanged.connect(on_color_live_changed)

            if dlg.exec() == QColorDialog.Accepted:
                final_c = dlg.selectedColor()
                if final_c.isValid():
                    layer[key] = final_c.name()
                    if key == "bg_box_color":
                        layer["bg_box_enabled"] = True
                    self._update_color_buttons_display(layer)
                    self._on_prop_edited()
            else:
                # Phục hồi lại màu ban đầu nếu bấm Hủy (Cancel)
                layer[key] = original_val
                if key == "bg_box_color":
                    layer["bg_box_enabled"] = (original_val.lower() not in {"none", "transparent", ""})
                self._update_color_buttons_display(layer)
                self.canvas.update()

    def _set_color_none(self, key: str) -> None:
        layers = self._get_layers()
        idx = self.layer_list.currentRow()
        if 0 <= idx < len(layers):
            layer = layers[idx]
            layer[key] = "none"
            if key == "bg_box_color":
                layer["bg_box_enabled"] = False
            self._update_color_buttons_display(layer)
            self._on_prop_edited()

    def _pick_color(self, key: str) -> None:
        self._open_color_dialog(key, "Màu sắc")

    def _add_layer(self, layer_type: str) -> None:
        layers = self._get_layers()
        new_layer = {
            "id": f"layer_{uuid.uuid4().hex[:6]}",
            "name": f"Lớp mới ({layer_type})",
            "type": layer_type,
            "file_path": "",
            "enabled": True,
            "locked": False,
            "box_x": 0.35, "box_y": 0.35, "box_w": 0.30, "box_h": 0.30,
            "opacity": 1.0,
            "blend_mode": "alpha"
        }
        if layer_type == "text":
            new_layer["name"] = "📝 Tiêu Đề Mới"
            new_layer["text_content"] = "Tiêu đề mới\n(Dòng 2 ví dụ)"
            new_layer["box_x"] = 0.15
            new_layer["box_y"] = 0.15
            new_layer["box_w"] = 0.70
            new_layer["box_h"] = 0.14
            new_layer["font_name"] = "Arial"
            new_layer["font_size"] = 32
            new_layer["bold"] = True
            new_layer["italic"] = False
            new_layer["italic_mode"] = "none"
            new_layer["align"] = "center"
            new_layer["font_color"] = "#FFFFFF"
            new_layer["outline_color"] = "#000000"
            new_layer["outline_width"] = 2.0
            new_layer["bg_box_enabled"] = True
            new_layer["bg_box_color"] = "#000000"
            new_layer["bg_box_opacity"] = 0.5
            new_layer["box_radius"] = 8
        elif layer_type == "subtitle":
            sub_cfg = self.settings.setdefault("subtitle", {})
            new_layer["name"] = "💬 Phụ Đề Video (Subtitle)"
            new_layer["text_content"] = ""
            new_layer["sub_mode"] = str(sub_cfg.get("sub_mode", "rolling_2line") or "rolling_2line")
            new_layer["highlight_color"] = str(sub_cfg.get("highlight_color", "#FFE600") or "#FFE600")
            new_layer["box_x"] = float(sub_cfg.get("box_x", 0.15))
            new_layer["box_y"] = float(sub_cfg.get("box_y", 0.70))
            new_layer["box_w"] = float(sub_cfg.get("box_w", 0.70))
            new_layer["box_h"] = float(sub_cfg.get("box_h", 0.20))
            new_layer["font_name"] = str(sub_cfg.get("font_family", "Arial") or "Arial")
            new_layer["font_size"] = int(sub_cfg.get("font_size", 38) or 38)
            new_layer["bold"] = bool(sub_cfg.get("bold", True))
            new_layer["italic"] = bool(sub_cfg.get("italic", False))
            new_layer["italic_mode"] = str(sub_cfg.get("italic_mode", "right" if new_layer["italic"] else "none"))
            new_layer["align"] = "center"
            new_layer["font_color"] = str(sub_cfg.get("font_color", "#FFFFFF") or "#FFFFFF")
            new_layer["outline_color"] = str(sub_cfg.get("outline_color", "#000000") or "#000000")
            new_layer["outline_width"] = float(sub_cfg.get("outline_width", 2.5) or 2.5)
            new_layer["bg_box_enabled"] = False
            new_layer["bg_box_color"] = "none"
            new_layer["bg_box_opacity"] = 0.5
            new_layer["box_radius"] = 6
            sub_cfg["box_x"] = new_layer["box_x"]
            sub_cfg["box_y"] = new_layer["box_y"]
            sub_cfg["box_w"] = new_layer["box_w"]
            sub_cfg["box_h"] = new_layer["box_h"]
            sub_cfg["font_family"] = new_layer["font_name"]
            sub_cfg["font_size"] = new_layer["font_size"]
            sub_cfg["font_color"] = new_layer["font_color"]
            sub_cfg["highlight_color"] = new_layer["highlight_color"]
            sub_cfg["outline_color"] = new_layer["outline_color"]
            sub_cfg["outline_width"] = new_layer["outline_width"]
            sub_cfg["bold"] = new_layer["bold"]
            sub_cfg["italic"] = new_layer["italic"]
            sub_cfg["italic_mode"] = new_layer["italic_mode"]
            sub_cfg["sub_mode"] = new_layer["sub_mode"]
        elif layer_type == "live_badge":
            new_layer["name"] = "🔴 Huy hiệu Live"
            new_layer["box_x"] = 0.04
            new_layer["box_y"] = 0.04
            new_layer["box_w"] = 0.15
            new_layer["box_h"] = 0.06

        layers.append(new_layer)
        self.settings["layout_studio"]["layers"] = layers
        self.canvas.selected_idx = len(layers) - 1
        self._sync_to_ui()
        self.settings_changed.emit(self.settings)

    def _delete_layer(self) -> None:
        layers = self._get_layers()
        idx = self.layer_list.currentRow()
        if 0 <= idx < len(layers):
            del layers[idx]
            self.settings["layout_studio"]["layers"] = layers
            self.canvas.selected_idx = max(-1, idx - 1)
            self._sync_to_ui()
            self.settings_changed.emit(self.settings)

    def _duplicate_layer(self) -> None:
        layers = self._get_layers()
        idx = self.layer_list.currentRow()
        if 0 <= idx < len(layers):
            dup = copy.deepcopy(layers[idx])
            dup["id"] = f"layer_{uuid.uuid4().hex[:6]}"
            dup["name"] = dup["name"] + " (Copy)"
            dup["box_x"] = min(0.9, dup["box_x"] + 0.03)
            dup["box_y"] = min(0.9, dup["box_y"] + 0.03)
            layers.append(dup)
            self.settings["layout_studio"]["layers"] = layers
            self.canvas.selected_idx = len(layers) - 1
            self._sync_to_ui()
            self.settings_changed.emit(self.settings)

    def _move_layer_to_top(self) -> None:
        """Đưa layer lên trên cùng (Lớp trên cùng / Foreground)."""
        layers = self._get_layers()
        idx = self.layer_list.currentRow()
        if 0 <= idx < len(layers) - 1:
            layer = layers.pop(idx)
            layers.append(layer)
            self.settings["layout_studio"]["layers"] = layers
            self.canvas.selected_idx = len(layers) - 1
            self._sync_to_ui()
            self.settings_changed.emit(self.settings)

    def _move_layer_to_bottom(self) -> None:
        """Đưa layer xuống đáy cùng (Lớp nền z-index = 0 / Background)."""
        layers = self._get_layers()
        idx = self.layer_list.currentRow()
        if idx > 0 and idx < len(layers):
            layer = layers.pop(idx)
            layers.insert(0, layer)
            self.settings["layout_studio"]["layers"] = layers
            self.canvas.selected_idx = 0
            self._sync_to_ui()
            self.settings_changed.emit(self.settings)

    def _move_layer_up(self) -> None:
        """Đưa layer lên phía trên Z-Index (nằm đè lên các layer dưới)."""
        layers = self._get_layers()
        idx = self.layer_list.currentRow()
        if 0 <= idx < len(layers) - 1:
            layers[idx], layers[idx + 1] = layers[idx + 1], layers[idx]
            self.settings["layout_studio"]["layers"] = layers
            self.canvas.selected_idx = idx + 1
            self._sync_to_ui()
            self.settings_changed.emit(self.settings)

    def _move_layer_down(self) -> None:
        """Đưa layer xuống phía dưới Z-Index (chìm xuống dưới)."""
        layers = self._get_layers()
        idx = self.layer_list.currentRow()
        if idx > 0:
            layers[idx], layers[idx - 1] = layers[idx - 1], layers[idx]
            self.settings["layout_studio"]["layers"] = layers
            self.canvas.selected_idx = idx - 1
            self._sync_to_ui()
            self.settings_changed.emit(self.settings)

    def _reload_presets(self, select_key: Optional[str] = None) -> None:
        target_key = select_key or (self.preset_combo.currentData() if hasattr(self, "preset_combo") else "default")
        if hasattr(self, "preset_combo"):
            self.preset_combo.blockSignals(True)
            self.preset_combo.clear()
            all_presets = get_all_layout_presets()
            for k, v in all_presets.items():
                self.preset_combo.addItem(v["name"], k)
            idx = self.preset_combo.findData(target_key)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)
            else:
                self.preset_combo.setCurrentIndex(0)
            self.preset_combo.blockSignals(False)

    def _on_preset_selected(self, index: int) -> None:
        pass

    def _apply_current_preset(self) -> None:
        p_key = self.preset_combo.currentData()
        all_presets = get_all_layout_presets()
        if p_key in all_presets:
            preset = all_presets[p_key]
            reply = QMessageBox.question(
                self,
                "Áp Dụng Mẫu Bố Cục",
                f"Bạn có chắc muốn áp dụng '{preset['name']}'?\n(Các lớp hiện tại sẽ được thay thế bằng mẫu này)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                self.settings["layout_studio"]["layers"] = copy.deepcopy(preset.get("layers", []))
                self.settings["layout_studio"]["selected_preset"] = p_key
                self.canvas.selected_idx = 0 if len(preset.get("layers", [])) > 0 else -1
                self._sync_to_ui()
                self.settings_changed.emit(self.settings)

    def _quick_save_preset(self) -> None:
        """Lưu đè nhanh vào mẫu tùy chỉnh đang chọn, hoặc mở hộp thoại lưu mới nếu là mẫu mặc định."""
        p_key = self.preset_combo.currentData() if hasattr(self, "preset_combo") else "default"
        all_presets = get_all_layout_presets()
        preset_info = all_presets.get(p_key, {})
        if preset_info.get("is_custom") and preset_info.get("file_path"):
            file_path = Path(preset_info["file_path"])
            clean_name = preset_info.get("name", file_path.stem).replace("⭐ ", "").replace(" (Mẫu riêng)", "").strip()
            data = {
                "name": clean_name,
                "layers": copy.deepcopy(self._get_layers())
            }
            try:
                file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                self._reload_presets(select_key=p_key)
                self.settings_changed.emit(self.settings)
                QMessageBox.information(self, "Thành công", f"✔ Đã cập nhật và lưu đè vào mẫu '{clean_name}'!")
            except Exception as ex:
                QMessageBox.warning(self, "Lỗi", f"Không thể lưu file mẫu: {ex}")
        else:
            # Nếu đang ở preset mặc định, yêu cầu nhập tên để lưu mẫu mới
            self._save_custom_preset()

    def _save_custom_preset(self) -> None:
        """Lưu bố cục hiện tại thành mẫu mới (Save As New Preset)."""
        name, ok = QInputDialog.getText(self, "Lưu Thành Mẫu Mới", "Nhập tên cho mẫu bố cục mới:")
        if ok and name and name.strip():
            clean_name = name.strip()
            LAYOUT_PRESETS_DIR.mkdir(parents=True, exist_ok=True)
            safe_file_name = re.sub(r'[\\/*?:"<>|]', "_", clean_name)
            preset_file = LAYOUT_PRESETS_DIR / f"{safe_file_name}.json"
            data = {
                "name": clean_name,
                "layers": copy.deepcopy(self._get_layers())
            }
            try:
                preset_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                self._reload_presets(select_key=f"custom_{safe_file_name}")
                self.settings_changed.emit(self.settings)
                QMessageBox.information(self, "Thành công", f"✔ Đã lưu mẫu bố cục '{clean_name}' vào presets/layouts/!")
            except Exception as ex:
                QMessageBox.warning(self, "Lỗi", f"Không thể lưu file mẫu: {ex}")

    def _delete_custom_preset(self) -> None:
        p_key = self.preset_combo.currentData()
        if not p_key or not str(p_key).startswith("custom_"):
            QMessageBox.warning(self, "Thông báo", "Chỉ có thể xóa các mẫu tùy chỉnh do bạn tự lưu!")
            return
        all_presets = get_all_layout_presets()
        preset_info = all_presets.get(p_key, {})
        preset_name = preset_info.get("name", p_key)
        reply = QMessageBox.question(
            self,
            "Xóa Mẫu Tùy Chỉnh",
            f"Bạn có chắc muốn xóa mẫu '{preset_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            file_path = preset_info.get("file_path")
            if file_path and Path(file_path).exists():
                try:
                    Path(file_path).unlink()
                except Exception as ex:
                    QMessageBox.warning(self, "Lỗi", f"Không thể xóa file mẫu: {ex}")
                    return
            self._reload_presets(select_key="default")
            self.settings_changed.emit(self.settings)
            QMessageBox.information(self, "Thành công", f"Đã xóa mẫu '{preset_name}'!")

    def update_settings(self, settings: Dict[str, Any]) -> None:
        new_ls = settings.get("layout_studio")
        if new_ls and isinstance(new_ls, dict) and "layers" in new_ls:
            self.settings["layout_studio"] = new_ls
        self.settings.update({k: v for k, v in settings.items() if k != "layout_studio"})
        self._sync_to_ui()


def get_all_layout_presets() -> Dict[str, Dict[str, Any]]:
    """Trả về tất cả preset mặc định + các preset tùy chỉnh trong thư mục presets/layouts."""
    presets = copy.deepcopy(LayoutStudioTab.PRESET_TEMPLATES)
    try:
        LAYOUT_PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        for p in sorted(LAYOUT_PRESETS_DIR.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                name = data.get("name", p.stem)
                layers = data.get("layers", [])
                key = f"custom_{p.stem}"
                presets[key] = {
                    "name": f"⭐ {name} (Mẫu riêng)",
                    "layers": layers,
                    "file_path": str(p),
                    "is_custom": True
                }
            except Exception:
                pass
    except Exception:
        pass
    return presets
