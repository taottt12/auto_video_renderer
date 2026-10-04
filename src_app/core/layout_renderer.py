import os
import re
import sys
import json
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont

from src_app.core.paths import CACHE_DIR, ASSETS_DIR


def find_font_file(font_name: str, bold: bool = True, italic: bool = False) -> Optional[Path]:
    """Tìm đường dẫn font chuẩn xác trên Windows hoặc thư mục assets của ứng dụng."""
    fname_clean = str(font_name or "Arial").strip().lower()

    # 1. Quét trong thư mục fonts của dự án nếu có
    local_fonts = ASSETS_DIR / "fonts"
    if local_fonts.exists():
        for f in local_fonts.glob("*.*"):
            if f.suffix.lower() in [".ttf", ".otf"] and fname_clean in f.stem.lower():
                return f

    # 2. Quét trong C:/Windows/Fonts
    win_fonts = Path("C:/Windows/Fonts")
    if not win_fonts.exists():
        return None

    # Bản đồ tên font phổ biến sang tên file Windows TTF
    font_map = {
        "arial black": "ariblk.ttf",
        "arial": "arialbd.ttf" if bold else ("ariali.ttf" if italic else "arial.ttf"),
        "montserrat": "Montserrat-Bold.ttf" if bold else "Montserrat-Regular.ttf",
        "montserrat black": "Montserrat-Black.ttf",
        "impact": "impact.ttf",
        "tahoma": "tahomabd.ttf" if bold else "tahoma.ttf",
        "segoe ui": "segoeuib.ttf" if bold else "segoeui.ttf",
        "segoe ui black": "seguibl.ttf",
        "times new roman": "timesbd.ttf" if bold else "times.ttf",
        "roboto": "Roboto-Bold.ttf" if bold else "Roboto-Regular.ttf",
        "helvetica": "arialbd.ttf" if bold else "arial.ttf",
        "verdana": "verdanab.ttf" if bold else "verdana.ttf",
        "comic sans ms": "comicbd.ttf" if bold else "comic.ttf",
        "trebuchet ms": "trebucbd.ttf" if bold else "trebuc.ttf",
        "georgia": "georgiab.ttf" if bold else "georgia.ttf",
    }

    if fname_clean in font_map:
        target = win_fonts / font_map[fname_clean]
        if target.exists():
            return target

    for k, v in font_map.items():
        if k in fname_clean or fname_clean in k:
            target = win_fonts / v
            if target.exists():
                return target

    # Quét trực tiếp theo tên file
    cand = win_fonts / f"{font_name}.ttf"
    if cand.exists():
        return cand
    cand_otf = win_fonts / f"{font_name}.otf"
    if cand_otf.exists():
        return cand_otf

    # Fallback mặc định
    default_font = win_fonts / ("arialbd.ttf" if bold else "arial.ttf")
    return default_font if default_font.exists() else None


def resolve_asset_path(path_str: str) -> Optional[Path]:
    """Tìm file ảnh tài nguyên, tự động đảo ổ đĩa (E: <-> F:) nếu chuyển máy."""
    if not path_str or not str(path_str).strip():
        return None
    p = Path(str(path_str).strip())
    if p.exists():
        return p
    s = str(p)
    for drive in ["F:", "E:", "D:", "C:"]:
        if len(s) > 2 and s[1] == ":":
            candidate = Path(drive + s[2:])
            if candidate.exists():
                return candidate
    return None


def hex_to_rgba(hex_str: str, opacity: float = 1.0) -> Tuple[int, int, int, int]:
    """Chuyển chuỗi màu HEX thành tuple (R, G, B, A)."""
    h = str(hex_str or "#FFFFFF").strip().lstrip("#")
    if len(h) == 3:
        h = "".join([c * 2 for c in h])
    if len(h) == 6:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        a = int(round(max(0.0, min(1.0, opacity)) * 255))
        return (r, g, b, a)
    elif len(h) == 8:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        a = int(round(int(h[6:8], 16) * max(0.0, min(1.0, opacity))))
        return (r, g, b, a)
    # Tên màu thông dụng
    named = {
        "white": (255, 255, 255),
        "black": (0, 0, 0),
        "red": (255, 0, 0),
        "yellow": (255, 255, 0),
        "blue": (0, 0, 255),
        "green": (0, 255, 0),
    }
    base = named.get(h.lower(), (255, 255, 255))
    return (base[0], base[1], base[2], int(round(max(0.0, min(1.0, opacity)) * 255)))


def get_layout_hash(
    layers: List[Dict[str, Any]],
    width: int,
    height: int,
    audio_title: str = "",
) -> str:
    """Tạo mã băm MD5 duy nhất cho bố cục gồm JSON, file ảnh, font và độ phân giải."""
    hasher = hashlib.md5()
    hasher.update(f"{width}x{height}:{audio_title}:v1".encode("utf-8"))

    # Lọc lấy các layer tĩnh
    for l in layers:
        if not l.get("enabled", True):
            continue
        l_str = json.dumps(l, sort_keys=True)
        hasher.update(l_str.encode("utf-8"))

        f_path = str(l.get("file_path", "")).strip()
        if f_path:
            res = resolve_asset_path(f_path)
            if res and res.exists():
                try:
                    mtime = os.path.getmtime(res)
                    size = os.path.getsize(res)
                    hasher.update(f"{res.name}:{mtime}:{size}".encode("utf-8"))
                except Exception:
                    pass

    return hasher.hexdigest()


class LayoutRenderer:
    """Renderer thống nhất cho toàn bộ hệ thống (Preview GUI = Render Video 100% WYSIWYG)."""

    @staticmethod
    def render_canvas(
        layers: List[Dict[str, Any]],
        width: int = 1920,
        height: int = 1080,
        audio_title: str = "",
        preview_mode: bool = False,
        log_fn: Optional[Any] = None,
    ) -> Tuple[Image.Image, List[Dict[str, Any]]]:
        """
        Dựng hình ảnh toàn bộ các layer tĩnh (Ảnh, Logo, Frame, Text tiêu đề, Badge) thành 1 Canvas RGBA duy nhất.
        Trả về:
            canvas (PIL Image RGBA 1920x1080)
            dynamic_layers (danh sách layer động có animation / gif / video mask cần FFmpeg xử lý tiếp)
        """
        _log = log_fn or (lambda msg: None)
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        dynamic_layers: List[Dict[str, Any]] = []

        active_layers = [l for l in layers if isinstance(l, dict) and l.get("enabled", True)]

        for layer in active_layers:
            l_type = str(layer.get("type", "image")).lower()
            in_eff = str(layer.get("in_effect", "none")).lower()
            out_eff = str(layer.get("out_effect", "none")).lower()
            mot_eff = str(layer.get("motion_effect", "none")).lower()
            f_path_raw = str(layer.get("file_path", "")).strip()
            is_gif = (l_type in {"gif", "reaction", "animated_image"}) or f_path_raw.lower().endswith(".gif")

            # Kiểm tra xem layer có hiệu ứng hoạt họa theo thời gian hay không
            has_time_anim = (in_eff != "none" or out_eff != "none" or mot_eff != "none")
            is_dynamic = is_gif or (l_type in {"video_mask"}) or has_time_anim

            # Nếu là GIF động hoặc video mask hoặc layer có hiệu ứng chuyển động theo thời gian:
            # - Khi Render Video: Chuyển sang dynamic_layers để FFmpeg xử lý hoạt họa đa khung hình
            # - Khi Preview Mode: Vẽ khung hình đầu tiên lên Canvas để người dùng nhìn thấy trực quan
            if not preview_mode and is_dynamic:
                dynamic_layers.append(layer)
                continue

            # -------------------------------------------------------------
            # 1. LAYER HÌNH ẢNH (Image / Logo / Watermark / Banner / GIF / Chat Bubble / Badge / Frame / Sticker)
            # -------------------------------------------------------------
            if l_type in {"image", "banner", "logo", "watermark", "chat_bubble", "badge", "frame", "sticker", "reaction", "gif"}:
                if not f_path_raw:
                    continue

                res_path = resolve_asset_path(f_path_raw)
                if not res_path or not res_path.exists():
                    _log(f"⚠️ Không tìm thấy ảnh layer '{layer.get('name')}': {f_path_raw}")
                    continue

                try:
                    with Image.open(res_path) as src_img:
                        # Với GIF ở chế độ Preview, lấy khung hình đầu tiên
                        if is_gif:
                            src_img.seek(0)
                        img = src_img.convert("RGBA")
                        bx = float(layer.get("box_x", 0.0))
                        by = float(layer.get("box_y", 0.0))
                        bw = float(layer.get("box_w", 0.3))
                        bh = float(layer.get("box_h", 0.2))

                        px = int(round(width * bx))
                        py = int(round(height * by))
                        pw = max(8, int(round(width * bw)))
                        ph = max(8, int(round(height * bh)))

                        opacity = float(layer.get("opacity", 1.0) if layer.get("opacity") is not None else 1.0)
                        opacity = max(0.0, min(1.0, opacity))

                        scale_mode = str(layer.get("scale_mode", "stretch")).lower()
                        if scale_mode == "fit":
                            img.thumbnail((pw, ph), Image.Resampling.LANCZOS)
                            offset_x = px + (pw - img.width) // 2
                            offset_y = py + (ph - img.height) // 2
                        elif scale_mode == "crop":
                            src_ratio = img.width / max(1, img.height)
                            target_ratio = pw / max(1, ph)
                            if src_ratio > target_ratio:
                                new_w = int(img.height * target_ratio)
                                left = (img.width - new_w) // 2
                                img = img.crop((left, 0, left + new_w, img.height))
                            else:
                                new_h = int(img.width / target_ratio)
                                top = (img.height - new_h) // 2
                                img = img.crop((0, top, img.width, top + new_h))
                            img = img.resize((pw, ph), Image.Resampling.LANCZOS)
                            offset_x = px
                            offset_y = py
                        else:
                            img = img.resize((pw, ph), Image.Resampling.LANCZOS)
                            offset_x = px
                            offset_y = py

                        if opacity < 0.999:
                            r, g, b, a = img.split()
                            a = a.point(lambda p: int(p * opacity))
                            img = Image.merge("RGBA", (r, g, b, a))

                        canvas.paste(img, (offset_x, offset_y), img)
                except Exception as ex:
                    _log(f"⚠️ Lỗi vẽ layer ảnh '{layer.get('name')}': {ex}")

            # -------------------------------------------------------------
            # 2. LAYER CHỮ / TIÊU ĐỀ & PHỤ ĐỀ XEM TRƯỚC (Text / Subtitle Live Preview)
            # -------------------------------------------------------------
            elif l_type in {"text", "subtitle"}:
                if l_type == "subtitle" and not preview_mode:
                    # Khi render video thật, subtitle được vẽ động bằng FFmpeg filter ASS/SRT theo từng mili-giây
                    continue

                raw_content = str(layer.get("text_content", "") or layer.get("content", "")).strip()
                l_name_lower = str(layer.get("name", "")).lower()

                if l_type == "subtitle":
                    content = raw_content
                    if not content:
                        sub_mode = str(layer.get("sub_mode", "rolling_2line")).lower()
                        if sub_mode == "rolling_2line":
                            content = "Dòng 1: Câu vừa đọc xong (giữ để đọc kịp)...\nDòng 2: Câu đang đọc (Mới nhất theo audio)"
                        elif sub_mode == "cinema_hold":
                            content = "Cụm câu hoàn chỉnh chuẩn điện ảnh\n(Giữ đệm tối thiểu 2.5s không bị mất vội)"
                        elif sub_mode == "karaoke_highlight":
                            content = "Phụ đề Karaoke Highlight:\nSáng từng từ theo nhịp giọng đọc AI"
                        else:
                            content = "Đây là phụ đề mẫu xem trước (Subtitle Live Preview)"
                else:
                    # Thay thế biến động {title}, {filename}
                    content = raw_content
                    if not content and (l_name_lower in ["tiêu-đề", "tieu de", "title", "tiêu đề", "tieude"]):
                        content = audio_title if audio_title else ("[Tên Video]" if preview_mode else "[Tiêu Đề]")
                    elif audio_title:
                        for tag in ["{title}", "{filename}", "{name}", "{audio_name}", "{ten_audio}", "{ten_video}", "{tieu_de}"]:
                            content = content.replace(tag, audio_title).replace(tag.upper(), audio_title)
                    elif preview_mode:
                        for tag in ["{title}", "{filename}", "{name}", "{audio_name}", "{ten_audio}", "{ten_video}", "{tieu_de}"]:
                            content = content.replace(tag, "[Tên Video]").replace(tag.upper(), "[Tên Video]")

                # Loại bỏ emoji Unicode ngoài BMP tránh vẽ ô vuông đứt nét
                content = re.sub(r"[\U00010000-\U0010ffff]", "", content).strip()
                if not content:
                    continue

                font_name = str(layer.get("font_name", "Arial") or "Arial")
                font_size = int(layer.get("font_size", 36) or 36)
                font_bold = bool(layer.get("bold", True))
                font_italic = bool(layer.get("italic", False))

                # Scale font size theo độ phân giải canvas (chuẩn 1080p)
                scaled_font_size = max(10, int(round(font_size * (height / 1080.0))))
                font_file = find_font_file(font_name, font_bold, font_italic)

                font: Optional[ImageFont.FreeTypeFont] = None
                if font_file and font_file.exists():
                    try:
                        font = ImageFont.truetype(str(font_file), scaled_font_size)
                    except Exception:
                        pass
                if font is None:
                    try:
                        font = ImageFont.truetype("arial.ttf", scaled_font_size)
                    except Exception:
                        font = ImageFont.load_default()

                bx = float(layer.get("box_x", 0.1))
                by = float(layer.get("box_y", 0.1 if l_type != "subtitle" else 0.7))
                bw = float(layer.get("box_w", 0.8))
                bh = float(layer.get("box_h", 0.2))

                px = int(round(width * bx))
                py = int(round(height * by))
                pw = max(16, int(round(width * bw)))
                ph = max(16, int(round(height * bh)))

                # 2.1 Vẽ Background Box nếu bật
                bg_box_enabled = bool(layer.get("bg_box_enabled", False))
                bg_color_raw = str(layer.get("bg_box_color", "#000000")).strip()
                if bg_box_enabled and bg_color_raw.lower() not in {"none", "transparent", ""}:
                    bg_opacity = float(layer.get("bg_box_opacity", 0.5) if layer.get("bg_box_opacity") is not None else 0.5)
                    bg_rgba = hex_to_rgba(bg_color_raw, bg_opacity)
                    box_radius = int(round(int(layer.get("box_radius", 8) or 8) * (height / 1080.0)))
                    draw.rounded_rectangle([px, py, px + pw, py + ph], radius=box_radius, fill=bg_rgba)

                # 2.2 Thuật toán Word Wrapping chuẩn xác từng pixel hỗ trợ cả \n và tự động bẻ dòng
                def get_text_w(s: str) -> int:
                    if hasattr(font, "getlength"):
                        return int(round(font.getlength(s)))
                    bbox = draw.textbbox((0, 0), s, font=font)
                    return bbox[2] - bbox[0]

                raw_lines: List[str] = []
                paragraphs = content.splitlines() if ("\n" in content or "\r" in content) else [content]
                for paragraph in paragraphs:
                    clean_words = paragraph.strip().split()
                    if not clean_words:
                        continue
                    cur_line = ""
                    for w in clean_words:
                        test_l = f"{cur_line} {w}".strip() if cur_line else w
                        if get_text_w(test_l) <= pw:
                            cur_line = test_l
                        else:
                            if cur_line:
                                raw_lines.append(cur_line)
                            cur_line = w
                    if cur_line:
                        raw_lines.append(cur_line)

                # Làm sạch dấu phân cách | - : ; / \ ở đầu và cuối dòng
                lines: List[str] = []
                for idx, l in enumerate(raw_lines):
                    l_clean = l.strip()
                    if idx > 0:
                        l_clean = re.sub(r"^[\|\-:\;/\\]+\s*", "", l_clean).strip()
                    l_clean = re.sub(r"\s*[\|\-:\;/\\]+$", "", l_clean).strip()
                    if l_clean:
                        lines.append(l_clean)

                if not lines:
                    continue

                # 2.3 Tính toán chiều cao dòng (Line Height) & Khoảng cách dòng (Line Spacing) khít chuẩn poster
                cap_bbox = draw.textbbox((0, 0), "ÁyTgjpqQ|", font=font)
                actual_glyph_h = cap_bbox[3] - cap_bbox[1]

                user_spacing = int(layer.get("line_spacing", 4) or 4)
                line_spacing_px = user_spacing
                if scaled_font_size >= 80:
                    line_spacing_px = max(2, int(scaled_font_size * 0.08) + user_spacing)
                elif scaled_font_size >= 40:
                    line_spacing_px = max(2, int(scaled_font_size * 0.12) + user_spacing)

                line_step_h = actual_glyph_h + line_spacing_px
                total_text_h = len(lines) * actual_glyph_h + (len(lines) - 1) * line_spacing_px

                start_y = py + max(0, (ph - total_text_h) // 2)

                font_color_raw = str(layer.get("font_color", "#FFFFFF")).strip()
                font_rgba = hex_to_rgba(font_color_raw, 1.0)

                outline_color_raw = str(layer.get("outline_color", "#000000")).strip()
                outline_width_raw = float(layer.get("outline_width", 2.0) or 2.0)
                has_outline = (outline_color_raw.lower() not in {"none", "transparent", ""}) and outline_width_raw > 0
                outline_rgba = hex_to_rgba(outline_color_raw, 1.0) if has_outline else None
                stroke_w = int(round(outline_width_raw * (height / 1080.0))) if has_outline else 0

                font_align = str(layer.get("align", "center")).lower()

                for i, line_str in enumerate(lines):
                    line_w = get_text_w(line_str)
                    if font_align == "left":
                        cur_x = px
                    elif font_align == "right":
                        cur_x = px + pw - line_w
                    else:  # center
                        cur_x = px + (pw - line_w) // 2

                    cur_y = start_y + i * line_step_h

                    draw.text(
                        (cur_x, cur_y),
                        line_str,
                        font=font,
                        fill=font_rgba,
                        stroke_width=stroke_w,
                        stroke_fill=outline_rgba,
                    )

            # -------------------------------------------------------------
            # 3. LAYER HUY HIỆU TRỰC TIẾP (Live Badge)
            # -------------------------------------------------------------
            elif l_type == "live_badge":
                bx = float(layer.get("box_x", 0.05))
                by = float(layer.get("box_y", 0.05))
                bw = float(layer.get("box_w", 0.12))
                bh = float(layer.get("box_h", 0.05))

                px = int(round(width * bx))
                py = int(round(height * by))
                pw = max(60, int(round(width * bw)))
                ph = max(24, int(round(height * bh)))

                draw.rounded_rectangle([px, py, px + pw, py + ph], radius=ph // 2, fill=(230, 30, 30, 240))
                dot_r = max(3, ph // 5)
                dot_cx = px + ph // 2
                dot_cy = py + ph // 2
                draw.ellipse([dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r], fill=(255, 255, 255, 255))
                badge_font_size = max(12, int(ph * 0.55))
                b_font = find_font_file("Arial", bold=True)
                badge_font = ImageFont.truetype(str(b_font), badge_font_size) if b_font else ImageFont.load_default()
                draw.text((dot_cx + dot_r + 6, py + (ph - badge_font_size) // 2 - 2), "LIVE", font=badge_font, fill=(255, 255, 255, 255))

        return canvas, dynamic_layers

    @staticmethod
    def get_or_render_cached_canvas(
        layers: List[Dict[str, Any]],
        width: int = 1920,
        height: int = 1080,
        audio_title: str = "",
        log_fn: Optional[Any] = None,
    ) -> Tuple[Path, List[Dict[str, Any]]]:
        """Lấy file ảnh Canvas PNG từ bộ nhớ Cache nếu đã có, hoặc dựng mới và lưu Cache."""
        cache_dir = CACHE_DIR / "layouts"
        cache_dir.mkdir(parents=True, exist_ok=True)

        layout_hash = get_layout_hash(layers, width, height, audio_title)
        cached_png = cache_dir / f"layout_{layout_hash}.png"

        if cached_png.exists() and cached_png.stat().st_size > 500:
            if log_fn:
                log_fn(f"⚡ Layout Cache Hit: Tái sử dụng Canvas PNG có sẵn [hash: {layout_hash[:8]}] (0ms).")
            dynamic_layers = [
                l for l in layers
                if isinstance(l, dict) and l.get("enabled", True)
                and (
                    str(l.get("in_effect", "none")).lower() != "none"
                    or str(l.get("out_effect", "none")).lower() != "none"
                    or str(l.get("motion_effect", "none")).lower() != "none"
                    or str(l.get("type", "")).lower() in {"video_mask", "gif", "reaction", "animated_image"}
                    or str(l.get("file_path", "")).lower().endswith(".gif")
                )
            ]
            return cached_png, dynamic_layers

        canvas, dynamic_layers = LayoutRenderer.render_canvas(
            layers=layers,
            width=width,
            height=height,
            audio_title=audio_title,
            preview_mode=False,
            log_fn=log_fn,
        )

        canvas.save(cached_png, "PNG", optimize=True)
        if log_fn:
            log_fn(f"⚡ Layout Cache Created: Đã lưu Canvas PNG mới [hash: {layout_hash[:8]}].")

        return cached_png, dynamic_layers
