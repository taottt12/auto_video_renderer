from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src_app.core.audio_crawler import (
    extract_entry_list,
    run_crawler,
    youtube_source_key,
    youtube_video_id,
)


class TestCrawlerProjectHistory(unittest.TestCase):
    def test_youtube_identifiers_are_stable(self):
        self.assertEqual(
            youtube_source_key("https://www.youtube.com/playlist?list=PL123&index=2"),
            "playlist:PL123",
        )
        self.assertEqual(youtube_video_id("https://youtu.be/abc123?t=5"), "abc123")
        self.assertEqual(youtube_video_id("https://www.youtube.com/watch?v=xyz789&list=PL1"), "xyz789")

    def test_completed_video_is_skipped_and_new_video_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp)
            old_file = save_dir / "old.mp3"
            old_file.write_bytes(b"0" * 12000)
            new_file = save_dir / "new.mp3"
            history = {
                "old-id": {
                    "status": "downloaded",
                    "file_path": str(old_file),
                    "source_key": "playlist:PL123",
                }
            }
            cfg = {
                "mode": "playlist",
                "playlist_url": "https://www.youtube.com/playlist?list=PL123",
                "save_folder": str(save_dir),
                "only_new": True,
                "download_history": history,
                "selected_targets": [
                    {"id": "old-id", "title": "Old", "url": "https://youtu.be/old-id"},
                    {"id": "new-id", "title": "New", "url": "https://youtu.be/new-id"},
                ],
            }

            def fake_download(**_kwargs):
                new_file.write_bytes(b"1" * 12000)
                return str(new_file)

            with patch("src_app.core.audio_crawler.download_single_audio", side_effect=fake_download):
                files = run_crawler(cfg)

            self.assertEqual(files, [str(new_file)])
            self.assertEqual(history["new-id"]["status"], "downloaded")
            self.assertEqual(history["new-id"]["source_key"], "playlist:PL123")

    def test_playlist_limit_is_applied_after_history_filter(self):
        class FakeYDL:
            def __init__(self, _opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, _url, download=False):
                self.assert_download = download
                return {
                    "entries": [
                        {"id": "old", "title": "Old", "url": "https://youtu.be/old"},
                        {"id": "new-1", "title": "New 1", "url": "https://youtu.be/new-1"},
                        {"id": "new-2", "title": "New 2", "url": "https://youtu.be/new-2"},
                    ]
                }

        with patch("src_app.core.audio_crawler.yt_dlp.YoutubeDL", FakeYDL):
            result = extract_entry_list(
                "https://youtube.com/playlist?list=PL123",
                limit=1,
                browser_cookie="none",
                exclude_ids={"old"},
            )

        self.assertEqual([item["id"] for item in result], ["new-1"])


if __name__ == "__main__":
    unittest.main()
