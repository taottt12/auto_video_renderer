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


def clean_episode_badge(ep: str, fallback_idx: int = 1) -> str:
    """Nhận diện huy hiệu tập ngắn gọn (mặc định dạng P1, P2, P3... theo yêu cầu người dùng)."""
    if not ep:
        return f"P{fallback_idx}"
    m = re.search(r"\b(p\d+[a-zA-Z]?|tập\s*\d+[a-zA-Z]?|phần\s*\d+[a-zA-Z]?|chương\s*\d+[a-zA-Z]?)\b", ep, re.IGNORECASE)
    if m:
        raw = m.group(1).upper()
        if raw.startswith("P") and raw[1:].isalnum():
            return raw
        # Rút gọn PHẦN 1, TẬP 1, CHƯƠNG 1 -> P1
        m_num = re.search(r"\d+[a-zA-Z]?", raw)
        if m_num:
            return f"P{m_num.group(0)}"
        return re.sub(r"\s+", " ", raw)
    m_num = re.search(r"\d+[a-zA-Z]?", ep)
    if m_num:
        return f"P{m_num.group(0)}"
    return f"P{fallback_idx}"


def to_ascii_tag(text: str) -> str:
    """Tạo hashtag không dấu viết liền từ tên tiếng Việt."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = "".join([c for c in nfkd if not unicodedata.combining(c)])
    clean = re.sub(r"[^a-zA-Z0-9]", "", ascii_text.lower())
    return clean[:20] if clean else "truyenaudio"


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
    def generate_video_metadata(
        cls,
        story_title: str,
        episode_name: str = "",
        extra_info: str = "",
        channel_name: str = "",
        episode_index: int = 1,
    ) -> Dict[str, Any]:
        clean_title = clean_story_title(story_title)
        badge = clean_episode_badge(episode_name, episode_index)
        ch_name = channel_name.strip() or "Truyện Audio"

        # Lấy hook theo index để từng tập có phụ đề khác nhau
        hook_idx = (episode_index - 1) % len(cls.EPISODE_HOOKS)
        hook = cls.EPISODE_HOOKS[hook_idx]

        hl_idx = (episode_index - 1) % len(cls.HIGHLIGHT_HOOKS)
        hl_text = cls.HIGHLIGHT_HOOKS[hl_idx]

        # Tiêu đề chuẩn SEO YouTube (< 100 ký tự)
        # Ví dụ: "PHẦN 1: Ta Là Tiêu Sư Giữ Quy Củ Nhất Thiên Hạ - Xuất Sơn Lập Uy | Gã Đạo Tặc"
        candidate_title = f"{badge}: {clean_title} - {hook} | {ch_name}"
        if len(candidate_title) > 98:
            # Rút gọn nếu quá dài
            candidate_title = f"{badge}: {clean_title} | {ch_name}"
            if len(candidate_title) > 98:
                candidate_title = candidate_title[:95] + "..."

        # Hashtags
        tag_story = to_ascii_tag(clean_title)
        tag_ch = to_ascii_tag(ch_name)
        tag_badge = to_ascii_tag(badge)

        # Mô tả chuyên nghiệp chuẩn YouTube
        description = f"""🎧 Chào mừng quý thính giả đến với kênh {ch_name}!
📖 Mời các bạn cùng lắng nghe bộ truyện audio đặc sắc:
⚔ {clean_title} ({badge})

🔥 Tóm tắt nội dung {badge}:
Hành trình kịch tính và đầy lôi cuốn của nhân vật chính giữa muôn trùng hiểm nguy và những quy tắc khắc nghiệt nơi giang hồ. Cùng theo dõi những tình tiết bất ngờ, những trận so tài nghẹt thở trong {badge}!

🎙 Diễn đọc: AI Story Audio
📻 Chất lượng âm thanh: Âm thanh vòm Stereo chất lượng cao
⏰ Lịch phát sóng: Phát định kỳ hàng ngày trên kênh {ch_name}

🔔 Hãy bấm ĐĂNG KÝ KÊNH (Subscribe) và BẬT CHUÔNG 🔔 để đón nghe các tập tiếp theo sớm nhất!
👍 Đừng quên LIKE & BÌNH LUẬN cảm xúc của bạn dưới video để ủng hộ kênh nhé!

© Bản quyền nội dung và âm thanh thuộc về {ch_name}.
Vui lòng không sao chép hoặc reup dưới mọi hình thức để tôn trọng bản quyền tác giả.

#truyenaudio #kiemhiep #tienhiep #{tag_story} #{tag_ch} #{tag_badge} #audiodoctruyen
"""

        # Tags chuẩn SEO
        tags_list = [
            clean_title.lower(),
            "truyen audio",
            "kiem hiep",
            "tien hiep",
            "truyen audio hay",
            "truyen audio moi nhat",
            badge.lower(),
            ch_name.lower(),
            "audio truyen",
            "doc truyen online",
            "truyen audio trinh tham",
            f"{clean_title.lower()} {badge.lower()}",
        ]
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
                "maxOutputTokens": 2048,
            }
        }

        for m in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={self.api_key}"
            try:
                resp = requests.post(url, json=payload, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        return candidates[0]["content"]["parts"][0]["text"]
                last_error = f"Model {m} trả về HTTP {resp.status_code}: {resp.text}"
            except Exception as e:
                last_error = str(e)
                continue

        raise RuntimeError(f"Không thể kết nối Gemini API:\n{last_error}")

    def generate_video_metadata(
        self,
        story_title: str,
        episode_name: str = "",
        extra_info: str = "",
        channel_name: str = "",
        episode_index: int = 1,
    ) -> Dict[str, Any]:
        """Tạo trọn bộ Metadata: Tiêu đề giật tít SEO, Mô tả đầy đủ, Tags và text Thumbnail."""
        prompt = f"""
Bạn là chuyên gia tối ưu hóa nội dung YouTube (SEO YouTube Master) cho các kênh truyện audio, phim, tiểu thuyết.
Hãy tạo thông tin đăng tải cho video YouTube sau:
- Tên truyện / Chủ đề: {story_title}
- Tập hoặc Chương: {episode_name}
- Thông tin thêm: {extra_info}
- Tên kênh: {channel_name}

Yêu cầu nghiêm ngặt:
1. "title": Tiêu đề cực kỳ cuốn hút, giật tít gây tò mò, chuẩn SEO nhưng TUYỆT ĐỐI KHÔNG vượt quá 95 ký tự. Ví dụ: "{episode_name}: Tự Phế Đan Điền Để Đúc Căn Cơ Vô Thượng | {channel_name}"
2. "description": Mô tả video chuyên nghiệp gồm:
   - Đoạn tóm tắt mở đầu 3-4 câu kịch tính, lôi cuốn người nghe.
   - Danh sách lưu ý nghe truyện, lịch phát sóng.
   - Lời kêu gọi Like, Subscribe ủng hộ kênh.
   - Tuyên bố bản quyền & miễn trừ trách nhiệm (Disclaimer).
   - 5 đến 8 Hashtag liên quan chuẩn xu hướng (#truyenaudio #kiemhiep...).
3. "tags": Danh sách 15-20 từ khóa tìm kiếm (tags) chuẩn SEO liên quan nhất, cách nhau bằng dấu phẩy. Tổng độ dài dưới 450 ký tự.
4. "thumbnail_badge": Chữ số tập ngắn gọn cho huy hiệu thumbnail (ví dụ: "{episode_name}").
5. "thumbnail_highlight": Câu chữ ngắn 3-6 chữ gây sốc nhất để in to lên Thumbnail (ví dụ: "GIẢ LÀM PHẾ VẬT!").
6. "thumbnail_ai_prompt": Một prompt chi tiết bằng tiếng Anh (dài 30-50 từ) để vẽ ảnh bìa.

BẮT BUỘC TRẢ VỀ DƯỚI ĐỊNH DẠNG JSON DUY NHẤT:
{{
  "title": "...",
  "description": "...",
  "tags": "tag1, tag2, tag3, ...",
  "thumbnail_badge": "...",
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
            if len(res.get("title", "")) > 100:
                res["title"] = res["title"][:97] + "..."
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
        episode_index: int = 1,
    ) -> Dict[str, Any]:
        prompt = f"""Bạn là chuyên gia SEO YouTube truyện audio.
Tên truyện: {story_title}
Tập: {episode_name}
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

