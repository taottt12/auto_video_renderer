import os
import re
import sys
import json
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont

from src_app.core.paths import CACHE_DIR, ASSETS_DIR


# -------------------------------------------------------------
# MULTI-TIER PERFORMANCE CACHES (PREVIEW & RENDER ACCELERATION)
# -------------------------------------------------------------
_FONT_PATH_CACHE: Dict[Tuple[str, bool, bool], Optional[Path]] = {}
_FONT_OBJ_CACHE: Dict[Tuple[str, int], Any] = {}
_LAYER_IMG_CACHE: Dict[Tuple[str, int, int, str, float, bool, bool, float, float], Image.Image] = {}
_REGISTRY_FONTS_CACHE: Optional[List[Tuple[str, Path]]] = None


def clear_layout_caches():
    """Xóa sạch các tầng cache trong bộ nhớ khi cần thiết."""
    global _FONT_PATH_CACHE, _FONT_OBJ_CACHE, _LAYER_IMG_CACHE, _REGISTRY_FONTS_CACHE
    _FONT_PATH_CACHE.clear()
    _FONT_OBJ_CACHE.clear()
    _LAYER_IMG_CACHE.clear()
    _REGISTRY_FONTS_CACHE = None


def _default_font_file() -> Optional[Path]:
    """Font mặc định fallback an toàn."""
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _get_registry_fonts() -> List[Tuple[str, Path]]:
    """Tra cứu và lưu cache danh sách font từ Windows Registry (quét 1 lần duy nhất)."""
    global _REGISTRY_FONTS_CACHE
    if _REGISTRY_FONTS_CACHE is not None:
        return _REGISTRY_FONTS_CACHE

    font_candidates: List[Tuple[str, Path]] = []
    win_fonts = Path("C:/Windows/Fonts")
    try:
        import winreg

        reg_roots = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        ]
        for hkey, subkey in reg_roots:
            try:
                with winreg.OpenKey(hkey, subkey) as key:
                    num_values = winreg.QueryInfoKey(key)[1]
                    for i in range(num_values):
                        val_name, val_data, _ = winreg.EnumValue(key, i)
                        clean_val = re.sub(
                            r"\s*\((TrueType|OpenType|All type)\)", "", str(val_name), flags=re.IGNORECASE
                        ).strip().lower()
                        file_p = Path(str(val_data))
                        if not file_p.is_absolute():
                            file_p = win_fonts / val_data
                        if file_p.exists():
                            font_candidates.append((clean_val, file_p))
            except Exception:
                pass
    except Exception:
        pass

    _REGISTRY_FONTS_CACHE = font_candidates
    return _REGISTRY_FONTS_CACHE


def find_font_file(font_name: str, bold: bool = True, italic: bool = False) -> Optional[Path]:
    """
    Tìm đường dẫn file font (.ttf/.otf) chuẩn xác trên Windows Registry,
    thư mục Fonts hệ thống và thư mục assets của ứng dụng.
    Có Cache Tầng 1 tối ưu hiệu năng (0ms sau lần đầu).
    """
    if not font_name:
        return _default_font_file()

    font_clean = str(font_name).strip()
    font_clean_lower = font_clean.lower()
    cache_key = (font_clean_lower, bool(bold), bool(italic))
    if cache_key in _FONT_PATH_CACHE:
        return _FONT_PATH_CACHE[cache_key]

    win_fonts = Path("C:/Windows/Fonts")

    # 1. Tra cứu tự động từ Windows Font Registry (đã có Registry Cache)
    try:
        font_candidates = _get_registry_fonts()
        target_style = font_clean_lower
        if bold and italic:
            target_style += " bold italic"
        elif bold:
            target_style += " bold"
        elif italic:
            target_style += " italic"

        # Khớp chính xác tên + style
        for name, fpath in font_candidates:
            if name == target_style:
                _FONT_PATH_CACHE[cache_key] = fpath
                return fpath

        # Khớp chính xác tên font
        for name, fpath in font_candidates:
            if name == font_clean_lower:
                _FONT_PATH_CACHE[cache_key] = fpath
                return fpath

        # Khớp chứa chuỗi tên font + style
        for name, fpath in font_candidates:
            if font_clean_lower in name:
                if bold and italic and ("bold" in name and "italic" in name):
                    _FONT_PATH_CACHE[cache_key] = fpath
                    return fpath
                elif bold and not italic and ("bold" in name and "italic" not in name):
                    _FONT_PATH_CACHE[cache_key] = fpath
                    return fpath
                elif italic and not bold and ("italic" in name and "bold" not in name):
                    _FONT_PATH_CACHE[cache_key] = fpath
                    return fpath
                elif not bold and not italic and "bold" not in name and "italic" not in name:
                    _FONT_PATH_CACHE[cache_key] = fpath
                    return fpath

        # Khớp chứa chuỗi tên font chung
        for name, fpath in font_candidates:
            if font_clean_lower in name:
                _FONT_PATH_CACHE[cache_key] = fpath
                return fpath
    except Exception:
        pass

    # 2. Quét trong thư mục fonts của dự án nếu có
    local_fonts = ASSETS_DIR / "fonts"
    if local_fonts.exists():
        for f in local_fonts.glob("*.*"):
            if f.suffix.lower() in [".ttf", ".otf"] and font_clean_lower in f.stem.lower():
                _FONT_PATH_CACHE[cache_key] = f
                return f

    # 3. Bản đồ mapping mở rộng cho các font phổ biến (hỗ trợ đầy đủ Bold, Italic, Bold Italic)
    if win_fonts.exists():
        font_map = {
            "arial rounded mt bold": "ARLRDBD.TTF",
            "arial rounded mt": "ARLRDBD.TTF",
            "arial rounded": "ARLRDBD.TTF",
            "arial black": "ariblk.ttf",
            "arial": "arialbi.ttf" if (bold and italic) else ("arialbd.ttf" if bold else ("ariali.ttf" if italic else "arial.ttf")),
            "montserrat": "Montserrat-Bold.ttf" if bold else "Montserrat-Regular.ttf",
            "montserrat black": "Montserrat-Black.ttf",
            "impact": "impact.ttf",
            "tahoma": "tahomabd.ttf" if bold else "tahoma.ttf",
            "segoe ui": "segoeub.ttf" if (bold and italic) else ("segoeuib.ttf" if bold else ("segoeuii.ttf" if italic else "segoeui.ttf")),
            "segoe ui black": "seguibl.ttf",
            "segoe script": "segoescb.ttf" if bold else "segoesc.ttf",
            "times new roman": "timesbi.ttf" if (bold and italic) else ("timesbd.ttf" if bold else ("timesi.ttf" if italic else "times.ttf")),
            "roboto": "Roboto-Bold.ttf" if bold else "Roboto-Regular.ttf",
            "helvetica": "arialbd.ttf" if bold else "arial.ttf",
            "verdana": "verdanaz.ttf" if (bold and italic) else ("verdanab.ttf" if bold else ("verdanai.ttf" if italic else "verdana.ttf")),
            "comic sans ms": "comicz.ttf" if (bold and italic) else ("comicbd.ttf" if bold else ("comici.ttf" if italic else "comic.ttf")),
            "trebuchet ms": "trebucbi.ttf" if (bold and italic) else ("trebucbd.ttf" if bold else ("trebucit.ttf" if italic else "trebuc.ttf")),
            "georgia": "georgiaz.ttf" if (bold and italic) else ("georgiab.ttf" if bold else ("georgiai.ttf" if italic else "georgia.ttf")),
            "brush script mt": "BRUSHSCI.TTF",
            "brush script": "BRUSHSCI.TTF",
            "calibri": "calibriz.ttf" if (bold and italic) else ("calibrib.ttf" if bold else ("calibrii.ttf" if italic else "calibri.ttf")),
            "consolas": "consolaz.ttf" if (bold and italic) else ("consolab.ttf" if bold else ("consolai.ttf" if italic else "consola.ttf")),
            "monotype corsiva": "MTCORSVA.TTF",
            "lucida handwriting": "LHANDW.TTF",
            "chiller": "CHILLER.TTF",
            "freestyle script": "FREESCPT.TTF",
            "kristen itc": "ITCKRIST.TTF",
            "mistral": "MISTRAL.TTF",
            "papyrus": "PAPYRUS.TTF",
        }

        if font_clean_lower in font_map:
            target = win_fonts / font_map[font_clean_lower]
            if target.exists():
                _FONT_PATH_CACHE[cache_key] = target
                return target

        for k, v in font_map.items():
            if k in font_clean_lower or font_clean_lower in k:
                target = win_fonts / v
                if target.exists():
                    _FONT_PATH_CACHE[cache_key] = target
                    return target

        # 4. Quét trực tiếp file stem trong C:/Windows/Fonts
        for f in win_fonts.glob("*.ttf"):
            if font_clean_lower in f.stem.lower():
                _FONT_PATH_CACHE[cache_key] = f
                return f
        for f in win_fonts.glob("*.otf"):
            if font_clean_lower in f.stem.lower():
                _FONT_PATH_CACHE[cache_key] = f
                return f

    res = _default_font_file()
    _FONT_PATH_CACHE[cache_key] = res
    return res


def get_cached_font(font_file: Optional[Path], size: int) -> ImageFont.FreeTypeFont:
    """Cache Tầng 2: Tái sử dụng đối tượng Pillow FreeType Font trong bộ nhớ RAM."""
    f_key = (str(font_file) if font_file else "__default__", int(size))
    if f_key in _FONT_OBJ_CACHE:
        return _FONT_OBJ_CACHE[f_key]

    font = None
    try:
        if font_file and font_file.exists():
            font = ImageFont.truetype(str(font_file), size)
        else:
            font = ImageFont.truetype("arial.ttf", size)
    except Exception:
        try:
            font = ImageFont.load_default()
        except Exception:
            pass

    if font is not None:
        if len(_FONT_OBJ_CACHE) > 500:
            _FONT_OBJ_CACHE.clear()
        _FONT_OBJ_CACHE[f_key] = font
    return font


def clean_text_content(text: str) -> str:
    """Làm sạch các ký tự unicode đặc biệt, ô vuông lỗi, BOM, emoji ngoài BMP."""
    if not text:
        return ""
    s = (
        str(text)
        .replace("\uff5c", "|")  # ｜
        .replace("\uff1a", ":")  # ：
        .replace("\uff0f", "/")  # ／
        .replace("\u25a1", "")   # ▯
        .replace("\ufffd", "")   # replacement char
        .replace("\u200b", "")   # zero-width space
        .replace("\ufeff", "")   # BOM
    )
    # Loại bỏ emoji Unicode ngoài BMP tránh vẽ ô vuông đứt nét
    s = re.sub(r"[\U00010000-\U0010ffff]", "", s)
    return s.strip()


def measure_text_and_fit_box(
    text: str,
    font_file: Optional[Path],
    font_size: int,
    box_w: int,
    box_h: int,
    line_spacing: int = 4,
    min_font_size: int = 14,
    max_lines: int = 2,
    margin_w_ratio: float = 0.94,
    margin_h_ratio: float = 0.90,
    auto_fit: bool = True,
) -> Tuple[List[str], int, int, int, int]:
    """
    Thuật toán dùng chung duy nhất (Single Source of Truth) giữa Preview và Render:
    1. Tự động ngắt dòng theo ranh giới từ (không xé đôi từ, không ngắt ở dấu gạch nối)
    2. Nếu auto_fit=True: Tự động co nhỏ font_size sao cho tiêu đề nằm vừa vặn hoàn hảo trong tối đa max_lines
       Nếu auto_fit=False: Giữ nguyên font_size cấu hình và chỉ bẻ dòng
    3. Đồng bộ chuẩn xác margin và line spacing
    Trả về: (lines, fitted_font_size, total_text_h, line_h, eff_spacing)
    """
    clean_text = clean_text_content(text)
    if not clean_text:
        return ([], font_size, 0, 0, line_spacing)

    avail_w = max(40, int(box_w * margin_w_ratio))
    avail_h = max(24, int(box_h * margin_h_ratio))

    cur_font_size = int(font_size)
    dummy_img = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(dummy_img)

    def _measure_with_size(sz: int) -> Tuple[List[str], int, int, int]:
        font = get_cached_font(font_file, sz)

        def get_w(s: str) -> int:
            if not s:
                return 0
            if font and hasattr(draw, "textbbox"):
                bbox = draw.textbbox((0, 0), s, font=font)
                return bbox[2] - bbox[0]
            elif font and hasattr(font, "getlength"):
                return int(round(font.getlength(s)))
            return int(len(s) * sz * 0.55)

        def get_line_h() -> int:
            if font and hasattr(font, "getmetrics"):
                ascent, descent = font.getmetrics()
                return ascent + descent
            if font and hasattr(draw, "textbbox"):
                bbox = draw.textbbox((0, 0), "ÁyTgjpqQ|", font=font)
                return bbox[3] - bbox[1]
            return int(sz * 1.25)

        # Ngắt dòng theo từ ngữ nguyên vẹn
        paragraphs = clean_text.splitlines() if ("\n" in clean_text or "\r" in clean_text) else [clean_text]
        raw_lines: List[str] = []
        for paragraph in paragraphs:
            words = paragraph.strip().split()
            if not words:
                continue
            cur_line = ""
            for w in words:
                test_line = f"{cur_line} {w}".strip() if cur_line else w
                if get_w(test_line) <= avail_w:
                    cur_line = test_line
                else:
                    if cur_line:
                        raw_lines.append(cur_line)
                    cur_line = w
            if cur_line:
                raw_lines.append(cur_line)

        # Dọn dẹp ký tự ngăn cách ở đầu/cuối dòng
        lines: List[str] = []
        for idx, l in enumerate(raw_lines):
            l_clean = l.strip()
            if idx > 0:
                l_clean = re.sub(r"^[\|\-:\;/\\]+\s*", "", l_clean).strip()
            l_clean = re.sub(r"\s*[\|\-:\;/\\]+$", "", l_clean).strip()
            if l_clean:
                lines.append(l_clean)

        line_h = get_line_h()
        eff_spacing = line_spacing
        if sz >= 60:
            eff_spacing = line_spacing - int(sz * 0.20)
        elif sz >= 35:
            eff_spacing = line_spacing - int(sz * 0.10)

        total_h = len(lines) * line_h + (len(lines) - 1) * eff_spacing
        return (lines, total_h, line_h, eff_spacing)

    if not auto_fit:
        # Giữ nguyên font size, chỉ wrap text
        lines, total_h, line_h, eff_spacing = _measure_with_size(cur_font_size)
        return (lines, cur_font_size, total_h, line_h, eff_spacing)

    best_lines: List[str] = [clean_text]
    best_size = cur_font_size
    best_total_h = 0
    best_line_h = 0
    best_eff_spacing = line_spacing

    while cur_font_size >= min_font_size:
        lines, total_h, line_h, eff_spacing = _measure_with_size(cur_font_size)
        font = get_cached_font(font_file, cur_font_size)

        def get_w(s: str) -> int:
            if not s:
                return 0
            if font and hasattr(draw, "textbbox"):
                bbox = draw.textbbox((0, 0), s, font=font)
                return bbox[2] - bbox[0]
            elif font and hasattr(font, "getlength"):
                return int(round(font.getlength(s)))
            return int(len(s) * cur_font_size * 0.55)

        max_line_w = max((get_w(l) for l in lines), default=0)

        if len(lines) <= max_lines and max_line_w <= avail_w and total_h <= avail_h:
            return (lines, cur_font_size, total_h, line_h, eff_spacing)

        best_lines = lines if lines else [clean_text]
        best_size = cur_font_size
        best_total_h = total_h
        best_line_h = line_h
        best_eff_spacing = eff_spacing
        cur_font_size -= 2

    return (best_lines, best_size, best_total_h, best_line_h, best_eff_spacing)


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
                    rotation = float(layer.get("rotation", 0.0) or 0.0)
                    flip_h = bool(layer.get("flip_h", False))
                    flip_v = bool(layer.get("flip_v", False))

                    mtime = 0.0
                    try:
                        mtime = os.path.getmtime(res_path)
                    except Exception:
                        pass

                    cache_key = (
                        str(res_path.resolve()),
                        pw,
                        ph,
                        scale_mode,
                        round(rotation, 1),
                        flip_h,
                        flip_v,
                        round(opacity, 3),
                        mtime,
                        is_gif,
                    )

                    cached_img = _LAYER_IMG_CACHE.get(cache_key)
                    if cached_img is not None:
                        img = cached_img
                    else:
                        with Image.open(res_path) as src_img:
                            # Với GIF ở chế độ Preview, lấy khung hình đầu tiên
                            if is_gif:
                                src_img.seek(0)
                            img = src_img.convert("RGBA")

                        # 1. Flip
                        if flip_h:
                            img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                        if flip_v:
                            img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

                        # 2. Scale Mode
                        if scale_mode == "fit":
                            img.thumbnail((pw, ph), Image.Resampling.LANCZOS)
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
                        else:  # stretch / fill
                            img = img.resize((pw, ph), Image.Resampling.LANCZOS)

                        # 3. Rotate (nếu có góc xoay != 0)
                        if abs(rotation) > 0.01:
                            img = img.rotate(-rotation, expand=True, resample=Image.Resampling.BICUBIC)

                        # 4. Opacity
                        if opacity < 0.999:
                            r, g, b, a = img.split()
                            a = a.point(lambda p: int(p * opacity))
                            img = Image.merge("RGBA", (r, g, b, a))

                        if len(_LAYER_IMG_CACHE) > 120:
                            _LAYER_IMG_CACHE.clear()
                        _LAYER_IMG_CACHE[cache_key] = img

                    offset_x = px + (pw - img.width) // 2
                    offset_y = py + (ph - img.height) // 2
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

                content = clean_text_content(content)
                if not content:
                    continue

                font_name = str(layer.get("font_name", "Arial") or "Arial")
                font_size = int(layer.get("font_size", 36) or 36)
                font_bold = bool(layer.get("bold", True))
                font_italic = bool(layer.get("italic", False))

                # Scale font size theo độ phân giải canvas (chuẩn 1080p)
                scaled_font_size = max(10, int(round(font_size * (height / 1080.0))))
                font_file = find_font_file(font_name, font_bold, font_italic)

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

                # 2.2 Thuật toán đo và fit text dùng chung duy nhất với Render
                layer_spacing = int(layer.get("line_spacing", 4) or 4)
                scaled_line_spacing = max(0, int(round(layer_spacing * (height / 1080.0))))
                min_sz = max(10, int(round(14 * (height / 1080.0))))
                auto_fit = bool(layer.get("auto_fit", True))

                lines, fitted_font_size, total_text_h, line_h, eff_spacing = measure_text_and_fit_box(
                    text=content,
                    font_file=font_file,
                    font_size=scaled_font_size,
                    box_w=pw,
                    box_h=ph,
                    line_spacing=scaled_line_spacing,
                    min_font_size=min_sz,
                    max_lines=2,
                    margin_w_ratio=0.94,
                    margin_h_ratio=0.90,
                    auto_fit=auto_fit,
                )

                if not lines:
                    continue

                font = get_cached_font(font_file, fitted_font_size)

                def get_text_w(s: str) -> int:
                    if hasattr(font, "getlength"):
                        return int(round(font.getlength(s)))
                    bbox = draw.textbbox((0, 0), s, font=font)
                    return bbox[2] - bbox[0]

                line_step_h = line_h + eff_spacing
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
                badge_font = get_cached_font(b_font, badge_font_size)
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
