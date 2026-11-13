import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "server.py"
os.environ.setdefault("TOKEN_FILE", "/tmp/go2rtc-control-test-token")
spec = importlib.util.spec_from_file_location("go2rtc_control_server", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SourceRegistryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.config = root / "go2rtc.yaml"
        self.registry = root / "state" / "cameras.json"
        self.old_config = module.GO2RTC_CONFIG
        self.old_registry = module.SOURCE_REGISTRY
        module.GO2RTC_CONFIG = self.config
        module.SOURCE_REGISTRY = self.registry

    def tearDown(self):
        module.GO2RTC_CONFIG = self.old_config
        module.SOURCE_REGISTRY = self.old_registry
        self.directory.cleanup()

    def test_migrates_simple_named_sources_once(self):
        self.config.write_text(
            'streams:\n  salon: "rtsp://camera/live"\n  entree: "ffmpeg:source#video=h264"\n',
            encoding="utf-8",
        )
        module.ensure_source_registry()
        self.assertEqual(
            module.load_sources(),
            {"salon": "rtsp://camera/live", "entree": "ffmpeg:source#video=h264"},
        )
        self.assertEqual(self.registry.stat().st_mode & 0o777, 0o600)

    def test_ignores_complex_or_invalid_entries_during_migration(self):
        self.config.write_text(
            'streams:\n  ok: "rtsp://camera/live"\n  complex: ["a", "b"]\n  "bad name": "rtsp://x"\n',
            encoding="utf-8",
        )
        module.ensure_source_registry()
        self.assertEqual(module.load_sources(), {"ok": "rtsp://camera/live"})

    def test_registry_survives_yaml_entry_removal_and_restart(self):
        self.config.write_text('streams:\n  doorbell: "rtsp://user:password@camera/live"\n', encoding="utf-8")
        module.ensure_source_registry()
        # Simulate go2rtc DELETE removing the stream from its persistent YAML.
        self.config.write_text("streams: {}\n", encoding="utf-8")
        module.ensure_source_registry()
        self.assertEqual(module.load_sources(), {"doorbell": "rtsp://user:password@camera/live"})

    def test_existing_registry_is_never_overwritten(self):
        self.config.write_text('streams:\n  camera: "rtsp://new-source"\n', encoding="utf-8")
        self.registry.parent.mkdir(parents=True)
        self.registry.write_text(json.dumps({"camera": "rtsp://preserved-source"}), encoding="utf-8")
        module.ensure_source_registry()
        self.assertEqual(module.load_sources(), {"camera": "rtsp://preserved-source"})

    def test_empty_yaml_creates_empty_registry(self):
        self.config.write_text("streams: {}\n", encoding="utf-8")
        module.ensure_source_registry()
        self.assertEqual(module.load_sources(), {})


class CameraAudioSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.old_registry = module.SOURCE_REGISTRY
        module.SOURCE_REGISTRY = Path(self.directory.name) / "cameras.json"

    def tearDown(self):
        module.SOURCE_REGISTRY = self.old_registry
        self.directory.cleanup()

    def test_legacy_registry_preserves_existing_audio_behavior(self):
        module.SOURCE_REGISTRY.write_text(
            json.dumps({"salon": "rtsp://camera/live"}),
            encoding="utf-8",
        )
        settings = module.load_camera_settings()
        self.assertEqual(settings["salon"]["source"], "rtsp://camera/live")
        self.assertTrue(settings["salon"]["audio_enabled"])
        self.assertEqual(settings["salon"]["quality"], "1080p")

    def test_audio_preference_is_persisted_in_private_registry(self):
        expected = {
            "salon": {
                "source": "rtsp://camera/live",
                "audio_enabled": False,
                "quality": "720p",
                "default_profile_id": "native",
                "selected_profile_id": "native",
                "profiles": {"native": {"id": "native", "name": "Natif", "type": "native"}},
            }
        }
        module.save_camera_settings(expected)
        self.assertEqual(module.load_camera_settings(), expected)
        self.assertEqual(module.SOURCE_REGISTRY.stat().st_mode & 0o777, 0o600)

    def test_quality_preference_defaults_and_persists(self):
        module.SOURCE_REGISTRY.write_text(json.dumps({"salon": {"source": "rtsp://camera/stream1", "audio_enabled": True}}), encoding="utf-8")
        settings = module.load_camera_settings()
        self.assertEqual(settings["salon"]["quality"], "1080p")
        settings["salon"]["quality"] = "720p"
        module.save_camera_settings(settings)
        self.assertEqual(module.load_camera_settings()["salon"]["quality"], "720p")


    def test_legacy_registry_is_migrated_to_native_profile(self):
        module.SOURCE_REGISTRY.write_text(
            json.dumps({"salon": "rtsp://camera/live"}),
            encoding="utf-8",
        )
        module.ensure_source_registry()
        persisted = json.loads(module.SOURCE_REGISTRY.read_text(encoding="utf-8"))
        self.assertEqual(persisted["salon"]["source"], "rtsp://camera/live")
        self.assertTrue(persisted["salon"]["audio_enabled"])
        self.assertEqual(persisted["salon"]["quality"], "1080p")
        self.assertEqual(persisted["salon"]["default_profile_id"], "native")
        self.assertEqual(
            persisted["salon"]["profiles"],
            {"native": {"id": "native", "name": "Natif", "type": "native"}},
        )
        self.assertEqual(module.SOURCE_REGISTRY.stat().st_mode & 0o777, 0o600)

    def test_migration_preserves_existing_camera_preferences_and_ptz(self):
        original = {
            "source": "rtsp://camera/stream1",
            "audio_enabled": False,
            "quality": "720p",
            "ptz": {
                "host": "192.0.2.10",
                "port": 8080,
                "username": "operator",
                "password": "private-test-value",
            },
        }
        module.SOURCE_REGISTRY.write_text(
            json.dumps({"salon": original}),
            encoding="utf-8",
        )
        module.ensure_source_registry()
        migrated = json.loads(module.SOURCE_REGISTRY.read_text(encoding="utf-8"))["salon"]
        self.assertEqual(migrated["source"], original["source"])
        self.assertFalse(migrated["audio_enabled"])
        self.assertEqual(migrated["quality"], "720p")
        self.assertEqual(migrated["ptz"], original["ptz"])
        self.assertEqual(migrated["default_profile_id"], "native")
        self.assertEqual(list(migrated["profiles"]), ["native"])

    def test_custom_profiles_survive_registry_round_trip(self):
        profile_id = "0123456789abcdef0123456789abcdef"
        settings = {
            "salon": {
                "source": "rtsp://camera/stream1",
                "audio_enabled": False,
                "quality": "1080p",
                "default_profile_id": "native",
                "profiles": {
                    profile_id: {
                        "name": "Consultation mobile",
                        "type": "transcode",
                        "width": 854,
                        "height": 480,
                        "fps": 10,
                        "bitrate_kbps": 200,
                    }
                },
            }
        }
        module.save_camera_settings(settings)
        loaded = module.load_camera_settings()
        self.assertEqual(loaded["salon"]["default_profile_id"], "native")
        self.assertEqual(loaded["salon"]["profiles"][profile_id]["name"], "Consultation mobile")
        self.assertEqual(loaded["salon"]["profiles"][profile_id]["fps"], 10.0)
        self.assertFalse(loaded["salon"]["audio_enabled"])

    def test_invalid_persisted_profiles_are_not_silently_discarded(self):
        profile_id = "0123456789abcdef0123456789abcdef"
        module.SOURCE_REGISTRY.write_text(
            json.dumps({
                "salon": {
                    "source": "rtsp://camera/live",
                    "audio_enabled": True,
                    "quality": "720p",
                    "default_profile_id": "native",
                    "profiles": {
                        profile_id: {
                            "name": "Upscale",
                            "type": "transcode",
                            "width": 1920,
                            "height": 1080,
                            "fps": 10,
                            "bitrate_kbps": 200,
                        }
                    },
                }
            }),
            encoding="utf-8",
        )
        with self.assertRaises(module.ControlError):
            module.load_camera_settings()

    def test_quality_selects_native_rtsp_stream_and_preserves_query_fragment(self):
        source = "rtsp://user:password@camera:554/live/stream1?profile=main#tcp"
        self.assertEqual(module.source_for_quality(source, "720p"), "rtsp://user:password@camera:554/live/stream2?profile=main#tcp")
        self.assertEqual(module.source_for_quality(source, "1080p"), source)

    def test_quality_rejects_unsupported_source_path(self):
        with self.assertRaises(module.ControlError):
            module.source_for_quality("rtsp://camera/live", "720p")

    def test_1080p_keeps_non_tapo_source_unchanged(self):
        source = "rtsp://camera/live"
        self.assertEqual(module.source_for_quality(source, "1080p"), source)

    def test_quality_rejects_unknown_value(self):
        with self.assertRaises(module.ControlError):
            module.source_for_quality("rtsp://camera/stream1", "480p")

    def test_video_only_source_adds_media_fragment(self):
        self.assertEqual(
            module.source_for_audio("rtsp://camera/live", False),
            "rtsp://camera/live#media=video",
        )

    def test_audio_enabled_uses_original_source_unchanged(self):
        source = "rtsp://user:password@camera/live?profile=main"
        self.assertEqual(module.source_for_audio(source, True), source)

    def test_video_only_source_preserves_existing_fragment_options(self):
        self.assertEqual(
            module.source_for_audio("rtsp://camera/live#tcp", False),
            "rtsp://camera/live#tcp&media=video",
        )


if __name__ == "__main__":
    unittest.main()
