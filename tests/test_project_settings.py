from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src_app.core.settings import SettingsManager


class TestProjectSettings(unittest.TestCase):
    def test_global_save_moves_secrets_out_of_config(self):
        settings = {
            "audio_files": ["D:/audio/project-only.mp3"],
            "audio_crawler": {"cookie_file_path": "COOKIE", "save_folder": "D:/downloads"},
            "youtube_uploader": {"custom_api_key": "KEY", "active_channel_id": "channel"},
            "project": {"current_name": "Demo", "current_path": "D:/demo.avr.json", "output_folder": "D:/out"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "config.json"
            secrets_file = Path(tmp) / "secrets.json"
            manager = SettingsManager(config_file)
            with patch("src_app.core.settings.SECRETS_PATH", secrets_file):
                manager.save(settings)
                raw_config = json.loads(config_file.read_text(encoding="utf-8"))
                raw_secrets = json.loads(secrets_file.read_text(encoding="utf-8"))
                loaded = manager.load()

        self.assertNotIn("audio_files", raw_config)
        self.assertNotIn("cookie_file_path", raw_config["audio_crawler"])
        self.assertNotIn("custom_api_key", raw_config["youtube_uploader"])
        self.assertNotIn("output_folder", raw_config["project"])
        self.assertEqual(raw_secrets["audio_crawler"]["cookie_file_path"], "COOKIE")
        self.assertEqual(loaded["youtube_uploader"]["custom_api_key"], "KEY")

    def test_project_file_excludes_account_and_crawler_credentials(self):
        settings = {
            "audio_files": ["D:/audio/one.mp3"],
            "media_files": ["D:/media/bg.jpg"],
            "render_queue": [{"id": "job-1", "audio_file": "D:/audio/one.mp3", "title": "One"}],
            "opening_effect": {"enabled": True, "mode": "fade_black", "duration": 0.8},
            "audio_crawler": {"cookie_file_path": "SECRET_COOKIE", "save_folder": "D:/audio"},
            "youtube_uploader": {"custom_api_key": "SECRET_KEY", "active_channel_id": "channel"},
            "project": {"current_name": "Demo", "current_path": "D:/old/demo.avr.json"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            project_file = Path(tmp) / "demo.avr.json"
            SettingsManager.save_project(project_file, settings)
            raw = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertEqual(raw["audio_files"], ["D:/audio/one.mp3"])
        self.assertEqual(raw["render_queue"][0]["title"], "One")
        self.assertTrue(raw["opening_effect"]["enabled"])
        self.assertNotIn("audio_crawler", raw)
        self.assertNotIn("youtube_uploader", raw)
        self.assertNotIn("current_path", raw["project"])

    def test_loading_project_keeps_global_account_settings(self):
        legacy_project = {
            "audio_files": ["D:/audio/project.mp3"],
            "youtube_uploader": {"custom_api_key": "OLD_PROJECT_SECRET"},
            "audio_crawler": {"cookie_file_path": "OLD_PROJECT_COOKIE"},
            "project": {"current_name": "Demo"},
        }
        base = {
            "youtube_uploader": {"custom_api_key": "GLOBAL_SECRET", "active_channel_id": "abc"},
            "audio_crawler": {"cookie_file_path": "GLOBAL_COOKIE"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            project_file = Path(tmp) / "demo.avr.json"
            project_file.write_text(json.dumps(legacy_project), encoding="utf-8")
            loaded = SettingsManager.load_project(project_file, base)

        self.assertEqual(loaded["audio_files"], ["D:/audio/project.mp3"])
        self.assertEqual(loaded["youtube_uploader"]["custom_api_key"], "GLOBAL_SECRET")
        self.assertEqual(loaded["audio_crawler"]["cookie_file_path"], "GLOBAL_COOKIE")
        self.assertEqual(loaded["project"]["current_path"], str(project_file))


if __name__ == "__main__":
    unittest.main()
