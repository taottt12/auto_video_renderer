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
        max_width: int = 1180,
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
        """Tạo thumbnail chuẩn 16:9 1280x720: Giữ nguyên 100% màu gốc ảnh, chữ rõ nét, tinh tế."""
        import re
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

        # 1. Chuẩn bị ảnh nền - GIỮ NGUYÊN 100% MÀU GỐC (Không contrast/color boost, không phủ màn đen)
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

        draw = ImageDraw.Draw(base)

        # 2. Vẽ Huy hiệu Số Tập (Badge: P1, P2...) ở góc trên bên trái
        badge_clean = (badge_text or "").strip().upper()
        if badge_clean:
            font_badge = cls._get_font(34, bold=True)
            bbox = draw.textbbox((0, 0), badge_clean, font=font_badge)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]

            px, py = 18, 6
            bx0, by0 = 45, 38
            bx1, by1 = bx0 + tw + px * 2, by0 + th + py * 2

            # Đổ bóng nhẹ phía sau khung huy hiệu
            draw.rounded_rectangle([bx0 + 3, by0 + 3, bx1 + 3, by1 + 3], radius=8, fill=(0, 0, 0, 140))
            # Khung đỏ đậm với viền vàng kim tinh tế
            draw.rounded_rectangle([bx0, by0, bx1, by1], radius=8, fill=(200, 20, 30, 240), outline=(255, 215, 0, 255), width=2)
            # Chữ trắng rõ nét
            draw.text((bx0 + px, by0 + py - 2), badge_clean, fill=(255, 255, 255, 255), font=font_badge)

        # 3. Vẽ Chữ to nổi bật (Lấy đúng nội dung người dùng muốn, đặt ở góc dưới)
        title_clean = (highlight_title or "").strip()
        # Loại bỏ tiền tố P1, Tập 1... nếu lỡ dính vào
        title_clean = re.sub(r"^(p\d+[a-zA-Z]?|tập\s*\d+|phần\s*\d+)[\s:\-_]+", "", title_clean, flags=re.IGNORECASE).strip()

        if title_clean:
            words = [w.strip("-,_ ") for w in title_clean.split() if w.strip("-,_ ")]
            if len(words) <= 4:
                lines = [" ".join(words)]
            elif len(words) <= 8:
                mid = len(words) // 2
                lines = [" ".join(words[:mid]), " ".join(words[mid:])]
            else:
                mid = len(words) // 2
                lines = [" ".join(words[:mid]), " ".join(words[mid:])]

            # Dải bóng mờ cực nhẹ chỉ ở sát mép dưới (bottom 180px) để chữ luôn đọc rõ mà không làm tối ảnh
            grad = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), (0, 0, 0, 0))
            draw_g = ImageDraw.Draw(grad)
            for y in range(cls.HEIGHT - 180, cls.HEIGHT):
                ratio = (y - (cls.HEIGHT - 180)) / 180.0
                alpha = int(125 * (ratio ** 1.5))
                draw_g.line([(0, y), (cls.WIDTH, y)], fill=(0, 0, 0, alpha))
            base = Image.alpha_composite(base, grad)
            draw = ImageDraw.Draw(base)

            # Tính vị trí chữ ở góc dưới bên trái
            start_x = 45
            base_y = cls.HEIGHT - 55 - (len(lines) * 78)

            for i, line in enumerate(lines):
                line_str = line.upper()
                init_sz = 72 if len(lines) == 1 else 62
                f = cls._fit_font(draw, line_str, init_sz, max_width=1180)

                # Dòng 1 trắng, dòng 2 vàng ánh kim nổi bật
                text_color = (255, 255, 255, 255) if i == 0 else (255, 225, 45, 255)
                line_y = base_y + i * 80

                # Bóng đổ chữ mềm mại
                draw.text((start_x + 4, line_y + 4), line_str, fill=(0, 0, 0, 220), font=f)
                # Viền đen sắc nét + chữ chính
                draw.text((start_x, line_y), line_str, fill=text_color, font=f, stroke_width=4, stroke_fill=(0, 0, 0, 255))

        # 4. Lưu kết quả JPEG chất lượng cao 95%
        final_img = base.convert("RGB")
        final_img.save(str(out_file), "JPEG", quality=95, optimize=True)
        return out_file
