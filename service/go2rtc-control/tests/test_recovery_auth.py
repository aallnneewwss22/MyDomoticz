import json
import os
import tempfile
import unittest
from pathlib import Path

from recovery_auth import (
    KEY_PATTERN, RecoveryAuth, RecoveryRateLimited, RecoveryUnauthorized,
)


class RecoveryAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = 1000.0
        self.auth = RecoveryAuth(self.root / "state" / "recovery-key.json", clock=lambda: self.now)

    def tearDown(self):
        self.temp.cleanup()

    def test_generated_key_is_random_url_safe_and_only_verifier_is_persisted(self):
        key = self.auth.create_or_rotate_key()
        self.assertRegex(key, KEY_PATTERN)
        stored = self.auth.key_file.read_text(encoding="utf-8")
        self.assertNotIn(key, stored)
        data = json.loads(stored)
        self.assertEqual(data["version"], 1)
        self.assertEqual(len(bytes.fromhex(data["salt"])), 16)
        self.assertEqual(len(bytes.fromhex(data["digest"])), 32)
        self.assertEqual(os.stat(self.auth.key_file).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.auth.key_file.parent).st_mode & 0o777, 0o700)

    def test_valid_key_issues_opaque_session(self):
        key = self.auth.create_or_rotate_key()
        session = self.auth.issue_session(key, "192.0.2.10")
        self.assertNotEqual(session, key)
        self.assertTrue(self.auth.is_session_valid(session))

    def test_invalid_key_is_rejected(self):
        self.auth.create_or_rotate_key()
        with self.assertRaises(RecoveryUnauthorized):
            self.auth.issue_session("incorrect", "192.0.2.10")

    def test_missing_or_corrupt_verifier_fails_closed(self):
        with self.assertRaises(RecoveryUnauthorized):
            self.auth.issue_session("A" * 43, "192.0.2.10")
        self.auth.key_file.parent.mkdir()
        self.auth.key_file.write_text("{broken", encoding="utf-8")
        with self.assertRaises(RecoveryUnauthorized):
            self.auth.issue_session("A" * 43, "192.0.2.10")

    def test_attempts_are_rate_limited_per_client(self):
        self.auth.create_or_rotate_key()
        for _ in range(5):
            with self.assertRaises(RecoveryUnauthorized):
                self.auth.issue_session("A" * 43, "192.0.2.10")
        with self.assertRaises(RecoveryRateLimited):
            self.auth.issue_session("A" * 43, "192.0.2.10")
        # A different client has an independent allowance.
        with self.assertRaises(RecoveryUnauthorized):
            self.auth.issue_session("A" * 43, "192.0.2.11")

    def test_rate_limit_expires(self):
        self.auth.create_or_rotate_key()
        for _ in range(5):
            with self.assertRaises(RecoveryUnauthorized):
                self.auth.issue_session("A" * 43, "192.0.2.10")
        self.now += 301
        with self.assertRaises(RecoveryUnauthorized):
            self.auth.issue_session("A" * 43, "192.0.2.10")

    def test_session_expires_after_five_minutes(self):
        key = self.auth.create_or_rotate_key()
        session = self.auth.issue_session(key, "192.0.2.10")
        self.now += 299
        self.assertTrue(self.auth.is_session_valid(session))
        self.now += 1
        self.assertFalse(self.auth.is_session_valid(session))

    def test_rotation_invalidates_previous_key_and_all_sessions(self):
        first_key = self.auth.create_or_rotate_key()
        session = self.auth.issue_session(first_key, "192.0.2.10")
        second_key = self.auth.create_or_rotate_key()
        self.assertNotEqual(first_key, second_key)
        self.assertFalse(self.auth.is_session_valid(session))
        with self.assertRaises(RecoveryUnauthorized):
            self.auth.issue_session(first_key, "192.0.2.10")
        self.assertTrue(self.auth.is_session_valid(
            self.auth.issue_session(second_key, "192.0.2.10")
        ))

    def test_session_does_not_survive_service_restart(self):
        key = self.auth.create_or_rotate_key()
        session = self.auth.issue_session(key, "192.0.2.10")
        restarted = RecoveryAuth(self.auth.key_file, clock=lambda: self.now)
        self.assertFalse(restarted.is_session_valid(session))
        self.assertTrue(restarted.issue_session(key, "192.0.2.10"))

    def test_symlinked_verifier_is_rejected(self):
        key = self.auth.create_or_rotate_key()
        real_file = self.auth.key_file
        link_file = self.root / "linked-key.json"
        link_file.symlink_to(real_file)
        linked = RecoveryAuth(link_file, clock=lambda: self.now)
        with self.assertRaises(RecoveryUnauthorized):
            linked.issue_session(key, "192.0.2.10")
        with self.assertRaises(OSError):
            linked.create_or_rotate_key()

    def test_successful_authentication_clears_failed_attempt_counter(self):
        key = self.auth.create_or_rotate_key()
        for _ in range(4):
            with self.assertRaises(RecoveryUnauthorized):
                self.auth.issue_session("A" * 43, "192.0.2.10")
        self.auth.issue_session(key, "192.0.2.10")
        for _ in range(4):
            with self.assertRaises(RecoveryUnauthorized):
                self.auth.issue_session("A" * 43, "192.0.2.10")
        with self.assertRaises(RecoveryUnauthorized):
            self.auth.issue_session("A" * 43, "192.0.2.10")
        with self.assertRaises(RecoveryRateLimited):
            self.auth.issue_session("A" * 43, "192.0.2.10")

    def test_expired_sessions_are_purged(self):
        key = self.auth.create_or_rotate_key()
        session = self.auth.issue_session(key, "192.0.2.10")
        self.now += 301
        self.assertFalse(self.auth.is_session_valid(session))
        self.assertEqual(self.auth._sessions, {})

    def test_explicit_revocation(self):
        key = self.auth.create_or_rotate_key()
        session = self.auth.issue_session(key, "192.0.2.10")
        self.auth.revoke_sessions()
        self.assertFalse(self.auth.is_session_valid(session))


if __name__ == "__main__":
    unittest.main()
