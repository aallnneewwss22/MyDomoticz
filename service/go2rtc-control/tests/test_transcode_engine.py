"""Unit tests for the two-stage FFmpeg transcode process adapter."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
import urllib.parse
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transcode_engine import (
    FFmpegTranscodeEngine,
    TranscodeEngineError,
    build_ffmpeg_commands,
    output_stream_name,
)

PROFILE = {
    "source": "1080p", "width": 1920, "height": 1080,
    "fps": 10.0, "bitrate_kbps": 400,
}


class FakeProcess:
    def __init__(self, exit_code=None, label="process", events=None):
        self.exit_code = exit_code
        self.label = label
        self.events = events if events is not None else []
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.events.append(self.label + "-stop")
        self.terminated = True
        self.exit_code = 0

    def kill(self):
        self.events.append(self.label + "-kill")
        self.killed = True
        self.exit_code = -9

    def wait(self, timeout=None):
        self.waited = True
        if self.exit_code is None:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        return self.exit_code


class BuildCommandTests(unittest.TestCase):
    def commands(self, profile=PROFILE):
        return build_ffmpeg_commands(
            "/usr/bin/ffmpeg", "salon", profile, 12345
        )

    def test_native_resolution_uses_only_fps_filter(self):
        relay, encoder = self.commands()
        self.assertEqual(encoder[encoder.index("-vf") + 1], "fps=10")
        self.assertNotIn("scale=", " ".join(encoder))
        self.assertIn("h264_v4l2m2m", encoder)
        self.assertEqual(encoder[encoder.index("-map") + 1], "0:v:0")
        self.assertIn("-an", encoder)

    def test_encoder_reads_local_native_video_only_source(self):
        _relay, encoder = self.commands()
        joined = " ".join(encoder)
        self.assertIn("rtsp://127.0.0.1:8554/salon?video", joined)
        self.assertIn("-an", encoder)

    def test_encoder_uses_hardware_bitrate_and_two_second_gop(self):
        _relay, encoder = self.commands()
        self.assertEqual(encoder[encoder.index("-b:v") + 1], "400k")
        self.assertEqual(encoder[encoder.index("-maxrate") + 1], "400k")
        self.assertEqual(encoder[encoder.index("-bufsize") + 1], "800k")
        self.assertEqual(encoder[encoder.index("-g") + 1], "20")
        self.assertEqual(encoder[encoder.index("-keyint_min") + 1], "20")

    def test_encoder_sends_mpegts_to_local_udp(self):
        _relay, encoder = self.commands()
        self.assertIn("-flush_packets", encoder)
        self.assertIn("-f", encoder)
        self.assertEqual(encoder[encoder.index("-f") + 1], "mpegts")
        self.assertTrue(encoder[-1].startswith("udp://127.0.0.1:12345?pkt_size=1316"))

    def test_relay_receives_udp_and_publishes_rtsp_copy(self):
        relay, _encoder = self.commands()
        joined = " ".join(relay)
        self.assertIn("udp://127.0.0.1:12345?fifo_size=5000000&overrun_nonfatal=1", joined)
        self.assertEqual(relay[relay.index("-c:v") + 1], "copy")
        self.assertEqual(relay[relay.index("-f") + 1], "rtsp")
        self.assertIn("rtsp://127.0.0.1:8554/salon_transcode", joined)
        self.assertIn("-an", relay)

    def test_non_native_resolution_retains_scale_and_pad(self):
        profile = dict(PROFILE, width=854, height=480)
        _relay, encoder = self.commands(profile)
        video_filter = encoder[encoder.index("-vf") + 1]
        self.assertIn("scale=854:480", video_filter)
        self.assertIn("pad=854:480", video_filter)
        self.assertIn("fps=10", video_filter)

    def test_fractional_fps_produces_minimum_one_frame_gop(self):
        profile = dict(PROFILE, fps=0.2)
        _relay, encoder = self.commands(profile)
        self.assertIn("fps=0.2", encoder[encoder.index("-vf") + 1])
        self.assertEqual(encoder[encoder.index("-g") + 1], "1")

    def test_invalid_camera_id_and_udp_port_are_rejected(self):
        with self.assertRaises(TranscodeEngineError):
            build_ffmpeg_commands("/usr/bin/ffmpeg", "../salon", PROFILE, 12345)
        with self.assertRaises(TranscodeEngineError):
            build_ffmpeg_commands("/usr/bin/ffmpeg", "salon", PROFILE, 0)

    def test_stream_name_is_deterministic(self):
        self.assertEqual(output_stream_name("salon"), "salon_transcode")


class Go2rtcProducerDetectionTests(unittest.TestCase):
    def make_engine(self):
        return FFmpegTranscodeEngine()

    @patch("transcode_engine.urllib.request.urlopen")
    def test_creation_uses_inert_webrtc_source(self, urlopen):
        response = MagicMock()
        response.status = 200
        urlopen.return_value.__enter__.return_value = response
        engine = self.make_engine()
        visibility_checks = iter((False, True))
        engine._stream_visible = lambda camera_id: next(visibility_checks)
        engine._stream_has_placeholder = lambda camera_id: True

        engine._create_output_stream("salon")

        request = urlopen.call_args.args[0]
        query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
        self.assertEqual(request.get_method(), "PUT")
        self.assertEqual(query["name"], ["salon_transcode"])
        self.assertEqual(query["src"], ["webrtc:"])
        self.assertIn("salon", engine._owned_streams)

    @patch("transcode_engine.urllib.request.urlopen")
    def test_webrtc_placeholder_is_not_reported_as_ffmpeg_producer(self, urlopen):
        payload = {
            "salon_transcode": {
                "producers": [{"url": "webrtc:"}],
                "consumers": [],
            }
        }
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        urlopen.return_value = response

        engine = self.make_engine()
        self.assertFalse(engine._stream_has_producer("salon"))
        self.assertTrue(engine._stream_has_placeholder("salon"))
        self.assertTrue(engine._stream_can_be_reclaimed("salon"))

    @patch("transcode_engine.urllib.request.urlopen")
    def test_rtsp_tcp_publisher_is_detected_as_ffmpeg_producer(self, urlopen):
        payload = {
            "salon_transcode": {
                "producers": [
                    {"url": "webrtc:"},
                    {"format_name": "rtsp", "protocol": "rtsp+tcp", "id": "relay-1"},
                ],
                "consumers": [],
            }
        }
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        urlopen.return_value = response

        engine = self.make_engine()
        self.assertTrue(engine._stream_has_producer("salon"))
        self.assertTrue(engine._stream_has_placeholder("salon"))
        self.assertFalse(engine._stream_can_be_reclaimed("salon"))

    @patch("transcode_engine.urllib.request.urlopen")
    def test_foreign_producer_prevents_destination_reclamation(self, urlopen):
        payload = {
            "salon_transcode": {
                "producers": [{"url": "rtsp://other-source/stream"}],
                "consumers": [],
            }
        }
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        urlopen.return_value = response

        self.assertFalse(self.make_engine()._stream_can_be_reclaimed("salon"))

    @patch("transcode_engine.urllib.request.urlopen")
    def test_empty_stale_destination_can_be_reclaimed(self, urlopen):
        payload = {"salon_transcode": {"producers": [], "consumers": []}}
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        urlopen.return_value = response

        self.assertTrue(self.make_engine()._stream_can_be_reclaimed("salon"))


class EngineLifecycleTests(unittest.TestCase):
    def make_engine(self, processes, events):
        def popen(command, **_options):
            if "copy" in command:
                events.append("relay-start")
                return processes[0]
            events.append("encoder-start")
            return processes[1]

        engine = FFmpegTranscodeEngine(
            ffmpeg_bin="/usr/bin/ffmpeg",
            popen=popen,
            udp_port_allocator=lambda: 12345,
            startup_timeout=0.1,
            sleep=lambda _delay: None,
        )
        owned = set()

        def create_stream(camera_id):
            events.append("stream-create")
            owned.add(camera_id)

        def delete_stream(camera_id):
            if camera_id in owned:
                events.append("stream-delete")
                owned.remove(camera_id)

        engine._create_output_stream = create_stream
        engine._delete_output_stream = delete_stream
        engine._stream_has_producer = lambda _camera_id: True
        return engine

    @patch("transcode_engine.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_start_starts_relay_before_encoder_and_stop_reverses_order(self, _which):
        events = []
        relay = FakeProcess(label="relay", events=events)
        encoder = FakeProcess(label="encoder", events=events)
        engine = self.make_engine([relay, encoder], events)

        self.assertTrue(engine.start("salon", PROFILE))
        self.assertEqual(events, ["stream-create", "relay-start", "encoder-start"])
        self.assertTrue(engine.health("salon"))

        engine.stop("salon")
        self.assertTrue(encoder.terminated)
        self.assertTrue(relay.terminated)
        self.assertFalse(engine.health("salon"))
        self.assertEqual(
            events,
            [
                "stream-create", "relay-start", "encoder-start",
                "encoder-stop", "relay-stop", "stream-delete",
            ],
        )

    @patch("transcode_engine.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_start_rejects_a_second_process_pair_for_same_camera(self, _which):
        events = []
        engine = self.make_engine(
            [FakeProcess(label="relay", events=events),
             FakeProcess(label="encoder", events=events)],
            events,
        )
        engine.start("salon", PROFILE)
        with self.assertRaises(TranscodeEngineError):
            engine.start("salon", PROFILE)

    @patch("transcode_engine.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_start_cleans_relay_if_encoder_exits_during_startup(self, _which):
        events = []
        relay = FakeProcess(label="relay", events=events)
        encoder = FakeProcess(exit_code=1, label="encoder", events=events)
        engine = self.make_engine([relay, encoder], events)
        with self.assertRaises(TranscodeEngineError):
            engine.start("salon", PROFILE)
        self.assertTrue(relay.terminated)
        self.assertFalse(engine.health("salon"))
        self.assertEqual(events[-2:], ["relay-stop", "stream-delete"])
        self.assertNotIn("salon", engine._udp_ports)

    @patch("transcode_engine.shutil.which", return_value=None)
    def test_start_fails_cleanly_when_ffmpeg_is_missing(self, _which):
        events = []
        engine = self.make_engine(
            [FakeProcess(), FakeProcess()], events
        )
        with self.assertRaises(TranscodeEngineError):
            engine.start("salon", PROFILE)
        self.assertEqual(events, [])

    @patch("transcode_engine.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_stop_is_idempotent(self, _which):
        events = []
        engine = self.make_engine(
            [FakeProcess(label="relay", events=events),
             FakeProcess(label="encoder", events=events)],
            events,
        )
        engine.start("salon", PROFILE)
        engine.stop("salon")
        engine.stop("salon")
        self.assertEqual(events.count("stream-delete"), 1)
        self.assertNotIn("salon", engine._udp_ports)



    @patch("transcode_engine.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_encoder_launch_exception_stops_relay_and_cleans_resources(self, _which):
        events = []
        relay = FakeProcess(label="relay", events=events)
        owned = set()

        def popen(command, **_options):
            if "copy" in command:
                events.append("relay-start")
                return relay
            events.append("encoder-launch-failed")
            raise OSError("simulated encoder launch failure")

        engine = FFmpegTranscodeEngine(
            ffmpeg_bin="/usr/bin/ffmpeg",
            popen=popen,
            udp_port_allocator=lambda: 12345,
        )

        def create_stream(camera_id):
            events.append("stream-create")
            owned.add(camera_id)

        def delete_stream(camera_id):
            if camera_id in owned:
                events.append("stream-delete")
                owned.remove(camera_id)

        engine._create_output_stream = create_stream
        engine._delete_output_stream = delete_stream

        with self.assertRaises(TranscodeEngineError):
            engine.start("salon", PROFILE)

        self.assertTrue(relay.terminated)
        self.assertIn("relay-stop", events)
        self.assertEqual(events[-1], "stream-delete")
        self.assertNotIn("salon", engine._udp_ports)
        self.assertFalse(engine.health("salon"))
        self.assertNotIn("salon", owned)

    def test_udp_port_allocator_retries_a_port_already_in_use_by_engine(self):
        ports = iter((12345, 12345, 12346))
        engine = FFmpegTranscodeEngine(
            udp_port_allocator=lambda: next(ports)
        )

        self.assertEqual(engine._reserve_udp_port("salon"), 12345)
        self.assertEqual(engine._reserve_udp_port("cuisine"), 12346)
        self.assertEqual(engine._udp_ports, {"salon": 12345, "cuisine": 12346})

if __name__ == "__main__":
    unittest.main()
