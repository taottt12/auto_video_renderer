from __future__ import annotations

import os
import re
import math
import random
from pathlib import Path
from typing import Optional, Dict, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter


class ThumbnailBuilder:
    """Xưởng tạo ảnh thu nhỏ (Thumbnail) chuẩn YouTube 1280x720 mang phong cách Kiếm Hiệp / Tiên Hiệp / Huyền Huyễn đỉnh cao:
    - Chữ Cọ Xước Kiếm Hiệp (Martial Arts Brush Font)
    - Vệt Cọ Xước Rách Sơn Đỏ (Torn Grunge Crimson Brush Banner)
    - Chữ Huyết Thư Rùng Rợn (Dripping Blood Horror Font)
    - Góc nghiêng nghệ thuật (-6 độ) tạo sức hút click cực mạnh
    - Giữ trọn 100% màu sắc nguyên bản của hình ảnh gốc
    """

    WIDTH = 1280
    HEIGHT = 720
    FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

    @classmethod
    def _get_font(cls, font_filename: str, size: int) -> ImageFont.FreeTypeFont:
        font_path = cls.FONTS_DIR / font_filename
        if font_path.exists():
            try:
                return ImageFont.truetype(str(font_path), size)
            except Exception:
                pass

        # Fallback candidates từ hệ thống Windows
        system_candidates = [
            r"C:\Windows\Fonts\seguibl.ttf",
            r"C:\Windows\Fonts\ariblk.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
        ]
        for p in system_candidates:
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    @staticmethod
    def _make_grunge_banner(width: int, height: int, color: Tuple[int, int, int] = (205, 12, 18), seed: int = 777) -> Image.Image:
        """Tạo vệt sơn cọ xước rách màu đỏ crimson với hiệu ứng giọt sơn rơi đậm chất kiếm hiệp."""
        random.seed(seed)
        scale = 2
        sw, sh = width * scale, height * scale
        mask = Image.new("L", (sw, sh), 0)
        draw = ImageDraw.Draw(mask)
        cy = sh // 2
        h_core = int(sh * 0.38)
        pad = int(30 * scale)

        # 1. Lõi đặc ở trung tâm để đảm bảo chữ trên banner luôn sắc nét 100%
        draw.rectangle([pad + int(20 * scale), cy - h_core, sw - pad - int(20 * scale), cy + h_core], fill=255)

        # 2. Vệt cọ xước ngang mô phỏng nét chổi lông khô kéo trên giấy
        for _ in range(320):
            y_pos = cy + (random.random() - 0.5) * sh * 0.86
            x1 = random.randint(0, pad + int(15 * scale))
            x2 = sw - random.randint(0, pad + int(25 * scale))
            lw = random.randint(int(2 * scale), int(7 * scale))
            draw.line([(x1, y_pos), (x2, y_pos)], fill=random.randint(190, 255), width=lw)

        # 3. Giọt sơn nhỏ rơi xuống từ mép dưới
        for _ in range(45):
            dx = random.randint(pad + int(25 * scale), sw - pad - int(25 * scale))
            dy_start = cy + h_core - int(4 * scale)
            dy_len = random.randint(int(6 * scale), int(26 * scale))
            draw.line([(dx, dy_start), (dx, dy_start + dy_len)], fill=random.randint(180, 255), width=random.randint(int(2 * scale), int(4 * scale)))

        # 4. Đầu xước rách ở hai mép trái - phải
        for _ in range(70):
            ly = cy + (random.random() - 0.5) * sh * 0.75
            draw.line([(0, ly), (pad + random.randint(int(8 * scale), int(35 * scale)), ly)], fill=random.randint(180, 255), width=random.randint(2 * scale, 5 * scale))
            ry = cy + (random.random() - 0.5) * sh * 0.75
            draw.line([(sw - pad - random.randint(int(8 * scale), int(35 * scale)), ry), (sw, ry)], fill=random.randint(180, 255), width=random.randint(2 * scale, 5 * scale))

        mask = mask.resize((width, height), Image.Resampling.LANCZOS)

        # Gradient màu đỏ thẫm rực rỡ với bóng viền dưới sâu
        banner = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        b_draw = ImageDraw.Draw(banner)
        for y in range(height):
            ratio = y / float(height)
            r = int(color[0] * (1.18 - 0.28 * ratio))
            g = int(color[1] * (0.95 - 0.5 * ratio))
            b = int(color[2] * (0.95 - 0.5 * ratio))
            b_draw.line([(0, y), (width, y)], fill=(min(255, max(0, r)), min(255, max(0, g)), min(255, max(0, b)), 255))

        banner.putalpha(mask)
        return banner

    @classmethod
    def _parse_title_structure(cls, title: str) -> Dict[str, str]:
        """Tự động phân tích tiêu đề thành các tầng thị giác điện ảnh:
        - Lead: Tiền đề dẫn nhập (Ví dụ: 'TA LÀ', 'TRỌNG SINH THÀNH'...)
        - Hero: Chủ ngữ nhân vật chính (Ví dụ: 'TIÊU SƯ', 'MA ĐẾ'...)
        - Banner: Khẳng định 1 nằm trong dải sơn đỏ (Ví dụ: 'GIỮ QUY CỦ NHẤT THIÊN HẠ')
        - Pivot: Từ nối chuyển biến cảm xúc (Ví dụ: 'NHƯNG CŨNG LÀ', 'LẠI LÀ'...)
        - Climax: Điểm nhấn kịch tính bằng chữ Huyết Thư rùng rợn (Ví dụ: 'KẺ TÀN NHẪN NHẤT')
        """
        raw = re.sub(r"^(p\d+[a-zA-Z]?|tập\s*\d+|phần\s*\d+)[\s:\-_]+", "", (title or "").strip(), flags=re.IGNORECASE).strip()

        pivot_patterns = [
            r"(\bnhưng cũng là\b)",
            r"(\bnhưng lại là\b)",
            r"(\bnhưng là\b)",
            r"(\bnhưng\b)",
            r"(\bcũng là\b)",
            r"(\blại là\b)",
            r"(\bsong lại là\b)",
        ]

        pivot_match = None
        for pat in pivot_patterns:
            m = re.search(pat, raw, flags=re.IGNORECASE)
            if m:
                pivot_match = m
                break

        if pivot_match:
            part1 = raw[:pivot_match.start()].strip()
            pivot = pivot_match.group(1).strip()
            part2 = raw[pivot_match.end():].strip()
        else:
            part1 = raw
            pivot = ""
            part2 = ""

        lead_patterns = [
            r"^(ta là)",
            r"^(trọng sinh thành)",
            r"^(trọng sinh)",
            r"^(ta trở thành)",
            r"^(xuyên không thành)",
            r"^(xuyên không)",
            r"^(hóa ra)",
            r"^(đại ca)",
        ]
        matched_lead = None
        for lp in lead_patterns:
            lm = re.match(lp, part1, flags=re.IGNORECASE)
            if lm:
                matched_lead = lm.group(1)
                break

        words1 = [w for w in part1.split() if w]
        lead = ""
        hero = ""
        banner = ""

        if matched_lead:
            lead = matched_lead.upper()
            rem = part1[len(matched_lead):].strip()
            rem_words = [w for w in rem.split() if w]
            if len(rem_words) <= 2:
                hero = " ".join(rem_words).upper()
            else:
                hero = " ".join(rem_words[:2]).upper()
                banner = " ".join(rem_words[2:]).upper()
        else:
            if len(words1) <= 2:
                hero = " ".join(words1).upper()
            elif len(words1) <= 4:
                hero = " ".join(words1[:2]).upper()
                banner = " ".join(words1[2:]).upper()
            else:
                lead = " ".join(words1[:2]).upper()
                hero = " ".join(words1[2:4]).upper()
                banner = " ".join(words1[4:]).upper()

        return {
            "lead": lead,
            "hero": hero,
            "banner": banner,
            "pivot": pivot.upper(),
            "climax": part2.upper(),
        }

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
        """Tạo thumbnail chuẩn 16:9 1280x720: Giữ nguyên 100% màu gốc ảnh, chữ nghệ thuật cọ xước kiếm hiệp đỉnh cao."""
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

        # 1. Chuẩn bị ảnh nền - GIỮ NGUYÊN 100% MÀU GỐC
        bg_path = Path(bg_image)
        if bg_path.exists():
            try:
                base = Image.open(bg_path).convert("RGBA")
            except Exception:
                base = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), color=(15, 10, 25, 255))
        else:
            base = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), color=(15, 10, 25, 255))

        base_w, base_h = base.size
        scale = max(cls.WIDTH / base_w, cls.HEIGHT / base_h)
        new_w, new_h = int(base_w * scale), int(base_h * scale)
        base = base.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (new_w - cls.WIDTH) // 2
        top = (new_h - cls.HEIGHT) // 2
        base = base.crop((left, top, left + cls.WIDTH, top + cls.HEIGHT))

        # 2. Hiệu ứng đổ bóng mờ góc bên trái (0 -> 54% bề ngang) để chữ luôn cực kỳ rõ nét mà không làm tối nhân vật
        vignette = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), (0, 0, 0, 0))
        vd = ImageDraw.Draw(vignette)
        for x in range(int(cls.WIDTH * 0.54)):
            ratio = 1.0 - (x / (cls.WIDTH * 0.54))
            alpha = int(175 * (ratio ** 1.9))
            vd.line([(x, 0), (x, cls.HEIGHT)], fill=(0, 0, 0, alpha))
        base = Image.alpha_composite(base, vignette)

        overlay = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), (0, 0, 0, 0))

        # 3. Phân tích tiêu đề theo các tầng chữ
        p = cls._parse_title_structure(highlight_title)

        # Tải bộ phông chữ nghệ thuật chuyên biệt
        f_brush = cls._get_font("Protest_Revolution.ttf", 46)
        f_hero = cls._get_font("Protest_Revolution.ttf", 110)
        f_banner = cls._get_font("Dela_Gothic_One.ttf", 30)
        f_sub = cls._get_font("Protest_Revolution.ttf", 38)
        f_climax = cls._get_font("Road_Rage.ttf", 86)
        f_badge = cls._get_font("Dela_Gothic_One.ttf", 28)

        # Canvas vẽ chữ
        tc_w, tc_h = 660, 500
        tc = Image.new("RGBA", (tc_w, tc_h), (0, 0, 0, 0))
        td = ImageDraw.Draw(tc)

        cur_y = 15

        # Dòng 1: Tiền tố (Lead)
        if p["lead"]:
            td.text((84, cur_y + 4), p["lead"], font=f_brush, fill=(0, 0, 0, 240))
            td.text((80, cur_y), p["lead"], font=f_brush, fill=(245, 240, 235, 255))
            cur_y += 47
        else:
            cur_y += 15

        # Dòng 2: Tên nhân vật / Từ khóa chính (Hero) - Chữ Cọ Xước Kiếm Hiệp khổng lồ với bóng 3D
        if p["hero"]:
            for off in range(7, 0, -1):
                td.text((35 + off, cur_y + off), p["hero"], font=f_hero, fill=(20, 0, 0, 240))
            td.text((35, cur_y), p["hero"], font=f_hero, fill=(255, 248, 238, 255), stroke_width=3, stroke_fill=(35, 5, 5, 255))
            cur_y += 136

        # Dòng 3: Dải vệt cọ xước rách sơn đỏ (Banner)
        if p["banner"]:
            bbox_b = td.textbbox((0, 0), p["banner"], font=f_banner)
            tw = bbox_b[2] - bbox_b[0]
            banner_w = min(tc_w - 20, max(440, tw + 90))
            banner_h = 62
            b_img = cls._make_grunge_banner(banner_w, banner_h, color=(205, 12, 18))

            # Bóng mờ dưới vệt sơn đỏ
            b_sh = Image.new("RGBA", (banner_w, banner_h), (0, 0, 0, 0))
            ImageDraw.Draw(b_sh).rectangle([12, 5, banner_w - 12, banner_h - 5], fill=(0, 0, 0, 180))
            b_sh = b_sh.filter(ImageFilter.GaussianBlur(5))
            tc.paste(b_sh, (12, cur_y + 5), b_sh)
            tc.paste(b_img, (10, cur_y), b_img)

            # Chữ trắng ngà sắc bén bên trong vệt sơn
            bx = 10 + (banner_w - tw) // 2
            by = cur_y + (banner_h - (bbox_b[3] - bbox_b[1])) // 2 - 2
            td.text((bx + 2, by + 2), p["banner"], font=f_banner, fill=(50, 0, 0, 240))
            td.text((bx, by), p["banner"], font=f_banner, fill=(255, 250, 235, 255))
            cur_y += 82

        # Dòng 4: Từ nối chuyển ý (Pivot)
        if p["pivot"]:
            td.text((102, cur_y + 3), p["pivot"], font=f_sub, fill=(0, 0, 0, 230))
            td.text((100, cur_y), p["pivot"], font=f_sub, fill=(250, 245, 240, 255))
            cur_y += 50

        # Dòng 5: Chữ Huyết Thư rùng rợn (Climax)
        if p["climax"]:
            td.text((33, cur_y + 4), p["climax"], font=f_climax, fill=(0, 0, 0, 240))
            td.text((30, cur_y), p["climax"], font=f_climax, fill=(230, 12, 18, 255), stroke_width=2, stroke_fill=(70, 0, 0, 255))

        # Nghiêng toàn bộ khối chữ -6 độ theo phong cách poster phim bom tấn
        rotated_tc = tc.rotate(-6, resample=Image.Resampling.BICUBIC, expand=True)
        overlay.paste(rotated_tc, (12, 85), rotated_tc)

        # 4. Huy hiệu số tập (Badge: P1, P2...) ở góc trên bên trái
        badge_clean = (badge_text or "").strip().upper()
        if badge_clean:
            bdg = Image.new("RGBA", (135, 54), (0, 0, 0, 0))
            bdg_d = ImageDraw.Draw(bdg)
            bdg_d.rounded_rectangle([2, 2, 131, 50], radius=10, fill=(185, 15, 20, 240), outline=(255, 215, 0, 255), width=2)
            bdg_d.text((38, 7), badge_clean, font=f_badge, fill=(255, 255, 255, 255))
            overlay.paste(bdg, (45, 30), bdg)

        # 5. Lưu kết quả JPEG chất lượng cao 95%
        final_img = Image.alpha_composite(base, overlay).convert("RGB")
        final_img.save(str(out_file), "JPEG", quality=95, optimize=True)
        return out_file
