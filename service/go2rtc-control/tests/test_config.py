import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "server.py"
os.environ.setdefault("TOKEN_FILE", "/tmp/go2rtc-control-test-token")
spec = importlib.util.spec_from_file_location("go2rtc_control_server", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LoadSourcesTests(unittest.TestCase):
    def test_loads_simple_named_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "go2rtc.yaml"
            config.write_text(
                'streams:\n  salon: "rtsp://camera/live"\n  entree: "ffmpeg:source#video=h264"\n',
                encoding="utf-8",
            )
            old_path = module.GO2RTC_CONFIG
            module.GO2RTC_CONFIG = config
            try:
                self.assertEqual(
                    module.load_sources(),
                    {"salon": "rtsp://camera/live", "entree": "ffmpeg:source#video=h264"},
                )
            finally:
                module.GO2RTC_CONFIG = old_path

    def test_ignores_complex_or_invalid_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "go2rtc.yaml"
            config.write_text(
                'streams:\n  ok: "rtsp://camera/live"\n  complex: ["a", "b"]\n  "bad name": "rtsp://x"\n',
                encoding="utf-8",
            )
            old_path = module.GO2RTC_CONFIG
            module.GO2RTC_CONFIG = config
            try:
                self.assertEqual(module.load_sources(), {"ok": "rtsp://camera/live"})
            finally:
                module.GO2RTC_CONFIG = old_path


if __name__ == "__main__":
    unittest.main()
