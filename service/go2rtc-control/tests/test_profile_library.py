import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from profile_library import (
    PROFILE_LIBRARY_FORMAT,
    ProfileLibraryError,
    delete_profile_library_entry,
    list_profile_library,
    profile_library_filename,
    read_profile_library_entry,
    save_profile_library_entry,
)


PROFILE = {
    "name": "Équilibré",
    "width": 1280,
    "height": 720,
    "fps": 10,
    "bitrate_kbps": 400,
}


class ProfileLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_filename_is_derived_safely_from_profile_name(self):
        self.assertEqual(profile_library_filename("Équilibré"), "equilibre.json")
        with self.assertRaises(ProfileLibraryError):
            profile_library_filename("../secret")

    def test_save_and_read_profile_use_common_library_format(self):
        saved = save_profile_library_entry(self.directory, PROFILE)
        self.assertEqual(saved["filename"], "equilibre.json")
        path = self.directory / saved["filename"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["format"], PROFILE_LIBRARY_FORMAT)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["profile"]["name"], "Équilibré")
        loaded = read_profile_library_entry(self.directory, saved["filename"])
        self.assertEqual(loaded["profile"], saved["profile"])

    def test_list_returns_only_profile_metadata(self):
        save_profile_library_entry(self.directory, PROFILE)
        entries = list_profile_library(self.directory)
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["valid"])
        self.assertEqual(entries[0]["name"], "Équilibré")

    def test_existing_entry_requires_explicit_overwrite(self):
        save_profile_library_entry(self.directory, PROFILE)
        with self.assertRaises(FileExistsError):
            save_profile_library_entry(self.directory, PROFILE)
        replacement = dict(PROFILE, bitrate_kbps=600)
        save_profile_library_entry(self.directory, replacement, overwrite=True)
        self.assertEqual(
            read_profile_library_entry(self.directory, "equilibre.json")["profile"]["bitrate_kbps"],
            600,
        )

    def test_filename_collision_between_different_names_is_rejected(self):
        save_profile_library_entry(self.directory, PROFILE)
        with self.assertRaises(ProfileLibraryError):
            save_profile_library_entry(
                self.directory, dict(PROFILE, name="Equilibre"), overwrite=True
            )

    def test_invalid_profile_values_are_rejected(self):
        with self.assertRaises(ProfileLibraryError):
            save_profile_library_entry(self.directory, dict(PROFILE, width=1111))

    def test_corrupt_entry_is_listed_as_invalid_and_can_be_deleted(self):
        path = self.directory / "corrupt.json"
        path.write_text("{", encoding="utf-8")
        entries = list_profile_library(self.directory)
        self.assertEqual(entries, [{"filename": "corrupt.json", "name": "corrupt", "valid": False}])
        delete_profile_library_entry(self.directory, "corrupt.json")
        self.assertFalse(path.exists())

    def test_path_traversal_and_symlinks_are_rejected(self):
        with self.assertRaises(ProfileLibraryError):
            read_profile_library_entry(self.directory, "../outside.json")
        outside = self.directory / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        link = self.directory / "link.json"
        link.symlink_to(outside)
        with self.assertRaises(FileNotFoundError):
            read_profile_library_entry(self.directory, "link.json")


if __name__ == "__main__":
    unittest.main()
