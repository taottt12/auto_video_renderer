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
    QLineEdit, QFormLayout, QScrollArea, QTextEdit, QPlainTextEdit, QColorDialog,
    QToolButton, QLabel, QAbstractItemView, QSplitter, QMessageBox
)

from core.media_utils import AUDIO_EXTENSIONS
from core.subtitle_utils import preflight_whisper_model, check_cuda_whisper_support, ensure_cuda_whisper_libraries
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
        self.motion_mode = "auto_smart"
        self._anim_t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(40)  # ~25 FPS

    def _on_tick(self) -> None:
        self._anim_t += 0.04
        self.update()

    def set_motion(self, mode: str) -> None:
        self.motion_mode = mode or "auto_smart"
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
        t = self._anim_t
        zoom = 1.0
        pan_x = 0.0
        pan_y = 0.0

        mode = self.motion_mode
        p3 = (t % 3.0) / 3.0

        if mode == "auto_smart":
            # Xoay tua 4 kiểu mượt mà (chu kỳ 8s)
            cycle = int(t / 2.0) % 4
            sub_p = (t % 2.0) / 2.0
            if cycle == 0:
                zoom = 1.0 + 0.30 * sub_p
            elif cycle == 1:
                zoom = 1.15
                pan_x = -16 * (sub_p - 0.5)
            elif cycle == 2:
                zoom = 1.30 - 0.30 * sub_p
            else:
                zoom = 1.15
                pan_x = 16 * (sub_p - 0.5)
        elif mode == "auto_light":
            zoom = 1.0 + 0.08 * math.sin(t * 1.2)
            pan_x = 8 * math.cos(t * 0.9)
        elif mode == "auto_rich":
            zoom = 1.0 + 0.16 * math.sin(t * 1.5)
            pan_x = 14 * math.sin(t * 1.1)
            pan_y = 6 * math.cos(t * 1.3)
        elif mode == "zoom_in_center":
            zoom = 1.0 + 0.35 * p3
        elif mode == "zoom_out_center":
            zoom = 1.35 - 0.35 * p3
        elif mode == "zoom_in_top_left":
            zoom = 1.0 + 0.35 * p3
            pan_x = -14 * p3
            pan_y = -8 * p3
        elif mode == "zoom_in_top_right":
            zoom = 1.0 + 0.35 * p3
            pan_x = 14 * p3
            pan_y = -8 * p3
        elif mode == "zoom_in_bottom_left":
            zoom = 1.0 + 0.35 * p3
            pan_x = -14 * p3
            pan_y = 8 * p3
        elif mode == "zoom_in_bottom_right":
            zoom = 1.0 + 0.35 * p3
            pan_x = 14 * p3
            pan_y = 8 * p3
        elif mode == "pan_left":
            zoom = 1.15
            pan_x = -20 * (p3 - 0.5)
        elif mode == "pan_right":
            zoom = 1.15
            pan_x = 20 * (p3 - 0.5)
        elif mode == "pan_up":
            zoom = 1.15
            pan_y = -12 * (p3 - 0.5)
        elif mode == "pan_down":
            zoom = 1.15
            pan_y = 12 * (p3 - 0.5)
        elif mode == "smooth_pulse":
            pulse = (math.sin(t * 2.5) + 1.0) * 0.5
            zoom = 1.0 + 0.18 * pulse
        elif mode == "loop_pan_zoom":
            zoom = 1.08 + 0.12 * math.sin(t * 1.8)
            pan_x = 16 * math.sin(t * 1.2)
            pan_y = 8 * math.cos(t * 1.4)
        elif mode == "none":
            zoom = 1.0
            pan_x = 0.0
            pan_y = 0.0

        painter.save()
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
            "auto_smart": "Xoay tua thông minh (Auto Smart)",
            "auto_light": "Auto Light (Pan & Zoom nhẹ)",
            "auto_rich": "Auto Rich (Ken Burns đa hướng)",
            "zoom_in_center": "Zoom In (Tâm)",
            "zoom_out_center": "Zoom Out (Tâm)",
            "zoom_in_top_left": "Zoom In (Góc Trên Trái)",
            "zoom_in_top_right": "Zoom In (Góc Trên Phải)",
            "zoom_in_bottom_left": "Zoom In (Góc Dưới Trái)",
            "zoom_in_bottom_right": "Zoom In (Góc Dưới Phải)",
            "pan_left": "Pan Sang Trái",
            "pan_right": "Pan Sang Phải",
            "pan_up": "Pan Lên Trên",
            "pan_down": "Pan Xuống Dưới",
            "smooth_pulse": "Smooth Pulse (Nhịp thở)",
            "loop_pan_zoom": "Loop Pan & Zoom",
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
    """Widget demo trực quan hiệu ứng chuyển cảnh (Transitions: Crossfade, Wipe, Slide, Circle, Zoom...)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(115)
        self.transition_mode = "auto_soft"
        self._anim_t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(40)  # ~25 FPS

    def _on_tick(self) -> None:
        self._anim_t += 0.04
        self.update()

    def set_transition(self, mode: str) -> None:
        self.transition_mode = mode or "auto_soft"
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
            "auto_soft": "Auto Soft (Chuyển cảnh êm)",
            "auto_dynamic": "Auto Dynamic (Đa dạng sôi động)",
            "auto_light": "Auto Light (Crossfade cơ bản)",
            "auto_rich": "Auto Rich (Phong phú)",
            "fade": "Crossfade (Mờ dần chồng)",
            "fadeblack": "Fade to Black (Đen dần)",
            "fadewhite": "Fade to White (Trắng chớp)",
            "dissolve": "Dissolve (Hòa tan)",
            "slideleft": "Slide Left (Trượt sang trái)",
            "slideright": "Slide Right (Trượt sang phải)",
            "slideup": "Slide Up (Trượt lên trên)",
            "slidedown": "Slide Down (Trượt xuống dưới)",
            "wipeleft": "Wipe Left (Quét sang trái)",
            "wiperight": "Wipe Right (Quét sang phải)",
            "wipeup": "Wipe Up (Quét lên trên)",
            "wipedown": "Wipe Down (Quét xuống dưới)",
            "circleopen": "Circle Open (Vòng tròn mở)",
            "circleclose": "Circle Close (Vòng tròn đóng)",
            "zoomin": "Zoom In (Phóng to cảnh mới)",
            "pixelize": "Pixelize (Vỡ hạt Pixel)",
            "radial": "Radial (Quạt xoay 360°)",
            "none": "Cut (Cắt thẳng / Tắt chuyển cảnh)",
        }.get(self.transition_mode, self.transition_mode)

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QColor("#ffb74d"))
        painter.drawText(QRect(0, y0 + box_h + 2, w, 18), Qt.AlignCenter, f"🔄 {trans_text}")

    def _render_transition(self, painter: QPainter, rect: QRect, from_a_to_b: bool, progress: float) -> None:
        p = min(1.0, max(0.0, progress))
        mode = self.transition_mode

        def draw_from():
            if from_a_to_b:
                self._draw_scene_a(painter, rect)
            else:
                self._draw_scene_b(painter, rect)

        def draw_to():
            if from_a_to_b:
                self._draw_scene_b(painter, rect)
            else:
                self._draw_scene_a(painter, rect)

        if mode == "none":
            if p < 0.5:
                draw_from()
            else:
                draw_to()
            return

        if mode == "fadeblack":
            if p < 0.5:
                draw_from()
                painter.fillRect(rect, QColor(0, 0, 0, int(255 * (p * 2))))
            else:
                draw_to()
                painter.fillRect(rect, QColor(0, 0, 0, int(255 * (1.0 - (p - 0.5) * 2))))
            return

        if mode == "fadewhite":
            if p < 0.5:
                draw_from()
                painter.fillRect(rect, QColor(255, 255, 255, int(255 * (p * 2))))
            else:
                draw_to()
                painter.fillRect(rect, QColor(255, 255, 255, int(255 * (1.0 - (p - 0.5) * 2))))
            return

        if mode in {"slideleft", "slideright", "slideup", "slidedown"}:
            offset_x = 0
            offset_y = 0
            if mode == "slideleft":
                offset_x = int(rect.width() * p)
            elif mode == "slideright":
                offset_x = -int(rect.width() * p)
            elif mode == "slideup":
                offset_y = int(rect.height() * p)
            elif mode == "slidedown":
                offset_y = -int(rect.height() * p)

            painter.save()
            painter.translate(-offset_x, -offset_y)
            draw_from()
            if mode == "slideleft":
                painter.translate(rect.width(), 0)
            elif mode == "slideright":
                painter.translate(-rect.width(), 0)
            elif mode == "slideup":
                painter.translate(0, rect.height())
            elif mode == "slidedown":
                painter.translate(0, -rect.height())
            draw_to()
            painter.restore()
            return

        if mode in {"wipeleft", "wiperight", "wipeup", "wipedown", "auto_rich"}:
            draw_from()
            clip = QRect()
            if mode == "wipeleft":
                wipe_w = int(rect.width() * p)
                clip = QRect(rect.right() - wipe_w, rect.top(), wipe_w + 1, rect.height())
            elif mode in {"wiperight", "auto_rich"}:
                wipe_w = int(rect.width() * p)
                clip = QRect(rect.left(), rect.top(), wipe_w, rect.height())
            elif mode == "wipeup":
                wipe_h = int(rect.height() * p)
                clip = QRect(rect.left(), rect.bottom() - wipe_h, rect.width(), wipe_h + 1)
            elif mode == "wipedown":
                wipe_h = int(rect.height() * p)
                clip = QRect(rect.left(), rect.top(), rect.width(), wipe_h)

            if not clip.isEmpty():
                painter.save()
                painter.setClipRect(clip)
                draw_to()
                painter.setPen(QPen(QColor(255, 255, 255, 180), 2))
                if mode in {"wiperight", "auto_rich"}:
                    painter.drawLine(clip.right(), rect.top(), clip.right(), rect.bottom())
                elif mode == "wipeleft":
                    painter.drawLine(clip.left(), rect.top(), clip.left(), rect.bottom())
                elif mode == "wipedown":
                    painter.drawLine(rect.left(), clip.bottom(), rect.right(), clip.bottom())
                elif mode == "wipeup":
                    painter.drawLine(rect.left(), clip.top(), rect.right(), clip.top())
                painter.restore()
            return

        if mode == "circleopen":
            draw_from()
            max_r = math.hypot(rect.width() / 2, rect.height() / 2)
            c_path = QPainterPath()
            c_path.addEllipse(QPointF(rect.center().x(), rect.center().y()), max_r * p, max_r * p)
            painter.save()
            painter.setClipPath(c_path)
            draw_to()
            painter.restore()
            return

        if mode == "circleclose":
            draw_to()
            max_r = math.hypot(rect.width() / 2, rect.height() / 2)
            c_path = QPainterPath()
            c_path.addEllipse(QPointF(rect.center().x(), rect.center().y()), max_r * (1.0 - p), max_r * (1.0 - p))
            painter.save()
            painter.setClipPath(c_path)
            draw_from()
            painter.restore()
            return

        if mode == "zoomin":
            draw_from()
            painter.save()
            scale = max(0.01, p)
            painter.translate(rect.center().x(), rect.center().y())
            painter.scale(scale, scale)
            painter.translate(-rect.center().x(), -rect.center().y())
            painter.setOpacity(min(1.0, p * 1.2))
            draw_to()
            painter.restore()
            return

        if mode == "pixelize":
            draw_from()
            painter.save()
            painter.setOpacity(p)
            draw_to()
            painter.restore()
            if 0.05 < p < 0.95:
                pixel_size = max(4, int(20 * math.sin(p * math.pi)))
                painter.setPen(QColor(0, 0, 0, 45))
                for px in range(rect.left(), rect.right(), pixel_size):
                    painter.drawLine(px, rect.top(), px, rect.bottom())
                for py in range(rect.top(), rect.bottom(), pixel_size):
                    painter.drawLine(rect.left(), py, rect.right(), py)
            return

        if mode == "radial":
            draw_from()
            c_path = QPainterPath()
            c_path.moveTo(rect.center().x(), rect.center().y())
            c_path.arcTo(QRectF(rect.adjusted(-rect.width(), -rect.height(), rect.width(), rect.height())), 90, -int(360 * p))
            c_path.closeSubpath()
            painter.save()
            painter.setClipPath(c_path)
            draw_to()
            painter.restore()
            return

        if mode == "auto_dynamic":
            cycle = int(self._anim_t / 3.2) % 4
            if cycle == 0:
                offset = int(rect.width() * p)
                painter.save(); painter.translate(-offset, 0); draw_from(); painter.translate(rect.width(), 0); draw_to(); painter.restore()
            elif cycle == 1:
                draw_from()
                max_r = math.hypot(rect.width() / 2, rect.height() / 2)
                c_path = QPainterPath()
                c_path.addEllipse(QPointF(rect.center().x(), rect.center().y()), max_r * p, max_r * p)
                painter.save(); painter.setClipPath(c_path); draw_to(); painter.restore()
            elif cycle == 2:
                draw_from()
                painter.save()
                scale = max(0.01, p)
                painter.translate(rect.center().x(), rect.center().y()); painter.scale(scale, scale); painter.translate(-rect.center().x(), -rect.center().y())
                painter.setOpacity(min(1.0, p * 1.2))
                draw_to()
                painter.restore()
            else:
                draw_from()
                wipe_w = int(rect.width() * p)
                if wipe_w > 0:
                    clip = QRect(rect.left(), rect.top(), wipe_w, rect.height())
                    painter.save(); painter.setClipRect(clip); draw_to(); painter.restore()
            return

        # Default / auto_soft / fade / dissolve
        draw_from()
        painter.save()
        painter.setOpacity(p)
        draw_to()
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
        self._lock_emit = True
        self._preview_player = QMediaPlayer(self)
        self._preview_audio_output = QAudioOutput(self)
        self._preview_player.setAudioOutput(self._preview_audio_output)
        self._preview_player.playbackStateChanged.connect(self._on_preview_player_state_changed)
        self._build_ui()
        self.load_settings(settings)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

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
        outer.addLayout(save_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 8, 0)
        root.setSpacing(6)

        root.addWidget(CollapsibleBox("Intro / Outro", self._build_extra_group(), collapsed=False))
        root.addWidget(CollapsibleBox("Text Overlay", self._build_text_group(), collapsed=True))
        root.addWidget(CollapsibleBox("Phụ đề Video (Subtitle)", self._build_subtitle_group(), collapsed=False))
        root.addWidget(CollapsibleBox("Nhạc nền (Background Music)", self._build_background_music_group(), collapsed=True))
        root.addWidget(CollapsibleBox("Audio quảng bá / chèn giữa video", self._build_promo_audio_group(), collapsed=True))
        root.addWidget(CollapsibleBox("Chuyển động & Chuyển cảnh", self._build_effect_audio_group(), collapsed=False))
        root.addWidget(CollapsibleBox("Export Setting", self._build_export_group(), collapsed=False))
        root.addWidget(CollapsibleBox("Hiệu năng / CPU / GPU", self._build_performance_group(), collapsed=True))

        root.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

    def _refresh_preview(self) -> None:
        pass

    def save_settings_action(self) -> None:
        settings = self.collect_settings()
        self.settings = settings
        self.settings_changed.emit(settings)
        self.save_status_label.setText("✔ Đã lưu cấu hình!")
        QTimer.singleShot(2500, lambda: self.save_status_label.setText("Sẵn sàng"))

    def _build_extra_group(self) -> QGroupBox:
        group = QGroupBox()
        form = QFormLayout(group)
        self.intro_edit = self._file_row(form, "Intro", "Chọn intro", "Video (*.mp4 *.mov *.mkv)")

        self.intro_mode_combo = QComboBox()
        self.intro_mode_combo.addItem("Nối tiếp trước MP3 (Phát xong Intro mới tới nội dung chính)", "sequential")
        self.intro_mode_combo.addItem("Đè lên đầu MP3 (MP3 phát từ 0:00, Intro chỉ đè hình ảnh mở đầu)", "overlay")
        form.addRow("Chế độ Intro:", self.intro_mode_combo)

        self.outro_edit = self._file_row(form, "Outro", "Chọn outro", "Video (*.mp4 *.mov *.mkv)")

        self.filter_bgm_after_30s_cb = QCheckBox("Tự động giảm/lọc bỏ nhạc nền sau 30s đầu (Giữ nguyên giọng đọc & SFX)")
        self.filter_bgm_after_30s_cb.setToolTip("Khi bật: 30s đầu giữ nguyên 100% âm thanh gốc (bao gồm nhạc dạo / voice intro). Từ giây 30 trở đi sẽ lọc giảm nhạc nền giúp lời đọc rõ nét và giữ SFX.")
        form.addRow("Lọc nhạc sau 30s:", self.filter_bgm_after_30s_cb)

        note_label = QLabel("💡 <i>Logo, Watermark, Huy hiệu & Lớp phủ đồ họa hiện được quản lý trực quan tại tab <b>Studio Layout</b>.</i>")
        note_label.setStyleSheet("color: #88c0d0; font-size: 11px;")
        form.addRow(note_label)

        self._connect_change_widgets(self.intro_edit, self.intro_mode_combo, self.outro_edit, self.filter_bgm_after_30s_cb)
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

        auto_row = QHBoxLayout()
        self.sub_auto_transcribe = QCheckBox("⚡ Tự động quét giọng nói & tạo phụ đề khi Render (Whisper AI)")
        self.sub_auto_transcribe.setStyleSheet("color: #ffca28; font-weight: bold;")
        self.sub_auto_transcribe.setToolTip("Khi bật, lúc nhấn 'Chạy render' hệ thống sẽ tự động nghe MP3 theo đúng ngôn ngữ đã chọn để tạo file .srt rồi gắn vào video.")

        def _on_sub_enabled_changed(checked: bool):
            if checked and not self.sub_folder_edit.text().strip() and not self.sub_auto_transcribe.isChecked():
                self.sub_auto_transcribe.setChecked(True)
        self.sub_enabled.toggled.connect(_on_sub_enabled_changed)

        self.sub_whisper_lang = QComboBox()
        self.sub_whisper_lang.addItem("🌐 Tự động nhận diện (Auto Detect)", "auto")
        self.sub_whisper_lang.addItem("🇵🇭 Philippines (Tagalog / Filipino)", "tl")
        self.sub_whisper_lang.addItem("🇸🇬 Singapore / Mã Lai (Malay)", "ms")
        self.sub_whisper_lang.addItem("🇹🇭 Thái Lan (Thai)", "th")
        self.sub_whisper_lang.addItem("🇻🇳 Tiếng Việt (Vietnamese)", "vi")
        self.sub_whisper_lang.addItem("🇺🇸 Tiếng Anh (English)", "en")
        self.sub_whisper_lang.addItem("🇨🇳 Tiếng Trung (Chinese)", "zh")
        self.sub_whisper_lang.addItem("🇯🇵 Tiếng Nhật (Japanese)", "ja")
        self.sub_whisper_lang.addItem("🇰🇷 Tiếng Hàn (Korean)", "ko")
        self.sub_whisper_lang.addItem("🇮🇩 Indonesia (Bahasa)", "id")
        self.sub_whisper_lang.addItem("🇪🇸 Tây Ban Nha (Spanish)", "es")
        self.sub_whisper_lang.addItem("🇧🇷 Bồ Đào Nha (Portuguese)", "pt")
        self.sub_whisper_lang.addItem("🇫🇷 Tiếng Pháp (French)", "fr")
        self.sub_whisper_lang.addItem("🇩🇪 Tiếng Đức (German)", "de")
        self.sub_whisper_lang.addItem("🇷🇺 Tiếng Nga (Russian)", "ru")
        self.sub_whisper_lang.addItem("🇮🇳 Tiếng Hindi (India)", "hi")
        self.sub_whisper_lang.addItem("🇸🇦 Tiếng Ả Rập (Arabic)", "ar")
        self.sub_whisper_lang.setCurrentIndex(0)
        self.sub_whisper_lang.setToolTip("Chọn ngôn ngữ của giọng đọc audio để Whisper AI nhận diện chính xác 100%, không bị nhầm lẫn ngôn ngữ.")

        self.sub_whisper_model = QComboBox()
        self.sub_whisper_model.addItem("turbo (⚡ Large-v3-Turbo - Khuyên dùng, Nhanh & Chính xác nhất)", "turbo")
        self.sub_whisper_model.addItem("medium (Dự phòng - Cân bằng GPU/CPU)", "medium")
        self.sub_whisper_model.setCurrentIndex(0)

        self.sub_check_model_btn = QPushButton("🔍 Kiểm tra GPU")
        self.sub_check_model_btn.setToolTip("Kiểm tra khả năng tương thích và nạp thử model trên GPU NVIDIA trước khi render để đảm bảo 100% không bị lỗi.")
        self.sub_check_model_btn.clicked.connect(self._check_whisper_gpu_model)

        auto_row.addWidget(self.sub_auto_transcribe, 3)
        auto_row.addWidget(QLabel("Ngôn ngữ:"))
        auto_row.addWidget(self.sub_whisper_lang, 2)
        auto_row.addWidget(QLabel("Model AI:"))
        auto_row.addWidget(self.sub_whisper_model, 2)
        auto_row.addWidget(self.sub_check_model_btn, 1)

        # Hàng chọn Kiểu hiển thị phụ đề (3 chế độ)
        mode_row = QHBoxLayout()
        self.sub_mode_combo = QComboBox()
        self.sub_mode_combo.addItem("📜 Cuộn 2 dòng (Truyện dài / Podcast - Dễ đọc nhất)", "rolling_2line")
        self.sub_mode_combo.addItem("🎬 Chuẩn điện ảnh (Cụm câu trọn vẹn + Giữ đệm tối thiểu 2.5s)", "cinema_hold")
        self.sub_mode_combo.addItem("✨ Karaoke Highlight (Shorts / TikTok - Sáng từng từ)", "karaoke_highlight")
        self.sub_mode_combo.setToolTip("Chọn cách hiển thị phụ đề:\n- Cuộn 2 dòng: Giữ câu cũ ở trên, câu mới ở dưới giúp đọc kịp\n- Chuẩn điện ảnh: Giữ câu tối thiểu 2.5s không bị mất vội\n- Karaoke Highlight: Sáng từng từ theo nhịp giọng đọc")
        
        self.sub_highlight_color_btn = QPushButton("🎨 Chọn Màu Highlight...")
        self.sub_highlight_color_btn.setFixedWidth(160)
        self.sub_highlight_color_btn.clicked.connect(self._choose_sub_highlight_color)
        self.sub_highlight_color_edit = QLineEdit("#FFE600")
        self.sub_highlight_color_edit.setFixedWidth(85)
        self.sub_highlight_color_edit.textChanged.connect(self._update_sub_highlight_btn_style)

        mode_row.addWidget(self.sub_mode_combo, 2)
        self.sub_highlight_widget = QWidget()
        hw_layout = QHBoxLayout(self.sub_highlight_widget)
        hw_layout.setContentsMargins(0, 0, 0, 0)
        hw_layout.addWidget(QLabel("Màu Highlight:"))
        hw_layout.addWidget(self.sub_highlight_color_edit)
        hw_layout.addWidget(self.sub_highlight_color_btn)
        mode_row.addWidget(self.sub_highlight_widget, 1)

        self.sub_mode_combo.currentIndexChanged.connect(self._on_sub_mode_changed)

        self.sub_enhance_voice_cb = QCheckBox("⚡ Lọc tăng cường dải tần giọng nói DSP (Khuyên dùng - Quét nhanh & chống nuốt chữ)")
        self.sub_enhance_voice_cb.setChecked(True)
        self.sub_enhance_voice_cb.setToolTip("Khi bật, audio sẽ được lọc dải tần giọng nói qua DSP/FFmpeg để Whisper AI nhận diện phụ đề chuẩn xác 100%, không bị tiếng nhạc nền làm sót câu chữ.")

        self.sub_whisper_keywords = QPlainTextEdit()
        self.sub_whisper_keywords.setFixedHeight(50)
        self.sub_whisper_keywords.setPlaceholderText("Nhập các từ khóa, tên riêng, câu cửa miệng... cách nhau bởi dấu phẩy (Ví dụ: AYNA WOW, PINOY LAUGH RADIO, ILOCANO, NALAKA A PAGKWARTAAN)")
        self.sub_whisper_keywords.setToolTip("Mớm từ khóa ngữ cảnh cho Whisper AI (Initial Prompt) để tránh hiện tượng dịch sai từ riêng thành các âm vô nghĩa.")

        form.addRow("Trạng thái", self.sub_enabled)
        form.addRow("Kiểu hiển thị", mode_row)
        form.addRow("Quét Sub tự động", auto_row)
        form.addRow("Từ khóa AI Prompt", self.sub_whisper_keywords)
        form.addRow("Tăng cường AI", self.sub_enhance_voice_cb)
        form.addRow("Thư mục Sub (.srt)", folder_row)

        note_label = QLabel("💡 <i>Vị trí hiển thị, phông chữ, cỡ chữ, màu sắc, viền, độ dày và căn lề phụ đề hiện được quản lý trực quan tại tab <b>Studio Layout</b>.</i>")
        note_label.setStyleSheet("color: #88c0d0; font-size: 11px;")
        form.addRow(note_label)

        layout.addLayout(form)

        for w in (self.sub_enabled, self.sub_auto_transcribe, self.sub_whisper_lang, self.sub_whisper_model, self.sub_enhance_voice_cb, self.sub_whisper_keywords, self.sub_folder_edit, self.sub_mode_combo, self.sub_highlight_color_edit):
            if hasattr(w, "stateChanged"):
                w.stateChanged.connect(lambda: self._emit())
            elif hasattr(w, "currentIndexChanged"):
                w.currentIndexChanged.connect(lambda: self._emit())
            elif hasattr(w, "textChanged"):
                w.textChanged.connect(lambda: self._emit())

        self._on_sub_mode_changed()
        self._update_sub_highlight_btn_style()
        return group

    def _check_whisper_gpu_model(self) -> None:
        import threading
        model_name = self.sub_whisper_model.currentData() if hasattr(self, "sub_whisper_model") else "turbo"
        self.sub_check_model_btn.setEnabled(False)
        self.sub_check_model_btn.setText("⏳ Đang kiểm tra...")

        def _bg():
            ok, msg = preflight_whisper_model(model_name)
            def _done():
                self.sub_check_model_btn.setEnabled(True)
                self.sub_check_model_btn.setText("🔍 Kiểm tra GPU")
                if ok:
                    QMessageBox.information(
                        self,
                        "Kiểm tra Model & GPU thành công",
                        f"✅ Model Whisper [{model_name}] hoạt động 100% hoàn hảo trên GPU NVIDIA!\n\n"
                        f"• Chi tiết: {msg}\n"
                        f"• Chế độ: PyTorch CUDA GPU (fp16 Native)\n"
                        f"• Đã sẵn sàng phục vụ render video không lo phát sinh lỗi."
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "Cảnh báo tương thích GPU",
                        f"⚠️ Model [{model_name}] gặp cảnh báo trên GPU:\n{msg}\n\n"
                        f"Vui lòng kiểm tra lại kết nối mạng để tải weights hoặc cấu hình GPU."
                    )
            QTimer.singleShot(0, _done)

        threading.Thread(target=_bg, daemon=True).start()


    def _on_sub_mode_changed(self) -> None:
        if hasattr(self, "sub_highlight_widget") and hasattr(self, "sub_mode_combo"):
            is_karaoke = (self.sub_mode_combo.currentData() == "karaoke_highlight")
            self.sub_highlight_widget.setVisible(is_karaoke)

    def _update_sub_highlight_btn_style(self) -> None:
        if hasattr(self, "sub_highlight_color_btn") and hasattr(self, "sub_highlight_color_edit"):
            c = self.sub_highlight_color_edit.text().strip() or "#FFE600"
            self.sub_highlight_color_btn.setStyleSheet(f"background-color: {c}; color: #000000; font-weight: bold; border-radius: 3px;")

    def _choose_sub_highlight_color(self) -> None:
        current_c = QColor(self.sub_highlight_color_edit.text().strip() or "#FFE600")
        color = QColorDialog.getColor(current_c, self, "Chọn màu Highlight Karaoke")
        if color.isValid():
            self.sub_highlight_color_edit.setText(color.name().upper())
            self._update_sub_highlight_btn_style()
            self._emit()

    def _choose_sub_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục chứa file phụ đề (.srt)", self.sub_folder_edit.text().strip())
        if folder:
            self.sub_folder_edit.setText(folder)
            self._emit()

    def _choose_sub_font_color(self) -> None:
        pass

    def _choose_sub_outline_color(self) -> None:
        pass

    def _update_sub_color_previews(self) -> None:
        pass

    def _on_sub_style_changed(self) -> None:
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
        self.effect_combo.addItem("✨ Xoay tua thông minh (Auto Smart)", "auto_smart")
        self.effect_combo.addItem("🌟 Nhẹ nhàng (Auto Light)", "auto_light")
        self.effect_combo.addItem("🔥 Đa dạng (Auto Rich)", "auto_rich")
        self.effect_combo.addItem("🔍 Zoom In (Tâm)", "zoom_in_center")
        self.effect_combo.addItem("🔎 Zoom Out (Tâm)", "zoom_out_center")
        self.effect_combo.addItem("↖️ Zoom In (Góc Trên Trái)", "zoom_in_top_left")
        self.effect_combo.addItem("↗️ Zoom In (Góc Trên Phải)", "zoom_in_top_right")
        self.effect_combo.addItem("↙️ Zoom In (Góc Dưới Trái)", "zoom_in_bottom_left")
        self.effect_combo.addItem("↘️ Zoom In (Góc Dưới Phải)", "zoom_in_bottom_right")
        self.effect_combo.addItem("⬅️ Pan Sang Trái", "pan_left")
        self.effect_combo.addItem("➡️ Pan Sang Phải", "pan_right")
        self.effect_combo.addItem("⬆️ Pan Lên Trên", "pan_up")
        self.effect_combo.addItem("⬇️ Pan Xuống Dưới", "pan_down")
        self.effect_combo.addItem("💓 Smooth Pulse (Nhịp thở)", "smooth_pulse")
        self.effect_combo.addItem("🔄 Loop Pan & Zoom", "loop_pan_zoom")
        self.effect_combo.addItem("⛔ Tắt hiệu ứng (Ảnh tĩnh)", "none")
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
        self.transition_combo.addItem("✨ Auto Mượt mà (Soft Blend)", "auto_soft")
        self.transition_combo.addItem("⚡ Auto Đa dạng (All FX)", "auto_dynamic")
        self.transition_combo.addItem("🌟 Auto Light (Cơ bản)", "auto_light")
        self.transition_combo.addItem("🔥 Auto Rich (Phong phú)", "auto_rich")
        self.transition_combo.addItem("🌫️ Crossfade (Mờ dần)", "fade")
        self.transition_combo.addItem("⬛ Fade to Black (Đen dần)", "fadeblack")
        self.transition_combo.addItem("⬜ Fade to White (Trắng chớp)", "fadewhite")
        self.transition_combo.addItem("💫 Dissolve (Hòa tan)", "dissolve")
        self.transition_combo.addItem("⬅️ Slide Left (Trượt trái)", "slideleft")
        self.transition_combo.addItem("➡️ Slide Right (Trượt phải)", "slideright")
        self.transition_combo.addItem("⬆️ Slide Up (Trượt lên)", "slideup")
        self.transition_combo.addItem("⬇️ Slide Down (Trượt xuống)", "slidedown")
        self.transition_combo.addItem("🧹 Wipe Left (Quét trái)", "wipeleft")
        self.transition_combo.addItem("🧹 Wipe Right (Quét phải)", "wiperight")
        self.transition_combo.addItem("🧹 Wipe Up (Quét lên)", "wipeup")
        self.transition_combo.addItem("🧹 Wipe Down (Quét xuống)", "wipedown")
        self.transition_combo.addItem("⭕ Circle Open (Vòng tròn)", "circleopen")
        self.transition_combo.addItem("⚫ Circle Close", "circleclose")
        self.transition_combo.addItem("🔍 Zoom In", "zoomin")
        self.transition_combo.addItem("👾 Pixelize (Vỡ hạt)", "pixelize")
        self.transition_combo.addItem("🌀 Radial (Quạt xoay)", "radial")
        self.transition_combo.addItem("✂️ Cut (Tắt chuyển cảnh)", "none")
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
        self.quality_combo.addItem("Tiết kiệm dung lượng (~2.5 Mbps - Audio/Truyện dài nhẹ máy)", "economy")
        self.quality_combo.addItem("Chuẩn YouTube 1080p (~6.0 Mbps - Sắc nét phổ thông, Khuyên dùng)", "standard")
        self.quality_combo.addItem("Chất lượng cao HD (~10.0 Mbps - Cực nét cho chữ & đồ họa)", "high")
        self.quality_combo.addItem("Chất lượng Siêu cao (~16.0 Mbps - Master chất lượng gốc)", "ultra")
        self.quality_combo.addItem("Tùy chỉnh Bitrate (Nhập Kbps mong muốn)", "custom")

        self.custom_bitrate_spin = QSpinBox()
        self.custom_bitrate_spin.setRange(500, 50000)
        self.custom_bitrate_spin.setSingleStep(500)
        self.custom_bitrate_spin.setValue(6000)
        self.custom_bitrate_spin.setSuffix(" kbps")

        self.custom_bitrate_label = QLabel("Bitrate tùy chỉnh:")

        self.estimated_size_label = QLabel()
        self.estimated_size_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 11px;")

        out_row = QHBoxLayout()
        self.output_edit = QLineEdit("output")
        self.output_btn = QPushButton("Chọn...")
        self.output_btn.clicked.connect(self.choose_output_folder)
        out_row.addWidget(self.output_edit)
        out_row.addWidget(self.output_btn)

        form.addRow("Tỉ lệ khung hình", self.ratio_combo)
        form.addRow("FPS", self.fps_spin)
        form.addRow("Chất lượng xuất", self.quality_combo)
        form.addRow(self.custom_bitrate_label, self.custom_bitrate_spin)
        form.addRow("Ước tính dung lượng", self.estimated_size_label)
        form.addRow("Thư mục xuất", out_row)

        self.quality_combo.currentIndexChanged.connect(self._on_quality_changed)
        self.fps_spin.valueChanged.connect(self._update_estimated_size)
        self.ratio_combo.currentIndexChanged.connect(self._update_estimated_size)
        self.custom_bitrate_spin.valueChanged.connect(self._update_estimated_size)

        self._connect_change_widgets(
            self.ratio_combo, self.fps_spin, self.quality_combo,
            self.custom_bitrate_spin, self.output_edit
        )
        self._on_quality_changed()
        return group

    def _on_quality_changed(self) -> None:
        if hasattr(self, "quality_combo") and hasattr(self, "custom_bitrate_label") and hasattr(self, "custom_bitrate_spin"):
            is_custom = (self.quality_combo.currentData() == "custom")
            self.custom_bitrate_label.setVisible(is_custom)
            self.custom_bitrate_spin.setVisible(is_custom)
        self._update_estimated_size()
        self._emit()

    def _update_estimated_size(self) -> None:
        if not hasattr(self, "quality_combo") or not hasattr(self, "estimated_size_label"):
            return
        q = str(self.quality_combo.currentData() or "standard").lower()
        if q in ["economy", "low", "draft"]:
            base_kbps = 2500
        elif q == "high":
            base_kbps = 10000
        elif q == "ultra":
            base_kbps = 16000
        elif q == "custom":
            base_kbps = self.custom_bitrate_spin.value() if hasattr(self, "custom_bitrate_spin") else 6000
        else:
            base_kbps = 6000

        fps = self.fps_spin.value() if hasattr(self, "fps_spin") else 30
        fps_scale = min(1.30, max(0.70, fps / 30.0))
        video_kbps = base_kbps * fps_scale
        total_kbps = video_kbps + 192  # Audio AAC 192k

        # Tính dung lượng: (total_kbps * 1000 bits * seconds) / (8 * 1024 * 1024 * 1024)
        size_1h_gb = (total_kbps * 1000 * 3600) / (8 * (1024**3))
        size_2h_gb = size_1h_gb * 2.0

        self.estimated_size_label.setText(
            f"💡 Dự kiến: ~{size_1h_gb:.1f} GB / 1 giờ  (~{size_2h_gb:.1f} GB / 2 giờ) — Video chuẩn nét YouTube 1080p"
        )

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

        self.clean_cache_btn = QPushButton("🧹 Dọn dẹp Cache & Rác tạm (Giải phóng dung lượng)")
        self.clean_cache_btn.setStyleSheet(
            "QPushButton { background-color: #2e7d32; color: white; font-weight: bold; padding: 6px 12px; border-radius: 4px; } "
            "QPushButton:hover { background-color: #388e3c; }"
        )
        self.clean_cache_btn.clicked.connect(self.clean_temp_caches)

        form.addRow("Bộ mã hóa (Encoder)", self.encoder_combo)
        form.addRow("Render song song (Jobs)", self.max_parallel_spin)
        form.addRow("Số luồng CPU (Threads)", self.cpu_threads_spin)
        form.addRow("Batch chuyển cảnh", self.transition_batch_spin)
        form.addRow("Thư mục Temp riêng", temp_row)
        form.addRow("Dọn temp thành công", self.auto_clear_temp_checkbox)
        form.addRow("Giữ temp khi lỗi", self.keep_temp_on_error_checkbox)
        form.addRow("Fallback về CPU", self.allow_cpu_fallback_checkbox)
        form.addRow("Preflight test GPU", self.gpu_preflight_checkbox)
        form.addRow("Dọn rác hệ thống", self.clean_cache_btn)

        self._connect_change_widgets(
            self.encoder_combo, self.max_parallel_spin, self.cpu_threads_spin,
            self.transition_batch_spin, self.temp_folder_edit,
            self.auto_clear_temp_checkbox, self.keep_temp_on_error_checkbox,
            self.allow_cpu_fallback_checkbox, self.gpu_preflight_checkbox
        )
        return group

    def clean_temp_caches(self) -> None:
        from core.paths import cleanup_all_temp_caches
        reply = QMessageBox.question(
            self,
            "Xác nhận dọn dẹp Cache",
            "Bạn có chắc muốn dọn sạch toàn bộ file tạm _avr_temp, cache Python và rác hệ thống?\n\nThao tác này giúp giải phóng dung lượng ổ đĩa và tăng tốc độ xử lý của tool.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        custom_temp = self.temp_folder_edit.text().strip() if hasattr(self, "temp_folder_edit") else ""
        out_folder = self.output_edit.text().strip() if hasattr(self, "output_edit") else ""
        res = cleanup_all_temp_caches(custom_temp_dir=custom_temp, output_dir=out_folder)
        freed = res.get("freed_formatted", "0 B")
        files = res.get("deleted_files", 0)
        folders = res.get("deleted_folders", 0)
        QMessageBox.information(
            self,
            "Dọn dẹp hoàn tất",
            f"🧹 Đã dọn dẹp rác & cache thành công!\n\n• Dung lượng giải phóng: {freed}\n• Đã xóa: {files} file tạm, {folders} thư mục cache.",
        )

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
            "intro_mode": self.intro_mode_combo.currentData() if hasattr(self, "intro_mode_combo") else "sequential",
            "outro_file": self.outro_edit.text().strip(),
            "filter_bgm_after_30s": self.filter_bgm_after_30s_cb.isChecked() if hasattr(self, "filter_bgm_after_30s_cb") else False,
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
                "sub_mode": self.sub_mode_combo.currentData() if hasattr(self, "sub_mode_combo") else "rolling_2line",
                "highlight_color": self.sub_highlight_color_edit.text().strip() or "#FFE600" if hasattr(self, "sub_highlight_color_edit") else "#FFE600",
                "auto_transcribe": self.sub_auto_transcribe.isChecked() if hasattr(self, "sub_auto_transcribe") else False,
                "whisper_enhance_voice": self.sub_enhance_voice_cb.isChecked() if hasattr(self, "sub_enhance_voice_cb") else True,
                "whisper_keywords": self.sub_whisper_keywords.toPlainText().strip() if hasattr(self, "sub_whisper_keywords") else "",
                "whisper_language": self.sub_whisper_lang.currentData() if hasattr(self, "sub_whisper_lang") else "auto",
                "whisper_model": self.sub_whisper_model.currentData() if hasattr(self, "sub_whisper_model") else "turbo",
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
                "custom_bitrate_kbps": self.custom_bitrate_spin.value() if hasattr(self, "custom_bitrate_spin") else 2200,
                "format": "mp4",
                "output_folder": self.output_edit.text().strip() or "output",
            },
        })
        return settings

    def load_settings(self, settings: Dict[str, Any]) -> None:
        self._lock_emit = True
        self.settings = settings

        self.intro_edit.setText(settings.get("intro_file", ""))
        if hasattr(self, "intro_mode_combo"):
            self._set_combo_by_data(self.intro_mode_combo, settings.get("intro_mode", "sequential"))
        self.outro_edit.setText(settings.get("outro_file", ""))
        if hasattr(self, "filter_bgm_after_30s_cb"):
            self.filter_bgm_after_30s_cb.setChecked(bool(settings.get("filter_bgm_after_30s", False)))

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
        effect_mode = settings.get("effect_mode", "auto_smart")
        im_on = bool(settings.get("image_motion_enabled", effect_mode != "none"))
        self.image_motion_enabled.setChecked(im_on)
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

        transition_mode = settings.get("transition_mode", "auto_soft")
        tr_on = bool(settings.get("transition_enabled", transition_mode != "none"))
        self.transition_enabled.setChecked(tr_on)
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
            if hasattr(self, "sub_mode_combo"):
                self._set_combo_by_data(self.sub_mode_combo, sub_cfg.get("sub_mode", "rolling_2line"))
            if hasattr(self, "sub_highlight_color_edit"):
                self.sub_highlight_color_edit.setText(str(sub_cfg.get("highlight_color", "#FFE600") or "#FFE600"))
                self._update_sub_highlight_btn_style()
            if hasattr(self, "sub_auto_transcribe"):
                self.sub_auto_transcribe.setChecked(bool(sub_cfg.get("auto_transcribe", False)))
            if hasattr(self, "sub_enhance_voice_cb"):
                self.sub_enhance_voice_cb.setChecked(bool(sub_cfg.get("whisper_enhance_voice", True)))
            if hasattr(self, "sub_whisper_keywords"):
                self.sub_whisper_keywords.setPlainText(str(sub_cfg.get("whisper_keywords", "") or ""))
            if hasattr(self, "sub_whisper_lang"):
                self._set_combo_by_data(self.sub_whisper_lang, sub_cfg.get("whisper_language", "auto"))
            if hasattr(self, "sub_whisper_model"):
                self._set_combo_by_data(self.sub_whisper_model, sub_cfg.get("whisper_model", "turbo"))
            self.sub_folder_edit.setText(str(sub_cfg.get("folder", "") or ""))

        export = settings.get("export", {})
        self.fps_spin.setValue(int(export.get("fps", 30)))
        self.output_edit.setText(export.get("output_folder", "output"))
        self._set_ratio(export.get("width", 1920), export.get("height", 1080))
        quality_val = str(export.get("quality", "standard") or "standard").lower()
        if quality_val in ["draft", "low"]:
            quality_val = "economy"
        self._set_combo_by_data(self.quality_combo, quality_val)
        if hasattr(self, "custom_bitrate_spin"):
            self.custom_bitrate_spin.setValue(int(export.get("custom_bitrate_kbps", 2200) or 2200))
        self._on_quality_changed()

        self._update_effect_demo()
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
            if widget is not self:
                widget.setEnabled(not locked)

    def _set_ratio(self, width: int, height: int) -> None:
        for i in range(self.ratio_combo.count()):
            data = self.ratio_combo.itemData(i)
            if data and data[0] == width and data[1] == height:
                self.ratio_combo.setCurrentIndex(i)
                return

    @staticmethod
    def _set_combo_by_data(combo: QComboBox, value: Any) -> None:
        target = str(value or "").strip()
        if target in ["large-v3-turbo", "whisper-large-v3-turbo", "large-v2", "large"]:
            target = "turbo"
        for i in range(combo.count()):
            item_d = str(combo.itemData(i))
            if item_d == target or combo.itemData(i) == value:
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
        settings = self.collect_settings()
        self.settings = settings
        self.settings_changed.emit(settings)
