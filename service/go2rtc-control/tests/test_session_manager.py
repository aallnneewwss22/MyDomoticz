"""Tests for shared transcoding session coordination."""
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from session_manager import (
    EXPIRATION_SWEEP_INTERVAL_SECONDS,
    HEARTBEAT_INTERVAL_SECONDS,
    SESSION_LEASE_SECONDS,
    SessionConflict,
    SessionError,
    SessionManager,
    SessionUnauthorized,
    SessionUnavailable,
)

PROFILE_1080 = {
    "source": "1080p", "width": 854, "height": 480,
    "fps": 10, "bitrate_kbps": 400,
}
PROFILE_720 = {
    "source": "720p", "width": 640, "height": 360,
    "fps": 5, "bitrate_kbps": 250,
}


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FakeProducer:
    def __init__(self):
        self.active = set()
        self.starts = []
        self.stops = []
        self.fail_start = False
        self.fail_stop = False

    def start(self, camera_id, profile):
        self.starts.append((camera_id, dict(profile)))
        if self.fail_start:
            return False
        self.active.add(camera_id)
        return True

    def stop(self, camera_id):
        self.stops.append(camera_id)
        if self.fail_stop:
            raise RuntimeError("stop failed")
        self.active.discard(camera_id)

    def health(self, camera_id):
        return camera_id in self.active


class SessionManagerTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.producer = FakeProducer()
        self.manager = SessionManager(
            self.producer.start, self.producer.stop, self.producer.health,
            clock=self.clock,
        )

    def test_timing_contract_is_explicit(self):
        self.assertEqual(HEARTBEAT_INTERVAL_SECONDS, 10)
        self.assertEqual(SESSION_LEASE_SECONDS, 60)
        self.assertEqual(EXPIRATION_SWEEP_INTERVAL_SECONDS, 5)

    def test_first_session_starts_one_producer(self):
        result = self.manager.acquire("salon", PROFILE_1080)
        self.assertEqual(result["result"], "started")
        self.assertTrue(self.producer.health("salon"))
        self.assertEqual(len(self.producer.starts), 1)
        self.assertEqual(self.manager.status("salon")["session_count"], 1)

    def test_identical_profile_joins_existing_producer(self):
        first = self.manager.acquire("salon", PROFILE_1080)
        second = self.manager.acquire("salon", PROFILE_1080)
        self.assertEqual(first["result"], "started")
        self.assertEqual(second["result"], "joined")
        self.assertEqual(len(self.producer.starts), 1)
        self.assertEqual(self.manager.status("salon")["session_count"], 2)

    def test_different_profile_conflicts_without_creating_session(self):
        self.manager.acquire("salon", PROFILE_1080)
        result = self.manager.acquire("salon", PROFILE_720)
        self.assertEqual(result["result"], "profile_conflict")
        self.assertEqual(result["active_profile"]["source"], "1080p")
        self.assertEqual(self.manager.status("salon")["session_count"], 1)
        self.assertEqual(len(self.producer.starts), 1)

    def test_accepting_active_profile_joins_shared_producer(self):
        self.manager.acquire("salon", PROFILE_1080)
        result = self.manager.acquire("salon", PROFILE_1080)
        self.assertEqual(result["result"], "joined")
        self.assertEqual(len(self.producer.starts), 1)

    def test_first_user_release_does_not_stop_producer_while_another_remains(self):
        first = self.manager.acquire("salon", PROFILE_1080)
        second = self.manager.acquire("salon", PROFILE_1080)
        self.manager.release("salon", first["session_id"], first["session_token"])
        self.assertTrue(self.producer.health("salon"))
        self.assertEqual(self.manager.status("salon")["session_count"], 1)
        self.assertEqual(self.producer.stops, [])
        self.manager.release("salon", second["session_id"], second["session_token"])
        self.assertFalse(self.producer.health("salon"))
        self.assertEqual(self.manager.status("salon")["state"], "idle")
        self.assertEqual(self.producer.stops, ["salon"])

    def test_heartbeat_renews_lease(self):
        session = self.manager.acquire("salon", PROFILE_1080)
        self.clock.advance(50)
        result = self.manager.heartbeat("salon", session["session_id"], session["session_token"])
        self.assertEqual(result, {"result": "renewed", "expires_in": 60})
        self.clock.advance(50)
        self.assertEqual(self.manager.cleanup_expired(), [])
        self.assertEqual(self.manager.status("salon")["session_count"], 1)

    def test_expiration_removes_last_session_and_stops_producer(self):
        self.manager.acquire("salon", PROFILE_1080)
        self.clock.advance(60)
        expired = self.manager.cleanup_expired()
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["camera_id"], "salon")
        self.assertEqual(self.manager.status("salon")["state"], "idle")
        self.assertFalse(self.producer.health("salon"))

    def test_heartbeat_after_expiration_cannot_resurrect_session(self):
        session = self.manager.acquire("salon", PROFILE_1080)
        self.clock.advance(60)
        result = self.manager.heartbeat("salon", session["session_id"], session["session_token"])
        self.assertEqual(result["result"], "session_expired")
        self.assertEqual(self.manager.status("salon")["session_count"], 0)

    def test_release_is_idempotent_for_unknown_session(self):
        result = self.manager.release("salon", "unknown", "irrelevant")
        self.assertEqual(result, {"result": "released", "session_count": 0})

    def test_wrong_token_is_rejected(self):
        session = self.manager.acquire("salon", PROFILE_1080)
        with self.assertRaises(SessionUnauthorized):
            self.manager.heartbeat("salon", session["session_id"], "wrong-token")

    def test_invalid_profile_is_rejected(self):
        invalid = dict(PROFILE_1080, fps=7)
        with self.assertRaises(SessionError):
            self.manager.acquire("salon", invalid)
        self.assertEqual(self.producer.starts, [])

    def test_failed_start_creates_no_session_and_returns_to_idle(self):
        self.producer.fail_start = True
        with self.assertRaises(SessionUnavailable):
            self.manager.acquire("salon", PROFILE_1080)
        self.assertEqual(self.manager.status("salon")["session_count"], 0)
        self.assertEqual(self.manager.status("salon")["state"], "idle")

    def test_failed_start_logs_original_exception(self):
        def failing_start(camera_id, profile):
            raise RuntimeError("diagnostic test failure")

        manager = SessionManager(
            failing_start, self.producer.stop, self.producer.health,
            clock=self.clock,
        )
        with self.assertLogs("go2rtc-control.sessions", level="ERROR") as captured:
            with self.assertRaises(SessionUnavailable):
                manager.acquire("salon", PROFILE_1080)

        output = "\n".join(captured.output)
        self.assertIn("Échec du démarrage du transcodeur", output)
        self.assertIn("diagnostic test failure", output)
        self.assertEqual(manager.status("salon")["state"], "idle")
        self.assertEqual(manager.status("salon")["session_count"], 0)

    def test_start_can_be_retried_after_a_clean_failure(self):
        self.producer.fail_start = True
        with self.assertRaises(SessionUnavailable):
            self.manager.acquire("salon", PROFILE_1080)
        self.producer.fail_start = False
        result = self.manager.acquire("salon", PROFILE_1080)
        self.assertEqual(result["result"], "started")
        self.assertEqual(self.manager.status("salon")["session_count"], 1)

    def test_failed_stop_keeps_profile_reserved_and_blocks_quality_change(self):
        session = self.manager.acquire("salon", PROFILE_1080)
        self.producer.fail_stop = True
        with self.assertRaises(SessionUnavailable):
            self.manager.release("salon", session["session_id"], session["session_token"])
        with self.assertRaises(SessionConflict):
            self.manager.assert_native_quality_change_allowed("salon")
        with self.assertRaises(SessionUnavailable):
            self.manager.acquire("salon", PROFILE_1080)

    def test_native_quality_change_allowed_only_when_idle(self):
        self.manager.assert_native_quality_change_allowed("salon")
        session = self.manager.acquire("salon", PROFILE_1080)
        with self.assertRaises(SessionConflict):
            self.manager.assert_native_quality_change_allowed("salon")
        self.manager.release("salon", session["session_id"], session["session_token"])
        self.manager.assert_native_quality_change_allowed("salon")

    def test_cameras_have_independent_producers_and_profiles(self):
        self.manager.acquire("salon", PROFILE_1080)
        self.manager.acquire("entree", PROFILE_720)
        self.assertEqual(len(self.producer.starts), 2)
        self.assertEqual(self.manager.status("salon")["active_profile"]["source"], "1080p")
        self.assertEqual(self.manager.status("entree")["active_profile"]["source"], "720p")

    def test_simultaneous_acquire_starts_only_one_producer(self):
        barrier = threading.Barrier(3)
        results = []
        errors = []

        def acquire():
            barrier.wait()
            try:
                results.append(self.manager.acquire("salon", PROFILE_1080))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=acquire) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=2)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(item["result"] for item in results), ["joined", "started"])
        self.assertEqual(len(self.producer.starts), 1)
        self.assertEqual(self.manager.status("salon")["session_count"], 2)

    def test_reaper_can_be_started_repeatedly_and_stopped(self):
        self.manager.start_reaper()
        first_thread = self.manager._reaper_thread
        self.manager.start_reaper()
        self.assertIs(self.manager._reaper_thread, first_thread)
        self.manager.close()
        self.assertFalse(first_thread.is_alive())

    def test_close_discards_future_acquire_requests(self):
        self.manager.close()
        with self.assertRaises(SessionUnavailable):
            self.manager.acquire("salon", PROFILE_1080)


if __name__ == "__main__":
    unittest.main()
