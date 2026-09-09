from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests


class GeminiAssistant:
    """Trợ lý AI tạo Tiêu đề, Mô tả, Tags và Ý tưởng Thumbnail chuẩn YouTube."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self.api_key = (api_key or "").strip()
        self.model = model or "gemini-2.0-flash"
        self.endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _call_gemini(self, prompt: str) -> str:
        if not self.api_key:
            raise ValueError("Chưa cấu hình Gemini API Key!")

        url = f"{self.endpoint}?key={self.api_key}"
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

        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code != 200:
            # Nếu model 2.0 chưa khả dụng trên key, thử fallback 1.5-flash
            if self.model != "gemini-1.5-flash" and resp.status_code in (404, 400):
                fallback_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"
                fallback_resp = requests.post(fallback_url, json=payload, timeout=30)
                if fallback_resp.status_code == 200:
                    data = fallback_resp.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"]
            raise RuntimeError(f"Lỗi gọi Gemini API (HTTP {resp.status_code}): {resp.text}")

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini không trả về nội dung nào.")
        return candidates[0]["content"]["parts"][0]["text"]

    def generate_video_metadata(
        self,
        story_title: str,
        episode_name: str = "",
        extra_info: str = "",
        channel_name: str = "",
    ) -> Dict[str, Any]:
        """Tạo trọn bộ Metadata: Tiêu đề giật tít SEO, Mô tả đầy đủ, Tags và text Thumbnail."""
        prompt = f"""
Bạn là chuyên gia tối ưu hóa nội dung YouTube (SEO YouTube Master) cho các kênh truyện audio, phim, tiểu thuyết, tin tức.
Hãy tạo thông tin đăng tải cho video YouTube sau:
- Tên truyện / Chủ đề: {story_title}
- Tập hoặc Chương: {episode_name}
- Thông tin thêm: {extra_info}
- Tên kênh: {channel_name}

Yêu cầu nghiêm ngặt:
1. "title": Tiêu đề cực kỳ cuốn hút, giật tít gây tò mò, chuẩn SEO nhưng TUYỆT ĐỐI KHÔNG vượt quá 95 ký tự. Ví dụ: "TẬP 32: Tự Phế Đan Điền Giả Làm Phế Vật Để Đúc Căn Cơ Vô Thượng | {channel_name}"
2. "description": Mô tả video chuyên nghiệp gồm:
   - Đoạn tóm tắt mở đầu 3-4 câu cực kỳ kịch tính, lôi cuốn người nghe.
   - Danh sách mốc thời gian hoặc lưu ý nghe truyện.
   - Lời kêu gọi Like, Subscribe ủng hộ kênh.
   - Tuyên bố bản quyền & miễn trừ trách nhiệm (Disclaimer).
   - 5 đến 8 Hashtag liên quan chuẩn xu hướng (#truyenaudio #kiemhiep...).
3. "tags": Danh sách 15-20 từ khóa tìm kiếm (tags) chuẩn SEO liên quan nhất, cách nhau bằng dấu phẩy. Tổng độ dài dưới 450 ký tự.
4. "thumbnail_badge": Chữ số tập ngắn gọn cho huy hiệu thumbnail (ví dụ: "TẬP 32").
5. "thumbnail_highlight": Câu chữ ngắn 3-6 chữ gây sốc nhất để in to lên Thumbnail (ví dụ: "GIẢ LÀM PHẾ VẬT!").
6. "thumbnail_ai_prompt": Một prompt chi tiết bằng tiếng Anh (dài 30-50 từ) để đưa cho AI vẽ ảnh bìa phù hợp với nội dung truyện (ví dụ: "Cinematic anime artwork of a mystical warrior with glowing purple aura sitting in deep meditation, shattered stone surroundings, dramatic celestial lighting, 8k wallpaper").

BẮT BUỘC TRẢ VỀ DƯỚI ĐỊNH DẠNG JSON DUY NHẤT (không kèm markdown ngoài khối JSON):
{{
  "title": "...",
  "description": "...",
  "tags": "tag1, tag2, tag3, ...",
  "thumbnail_badge": "...",
  "thumbnail_highlight": "...",
  "thumbnail_ai_prompt": "..."
}}
"""
        raw = self._call_gemini(prompt)

        # Trích xuất JSON từ text
        cleaned = raw.strip()
        if "`json" in cleaned:
            cleaned = cleaned.split("`json", 1)[1].split("`", 1)[0].strip()
        elif "`" in cleaned:
            cleaned = cleaned.split("`", 1)[1].split("`", 1)[0].strip()

        try:
            res = json.loads(cleaned)
        except Exception:
            # Fallback nếu parse json thất bại
            res = {
                "title": f"{story_title} - {episode_name}"[:95],
                "description": f"Chào mừng bạn đến với kênh! Đón nghe {story_title} {episode_name}.\n\n#truyenaudio #audio",
                "tags": f"{story_title}, {episode_name}, truyen audio, kiem hiep",
                "thumbnail_badge": episode_name or "MỚI NHẤT",
                "thumbnail_highlight": story_title[:20].upper(),
                "thumbnail_ai_prompt": "Fantasy anime wallpaper, mystical warrior with glowing aura, highly detailed, 8k",
            }

        # Đảm bảo title không quá 100 ký tự
        if len(res.get("title", "")) > 100:
            res["title"] = res["title"][:97] + "..."

        return res
