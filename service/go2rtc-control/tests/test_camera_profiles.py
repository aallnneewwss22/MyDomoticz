import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from camera_profiles import (
    CameraProfileError,
    NATIVE_PROFILE,
    NATIVE_PROFILE_ID,
    normalize_camera_profiles,
)


class CameraProfileNormalizationTests(unittest.TestCase):
    def test_missing_profiles_creates_mandatory_native_default(self):
        profiles, default_id = normalize_camera_profiles(None, None, "1080p")
        self.assertEqual(profiles, {"native": NATIVE_PROFILE})
        self.assertEqual(default_id, NATIVE_PROFILE_ID)

    def test_native_profile_is_canonical_and_cannot_be_customized(self):
        profiles, default_id = normalize_camera_profiles(
            {"native": dict(NATIVE_PROFILE)}, "native", "1080p"
        )
        self.assertEqual(profiles["native"], NATIVE_PROFILE)
        self.assertEqual(default_id, "native")
        with self.assertRaises(CameraProfileError):
            normalize_camera_profiles(
                {"native": {"id": "native", "name": "Original", "type": "native"}},
                "native",
                "1080p",
            )

    def test_custom_profiles_are_normalized_and_keep_stable_ids(self):
        profile_id = "0123456789abcdef0123456789abcdef"
        profiles, default_id = normalize_camera_profiles(
            {
                profile_id: {
                    "name": "  Consultation mobile  ",
                    "type": "transcode",
                    "width": 854,
                    "height": 480,
                    "fps": 10,
                    "bitrate_kbps": 200,
                }
            },
            "native",
            "1080p",
        )
        self.assertEqual(default_id, "native")
        self.assertEqual(
            profiles[profile_id],
            {
                "id": profile_id,
                "name": "Consultation mobile",
                "type": "transcode",
                "width": 854,
                "height": 480,
                "fps": 10.0,
                "bitrate_kbps": 200,
            },
        )

    def test_custom_profile_names_are_unique_case_insensitively(self):
        first = "0123456789abcdef0123456789abcdef"
        second = "1123456789abcdef0123456789abcdef"
        profiles = {
            first: {"name": "Mobile", "type": "transcode", "width": 854, "height": 480, "fps": 10, "bitrate_kbps": 200},
            second: {"name": " mobile ", "type": "transcode", "width": 640, "height": 360, "fps": 5, "bitrate_kbps": 100},
        }
        with self.assertRaises(CameraProfileError):
            normalize_camera_profiles(profiles, "native", "1080p")

    def test_native_name_is_reserved(self):
        profile_id = "0123456789abcdef0123456789abcdef"
        profiles = {
            profile_id: {"name": "NATIF", "type": "transcode", "width": 854, "height": 480, "fps": 10, "bitrate_kbps": 200}
        }
        with self.assertRaises(CameraProfileError):
            normalize_camera_profiles(profiles, "native", "1080p")

    def test_profile_cannot_upscale_beyond_native_quality(self):
        profile_id = "0123456789abcdef0123456789abcdef"
        profiles = {
            profile_id: {"name": "Full HD", "type": "transcode", "width": 1920, "height": 1080, "fps": 10, "bitrate_kbps": 400}
        }
        with self.assertRaises(CameraProfileError):
            normalize_camera_profiles(profiles, "native", "720p")

    def test_profile_dimensions_must_be_supported(self):
        profile_id = "0123456789abcdef0123456789abcdef"
        profiles = {
            profile_id: {"name": "Custom", "type": "transcode", "width": 1000, "height": 600, "fps": 10, "bitrate_kbps": 400}
        }
        with self.assertRaises(CameraProfileError):
            normalize_camera_profiles(profiles, "native", "1080p")

    def test_profile_frame_rate_and_bitrate_follow_engine_limits(self):
        profile_id = "0123456789abcdef0123456789abcdef"
        invalid_profiles = [
            {"name": "FPS", "type": "transcode", "width": 854, "height": 480, "fps": 12, "bitrate_kbps": 200},
            {"name": "Bitrate", "type": "transcode", "width": 854, "height": 480, "fps": 10, "bitrate_kbps": 20},
        ]
        for profile in invalid_profiles:
            with self.subTest(profile=profile):
                with self.assertRaises(CameraProfileError):
                    normalize_camera_profiles({profile_id: profile}, "native", "1080p")

    def test_only_native_can_be_default(self):
        with self.assertRaises(CameraProfileError):
            normalize_camera_profiles({}, "0123456789abcdef0123456789abcdef", "1080p")

    def test_invalid_profile_id_is_rejected(self):
        profiles = {
            "mobile": {"name": "Mobile", "type": "transcode", "width": 854, "height": 480, "fps": 10, "bitrate_kbps": 200}
        }
        with self.assertRaises(CameraProfileError):
            normalize_camera_profiles(profiles, "native", "1080p")


if __name__ == "__main__":
    unittest.main()
