from __future__ import annotations

import base64
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests
from PIL import Image


def clean_story_title(title: str) -> str:
    """Loại bỏ tiền tố số tập, dấu gạch dưới, khoảng trắng thừa để lấy tên truyện chuẩn."""
    if not title:
        return "Truyện Audio Hay"
    # Bỏ tiền tố P1, Tập 1, v.v. ở đầu nếu có
    t = re.sub(
        r"^(p\d+[a-zA-Z]?|tập\s*\d+|phần\s*\d+|chương\s*\d+)[\s:\-_]+",
        "",
        title,
        flags=re.IGNORECASE
    ).strip()
    t = t.replace("_", ", ")
    t = re.sub(r"\s+", " ", t).strip()
    return t.title() if t.isupper() or t.islower() else t


def clean_episode_badge(ep: str, fallback_idx: Optional[int] = None) -> str:
    """Nhận diện huy hiệu tập ngắn gọn (dạng P1, P2, Tập 1...).
    Hỗ trợ cả có dấu và không dấu (tập/tap, phần/phan, chương/chuong, p, ep).
    Nếu quét tiêu đề file không tìm thấy số tập hợp lệ thì trả về chuỗi rỗng "" (không tự ý gán số tập).
    """
    if not ep:
        return f"P{fallback_idx}" if fallback_idx is not None else ""

    # Chuẩn hóa khoảng trắng và gạch ngang/gạch dưới để dễ nhận diện
    normalized = re.sub(r"[_\-]+", " ", ep).strip()

    # Tìm các mẫu số tập hợp lệ rõ ràng: P1, P10, Tập 1, Tap 1, Phần 2, Phan 2, Ep 3, Chương 5... (1 đến 4 chữ số)
    m = re.search(
        r"(?:^|[\s\[\(_\-])(?:p\s*(\d{1,4}[a-zA-Z]?)|(?:tập|tap)\s*(\d{1,4}[a-zA-Z]?)|(?:phần|phan)\s*(\d{1,4}[a-zA-Z]?)|(?:chương|chuong)\s*(\d{1,4}[a-zA-Z]?)|(?:ep|episode)\s*(\d{1,4}[a-zA-Z]?))(?:$|[\s\]\)_:\-])",
        normalized,
        re.IGNORECASE
    )
    if m:
        for num in m.groups():
            if num:
                return f"P{num.upper().strip()}"

    # Kiểm tra dạng ngoặc hoặc ký hiệu bao bọc: [P1], (P1), _P1_, - P1 -
    m_bracket = re.search(r"[\[\(_\-\s](?:p|ep|tập|tap|phần|phan)\s*(\d{1,4}[a-zA-Z]?)[\]\)_\-\s]", ep, re.IGNORECASE)
    if m_bracket:
        return f"P{m_bracket.group(1).upper().strip()}"

    # Nếu không tìm thấy mẫu tập rõ ràng, KHÔNG tự tiện lấy chuỗi số ngẫu nhiên (tránh bắt nhầm mã ID 19 số của TikTok/Douyin)
    if fallback_idx is not None:
        return f"P{fallback_idx}"
    return ""


def extract_clean_video_title(filename_or_stem: str) -> str:
    """Làm sạch tên file video thành tiêu đề video đẹp:
    - Bỏ phần mở rộng (.mp4, .mkv...)
    - Bỏ mã số ID video dài (>=7 chữ số) ở đầu (ví dụ 19 số TikTok/Douyin: 7672309670169562394_)
    - Bỏ các hậu tố kỹ thuật (_vi_xuly, _xuly, _output, _hd, _merged, _converted...)
    - Bỏ tiền tố/hậu tố số tập nếu có (đã có badge riêng) để tránh trùng lặp
    - Chuyển dấu gạch dưới thành khoảng trắng
    """
    stem = Path(filename_or_stem).stem
    # Bỏ mã ID dạng số dài (>=7 số) ở đầu: ví dụ 7672309670169562394_
    t = re.sub(r"^\d{7,}[_\-\s]+", "", stem)
    # Bỏ hậu tố kỹ thuật ở đuôi
    t = re.sub(r"([_\-\s]+(vi_xuly|xuly|output|final|converted|render|1080p|720p|hd|sub))+$", "", t, flags=re.IGNORECASE)
    # Bỏ tiền tố số tập ở đầu nếu có (đã có badge riêng)
    t = re.sub(r"^(?:p\d{1,4}[a-zA-Z]?|(?:tập|tap)\s*\d{1,4}[a-zA-Z]?|(?:phần|phan)\s*\d{1,4}[a-zA-Z]?)[\s:\-_]+", "", t, flags=re.IGNORECASE).strip()
    # Bỏ số tập ở đuôi nếu có (ví dụ _Tap_3, - Tập 3, _P3)
    t = re.sub(r"[\s:\-_]+(?:p\s*\d{1,4}[a-zA-Z]?|(?:tập|tap)\s*\d{1,4}[a-zA-Z]?|(?:phần|phan)\s*\d{1,4}[a-zA-Z]?)$", "", t, flags=re.IGNORECASE).strip()
    t = t.replace("_", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def to_ascii_tag(text: str) -> str:
    """Tạo hashtag không dấu viết liền từ tên tiếng Việt."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = "".join([c for c in nfkd if not unicodedata.combining(c)])
    clean = re.sub(r"[^a-zA-Z0-9]", "", ascii_text.lower())
    return clean[:20] if clean else "truyenaudio"


def trim_chunk(text: str, max_words: int = 5) -> str:
    """Cắt tỉa cụm từ chuẩn ngữ nghĩa, bỏ từ nối dư thừa và bảo vệ ranh giới từ ghép tiếng Việt."""
    compound_words = [
        "dưa hấu", "bạn gái", "bạn trai", "thần thụ", "kỷ nguyên", "kỉ nguyên", "hoàng gia",
        "chiến thần", "ma đế", "tiêu sư", "quy củ", "phấn trắng", "hạt dưa",
        "thiên hạ", "cổ trang", "cung đình", "hoàng cung", "tình yêu",
        "cuộc chiến", "thần bí", "vô địch", "huyết chiến", "đại náo",
        "đan điền", "căn cơ", "vô thượng", "trọng sinh", "xuyên không",
        "biến dị", "tiến hóa", "hóa thần", "ma thụ", "đại thụ"
    ]
    t = re.sub(r"^(?:để|và|là|của|cho|do|khi|nếu)\s+", "", text.strip(), flags=re.IGNORECASE)
    t = re.sub(r"\s+(?:để|và|là|của|cho|do|khi|nếu)$", "", t.strip(), flags=re.IGNORECASE)
    words = [w for w in re.sub(r"[^\w\sÀ-ỹà-ỹĐđ]", " ", t).split() if w]
    if len(words) <= max_words:
        return " ".join(words).upper()
    target_len = max_words
    if target_len < len(words):
        pair = f"{words[target_len-1]} {words[target_len]}".lower()
        if pair in compound_words and target_len + 1 <= max_words + 1:
            target_len += 1
    return " ".join(words[:target_len]).upper()


def semantic_chunk_title(title: str) -> List[str]:
    """Phân tích tiêu đề thành các cụm từ ngữ pháp tiếng Việt có nghĩa logic hoàn chỉnh:
    - Nhận diện các từ ghép tiếng Việt phổ biến không thể cắt đôi (như 'dưa hấu', 'bạn gái', 'thần thụ'...)
    - Phân chia thành 2 cụm ngữ nghĩa logic (Chủ ngữ / Biến cố - Cao trào) thay vì đếm từ mù quáng.
    """
    if not title:
        return ["TIÊU ĐỀ NỔI BẬT"]

    # 1. Bỏ phần kênh sau dấu gạch đứng | hoặc hậu tố thể loại
    t = title.split("|")[0].strip()
    # Bỏ tiền tố số tập ở đầu (P1:, Tập 1:, Phần 1:)
    t = re.sub(r"^(?:p\d{1,4}[a-zA-Z]?|(?:tập|tap)\s*\d{1,4}[a-zA-Z]?|(?:phần|phan)\s*\d{1,4}[a-zA-Z]?)[\s:\-_]+", "", t, flags=re.IGNORECASE).strip()

    # Tách nếu có dấu gạch ngang, hai chấm rõ ràng
    dash_parts = [p.strip() for p in re.split(r"[-–—:]", t) if p.strip()]
    stopwords = ["truyen audio", "truyện audio", "kiem hiep", "kiếm hiệp", "tien hiep", "tiên hiệp", "full", "audio", "nghe truyen", "nghe truyện", "sinh tồn hay", "truyện viễn tưởng", "viễn tưởng"]
    dash_filtered = [p for p in dash_parts if not any(sw in p.lower() for sw in stopwords)]

    if len(dash_filtered) >= 2:
        c1 = trim_chunk(dash_filtered[0], 6)
        c2 = trim_chunk(dash_filtered[1], 12)
        return [c1, c2]

    # Danh sách từ nối/động từ chuyển tiếp thường là ranh giới cụm từ logic trong tiếng Việt
    break_words = [
        r"\bbỗng hóa thành\b", r"\bbỗng biến thành\b", r"\bbiến dị thành\b", r"\bbiến thành\b",
        r"\btrở thành\b", r"\bhóa thành\b", r"\bnhổ ra\b", r"\brơi vào\b",
        r"\bđể đúc\b", r"\bquyết định\b", r"\bđại chiến\b", r"\bkhiến cho\b",
        r"\blại là\b", r"\bnhưng là\b", r"\bvà\b"
    ]

    for pat in break_words:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            p1 = t[:m.start()].strip()
            p2 = t[m.start():].strip()
            # Bỏ từ nối phụ ở đầu p2 (như "nhổ ra", "rơi vào", "để đúc", "bỗng")
            p2_clean = re.sub(r"^(?:nhổ ra|rơi vào|để đúc|bỗng|để)\s+", "", p2, flags=re.IGNORECASE).strip()
            c1 = trim_chunk(p1, 5)
            c2 = trim_chunk(p2_clean or p2, 5)
            if c1 and c2:
                return [c1, c2]

    compound_words = [
        "dưa hấu", "bạn gái", "bạn trai", "thần thụ", "kỷ nguyên", "kỉ nguyên", "hoàng gia",
        "chiến thần", "ma đế", "tiêu sư", "quy củ", "phấn trắng", "hạt dưa",
        "thiên hạ", "cổ trang", "cung đình", "hoàng cung", "tình yêu",
        "cuộc chiến", "thần bí", "vô địch", "huyết chiến", "đại náo"
    ]

    clean_t = re.sub(r"[^\w\sÀ-ỹà-ỹĐđ]", " ", t)
    words = [w for w in clean_t.split() if w]
    if len(words) <= 5:
        return [" ".join(words).upper()]

    # Tìm điểm chia tự nhiên nhất quanh giữa
    mid = len(words) // 2
    pair = f"{words[mid-1]} {words[mid]}".lower()
    if pair in compound_words and mid + 1 < len(words):
        mid += 1

    p1 = " ".join(words[:mid])
    p2 = " ".join(words[mid:])
    return [trim_chunk(p1, 5), trim_chunk(p2, 5)]


def extract_highlight_from_title(title: str) -> str:
    """Phân tích tiêu đề video và trích xuất các cụm từ cốt lõi/nổi bật nhất (in hoa, nối bằng dấu ' - ')."""
    if not title:
        return "TIÊU ĐỀ NỔI BẬT"

    chunks = semantic_chunk_title(title)
    if len(chunks) >= 2:
        return f"{chunks[0]} - {chunks[1]}"
    elif chunks:
        return chunks[0]

    return "TIÊU ĐỀ NỔI BẬT"


SUPPORTED_LANGUAGES: Dict[str, Dict[str, str]] = {
    "vi": {
        "name": "Tiếng Việt",
        "english_name": "Vietnamese",
        "culture": "Vietnam YouTube drama / truyện audio tình cảm tâm lý xã hội",
    },
    "tl": {
        "name": "Tiếng Tagalog / Philippines",
        "english_name": "Tagalog / Filipino",
        "culture": "Philippines TV drama, radio stories, heart-wrenching emotional family romance (e.g. May Pangako Ang Bukas, TMT Radio Stories)",
    },
    "en": {
        "name": "Tiếng Anh (English)",
        "english_name": "English",
        "culture": "Global YouTube viral drama / audio storytelling format",
    },
    "th": {
        "name": "Tiếng Thái (Thai)",
        "english_name": "Thai",
        "culture": "Thailand Lakorn emotional drama / romance audio series",
    },
    "id": {
        "name": "Tiếng Indonesia (Bahasa)",
        "english_name": "Indonesian / Bahasa",
        "culture": "Indonesian sinetron / kisah drama audio",
    },
    "es": {
        "name": "Tiếng Tây Ban Nha (Español)",
        "english_name": "Spanish",
        "culture": "Spanish telenovela / radionovela drama series",
    },
    "pt": {
        "name": "Tiếng Bồ Đào Nha (Português)",
        "english_name": "Portuguese",
        "culture": "Portuguese / Brazilian telenovela drama series",
    },
    "ja": {
        "name": "Tiếng Nhật (Japanese)",
        "english_name": "Japanese",
        "culture": "Japanese voice drama / audio novel",
    },
    "ko": {
        "name": "Tiếng Hàn (Korean)",
        "english_name": "Korean",
        "culture": "K-Drama emotional romance web drama",
    },
    "zh": {
        "name": "Tiếng Trung (Chinese)",
        "english_name": "Chinese",
        "culture": "Chinese audio drama / short drama series",
    },
}


class OfflineSEOAssistant:
    """Bộ tạo nội dung & tiêu đề truyện audio chuẩn SEO YouTube hoàn toàn MIỄN PHÍ & OFFLINE."""

    # Kho phụ đề kịch tính phong phú cho các tập truyện audio
    EPISODE_HOOKS = [
        "Xuất Sơn Lập Uy - Giang Hồ Dậy Sóng",
        "Quy Củ Bất Diệt - Một Kiếm Trảm Cường Địch",
        "Thân Phận Thần Bí - Tuyệt Kỹ Vô Song",
        "Huyết Chiến Hắc Phong - Báo Thù Rửa Hận",
        "Phá Bỏ Định Mệnh - Đột Phá Cảnh Giới",
        "Ma Đạo Chặn Đường - Cửu Tử Nhất Sinh",
        "Nhất Kiếm Định Càn Khôn - Trấn Áp Tứ Phương",
        "Bí Mật Áp Tiêu - Âm Mưu Thâm Độc",
        "Nộ Hỏa Xung Thiên - Huyết Nhiễm Sơn Hà",
        "Vô Địch Thiên Hạ - Khí Phách Hiên Ngang",
        "Đại Náo Tông Môn - Cắt Đứt Ân Oán",
        "Thiết Huyết Đan Tâm - Tuyệt Không Khoan Nhượng",
        "Long Tranh Hổ Đấu - Phong Vân Biến Sắc",
        "Thần Binh Xuất Thế - Trấn Cổ Thước Kim",
        "Tàn Nhẫn Vô Tình - Kẻ Thù Khiếp Sợ",
        "Cường Địch Vây Khốn - Nghịch Chuyển Càn Khôn",
        "Bí Cảnh Hiểm Nguy - Thần Ma Thoái Nhượng",
        "Thiên Địa Bất Nhân - Một Mình Nghịch Mệnh",
        "Khai Sơn Phá Thạch - Uy Chấn Bát Hoang",
        "Trận Chiến Quyết Định - Danh Chấn Thiên Hạ",
    ]

    TAGALOG_HOOKS = [
        "Nang Dahil Sa Pag-ibig",
        "Nang Dahil Sa Mana Nagkawatak-watak Ang Pamilya",
        "Ang Lihim Ng Nakaraan",
        "Bakas Ng Kahapon",
        "Luha At Sakripisyo",
        "May Pangako Ang Bukas",
        "Huling Hiling Ng Puso",
        "Hapdi Ng Katotohanan",
    ]

    ENGLISH_HOOKS = [
        "A Broken Promise",
        "Love and Betrayal",
        "The Pain of Goodbyes",
        "Family Secrets Revealed",
        "Tears in the Rain",
        "Unforgiven Sins",
        "The Ultimate Sacrifice",
    ]

    HIGHLIGHT_HOOKS = [
        "QUY CỦ THIÊN HẠ!",
        "XUẤT SƠN ĐOẠT TIÊU!",
        "TÀN NHẪN NHẤT!",
        "HUYẾT CHIẾN GIANG HỒ!",
        "NHẤT KIẾM ĐỊNH THIÊN!",
        "KHÍ PHÁCH HIÊN NGANG!",
        "BÁO THÙ RỬA HẬN!",
        "VÔ ĐỊCH THIÊN HẠ!",
        "TRẤN ÁP TỨ PHƯƠNG!",
        "ĐỘT PHÁ CẢNH GIỚI!",
    ]

    @classmethod
    def generate_video_metadata(
        cls,
        story_title: str,
        episode_name: str = "",
        extra_info: str = "",
        channel_name: str = "",
        episode_index: Optional[int] = None,
        target_language: str = "vi",
    ) -> Dict[str, Any]:
        clean_title = clean_story_title(story_title)
        badge = clean_episode_badge(episode_name, episode_index) if episode_name else ""
        clean_channel = re.sub(r"\(.*?\)", "", channel_name or "").strip()
        ch_name = clean_channel or "Truyện Audio"

        hooks_pool = cls.EPISODE_HOOKS
        if target_language == "tl":
            hooks_pool = cls.TAGALOG_HOOKS
        elif target_language == "en":
            hooks_pool = cls.ENGLISH_HOOKS

        # Lấy hook theo index để từng tập có phụ đề khác nhau
        if episode_index is not None and episode_index > 0:
            hook_idx = (episode_index - 1) % len(hooks_pool)
        else:
            seed = abs(hash(clean_title))
            hook_idx = seed % len(hooks_pool)

        hook = hooks_pool[hook_idx]

        # Tiêu đề chuẩn SEO YouTube (< 100 ký tự)
        if badge:
            candidate_title = f"{badge}: {clean_title} - {hook} | {ch_name}"
        else:
            candidate_title = f"{clean_title} - {hook} | {ch_name}"

        if len(candidate_title) > 98:
            candidate_title = f"{badge}: {clean_title} | {ch_name}" if badge else f"{clean_title} | {ch_name}"
            if len(candidate_title) > 98:
                candidate_title = candidate_title[:95] + "..."

        # Trích xuất chữ to nổi bật trực tiếp từ tiêu đề vừa tạo
        hl_text = extract_highlight_from_title(candidate_title)

        # Hashtags
        tag_story = to_ascii_tag(clean_title)
        tag_ch = to_ascii_tag(ch_name)
        tag_badge = to_ascii_tag(badge) if badge else ""

        badge_header = f" ({badge})" if badge else ""
        badge_summary = f" {badge}" if badge else ""
        badge_hashtag = f" #{tag_badge}" if tag_badge else ""

        # Mô tả chuyên nghiệp chuẩn YouTube
        description = f"""🎧 Chào mừng quý thính giả đến với kênh {ch_name}!
📖 Mời các bạn cùng lắng nghe tác phẩm đặc sắc:
⚔ {clean_title}{badge_header}

🔥 Tóm tắt nội dung{badge_summary}:
Hành trình kịch tính và đầy lôi cuốn của nhân vật chính giữa muôn trùng hiểm nguy và những biến cố khó lường. Cùng theo dõi những tình tiết bất ngờ, những nút thắt nghẹt thở!

🎙 Diễn đọc: AI Story Audio
📻 Chất lượng âm thanh: Âm thanh vòm Stereo chất lượng cao
⏰ Lịch phát sóng: Phát định kỳ hàng ngày trên kênh {ch_name}

🔔 Hãy bấm ĐĂNG KÝ KÊNH (Subscribe) và BẬT CHUÔNG 🔔 để đón xem các nội dung tiếp theo sớm nhất!
👍 Đừng quên LIKE & BÌNH LUẬN cảm xúc của bạn dưới video để ủng hộ kênh nhé!

© Bản quyền nội dung và âm thanh thuộc về {ch_name}.
Vui lòng không sao chép hoặc reup dưới mọi hình thức để tôn trọng bản quyền tác giả.

#truyenaudio #kiemhiep #tienhiep #{tag_story} #{tag_ch}{badge_hashtag} #audiodoctruyen
"""

        # Tags chuẩn SEO
        tags_list = [
            clean_title.lower(),
            "truyen audio",
            "kiem hiep",
            "tien hiep",
            "truyen audio hay",
            "truyen audio moi nhat",
            ch_name.lower(),
            "audio truyen",
            "doc truyen online",
            "truyen audio trinh tham",
        ]
        if badge:
            tags_list.append(badge.lower())
            tags_list.append(f"{clean_title.lower()} {badge.lower()}")
        tags = ", ".join(tags_list)

        return {
            "title": candidate_title,
            "description": description.strip(),
            "tags": tags,
            "thumbnail_badge": badge,
            "thumbnail_highlight": hl_text,
            "thumbnail_ai_prompt": f"Dramatic fantasy anime wallpaper, martial arts warrior with glowing aura, epic cinematic background, 8k resolution, photorealistic",
            "provider_used": "offline_smart_seo"
        }


class GeminiAssistant:
    """Trợ lý AI tạo Tiêu đề, Mô tả, Tags chuẩn YouTube dùng Google Gemini API."""

    CANDIDATE_MODELS = [
        "gemini-2.5-flash",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        self.api_key = (api_key or "").strip()
        self.model = model or "gemini-2.5-flash"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _call_gemini(self, prompt: str) -> str:
        if not self.api_key:
            raise ValueError("Chưa nhập Gemini API Key!")

        # Kiểm tra nếu key bắt đầu bằng AQ. (token Google Cloud, không phải AI Studio API key)
        if self.api_key.startswith("AQ."):
            raise ValueError(
                "Key bạn nhập có dạng 'AQ....' (đây là Token Google Cloud, không phải Gemini API Key của AI Studio).\n"
                "Key chuẩn của Google AI Studio miễn phí bắt đầu bằng 'AIzaSy...'.\n"
                "Vui lòng nhấn nút '🌐 Lấy Key Free' hoặc chọn chế độ '⚡ Mẫu Tự Động Chuẩn SEO' để dùng miễn phí không cần key!"
            )

        models_to_try = [self.model]
        for m in self.CANDIDATE_MODELS:
            if m not in models_to_try:
                models_to_try.append(m)

        last_error = ""
        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "topP": 0.95,
                "topK": 40,
                "maxOutputTokens": 1200,
                "responseMimeType": "application/json",
            }
        }

        for mod in models_to_try:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={self.api_key}"
            try:
                resp = requests.post(endpoint, json=payload, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts:
                            return parts[0].get("text", "")
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text}"
            except Exception as ex:
                last_error = str(ex)

        raise RuntimeError(f"Tất cả model Gemini đều thất bại. Chi tiết: {last_error}")

    def generate_video_metadata(
        self,
        story_title: str,
        episode_name: str = "",
        extra_info: str = "",
        channel_name: str = "",
        episode_index: Optional[int] = None,
        target_language: str = "vi",
    ) -> Dict[str, Any]:
        """Tạo trọn bộ Metadata: Tiêu đề giật tít SEO, Mô tả đầy đủ, Tags và text Thumbnail."""
        lang_info = SUPPORTED_LANGUAGES.get(target_language, SUPPORTED_LANGUAGES["vi"])
        lang_name = lang_info["english_name"]
        lang_culture = lang_info["culture"]
        clean_channel = re.sub(r"\(.*?\)", "", channel_name or "").strip()
        ch_name = clean_channel or "Truyện Audio"
        ep_info = episode_name if episode_name else "Video đơn lẻ / Không có số tập (KHÔNG thêm tiền tố tập hay P... vào tiêu đề)"
        title_eg = f'"{episode_name}: Tự Phế Đan Điền Để Đúc Căn Cơ Vô Thượng | {ch_name}"' if episode_name else f'"Tự Phế Đan Điền Để Đúc Căn Cơ Vô Thượng | {ch_name}"'
        prompt = f"""
Bạn là chuyên gia tối ưu hóa nội dung YouTube (SEO YouTube Master) cho các kênh video, phim drama & truyện audio, chuyên sâu về thị trường: {lang_culture}.
NGÔN NGỮ ĐÍCH BẮT BUỘC: {lang_name} ({target_language}).
Nếu tiêu đề hoặc nội dung gốc là tiếng Việt hoặc ngôn ngữ khác, BẠN BẮT BUỘC DỊCH VÀ BIẾN ĐỔI SÁNG TẠO nội dung sang {lang_name} theo đúng phong cách tiêu đề & mô tả thịnh hành của YouTube tại quốc gia đó!

- Tên truyện / Chủ đề gốc: {story_title}
- Tập hoặc Chương: {ep_info}
- Thông tin thêm: {extra_info}
- Tên kênh: {ch_name}
- Ngôn ngữ đích: {lang_name}

Yêu cầu nghiêm ngặt:
1. "title": Tiêu đề hoàn toàn bằng {lang_name} cực kỳ cuốn hút, giật tít drama gây tò mò, chuẩn SEO nhưng TUYỆT ĐỐI KHÔNG vượt quá 95 ký tự. (Ví dụ nếu Tagalog: "May Pangako Ang Bukas - Nang Dahil Sa Mana | {ch_name}").
2. "description": Mô tả video chuyên nghiệp hoàn toàn bằng {lang_name} gồm:
   - Đoạn tóm tắt mở đầu 3-4 câu kịch tính, lôi cuốn người nghe bằng {lang_name}.
   - Danh sách lưu ý nghe truyện, lịch phát sóng.
   - Lời kêu gọi Like, Subscribe ủng hộ kênh.
   - Tuyên bố bản quyền & miễn trừ trách nhiệm (Disclaimer).
   - 5 đến 8 Hashtag liên quan chuẩn xu hướng bằng {lang_name}.
3. "tags": Danh sách 15-20 từ khóa tìm kiếm (tags) bằng {lang_name} chuẩn SEO liên quan nhất, cách nhau bằng dấu phẩy. Tổng độ dài dưới 450 ký tự.
4. "thumbnail_badge": Chữ số tập ngắn gọn bằng {lang_name} (nếu không có số tập thì để chuỗi rỗng "").
5. "thumbnail_highlight": Phân tích trực tiếp từ chính tiêu đề ("title") vừa tạo ở trên, chia thành 2 cụm từ nổi bật nhất bằng {lang_name} (cách nhau bởi dấu gạch ngang " - ", ALL CAPS) để in to rõ ràng lên 2 bên Thumbnail (Ví dụ: 'MAY PANGAKO ANG BUKAS - NANG DAHIL SA MANA').
6. "thumbnail_ai_prompt": Một prompt chi tiết bằng tiếng Anh (dài 40-60 từ) siêu thực (cinematic photorealistic, 8k, dramatic lighting) mô tả bối cảnh và nhân vật drama phù hợp {lang_culture}.

BẮT BUỘC TRẢ VỀ DƯỚI ĐỊNH DẠNG JSON DUY NHẤT:
{{
  "title": "...",
  "description": "...",
  "tags": "tag1, tag2, tag3, ...",
  "thumbnail_badge": "{episode_name}",
  "thumbnail_highlight": "CỤM 1 - CỤM 2",
  "thumbnail_ai_prompt": "..."
}}
"""
        try:
            raw = self._call_gemini(prompt)
            cleaned = raw.strip()
            if "`json" in cleaned:
                cleaned = cleaned.split("`json", 1)[1].split("`", 1)[0].strip()
            elif "`" in cleaned:
                cleaned = cleaned.split("`", 1)[1].split("`", 1)[0].strip()

            res = json.loads(cleaned)
            if not episode_name:
                res["thumbnail_badge"] = ""
                res["title"] = re.sub(r"^(?:p\d{1,4}[a-zA-Z]?|tập\s*\d{1,4}[a-zA-Z]?|phần\s*\d{1,4}[a-zA-Z]?)[\s:\-_]+", "", res.get("title", ""), flags=re.IGNORECASE).strip()
            if len(res.get("title", "")) > 100:
                res["title"] = res["title"][:97] + "..."
            hl = res.get("thumbnail_highlight", "").strip().upper()
            if not hl or " - " not in hl:
                hl = extract_highlight_from_title(res.get("title", ""))
            res["thumbnail_highlight"] = hl
            res["provider_used"] = "gemini_api"
            return res
        except Exception as e:
            # Tự động chuyển đổi sang Offline Smart SEO để không bao giờ làm gián đoạn người dùng!
            fallback = OfflineSEOAssistant.generate_video_metadata(
                story_title=story_title,
                episode_name=episode_name,
                extra_info=extra_info,
                channel_name=channel_name,
                episode_index=episode_index,
                target_language=target_language,
            )
            fallback["warning"] = f"Lỗi Gemini ({e}). Đã tự động sinh bằng Mẫu Chuẩn SEO Truyện Miễn Phí!"
            return fallback


class CustomAIAssistant:
    """Hỗ trợ OpenAI-compatible API (Groq, OpenRouter, DeepSeek, 9Router, v.v.)."""

    def __init__(self, api_key: str, base_url: str = "https://api.groq.com/openai/v1", model: str = "llama-3.3-70b-versatile") -> None:
        self.api_key = api_key.strip()
        self.base_url = (base_url or "https://api.groq.com/openai/v1").rstrip("/")
        self.model = model or "llama-3.3-70b-versatile"

    def generate_video_metadata(
        self,
        story_title: str,
        episode_name: str = "",
        extra_info: str = "",
        channel_name: str = "",
        episode_index: Optional[int] = None,
        target_language: str = "vi",
    ) -> Dict[str, Any]:
        lang_info = SUPPORTED_LANGUAGES.get(target_language, SUPPORTED_LANGUAGES["vi"])
        lang_name = lang_info["english_name"]
        lang_culture = lang_info["culture"]
        clean_channel = re.sub(r"\(.*?\)", "", channel_name or "").strip()
        ch_name = clean_channel or "Truyện Audio"
        ep_info = episode_name if episode_name else "Video đơn lẻ / Không có số tập (KHÔNG thêm tiền tố tập hay P... vào tiêu đề)"

        prompt = f"""Bạn là chuyên gia SEO YouTube truyện audio & video drama thị trường: {lang_culture}.
NGÔN NGỮ ĐÍCH BẮT BUỘC: {lang_name} ({target_language}).
Nếu tiêu đề hoặc nội dung gốc là tiếng Việt hoặc ngôn ngữ khác, BẠN BẮT BUỘC DỊCH VÀ BIẾN ĐỔI SÁNG TẠO nội dung sang {lang_name} theo phong cách tiêu đề & mô tả thịnh hành của YouTube tại quốc gia đó!

- Tên truyện gốc: {story_title}
- Tập: {ep_info}
- Kênh: {ch_name}
- Ngôn ngữ đích: {lang_name}

Yêu cầu đặc biệt: "thumbnail_highlight" BẮT BUỘC phân tích trực tiếp từ chính "title" vừa tạo, chia thành 2 cụm từ nổi bật nhất bằng {lang_name} (cách nhau bởi dấu gạch ngang " - ", ALL CAPS) để in to rõ lên 2 bên Thumbnail (Ví dụ: 'MAY PANGAKO ANG BUKAS - NANG DAHIL SA MANA').

Trả về JSON duy nhất:
{{
  "title": "<tiêu đề dưới 95 ký tự bằng {lang_name}>",
  "description": "<mô tả video đầy đủ bằng {lang_name} kèm hashtag>",
  "tags": "<15 từ khóa bằng {lang_name} cách nhau bằng dấu phẩy>",
  "thumbnail_badge": "{episode_name}",
  "thumbnail_highlight": "<cụm 1 - cụm 2 in hoa bằng {lang_name}>",
  "thumbnail_ai_prompt": "<prompt tiếng Anh siêu thực cinematic 8k>"
}}"""
        url = f"{self.base_url}/chat/completions" if self.base_url.endswith("/v1") else f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "stream": False,
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=35)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                # Trích xuất khối JSON chuẩn xác
                m = re.search(r"\{.*\}", content, re.DOTALL)
                if m:
                    content = m.group(0)
                res = json.loads(content)
                if not episode_name:
                    res["thumbnail_badge"] = ""
                    res["title"] = re.sub(r"^(?:p\d{1,4}[a-zA-Z]?|tập\s*\d{1,4}[a-zA-Z]?|phần\s*\d{1,4}[a-zA-Z]?)[\s:\-_]+", "", res.get("title", ""), flags=re.IGNORECASE).strip()
                hl = res.get("thumbnail_highlight", "").strip().upper()
                if not hl or " - " not in hl:
                    hl = extract_highlight_from_title(res.get("title", ""))
                res["thumbnail_highlight"] = hl
                res["provider_used"] = f"custom_ai ({self.model})"
                return res
        except Exception:
            pass

        return OfflineSEOAssistant.generate_video_metadata(
            story_title=story_title,
            episode_name=episode_name,
            extra_info=extra_info,
            channel_name=channel_name,
            episode_index=episode_index,
            target_language=target_language,
        )


def detect_9router_api_key() -> str:
    """Tự động đọc API Key sẵn có từ cơ sở dữ liệu 9Router cục bộ (chế độ read-only, không lo lock)."""
    try:
        db_path = Path.home() / "AppData/Roaming/9router/db/data.sqlite"
        if db_path.exists():
            import sqlite3
            uri = f"file:{db_path.as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=1.0) as conn:
                cur = conn.cursor()
                cur.execute("SELECT key FROM apiKeys ORDER BY rowid DESC LIMIT 1;")
                r = cur.fetchone()
                if r and r[0]:
                    return r[0]
    except Exception:
        pass
    return ""


class ThumbnailPromptGenerator:
    """Bộ chuyển đổi Tiêu đề, Mô tả và phân tích 1-3 ảnh mẫu (Vision AI) thành Prompt tiếng Anh chân thực cho Thumbnail."""

    @classmethod
    def generate_prompt(
        cls,
        title: str,
        description: str = "",
        sample_images: Optional[List[Path | str]] = None,
        channel_name: str = "",
        provider: str = "9router",
        api_key: str = "",
        model: str = "",
        custom_base_url: str = "",
        target_language: str = "vi",
        **kwargs: Any,
    ) -> str:
        clean_title = (title or "").strip()
        clean_desc = (description or "").strip()[:500]

        # Chuẩn bị ảnh mẫu (tối đa 3 ảnh)
        valid_images: List[Path] = []
        if sample_images:
            for p in sample_images[:3]:
                path_obj = Path(p)
                if path_obj.exists() and path_obj.is_file():
                    valid_images.append(path_obj)

        clean_ch = re.sub(r"\(.*?\)", "", channel_name or "").strip()
        channel_str = clean_ch or "Radio Drama"
        lang_info = SUPPORTED_LANGUAGES.get(target_language, SUPPORTED_LANGUAGES["vi"])
        lang_name = lang_info["english_name"]
        lang_culture = lang_info["culture"]

        hl_phrase = extract_highlight_from_title(clean_title) or clean_story_title(clean_title)

        # Trích xuất các cụm từ ngữ pháp logic có nghĩa từ tiêu đề
        chunks = semantic_chunk_title(clean_title)
        primary_text = chunks[0] if chunks else hl_phrase
        secondary_text = chunks[1] if len(chunks) > 1 else ""

        # Hệ thống chỉ dẫn Master Prompt chuẩn YouTube Viral Thumbnail:
        if target_language != "vi" or re.search(r"[À-ỹà-ỹĐđ]", channel_str):
            channel_badge_name = "TMTRD"
        else:
            channel_badge_name = channel_str or "Radio Drama"
        sec_text_spec = f'- Secondary headline below: "{secondary_text}" in bold yellow text with a heavy black outline and drop shadow.\n' if secondary_text else ""

        if valid_images:
            system_instruction = (
                "You are an elite AI art director and master prompt engineer for YouTube viral thumbnails.\n"
                f"TARGET AUDIENCE & CULTURE: {lang_name} ({lang_culture}).\n"
                "CRITICAL GOAL: The user provided reference sample image(s). You MUST analyze the sample image's visual composition and typography style.\n"
                "Format your response specifically in this exact, high-impact 3-part layout (do NOT use code blocks, output clean plain text only):\n\n"
                "Part 1: Scene & Characters\n"
                "Extreme right-weighted composition: Describe the emotional characters (weeping woman wiping tears with tissue, comforted by a somber man), facial grief, tear streaks, and lighting (moody cinematic domestic interior with rain-streaked windows) STRICTLY on the far right 35% of the frame, leaving the left 65% as empty negative space.\n\n"
                "Part 2: Typography Breakdown\n"
                f"Prominent, multi-layered 3D YouTube typography placed on the left side in {lang_name}:\n"
                f'- Top primary headline: "{primary_text}" in massive bold red letters with a thick white border and cyan outer glow.\n'
                + sec_text_spec +
                '- Bottom left text: Bold sans-serif "Full Episode" in crisp white with a thick black stroke.\n'
                f'- Bottom right corner: A rectangular broadcast badge labeled "{channel_badge_name}" alongside a vibrant red diagonal "NEW ARRIVAL" ribbon banner.\n\n'
                "Part 3: Technical Specs\n"
                "High-contrast TV drama aesthetic, ultra-sharp focus, rich color saturation, 16:9 aspect ratio."
            )
            user_text = (
                f"Video Title ({lang_name}): {clean_title}\n"
                f"Target Market: {lang_name}\n"
                f"Core Highlight Phrase: \"{hl_phrase}\"\n"
                f"Primary Text to Paint: \"{primary_text}\"\n"
                + (f"Secondary Text to Paint: \"{secondary_text}\"\n" if secondary_text else "")
                + (f"Channel Name: \"{channel_badge_name}\"\n")
                + f"Story Description: {clean_desc}\n\n"
                f"Attached are {len(valid_images)} sample image(s). Analyze their character composition, emotional drama, lighting, and typography style. Create the thumbnail prompt strictly following the 3-part structure above."
            )
        else:
            system_instruction = (
                "You are an elite AI art director and master prompt engineer for YouTube viral thumbnails.\n"
                f"TARGET AUDIENCE & CULTURE: {lang_name} ({lang_culture}).\n"
                "Generate a single, high-impact image generation prompt in ENGLISH specifically formatted for generating a viral 16:9 YouTube thumbnail.\n"
                "Format in 3 clean sections:\n"
                "1. Scene & Characters: Extreme right-side composition: Describe charismatic characters in emotional drama or intense action on the far right 35% of the frame, leaving the left 65% as empty negative space with cinematic lighting and rich depth of field.\n"
                f"2. Prominent, multi-layered 3D YouTube typography placed on the left side in {lang_name}:\n"
                f'- Top primary headline: "{primary_text}" in massive bold red letters with a thick white border and cyan outer glow.\n'
                + sec_text_spec +
                '- Bottom left text: Bold sans-serif "Full Episode" in crisp white with a thick black stroke.\n'
                f'- Bottom right corner: A broadcast badge labeled "{channel_badge_name}" alongside a vibrant red diagonal "NEW ARRIVAL" ribbon banner.\n'
                "3. High-contrast TV drama aesthetic, ultra-sharp focus, rich color saturation, 16:9 aspect ratio."
            )
            user_text = (
                f"Video Title ({lang_name}): {clean_title}\n"
                f"Target Market: {lang_name}\n"
                f"Core Highlight Phrase: \"{hl_phrase}\"\n"
                f"Primary Text: \"{primary_text}\"\n"
                + (f"Secondary Text: \"{secondary_text}\"\n" if secondary_text else "")
                + (f"Channel Name: \"{channel_badge_name}\"\n")
                + f"Story Description: {clean_desc}"
            )

        # 1. Gọi 9Router hoặc Custom OpenAI
        if provider in ["9router", "custom"]:
            if provider == "9router" and not api_key:
                api_key = detect_9router_api_key()

            if not api_key and provider == "custom":
                # Không có key thì fallback ngay
                pass
            else:
                base = (custom_base_url or ("http://localhost:20128/v1" if provider == "9router" else "https://api.groq.com/openai/v1")).rstrip("/")
                if not base.endswith("/v1"):
                    base += "/v1"
                url = f"{base}/chat/completions"
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

                content_parts: List[Dict[str, Any]] = [{"type": "text", "text": user_text}]
                for img_path in valid_images:
                    try:
                        with Image.open(img_path) as im:
                            im = im.convert("RGB")
                            im.thumbnail((1024, 1024))
                            import io
                            buf = io.BytesIO()
                            im.save(buf, format="JPEG", quality=85)
                            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                            content_parts.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                            })
                    except Exception:
                        pass

                user_payload: Any = content_parts if valid_images else user_text
                payload = {
                    "model": model or ("ag/gemini-3.8-flash-high" if provider == "9router" else "llama-3.3-70b-versatile"),
                    "messages": [
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": user_payload}
                    ],
                    "stream": False,
                    "temperature": 0.7,
                }
                try:
                    resp = requests.post(url, headers=headers, json=payload, timeout=18)
                    if resp.status_code == 200:
                        data = resp.json()
                        choices = data.get("choices", [])
                        if choices and "message" in choices[0]:
                            res_text = choices[0]["message"].get("content", "").strip()
                            if res_text:
                                return res_text.strip('"`')
                except Exception:
                    pass

        # 2. Gọi Google Gemini API
        elif provider == "gemini" and api_key:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model or 'gemini-2.5-flash'}:generateContent?key={api_key}"
            parts: List[Dict[str, Any]] = [{"text": f"{system_instruction}\n\n{user_text}"}]
            for img_path in valid_images:
                try:
                    with Image.open(img_path) as im:
                        im = im.convert("RGB")
                        im.thumbnail((1024, 1024))
                        import io
                        buf = io.BytesIO()
                        im.save(buf, format="JPEG", quality=85)
                        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                        parts.append({
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": b64
                            }
                        })
                except Exception:
                    pass

            payload = {"contents": [{"parts": parts}]}
            try:
                resp = requests.post(endpoint, json=payload, timeout=18)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        cparts = candidates[0]["content"].get("parts", [])
                        if cparts and "text" in cparts[0]:
                            res_text = cparts[0]["text"].strip()
                            if res_text:
                                return res_text.strip('"`')
            except Exception:
                pass

        # 3. Offline fallback chất lượng cao đúng chuẩn 3 phần
        return (
            f"Extreme right-weighted composition: A heart-wrenching emotional Asian couple strictly in the foreground on the far right 35% of the frame. "
            f"An emotional woman is weeping with visible tears wiping them with a tissue, while a somber man comforts her with his hand gently resting on her shoulder. "
            f"The left 65% of the frame is an empty domestic room interior with moody cinematic lighting and rain-streaked windows, wide negative space on the left.\n\n"
            f"Prominent, multi-layered 3D YouTube typography placed on the left side in {lang_name}:\n"
            f'- Top primary headline: "{primary_text}" in massive bold red letters with a thick white border and cyan outer glow.\n'
            + (f'- Secondary headline below: "{secondary_text}" in bold yellow text with a heavy black outline and drop shadow.\n' if secondary_text else "")
            + f'- Bottom left text: Bold sans-serif "Full Episode" in crisp white with a thick black stroke.\n'
            f'- Bottom right corner: A rectangular broadcast badge labeled "{channel_badge_name}" alongside a vibrant red diagonal "NEW ARRIVAL" ribbon banner.\n\n'
            f"High-contrast TV drama aesthetic, ultra-sharp focus, rich color saturation, 16:9 aspect ratio."
        )


