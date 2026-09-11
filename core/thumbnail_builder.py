from __future__ import annotations

import os
import re
import math
import random
from pathlib import Path
from typing import Optional, Dict, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageStat


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
    def detect_text_in_image(cls, image_path: str | Path) -> Tuple[bool, str]:
        """Tự động quét phát hiện xem ảnh nền đã có sẵn chữ/tiêu đề hay chưa.
        Phân tích mật độ viền sắc nét cục bộ (High-contrast Edge Density) qua PIL:
        Chữ viết/Typography luôn có độ tương phản cao và mật độ đường viền dày đặc trong các vùng cục bộ.
        """
        try:
            p = Path(image_path)
            if not p.exists():
                return False, "File không tồn tại"

            img = Image.open(p).convert("L")
            target_w, target_h = 1280, 720
            img_resized = img.resize((target_w, target_h), Image.Resampling.BILINEAR)
            edges = img_resized.filter(ImageFilter.FIND_EDGES)

            grid_x, grid_y = 8, 8
            cell_w = target_w // grid_x
            cell_h = target_h // grid_y
            high_edge_cells = 0

            for r in range(grid_y):
                for c in range(grid_x):
                    box = (c * cell_w, r * cell_h, (c + 1) * cell_w, (r + 1) * cell_h)
                    cell = edges.crop(box)
                    stat = ImageStat.Stat(cell)
                    mean_edge = stat.mean[0]
                    std_edge = stat.stddev[0]
                    if mean_edge > 30 and std_edge > 32:
                        high_edge_cells += 1

            has_text = high_edge_cells >= 4
            info = f"Mật độ viền chữ: {high_edge_cells} vùng (ngưỡng phát hiện >= 4)"
            return has_text, info
        except Exception as e:
            return False, f"Lỗi quét: {e}"

    @classmethod
    def create_thumbnail(
        cls,
        bg_image: str | Path,
        output_path: str | Path,
        badge_text: str = "P1",
        highlight_title: str = "",
        subtitle: str = "",
        channel_logo: Optional[str | Path] = None,
        font_style: str = "but_phap",
        position: str = "split_lr",
        pos_x: Optional[int] = None,
        pos_y: Optional[int] = None,
        font_scale: float = 0.68,
        badge_only: bool = False,
        badge_position: str = "top_left",
    ) -> Path:
        """Tạo thumbnail chuẩn 16:9 1280x720: Giữ nguyên 100% màu gốc ảnh, nét chữ bút pháp kiếm hiệp, né mặt nhân vật và hỗ trợ bố cục phân tách đa điểm (Split Layout)."""
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

        # =========================================================================
        # CHẾ ĐỘ CHỈ ĐÓNG HUY HIỆU TẬP (Khi ảnh gốc ĐÃ CÓ CHỮ SẴN)
        # 100% giữ nguyên ảnh gốc, không phủ vignette làm mờ, không vẽ lại tiêu đề
        # =========================================================================
        if badge_only:
            overlay = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), (0, 0, 0, 0))
            badge_clean = (badge_text or "").strip().upper()
            if badge_clean:
                f_badge = cls._get_font("Protest_Revolution.ttf", 24)
                d_test = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
                bbox = d_test.textbbox((0, 0), badge_clean, font=f_badge)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                bw = max(110, int(tw + 36))
                bh = 46
                bdg = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
                bd = ImageDraw.Draw(bdg)
                # Bóng đổ
                bd.rounded_rectangle([4, 4, bw, bh], radius=8, fill=(0, 0, 0, 180))
                # Nền đỏ viền vàng hoàng kim
                bd.rounded_rectangle([0, 0, bw - 4, bh - 4], radius=8, fill=(185, 15, 20, 245), outline=(255, 215, 0, 255), width=2)
                tx = (bw - 4 - tw) // 2 - bbox[0]
                ty = (bh - 4 - th) // 2 - bbox[1]
                bd.text((tx, ty), badge_clean, font=f_badge, fill=(255, 255, 255, 255))

                pos = (28, 22)
                bpos_clean = (badge_position or "top_left").lower().strip()
                if bpos_clean in ("top_right", "tr"):
                    pos = (cls.WIDTH - bw - 28, 22)
                elif bpos_clean in ("bottom_left", "bl"):
                    pos = (28, cls.HEIGHT - bh - 22)
                elif bpos_clean in ("bottom_right", "br"):
                    pos = (cls.WIDTH - bw - 28, cls.HEIGHT - bh - 22)
                overlay.paste(bdg, pos, bdg)

            final_img = Image.alpha_composite(base, overlay).convert("RGB")
            final_img.save(str(out_file), "JPEG", quality=95, optimize=True)
            return out_file

        # 2. Phân tích tiêu đề theo các tầng chữ
        p = cls._parse_title_structure(highlight_title)

        # 3. Chọn bộ font theo phong cách phối nghệ thuật (font_style)
        st = (font_style or "but_phap").lower().strip()
        if st == "dong_bo":
            fh_name, fb_name, fc_name = "Protest_Revolution.ttf", "Protest_Revolution.ttf", "Protest_Revolution.ttf"
        elif st == "thu_phap":
            fh_name, fb_name, fc_name = "ThuphapCongthuy.ttf", "Sedgwick_Ave.ttf", "ThuphapCongthuy.ttf"
        elif st == "huyet_thu":
            fh_name, fb_name, fc_name = "Protest_Revolution.ttf", "Sedgwick_Ave.ttf", "Protest_Revolution.ttf"
        else:
            # but_phap (Mặc định): Hero cọ xước + Banner Sedgwick Ave mềm mại + Climax cọ xước huyết dụ
            fh_name, fb_name, fc_name = "Protest_Revolution.ttf", "Sedgwick_Ave.ttf", "Protest_Revolution.ttf"

        pos_clean = (position or "split_lr").lower().strip()
        can_split = bool(p["banner"] or p["climax"])
        is_split = pos_clean in ("split_lr", "split_lb") and can_split

        overlay = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), (0, 0, 0, 0))

        if is_split:
            # =========================================================================
            # BỐ CỤC PHÂN TÁCH ĐA ĐIỂM (SPLIT LAYOUT): Chữ to rõ, cân đối, 100% né mặt
            # =========================================================================
            badge_pos = (28, 18)
            px1 = pos_x if pos_x is not None else 18
            py1 = pos_y if pos_y is not None else 68

            if pos_clean == "split_lb":
                # Phân tách chéo: Trái Trên + Phải Dưới
                px2 = 690
                py2 = 465
                rot_angle2 = -3
                # Vignette góc trái trên & phải dưới
                vignette = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), (0, 0, 0, 0))
                vd = ImageDraw.Draw(vignette)
                for x in range(int(cls.WIDTH * 0.32)):
                    ratio = 1.0 - (x / (cls.WIDTH * 0.32))
                    vd.line([(x, 0), (x, 320)], fill=(0, 0, 0, int(140 * (ratio ** 1.8))))
                for y in range(440, cls.HEIGHT):
                    ratio = (y - 440) / (cls.HEIGHT - 440)
                    vd.line([(600, y), (cls.WIDTH, y)], fill=(0, 0, 0, int(155 * (ratio ** 1.8))))
                base = Image.alpha_composite(base, vignette)
            else:
                # Mặc định: split_lr (Phân tách hai bên: Trái Trên + Phải)
                px2 = 720
                py2 = 95
                rot_angle2 = -4
                # Vignette mỏng hai bên, vùng giữa 32% - 60% hoàn toàn trong suốt cho mặt nhân vật
                vignette = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), (0, 0, 0, 0))
                vd = ImageDraw.Draw(vignette)
                for x in range(int(cls.WIDTH * 0.32)):
                    ratio = 1.0 - (x / (cls.WIDTH * 0.32))
                    vd.line([(x, 0), (x, cls.HEIGHT)], fill=(0, 0, 0, int(140 * (ratio ** 1.8))))
                for x in range(int(cls.WIDTH * 0.60), cls.WIDTH):
                    ratio = (x - int(cls.WIDTH * 0.60)) / (cls.WIDTH * 0.40)
                    vd.line([(x, 0), (x, cls.HEIGHT)], fill=(0, 0, 0, int(150 * (ratio ** 1.8))))
                base = Image.alpha_composite(base, vignette)

            # --- CỤM 1: Mở đầu / Chủ thể (Lead + Hero) ---
            sc1 = 0.95
            dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            f_hero_test = cls._get_font(fh_name, int(92 * sc1))
            w_h_test = dummy_draw.textbbox((0, 0), p["hero"], font=f_hero_test)[2] if p["hero"] else 0
            # Giới hạn không cho chữ vượt quá x=305 để né mặt nhân vật nam chính
            max_avail_w1 = 305 - px1
            if w_h_test > max_avail_w1 and max_avail_w1 > 50:
                sc1 *= (max_avail_w1 / w_h_test)
                sc1 = max(0.65, sc1)

            f_brush1 = cls._get_font(fh_name, int(40 * sc1))
            f_hero1 = cls._get_font(fh_name, int(92 * sc1))
            w_lead = dummy_draw.textbbox((0, 0), p["lead"], font=f_brush1)[2] if p["lead"] else 0
            w_hero = dummy_draw.textbbox((0, 0), p["hero"], font=f_hero1)[2] if p["hero"] else 0
            tc1_w = int(max(w_lead, w_hero, 100) + 40 * sc1)
            tc1_h = int(220 * sc1)

            tc1 = Image.new("RGBA", (tc1_w, tc1_h), (0, 0, 0, 0))
            td1 = ImageDraw.Draw(tc1)
            cur_bottom1 = int(8 * sc1)

            if p["lead"]:
                b_lead = dummy_draw.textbbox((0, 0), p["lead"], font=f_brush1)
                lead_y = cur_bottom1 - b_lead[1]
                td1.text((int(26 * sc1), lead_y + 2), p["lead"], font=f_brush1, fill=(0, 0, 0, 230))
                td1.text((int(24 * sc1), lead_y), p["lead"], font=f_brush1, fill=(245, 240, 235, 255))
                cur_bottom1 = lead_y + b_lead[3]

            if p["hero"]:
                b_hero = dummy_draw.textbbox((0, 0), p["hero"], font=f_hero1)
                hero_top = cur_bottom1 + int(16 * sc1)
                hero_y = hero_top - b_hero[1]
                for off in range(int(5 * sc1), 0, -1):
                    td1.text((int(12 * sc1) + off, hero_y + off), p["hero"], font=f_hero1, fill=(20, 0, 0, 240))
                td1.text((int(12 * sc1), hero_y), p["hero"], font=f_hero1, fill=(255, 250, 242, 255), stroke_width=2, stroke_fill=(35, 5, 5, 255))
                cur_bottom1 = hero_y + b_hero[3]

            rot1 = tc1.rotate(-6, resample=Image.Resampling.BICUBIC, expand=True)
            overlay.paste(rot1, (px1, py1), rot1)

            # --- CỤM 2: Vệt rách & Biến cố kịch tính (Banner + Pivot + Climax) ---
            sc2 = 1.05
            f_banner2 = cls._get_font(fb_name, int(27 * sc2))
            f_sub2 = cls._get_font(fh_name, int(35 * sc2))
            f_climax2 = cls._get_font(fc_name, int(64 * sc2))

            w_banner = dummy_draw.textbbox((0, 0), p["banner"], font=f_banner2)[2] if p["banner"] else 0
            w_pivot = dummy_draw.textbbox((0, 0), p["pivot"], font=f_sub2)[2] if p["pivot"] else 0
            w_climax = dummy_draw.textbbox((0, 0), p["climax"], font=f_climax2)[2] if p["climax"] else 0

            max_b_w = max(w_banner + int(50 * sc2), w_pivot, w_climax, 100)
            max_avail_w2 = cls.WIDTH - 660 - 25  # Khoảng an toàn 595px bên phải
            if max_b_w > max_avail_w2:
                scale_fit = max_avail_w2 / max_b_w
                sc2 *= scale_fit
                f_banner2 = cls._get_font(fb_name, int(27 * sc2))
                f_sub2 = cls._get_font(fh_name, int(35 * sc2))
                f_climax2 = cls._get_font(fc_name, int(64 * sc2))
                w_banner = dummy_draw.textbbox((0, 0), p["banner"], font=f_banner2)[2] if p["banner"] else 0
                w_pivot = dummy_draw.textbbox((0, 0), p["pivot"], font=f_sub2)[2] if p["pivot"] else 0
                w_climax = dummy_draw.textbbox((0, 0), p["climax"], font=f_climax2)[2] if p["climax"] else 0
                max_b_w = max(w_banner + int(50 * sc2), w_pivot, w_climax, 100)

            tc2_w = int(max_b_w + 50 * sc2)
            tc2_h = int(280 * sc2)

            tc2 = Image.new("RGBA", (tc2_w, tc2_h), (0, 0, 0, 0))
            td2 = ImageDraw.Draw(tc2)
            cur_bottom2 = int(6 * sc2)

            if p["banner"]:
                banner_w = min(tc2_w - int(8 * sc2), int(w_banner + 50 * sc2))
                banner_h = int(48 * sc2)
                b_img = cls._make_grunge_banner(banner_w, banner_h, color=(205, 12, 18), seed=888)
                b_sh = Image.new("RGBA", (banner_w, banner_h), (0, 0, 0, 0))
                ImageDraw.Draw(b_sh).rectangle([int(8 * sc2), int(3 * sc2), banner_w - int(8 * sc2), banner_h - int(3 * sc2)], fill=(0, 0, 0, 180))
                b_sh = b_sh.filter(ImageFilter.GaussianBlur(3))
                tc2.paste(b_sh, (int(8 * sc2), cur_bottom2 + int(2 * sc2)), b_sh)
                tc2.paste(b_img, (int(6 * sc2), cur_bottom2), b_img)

                bx = int(6 * sc2) + (banner_w - w_banner) // 2
                bbox_ban = td2.textbbox((0, 0), p["banner"], font=f_banner2)
                bh_text = bbox_ban[3] - bbox_ban[1]
                by = cur_bottom2 + (banner_h - bh_text) // 2 - int(2 * sc2)
                td2.text((bx + 1, by + 1), p["banner"], font=f_banner2, fill=(50, 0, 0, 240))
                td2.text((bx, by), p["banner"], font=f_banner2, fill=(255, 250, 235, 255))
                cur_bottom2 += banner_h

            if p["pivot"]:
                b_pivot = dummy_draw.textbbox((0, 0), p["pivot"], font=f_sub2)
                pivot_top = cur_bottom2 + int(14 * sc2)
                pivot_y = pivot_top - b_pivot[1]
                td2.text((int(32 * sc2), pivot_y + 2), p["pivot"], font=f_sub2, fill=(0, 0, 0, 230))
                td2.text((int(30 * sc2), pivot_y), p["pivot"], font=f_sub2, fill=(250, 245, 240, 255))
                cur_bottom2 = pivot_y + b_pivot[3]

            if p["climax"]:
                b_climax = dummy_draw.textbbox((0, 0), p["climax"], font=f_climax2)
                climax_top = cur_bottom2 + int(16 * sc2)
                climax_y = climax_top - b_climax[1]
                for off in range(int(5 * sc2), 0, -1):
                    td2.text((int(12 * sc2) + off, climax_y + off), p["climax"], font=f_climax2, fill=(20, 0, 0, 240))
                td2.text((int(12 * sc2), climax_y), p["climax"], font=f_climax2, fill=(235, 15, 20, 255), stroke_width=2, stroke_fill=(65, 0, 0, 255))
                cur_bottom2 = climax_y + b_climax[3]

            rot2 = tc2.rotate(rot_angle2, resample=Image.Resampling.BICUBIC, expand=True)
            px2 = max(660, min(cls.WIDTH - int(rot2.size[0]) - 20, 750))
            overlay.paste(rot2, (px2, py2), rot2)

        else:
            # =========================================================================
            # BỐ CỤC DỒN TOÀN BỘ (UNIFIED LAYOUT: full_right, full_left, compact, custom)
            # =========================================================================
            if pos_clean in ("full_right", "right"):
                # Dồn trọn vẹn sang phải: Chữ cực to (Khi nhân vật ở bên trái)
                sc = max(0.5, min(1.5, (font_scale or 1.05) if position == "custom" else 1.05))
                px = pos_x if pos_x is not None else 740
                py = pos_y if pos_y is not None else 60
                rot_angle = -4
                badge_pos = (cls.WIDTH - 165, 25)
                vignette = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), (0, 0, 0, 0))
                vd = ImageDraw.Draw(vignette)
                for x in range(int(cls.WIDTH * 0.58), cls.WIDTH):
                    ratio = (x - int(cls.WIDTH * 0.58)) / (cls.WIDTH * 0.42)
                    vd.line([(x, 0), (x, cls.HEIGHT)], fill=(0, 0, 0, int(165 * (ratio ** 1.8))))
                base = Image.alpha_composite(base, vignette)
            elif pos_clean == "full_left":
                # Dồn trọn vẹn sang trái: Chữ cực to (Khi nhân vật ở bên phải)
                sc = max(0.5, min(1.5, (font_scale or 1.05) if position == "custom" else 1.05))
                px = pos_x if pos_x is not None else 20
                py = pos_y if pos_y is not None else 60
                rot_angle = -6
                badge_pos = (28, 18)
                vignette = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), (0, 0, 0, 0))
                vd = ImageDraw.Draw(vignette)
                for x in range(int(cls.WIDTH * 0.46)):
                    ratio = 1.0 - (x / (cls.WIDTH * 0.46))
                    vd.line([(x, 0), (x, cls.HEIGHT)], fill=(0, 0, 0, int(165 * (ratio ** 1.8))))
                base = Image.alpha_composite(base, vignette)
            elif pos_clean == "bottom_left":
                sc = max(0.4, min(1.5, font_scale or 0.72))
                px = pos_x if pos_x is not None else 20
                py = pos_y if pos_y is not None else 390
                rot_angle = -6
                badge_pos = (28, 18)
                vignette = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), (0, 0, 0, 0))
                vd = ImageDraw.Draw(vignette)
                for y in range(int(cls.HEIGHT * 0.50), cls.HEIGHT):
                    ratio = (y - int(cls.HEIGHT * 0.50)) / (cls.HEIGHT * 0.50)
                    vd.line([(0, y), (int(cls.WIDTH * 0.45), y)], fill=(0, 0, 0, int(160 * (ratio ** 1.8))))
                base = Image.alpha_composite(base, vignette)
            elif pos_clean == "bottom_right":
                sc = max(0.4, min(1.5, font_scale or 0.72))
                px = pos_x if pos_x is not None else 780
                py = pos_y if pos_y is not None else 390
                rot_angle = -4
                badge_pos = (cls.WIDTH - 165, 25)
                vignette = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), (0, 0, 0, 0))
                vd = ImageDraw.Draw(vignette)
                for y in range(int(cls.HEIGHT * 0.50), cls.HEIGHT):
                    ratio = (y - int(cls.HEIGHT * 0.50)) / (cls.HEIGHT * 0.50)
                    vd.line([(int(cls.WIDTH * 0.55), y), (cls.WIDTH, y)], fill=(0, 0, 0, int(165 * (ratio ** 1.8))))
                base = Image.alpha_composite(base, vignette)
            elif pos_clean == "custom":
                sc = max(0.4, min(1.5, font_scale or 0.72))
                px = pos_x if pos_x is not None else 16
                py = pos_y if pos_y is not None else 75
                rot_angle = -5
                badge_pos = (28, 18) if px < 500 else (cls.WIDTH - 165, 25)
                vignette = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), (0, 0, 0, 0))
                vd = ImageDraw.Draw(vignette)
                if px < 500:
                    for x in range(int(cls.WIDTH * 0.35)):
                        ratio = 1.0 - (x / (cls.WIDTH * 0.35))
                        vd.line([(x, 0), (x, cls.HEIGHT)], fill=(0, 0, 0, int(150 * (ratio ** 1.8))))
                base = Image.alpha_composite(base, vignette)
            else:
                # Mặc định: compact_tl / top_left (Né mặt tối đa, nằm gọn góc trên bên trái)
                sc = max(0.4, min(1.5, font_scale or 0.68))
                px = pos_x if pos_x is not None else 16
                py = pos_y if pos_y is not None else 75
                rot_angle = -6
                badge_pos = (28, 18)
                vignette = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), (0, 0, 0, 0))
                vd = ImageDraw.Draw(vignette)
                for x in range(int(cls.WIDTH * 0.34)):
                    ratio = 1.0 - (x / (cls.WIDTH * 0.34))
                    vd.line([(x, 0), (x, cls.HEIGHT)], fill=(0, 0, 0, int(160 * (ratio ** 1.8))))
                base = Image.alpha_composite(base, vignette)

            f_brush = cls._get_font(fh_name, int(40 * sc))
            f_hero = cls._get_font(fh_name, int(92 * sc))
            f_banner = cls._get_font(fb_name, int(26 * sc))
            f_sub = cls._get_font(fh_name, int(34 * sc))
            f_climax = cls._get_font(fc_name, int(62 * sc))

            dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            w_lead = dummy_draw.textbbox((0, 0), p["lead"], font=f_brush)[2] if p["lead"] else 0
            w_hero = dummy_draw.textbbox((0, 0), p["hero"], font=f_hero)[2] if p["hero"] else 0
            w_banner = dummy_draw.textbbox((0, 0), p["banner"], font=f_banner)[2] if p["banner"] else 0
            w_pivot = dummy_draw.textbbox((0, 0), p["pivot"], font=f_sub)[2] if p["pivot"] else 0
            w_climax = dummy_draw.textbbox((0, 0), p["climax"], font=f_climax)[2] if p["climax"] else 0

            max_line_w = max(w_lead, w_hero, w_banner + int(50 * sc), w_pivot, w_climax, 100)
            tc_w = int(max_line_w + 40 * sc)
            tc_h = int(480 * sc)

            tc = Image.new("RGBA", (tc_w, tc_h), (0, 0, 0, 0))
            td = ImageDraw.Draw(tc)
            cur_bottom = int(8 * sc)

            if p["lead"]:
                b_lead = dummy_draw.textbbox((0, 0), p["lead"], font=f_brush)
                lead_y = cur_bottom - b_lead[1]
                td.text((int(38 * sc), lead_y + 2), p["lead"], font=f_brush, fill=(0, 0, 0, 230))
                td.text((int(36 * sc), lead_y), p["lead"], font=f_brush, fill=(245, 240, 235, 255))
                cur_bottom = lead_y + b_lead[3]

            if p["hero"]:
                b_hero = dummy_draw.textbbox((0, 0), p["hero"], font=f_hero)
                hero_top = cur_bottom + int(16 * sc)
                hero_y = hero_top - b_hero[1]
                for off in range(int(5 * sc), 0, -1):
                    td.text((int(15 * sc) + off, hero_y + off), p["hero"], font=f_hero, fill=(20, 0, 0, 240))
                td.text((int(15 * sc), hero_y), p["hero"], font=f_hero, fill=(255, 250, 242, 255), stroke_width=2, stroke_fill=(35, 5, 5, 255))
                cur_bottom = hero_y + b_hero[3]

            if p["banner"]:
                banner_w = min(tc_w - int(8 * sc), int(w_banner + 50 * sc))
                banner_h = int(46 * sc)
                b_img = cls._make_grunge_banner(banner_w, banner_h, color=(205, 12, 18), seed=888)
                b_sh = Image.new("RGBA", (banner_w, banner_h), (0, 0, 0, 0))
                ImageDraw.Draw(b_sh).rectangle([int(8 * sc), int(3 * sc), banner_w - int(8 * sc), banner_h - int(3 * sc)], fill=(0, 0, 0, 180))
                b_sh = b_sh.filter(ImageFilter.GaussianBlur(3))
                banner_top = cur_bottom + int(14 * sc)
                tc.paste(b_sh, (int(8 * sc), banner_top + int(2 * sc)), b_sh)
                tc.paste(b_img, (int(6 * sc), banner_top), b_img)

                bx = int(6 * sc) + (banner_w - w_banner) // 2
                bbox_ban = td.textbbox((0, 0), p["banner"], font=f_banner)
                bh_text = bbox_ban[3] - bbox_ban[1]
                by = banner_top + (banner_h - bh_text) // 2 - int(2 * sc)
                td.text((bx + 1, by + 1), p["banner"], font=f_banner, fill=(50, 0, 0, 240))
                td.text((bx, by), p["banner"], font=f_banner, fill=(255, 250, 235, 255))
                cur_bottom = banner_top + banner_h

            if p["pivot"]:
                b_pivot = dummy_draw.textbbox((0, 0), p["pivot"], font=f_sub)
                pivot_top = cur_bottom + int(14 * sc)
                pivot_y = pivot_top - b_pivot[1]
                td.text((int(38 * sc), pivot_y + 2), p["pivot"], font=f_sub, fill=(0, 0, 0, 230))
                td.text((int(36 * sc), pivot_y), p["pivot"], font=f_sub, fill=(250, 245, 240, 255))
                cur_bottom = pivot_y + b_pivot[3]

            if p["climax"]:
                b_climax = dummy_draw.textbbox((0, 0), p["climax"], font=f_climax)
                climax_top = cur_bottom + int(16 * sc)
                climax_y = climax_top - b_climax[1]
                for off in range(int(4 * sc), 0, -1):
                    td.text((int(12 * sc) + off, climax_y + off), p["climax"], font=f_climax, fill=(20, 0, 0, 240))
                td.text((int(12 * sc), climax_y), p["climax"], font=f_climax, fill=(235, 15, 20, 255), stroke_width=2, stroke_fill=(65, 0, 0, 255))
                cur_bottom = climax_y + b_climax[3]

            rotated_tc = tc.rotate(rot_angle, resample=Image.Resampling.BICUBIC, expand=True)
            overlay.paste(rotated_tc, (px, py), rotated_tc)

        # 4. Huy hiệu số tập (Badge: P1, P2...)
        badge_clean = (badge_text or "").strip().upper()
        if badge_clean:
            f_badge = cls._get_font("Protest_Revolution.ttf", 22)
            d_test = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            b_box = d_test.textbbox((0, 0), badge_clean, font=f_badge)
            tw = b_box[2] - b_box[0]
            th = b_box[3] - b_box[1]
            bw = max(110, int(tw + 34))
            bh = 42
            bdg = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
            bdg_d = ImageDraw.Draw(bdg)
            bdg_d.rounded_rectangle([3, 3, bw, bh], radius=8, fill=(0, 0, 0, 160))
            bdg_d.rounded_rectangle([0, 0, bw - 3, bh - 3], radius=8, fill=(185, 15, 20, 240), outline=(255, 215, 0, 255), width=2)
            tx = (bw - 3 - tw) // 2 - b_box[0]
            ty = (bh - 3 - th) // 2 - b_box[1]
            bdg_d.text((tx, ty), badge_clean, font=f_badge, fill=(255, 255, 255, 255))
            overlay.paste(bdg, badge_pos, bdg)

        # 5. Lưu kết quả JPEG chất lượng cao 95%
        final_img = Image.alpha_composite(base, overlay).convert("RGB")
        final_img.save(str(out_file), "JPEG", quality=95, optimize=True)
        return out_file

    @classmethod
    def extract_video_frame(cls, video_path: str | Path, output_path: str | Path, timestamp_sec: float = 3.0) -> Path:
        """Trích xuất 1 khung hình sắc nét từ video bằng FFmpeg tại timestamp_sec (mặc định giây thứ 3)."""
        import subprocess
        from core.paths import find_binary

        v_path = Path(video_path)
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg_bin = find_binary("ffmpeg.exe") or "ffmpeg"

        m, s = divmod(int(timestamp_sec), 60)
        h, m = divmod(m, 60)
        time_str = f"{h:02d}:{m:02d}:{s:02d}"

        cmd = [
            str(ffmpeg_bin),
            "-y",
            "-ss", time_str,
            "-i", str(v_path),
            "-vframes", "1",
            "-q:v", "2",
            str(out_file)
        ]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=flags)

        # Nếu timestamp vượt quá độ dài video, thử fallback về giây thứ 1
        if not out_file.exists() or out_file.stat().st_size == 0:
            cmd[2] = "00:00:01"
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=flags)

        if not out_file.exists() or out_file.stat().st_size == 0:
            raise RuntimeError(f"Không thể trích xuất khung hình từ video: {res.stderr[:200]}")
        return out_file

    @classmethod
    def generate_ai_thumbnail_image(cls, prompt_or_title: str, output_path: str | Path) -> Path:
        """Tạo hình ảnh Thumbnail nghệ thuật chất lượng cao (1280x720) bằng AI (Pollinations.ai FLUX hoàn toàn MIỄN PHÍ)."""
        import urllib.request
        import urllib.parse

        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

        clean_p = (prompt_or_title or "").strip()
        # Xây dựng prompt điện ảnh cuốn hút
        full_prompt = (
            f"cinematic dramatic YouTube thumbnail wallpaper, {clean_p}, "
            "vibrant colors, epic lighting, highly detailed, photorealistic, 8k resolution, masterpiece"
        )
        encoded = urllib.parse.quote(full_prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=1280&height=720&nologo=true&model=flux"

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=45) as response, open(out_file, "wb") as f_out:
            f_out.write(response.read())

        if not out_file.exists() or out_file.stat().st_size < 1000:
            raise RuntimeError("Không thể tải ảnh AI từ Pollinations.ai")
        return out_file
