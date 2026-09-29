from __future__ import annotations

import base64
import json
import random
import urllib.parse
from pathlib import Path
from typing import Optional, List, Tuple
import requests
from PIL import Image


class AIImageGenerator:
    """Bc sinh anh Thumbnail AI chat luong cao chuan YouTube (1280x720)."""
    AVAILABLE_MODELS = [
        ("flux", "Flux Photorealistic (Sieu thuc, Dep nhat - Mien phi)"),
        ("flux-realism", "Flux Realism (Chan thuc dien anh - Mien phi)"),
        ("flux-anime", "Flux Anime / Fantasy (Tien hiep, Vien tuong - Mien phi)"),
        ("turbo", "SDXL Turbo (Tao sieu toc - Mien phi)"),
        ("imagen-3", "Google Imagen 3 (Yeu cau Gemini API Key)"),
        ("dall-e-3", "OpenAI DALL-E3 (Yeu cau OpenAI API Key)"),
    ]

    @classmethod
    def clean_visual_prompt(cls, prompt: str) -> str:
        """Tách lấy phần mô tả hình ảnh bối cảnh và nhân vật, loại bỏ các dòng hướng dẫn typography
        để Diffusion Model (Flux, SDXL, Imagen) không cố gắng vẽ chữ méo mó hoặc đặt nhân vật vào giữa.
        Đảm bảo nhân vật ở tiền cảnh bên phải, bên trái để trống 60% cho typography nghệ thuật."""
        import re
        p = prompt.strip()
        # Bỏ tiêu đề 'Part 1: Scene & Characters' ở đầu nếu có
        p = re.sub(r"^(?:Part\s*1\s*[:\-]\s*(?:Scene\s*&\s*Characters)?)[\s:\-_]*", "", p, flags=re.IGNORECASE).strip()

        split_markers = [
            "Part 2 -",
            "Part 2:",
            "Part 2",
            "Prominent, multi-layered",
            "Embedded typography",
            "Prominent 3D YouTube typography",
            "Typography breakdown",
            "Typography:",
            "Typography (LEFT SIDE OF FRAME):",
        ]
        for m in split_markers:
            if m.lower() in p.lower():
                idx = p.lower().find(m.lower())
                p = p[:idx].strip()
                break

        # Nếu có Part 3 (Lighting / Technical specs) ở cuối prompt gốc, thêm vào để tăng độ chân thực
        tech_specs = ""
        tech_markers = ["Part 3 -", "Part 3:", "Technical & Lighting", "Technical specs", "Part 3"]
        for tm in tech_markers:
            if tm.lower() in prompt.lower():
                t_idx = prompt.lower().find(tm.lower())
                raw_tech = prompt[t_idx:].split("\n", 1)
                if len(raw_tech) > 1:
                    tech_specs = raw_tech[1].strip()
                else:
                    tech_specs = raw_tech[0].strip()
                break

        tech_specs = re.sub(r"^(?:Part\s*3\s*[:\-]\s*(?:Technical\s*Specs)?)[\s:\-_]*", "", tech_specs, flags=re.IGNORECASE).strip()

        # Đưa chỉ dẫn bố cục lệch phải lên đầu để Diffusion Model ưu tiên tạo nhân vật ở bên phải
        front_instruction = "Extreme right-side composition, off-center framing: On the far right 35 percent of the widescreen frame, "
        back_instruction = ". The left 65 percent of the frame is unoccupied room interior background with soft blur, wide empty negative space on the left, absolutely no people on the left side"
        if tech_specs:
            back_instruction += f", {tech_specs}"
        back_instruction += ", ultra-sharp 8k cinematic photography, widescreen 16:9, no text, no words, no letters in image"

        return f"{front_instruction}{p}{back_instruction}"

    @classmethod
    def generate_image(
        cls,
        prompt: str,
        output_path: Path | str,
        model_name: str = "flux",
        width: int = 1280,
        height: int = 720,
        api_key: str = "",
        base_url: str = "",
        timeout: int = 45,
    ) -> Path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        clean_prompt = prompt.strip()
        if not clean_prompt:
            raise ValueError("Prompt tao anh khong duoc de trong!")

        visual_prompt = cls.clean_visual_prompt(clean_prompt)

        if model_name == "imagen-3":
            if not api_key:
                raise ValueError("Chưa nhập Gemini API Key để dùng Google Imagen 3!")
            return cls._generate_with_imagen3(visual_prompt, out_p, api_key, timeout)

        if model_name == "dall-e-3":
            if not api_key:
                raise ValueError("Chưa nhập OpenAI API Key để dùng OpenAI DALL-E 3!")
            return cls._generate_with_dalle3(visual_prompt, out_p, api_key, base_url, timeout)

        return cls._generate_with_pollinations(
            prompt=visual_prompt,
            output_path=out_p,
            model=model_name,
            width=width,
            height=height,
            timeout=timeout,
        )

    @classmethod
    def _generate_with_pollinations(
        cls,
        prompt: str,
        output_path: Path,
        model: str = "flux",
        width: int = 1280,
        height: int = 720,
        timeout: int = 45,
    ) -> Path:
        seed = random.randint(1000, 999999)
        encoded_prompt = urllib.parse.quote(prompt)
        url = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?width={width}&height={height}&model={model}&nologo=true&seed={seed}&enhance=false"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200 and len(resp.content) > 1000:
                with open(out_path := str(output_path), "wb") as f:
                    f.write(resp.content)
                with Image.open(out_path) as img:
                    img = img.convert("RGB")
                    if img.size != (width, height):
                        img = img.resize((width, height), Image.Resampling.LANCZOS)
                    # Dọn dẹp watermark pollinations nhỏ ở góc phải dưới nếu có
                    try:
                        w_crop = img.crop((width - 160, height - 60, width, height - 30))
                        img.paste(w_crop, (width - 160, height - 30))
                    except Exception:
                        pass
                    img.save(out_path, "JPEG", quality=95)
                return output_path
            else:
                raise RuntimeError(f"Pollinations tra ve ma {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            if model != "flux":
                return cls._generate_with_pollinations(prompt, output_path, "flux", width, height, timeout)
            raise RuntimeError(f"Loi tao anh AI qua Pollinations ({e})")

    @classmethod
    def _generate_with_imagen3(cls, prompt: str, output_path: Path, api_key: str, timeout: int) -> Path:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={api_key}"
        payload = {
            "instances": [{"prompt": prompt}],
            "parameters": {
                "sampleCount": 1,
                "aspectRatio": "16:9",
                "outputOptions": {"mimeType": "image/jpeg"},
            },
        }
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            predictions = data.get("predictions", [])
            if predictions and "bytesBase64Encoded" in predictions[0]:
                raw_bytes = base64.b64decode(predictions[0]["bytesBase64Encoded"])
                with open(output_path, "wb") as f:
                    f.write(raw_bytes)
                return output_path
        raise RuntimeError(f"Loi tao anh Imagen 3 ({resp.status_code}): {resp.text[:300]}")

    @classmethod
    def _generate_with_dalle3(
        cls, prompt: str, output_path: Path, api_key: str, base_url: str, timeout: int
    ) -> Path:
        base = (base_url or "https://api.openai.com/v1").rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        url = f"{base}/images/generations"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "dall-e-3",
            "prompt": prompt,
            "n": 1,
            "size": "1792x1024",
            "response_format": "b64_json",
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data", [])
            if items:
                if "b64_json" in items[0]:
                    raw_bytes = base64.b64decode(items[0]["b64_json"])
                    with open(output_path, "wb") as f:
                        f.write(raw_bytes)
                    return output_path
                elif "url" in items[0]:
                    img_resp = requests.get(items[0]["url"], timeout=timeout)
                    if img_resp.status_code == 200:
                        with open(out_path, "wb") as f:
                            f.write(img_resp.content)
                        return output_path
        raise RuntimeError(f"Loi tao anh DALL-E 3 ({resp.status_code}): {resp.text[:300]}")
