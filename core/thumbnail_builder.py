from __future__ import annotations

import os
import re
import math
import random
import datetime
import subprocess
from pathlib import Path
from typing import Optional, Dict, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageStat
from core.paths import find_binary



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

        # Kiểm tra trực tiếp thư mục Fonts của Windows
        win_font = Path("C:/Windows/Fonts") / font_filename
        if win_font.exists():
            try:
                return ImageFont.truetype(str(win_font), size)
            except Exception:
                pass

        # Fallback candidates từ hệ thống Windows
        system_candidates = [
            r"C:\Windows\Fonts\seguibl.ttf",
            r"C:\Windows\Fonts\ariblk.ttf",
            r"C:\Windows\Fonts\impact.ttf",
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

        def _safe_randint(a: int, b: int) -> int:
            if a > b:
                a, b = b, a
            elif a == b:
                return a
            return random.randint(a, b)

        # 1. Lõi đặc ở trung tâm để đảm bảo chữ trên banner luôn sắc nét 100%
        rx1 = min(pad + int(20 * scale), max(0, sw // 3))
        rx2 = max(rx1 + 10, sw - pad - int(20 * scale))
        ry1 = max(0, cy - h_core)
        ry2 = max(ry1 + 10, cy + h_core)
        draw.rectangle([rx1, ry1, rx2, ry2], fill=255)

        # 2. Vệt cọ xước ngang mô phỏng nét chổi lông khô kéo trên giấy
        for _ in range(320):
            y_pos = cy + (random.random() - 0.5) * sh * 0.86
            x1 = _safe_randint(0, pad + int(15 * scale))
            x2 = sw - _safe_randint(0, pad + int(25 * scale))
            lw = _safe_randint(int(2 * scale), int(7 * scale))
            draw.line([(x1, y_pos), (x2, y_pos)], fill=_safe_randint(190, 255), width=lw)

        # 3. Giọt sơn nhỏ rơi xuống từ mép dưới
        for _ in range(45):
            dx = _safe_randint(pad + int(25 * scale), max(pad + int(25 * scale) + 1, sw - pad - int(25 * scale)))
            dy_start = cy + h_core - int(4 * scale)
            dy_len = _safe_randint(int(6 * scale), int(26 * scale))
            draw.line([(dx, dy_start), (dx, dy_start + dy_len)], fill=_safe_randint(180, 255), width=_safe_randint(int(2 * scale), int(4 * scale)))

        # 4. Đầu xước rách ở hai mép trái - phải
        for _ in range(70):
            ly = cy + (random.random() - 0.5) * sh * 0.75
            draw.line([(0, ly), (pad + _safe_randint(int(8 * scale), int(35 * scale)), ly)], fill=_safe_randint(180, 255), width=_safe_randint(2 * scale, 5 * scale))
            ry = cy + (random.random() - 0.5) * sh * 0.75
            draw.line([(sw - pad - _safe_randint(int(8 * scale), int(35 * scale)), ry), (sw, ry)], fill=_safe_randint(180, 255), width=_safe_randint(2 * scale, 5 * scale))

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

        # 1. Tách theo dấu phân cách rõ ràng nếu có ( - , – , — , | , / , \n)
        split_sep = None
        for sep in [" - ", " – ", " — ", " | ", " / ", "\n", "-", "–", "—"]:
            if sep in raw:
                split_sep = sep
                break

        if split_sep:
            s_idx = raw.find(split_sep)
            part1 = raw[:s_idx].strip()
            pivot = ""
            part2 = raw[s_idx + len(split_sep):].strip()
        else:
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

        # Bảo vệ từ ghép tiếng Việt
        compound_words = [
            "dưa hấu", "bạn gái", "bạn trai", "thần thụ", "kỷ nguyên", "hoàng gia",
            "chiến thần", "ma đế", "tiêu sư", "quy củ", "phấn trắng", "hạt dưa",
            "thiên hạ", "cổ trang", "cung đình", "hoàng cung", "tình yêu",
            "cuộc chiến", "thần bí", "vô địch", "huyết chiến", "đại náo"
        ]

        if matched_lead:
            lead = matched_lead.upper()
            rem = part1[len(matched_lead):].strip()
            rem_words = [w for w in rem.split() if w]
            if len(rem_words) <= 2:
                hero = " ".join(rem_words).upper()
            else:
                # Kiểm tra từ ghép tại ranh giới
                split_at = 2
                if len(rem_words) > 2 and f"{rem_words[1]} {rem_words[2]}".lower() in compound_words:
                    split_at = 3
                hero = " ".join(rem_words[:split_at]).upper()
                banner = " ".join(rem_words[split_at:]).upper()
        else:
            if len(words1) <= 2:
                hero = " ".join(words1).upper()
            elif len(words1) <= 4:
                split_at = 2
                if len(words1) > 2 and f"{words1[1]} {words1[2]}".lower() in compound_words:
                    split_at = 3
                hero = " ".join(words1[:split_at]).upper()
                banner = " ".join(words1[split_at:]).upper()
            else:
                # Kiểm tra các ranh giới từ ghép
                s1 = 2
                if f"{words1[1]} {words1[2]}".lower() in compound_words:
                    s1 = 3
                s2 = s1 + 2
                if len(words1) > s2 and f"{words1[s2-1]} {words1[s2]}".lower() in compound_words:
                    s2 += 1
                lead = " ".join(words1[:s1]).upper()
                hero = " ".join(words1[s1:s2]).upper()
                banner = " ".join(words1[s2:]).upper()

        climax = ""
        if part2:
            words2 = [w for w in part2.split() if w]
            if not banner and len(words2) >= 3:
                mid2 = max(1, len(words2) // 2)
                if f"{words2[mid2-1]} {words2[mid2]}".lower() in compound_words and mid2 + 1 < len(words2):
                    mid2 += 1
                banner = " ".join(words2[:mid2]).upper()
                climax = " ".join(words2[mid2:]).upper()
            else:
                climax = part2.upper()

        return {
            "lead": lead,
            "hero": hero,
            "banner": banner,
            "pivot": pivot.upper(),
            "climax": climax,
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
    def extract_frame_from_video(
        cls,
        video_path: str | Path,
        time_sec: float = 3.0,
        out_path: Optional[str | Path] = None
    ) -> Path:
        """Trích xuất 1 khung hình sắc nét (1080p/720p) từ video làm ảnh nền Thumbnail bằng FFmpeg."""
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Video không tồn tại: {video_path}")

        if out_path is None:
            out_path = video_path.parent / f"frame_{video_path.stem}.jpg"
        else:
            out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        ffmpeg_bin = find_binary("ffmpeg.exe")
        cmd = [
            ffmpeg_bin,
            "-y",
            "-ss", f"{max(0.1, time_sec):.3f}",
            "-i", str(video_path),
            "-update", "1",
            "-frames:v", "1",
            "-q:v", "2",
            str(out_path)
        ]
        cflags = 0
        if os.name == "nt":
            cflags = subprocess.CREATE_NO_WINDOW
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=cflags)

        if not out_path.exists() or out_path.stat().st_size == 0:
            # Fallback nếu video quá ngắn
            cmd_fallback = [
                ffmpeg_bin,
                "-y",
                "-ss", "0.500",
                "-i", str(video_path),
                "-update", "1",
                "-frames:v", "1",
                "-q:v", "2",
                str(out_path)
            ]
            subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=cflags)

        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RuntimeError(f"Không thể trích xuất frame từ {video_path.name}")
        return out_path

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
        enable_badge: bool = True,
        enable_highlight: bool = True,
    ) -> Path:
        """Tạo thumbnail chuẩn 16:9 1280x720: Giữ nguyên 100% màu gốc ảnh, nét chữ bút pháp kiếm hiệp hoặc YouTube drama, né mặt nhân vật và hỗ trợ bật/tắt độc lập Huy hiệu & Chữ to nổi bật."""
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
        # TRƯỜNG HỢP 1: TẮT CẢ 2 (GIỮ NGUYÊN 100% ẢNH GỐC)
        # =========================================================================
        if not enable_badge and not enable_highlight:
            final_img = base.convert("RGB")
            final_img.save(str(out_file), "JPEG", quality=95, optimize=True)
            return out_file

        # =========================================================================
        # TRƯỜNG HỢP 2: CHỈ ĐÓNG HUY HIỆU TẬP (Bật Huy hiệu, Tắt Chữ nổi bật)
        # 100% giữ nguyên ảnh gốc, chỉ dập duy nhất nhãn số tập ở góc
        # =========================================================================
        if badge_only or (enable_badge and not enable_highlight):
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
        if st in ("drama", "tam_ly", "youtube_pop", "modern") or any(k in st for k in ("drama", "tam_ly", "tâm lý", "tam ly")):
            return cls._create_drama_thumbnail(
                base=base,
                output_path=out_file,
                highlight_title=highlight_title,
                subtitle=subtitle,
                badge_text=badge_text,
                channel_logo=channel_logo,
                pos_x=pos_x,
                pos_y=pos_y,
                font_scale=font_scale,
                badge_position=badge_position,
                enable_badge=enable_badge,
                enable_highlight=enable_highlight,
            )

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
                bx1_sh = int(8 * sc2)
                by1_sh = int(3 * sc2)
                bx2_sh = max(bx1_sh + 10, banner_w - bx1_sh)
                by2_sh = max(by1_sh + 10, banner_h - by1_sh)
                ImageDraw.Draw(b_sh).rectangle([bx1_sh, by1_sh, bx2_sh, by2_sh], fill=(0, 0, 0, 180))
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
                bx1_sh = int(8 * sc)
                by1_sh = int(3 * sc)
                bx2_sh = max(bx1_sh + 10, banner_w - bx1_sh)
                by2_sh = max(by1_sh + 10, banner_h - by1_sh)
                ImageDraw.Draw(b_sh).rectangle([bx1_sh, by1_sh, bx2_sh, by2_sh], fill=(0, 0, 0, 180))
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
        if enable_badge:
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
    def _create_drama_thumbnail(
        cls,
        base: Image.Image,
        output_path: Path,
        highlight_title: str = "",
        subtitle: str = "",
        badge_text: str = "",
        channel_logo: Optional[str | Path] = None,
        pos_x: Optional[int] = None,
        pos_y: Optional[int] = None,
        font_scale: float = 1.0,
        badge_position: str = "top_left",
        enable_badge: bool = True,
        enable_highlight: bool = True,
    ) -> Path:
        """Tạo thumbnail chuẩn YouTube Drama / Radio Stories 60% Trái - 40% Phải:
        - Cột trái chiếm 58-62% bề ngang (W <= 760px), chữ to khổng lồ, xếp 5 tầng từ đỉnh đến đáy.
        - Tầng 1 (y: ~18px): Tiêu đề Series đỏ rực viền trắng phát sáng cyan (font 96px)
        - Tầng 2 (y: ~140px): Tiêu đề kịch bản drama vàng rực viền đen đổ bóng đậm (font 68px)
        - Tầng 3 (y: ~330px): Tên Kênh / Định danh Radio Stories Cyan lớn (font 84px)
        - Tầng 4 (y: ~460px): Dòng ngày phát hành 'Production: DD/MM/YYYY' (font 46px)
        - Tầng 5 (y: ~560px): Cụm chốt đáy Full Episode / TẬP X (font 102px) + Box Badge Radio Drama 2 màu
        - Góc phải trên: Dải ruy băng chéo góc đỏ chữ trắng 'NEW' chuẩn xác
        """
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

        if not enable_badge and not enable_highlight:
            final_img = base.convert("RGB")
            final_img.save(str(out_file), "JPEG", quality=95, optimize=True)
            return out_file

        sc = max(0.65, min(1.35, font_scale or 1.0))
        overlay = Image.new("RGBA", (cls.WIDTH, cls.HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        dummy_d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

        # Phân tích câu 2 tầng chuẩn YouTube Drama (bảo toàn cụm từ có nghĩa)
        raw_hl = (highlight_title or "").strip().rstrip(":").strip()
        tier1 = ""
        tier2 = ""
        for sep in [":", " - ", " – ", " — ", " | ", "\n"]:
            if sep in raw_hl:
                parts = [x.strip() for x in raw_hl.split(sep, 1) if x.strip()]
                tier1 = parts[0].upper()
                tier2 = parts[1].upper() if len(parts) > 1 else ""
                break

        if not tier1:
            words_hl = [w for w in raw_hl.split() if w]
            if len(words_hl) <= 4:
                tier1 = raw_hl.upper()
                tier2 = ""
            else:
                mid_hl = len(words_hl) // 2
                tier1 = " ".join(words_hl[:mid_hl]).upper()
                tier2 = " ".join(words_hl[mid_hl:]).upper()

        if not tier1:
            tier1 = "TIÊU ĐỀ NỔI BẬT"

        has_vn = bool(re.search(r"[À-ỹà-ỹĐđ]", f"{tier1} {tier2}"))
        def get_drama_font(sz: int):
            f_list = ["seguibl.ttf", "arialbd.ttf", "tahomabd.ttf"] if has_vn else ["impact.ttf", "seguibl.ttf", "arialbd.ttf"]
            for fname in f_list:
                f = cls._get_font(fname, sz)
                if f:
                    return f
            return ImageFont.load_default()

        # Tên kênh chính xác
        clean_sub = re.sub(r"\(.*?\)", "", subtitle or "").strip()
        if clean_sub:
            if "Radio" in clean_sub or "Story" in clean_sub or "Stories" in clean_sub:
                ch_main_text = clean_sub
            else:
                ch_main_text = f"{clean_sub} Radio Stories"
        else:
            ch_main_text = "TMT Radio Stories"

        # Tag viết tắt cho Box Badge
        words_sub = [w for w in clean_sub.split() if w]
        if len(words_sub) >= 2:
            tag_name = "".join(w[0] for w in words_sub).upper()[:5]
        elif len(words_sub) == 1:
            tag_name = clean_sub[:4].upper()
        else:
            tag_name = "TMTRD"

        x_left = pos_x if pos_x is not None else 28
        max_col_w = 800  # Chiếm trọn 62-65% chiều ngang bên trái

        if enable_highlight:
            # =================================================================
            # TẦNG 1 (y: ~12px): Tiêu đề Series đỏ rực viền trắng phát sáng cyan (SIÊU TO)
            # =================================================================
            y1 = pos_y if pos_y is not None else 12
            f_sz1 = int(155 * sc)
            f1 = get_drama_font(f_sz1)
            w1 = dummy_d.textbbox((0, 0), tier1, font=f1)[2]
            if w1 > max_col_w:
                f_sz1 = max(45, int(f_sz1 * (max_col_w / w1)))
                f1 = get_drama_font(f_sz1)

            # Outer glow Cyan
            draw.text((x_left, y1), tier1, font=f1, fill=(0, 225, 255, 255), stroke_width=int(18 * sc), stroke_fill=(0, 225, 255, 255))
            # Inner border White
            draw.text((x_left, y1), tier1, font=f1, fill=(255, 255, 255, 255), stroke_width=int(8 * sc), stroke_fill=(255, 255, 255, 255))
            # Fill Red
            draw.text((x_left, y1), tier1, font=f1, fill=(240, 20, 25, 255))

            bbox1 = dummy_d.textbbox((0, 0), tier1, font=f1)
            h1 = bbox1[3] - bbox1[1]
            cur_y = y1 + h1 + int(8 * sc)

            # =================================================================
            # TẦNG 2: Tiêu đề kịch bản drama vàng rực viền đen đậm (KHOẢNG CÁCH SÁT)
            # =================================================================
            if tier2:
                f_sz2 = int(110 * sc)
                f2 = get_drama_font(f_sz2)
                w2 = dummy_d.textbbox((0, 0), tier2, font=f2)[2]
                tier2_lines = [tier2]
                if w2 > max_col_w:
                    words2 = tier2.split()
                    if len(words2) >= 4:
                        mid2 = len(words2) // 2
                        tier2_lines = [" ".join(words2[:mid2]), " ".join(words2[mid2:])]
                    else:
                        f_sz2 = max(38, int(f_sz2 * (max_col_w / w2)))
                        f2 = get_drama_font(f_sz2)

                for line2 in tier2_lines:
                    w_l2 = dummy_d.textbbox((0, 0), line2, font=f2)[2]
                    if w_l2 > max_col_w:
                        f2_curr = get_drama_font(max(34, int(f_sz2 * (max_col_w / w_l2))))
                    else:
                        f2_curr = f2
                    # Drop shadow
                    draw.text((x_left + 5, cur_y + 5), line2, font=f2_curr, fill=(0, 0, 0, 255), stroke_width=int(10 * sc), stroke_fill=(0, 0, 0, 255))
                    # Black outer stroke & Yellow fill
                    draw.text((x_left, cur_y), line2, font=f2_curr, fill=(255, 230, 0, 255), stroke_width=int(7 * sc), stroke_fill=(0, 0, 0, 255))
                    bb_l2 = dummy_d.textbbox((0, 0), line2, font=f2_curr)
                    cur_y += (bb_l2[3] - bb_l2[1]) + int(6 * sc)

            cur_y = max(cur_y + int(8 * sc), int(295 * sc))

            # =================================================================
            # TẦNG 3 (y: ~295px): Tên Kênh / Định danh Radio Stories Cyan khổng lồ
            # =================================================================
            f_sz3 = int(120 * sc)
            f3 = get_drama_font(f_sz3)
            w3 = dummy_d.textbbox((0, 0), ch_main_text, font=f3)[2]
            if w3 > max_col_w:
                f_sz3 = max(45, int(f_sz3 * (max_col_w / w3)))
                f3 = get_drama_font(f_sz3)

            # Drop shadow
            draw.text((x_left + 6, cur_y + 6), ch_main_text, font=f3, fill=(0, 0, 0, 255), stroke_width=int(12 * sc), stroke_fill=(0, 0, 0, 255))
            # Inner white stroke + outer black border
            draw.text((x_left, cur_y), ch_main_text, font=f3, fill=(255, 255, 255, 255), stroke_width=int(7 * sc), stroke_fill=(255, 255, 255, 255))
            draw.text((x_left, cur_y), ch_main_text, font=f3, fill=(0, 215, 255, 255))

            bbox3 = dummy_d.textbbox((0, 0), ch_main_text, font=f3)
            h3 = bbox3[3] - bbox3[1]
            y3_bottom = cur_y + h3

            # Chuẩn bị trước vị trí TẦNG 5 để căn TẦNG 4 cách 5%-10%
            ep_y = 545

            # =================================================================
            # TẦNG 4: Dòng thông tin sản xuất Production: DD/MM/YYYY
            # (Tự động canh vị trí thoáng đãng, cách Tầng 5 khoảng 5%-8% ~45px)
            # =================================================================
            now_dt = datetime.datetime.now().strftime("%d/%m/%Y")
            prod_text = f"Production: {now_dt}"
            f_sz4 = int(48 * sc)
            f4 = cls._get_font("arialbd.ttf", f_sz4)
            bbox4 = dummy_d.textbbox((0, 0), prod_text, font=f4)
            h4 = bbox4[3] - bbox4[1]

            y4_target = ep_y - h4 - int(42 * sc)
            y4 = max(y3_bottom + int(16 * sc), y4_target)

            draw.text((x_left + 3, y4 + 3), prod_text, font=f4, fill=(0, 0, 0, 240), stroke_width=int(6 * sc), stroke_fill=(0, 0, 0, 240))
            draw.text((x_left, y4), prod_text, font=f4, fill=(255, 255, 255, 255), stroke_width=int(2 * sc), stroke_fill=(0, 0, 0, 255))

        # =====================================================================
        # TẦNG 5 (y: ~545-690px): Cụm chốt đáy Full Episode / TẬP X + Box Badge
        # (BẮT BUỘC LUÔN CÓ trong phong cách YouTube Drama để tạo nhận diện)
        # =====================================================================
        badge_clean = (badge_text or "").strip().upper()
        if badge_clean in ("FULL EPISODE", "FULL", "FULL TẬP", "FULL_EPISODE"):
            ep_text = "Full Episode"
        elif badge_clean.startswith("P") and badge_clean[1:].isdigit():
            ep_text = f"TẬP {badge_clean[1:]}"
        elif badge_clean.startswith("TẬP") or badge_clean.isdigit():
            ep_text = f"TẬP {badge_clean}" if badge_clean.isdigit() else badge_clean
        elif badge_clean:
            ep_text = badge_clean
        else:
            ep_text = "Full Episode"

        f_ep_sz = int(135 * sc)
        f_ep = get_drama_font(f_ep_sz)
        w_ep = dummy_d.textbbox((0, 0), ep_text, font=f_ep)[2]

        box_w_est = int(250 * sc)
        if x_left + w_ep + int(24 * sc) + box_w_est > cls.WIDTH - 20:
            f_ep_sz = max(65, int(f_ep_sz * ((cls.WIDTH - 20 - x_left - box_w_est - 24) / max(1, w_ep))))
            f_ep = get_drama_font(f_ep_sz)
            w_ep = dummy_d.textbbox((0, 0), ep_text, font=f_ep)[2]

        ep_y = 545
        # Vẽ Full Episode / TẬP X to khổng lồ
        draw.text((x_left + 7, ep_y + 7), ep_text, font=f_ep, fill=(0, 0, 0, 255), stroke_width=int(12 * sc), stroke_fill=(0, 0, 0, 255))
        draw.text((x_left, ep_y), ep_text, font=f_ep, fill=(255, 255, 255, 255), stroke_width=int(7 * sc), stroke_fill=(0, 0, 0, 255))

        # Box Badge Radio Drama 2 màu đặt ngay cạnh Full Episode
        bx1 = x_left + w_ep + int(24 * sc)
        by1 = ep_y - int(4 * sc)
        by2 = by1 + int(148 * sc)

        f_tag = get_drama_font(int(82 * sc))
        w_tag = dummy_d.textbbox((0, 0), tag_name, font=f_tag)[2]
        blue_w = int(115 * sc)
        box_w = blue_w + w_tag + int(36 * sc)
        bx2 = min(bx1 + box_w, cls.WIDTH - 20)

        if bx1 < cls.WIDTH - 60 and bx2 > bx1 + 30:
            # Khung nền Vàng viền Đen dày
            draw.rectangle([bx1, by1, bx2, by2], fill=(255, 222, 0, 255), outline=(0, 0, 0, 255), width=5)
            # Khối nhỏ Xanh Dương bên trái
            draw.rectangle([bx1 + 4, by1 + 4, bx1 + blue_w, by2 - 4], fill=(0, 65, 175, 255), outline=(0, 0, 0, 255), width=3)

            # Chữ RADIO nhỏ
            f_mic_top = cls._get_font("arialbd.ttf", int(17 * sc))
            draw.text((bx1 + int(25 * sc), by1 + int(16 * sc)), "RADIO", font=f_mic_top, fill=(255, 255, 255, 255))

            # Icon micro trắng ở giữa
            mic_cx = bx1 + blue_w // 2
            mic_cy = by1 + int(74 * sc)
            if mic_cx + 6 > mic_cx - 6:
                draw.rounded_rectangle([mic_cx - 8, mic_cy - 15, mic_cx + 8, mic_cy + 5], radius=5, fill=(255, 255, 255, 255))
            draw.arc([mic_cx - 13, mic_cy - 10, mic_cx + 13, mic_cy + 10], start=0, end=180, fill=(255, 255, 255, 255), width=4)
            draw.line([(mic_cx, mic_cy + 10), (mic_cx, mic_cy + 20)], fill=(255, 255, 255, 255), width=4)
            draw.line([(mic_cx - 10, mic_cy + 20), (mic_cx + 10, mic_cy + 20)], fill=(255, 255, 255, 255), width=4)

            # Chữ DRAMA nhỏ ở dưới
            draw.text((bx1 + int(23 * sc), by1 + int(109 * sc)), "DRAMA", font=f_mic_top, fill=(255, 255, 255, 255))

            # Tên viết tắt Kênh (Màu Đỏ tươi rực rỡ)
            draw.text((bx1 + blue_w + int(18 * sc), by1 + int(26 * sc)), tag_name, font=f_tag, fill=(215, 15, 20, 255))

        # =====================================================================
        # GÓC PHẢI TRÊN: Dải Ruy Băng Chéo Góc Đỏ Chữ Trắng 'NEW'
        # (Cắt chéo góc chuẩn xác từ cạnh trên sang cạnh phải, chữ NEW xoay -45 độ)
        # =====================================================================
        ribbon_w = int(240 * sc)
        ribbon_h = int(240 * sc)
        ribbon_canvas = Image.new("RGBA", (ribbon_w, ribbon_h), (0, 0, 0, 0))
        r_draw = ImageDraw.Draw(ribbon_canvas)

        p_band = [(int(40 * sc), 0), (int(180 * sc), 0), (ribbon_w, int(60 * sc)), (ribbon_w, int(200 * sc))]
        r_draw.polygon(p_band, fill=(225, 20, 25, 255))
        r_draw.line([(int(40 * sc), 0), (ribbon_w, int(200 * sc))], fill=(255, 255, 255, 240), width=int(3 * sc))
        r_draw.line([(int(180 * sc), 0), (ribbon_w, int(60 * sc))], fill=(255, 255, 255, 240), width=int(3 * sc))

        f_new = cls._get_font("arialbd.ttf", int(46 * sc))
        txt_w, txt_h = int(140 * sc), int(50 * sc)
        txt_img = Image.new("RGBA", (txt_w, txt_h), (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_img)
        bbox_new = dummy_d.textbbox((0, 0), "NEW", font=f_new)
        bw_n = bbox_new[2] - bbox_new[0]
        bh_n = bbox_new[3] - bbox_new[1]
        t_draw.text(((txt_w - bw_n) // 2, (txt_h - bh_n) // 2 - bbox_new[1]), "NEW", font=f_new, fill=(255, 255, 255, 255), stroke_width=int(2 * sc), stroke_fill=(0, 0, 0, 200))

        rot_txt = txt_img.rotate(-45, resample=Image.Resampling.BICUBIC, expand=True)
        rw, rh = rot_txt.size
        ribbon_canvas.paste(rot_txt, (int(175 * sc) - rw // 2, int(65 * sc) - rh // 2), rot_txt)
        overlay.paste(ribbon_canvas, (cls.WIDTH - ribbon_w, 0), ribbon_canvas)

        final_img = Image.alpha_composite(base, overlay).convert("RGB")
        final_img.save(str(out_file), "JPEG", quality=95, optimize=True)
        return out_file

