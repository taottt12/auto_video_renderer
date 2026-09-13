from __future__ import annotations

import math
import os
import random
from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import Signal, Qt, QRect, QTimer, QUrl
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPen, QBrush, QPixmap,
    QLinearGradient, QRadialGradient, QPainterPath
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QPushButton, QListWidget,
    QFileDialog, QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QLineEdit, QFormLayout, QScrollArea, QTextEdit, QColorDialog,
    QToolButton, QLabel, QAbstractItemView, QSplitter
)

from core.media_utils import AUDIO_EXTENSIONS
from ui.subtitle_widget import SubtitleBoxSelectorWidget


class LayoutPreviewWidget(QWidget):
    """Widget vẽ mô phỏng trực quan bố cục khung hình video xuất ra trong thời gian thực."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(260, 260)
        self.settings: Dict[str, Any] = {}
        self.cached_logo: QPixmap | None = None
        self.cached_logo_path: str = ""
        self.cached_watermark: QPixmap | None = None
        self.cached_watermark_path: str = ""
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._on_anim_tick)
        self._anim_t = 0.0

    def _on_anim_tick(self) -> None:
        self._anim_t += 0.033
        self.update()

    def update_settings(self, settings: Dict[str, Any]) -> None:
        self.settings = dict(settings)
        logo_file = str(self.settings.get("logo_file", "")).strip()
        if logo_file != self.cached_logo_path:
            self.cached_logo_path = logo_file
            self.cached_logo = QPixmap(logo_file) if (logo_file and os.path.exists(logo_file)) else None

        wm_file = str(self.settings.get("watermark_file", "")).strip()
        if wm_file != self.cached_watermark_path:
            self.cached_watermark_path = wm_file
            self.cached_watermark = QPixmap(wm_file) if (wm_file and os.path.exists(wm_file)) else None

        text_cfg = self.settings.get("text_overlay", {}) or {}
        if text_cfg.get("enabled") and text_cfg.get("moving_enabled") and str(text_cfg.get("content", "")).strip():
            if not self._anim_timer.isActive():
                self._anim_timer.start(33)
        else:
            if self._anim_timer.isActive():
                self._anim_timer.stop()

        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        export = self.settings.get("export", {})
        ratio_w = int(export.get("width", 1920))
        ratio_h = int(export.get("height", 1080))
        if ratio_w <= 0 or ratio_h <= 0:
            ratio_w, ratio_h = 16, 9

        w_avail = self.width() - 24
        h_avail = self.height() - 36
        scale = min(w_avail / ratio_w, h_avail / ratio_h)
        canvas_w = max(100, int(ratio_w * scale))
        canvas_h = max(100, int(ratio_h * scale))
        canvas_x = (self.width() - canvas_w) // 2
        canvas_y = 28 + (h_avail - canvas_h) // 2
        canvas_rect = QRect(canvas_x, canvas_y, canvas_w, canvas_h)

        # 1. Vẽ nền Canvas
        painter.fillRect(canvas_rect, QColor("#1a1a24"))

        # Đường lưới căn giữa
        painter.setPen(QPen(QColor(255, 255, 255, 20), 1, Qt.DashLine))
        painter.drawLine(canvas_x + canvas_w // 2, canvas_y, canvas_x + canvas_w // 2, canvas_y + canvas_h)
        painter.drawLine(canvas_x, canvas_y + canvas_h // 2, canvas_x + canvas_w, canvas_y + canvas_h // 2)

        # 2. Watermark
        if self.settings.get("watermark_enabled"):
            wm_opacity = float(self.settings.get("watermark_opacity", 0.2))
            wm_scale = float(self.settings.get("watermark_scale", 1.0))
            if self.cached_watermark and not self.cached_watermark.isNull():
                painter.setOpacity(max(0.0, min(1.0, wm_opacity)))
                target_wm_w = int(canvas_w * wm_scale)
                target_wm_h = int(canvas_h * wm_scale)
                scaled_wm = self.cached_watermark.scaled(target_wm_w, target_wm_h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                wm_x = canvas_x + (canvas_w - scaled_wm.width()) // 2
                wm_y = canvas_y + (canvas_h - scaled_wm.height()) // 2
                painter.setClipRect(canvas_rect)
                painter.drawPixmap(wm_x, wm_y, scaled_wm)
                painter.setClipping(False)
                painter.setOpacity(1.0)
            else:
                # Mock watermark text
                painter.setOpacity(max(0.05, min(0.3, wm_opacity)))
                painter.setFont(QFont("Arial", max(10, int(canvas_w * 0.07)), QFont.Bold))
                painter.setPen(QColor("#ffffff"))
                painter.drawText(canvas_rect, Qt.AlignCenter, "WATERMARK")
                painter.setOpacity(1.0)

        # 3. Logo
        if self.settings.get("logo_enabled"):
            logo_scale = float(self.settings.get("logo_scale", 0.12))
            lg_w = max(16, int(canvas_w * logo_scale))
            pos = str(self.settings.get("logo_position", "top_right"))
            norm_factor = canvas_w / max(1, ratio_w)
            mx = int(int(self.settings.get("logo_margin_x", 30)) * norm_factor)
            my = int(int(self.settings.get("logo_margin_y", 30)) * norm_factor)

            if self.cached_logo and not self.cached_logo.isNull():
                scaled_logo = self.cached_logo.scaledToWidth(lg_w, Qt.SmoothTransformation)
                lg_h = scaled_logo.height()
            else:
                scaled_logo = None
                lg_h = lg_w

            if "left" in pos:
                lx = canvas_x + mx
            elif "center" in pos and ("left" not in pos and "right" not in pos):
                lx = canvas_x + (canvas_w - lg_w) // 2
            else:
                lx = canvas_x + canvas_w - lg_w - mx

            if "top" in pos:
                ly = canvas_y + my
            elif "bottom" in pos:
                ly = canvas_y + canvas_h - lg_h - my
            else:
                ly = canvas_y + (canvas_h - lg_h) // 2

            if scaled_logo:
                painter.drawPixmap(lx, ly, scaled_logo)
            else:
                painter.setBrush(QColor("#e91e63"))
                painter.setPen(QColor("#ffffff"))
                painter.drawRoundedRect(lx, ly, lg_w, lg_h, 4, 4)
                painter.setFont(QFont("Arial", max(6, int(lg_w * 0.22)), QFont.Bold))
                painter.drawText(QRect(lx, ly, lg_w, lg_h), Qt.AlignCenter, "LOGO")

        # 4. Text Overlay
        text_cfg = self.settings.get("text_overlay", {}) or {}
        text_content = str(text_cfg.get("content", "")).strip()
        if text_cfg.get("enabled") and text_content:
            font_size = int(text_cfg.get("font_size", 48))
            norm_factor = canvas_h / max(1, ratio_h)
            draw_font_size = max(7, int(font_size * norm_factor))
            painter.setFont(QFont("Arial", draw_font_size, QFont.Bold))

            font_color_str = str(text_cfg.get("font_color", "#FFFFFF")).strip() or "#FFFFFF"
            text_color = QColor(font_color_str)

            fm = painter.fontMetrics()
            lines = text_content.splitlines()
            max_line_w = max((fm.horizontalAdvance(l) for l in lines), default=0)
            total_text_h = fm.lineSpacing() * len(lines)
            pad_x = 8
            pad_y = 4
            box_w = max_line_w + pad_x * 2
            box_h = total_text_h + pad_y * 2

            pos = str(text_cfg.get("position", "bottom_center"))
            tmx = int(int(text_cfg.get("margin_x", 40)) * norm_factor)
            tmy = int(int(text_cfg.get("margin_y", 80)) * norm_factor)

            if text_cfg.get("moving_enabled"):
                span_x = canvas_w - box_w - tmx * 2
                span_y = canvas_h - box_h - tmy * 2
                if span_x > 0:
                    pos_x = abs((self._anim_t * 60) % (2 * span_x) - span_x)
                    tx = canvas_x + tmx + int(pos_x)
                else:
                    tx = canvas_x + tmx

                if span_y > 0:
                    pos_y = abs((self._anim_t * 38) % (2 * span_y) - span_y)
                    ty = canvas_y + tmy + int(pos_y)
                else:
                    ty = canvas_y + tmy
            else:
                if "left" in pos:
                    tx = canvas_x + tmx
                elif "right" in pos:
                    tx = canvas_x + canvas_w - box_w - tmx
                else:
                    tx = canvas_x + (canvas_w - box_w) // 2

                if "top" in pos:
                    ty = canvas_y + tmy
                elif "bottom" in pos:
                    ty = canvas_y + canvas_h - box_h - tmy
                else:
                    ty = canvas_y + (canvas_h - box_h) // 2

            if text_cfg.get("box_enabled", True):
                box_op = float(text_cfg.get("box_opacity", 0.45))
                painter.setBrush(QColor(0, 0, 0, int(box_op * 255)))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(tx, ty, box_w, box_h, 4, 4)

            painter.setPen(text_color)
            for idx, line in enumerate(lines):
                line_y = ty + pad_y + fm.ascent() + idx * fm.lineSpacing()
                painter.drawText(tx + pad_x, line_y, line)

        # 4b. Phụ đề Video (Subtitle Overlay Preview)
        sub_cfg = self.settings.get("subtitle", {}) or {}
        if sub_cfg.get("enabled"):
            sub_x = float(sub_cfg.get("box_x", 0.15))
            sub_y = float(sub_cfg.get("box_y", 0.70))
            sub_w = float(sub_cfg.get("box_w", 0.70))
            sub_h = float(sub_cfg.get("box_h", 0.20))
            s_rect = QRect(
                canvas_x + int(sub_x * canvas_w),
                canvas_y + int(sub_y * canvas_h),
                max(20, int(sub_w * canvas_w)),
                max(15, int(sub_h * canvas_h))
            )
            painter.fillRect(s_rect, QColor(0, 200, 255, 30))
            painter.setPen(QPen(QColor("#00e5ff"), 1, Qt.DashLine))
            painter.drawRect(s_rect)

            sub_font_fam = str(sub_cfg.get("font_family", "Arial") or "Arial")
            sub_font_size = max(7, int(int(sub_cfg.get("font_size", 38)) * (canvas_h / max(1, ratio_h))))
            sub_font = QFont(sub_font_fam, sub_font_size)
            sub_font.setBold(bool(sub_cfg.get("bold", True)))
            sub_font.setItalic(bool(sub_cfg.get("italic", False)))
            painter.setFont(sub_font)

            s_text = "Phụ đề mẫu (Subtitle)"
            sfm = painter.fontMetrics()
            st_w = sfm.horizontalAdvance(s_text)
            st_x = s_rect.left() + (s_rect.width() - st_w) // 2
            st_y = s_rect.bottom() - 4

            spath = QPainterPath()
            spath.addText(st_x, st_y, sub_font, s_text)
            out_w = float(sub_cfg.get("outline_width", 2.0) or 2.0)
            if out_w > 0:
                painter.strokePath(spath, QPen(QColor(str(sub_cfg.get("outline_color", "#000000"))), max(1.0, out_w)))
            painter.fillPath(spath, QBrush(QColor(str(sub_cfg.get("font_color", "#FFFFFF")))))

        # 5. Khung viền và thông số tỉ lệ
        painter.setPen(QPen(QColor("#00bcd4"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(canvas_rect)

        ratio_tag = export.get("ratio", f"{ratio_w}:{ratio_h}")
        painter.setPen(QColor("#cfd8dc"))
        painter.setFont(QFont("Arial", 9, QFont.Bold))
        painter.drawText(QRect(0, 4, self.width(), 20), Qt.AlignCenter, f"Khung hình xuất: {ratio_tag} ({ratio_w} x {ratio_h})")


class ImageMotionDemoWidget(QWidget):
    """Widget demo trực quan chuyển động Ken Burns cho Ảnh (Pan & Zoom)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(115)
        self.motion_mode = "auto_light"
        self._anim_t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(40)  # ~25 FPS

    def _on_tick(self) -> None:
        self._anim_t += 0.04
        self.update()

    def set_motion(self, mode: str) -> None:
        self.motion_mode = mode or "auto_light"
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        w = self.width()
        h = self.height()

        box_w = min(w - 16, int((h - 26) * 16 / 9))
        box_h = int(box_w * 9 / 16)
        x0 = (w - box_w) // 2
        y0 = 4
        rect = QRect(x0, y0, box_w, box_h)

        painter.setClipRect(rect)

        # Tính toán ma trận Ken Burns (Pan & Zoom)
        painter.save()
        if self.motion_mode == "auto_light":
            # Pan ngang nhẹ & Zoom chậm
            zoom = 1.0 + 0.08 * math.sin(self._anim_t * 1.2)
            pan_x = 8 * math.cos(self._anim_t * 0.9)
            painter.translate(x0 + box_w // 2 + pan_x, y0 + box_h // 2)
            painter.scale(zoom, zoom)
            painter.translate(-(x0 + box_w // 2), -(y0 + box_h // 2))
        elif self.motion_mode == "auto_rich":
            # Chuyển động đa hướng chéo & Zoom sâu
            zoom = 1.0 + 0.16 * math.sin(self._anim_t * 1.5)
            pan_x = 14 * math.sin(self._anim_t * 1.1)
            pan_y = 6 * math.cos(self._anim_t * 1.3)
            painter.translate(x0 + box_w // 2 + pan_x, y0 + box_h // 2 + pan_y)
            painter.scale(zoom, zoom)
            painter.translate(-(x0 + box_w // 2), -(y0 + box_h // 2))

        # Vẽ ảnh phong cảnh núi non
        grad = QLinearGradient(x0, y0, x0, y0 + box_h)
        grad.setColorAt(0.0, QColor("#1a2a6c"))
        grad.setColorAt(0.5, QColor("#b21f1f"))
        grad.setColorAt(1.0, QColor("#fdbb2d"))
        painter.fillRect(rect.adjusted(-20, -20, 20, 20), grad)

        # Mặt trời
        sun_grad = QRadialGradient(x0 + int(box_w * 0.7), y0 + int(box_h * 0.4), int(box_h * 0.3))
        sun_grad.setColorAt(0.0, QColor(255, 255, 220, 230))
        sun_grad.setColorAt(0.6, QColor(255, 180, 50, 100))
        sun_grad.setColorAt(1.0, QColor(255, 120, 0, 0))
        painter.fillRect(rect.adjusted(-20, -20, 20, 20), sun_grad)

        # Dãy núi
        m_path = QPainterPath()
        m_path.moveTo(x0 - 20, y0 + box_h + 20)
        m_path.lineTo(x0 - 20, y0 + int(box_h * 0.65))
        m_path.lineTo(x0 + int(box_w * 0.3), y0 + int(box_h * 0.45))
        m_path.lineTo(x0 + int(box_w * 0.55), y0 + int(box_h * 0.7))
        m_path.lineTo(x0 + int(box_w * 0.8), y0 + int(box_h * 0.5))
        m_path.lineTo(x0 + box_w + 20, y0 + int(box_h * 0.65))
        m_path.lineTo(x0 + box_w + 20, y0 + box_h + 20)
        m_path.closeSubpath()
        painter.fillPath(m_path, QColor("#1e1233"))

        painter.restore()
        painter.setClipping(False)

        # Viền
        painter.setPen(QPen(QColor("#444"), 1))
        painter.drawRect(rect)

        mode_text = {
            "auto_light": "Auto Light (Pan & Zoom nhẹ)",
            "auto_rich": "Auto Rich (Ken Burns đa hướng)",
            "none": "Tắt hiệu ứng (Ảnh tĩnh)",
        }.get(self.motion_mode, self.motion_mode)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#4fc3f7"))
        painter.drawText(QRect(0, y0 + box_h + 2, w, 18), Qt.AlignCenter, f"📸 {mode_text}")


class VideoEffectDemoWidget(QWidget):
    """Widget demo trực quan hiệu ứng & lớp phủ Video (Vignette, Grain, Color Boost...)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(115)
        self.video_effect_mode = "auto_cinematic"
        self._anim_t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(40)  # ~25 FPS

    def _on_tick(self) -> None:
        self._anim_t += 0.04
        self.update()

    def set_effect(self, mode: str) -> None:
        self.video_effect_mode = mode or "auto_cinematic"
        self.update()

    def set_effects(self, image_effect: str, video_effect: str) -> None:
        self.set_effect(video_effect)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        w = self.width()
        h = self.height()

        box_w = min(w - 16, int((h - 26) * 16 / 9))
        box_h = int(box_w * 9 / 16)
        x0 = (w - box_w) // 2
        y0 = 4
        rect = QRect(x0, y0, box_w, box_h)

        painter.setClipRect(rect)

        # Nền video mẫu
        grad = QLinearGradient(x0, y0, x0, y0 + box_h)
        if self.video_effect_mode == "color_boost":
            grad.setColorAt(0.0, QColor("#ff416c"))
            grad.setColorAt(0.4, QColor("#ff4b2b"))
            grad.setColorAt(0.7, QColor("#ffb347"))
            grad.setColorAt(1.0, QColor("#2b5876"))
        else:
            grad.setColorAt(0.0, QColor("#3a1c71"))
            grad.setColorAt(0.4, QColor("#d76d77"))
            grad.setColorAt(0.7, QColor("#ffaf7b"))
            grad.setColorAt(1.0, QColor("#1e3c72"))
        painter.fillRect(rect, grad)

        # Slow push camera
        if self.video_effect_mode == "slow_zoom":
            zoom = 1.0 + 0.06 * (math.sin(self._anim_t * 0.8) + 1.0) * 0.5
            painter.translate(x0 + box_w // 2, y0 + box_h // 2)
            painter.scale(zoom, zoom)
            painter.translate(-(x0 + box_w // 2), -(y0 + box_h // 2))

        # Mặt trời
        sun_grad = QRadialGradient(x0 + int(box_w * 0.65), y0 + int(box_h * 0.45), int(box_h * 0.25))
        sun_grad.setColorAt(0.0, QColor(255, 255, 220, 230))
        sun_grad.setColorAt(0.5, QColor(255, 200, 100, 140))
        sun_grad.setColorAt(1.0, QColor(255, 150, 50, 0))
        painter.fillRect(rect, sun_grad)

        # Dãy núi
        m_path = QPainterPath()
        m_path.moveTo(x0, y0 + box_h)
        m_path.lineTo(x0, y0 + int(box_h * 0.65))
        m_path.lineTo(x0 + int(box_w * 0.25), y0 + int(box_h * 0.48))
        m_path.lineTo(x0 + int(box_w * 0.5), y0 + int(box_h * 0.68))
        m_path.lineTo(x0 + int(box_w * 0.75), y0 + int(box_h * 0.52))
        m_path.lineTo(x0 + box_w, y0 + int(box_h * 0.62))
        m_path.lineTo(x0 + box_w, y0 + box_h)
        m_path.closeSubpath()
        m_color = QColor("#1e1233") if self.video_effect_mode != "color_boost" else QColor("#15002a")
        painter.fillPath(m_path, m_color)

        if self.video_effect_mode == "slow_zoom":
            painter.resetTransform()

        # Áp dụng hiệu ứng
        if self.video_effect_mode in ["vignette", "auto_cinematic"]:
            vig_op = 0.55 if self.video_effect_mode == "vignette" else 0.35
            vig_grad = QRadialGradient(x0 + box_w // 2, y0 + box_h // 2, int(max(box_w, box_h) * 0.62))
            vig_grad.setColorAt(0.0, QColor(0, 0, 0, 0))
            vig_grad.setColorAt(0.5, QColor(0, 0, 0, 20))
            vig_grad.setColorAt(0.85, QColor(0, 0, 0, int(180 * vig_op)))
            vig_grad.setColorAt(1.0, QColor(0, 0, 0, int(250 * vig_op)))
            painter.fillRect(rect, vig_grad)

        if self.video_effect_mode == "bubbles":
            painter.setPen(Qt.NoPen)
            for i in range(14):
                bx = x0 + int(box_w * ((i * 0.077 + 0.04) % 1.0) + math.sin(self._anim_t * 1.8 + i) * 6)
                by = y0 + int((box_h + 20 - (self._anim_t * (25 + i * 4) + i * 20)) % (box_h + 20)) - 10
                br = 5 + (i % 5) * 2
                b_grad = QRadialGradient(bx - br * 0.3, by - br * 0.3, br)
                b_grad.setColorAt(0.0, QColor(220, 240, 255, 120))
                b_grad.setColorAt(0.7, QColor(130, 190, 250, 40))
                b_grad.setColorAt(0.95, QColor(190, 225, 255, 190))
                b_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
                painter.setBrush(QBrush(b_grad))
                painter.drawEllipse(QPoint(bx, by), br, br)
                painter.setBrush(QColor(255, 255, 255, 220))
                painter.drawEllipse(QPoint(int(bx - br * 0.35), int(by - br * 0.35)), max(1, br // 4), max(1, br // 5))

        if self.video_effect_mode in ["dew_particles", "dew", "snow"]:
            painter.setPen(Qt.NoPen)
            for i in range(28):
                dx = x0 + int((box_w * (i * 0.038) + math.sin(self._anim_t * 1.5 + i) * 8) % box_w)
                dy = y0 + int((self._anim_t * (18 + (i % 5) * 6) + i * 15) % box_h)
                twinkle = 0.5 + 0.5 * math.sin(self._anim_t * 3.0 + i)
                dr = 2 + int(twinkle * 2)
                alpha = int(140 + 115 * twinkle)
                d_color = QColor(180, 235, 255, alpha) if i % 2 == 0 else QColor(255, 235, 180, alpha)
                painter.setBrush(d_color)
                painter.drawEllipse(QPoint(dx, dy), dr, dr)

        if self.video_effect_mode in ["feathers", "feather"]:
            for i in range(8):
                fx = x0 + int((box_w * (i * 0.13 + 0.08) + math.sin(self._anim_t * 1.4 + i) * 16) % box_w)
                fy = y0 + int((self._anim_t * (14 + i * 4) + i * 35) % (box_h + 30)) - 15
                f_angle = math.sin(self._anim_t * 1.2 + i) * 35
                painter.save()
                painter.translate(fx, fy)
                painter.rotate(f_angle)
                f_path = QPainterPath()
                f_len = 16 + (i % 3) * 4
                f_w = f_len * 0.35
                f_path.moveTo(0, -f_len // 2)
                f_path.cubicTo(f_w, -f_len // 4, f_w * 0.8, f_len // 4, 0, f_len // 2)
                f_path.cubicTo(-f_w * 0.8, f_len // 4, -f_w, -f_len // 4, 0, -f_len // 2)
                painter.setBrush(QColor(255, 255, 255, 180))
                painter.setPen(Qt.NoPen)
                painter.drawPath(f_path)
                painter.setPen(QPen(QColor(255, 255, 255, 220), 1))
                painter.drawLine(0, -f_len // 2, 0, f_len // 2)
                painter.restore()

        if self.video_effect_mode in ["bokeh", "sparkles"]:
            painter.setPen(Qt.NoPen)
            for i in range(8):
                bx = x0 + int((box_w * (i * 0.13 + 0.08) + math.cos(self._anim_t * 0.6 + i) * 10) % box_w)
                by = y0 + int((box_h * (i * 0.12 + 0.1) + math.sin(self._anim_t * 0.7 + i) * 8) % box_h)
                pulse = 0.5 + 0.5 * math.sin(self._anim_t * 1.5 + i)
                br = 12 + int(pulse * 10)
                b_grad = QRadialGradient(bx, by, br)
                col = QColor(255, 220, 150, int(90 * pulse)) if i % 2 == 0 else QColor(200, 230, 255, int(80 * pulse))
                b_grad.setColorAt(0.0, col)
                b_grad.setColorAt(0.8, QColor(col.red(), col.green(), col.blue(), int(col.alpha() * 0.4)))
                b_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
                painter.setBrush(QBrush(b_grad))
                painter.drawEllipse(QPoint(bx, by), br, br)

        if self.video_effect_mode == "rain":
            painter.setPen(QPen(QColor(200, 225, 255, 160), 1))
            for i in range(35):
                rx = x0 + int((box_w * (i * 0.03) + self._anim_t * -40) % box_w)
                ry = y0 + int((self._anim_t * 160 + i * 20) % box_h)
                painter.drawLine(rx, ry, rx - 3, ry + 12)

        if self.video_effect_mode == "custom":
            painter.fillRect(rect, QColor(0, 0, 0, 50))
            painter.setFont(QFont("Arial", 8, QFont.Bold))
            painter.setPen(QColor("#a5d6a7"))
            painter.drawText(rect, Qt.AlignCenter, "📁 Video Layer Mask tùy chọn")

        if self.video_effect_mode == "film_grain":
            painter.setPen(QColor(255, 255, 255, 40))
            rng = random.Random(int(self._anim_t * 18))
            for _ in range(100):
                gx = x0 + rng.randint(0, box_w - 1)
                gy = y0 + rng.randint(0, box_h - 1)
                painter.drawPoint(gx, gy)
            painter.fillRect(rect, QColor(255, 210, 150, 16))

        painter.setClipping(False)

        # Viền
        painter.setPen(QPen(QColor("#444"), 1))
        painter.drawRect(rect)

        fx_desc = {
            "bubbles": "Bong bóng bay lên (Bubbles)",
            "dew_particles": "Hạt sương / Tuyết (Dew & Snow)",
            "feathers": "Lông vũ rơi chao liệng (Feathers)",
            "bokeh": "Đốm sáng lung linh (Bokeh)",
            "rain": "Mưa rơi (Rain Drops)",
            "film_grain": "Film Grain (Hạt phim cổ điển)",
            "auto_cinematic": "Auto Cinematic (Vignette + Tăng màu)",
            "vignette": "Vignette (Viền tối góc)",
            "color_boost": "Color Boost (Màu rực rỡ)",
            "slow_zoom": "Slow Push (Zoom đẩy chậm)",
            "custom": "Video Layer tùy chọn từ máy",
            "none": "Tắt hiệu ứng video",
        }.get(self.video_effect_mode, self.video_effect_mode)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#81c784"))
        painter.drawText(QRect(0, y0 + box_h + 2, w, 18), Qt.AlignCenter, f"🎬 {fx_desc}")


class TransitionDemoWidget(QWidget):
    """Widget demo trực quan hiệu ứng chuyển cảnh (Transitions: Crossfade, Wipe, Cut)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(115)
        self.transition_mode = "auto_light"
        self._anim_t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(40)  # ~25 FPS

    def _on_tick(self) -> None:
        self._anim_t += 0.04
        self.update()

    def set_transition(self, mode: str) -> None:
        self.transition_mode = mode or "auto_light"
        self.update()

    def _draw_scene_a(self, painter: QPainter, rect: QRect) -> None:
        """Cảnh A: Ban ngày / Trời xanh / Đồi xanh."""
        grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        grad.setColorAt(0.0, QColor("#00c6ff"))
        grad.setColorAt(1.0, QColor("#0072ff"))
        painter.fillRect(rect, grad)

        # Mặt trời vàng
        sun_grad = QRadialGradient(rect.left() + int(rect.width() * 0.25), rect.top() + int(rect.height() * 0.35), int(rect.height() * 0.22))
        sun_grad.setColorAt(0.0, QColor(255, 255, 200, 230))
        sun_grad.setColorAt(1.0, QColor(255, 220, 0, 0))
        painter.fillRect(rect, sun_grad)

        # Ngọn đồi xanh
        h_path = QPainterPath()
        h_path.moveTo(rect.left(), rect.bottom())
        h_path.quadTo(rect.left() + rect.width() * 0.4, rect.top() + rect.height() * 0.55, rect.right(), rect.bottom() - 10)
        h_path.lineTo(rect.right(), rect.bottom())
        h_path.closeSubpath()
        painter.fillPath(h_path, QColor("#11998e"))

    def _draw_scene_b(self, painter: QPainter, rect: QRect) -> None:
        """Cảnh B: Hoàng hôn tím hồng / Núi đá."""
        grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        grad.setColorAt(0.0, QColor("#654ea3"))
        grad.setColorAt(1.0, QColor("#eaafc8"))
        painter.fillRect(rect, grad)

        # Mặt trăng / Ánh hồng
        moon_grad = QRadialGradient(rect.left() + int(rect.width() * 0.75), rect.top() + int(rect.height() * 0.35), int(rect.height() * 0.22))
        moon_grad.setColorAt(0.0, QColor(255, 230, 230, 230))
        moon_grad.setColorAt(1.0, QColor(255, 100, 150, 0))
        painter.fillRect(rect, moon_grad)

        # Dãy núi tím sẫm
        m_path = QPainterPath()
        m_path.moveTo(rect.left(), rect.bottom())
        m_path.lineTo(rect.left() + int(rect.width() * 0.35), rect.top() + int(rect.height() * 0.5))
        m_path.lineTo(rect.left() + int(rect.width() * 0.65), rect.top() + int(rect.height() * 0.7))
        m_path.lineTo(rect.right(), rect.top() + int(rect.height() * 0.45))
        m_path.lineTo(rect.right(), rect.bottom())
        m_path.closeSubpath()
        painter.fillPath(m_path, QColor("#2c1654"))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        w = self.width()
        h = self.height()

        box_w = min(w - 16, int((h - 26) * 16 / 9))
        box_h = int(box_w * 9 / 16)
        x0 = (w - box_w) // 2
        y0 = 4
        rect = QRect(x0, y0, box_w, box_h)

        painter.setClipRect(rect)

        # Chu kỳ chuyển cảnh: 3.2 giây
        period = 3.2
        t = self._anim_t % period

        if t < 1.0:
            self._draw_scene_a(painter, rect)
        elif t < 1.8:
            p = (t - 1.0) / 0.8
            self._render_transition(painter, rect, from_a_to_b=True, progress=p)
        elif t < 2.4:
            self._draw_scene_b(painter, rect)
        else:
            p = (t - 2.4) / 0.8
            self._render_transition(painter, rect, from_a_to_b=False, progress=p)

        painter.setClipping(False)

        # Viền
        painter.setPen(QPen(QColor("#444"), 1))
        painter.drawRect(rect)

        trans_text = {
            "auto_light": "Auto Light (Dissolve / Fade mượt)",
            "auto_rich": "Auto Rich (Wipe, Slide, Fade)",
            "none": "Cut trực tiếp (Tắt chuyển cảnh)",
        }.get(self.transition_mode, self.transition_mode)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#ffb74d"))
        painter.drawText(QRect(0, y0 + box_h + 2, w, 18), Qt.AlignCenter, f"🔄 {trans_text}")

    def _render_transition(self, painter: QPainter, rect: QRect, from_a_to_b: bool, progress: float) -> None:
        if self.transition_mode == "none":
            if progress < 0.5:
                if from_a_to_b:
                    self._draw_scene_a(painter, rect)
                else:
                    self._draw_scene_b(painter, rect)
            else:
                if from_a_to_b:
                    self._draw_scene_b(painter, rect)
                else:
                    self._draw_scene_a(painter, rect)
            return

        if self.transition_mode == "auto_rich":
            if from_a_to_b:
                self._draw_scene_a(painter, rect)
            else:
                self._draw_scene_b(painter, rect)

            wipe_w = int(rect.width() * progress)
            if wipe_w > 0:
                clip = QRect(rect.left(), rect.top(), wipe_w, rect.height())
                painter.save()
                painter.setClipRect(clip)
                if from_a_to_b:
                    self._draw_scene_b(painter, rect)
                else:
                    self._draw_scene_a(painter, rect)
                painter.setPen(QPen(QColor(255, 255, 255, 180), 2))
                painter.drawLine(rect.left() + wipe_w, rect.top(), rect.left() + wipe_w, rect.bottom())
                painter.restore()
        else:
            if from_a_to_b:
                self._draw_scene_a(painter, rect)
            else:
                self._draw_scene_b(painter, rect)

            painter.save()
            painter.setOpacity(min(1.0, max(0.0, progress)))
            if from_a_to_b:
                self._draw_scene_b(painter, rect)
            else:
                self._draw_scene_a(painter, rect)
            painter.restore()


EffectDemoWidget = VideoEffectDemoWidget


class CollapsibleBox(QWidget):
    def __init__(self, title: str, content: QWidget, collapsed: bool = True) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toggle = QToolButton(text=title, checkable=True, checked=not collapsed)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.DownArrow if not collapsed else Qt.RightArrow)
        self.toggle.clicked.connect(self._toggle)
        self.content = content
        self.content.setVisible(not collapsed)
        layout.addWidget(self.toggle)
        layout.addWidget(self.content)

    def _toggle(self) -> None:
        opened = self.toggle.isChecked()
        self.toggle.setArrowType(Qt.DownArrow if opened else Qt.RightArrow)
        self.content.setVisible(opened)


class SettingTab(QWidget):
    settings_changed = Signal(dict)

    def __init__(self, settings: Dict[str, Any]) -> None:
        super().__init__()
        self.settings = settings
        self._lock_emit = False
        self._preview_player = QMediaPlayer(self)
        self._preview_audio_output = QAudioOutput(self)
        self._preview_player.setAudioOutput(self._preview_audio_output)
        self._preview_player.playbackStateChanged.connect(self._on_preview_player_state_changed)
        self._build_ui()
        self.load_settings(settings)

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(12)

        # ==========================================
        # CỘT TRÁI: CÁC NHÓM THIẾT LẬP RENDER
        # ==========================================
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # Thanh nút lưu đầu trang
        save_bar = QHBoxLayout()
        self.save_btn = QPushButton("💾 Lưu cấu hình Render")
        self.save_btn.setStyleSheet(
            "background-color: #2e7d32; color: white; padding: 7px 20px; font-weight: bold; font-size: 13px; border-radius: 4px;"
        )
        self.save_btn.clicked.connect(self.save_settings_action)

        self.save_status_label = QLabel("Sẵn sàng")
        self.save_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        save_bar.addWidget(self.save_btn)
        save_bar.addWidget(self.save_status_label)
        save_bar.addStretch(1)
        left_layout.addLayout(save_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 8, 0)
        root.setSpacing(6)

        root.addWidget(CollapsibleBox("Intro / Outro / Logo / Watermark", self._build_extra_group(), collapsed=False))
        root.addWidget(CollapsibleBox("Text Overlay", self._build_text_group(), collapsed=True))
        root.addWidget(CollapsibleBox("Phụ đề Video (Subtitle)", self._build_subtitle_group(), collapsed=False))
        root.addWidget(CollapsibleBox("Nhạc nền (Background Music)", self._build_background_music_group(), collapsed=True))
        root.addWidget(CollapsibleBox("Audio quảng bá / chèn giữa video", self._build_promo_audio_group(), collapsed=True))
        root.addWidget(CollapsibleBox("Hiệu ứng thị giác & Chuyển cảnh", self._build_effect_audio_group(), collapsed=False))
        root.addWidget(CollapsibleBox("Export Setting", self._build_export_group(), collapsed=False))
        root.addWidget(CollapsibleBox("Hiệu năng / CPU / GPU", self._build_performance_group(), collapsed=True))

        root.addStretch(1)
        scroll.setWidget(container)
        left_layout.addWidget(scroll, 1)

        # ==========================================
        # CỘT PHẢI: KHUNG XEM TRƯỚC BỐ CỤC (LIVE PREVIEW)
        # ==========================================
        right_group = QGroupBox("Xem trước Bố cục Video (Live Layout Preview)")
        right_layout = QVBoxLayout(right_group)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(8)

        preview_bar = QHBoxLayout()
        preview_desc = QLabel("Mô phỏng vị trí thực tế của Logo, Watermark, Text:")
        preview_desc.setStyleSheet("color: #888; font-size: 11px;")
        self.refresh_preview_btn = QPushButton("🔄 Cập nhật Preview")
        self.refresh_preview_btn.clicked.connect(self._refresh_preview)
        preview_bar.addWidget(preview_desc, 1)
        preview_bar.addWidget(self.refresh_preview_btn)
        right_layout.addLayout(preview_bar)

        self.layout_preview = LayoutPreviewWidget()
        right_layout.addWidget(self.layout_preview, 1)

        outer.addWidget(left_widget, 6)
        outer.addWidget(right_group, 4)

    def _refresh_preview(self) -> None:
        settings = self.collect_settings()
        self.layout_preview.update_settings(settings)

    def save_settings_action(self) -> None:
        settings = self.collect_settings()
        self.settings = settings
        self.settings_changed.emit(settings)
        self.layout_preview.update_settings(settings)
        self.save_status_label.setText("✔ Đã lưu cấu hình!")
        QTimer.singleShot(2500, lambda: self.save_status_label.setText("Sẵn sàng"))

    def _build_extra_group(self) -> QGroupBox:
        group = QGroupBox()
        form = QFormLayout(group)
        self.intro_edit = self._file_row(form, "Intro", "Chọn intro", "Video (*.mp4 *.mov *.mkv)")
        self.outro_edit = self._file_row(form, "Outro", "Chọn outro", "Video (*.mp4 *.mov *.mkv)")

        self.logo_enabled = QCheckBox("Bật logo")
        self.logo_edit = self._file_row(form, "Logo", "Chọn logo", "Image (*.png *.jpg *.jpeg *.webp)")
        self.logo_position = self._position_combo()
        self.logo_scale = QDoubleSpinBox()
        self.logo_scale.setRange(0.03, 0.8)
        self.logo_scale.setSingleStep(0.01)
        self.logo_scale.setDecimals(2)
        self.logo_margin_x = QSpinBox()
        self.logo_margin_x.setRange(0, 1000)
        self.logo_margin_y = QSpinBox()
        self.logo_margin_y.setRange(0, 1000)
        form.addRow("Logo enabled", self.logo_enabled)
        form.addRow("Vị trí logo", self.logo_position)
        form.addRow("Scale logo", self.logo_scale)
        form.addRow("Logo margin X", self.logo_margin_x)
        form.addRow("Logo margin Y", self.logo_margin_y)

        self.watermark_enabled = QCheckBox("Bật watermark full màn hình")
        self.watermark_edit = self._file_row(form, "Watermark", "Chọn watermark", "Image (*.png *.jpg *.jpeg *.webp)")
        self.watermark_opacity = QDoubleSpinBox()
        self.watermark_opacity.setRange(0.01, 1.0)
        self.watermark_opacity.setSingleStep(0.05)
        self.watermark_opacity.setDecimals(2)
        self.watermark_scale = QDoubleSpinBox()
        self.watermark_scale.setRange(0.5, 3.0)
        self.watermark_scale.setSingleStep(0.05)
        self.watermark_scale.setDecimals(2)
        self.watermark_scale.setToolTip("1.0 = phủ kín khung hình. Tăng nếu muốn crop mạnh hơn.")
        form.addRow("Watermark enabled", self.watermark_enabled)
        form.addRow("Độ mờ watermark", self.watermark_opacity)
        form.addRow("Scale watermark", self.watermark_scale)

        self._connect_change_widgets(
            self.intro_edit, self.outro_edit, self.logo_enabled, self.logo_position,
            self.logo_scale, self.logo_margin_x, self.logo_margin_y,
            self.watermark_enabled, self.watermark_opacity, self.watermark_scale
        )
        return group

    def _build_text_group(self) -> QGroupBox:
        group = QGroupBox()
        form = QFormLayout(group)
        self.text_enabled = QCheckBox("Bật hiển thị Text Overlay khi render")
        self.text_content = QTextEdit()
        self.text_content.setPlaceholderText("Nhập text cần hiển thị trên video...")
        self.text_content.setMaximumHeight(80)
        self.text_font_size = QSpinBox()
        self.text_font_size.setRange(12, 160)
        self.text_font_size.setValue(48)
        self.text_position = self._position_combo()

        color_row = QHBoxLayout()
        self.text_font_color = QLineEdit("#FFFFFF")
        self.text_color_btn = QPushButton("Chọn màu")
        self.text_color_btn.clicked.connect(self.choose_text_color)
        self.text_color_preview = QLabel()
        self.text_color_preview.setFixedSize(26, 26)
        color_row.addWidget(self.text_font_color)
        color_row.addWidget(self.text_color_btn)
        color_row.addWidget(self.text_color_preview)

        self.text_margin_x = QSpinBox()
        self.text_margin_x.setRange(0, 500)
        self.text_margin_y = QSpinBox()
        self.text_margin_y.setRange(0, 500)
        self.text_box_enabled = QCheckBox("Bật nền mờ (Box) phía sau text")
        self.text_box_opacity = QDoubleSpinBox()
        self.text_box_opacity.setRange(0.0, 1.0)
        self.text_box_opacity.setSingleStep(0.05)
        self.text_box_opacity.setValue(0.45)

        self.text_moving_enabled = QCheckBox("Bật chữ chạy chuyển động quanh màn hình (Bouncing Text / Chống Reup)")

        form.addRow("Trạng thái", self.text_enabled)
        form.addRow("Nội dung text", self.text_content)
        form.addRow("Cỡ chữ", self.text_font_size)
        form.addRow("Vị trí text", self.text_position)
        form.addRow("Chuyển động", self.text_moving_enabled)
        form.addRow("Màu chữ", color_row)
        form.addRow("Margin X", self.text_margin_x)
        form.addRow("Margin Y", self.text_margin_y)
        form.addRow("Box nền", self.text_box_enabled)
        form.addRow("Độ mờ nền box", self.text_box_opacity)

        self._connect_change_widgets(
            self.text_enabled, self.text_content, self.text_font_size, self.text_position,
            self.text_moving_enabled, self.text_font_color, self.text_margin_x, self.text_margin_y,
            self.text_box_enabled, self.text_box_opacity
        )
        self.text_font_color.textChanged.connect(self._update_color_preview)
        return group

    def _build_subtitle_group(self) -> QGroupBox:
        group = QGroupBox()
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        form = QFormLayout()
        self.sub_enabled = QCheckBox("Bật chèn phụ đề vào video (Burn-in Subtitle)")
        self.sub_enabled.setStyleSheet("font-weight: bold; color: #00e5ff;")

        folder_row = QHBoxLayout()
        self.sub_folder_edit = QLineEdit()
        self.sub_folder_edit.setPlaceholderText("Để trống = tự động tìm file .srt cùng tên trong thư mục audio")
        self.sub_folder_btn = QPushButton("Chọn thư mục...")
        self.sub_folder_btn.clicked.connect(self._choose_sub_folder)
        folder_row.addWidget(self.sub_folder_edit, 1)
        folder_row.addWidget(self.sub_folder_btn)

        font_row = QHBoxLayout()
        self.sub_font_family = QComboBox()
        fonts = ["Arial", "Roboto", "Montserrat", "Segoe UI", "Tahoma", "Times New Roman", "Verdana", "UTM Alexander", "UTM Bebas"]
        self.sub_font_family.addItems(fonts)
        self.sub_font_family.setEditable(True)

        self.sub_font_size = QSpinBox()
        self.sub_font_size.setRange(12, 120)
        self.sub_font_size.setValue(38)
        self.sub_font_size.setToolTip("Cỡ chữ chuẩn ở độ phân giải 1080p")

        self.sub_bold = QCheckBox("In đậm (Bold)")
        self.sub_bold.setChecked(True)
        self.sub_italic = QCheckBox("In nghiêng (Italic)")
        self.sub_italic.setChecked(False)

        font_row.addWidget(self.sub_font_family, 2)
        font_row.addWidget(QLabel("Cỡ:"))
        font_row.addWidget(self.sub_font_size, 1)
        font_row.addWidget(self.sub_bold)
        font_row.addWidget(self.sub_italic)

        color_row = QHBoxLayout()
        self.sub_font_color = QLineEdit("#FFFFFF")
        self.sub_font_color.setFixedWidth(80)
        self.sub_color_btn = QPushButton("Màu chữ")
        self.sub_color_btn.clicked.connect(self._choose_sub_font_color)
        self.sub_color_preview = QLabel()
        self.sub_color_preview.setFixedSize(24, 24)

        self.sub_outline_color = QLineEdit("#000000")
        self.sub_outline_color.setFixedWidth(80)
        self.sub_outline_color_btn = QPushButton("Màu viền")
        self.sub_outline_color_btn.clicked.connect(self._choose_sub_outline_color)
        self.sub_outline_color_preview = QLabel()
        self.sub_outline_color_preview.setFixedSize(24, 24)

        self.sub_outline_width = QDoubleSpinBox()
        self.sub_outline_width.setRange(0.0, 15.0)
        self.sub_outline_width.setSingleStep(0.5)
        self.sub_outline_width.setValue(2.5)

        color_row.addWidget(QLabel("Màu:"))
        color_row.addWidget(self.sub_font_color)
        color_row.addWidget(self.sub_color_btn)
        color_row.addWidget(self.sub_color_preview)
        color_row.addSpacing(10)
        color_row.addWidget(QLabel("Viền:"))
        color_row.addWidget(self.sub_outline_color)
        color_row.addWidget(self.sub_outline_color_btn)
        color_row.addWidget(self.sub_outline_color_preview)
        color_row.addWidget(QLabel("Dày:"))
        color_row.addWidget(self.sub_outline_width)

        auto_row = QHBoxLayout()
        self.sub_auto_transcribe = QCheckBox("⚡ Tự động quét giọng nói & tạo phụ đề khi Render (Whisper AI)")
        self.sub_auto_transcribe.setStyleSheet("color: #ffca28; font-weight: bold;")
        self.sub_auto_transcribe.setToolTip("Khi bật, lúc nhấn 'Chạy render' hệ thống sẽ tự động nghe MP3 để nhận diện ngôn ngữ nước đó và tạo file .srt rồi gắn vào video. Nếu tắt thì trực tiếp render luôn.")
        self.sub_whisper_model = QComboBox()
        self.sub_whisper_model.addItem("tiny (Siêu tốc)", "tiny")
        self.sub_whisper_model.addItem("base (Cân bằng - Khuyên dùng)", "base")
        self.sub_whisper_model.addItem("small (Chính xác cao)", "small")
        self.sub_whisper_model.setCurrentIndex(1)
        auto_row.addWidget(self.sub_auto_transcribe, 2)
        auto_row.addWidget(QLabel("Model:"))
        auto_row.addWidget(self.sub_whisper_model, 1)

        form.addRow("Trạng thái", self.sub_enabled)
        form.addRow("Quét Sub tự động", auto_row)
        form.addRow("Thư mục Sub (.srt)", folder_row)
        form.addRow("Phông chữ & Kiểu", font_row)
        form.addRow("Màu & Độ dày viền", color_row)
        layout.addLayout(form)

        # Bounding box selector widget
        box_desc = QLabel("Vùng hiển thị phụ đề (Kéo thả khung để định vị & co giãn; Mặc định: 2 bên 15%, cao 20%, cách đáy 10%):")
        box_desc.setStyleSheet("color: #00e5ff; font-weight: bold; font-size: 11px; margin-top: 4px;")
        layout.addWidget(box_desc)

        self.sub_box_selector = SubtitleBoxSelectorWidget()
        self.sub_box_selector.setMinimumHeight(240)
        layout.addWidget(self.sub_box_selector)

        # Connect signals
        self.sub_box_selector.box_changed.connect(lambda x, y, w, h: self._emit())
        self.sub_font_color.textChanged.connect(self._update_sub_color_previews)
        self.sub_outline_color.textChanged.connect(self._update_sub_color_previews)

        for w in (self.sub_enabled, self.sub_auto_transcribe, self.sub_whisper_model, self.sub_folder_edit, self.sub_font_family, self.sub_font_size,
                  self.sub_bold, self.sub_italic, self.sub_font_color, self.sub_outline_color, self.sub_outline_width):
            if hasattr(w, "stateChanged"):
                w.stateChanged.connect(self._on_sub_style_changed)
            elif hasattr(w, "currentIndexChanged"):
                w.currentIndexChanged.connect(self._on_sub_style_changed)
            elif hasattr(w, "valueChanged"):
                w.valueChanged.connect(self._on_sub_style_changed)
            elif hasattr(w, "textChanged"):
                w.textChanged.connect(self._on_sub_style_changed)

        self._update_sub_color_previews()
        return group

    def _choose_sub_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục chứa file phụ đề (.srt)", self.sub_folder_edit.text().strip())
        if folder:
            self.sub_folder_edit.setText(folder)
            self._emit()

    def _choose_sub_font_color(self) -> None:
        c = QColorDialog.getColor(QColor(self.sub_font_color.text().strip() or "#FFFFFF"), self, "Chọn màu chữ phụ đề")
        if c.isValid():
            self.sub_font_color.setText(c.name().upper())
            self._on_sub_style_changed()

    def _choose_sub_outline_color(self) -> None:
        c = QColorDialog.getColor(QColor(self.sub_outline_color.text().strip() or "#000000"), self, "Chọn màu viền phụ đề")
        if c.isValid():
            self.sub_outline_color.setText(c.name().upper())
            self._on_sub_style_changed()

    def _update_sub_color_previews(self) -> None:
        fc = self.sub_font_color.text().strip() or "#FFFFFF"
        oc = self.sub_outline_color.text().strip() or "#000000"
        self.sub_color_preview.setStyleSheet(f"background-color: {fc}; border: 1px solid #555; border-radius: 3px;")
        self.sub_outline_color_preview.setStyleSheet(f"background-color: {oc}; border: 1px solid #555; border-radius: 3px;")

    def _on_sub_style_changed(self) -> None:
        self._update_sub_color_previews()
        if hasattr(self, "sub_box_selector"):
            self.sub_box_selector.set_style(
                font_family=self.sub_font_family.currentText(),
                font_size=self.sub_font_size.value(),
                font_color=self.sub_font_color.text().strip() or "#FFFFFF",
                outline_color=self.sub_outline_color.text().strip() or "#000000",
                outline_width=self.sub_outline_width.value(),
                bold=self.sub_bold.isChecked(),
                italic=self.sub_italic.isChecked(),
            )
        self._emit()

    def _build_background_music_group(self) -> QGroupBox:
        group = QGroupBox()
        layout = QVBoxLayout(group)
        self.bgm_enabled = QCheckBox("Bật nhạc nền")
        layout.addWidget(self.bgm_enabled)

        self.bgm_list = QListWidget()
        self.bgm_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.bgm_list.setMaximumHeight(120)
        layout.addWidget(self.bgm_list)

        bgm_buttons = QHBoxLayout()
        self.add_bgm_btn = QPushButton("Thêm nhạc nền")
        self.remove_bgm_btn = QPushButton("Xóa chọn")
        self.clear_bgm_btn = QPushButton("Xóa hết")
        self.add_bgm_btn.clicked.connect(self.add_background_music)
        self.remove_bgm_btn.clicked.connect(lambda: self._remove_selected(self.bgm_list))
        self.clear_bgm_btn.clicked.connect(self.bgm_list.clear)
        for b in (self.add_bgm_btn, self.remove_bgm_btn, self.clear_bgm_btn):
            bgm_buttons.addWidget(b)
        layout.addLayout(bgm_buttons)

        # Nghe thử BGM
        bgm_preview_row = QHBoxLayout()
        self.bgm_play_btn = QPushButton("▶ Nghe thử")
        self.bgm_stop_btn = QPushButton("⏹ Dừng")
        self.bgm_preview_label = QLabel("Chọn file trong danh sách để nghe thử...")
        self.bgm_preview_label.setStyleSheet("color: #888; font-size: 11px;")
        self.bgm_play_btn.clicked.connect(self._play_bgm_preview)
        self.bgm_stop_btn.clicked.connect(self._stop_audio_preview)
        self.bgm_list.itemClicked.connect(lambda item: self.bgm_preview_label.setText(f"🎵 {Path(item.text()).name}"))
        bgm_preview_row.addWidget(self.bgm_play_btn)
        bgm_preview_row.addWidget(self.bgm_stop_btn)
        bgm_preview_row.addWidget(self.bgm_preview_label, 1)
        layout.addLayout(bgm_preview_row)

        opt_layout = QHBoxLayout()
        self.bgm_shuffle = QCheckBox("Xáo trộn danh sách")
        self.bgm_avoid_repeat = QCheckBox("Tránh trùng bài liên tiếp")
        opt_layout.addWidget(self.bgm_shuffle)
        opt_layout.addWidget(self.bgm_avoid_repeat)
        layout.addLayout(opt_layout)

        form = QFormLayout()
        self.bgm_volume = QDoubleSpinBox()
        self.bgm_volume.setRange(0.0, 1.0)
        self.bgm_volume.setSingleStep(0.02)
        self.bgm_volume.setValue(0.18)
        self.bgm_loop = QCheckBox("Lặp lại nếu hết nhạc")
        self.bgm_loop.setChecked(True)
        form.addRow("Âm lượng BGM", self.bgm_volume)
        form.addRow("Lặp lại nhạc", self.bgm_loop)
        layout.addLayout(form)

        self.bgm_list.model().rowsRemoved.connect(self._emit)
        self.bgm_list.model().rowsInserted.connect(self._emit)
        self._connect_change_widgets(self.bgm_enabled, self.bgm_volume, self.bgm_loop, self.bgm_shuffle, self.bgm_avoid_repeat)
        return group

    def _build_promo_audio_group(self) -> QGroupBox:
        group = QGroupBox()
        layout = QVBoxLayout(group)

        self.promo_enabled = QCheckBox("Bật audio quảng bá")
        layout.addWidget(self.promo_enabled)

        self.promo_list = QListWidget()
        self.promo_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.promo_list.setMaximumHeight(120)
        layout.addWidget(self.promo_list)

        buttons = QHBoxLayout()
        self.add_promo_btn = QPushButton("Thêm audio quảng bá")
        self.remove_promo_btn = QPushButton("Xóa chọn")
        self.clear_promo_btn = QPushButton("Xóa hết")
        self.add_promo_btn.clicked.connect(self.add_promo_audio)
        self.remove_promo_btn.clicked.connect(lambda: self._remove_selected(self.promo_list))
        self.clear_promo_btn.clicked.connect(self.promo_list.clear)
        for b in (self.add_promo_btn, self.remove_promo_btn, self.clear_promo_btn):
            buttons.addWidget(b)
        layout.addLayout(buttons)

        # Nghe thử Promo Audio
        preview_promo_row = QHBoxLayout()
        self.promo_play_btn = QPushButton("▶ Nghe thử")
        self.promo_stop_btn = QPushButton("⏹ Dừng")
        self.promo_preview_label = QLabel("Chọn file trong danh sách để nghe thử...")
        self.promo_preview_label.setStyleSheet("color: #888; font-size: 11px;")
        self.promo_play_btn.clicked.connect(self._play_promo_preview)
        self.promo_stop_btn.clicked.connect(self._stop_audio_preview)
        self.promo_list.itemClicked.connect(lambda item: self.promo_preview_label.setText(f"📢 {Path(item.text()).name}"))
        preview_promo_row.addWidget(self.promo_play_btn)
        preview_promo_row.addWidget(self.promo_stop_btn)
        preview_promo_row.addWidget(self.promo_preview_label, 1)
        layout.addLayout(preview_promo_row)

        opt_layout = QHBoxLayout()
        self.promo_shuffle = QCheckBox("Xáo trộn danh sách")
        self.promo_avoid_repeat = QCheckBox("Tránh trùng file liên tiếp")
        opt_layout.addWidget(self.promo_shuffle)
        opt_layout.addWidget(self.promo_avoid_repeat)
        layout.addLayout(opt_layout)

        form = QFormLayout()
        self.promo_positions = QTextEdit()
        self.promo_positions.setPlaceholderText("Ví dụ:\n01:00\n05:30\n00:10:00\n(hoặc cách nhau bằng dấu phẩy)")
        self.promo_positions.setMaximumHeight(70)

        self.promo_volume = QDoubleSpinBox()
        self.promo_volume.setRange(0.0, 2.0)
        self.promo_volume.setSingleStep(0.05)
        self.promo_volume.setValue(1.0)

        self.promo_duck_enabled = QCheckBox("Bật ducking (giảm âm lượng audio gốc khi phát promo)")
        self.promo_duck_volume = QDoubleSpinBox()
        self.promo_duck_volume.setRange(0.0, 1.0)
        self.promo_duck_volume.setSingleStep(0.05)
        self.promo_duck_volume.setValue(0.35)

        self.promo_duck_pad_start = QSpinBox()
        self.promo_duck_pad_start.setRange(0, 5000)
        self.promo_duck_pad_start.setValue(100)
        self.promo_duck_pad_start.setSuffix(" ms")

        self.promo_duck_pad_end = QSpinBox()
        self.promo_duck_pad_end.setRange(0, 5000)
        self.promo_duck_pad_end.setValue(300)
        self.promo_duck_pad_end.setSuffix(" ms")

        form.addRow("Thời điểm chèn", self.promo_positions)
        form.addRow("Âm lượng promo", self.promo_volume)
        form.addRow("Ducking audio gốc", self.promo_duck_enabled)
        form.addRow("Âm lượng gốc khi duck", self.promo_duck_volume)
        form.addRow("Đệm ducking đầu", self.promo_duck_pad_start)
        form.addRow("Đệm ducking đuôi", self.promo_duck_pad_end)
        layout.addLayout(form)

        self.promo_list.model().rowsRemoved.connect(self._emit)
        self.promo_list.model().rowsInserted.connect(self._emit)
        self._connect_change_widgets(
            self.promo_enabled, self.promo_positions, self.promo_volume,
            self.promo_duck_enabled, self.promo_duck_volume,
            self.promo_duck_pad_start, self.promo_duck_pad_end,
            self.promo_shuffle, self.promo_avoid_repeat
        )
        return group

    def _build_effect_audio_group(self) -> QGroupBox:
        group = QGroupBox()
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(6, 6, 6, 6)
        group_layout.setSpacing(8)

        # 3 Cột song song: [Ảnh] | [Video] | [Chuyển cảnh]
        cols_layout = QHBoxLayout()
        cols_layout.setSpacing(8)

        # Cột 1: Hiệu ứng chuyển động Ảnh
        col1_card = QGroupBox("1. Chuyển động Ảnh")
        col1_layout = QVBoxLayout(col1_card)
        col1_layout.setContentsMargins(6, 6, 6, 6)
        col1_layout.setSpacing(4)
        self.image_motion_enabled = QCheckBox("Bật chuyển động")
        self.image_motion_enabled.setChecked(True)
        self.effect_combo = QComboBox()
        self.effect_combo.addItem("Nhẹ (Auto Light)", "auto_light")
        self.effect_combo.addItem("Đa dạng (Auto Rich)", "auto_rich")
        self.effect_combo.addItem("Tắt hiệu ứng", "none")
        self.image_motion_demo = ImageMotionDemoWidget()
        col1_layout.addWidget(self.image_motion_enabled)
        col1_layout.addWidget(self.effect_combo)
        col1_layout.addWidget(self.image_motion_demo)
        cols_layout.addWidget(col1_card, 1)

        # Cột 2: Hiệu ứng & Lớp phủ Video (Layer Mask)
        col2_card = QGroupBox("2. Hiệu ứng Video (Layer Mask)")
        col2_layout = QVBoxLayout(col2_card)
        col2_layout.setContentsMargins(6, 6, 6, 6)
        col2_layout.setSpacing(4)
        self.video_effect_enabled = QCheckBox("Bật hiệu ứng Video")
        self.video_effect_enabled.setChecked(True)
        self.video_effect_combo = QComboBox()
        self.video_effect_combo.addItem("🫧 Bong bóng bay lên (Bubbles)", "bubbles")
        self.video_effect_combo.addItem("✨ Hạt sương / Tuyết (Dew & Snow)", "dew_particles")
        self.video_effect_combo.addItem("🪶 Lông vũ rơi (Feathers)", "feathers")
        self.video_effect_combo.addItem("🔮 Đốm sáng lung linh (Bokeh)", "bokeh")
        self.video_effect_combo.addItem("🌧️ Mưa rơi (Rain Drops)", "rain")
        self.video_effect_combo.addItem("🎞️ Hạt phim (Film Grain)", "film_grain")
        self.video_effect_combo.addItem("Auto Cinematic", "auto_cinematic")
        self.video_effect_combo.addItem("Vignette (Viền tối)", "vignette")
        self.video_effect_combo.addItem("Color Boost (Tăng màu)", "color_boost")
        self.video_effect_combo.addItem("Slow Push (Đẩy chậm)", "slow_zoom")
        self.video_effect_combo.addItem("📁 Video Layer tùy chọn từ máy...", "custom")
        self.video_effect_combo.addItem("Tắt hiệu ứng", "none")

        # Row chọn file video layer mask tùy chọn (khi chọn 'custom')
        self.custom_layer_row = QWidget()
        custom_layer_layout = QHBoxLayout(self.custom_layer_row)
        custom_layer_layout.setContentsMargins(0, 0, 0, 0)
        custom_layer_layout.setSpacing(4)
        self.custom_layer_edit = QLineEdit()
        self.custom_layer_edit.setPlaceholderText("File layer mask (*.mp4)...")
        self.custom_layer_btn = QPushButton("Chọn...")
        self.custom_layer_btn.clicked.connect(self._choose_custom_layer_file)
        custom_layer_layout.addWidget(self.custom_layer_edit, 1)
        custom_layer_layout.addWidget(self.custom_layer_btn)
        self.custom_layer_row.setVisible(False)

        # Thanh chỉnh độ đậm/mờ (Opacity)
        op_row = QHBoxLayout()
        op_row.addWidget(QLabel("Độ đậm:"))
        self.video_effect_opacity = QDoubleSpinBox()
        self.video_effect_opacity.setRange(0.1, 1.0)
        self.video_effect_opacity.setSingleStep(0.05)
        self.video_effect_opacity.setValue(0.80)
        op_row.addWidget(self.video_effect_opacity)

        self.video_effect_demo = VideoEffectDemoWidget()
        self.effect_demo = self.video_effect_demo  # alias
        col2_layout.addWidget(self.video_effect_enabled)
        col2_layout.addWidget(self.video_effect_combo)
        col2_layout.addWidget(self.custom_layer_row)
        col2_layout.addLayout(op_row)
        col2_layout.addWidget(self.video_effect_demo)
        cols_layout.addWidget(col2_card, 1)

        # Cột 3: Kiểu chuyển cảnh (Transitions)
        col3_card = QGroupBox("3. Chuyển cảnh")
        col3_layout = QVBoxLayout(col3_card)
        col3_layout.setContentsMargins(6, 6, 6, 6)
        col3_layout.setSpacing(4)
        self.transition_enabled = QCheckBox("Bật chuyển cảnh")
        self.transition_enabled.setChecked(True)
        self.transition_combo = QComboBox()
        self.transition_combo.addItem("Nhẹ (Auto Light)", "auto_light")
        self.transition_combo.addItem("Đa dạng (Auto Rich)", "auto_rich")
        self.transition_combo.addItem("Cut (Tắt hiệu ứng)", "none")
        self.transition_demo = TransitionDemoWidget()
        col3_layout.addWidget(self.transition_enabled)
        col3_layout.addWidget(self.transition_combo)
        col3_layout.addWidget(self.transition_demo)
        cols_layout.addWidget(col3_card, 1)

        group_layout.addLayout(cols_layout)

        # Hàng thông số gọn gàng dạng lưới 2x2 bên dưới
        params_group = QWidget()
        params_grid = QGridLayout(params_group)
        params_grid.setContentsMargins(4, 4, 4, 2)
        params_grid.setHorizontalSpacing(10)
        params_grid.setVerticalSpacing(6)

        params_grid.addWidget(QLabel("Thời lượng ảnh:"), 0, 0)
        self.image_duration_combo = QComboBox()
        self.image_duration_combo.addItems(["auto", "2", "3", "4", "5", "6", "7", "8", "9", "10", "12", "15", "18", "20", "25", "30"])
        self.image_duration_combo.setEditable(True)
        params_grid.addWidget(self.image_duration_combo, 0, 1)

        params_grid.addWidget(QLabel("Thời lượng chuyển cảnh:"), 0, 2)
        self.transition_duration = QDoubleSpinBox()
        self.transition_duration.setRange(0.1, 3.0)
        self.transition_duration.setSingleStep(0.1)
        self.transition_duration.setValue(0.5)
        self.transition_duration.setSuffix(" s")
        params_grid.addWidget(self.transition_duration, 0, 3)

        params_grid.addWidget(QLabel("Tốc độ Audio:"), 1, 0)
        self.audio_speed_spin = QDoubleSpinBox()
        self.audio_speed_spin.setRange(0.5, 3.0)
        self.audio_speed_spin.setSingleStep(0.05)
        self.audio_speed_spin.setValue(1.0)
        self.audio_speed_spin.setSuffix(" x")
        params_grid.addWidget(self.audio_speed_spin, 1, 1)

        params_grid.addWidget(QLabel("Tốc độ Video:"), 1, 2)
        self.video_speed_spin = QDoubleSpinBox()
        self.video_speed_spin.setRange(0.5, 3.0)
        self.video_speed_spin.setSingleStep(0.05)
        self.video_speed_spin.setValue(1.0)
        self.video_speed_spin.setSuffix(" x")
        params_grid.addWidget(self.video_speed_spin, 1, 3)

        group_layout.addWidget(params_group)

        self.image_motion_enabled.toggled.connect(self._on_effects_toggled)
        self.video_effect_enabled.toggled.connect(self._on_effects_toggled)
        self.transition_enabled.toggled.connect(self._on_effects_toggled)

        self.effect_combo.currentIndexChanged.connect(self._update_all_effect_demos)
        self.video_effect_combo.currentIndexChanged.connect(self._on_video_effect_combo_changed)
        self.transition_combo.currentIndexChanged.connect(self._update_all_effect_demos)

        self._connect_change_widgets(
            self.image_motion_enabled, self.video_effect_enabled, self.transition_enabled,
            self.image_duration_combo, self.effect_combo, self.video_effect_combo,
            self.custom_layer_edit, self.video_effect_opacity,
            self.transition_combo, self.transition_duration,
            self.audio_speed_spin, self.video_speed_spin
        )
        return group

    def _on_video_effect_combo_changed(self) -> None:
        is_custom = self.video_effect_combo.currentData() == "custom"
        self.custom_layer_row.setVisible(is_custom)
        self._update_all_effect_demos()

    def _choose_custom_layer_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn Video Layer Mask", "", "Video Files (*.mp4 *.mov *.webm *.mkv);;All Files (*.*)"
        )
        if path:
            self.custom_layer_edit.setText(path)
            self._emit()

    def _on_effects_toggled(self) -> None:
        im_on = self.image_motion_enabled.isChecked()
        self.effect_combo.setEnabled(im_on)
        self.image_motion_demo.setEnabled(im_on)
        self.image_motion_demo.set_motion(self.effect_combo.currentData() if im_on else "none")

        ve_on = self.video_effect_enabled.isChecked()
        self.video_effect_combo.setEnabled(ve_on)
        self.custom_layer_row.setEnabled(ve_on)
        self.video_effect_opacity.setEnabled(ve_on)
        self.video_effect_demo.setEnabled(ve_on)
        self.video_effect_demo.set_effect(self.video_effect_combo.currentData() if ve_on else "none")
        if ve_on:
            self.custom_layer_row.setVisible(self.video_effect_combo.currentData() == "custom")
        else:
            self.custom_layer_row.setVisible(False)

        tr_on = self.transition_enabled.isChecked()
        self.transition_combo.setEnabled(tr_on)
        self.transition_demo.setEnabled(tr_on)
        self.transition_duration.setEnabled(tr_on)
        self.transition_demo.set_transition(self.transition_combo.currentData() if tr_on else "none")

        self._emit()

    def _build_export_group(self) -> QGroupBox:
        group = QGroupBox()
        form = QFormLayout(group)
        self.ratio_combo = QComboBox()
        self.ratio_combo.addItem("16:9 (1920x1080 - YouTube chuẩn)", (1920, 1080, "16:9"))
        self.ratio_combo.addItem("9:16 (1080x1920 - Shorts/TikTok)", (1080, 1920, "9:16"))
        self.ratio_combo.addItem("1:1 (1080x1080 - Vuông)", (1080, 1080, "1:1"))
        self.ratio_combo.addItem("4:5 (1080x1350 - Facebook Feed)", (1080, 1350, "4:5"))

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(15, 60)
        self.fps_spin.setValue(30)

        self.quality_combo = QComboBox()
        self.quality_combo.addItem("High (CRF 18 / Tốt nhất)", "high")
        self.quality_combo.addItem("Standard (CRF 23 / Chuẩn)", "standard")
        self.quality_combo.addItem("Low (CRF 28 / Nhẹ)", "low")

        out_row = QHBoxLayout()
        self.output_edit = QLineEdit("output")
        self.output_btn = QPushButton("Chọn...")
        self.output_btn.clicked.connect(self.choose_output_folder)
        out_row.addWidget(self.output_edit)
        out_row.addWidget(self.output_btn)

        form.addRow("Tỉ lệ khung hình", self.ratio_combo)
        form.addRow("FPS", self.fps_spin)
        form.addRow("Chất lượng xuất", self.quality_combo)
        form.addRow("Thư mục xuất", out_row)
        self._connect_change_widgets(self.ratio_combo, self.fps_spin, self.quality_combo, self.output_edit)
        return group

    def _build_performance_group(self) -> QGroupBox:
        group = QGroupBox()
        form = QFormLayout(group)
        self.encoder_combo = QComboBox()
        self.encoder_combo.addItem("CPU (libx264 - Ổn định nhất)", "cpu")
        self.encoder_combo.addItem("NVIDIA (h264_nvenc - Nhanh nhất)", "nvidia")
        self.encoder_combo.addItem("Intel (h264_qsv)", "intel")
        self.encoder_combo.addItem("AMD (h264_amf)", "amd")

        self.max_parallel_spin = QSpinBox()
        self.max_parallel_spin.setRange(1, 10)
        self.max_parallel_spin.setValue(1)
        self.max_parallel_spin.setToolTip("Số video được render song song đồng thời.")

        self.cpu_threads_spin = QSpinBox()
        self.cpu_threads_spin.setRange(0, 64)
        self.cpu_threads_spin.setValue(0)
        self.cpu_threads_spin.setSpecialValueText("Tự động (FFmpeg auto)")

        self.transition_batch_spin = QSpinBox()
        self.transition_batch_spin.setRange(6, 60)
        self.transition_batch_spin.setValue(36)
        self.transition_batch_spin.setToolTip("Giới hạn số ảnh ghép trong 1 batch chuyển cảnh.")

        temp_row = QHBoxLayout()
        self.temp_folder_edit = QLineEdit()
        self.temp_folder_edit.setPlaceholderText("Mặc định dùng thư mục temp trong tool")
        self.temp_folder_btn = QPushButton("Chọn...")
        self.temp_folder_btn.clicked.connect(self.choose_temp_folder)
        temp_row.addWidget(self.temp_folder_edit)
        temp_row.addWidget(self.temp_folder_btn)

        self.auto_clear_temp_checkbox = QCheckBox("Tự động dọn file tạm sau khi render xong")
        self.auto_clear_temp_checkbox.setChecked(True)
        self.keep_temp_on_error_checkbox = QCheckBox("Giữ lại file tạm khi bị lỗi để kiểm tra")
        self.allow_cpu_fallback_checkbox = QCheckBox("Tự động lùi về CPU nếu GPU gặp lỗi")
        self.gpu_preflight_checkbox = QCheckBox("Kiểm tra phần cứng GPU trước khi chạy")
        self.gpu_preflight_checkbox.setChecked(True)

        form.addRow("Bộ mã hóa (Encoder)", self.encoder_combo)
        form.addRow("Render song song (Jobs)", self.max_parallel_spin)
        form.addRow("Số luồng CPU (Threads)", self.cpu_threads_spin)
        form.addRow("Batch chuyển cảnh", self.transition_batch_spin)
        form.addRow("Thư mục Temp riêng", temp_row)
        form.addRow("Dọn temp thành công", self.auto_clear_temp_checkbox)
        form.addRow("Giữ temp khi lỗi", self.keep_temp_on_error_checkbox)
        form.addRow("Fallback về CPU", self.allow_cpu_fallback_checkbox)
        form.addRow("Preflight test GPU", self.gpu_preflight_checkbox)

        self._connect_change_widgets(
            self.encoder_combo, self.max_parallel_spin, self.cpu_threads_spin,
            self.transition_batch_spin, self.temp_folder_edit,
            self.auto_clear_temp_checkbox, self.keep_temp_on_error_checkbox,
            self.allow_cpu_fallback_checkbox, self.gpu_preflight_checkbox
        )
        return group

    def _position_combo(self) -> QComboBox:
        combo = QComboBox()
        for text, data in [
            ("Trên trái", "top_left"), ("Trên giữa", "top_center"), ("Trên phải", "top_right"),
            ("Giữa trái", "center_left"), ("Giữa", "center"), ("Giữa phải", "center_right"),
            ("Dưới trái", "bottom_left"), ("Dưới giữa", "bottom_center"), ("Dưới phải", "bottom_right"),
        ]:
            combo.addItem(text, data)
        return combo

    def _file_row(self, form: QFormLayout, label: str, button_text: str, file_filter: str) -> QLineEdit:
        row = QHBoxLayout()
        edit = QLineEdit()
        btn = QPushButton(button_text)
        btn.clicked.connect(lambda: self._choose_file(edit, file_filter))
        row.addWidget(edit)
        row.addWidget(btn)
        form.addRow(label, row)
        edit.textChanged.connect(self._emit)
        return edit

    def choose_text_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.text_font_color.text() or "#FFFFFF"), self, "Chọn màu chữ")
        if color.isValid():
            self.text_font_color.setText(color.name().upper())

    def _update_color_preview(self) -> None:
        color = self.text_font_color.text().strip() or "#FFFFFF"
        self.text_color_preview.setStyleSheet(f"background:{color}; border:1px solid #999; border-radius:13px;")
        self._emit()

    def add_background_music(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(AUDIO_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn danh sách nhạc nền", "", f"Audio ({exts})")
        self._add_unique(self.bgm_list, files)

    def add_promo_audio(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(AUDIO_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn audio quảng bá", "", f"Audio ({exts})")
        self._add_unique(self.promo_list, files)

    def choose_output_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục output")
        if folder:
            self.output_edit.setText(folder)

    def choose_temp_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục temp/cache")
        if folder:
            self.temp_folder_edit.setText(folder)

    def _choose_file(self, edit: QLineEdit, file_filter: str) -> None:
        file, _ = QFileDialog.getOpenFileName(self, "Chọn file", "", file_filter)
        if file:
            edit.setText(file)

    @staticmethod
    def _add_unique(list_widget: QListWidget, files: List[str]) -> None:
        existing = {list_widget.item(i).text() for i in range(list_widget.count())}
        for file in files:
            if file and file not in existing:
                list_widget.addItem(file)

    def _remove_selected(self, list_widget: QListWidget) -> None:
        rows = sorted({list_widget.row(item) for item in list_widget.selectedItems()}, reverse=True)
        for row in rows:
            list_widget.takeItem(row)
        self._stop_audio_preview()

    @staticmethod
    def _list_items(list_widget: QListWidget) -> List[str]:
        return [list_widget.item(i).text() for i in range(list_widget.count())]

    def collect_settings(self) -> Dict[str, Any]:
        width, height, ratio = self.ratio_combo.currentData()
        settings = dict(self.settings)
        settings.update({
            "intro_file": self.intro_edit.text().strip(),
            "outro_file": self.outro_edit.text().strip(),
            "logo_file": self.logo_edit.text().strip(),
            "logo_enabled": self.logo_enabled.isChecked(),
            "logo_position": self.logo_position.currentData(),
            "logo_scale": self.logo_scale.value(),
            "logo_margin_x": self.logo_margin_x.value(),
            "logo_margin_y": self.logo_margin_y.value(),
            "watermark_file": self.watermark_edit.text().strip(),
            "watermark_enabled": self.watermark_enabled.isChecked(),
            "watermark_opacity": self.watermark_opacity.value(),
            "watermark_scale": self.watermark_scale.value(),
            "background_music": {
                "enabled": self.bgm_enabled.isChecked(),
                "file": self._list_items(self.bgm_list)[0] if self._list_items(self.bgm_list) else "",
                "files": self._list_items(self.bgm_list),
                "shuffle": self.bgm_shuffle.isChecked(),
                "avoid_repeat": self.bgm_avoid_repeat.isChecked(),
                "volume": self.bgm_volume.value(),
                "loop": self.bgm_loop.isChecked(),
            },
            "promo_audio": {
                "enabled": self.promo_enabled.isChecked(),
                "files": self._list_items(self.promo_list),
                "positions_text": self.promo_positions.toPlainText().strip(),
                "shuffle": self.promo_shuffle.isChecked(),
                "avoid_repeat": self.promo_avoid_repeat.isChecked(),
                "volume": self.promo_volume.value(),
                "duck_enabled": self.promo_duck_enabled.isChecked(),
                "duck_volume": self.promo_duck_volume.value(),
                "duck_pad_start_ms": self.promo_duck_pad_start.value(),
                "duck_pad_end_ms": self.promo_duck_pad_end.value(),
            },
            "image_duration_mode": self.image_duration_combo.currentText(),
            "image_motion_enabled": self.image_motion_enabled.isChecked(),
            "video_effect_enabled": self.video_effect_enabled.isChecked(),
            "transition_enabled": self.transition_enabled.isChecked(),
            "effect_mode": self.effect_combo.currentData() if self.image_motion_enabled.isChecked() else "none",
            "video_effect_mode": self.video_effect_combo.currentData() if self.video_effect_enabled.isChecked() else "none",
            "video_effect_custom_file": self.custom_layer_edit.text().strip() if hasattr(self, "custom_layer_edit") else "",
            "video_effect_opacity": self.video_effect_opacity.value() if hasattr(self, "video_effect_opacity") else 0.80,
            "transition_mode": self.transition_combo.currentData() if self.transition_enabled.isChecked() else "none",
            "transition_duration": self.transition_duration.value(),
            "audio_speed": self.audio_speed_spin.value(),
            "video_speed": self.video_speed_spin.value(),
            "performance": {
                "encoder": self.encoder_combo.currentData(),
                "max_parallel_jobs": self.max_parallel_spin.value(),
                "cpu_threads": self.cpu_threads_spin.value(),
                "transition_batch_size": self.transition_batch_spin.value(),
                "auto_clear_temp": self.auto_clear_temp_checkbox.isChecked(),
                "keep_temp_on_error": self.keep_temp_on_error_checkbox.isChecked(),
                "allow_cpu_fallback": self.allow_cpu_fallback_checkbox.isChecked(),
                "gpu_preflight_check": self.gpu_preflight_checkbox.isChecked(),
                "temp_folder": self.temp_folder_edit.text().strip(),
            },
            "text_overlay": {
                "enabled": self.text_enabled.isChecked(),
                "content": self.text_content.toPlainText().strip(),
                "font_size": self.text_font_size.value(),
                "position": self.text_position.currentData(),
                "moving_enabled": self.text_moving_enabled.isChecked(),
                "margin_x": self.text_margin_x.value(),
                "margin_y": self.text_margin_y.value(),
                "font_color": self.text_font_color.text().strip() or "#FFFFFF",
                "box_enabled": self.text_box_enabled.isChecked(),
                "box_opacity": self.text_box_opacity.value(),
            },
            "subtitle": {
                "enabled": self.sub_enabled.isChecked() if hasattr(self, "sub_enabled") else False,
                "auto_transcribe": self.sub_auto_transcribe.isChecked() if hasattr(self, "sub_auto_transcribe") else False,
                "whisper_model": self.sub_whisper_model.currentData() if hasattr(self, "sub_whisper_model") else "base",
                "folder": self.sub_folder_edit.text().strip() if hasattr(self, "sub_folder_edit") else "",
                "font_family": self.sub_font_family.currentText() if hasattr(self, "sub_font_family") else "Arial",
                "font_size": self.sub_font_size.value() if hasattr(self, "sub_font_size") else 38,
                "font_color": self.sub_font_color.text().strip() or "#FFFFFF" if hasattr(self, "sub_font_color") else "#FFFFFF",
                "outline_color": self.sub_outline_color.text().strip() or "#000000" if hasattr(self, "sub_outline_color") else "#000000",
                "outline_width": self.sub_outline_width.value() if hasattr(self, "sub_outline_width") else 2.5,
                "bold": self.sub_bold.isChecked() if hasattr(self, "sub_bold") else True,
                "italic": self.sub_italic.isChecked() if hasattr(self, "sub_italic") else False,
                "box_x": (self.sub_box_selector.get_box()[0]) if hasattr(self, "sub_box_selector") else 0.15,
                "box_y": (self.sub_box_selector.get_box()[1]) if hasattr(self, "sub_box_selector") else 0.70,
                "box_w": (self.sub_box_selector.get_box()[2]) if hasattr(self, "sub_box_selector") else 0.70,
                "box_h": (self.sub_box_selector.get_box()[3]) if hasattr(self, "sub_box_selector") else 0.20,
            },
            "export": {
                "ratio": ratio,
                "width": width,
                "height": height,
                "fps": self.fps_spin.value(),
                "quality": self.quality_combo.currentData(),
                "format": "mp4",
                "output_folder": self.output_edit.text().strip() or "output",
            },
        })
        return settings

    def load_settings(self, settings: Dict[str, Any]) -> None:
        self._lock_emit = True
        self.settings = settings

        self.intro_edit.setText(settings.get("intro_file", ""))
        self.outro_edit.setText(settings.get("outro_file", ""))
        self.logo_edit.setText(settings.get("logo_file", ""))
        self.logo_enabled.setChecked(bool(settings.get("logo_enabled", False)))
        self._set_combo_by_data(self.logo_position, settings.get("logo_position", "top_right"))
        self.logo_scale.setValue(float(settings.get("logo_scale", 0.12)))
        self.logo_margin_x.setValue(int(settings.get("logo_margin_x", 30)))
        self.logo_margin_y.setValue(int(settings.get("logo_margin_y", 30)))
        self.watermark_edit.setText(settings.get("watermark_file", ""))
        self.watermark_enabled.setChecked(bool(settings.get("watermark_enabled", False)))
        self.watermark_opacity.setValue(float(settings.get("watermark_opacity", 0.2)))
        self.watermark_scale.setValue(float(settings.get("watermark_scale", 1.0)))

        bgm = settings.get("background_music", {}) or {}
        self.bgm_list.clear()
        bgm_files = list(bgm.get("files", []) or [])
        if not bgm_files and bgm.get("file"):
            bgm_files = [str(bgm.get("file"))]
        self.bgm_list.addItems(bgm_files)
        self.bgm_enabled.setChecked(bool(bgm.get("enabled", False)))
        self.bgm_volume.setValue(float(bgm.get("volume", 0.18)))
        self.bgm_loop.setChecked(bool(bgm.get("loop", True)))
        self.bgm_shuffle.setChecked(bool(bgm.get("shuffle", True)))
        self.bgm_avoid_repeat.setChecked(bool(bgm.get("avoid_repeat", True)))

        promo = settings.get("promo_audio", {}) or {}
        self.promo_list.clear()
        self.promo_list.addItems(list(promo.get("files", []) or []))
        self.promo_enabled.setChecked(bool(promo.get("enabled", False)))
        self.promo_positions.setPlainText(str(promo.get("positions_text", "")))
        self.promo_volume.setValue(float(promo.get("volume", 1.0)))
        self.promo_duck_enabled.setChecked(bool(promo.get("duck_enabled", True)))
        self.promo_duck_volume.setValue(float(promo.get("duck_volume", 0.35)))
        self.promo_duck_pad_start.setValue(int(promo.get("duck_pad_start_ms", 100)))
        self.promo_duck_pad_end.setValue(int(promo.get("duck_pad_end_ms", 300)))
        self.promo_shuffle.setChecked(bool(promo.get("shuffle", True)))
        self.promo_avoid_repeat.setChecked(bool(promo.get("avoid_repeat", True)))

        self.image_duration_combo.setCurrentText(str(settings.get("image_duration_mode", "auto")))
        effect_mode = settings.get("effect_mode", "auto_light")
        im_on = bool(settings.get("image_motion_enabled", effect_mode != "none"))
        self.image_motion_enabled.setChecked(im_on)
        if effect_mode in ["random_light", "auto_light"]:
            effect_mode = "auto_light"
        elif effect_mode in ["random_rich", "auto_rich"]:
            effect_mode = "auto_rich"
        elif effect_mode == "none":
            effect_mode = "auto_light"
        self._set_combo_by_data(self.effect_combo, effect_mode)

        video_fx = settings.get("video_effect_mode", "bubbles")
        ve_on = bool(settings.get("video_effect_enabled", video_fx != "none"))
        self.video_effect_enabled.setChecked(ve_on)
        if video_fx == "none":
            video_fx = "bubbles"
        self._set_combo_by_data(self.video_effect_combo, video_fx)
        if hasattr(self, "custom_layer_edit"):
            self.custom_layer_edit.setText(str(settings.get("video_effect_custom_file", "") or ""))
        if hasattr(self, "video_effect_opacity"):
            self.video_effect_opacity.setValue(float(settings.get("video_effect_opacity", 0.80) or 0.80))
        if hasattr(self, "custom_layer_row"):
            self.custom_layer_row.setVisible(ve_on and self.video_effect_combo.currentData() == "custom")

        transition_mode = settings.get("transition_mode", "auto_light")
        tr_on = bool(settings.get("transition_enabled", transition_mode != "none"))
        self.transition_enabled.setChecked(tr_on)
        if transition_mode in ["random_basic", "auto_light", "fade"]:
            transition_mode = "auto_light"
        elif transition_mode == "none":
            transition_mode = "auto_light"
        self._set_combo_by_data(self.transition_combo, transition_mode)
        self.transition_duration.setValue(float(settings.get("transition_duration", 0.5)))
        self.audio_speed_spin.setValue(float(settings.get("audio_speed", 1.0)))
        self.video_speed_spin.setValue(float(settings.get("video_speed", 1.0)))
        self._on_effects_toggled()

        perf_cfg = settings.get("performance", {})
        self._set_combo_by_data(self.encoder_combo, perf_cfg.get("encoder", "cpu"))
        self.max_parallel_spin.setValue(int(perf_cfg.get("max_parallel_jobs", 1)))
        self.cpu_threads_spin.setValue(int(perf_cfg.get("cpu_threads", 0)))
        self.transition_batch_spin.setValue(int(perf_cfg.get("transition_batch_size", perf_cfg.get("max_transition_inputs", 36))))
        self.temp_folder_edit.setText(str(perf_cfg.get("temp_folder", "") or ""))
        self.auto_clear_temp_checkbox.setChecked(bool(perf_cfg.get("auto_clear_temp", True)))
        self.keep_temp_on_error_checkbox.setChecked(bool(perf_cfg.get("keep_temp_on_error", False)))
        self.allow_cpu_fallback_checkbox.setChecked(bool(perf_cfg.get("allow_cpu_fallback", False)))
        self.gpu_preflight_checkbox.setChecked(bool(perf_cfg.get("gpu_preflight_check", True)))

        text_cfg = settings.get("text_overlay", {})
        self.text_enabled.setChecked(bool(text_cfg.get("enabled", False)))
        self.text_content.setPlainText(str(text_cfg.get("content", "")))
        self.text_font_size.setValue(int(text_cfg.get("font_size", 48)))
        self._set_combo_by_data(self.text_position, text_cfg.get("position", "bottom_center"))
        self.text_moving_enabled.setChecked(bool(text_cfg.get("moving_enabled", False)))
        self.text_margin_x.setValue(int(text_cfg.get("margin_x", 40)))
        self.text_margin_y.setValue(int(text_cfg.get("margin_y", 80)))
        self.text_font_color.setText(str(text_cfg.get("font_color", "#FFFFFF")))
        self._update_color_preview()
        self.text_box_enabled.setChecked(bool(text_cfg.get("box_enabled", True)))
        self.text_box_opacity.setValue(float(text_cfg.get("box_opacity", 0.45)))

        sub_cfg = settings.get("subtitle", {}) or {}
        if hasattr(self, "sub_enabled"):
            self.sub_enabled.setChecked(bool(sub_cfg.get("enabled", False)))
            if hasattr(self, "sub_auto_transcribe"):
                self.sub_auto_transcribe.setChecked(bool(sub_cfg.get("auto_transcribe", False)))
            if hasattr(self, "sub_whisper_model"):
                self._set_combo_by_data(self.sub_whisper_model, sub_cfg.get("whisper_model", "base"))
            self.sub_folder_edit.setText(str(sub_cfg.get("folder", "") or ""))
            font_fam = str(sub_cfg.get("font_family", "Arial") or "Arial")
            idx = self.sub_font_family.findText(font_fam)
            if idx >= 0:
                self.sub_font_family.setCurrentIndex(idx)
            else:
                self.sub_font_family.setEditText(font_fam)
            self.sub_font_size.setValue(int(sub_cfg.get("font_size", 38) or 38))
            self.sub_bold.setChecked(bool(sub_cfg.get("bold", True)))
            self.sub_italic.setChecked(bool(sub_cfg.get("italic", False)))
            self.sub_font_color.setText(str(sub_cfg.get("font_color", "#FFFFFF") or "#FFFFFF"))
            self.sub_outline_color.setText(str(sub_cfg.get("outline_color", "#000000") or "#000000"))
            self.sub_outline_width.setValue(float(sub_cfg.get("outline_width", 2.5) or 2.5))
            self._update_sub_color_previews()

            bx = float(sub_cfg.get("box_x", 0.15))
            by = float(sub_cfg.get("box_y", 0.70))
            bw = float(sub_cfg.get("box_w", 0.70))
            bh = float(sub_cfg.get("box_h", 0.20))
            if hasattr(self, "sub_box_selector"):
                self.sub_box_selector.set_box(bx, by, bw, bh)
                self.sub_box_selector.set_style(
                    font_family=font_fam,
                    font_size=self.sub_font_size.value(),
                    font_color=self.sub_font_color.text().strip(),
                    outline_color=self.sub_outline_color.text().strip(),
                    outline_width=self.sub_outline_width.value(),
                    bold=self.sub_bold.isChecked(),
                    italic=self.sub_italic.isChecked(),
                )

        export = settings.get("export", {})
        self.fps_spin.setValue(int(export.get("fps", 30)))
        self.output_edit.setText(export.get("output_folder", "output"))
        self._set_ratio(export.get("width", 1920), export.get("height", 1080))
        self._set_combo_by_data(self.quality_combo, export.get("quality", "standard"))

        if hasattr(self, "sub_box_selector") and hasattr(self, "ratio_combo"):
            r_data = self.ratio_combo.currentData()
            if r_data:
                self.sub_box_selector.set_aspect_ratio(r_data[2], r_data[0], r_data[1])

        self._update_effect_demo()
        self.layout_preview.update_settings(settings)
        self._lock_emit = False

    def _update_all_effect_demos(self) -> None:
        if hasattr(self, "image_motion_demo") and hasattr(self, "effect_combo"):
            mode = self.effect_combo.currentData() or "auto_light"
            if hasattr(self, "image_motion_enabled") and not self.image_motion_enabled.isChecked():
                mode = "none"
            self.image_motion_demo.set_motion(mode)
        if hasattr(self, "video_effect_demo") and hasattr(self, "video_effect_combo"):
            mode = self.video_effect_combo.currentData() or "auto_cinematic"
            if hasattr(self, "video_effect_enabled") and not self.video_effect_enabled.isChecked():
                mode = "none"
            self.video_effect_demo.set_effect(mode)
        if hasattr(self, "transition_demo") and hasattr(self, "transition_combo"):
            mode = self.transition_combo.currentData() or "auto_light"
            if hasattr(self, "transition_enabled") and not self.transition_enabled.isChecked():
                mode = "none"
            self.transition_demo.set_transition(mode)

    def _update_effect_demo(self) -> None:
        self._update_all_effect_demos()

    def _play_bgm_preview(self) -> None:
        item = self.bgm_list.currentItem()
        if not item and self.bgm_list.count() > 0:
            self.bgm_list.setCurrentRow(0)
            item = self.bgm_list.currentItem()
        if not item:
            self.bgm_preview_label.setText("Chưa có file BGM nào để nghe thử.")
            return
        fpath = item.text().strip()
        if not os.path.exists(fpath):
            self.bgm_preview_label.setText("File không tồn tại trên đĩa.")
            return
        if self._preview_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._stop_audio_preview()
            return
        self._preview_player.setSource(QUrl.fromLocalFile(fpath))
        self._preview_player.play()
        self.bgm_play_btn.setText("⏸ Tạm dừng")
        self.bgm_preview_label.setText(f"▶ Đang phát: {Path(fpath).name}")

    def _play_promo_preview(self) -> None:
        item = self.promo_list.currentItem()
        if not item and self.promo_list.count() > 0:
            self.promo_list.setCurrentRow(0)
            item = self.promo_list.currentItem()
        if not item:
            self.promo_preview_label.setText("Chưa có file quảng bá nào để nghe thử.")
            return
        fpath = item.text().strip()
        if not os.path.exists(fpath):
            self.promo_preview_label.setText("File không tồn tại trên đĩa.")
            return
        if self._preview_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._stop_audio_preview()
            return
        self._preview_player.setSource(QUrl.fromLocalFile(fpath))
        self._preview_player.play()
        self.promo_play_btn.setText("⏸ Tạm dừng")
        self.promo_preview_label.setText(f"▶ Đang phát: {Path(fpath).name}")

    def _stop_audio_preview(self) -> None:
        self._preview_player.stop()
        self._preview_player.setSource(QUrl())
        self.bgm_play_btn.setText("▶ Nghe thử")
        self.promo_play_btn.setText("▶ Nghe thử")

    def _on_preview_player_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state != QMediaPlayer.PlaybackState.PlayingState:
            self.bgm_play_btn.setText("▶ Nghe thử")
            self.promo_play_btn.setText("▶ Nghe thử")

    def set_locked(self, locked: bool) -> None:
        for widget in self.findChildren(QWidget):
            if widget is not self and widget is not self.layout_preview:
                widget.setEnabled(not locked)

    def _set_ratio(self, width: int, height: int) -> None:
        for i in range(self.ratio_combo.count()):
            data = self.ratio_combo.itemData(i)
            if data and data[0] == width and data[1] == height:
                self.ratio_combo.setCurrentIndex(i)
                return

    @staticmethod
    def _set_combo_by_data(combo: QComboBox, value: Any) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    def _connect_change_widgets(self, *widgets: Any) -> None:
        for widget in widgets:
            if hasattr(widget, "stateChanged"):
                widget.stateChanged.connect(self._emit)
            elif hasattr(widget, "currentIndexChanged"):
                widget.currentIndexChanged.connect(self._emit)
            elif hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self._emit)
            elif hasattr(widget, "textChanged"):
                widget.textChanged.connect(self._emit)

    def _emit(self, *args: Any) -> None:
        if self._lock_emit:
            return
        if hasattr(self, "sub_box_selector") and hasattr(self, "ratio_combo"):
            r_data = self.ratio_combo.currentData()
            if r_data:
                self.sub_box_selector.set_aspect_ratio(r_data[2], r_data[0], r_data[1])
        settings = self.collect_settings()
        self.settings = settings
        self.settings_changed.emit(settings)
        self.layout_preview.update_settings(settings)
