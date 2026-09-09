"""Module sinh và quản lý video particle overlay / layer mask (bong bóng, hạt sương, lông vũ, v.v.)."""

from __future__ import annotations

import math
import random
import subprocess
from pathlib import Path
from typing import Dict, Any

from .paths import find_binary

OVERLAYS_DIR = Path(__file__).resolve().parents[1] / "assets" / "overlays"


def ensure_default_overlays() -> None:
    """Tự động kiểm tra và sinh các file overlay hạt rơi mặc định nếu chưa có."""
    OVERLAYS_DIR.mkdir(parents=True, exist_ok=True)
    targets = ["bubbles.mp4", "dew_particles.mp4", "feathers.mp4", "bokeh.mp4", "rain.mp4"]
    missing = [t for t in targets if not (OVERLAYS_DIR / t).exists()]
    if not missing:
        return

    try:
        from PySide6.QtGui import (
            QImage, QPainter, QColor, QRadialGradient, QLinearGradient,
            QBrush, QPen, QPainterPath
        )
        from PySide6.QtCore import Qt, QPointF
    except ImportError:
        return

    ffmpeg = _get_ffmpeg()
    if not ffmpeg:
        return

    width, height, fps, seconds = 1280, 720, 30, 8
    total_frames = fps * seconds

    def _gen(filename: str, draw_dict: Dict[str, Any], count: int, seed: int = 42) -> None:
        out_path = OVERLAYS_DIR / filename
        cmd = [
            ffmpeg, "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{width}x{height}", "-pix_fmt", "rgba", "-r", str(fps),
            "-i", "-", "-c:v", "h264_nvenc", "-preset", "p2", "-pix_fmt", "yuv420p",
            str(out_path)
        ]
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            cmd[10] = "libx264"
            cmd[12] = "veryfast"
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        img = QImage(width, height, QImage.Format_RGBA8888)
        random.seed(seed)
        items = [draw_dict["init"](width, height) for _ in range(count)]

        for frame_idx in range(total_frames):
            t = (frame_idx / total_frames) * seconds
            img.fill(QColor(0, 0, 0, 255))
            painter = QPainter(img)
            painter.setRenderHint(QPainter.Antialiasing, True)
            for item in items:
                draw_dict["draw"](painter, item, t, seconds, width, height)
            painter.end()
            proc.stdin.write(img.bits().tobytes())
        proc.stdin.close()
        proc.wait()

    # 1. Bubbles
    if "bubbles.mp4" in missing:
        def init_bubble(w, h):
            return {
                "x": random.uniform(0, w), "y": random.uniform(0, h), "radius": random.uniform(8, 26),
                "speed_y": random.uniform(50, 110), "phase": random.uniform(0, math.pi * 2),
                "wobble_speed": random.uniform(1.5, 3.5), "wobble_amp": random.uniform(12, 28), "alpha": random.uniform(140, 210)
            }
        def draw_bubble(p, b, t, max_t, w, h):
            cur_y = (b["y"] - b["speed_y"] * t) % (h + 60) - 30
            cur_x = (b["x"] + math.sin(t * b["wobble_speed"] + b["phase"]) * b["wobble_amp"]) % w
            r = b["radius"]
            grad = QRadialGradient(cur_x - r * 0.3, cur_y - r * 0.3, r)
            grad.setColorAt(0.0, QColor(220, 240, 255, int(b["alpha"] * 0.6)))
            grad.setColorAt(0.7, QColor(130, 190, 250, int(b["alpha"] * 0.2)))
            grad.setColorAt(0.95, QColor(190, 225, 255, int(b["alpha"] * 0.95)))
            grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cur_x, cur_y), r, r)
            spec = QRadialGradient(cur_x - r * 0.35, cur_y - r * 0.35, r * 0.35)
            spec.setColorAt(0.0, QColor(255, 255, 255, int(b["alpha"] * 0.95)))
            spec.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(spec))
            p.drawEllipse(QPointF(cur_x - r * 0.35, cur_y - r * 0.35), r * 0.28, r * 0.2)
        _gen("bubbles.mp4", {"init": init_bubble, "draw": draw_bubble}, 40)

    # 2. Dew / Snow
    if "dew_particles.mp4" in missing:
        def init_dew(w, h):
            return {
                "x": random.uniform(0, w), "y": random.uniform(0, h), "radius": random.uniform(2.5, 7.5),
                "speed_y": random.uniform(25, 65), "speed_x": random.uniform(-15, 15), "twinkle_speed": random.uniform(2.0, 5.0),
                "phase": random.uniform(0, math.pi * 2), "alpha_base": random.uniform(160, 240),
                "color_type": random.choice(["cyan", "gold", "white"])
            }
        def draw_dew(p, d, t, max_t, w, h):
            cur_y = (d["y"] + d["speed_y"] * t) % (h + 20) - 10
            cur_x = (d["x"] + d["speed_x"] * t + math.sin(t * 2.0 + d["phase"]) * 15) % w
            twinkle = 0.5 + 0.5 * math.sin(t * d["twinkle_speed"] + d["phase"])
            alpha = int(d["alpha_base"] * (0.4 + 0.6 * twinkle))
            r = d["radius"] * (0.8 + 0.4 * twinkle)
            grad = QRadialGradient(cur_x, cur_y, r * 2.2)
            c = QColor(160, 235, 255, alpha) if d["color_type"] == "cyan" else (QColor(255, 235, 170, alpha) if d["color_type"] == "gold" else QColor(255, 255, 255, alpha))
            grad.setColorAt(0.0, c)
            grad.setColorAt(0.4, QColor(c.red(), c.green(), c.blue(), int(alpha * 0.4)))
            grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cur_x, cur_y), r * 2.2, r * 2.2)
        _gen("dew_particles.mp4", {"init": init_dew, "draw": draw_dew}, 70)

    # 3. Feathers
    if "feathers.mp4" in missing:
        def init_feather(w, h):
            return {
                "x": random.uniform(0, w), "y": random.uniform(0, h), "length": random.uniform(32, 60),
                "speed_y": random.uniform(30, 70), "sway_speed": random.uniform(1.2, 2.5),
                "sway_amp": random.uniform(35, 75), "rot_speed": random.uniform(0.8, 1.8),
                "phase": random.uniform(0, math.pi * 2), "alpha": random.uniform(140, 210)
            }
        def draw_feather(p, f, t, max_t, w, h):
            cur_y = (f["y"] + f["speed_y"] * t) % (h + 100) - 50
            cur_x = (f["x"] + math.sin(t * f["sway_speed"] + f["phase"]) * f["sway_amp"]) % w
            angle = math.sin(t * f["rot_speed"] + f["phase"]) * 45 + math.cos(t * 0.8) * 20
            p.save()
            p.translate(cur_x, cur_y)
            p.rotate(angle)
            L = f["length"]
            W = L * 0.32
            path = QPainterPath()
            path.moveTo(0, -L/2)
            path.cubicTo(W, -L/4, W * 0.8, L/4, 0, L/2)
            path.cubicTo(-W * 0.8, L/4, -W, -L/4, 0, -L/2)
            grad = QLinearGradient(0, -L/2, 0, L/2)
            grad.setColorAt(0.0, QColor(255, 255, 255, int(f["alpha"] * 0.95)))
            grad.setColorAt(0.5, QColor(240, 245, 255, int(f["alpha"] * 0.75)))
            grad.setColorAt(1.0, QColor(220, 230, 245, int(f["alpha"] * 0.3)))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.NoPen)
            p.drawPath(path)
            p.setPen(QPen(QColor(255, 255, 255, int(f["alpha"])), 1.5))
            p.drawLine(0, -L/2, 0, L/2)
            p.restore()
        _gen("feathers.mp4", {"init": init_feather, "draw": draw_feather}, 25)

    # 4. Bokeh
    if "bokeh.mp4" in missing:
        def init_bokeh(w, h):
            return {
                "x": random.uniform(0, w), "y": random.uniform(0, h), "radius": random.uniform(25, 75),
                "speed_y": random.uniform(-20, 20), "speed_x": random.uniform(-20, 20), "pulse_speed": random.uniform(0.8, 2.0),
                "phase": random.uniform(0, math.pi * 2), "color": random.choice([QColor(255, 220, 150), QColor(200, 230, 255), QColor(255, 180, 220)]),
                "alpha_max": random.uniform(90, 160)
            }
        def draw_bokeh(p, b, t, max_t, w, h):
            cur_x = (b["x"] + b["speed_x"] * t) % w
            cur_y = (b["y"] + b["speed_y"] * t) % h
            pulse = 0.5 + 0.5 * math.sin(t * b["pulse_speed"] + b["phase"])
            alpha = int(b["alpha_max"] * (0.3 + 0.7 * pulse))
            r = b["radius"] * (0.85 + 0.3 * pulse)
            grad = QRadialGradient(cur_x, cur_y, r)
            grad.setColorAt(0.0, QColor(b["color"].red(), b["color"].green(), b["color"].blue(), alpha))
            grad.setColorAt(0.7, QColor(b["color"].red(), b["color"].green(), b["color"].blue(), int(alpha * 0.4)))
            grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cur_x, cur_y), r, r)
        _gen("bokeh.mp4", {"init": init_bokeh, "draw": draw_bokeh}, 25)

    # 5. Rain
    if "rain.mp4" in missing:
        def init_rain(w, h):
            return {
                "x": random.uniform(0, w), "y": random.uniform(0, h), "length": random.uniform(30, 65),
                "speed_y": random.uniform(500, 800), "speed_x": random.uniform(-100, -150), "alpha": random.uniform(100, 180)
            }
        def draw_rain(p, r, t, max_t, w, h):
            cur_y = (r["y"] + r["speed_y"] * t) % (h + 80) - 40
            cur_x = (r["x"] + r["speed_x"] * t) % (w + 100) - 50
            p.setPen(QPen(QColor(210, 230, 255, int(r["alpha"])), 1.2))
            p.drawLine(cur_x, cur_y, cur_x + r["length"] * -0.2, cur_y + r["length"])
        _gen("rain.mp4", {"init": init_rain, "draw": draw_rain}, 100)


def get_overlay_file(effect_mode: str, custom_file: str = "") -> Path | None:
    """Trả về đường dẫn file overlay video cho hiệu ứng được chọn."""
    if not effect_mode or effect_mode in {"none", "off"}:
        return None
    if effect_mode == "custom":
        if custom_file and Path(custom_file).exists():
            return Path(custom_file)
        return None
    name_map = {
        "bubbles": "bubbles.mp4",
        "dew_particles": "dew_particles.mp4",
        "dew": "dew_particles.mp4",
        "snow": "dew_particles.mp4",
        "feathers": "feathers.mp4",
        "feather": "feathers.mp4",
        "bokeh": "bokeh.mp4",
        "sparkles": "bokeh.mp4",
        "rain": "rain.mp4",
    }
    target = name_map.get(effect_mode)
    if not target:
        return None
    path = OVERLAYS_DIR / target
    if not path.exists():
        ensure_default_overlays()
    return path if path.exists() else None


def _get_ffmpeg() -> str:
    try:
        return find_binary("ffmpeg.exe")
    except Exception:
        try:
            return find_binary("ffmpeg")
        except Exception:
            return "ffmpeg"
