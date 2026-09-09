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
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
            r"C:\Windows\Fonts\tahomabd.ttf",
            r"C:\Windows\Fonts\arial.ttf",
        ]
        for path in font_candidates:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, font_size)
                except Exception:
                    continue
        return ImageFont.load_default()

    @classmethod
    def create_thumbnail(
        cls,
        bg_image: str | Path,
        output_path: str | Path,
        badge_text: str = "TẬP 1",
        highlight_title: str = "",
        subtitle: str = "",
        channel_logo: Optional[str | Path] = None,
    ) -> Path:
        """Tạo thumbnail chuyên nghiệp chuẩn 16:9 1280x720."""
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

        # 1. Chuẩn bị ảnh nền
        bg_path = Path(bg_image)
        if bg_path.exists():
            try:
                base = Image.open(bg_path).convert("RGBA")
            except Exception:
                base = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), color=(20, 15, 35, 255))
        else:
            base = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), color=(20, 15, 35, 255))

        # Scale & Crop ảnh nền vừa đúng 1280x720 theo tỉ lệ
        base_w, base_h = base.size
        scale = max(cls.WIDTH / base_w, cls.HEIGHT / base_h)
        new_w, new_h = int(base_w * scale), int(base_h * scale)
        base = base.resize((new_w, new_h), Image.Resampling.LANCZOS)
        # Crop giữa
        left = (new_w - cls.WIDTH) // 2
        top = (new_h - cls.HEIGHT) // 2
        base = base.crop((left, top, left + cls.WIDTH, top + cls.HEIGHT))

        # Tăng nhẹ độ tương phản và bão hòa cho ảnh nền
        enhancer = ImageEnhance.Color(base)
        base = enhancer.enhance(1.15)
        enhancer_c = ImageEnhance.Contrast(base)
        base = enhancer_c.enhance(1.10)

        # 2. Tạo lớp phủ bóng đổ (Dark Gradient) để chữ luôn nổi bật
        gradient = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), color=(0, 0, 0, 0))
        draw_g = ImageDraw.Draw(gradient)

        # Gradient bóng đen từ dưới lên và góc trái
        for y in range(cls.HEIGHT // 2, cls.HEIGHT):
            alpha = int(190 * ((y - cls.HEIGHT // 2) / (cls.HEIGHT // 2)))
            draw_g.line([(0, y), (cls.WIDTH, y)], fill=(0, 0, 0, alpha))

        # Gradient bóng đen góc trên bên trái cho badge
        for y in range(0, int(cls.HEIGHT * 0.35)):
            alpha = int(140 * (1.0 - (y / (cls.HEIGHT * 0.35))))
            draw_g.line([(0, y), (int(cls.WIDTH * 0.5), y)], fill=(0, 0, 0, alpha))

        base = Image.alpha_composite(base, gradient)
        draw = ImageDraw.Draw(base)

        # 3. Vẽ Huy hiệu Số Tập (Episode Badge) ở góc trên bên trái
        badge_clean = (badge_text or "").strip()
        if badge_clean:
            font_badge = cls._get_font(42, bold=True)
            bbox = draw.textbbox((0, 0), badge_clean, font=font_badge)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]

            pad_x = 24
            pad_y = 12
            bx0 = 50
            by0 = 45
            bx1 = bx0 + tw + pad_x * 2
            by1 = by0 + th + pad_y * 2

            # Khung đỏ/cam nổi bật với viền vàng kim
            draw.rounded_rectangle([bx0, by0, bx1, by1], radius=12, fill=(225, 20, 45, 240), outline=(255, 215, 0, 255), width=3)
            draw.text((bx0 + pad_x, by0 + pad_y - 4), badge_clean, fill=(255, 255, 255, 255), font=font_badge)

        # 4. Vẽ Chữ Tiêu Đề Nổi Bật (Highlight Title) ở nửa dưới
        title_clean = (highlight_title or "").strip()
        if title_clean:
            # Chia dòng nếu quá dài
            words = title_clean.split()
            lines = []
            cur = ""
            for w in words:
                if len(cur) + len(w) + 1 <= 24:
                    cur = f"{cur} {w}".strip()
                else:
                    if cur:
                        lines.append(cur)
                    cur = w
            if cur:
                lines.append(cur)
            if len(lines) > 2:
                lines = lines[:2]
                lines[1] += "..."

            font_size = 64 if len(lines) == 1 else 54
            font_title = cls._get_font(font_size, bold=True)

            total_h = len(lines) * (font_size + 14)
            start_y = cls.HEIGHT - total_h - 70

            for idx, line in enumerate(lines):
                line_y = start_y + idx * (font_size + 14)
                line_x = 55

                # Màu sắc: dòng 1 màu vàng chanh rực rỡ, dòng 2 màu trắng
                color = (255, 235, 59, 255) if idx == 0 else (255, 255, 255, 255)

                # Vẽ bóng đổ sâu
                draw.text((line_x + 5, line_y + 5), line, fill=(0, 0, 0, 220), font=font_title)
                # Vẽ viền đen dày (Thick Stroke)
                draw.text((line_x, line_y), line, fill=color, font=font_title, stroke_width=6, stroke_fill=(0, 0, 0, 255))

        # 5. Lưu kết quả JPEG chất lượng cao
        final_img = base.convert("RGB")
        final_img.save(str(out_file), "JPEG", quality=94, optimize=True)
        return out_file
