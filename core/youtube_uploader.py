from __future__ import annotations

import datetime
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from .youtube_auth import YouTubeAuthManager

ProgressCallback = Callable[[int, str, float], None]  # (percent, status_message, speed_mbps)


class YouTubeUploader:
    """Xử lý tải video lên YouTube với Resumable Upload, Playlist, Hẹn giờ và Thumbnail."""

    def __init__(self, auth_manager: Optional[YouTubeAuthManager] = None) -> None:
        self.auth_manager = auth_manager or YouTubeAuthManager()

    def get_service(self, channel_id: str):
        return self.auth_manager.get_service(channel_id)

    def list_playlists(self, channel_id: str) -> List[Dict[str, str]]:
        """Lấy toàn bộ danh sách playlist của kênh (hỗ trợ phân trang không giới hạn)."""
        playlists: List[Dict[str, str]] = []
        try:
            youtube = self.get_service(channel_id)
            request = youtube.playlists().list(
                part="snippet",
                mine=True,
                maxResults=50
            )
            while request:
                resp = request.execute()
                for item in resp.get("items", []):
                    title = item.get("snippet", {}).get("title", "")
                    pl_id = item.get("id", "")
                    if pl_id and title:
                        playlists.append({"id": pl_id, "title": title})
                request = youtube.playlists().list_next(request, resp)
            return playlists
        except Exception as e:
            print(f"Lỗi lấy toàn bộ playlist: {e}")
            return playlists

    def ensure_playlist(self, channel_id: str, playlist_title: str) -> str:
        """Kiểm tra playlist đã có chưa, nếu chưa thì tạo mới."""
        title_clean = playlist_title.strip()
        if not title_clean:
            return ""

        existing = self.list_playlists(channel_id)
        for pl in existing:
            if pl["title"].lower() == title_clean.lower():
                return pl["id"]

        # Tạo mới
        youtube = self.get_service(channel_id)
        resp = youtube.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": title_clean,
                    "description": f"Danh sách phát cho {title_clean}"
                },
                "status": {
                    "privacyStatus": "public"
                }
            }
        ).execute()
        return resp.get("id", "")

    def add_video_to_playlist(self, channel_id: str, playlist_id: str, video_id: str) -> None:
        if not playlist_id or not video_id:
            return
        youtube = self.get_service(channel_id)
        youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id
                    }
                }
            }
        ).execute()

    def set_thumbnail(self, channel_id: str, video_id: str, thumbnail_path: str | Path) -> bool:
        t_path = Path(thumbnail_path)
        if not t_path.exists():
            return False
        try:
            youtube = self.get_service(channel_id)
            media = MediaFileUpload(str(t_path), mimetype="image/jpeg", resumable=False)
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=media
            ).execute()
            return True
        except Exception as e:
            print(f"Lỗi đặt thumbnail: {e}")
            return False

    @staticmethod
    def calculate_schedule_slots(
        start_date: datetime.date,
        time_slots: List[str],
        count: int,
    ) -> List[datetime.datetime]:
        """Tính toán lịch đăng giãn cách theo số mốc giờ cố định trong ngày cho N video.

        Ví dụ: 2 mốc ['11:30', '19:30'] cho 5 video:
        - Tập 1: Ngày 1 11:30
        - Tập 2: Ngày 1 19:30
        - Tập 3: Ngày 2 11:30
        - Tập 4: Ngày 2 19:30
        - Tập 5: Ngày 3 11:30
        """
        if not time_slots:
            time_slots = ["11:30", "19:30"]

        parsed_slots: List[datetime.time] = []
        for ts in time_slots:
            try:
                parts = ts.strip().split(":")
                parsed_slots.append(datetime.time(int(parts[0]), int(parts[1])))
            except Exception:
                parsed_slots.append(datetime.time(12, 0))

        slots_per_day = len(parsed_slots)
        results: List[datetime.datetime] = []

        for i in range(count):
            day_offset = i // slots_per_day
            slot_idx = i % slots_per_day
            target_date = start_date + datetime.timedelta(days=day_offset)
            target_time = parsed_slots[slot_idx]
            dt = datetime.datetime.combine(target_date, target_time)
            results.append(dt)

        return results

    def upload_video(
        self,
        channel_id: str,
        video_path: str | Path,
        title: str,
        description: str,
        tags: str | List[str],
        privacy_status: str = "private",
        publish_at: Optional[datetime.datetime] = None,
        is_premiere: bool = False,
        category_id: str = "24",
        thumbnail_path: Optional[str | Path] = None,
        playlist_name: str = "",
        playlist_id: Optional[str] = None,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> Dict[str, Any]:
        """Tải video lên YouTube bằng giao thức Resumable Upload và cấu hình đầy đủ."""
        v_path = Path(video_path)
        if not v_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file video: {v_path}")

        file_size = v_path.stat().st_size
        youtube = self.get_service(channel_id)

        # Xử lý tags
        if isinstance(tags, str):
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        else:
            tag_list = tags

        body: Dict[str, Any] = {
            "snippet": {
                "title": title[:100],
                "description": description,
                "tags": tag_list,
                "categoryId": str(category_id or "24"),
            },
            "status": {
                "selfDeclaredMadeForKids": False,
            }
        }

        # Nếu có hẹn giờ
        if publish_at is not None and privacy_status == "schedule":
            # Chuyển sang chuẩn UTC ISO 8601 (Local Time -> UTC)
            utc_dt = publish_at.astimezone(datetime.timezone.utc)
            body["status"]["privacyStatus"] = "private"  # Theo chuẩn YouTube, video hẹn giờ ban đầu phải là private
            body["status"]["publishAt"] = utc_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        else:
            body["status"]["privacyStatus"] = privacy_status

        # Chunk size 2MB (256KB * 8)
        chunk_size = 2 * 1024 * 1024
        media = MediaFileUpload(str(v_path), chunksize=chunk_size, resumable=True, mimetype="video/mp4")

        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )

        response = None
        start_time = time.time()
        last_progress_time = start_time
        last_bytes = 0

        while response is None:
            status, response = request.next_chunk()
            if status:
                progress_pct = int(status.progress() * 100)
                now = time.time()
                elapsed = max(0.1, now - last_progress_time)
                uploaded_bytes = status.resumable_progress
                speed_mbps = ((uploaded_bytes - last_bytes) / (1024 * 1024)) / elapsed if elapsed > 0 else 0.0

                if progress_cb:
                    progress_cb(
                        progress_pct,
                        f"Đang tải lên: {progress_pct}% ({uploaded_bytes / (1024 * 1024):.1f} / {file_size / (1024 * 1024):.1f} MB)",
                        speed_mbps
                    )
                last_progress_time = now
                last_bytes = uploaded_bytes

        video_id = response.get("id", "")
        video_url = f"https://youtu.be/{video_id}"

        # 1. Đặt thumbnail nếu có
        if thumbnail_path and Path(thumbnail_path).exists():
            if progress_cb:
                progress_cb(98, "Đang tải ảnh thumbnail...", 0.0)
            self.set_thumbnail(channel_id, video_id, thumbnail_path)

        # 2. Thêm vào playlist nếu người dùng có chọn hoặc tạo mới
        target_pl_id = (playlist_id or "").strip()
        if not target_pl_id and playlist_name.strip():
            if progress_cb:
                progress_cb(99, f"Đang kiểm tra/tạo Playlist: {playlist_name.strip()}...", 0.0)
            try:
                target_pl_id = self.ensure_playlist(channel_id, playlist_name.strip())
            except Exception as pe:
                print(f"Lỗi tạo/tìm playlist: {pe}")

        if target_pl_id:
            if progress_cb:
                progress_cb(99, "Đang thêm video vào Playlist...", 0.0)
            try:
                self.add_video_to_playlist(channel_id, target_pl_id, video_id)
            except Exception as pe:
                print(f"Lỗi thêm playlist: {pe}")

        if progress_cb:
            progress_cb(100, f"Hoàn thành tải lên: {video_url}", 0.0)

        return {
            "video_id": video_id,
            "video_url": video_url,
            "title": title,
            "status": body["status"]["privacyStatus"],
            "response": response
        }
