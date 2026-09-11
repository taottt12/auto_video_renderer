from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests


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
    - Bỏ mã số ID video dài (>=6 chữ số) ở BẤT KỲ ĐÂU (ví dụ 19 số TikTok/Douyin: 7672309670169562394)
    - Bỏ các hậu tố kỹ thuật (_vi_xuly, _xuly, _output, _hd, _merged, _converted...)
    - Bỏ tiền tố/hậu tố số tập nếu có (đã có badge riêng) để tránh trùng lặp
    - Chuyển dấu gạch dưới thành khoảng trắng
    - Dọn dẹp ký tự thừa ở đầu và cuối
    """
    stem = Path(filename_or_stem).stem
    # Bỏ các hậu tố kỹ thuật ở đuôi
    t = re.sub(r"([_\-\s]+(vi_xuly|xuly|output|final|converted|render|1080p|720p|4k|hd|sub|raw))+$", "", stem, flags=re.IGNORECASE)
    # Bỏ mã ID dạng số dài (>=6 chữ số) ở bất kỳ đâu trong tên
    t = re.sub(r"[_\-\s]*\b\d{6,}\b[_\-\s]*", " ", t)
    # Tiếp tục dọn các hậu tố kỹ thuật còn sót lại sau khi bỏ số
    t = re.sub(r"([_\-\s]+(vi_xuly|xuly|output|final|converted|render|1080p|720p|4k|hd|sub|raw))+$", "", t, flags=re.IGNORECASE)
    # Bỏ tiền tố số tập ở đầu nếu có (đã có badge riêng)
    t = re.sub(r"^(?:p\d{1,4}[a-zA-Z]?|(?:tập|tap)\s*\d{1,4}[a-zA-Z]?|(?:phần|phan)\s*\d{1,4}[a-zA-Z]?)[\s:\-_]+", "", t, flags=re.IGNORECASE).strip()
    # Bỏ số tập ở đuôi nếu có (ví dụ _Tap_3, - Tập 3, _P3)
    t = re.sub(r"[\s:\-_]+(?:p\s*\d{1,4}[a-zA-Z]?|(?:tập|tap)\s*\d{1,4}[a-zA-Z]?|(?:phần|phan)\s*\d{1,4}[a-zA-Z]?)$", "", t, flags=re.IGNORECASE).strip()
    t = t.replace("_", " ")
    t = re.sub(r"\s+", " ", t).strip()
    # Dọn dẹp dấu gạch ngang, dấu phẩy, dấu chấm lơ lửng ở cuối
    t = re.sub(r"[\s,\-–_:]+$", "", t).strip()
    return t


def to_hashtag(text: str) -> str:
    """Tạo hashtag chuẩn YouTube: bắt đầu bằng #, không dấu tiếng Việt, không khoảng trắng, chỉ gồm chữ và số."""
    if not text:
        return ""
    s = str(text).replace("Đ", "D").replace("đ", "d")
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_text = "".join([c for c in nfkd if not unicodedata.combining(c)])
    clean = re.sub(r"[^a-zA-Z0-9]", "", ascii_text.lower())
    if not clean:
        return ""
    return f"#{clean}"


def to_ascii_tag(text: str) -> str:
    """Tạo hashtag không dấu viết liền từ tên tiếng Việt (tương thích ngược)."""
    h = to_hashtag(text)
    return h.lstrip("#")[:20] if h else "truyenaudio"


def format_tags_string(tags_input: Any) -> str:
    """Định dạng toàn bộ thẻ tags chuẩn 100%: #tagkhongdau, #tagkhongcach, #tagtieptheo."""
    if not tags_input:
        return "#video, #truyenaudio, #khampha"

    if isinstance(tags_input, str):
        raw_items = re.split(r"[,;\n]+", tags_input)
    elif isinstance(tags_input, (list, tuple, set)):
        raw_items = [str(x) for x in tags_input]
    else:
        raw_items = [str(tags_input)]

    results = []
    seen = set()

    for item in raw_items:
        s = item.strip()
        if not s:
            continue
        # Làm sạch ID số dài nếu có dính trong tag
        s = re.sub(r"\b\d{6,}\b", "", s).strip()
        if not s:
            continue

        if "#" in s:
            sub_parts = [p for p in s.split("#") if p.strip()]
        elif " " in s:
            # Vừa tạo tag cụm từ vừa thêm từ khóa chính
            words = s.split()
            sub_parts = [s]
            if len(words) > 2:
                sub_parts.append("".join(words[:2]))
        else:
            sub_parts = [s]

        for p in sub_parts:
            ht = to_hashtag(p)
            if ht and len(ht) > 2 and ht not in seen:
                seen.add(ht)
                results.append(ht)

    if not results:
        return "#video, #youtube"

    return ", ".join(results)


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
    def enhance_catchy_title(cls, raw_title: str) -> str:
        """Tự động phát hiện và viết lại tiêu đề thô / cụt lủn thành tiêu đề YouTube cực kỳ cuốn hút, giật gân, tò mò (High CTR)."""
        clean = extract_clean_video_title(raw_title).strip()
        if not clean:
            return "Câu Chuyện Kỳ Lạ - Sự Thật Bất Ngờ Khiến Tất Cả Sững Sờ"

        # Bổ sung từ bị cụt lửng ở đuôi nếu có
        dangling_fixes = [
            (r"\b(bị\s+rơi\s+vào|rơi\s+vào)\s*$", " Cơ Thể Bí Ẩn"),
            (r"\b(vô\s+tình\s+rơi\s+vào|lạc\s+vào)\s*$", " Thế Giới Kỳ Lạ"),
            (r"\b(bị|được|lại|sẽ|đã)\s*$", " Phát Hiện Sự Thật Động Trời"),
            (r"\b(vào|ở|tại|trong|cho|với|của)\s*$", " Hoàn Cảnh Khó Tin"),
            (r"\b(khi|thì|nếu|mà|vì)\s*$", " Sự Thật Được Phơi Bày"),
        ]
        completed = clean
        for pat, completion in dangling_fixes:
            if re.search(pat, completed, re.IGNORECASE):
                completed = re.sub(pat, "", completed, flags=re.IGNORECASE).strip() + completion
                break

        # Nếu đã có cấu trúc hấp dẫn hoặc dấu phân tách rõ ràng và đủ dài (>= 35 ký tự)
        if re.search(r"[-|:!?]", completed) and len(completed) >= 35:
            return completed[:95].strip()

        # Kho hook giật gân kích thích tương tác mạnh mẽ
        VIRAL_HOOKS = [
            "Cái Kết Khiến Triệu Người Ngỡ Ngàng",
            "Sự Thật Đằng Sau Khiến Ai Nấy Sững Sờ",
            "Cú Lội Ngược Dòng Đỉnh Cao Không Thể Ngờ",
            "Bước Ngoặt Định Mệnh Thay Đổi Cả Cuộc Đời",
            "Quyết Định Táo Bạo Khiến Kẻ Thù Khiếp Sợ",
            "Màn Đảo Ngược Tình Thế Chấn Động Tứ Phương",
            "Hành Trình Kỳ Lạ Chưa Từng Được Tiết Lộ",
            "Bí Mật Động Trời Khiến Tất Cả Bàng Hoàng",
            "Cái Giá Đắt Phải Trả Khi Xem Thường Người Khác",
            "Bài Học Đắt Giá Khiến Triệu Người Thán Phục",
        ]

        seed = abs(hash(completed)) % len(VIRAL_HOOKS)
        hook = VIRAL_HOOKS[seed]

        if re.search(r"\b(gì|sao|thế nào|không|ai)\s*$", completed, re.IGNORECASE):
            candidate = f"{completed}? - {hook}"
        else:
            candidate = f"{completed} - {hook}"

        if len(candidate) > 95:
            max_head = 95 - len(hook) - 4
            candidate = f"{completed[:max_head].rstrip()}... - {hook}"

        return candidate[:95].strip()

    @classmethod
    def generate_video_metadata(
        cls,
        story_title: str,
        episode_name: str = "",
        extra_info: str = "",
        channel_name: str = "",
        episode_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        clean_title = clean_story_title(story_title)
        badge = clean_episode_badge(episode_name, episode_index) if episode_name else ""
        ch_name = channel_name.strip() or "Truyện Audio"

        # Lấy hook theo index để từng tập có phụ đề khác nhau
        if episode_index is not None and episode_index > 0:
            hook_idx = (episode_index - 1) % len(cls.EPISODE_HOOKS)
            hl_idx = (episode_index - 1) % len(cls.HIGHLIGHT_HOOKS)
        else:
            seed = abs(hash(clean_title))
            hook_idx = seed % len(cls.EPISODE_HOOKS)
            hl_idx = seed % len(cls.HIGHLIGHT_HOOKS)

        hook = cls.EPISODE_HOOKS[hook_idx]
        hl_text = cls.HIGHLIGHT_HOOKS[hl_idx]

        # Tiêu đề chuẩn SEO YouTube (< 100 ký tự)
        if badge:
            candidate_title = f"{badge}: {clean_title} - {hook} | {ch_name}"
        else:
            candidate_title = f"{clean_title} - {hook} | {ch_name}"

        if len(candidate_title) > 98:
            candidate_title = f"{badge}: {clean_title} | {ch_name}" if badge else f"{clean_title} | {ch_name}"
            if len(candidate_title) > 98:
                candidate_title = candidate_title[:95] + "..."

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

        # Tags chuẩn SEO: Bắt buộc dạng #tagkhongdau, #tagkhongcach
        tags_list = [
            clean_title,
            "truyen audio",
            "kiem hiep",
            "tien hiep",
            "truyen audio hay",
            "truyen audio moi nhat",
            ch_name,
            "audio truyen",
            "doc truyen online",
            "review phim",
        ]
        if badge:
            tags_list.append(badge)
            tags_list.append(f"{clean_title} {badge}")
        tags = format_tags_string(tags_list)

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
    ) -> Dict[str, Any]:
        """Tạo trọn bộ Metadata: Tiêu đề giật tít SEO, Mô tả đầy đủ, Tags và text Thumbnail."""
        ep_info = episode_name if episode_name else "Video đơn lẻ / Không có số tập (KHÔNG thêm tiền tố tập hay P... vào tiêu đề)"
        title_eg = f'"{episode_name}: Tự Phế Đان Điền Để Đúc Căn Cơ Vô Thượng | {channel_name}"' if episode_name else f'"Tự Phế Đان Điền Để Đúc Căn Cơ Vô Thượng | {channel_name}"'
        prompt = f"""
Bạn là chuyên gia tối ưu hóa nội dung YouTube (SEO YouTube Master) cho các kênh truyện audio, phim, tiểu thuyết.
Hãy tạo thông tin đăng tải cho video YouTube sau:
- Tên truyện / Chủ đề: {story_title}
- Tập hoặc Chương: {ep_info}
- Thông tin thêm: {extra_info}
- Tên kênh: {channel_name}

Yêu cầu nghiêm ngặt:
1. "title": Tiêu đề cực kỳ cuốn hút, giật tít gây tò mò, chuẩn SEO nhưng TUYỆT ĐỐI KHÔNG vượt quá 95 ký tự. {title_eg}
2. "description": Mô tả video chuyên nghiệp gồm:
   - Đoạn tóm tắt mở đầu 3-4 câu kịch tính, lôi cuốn người nghe.
   - Danh sách lưu ý nghe truyện, lịch phát sóng.
   - Lời kêu gọi Like, Subscribe ủng hộ kênh.
   - Tuyên bố bản quyền & miễn trừ trách nhiệm (Disclaimer).
   - 5 đến 8 Hashtag liên quan chuẩn xu hướng (#truyenaudio #kiemhiep...).
3. "tags": Danh sách 15-20 từ khóa tìm kiếm (tags) chuẩn SEO liên quan nhất, cách nhau bằng dấu phẩy. Tổng độ dài dưới 450 ký tự.
4. "thumbnail_badge": Chữ số tập ngắn gọn cho huy hiệu thumbnail (nếu không có số tập thì để chuỗi rỗng "").
5. "thumbnail_highlight": Câu chữ ngắn 3-6 chữ gây sốc nhất để in to lên Thumbnail (ví dụ: "GIẢ LÀM PHẾ VẬT!").
6. "thumbnail_ai_prompt": Một prompt chi tiết bằng tiếng Anh (dài 30-50 từ) để vẽ ảnh bìa.

BẮT BUỘC TRẢ VỀ DƯỚI ĐỊNH DẠNG JSON DUY NHẤT:
{{
  "title": "...",
  "description": "...",
  "tags": "tag1, tag2, tag3, ...",
  "thumbnail_badge": "{episode_name}",
  "thumbnail_highlight": "...",
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
            if "tags" in res:
                res["tags"] = format_tags_string(res["tags"])
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
            )
            fallback["warning"] = f"Lỗi Gemini ({e}). Đã tự động sinh bằng Mẫu Chuẩn SEO Truyện Miễn Phí!"
            return fallback


class CustomAIAssistant:
    """Hỗ trợ OpenAI-compatible API (Groq, OpenRouter, DeepSeek, v.v.)."""

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
    ) -> Dict[str, Any]:
        ep_info = episode_name if episode_name else "Video đơn lẻ / Không có số tập (KHÔNG thêm tiền tố tập hay P... vào tiêu đề)"
        prompt = f"""Bạn là chuyên gia SEO YouTube truyện audio.
Tên truyện: {story_title}
Tập: {ep_info}
Kênh: {channel_name}

Trả về JSON duy nhất:
{{
  "title": "<tiêu đề dưới 95 ký tự>",
  "description": "<mô tả video đầy đủ kèm hashtag>",
  "tags": "<15 từ khóa cách nhau bằng dấu phẩy>",
  "thumbnail_badge": "{episode_name}",
  "thumbnail_highlight": "<3-5 chữ nổi bật in hoa>",
  "thumbnail_ai_prompt": "<prompt tiếng Anh>"
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
                if "tags" in res:
                    res["tags"] = format_tags_string(res["tags"])
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
        )

