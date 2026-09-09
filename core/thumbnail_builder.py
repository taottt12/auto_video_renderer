from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance


class ThumbnailBuilder:
    """Xưởng tạo ảnh thu nhỏ (Thumbnail) chuẩn YouTube 1280x720 với chữ nghệ thuật tiếng Việt."""

    WIDTH = 1280
    HEIGHT = 720

    @staticmethod
    def _get_font(font_size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
        font_candidates = [
            r"C:\Windows\Fonts\seguibl.ttf",  # Segoe UI Black (heavy bold, perfect VN Unicode)
            r"C:\Windows\Fonts\ariblk.ttf",   # Arial Black
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
            r"C:\Windows\Fonts\tahomabd.ttf",
        ]
        for path in font_candidates:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, font_size)
                except Exception:
                    continue
        return ImageFont.load_default()

    @classmethod
    def _fit_font(
        cls,
        draw: ImageDraw.ImageDraw,
        text: str,
        initial_size: int,
        max_width: int = 680,
        min_size: int = 24,
    ) -> ImageFont.FreeTypeFont:
        sz = initial_size
        f = cls._get_font(sz, bold=True)
        while sz > min_size:
            bbox = draw.textbbox((0, 0), text, font=f)
            if (bbox[2] - bbox[0]) <= max_width:
                break
            sz -= 2
            f = cls._get_font(sz, bold=True)
        return f

    @classmethod
    def create_thumbnail(
        cls,
        bg_image: str | Path,
        output_path: str | Path,
        badge_text: str = "P1",
        highlight_title: str = "",
        subtitle: str = "",
        channel_logo: Optional[str | Path] = None,
    ) -> Path:
        """Tạo thumbnail phong cách Kiếm Hiệp / Tiên Hiệp tương phản cao (High-CTR) chuẩn 16:9 1280x720."""
        import re
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

        # 1. Chuẩn bị ảnh nền
        bg_path = Path(bg_image)
        if bg_path.exists():
            try:
                base = Image.open(bg_path).convert("RGBA")
            except Exception:
                base = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), color=(15, 10, 25, 255))
        else:
            base = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), color=(15, 10, 25, 255))

        # Scale & Crop ảnh nền vừa đúng 1280x720 theo tỉ lệ
        base_w, base_h = base.size
        scale = max(cls.WIDTH / base_w, cls.HEIGHT / base_h)
        new_w, new_h = int(base_w * scale), int(base_h * scale)
        base = base.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (new_w - cls.WIDTH) // 2
        top = (new_h - cls.HEIGHT) // 2
        base = base.crop((left, top, left + cls.WIDTH, top + cls.HEIGHT))

        # Tăng nhẹ độ bão hòa màu và tương phản
        enhancer = ImageEnhance.Color(base)
        base = enhancer.enhance(1.15)
        enhancer_c = ImageEnhance.Contrast(base)
        base = enhancer_c.enhance(1.10)

        # 2. Lớp phủ bóng đổ (Dark Vignette) nửa bên trái: giữ nhân vật bên phải luôn sáng rõ
        gradient = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), color=(0, 0, 0, 0))
        draw_g = ImageDraw.Draw(gradient)

        # Gradient ngang từ x=0 sang x=780
        for x in range(0, 780):
            ratio = 1.0 - (x / 780)
            alpha = int(220 * (ratio ** 1.3))
            draw_g.line([(x, 0), (x, cls.HEIGHT)], fill=(0, 0, 0, alpha))

        # Gradient dọc góc dưới
        for y in range(cls.HEIGHT - 160, cls.HEIGHT):
            alpha = int(120 * ((y - (cls.HEIGHT - 160)) / 160))
            draw_g.line([(0, y), (cls.WIDTH, y)], fill=(0, 0, 0, alpha))

        base = Image.alpha_composite(base, gradient)
        draw = ImageDraw.Draw(base)

        # 3. Vẽ Huy hiệu Số Tập (Badge: P1, P2...) ở góc trên bên trái
        badge_clean = (badge_text or "").strip().upper()
        if badge_clean:
            font_badge = cls._get_font(38, bold=True)
            bbox = draw.textbbox((0, 0), badge_clean, font=font_badge)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]

            px, py = 20, 8
            bx0, by0 = 55, 45
            bx1, by1 = bx0 + tw + px * 2, by0 + th + py * 2

            # Khung đỏ đậm với viền vàng kim
            draw.rounded_rectangle([bx0, by0, bx1, by1], radius=8, fill=(185, 15, 25, 240), outline=(255, 215, 0, 255), width=2)
            draw.text((bx0 + px + 1, by0 + py), badge_clean, fill=(0, 0, 0, 220), font=font_badge)
            draw.text((bx0 + px, by0 + py - 2), badge_clean, fill=(255, 255, 255, 255), font=font_badge)

        # 4. Typography Kiếm Hiệp Đỉnh Cao (Phân tầng màu sắc Trắng - Đỏ - Đen)
        raw_title = highlight_title.replace("_", " - ").replace(":", " - ").strip()
        cleaned_title = re.sub(r"^(p\d+[a-zA-Z]?|tập\s*\d+|phần\s*\d+)[\s:\-_]+", "", raw_title, flags=re.IGNORECASE).strip()
        words = [w.strip("-,_ ") for w in cleaned_title.split() if w.strip("-,_ ")]

        cur_x = 55
        cur_y = 118

        if len(words) >= 5:
            # Tiêu đề dài đầy đủ: Mở đầu -> Từ khóa chính Cực Đại -> Ruy băng đỏ -> Câu kết kịch tính Đỏ máu
            line1 = " ".join(words[:2]).upper()
            line2 = " ".join(words[2:4]).upper()
            
            remaining = words[4:]
            split_idx = -1
            for i, w in enumerate(remaining):
                if w.lower() in ["nhưng", "cũng", "kẻ", "tàn", "một", "vô", "và"]:
                    split_idx = i
                    break

            if split_idx != -1 and split_idx > 0:
                mid_line = " ".join(remaining[:split_idx]).upper()
                tail_line = " ".join(remaining[split_idx:]).upper()
            else:
                mid_len = max(1, len(remaining) // 2)
                mid_line = " ".join(remaining[:mid_len]).upper()
                tail_line = " ".join(remaining[mid_len:]).upper()

            # Dòng 1: Mở đầu trắng vừa (34px)
            if line1:
                f1 = cls._fit_font(draw, line1, 34, max_width=680)
                draw.text((cur_x + 3, cur_y + 3), line1, fill=(0, 0, 0, 220), font=f1)
                draw.text((cur_x, cur_y), line1, fill=(255, 255, 255, 255), font=f1, stroke_width=4, stroke_fill=(0, 0, 0, 255))
                cur_y += 44

            # Dòng 2: TỪ KHÓA CHÍNH CỰC ĐẠI (78px, Trắng kem viền đen dày 8px)
            if line2:
                f2 = cls._fit_font(draw, line2, 78, max_width=680)
                draw.text((cur_x + 5, cur_y + 5), line2, fill=(0, 0, 0, 240), font=f2)
                draw.text((cur_x, cur_y), line2, fill=(255, 252, 235, 255), font=f2, stroke_width=8, stroke_fill=(0, 0, 0, 255))
                cur_y += 92

            # Dòng 3: Dải ruy băng đỏ thẫm (Red Ribbon Banner)
            if mid_line:
                f3 = cls._fit_font(draw, mid_line, 36, max_width=650)
                bbox = draw.textbbox((0, 0), mid_line, font=f3)
                rw = min(bbox[2] - bbox[0] + 36, 680)
                rh = bbox[3] - bbox[1] + 18
                draw.rounded_rectangle([cur_x, cur_y, cur_x + rw, cur_y + rh], radius=6, fill=(175, 15, 25, 240), outline=(230, 40, 40, 255), width=2)
                draw.text((cur_x + 18, cur_y + 7), mid_line, fill=(255, 255, 255, 255), font=f3, stroke_width=2, stroke_fill=(0, 0, 0, 200))
                cur_y += rh + 16

            # Dòng 4: ĐỎ MÁU RỰC RỠ (Kịch tính, sát phạt)
            if tail_line:
                tail_parts = tail_line.split()
                if len(tail_parts) > 3:
                    sub1 = " ".join(tail_parts[:3])
                    sub2 = " ".join(tail_parts[3:])
                    f_sub = cls._fit_font(draw, sub1, 32, max_width=680)
                    draw.text((cur_x + 3, cur_y + 3), sub1, fill=(0, 0, 0, 220), font=f_sub)
                    draw.text((cur_x, cur_y), sub1, fill=(255, 255, 255, 255), font=f_sub, stroke_width=3, stroke_fill=(0, 0, 0, 255))
                    cur_y += 40
                    f4 = cls._fit_font(draw, sub2, 66, max_width=680)
                    draw.text((cur_x + 6, cur_y + 6), sub2, fill=(0, 0, 0, 240), font=f4)
                    draw.text((cur_x, cur_y), sub2, fill=(255, 25, 45, 255), font=f4, stroke_width=7, stroke_fill=(0, 0, 0, 255))
                else:
                    f4 = cls._fit_font(draw, tail_line, 66, max_width=680)
                    draw.text((cur_x + 6, cur_y + 6), tail_line, fill=(0, 0, 0, 240), font=f4)
                    draw.text((cur_x, cur_y), tail_line, fill=(255, 25, 45, 255), font=f4, stroke_width=7, stroke_fill=(0, 0, 0, 255))

        elif len(words) >= 3:
            # Tiêu đề vừa (3 - 4 từ)
            w1 = " ".join(words[:2]).upper()
            w2 = " ".join(words[2:]).upper()
            f_top = cls._fit_font(draw, w1, 74, max_width=680)
            draw.text((cur_x + 5, cur_y + 5), w1, fill=(0, 0, 0, 240), font=f_top)
            draw.text((cur_x, cur_y), w1, fill=(255, 252, 235, 255), font=f_top, stroke_width=8, stroke_fill=(0, 0, 0, 255))
            cur_y += 88
            f_bot = cls._fit_font(draw, w2, 70, max_width=680)
            draw.text((cur_x + 5, cur_y + 5), w2, fill=(0, 0, 0, 240), font=f_bot)
            draw.text((cur_x, cur_y), w2, fill=(255, 25, 45, 255), font=f_bot, stroke_width=7, stroke_fill=(0, 0, 0, 255))
        else:
            # Tiêu đề ngắn (1 - 2 từ)
            full_w = " ".join(words).upper()
            f_big = cls._fit_font(draw, full_w, 84, max_width=680)
            draw.text((cur_x + 6, cur_y + 6), full_w, fill=(0, 0, 0, 240), font=f_big)
            draw.text((cur_x, cur_y), full_w, fill=(255, 252, 235, 255), font=f_big, stroke_width=9, stroke_fill=(0, 0, 0, 255))

        # 5. Lưu kết quả JPEG chất lượng cao 95%
        final_img = base.convert("RGB")
        final_img.save(str(out_file), "JPEG", quality=95, optimize=True)
        return out_file
