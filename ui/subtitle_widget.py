from __future__ import annotations

import math
from typing import Any, Dict, Tuple

from PySide6.QtCore import Qt, QRect, QRectF, QPoint, QPointF, Signal
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFont, QFontMetrics,
    QLinearGradient, QPainter, QPainterPath, QPen
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QFrame
)


class SubtitleBoxCanvas(QWidget):
    """Canvas tương tác trực quan cho phép kéo thả & co giãn vùng hiển thị phụ đề."""

    # box_changed emits (box_x, box_y, box_w, box_h) in normalized coordinates (0.0 to 1.0)
    box_changed = Signal(float, float, float, float)

    HANDLE_SIZE = 8

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(280, 240)
        self.setMouseTracking(True)

        # Tỉ lệ khung hình mặc định 16:9
        self.ratio_w: float = 16.0
        self.ratio_h: float = 9.0

        # Tọa độ bounding box chuẩn hóa (0.0 -> 1.0)
        # Mặc định theo yêu cầu: 2 bên 15% (margin 15%), cao 20%, cách bottom 10%
        # => x = 0.15, w = 0.70, y = 0.70 (1.0 - 0.10 - 0.20), h = 0.20
        self.box_x: float = 0.15
        self.box_y: float = 0.70
        self.box_w: float = 0.70
        self.box_h: float = 0.20

        # Phong cách chữ phụ đề hiển thị preview
        self.font_family: str = "Arial"
        self.font_size: int = 14
        self.font_color: str = "#FFFFFF"
        self.outline_color: str = "#000000"
        self.outline_width: float = 2.0
        self.is_bold: bool = True
        self.is_italic: bool = False
        self.sample_text: str = "Đây là dòng phụ đề mẫu\n(Subtitle Preview)"

        # Trạng thái tương tác chuột
        self._drag_mode: str | None = None  # 'move', 'nw', 'ne', 'sw', 'se', 'n', 's', 'w', 'e', 'new'
        self._drag_start_pos = QPoint()
        self._drag_start_box = (0.15, 0.70, 0.70, 0.20)
        self._canvas_rect = QRect()

    def set_aspect_ratio(self, ratio_str: str = "16:9", width: int = 1920, height: int = 1080) -> None:
        """Cập nhật tỉ lệ khung hình video để khung canvas co giãn đúng tỉ lệ."""
        if width > 0 and height > 0:
            self.ratio_w = float(width)
            self.ratio_h = float(height)
        elif ":" in str(ratio_str):
            try:
                parts = ratio_str.split(":")
                self.ratio_w = max(1.0, float(parts[0]))
                self.ratio_h = max(1.0, float(parts[1]))
            except Exception:
                self.ratio_w, self.ratio_h = 16.0, 9.0
        self.update()

    def set_box(self, x: float, y: float, w: float, h: float) -> None:
        """Thiết lập tọa độ bounding box chuẩn hóa."""
        self.box_x = max(0.0, min(0.9, float(x)))
        self.box_y = max(0.0, min(0.9, float(y)))
        self.box_w = max(0.05, min(1.0 - self.box_x, float(w)))
        self.box_h = max(0.05, min(1.0 - self.box_y, float(h)))
        self.update()

    def reset_default_box(self) -> None:
        """Khôi phục vùng phụ đề mặc định: 2 bên 15%, cao 20%, cách bottom 10%."""
        self.box_x = 0.15
        self.box_y = 0.70
        self.box_w = 0.70
        self.box_h = 0.20
        self.box_changed.emit(self.box_x, self.box_y, self.box_w, self.box_h)
        self.update()

    def set_style(
        self,
        font_family: str,
        font_size: int,
        font_color: str,
        outline_color: str,
        outline_width: float,
        bold: bool,
        italic: bool
    ) -> None:
        self.font_family = font_family or "Arial"
        self.font_size = font_size
        self.font_color = font_color or "#FFFFFF"
        self.outline_color = outline_color or "#000000"
        self.outline_width = outline_width
        self.is_bold = bold
        self.is_italic = italic
        self.update()

    def _calc_canvas_rect(self) -> QRect:
        margin = 16
        w_avail = max(50, self.width() - margin * 2)
        h_avail = max(50, self.height() - margin * 2 - 20)

        scale = min(w_avail / self.ratio_w, h_avail / self.ratio_h)
        cw = int(self.ratio_w * scale)
        ch = int(self.ratio_h * scale)
        cx = (self.width() - cw) // 2
        cy = 20 + (h_avail - ch) // 2
        return QRect(cx, cy, cw, ch)

    def _box_to_pixel_rect(self) -> QRect:
        cr = self._canvas_rect
        bx = int(cr.x() + self.box_x * cr.width())
        by = int(cr.y() + self.box_y * cr.height())
        bw = max(10, int(self.box_w * cr.width()))
        bh = max(10, int(self.box_h * cr.height()))
        return QRect(bx, by, bw, bh)

    def _get_handles(self, r: QRect) -> Dict[str, QRect]:
        hs = self.HANDLE_SIZE
        half = hs // 2
        return {
            "nw": QRect(r.left() - half, r.top() - half, hs, hs),
            "ne": QRect(r.right() - half, r.top() - half, hs, hs),
            "sw": QRect(r.left() - half, r.bottom() - half, hs, hs),
            "se": QRect(r.right() - half, r.bottom() - half, hs, hs),
            "n": QRect(r.center().x() - half, r.top() - half, hs, hs),
            "s": QRect(r.center().x() - half, r.bottom() - half, hs, hs),
            "w": QRect(r.left() - half, r.center().y() - half, hs, hs),
            "e": QRect(r.right() - half, r.center().y() - half, hs, hs),
        }

    def _hit_test(self, pt: QPoint) -> str | None:
        box_r = self._box_to_pixel_rect()
        handles = self._get_handles(box_r)
        for handle_name, hr in handles.items():
            if hr.contains(pt):
                return handle_name
        if box_r.contains(pt):
            return "move"
        if self._canvas_rect.contains(pt):
            return "new"
        return None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            pt = event.position().toPoint()
            mode = self._hit_test(pt)
            if mode:
                self._drag_mode = mode
                self._drag_start_pos = pt
                self._drag_start_box = (self.box_x, self.box_y, self.box_w, self.box_h)
                if mode == "new":
                    cr = self._canvas_rect
                    nx = (pt.x() - cr.x()) / max(1, cr.width())
                    ny = (pt.y() - cr.y()) / max(1, cr.height())
                    self.box_x = max(0.0, min(0.95, nx))
                    self.box_y = max(0.0, min(0.95, ny))
                    self.box_w = 0.05
                    self.box_h = 0.05
                    self.update()

    def mouseMoveEvent(self, event) -> None:
        pt = event.position().toPoint()
        cr = self._canvas_rect

        if not self._drag_mode:
            # Update cursor on hover
            mode = self._hit_test(pt)
            if mode in ("nw", "se"):
                self.setCursor(QCursor(Qt.SizeFDiagCursor))
            elif mode in ("ne", "sw"):
                self.setCursor(QCursor(Qt.SizeBDiagCursor))
            elif mode in ("n", "s"):
                self.setCursor(QCursor(Qt.SizeVerCursor))
            elif mode in ("w", "e"):
                self.setCursor(QCursor(Qt.SizeHorCursor))
            elif mode == "move":
                self.setCursor(QCursor(Qt.SizeAllCursor))
            elif mode == "new":
                self.setCursor(QCursor(Qt.CrossCursor))
            else:
                self.setCursor(QCursor(Qt.ArrowCursor))
            return

        # Đang kéo thả
        dx = (pt.x() - self._drag_start_pos.x()) / max(1, cr.width())
        dy = (pt.y() - self._drag_start_pos.y()) / max(1, cr.height())
        orig_x, orig_y, orig_w, orig_h = self._drag_start_box

        if self._drag_mode == "move":
            new_x = max(0.0, min(1.0 - orig_w, orig_x + dx))
            new_y = max(0.0, min(1.0 - orig_h, orig_y + dy))
            self.box_x = new_x
            self.box_y = new_y
        elif self._drag_mode == "new":
            nx = (pt.x() - cr.x()) / max(1, cr.width())
            ny = (pt.y() - cr.y()) / max(1, cr.height())
            x1, x2 = min(self.box_x, nx), max(self.box_x, nx)
            y1, y2 = min(self.box_y, ny), max(self.box_y, ny)
            self.box_x = max(0.0, min(0.95, x1))
            self.box_y = max(0.0, min(0.95, y1))
            self.box_w = max(0.05, min(1.0 - self.box_x, x2 - x1))
            self.box_h = max(0.05, min(1.0 - self.box_y, y2 - y1))
        elif self._drag_mode == "se":
            self.box_w = max(0.05, min(1.0 - orig_x, orig_w + dx))
            self.box_h = max(0.05, min(1.0 - orig_y, orig_h + dy))
        elif self._drag_mode == "sw":
            new_x = max(0.0, min(orig_x + orig_w - 0.05, orig_x + dx))
            self.box_w = (orig_x + orig_w) - new_x
            self.box_x = new_x
            self.box_h = max(0.05, min(1.0 - orig_y, orig_h + dy))
        elif self._drag_mode == "ne":
            new_y = max(0.0, min(orig_y + orig_h - 0.05, orig_y + dy))
            self.box_h = (orig_y + orig_h) - new_y
            self.box_y = new_y
            self.box_w = max(0.05, min(1.0 - orig_x, orig_w + dx))
        elif self._drag_mode == "nw":
            new_x = max(0.0, min(orig_x + orig_w - 0.05, orig_x + dx))
            new_y = max(0.0, min(orig_y + orig_h - 0.05, orig_y + dy))
            self.box_w = (orig_x + orig_w) - new_x
            self.box_h = (orig_y + orig_h) - new_y
            self.box_x = new_x
            self.box_y = new_y
        elif self._drag_mode == "s":
            self.box_h = max(0.05, min(1.0 - orig_y, orig_h + dy))
        elif self._drag_mode == "n":
            new_y = max(0.0, min(orig_y + orig_h - 0.05, orig_y + dy))
            self.box_h = (orig_y + orig_h) - new_y
            self.box_y = new_y
        elif self._drag_mode == "e":
            self.box_w = max(0.05, min(1.0 - orig_x, orig_w + dx))
        elif self._drag_mode == "w":
            new_x = max(0.0, min(orig_x + orig_w - 0.05, orig_x + dx))
            self.box_w = (orig_x + orig_w) - new_x
            self.box_x = new_x

        self.box_changed.emit(self.box_x, self.box_y, self.box_w, self.box_h)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_mode = None
        self.setCursor(QCursor(Qt.ArrowCursor))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        self._canvas_rect = self._calc_canvas_rect()
        cr = self._canvas_rect

        # 1. Vẽ nền Canvas mô phỏng video
        bg_grad = QLinearGradient(cr.topLeft(), cr.bottomLeft())
        bg_grad.setColorAt(0.0, QColor("#12141c"))
        bg_grad.setColorAt(1.0, QColor("#1a1f2c"))
        painter.fillRect(cr, bg_grad)

        # Viền canvas & nhãn tỉ lệ
        painter.setPen(QPen(QColor("#00e5ff"), 1.5))
        painter.drawRect(cr)

        ratio_label = f"Tỉ lệ khung hình: {int(self.ratio_w)}:{int(self.ratio_h)} (Kéo thả vùng chọn sub bên dưới)"
        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#b0bec5"))
        painter.drawText(QRect(0, 2, self.width(), 16), Qt.AlignCenter, ratio_label)

        # Đường chỉ dẫn căn giữa & quy tắc 1/3 (Rule of thirds)
        painter.setPen(QPen(QColor(255, 255, 255, 25), 1, Qt.DashLine))
        painter.drawLine(cr.x() + cr.width() // 2, cr.top(), cr.x() + cr.width() // 2, cr.bottom())
        painter.drawLine(cr.left(), cr.y() + int(cr.height() * 0.70), cr.right(), cr.y() + int(cr.height() * 0.70))
        painter.drawLine(cr.left(), cr.y() + int(cr.height() * 0.90), cr.right(), cr.y() + int(cr.height() * 0.90))

        # 2. Vẽ Bounding Box vùng hiển thị Subtitle
        box_r = self._box_to_pixel_rect()

        # Nền vùng chọn (hơi phát sáng cyan mờ)
        painter.fillRect(box_r, QColor(0, 200, 255, 35))

        # Viền vùng chọn
        box_pen = QPen(QColor("#00e5ff"), 2, Qt.DashLine)
        painter.setPen(box_pen)
        painter.drawRect(box_r)

        # 3. Vẽ chữ phụ đề xem trước (Text Preview with Font, Color, Outline)
        painter.save()
        painter.setClipRect(box_r)

        preview_font = QFont(self.font_family, max(8, min(24, int(self.font_size * cr.height() / 450))))
        preview_font.setBold(self.is_bold)
        preview_font.setItalic(self.is_italic)
        painter.setFont(preview_font)

        # Vẽ outline bằng QPainterPath
        fm = QFontMetrics(preview_font)
        lines = self.sample_text.split("\n")
        total_text_h = len(lines) * fm.lineSpacing()
        start_y = box_r.bottom() - total_text_h - 4  # Bottom-aligned inside box

        for idx, line in enumerate(lines):
            line_w = fm.horizontalAdvance(line)
            line_x = box_r.left() + (box_r.width() - line_w) // 2
            line_y = start_y + idx * fm.lineSpacing() + fm.ascent()

            path = QPainterPath()
            path.addText(line_x, line_y, preview_font, line)

            # Vẽ viền chữ
            if self.outline_width > 0:
                outline_pen = QPen(QColor(self.outline_color), max(1.5, self.outline_width * 1.2))
                painter.strokePath(path, outline_pen)

            # Vẽ ruột chữ
            painter.fillPath(path, QBrush(QColor(self.font_color)))

        painter.restore()

        # 4. Vẽ 8 núm điều khiển (Resize Handles)
        handles = self._get_handles(box_r)
        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.setBrush(QBrush(QColor("#00bcd4")))
        for hr in handles.values():
            painter.drawRect(hr)

        # 5. Thông tin tọa độ ở góc dưới
        coord_str = (
            f"Vị trí: Trái {self.box_x*100:.1f}% | Đáy {(1.0-(self.box_y+self.box_h))*100:.1f}% "
            f"| Rộng {self.box_w*100:.1f}% | Cao {self.box_h*100:.1f}%"
        )
        painter.setFont(QFont("Arial", 8))
        painter.setPen(QColor("#90caf9"))
        painter.drawText(QRect(0, self.height() - 18, self.width(), 16), Qt.AlignCenter, coord_str)


class SubtitleBoxSelectorWidget(QWidget):
    """Widget bao bọc hoàn chỉnh gồm Canvas chọn vùng sub + nút đặt lại mặc định + thông số."""

    box_changed = Signal(float, float, float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Canvas
        self.canvas = SubtitleBoxCanvas(self)
        self.canvas.box_changed.connect(self._on_box_changed)
        layout.addWidget(self.canvas, 1)

        # Hàng nút điều khiển nhanh
        btn_bar = QHBoxLayout()
        self.lbl_info = QLabel("Mặc định: 2 bên 15%, cao 20%, cách đáy 10%")
        self.lbl_info.setStyleSheet("color: #888; font-size: 11px;")

        self.btn_reset = QPushButton("↺ Đặt lại chuẩn (15% - 20% - 10%)")
        self.btn_reset.setToolTip("Khôi phục vị trí phụ đề chuẩn mực cho video")
        self.btn_reset.clicked.connect(self.canvas.reset_default_box)

        btn_bar.addWidget(self.lbl_info, 1)
        btn_bar.addWidget(self.btn_reset)
        layout.addLayout(btn_bar)

    def _on_box_changed(self, x: float, y: float, w: float, h: float) -> None:
        self.box_changed.emit(x, y, w, h)

    def set_aspect_ratio(self, ratio_str: str = "16:9", width: int = 1920, height: int = 1080) -> None:
        self.canvas.set_aspect_ratio(ratio_str, width, height)

    def set_box(self, x: float, y: float, w: float, h: float) -> None:
        self.canvas.set_box(x, y, w, h)

    def set_style(
        self,
        font_family: str,
        font_size: int,
        font_color: str,
        outline_color: str,
        outline_width: float,
        bold: bool,
        italic: bool
    ) -> None:
        self.canvas.set_style(font_family, font_size, font_color, outline_color, outline_width, bold, italic)

    def get_box(self) -> Tuple[float, float, float, float]:
        return (self.canvas.box_x, self.canvas.box_y, self.canvas.box_w, self.canvas.box_h)
