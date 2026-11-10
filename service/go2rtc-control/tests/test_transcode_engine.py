"""Unit tests for the FFmpeg transcode process adapter."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transcode_engine import (
    FFmpegTranscodeEngine,
    TranscodeEngineError,
    build_ffmpeg_command,
    output_stream_name,
)

PROFILE = {
    "source": "1080p", "width": 854, "height": 480,
    "fps": 10.0, "bitrate_kbps": 400,
}


class FakeProcess:
    def __init__(self, exit_code=None):
        self.exit_code = exit_code
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True
        self.exit_code = 0

    def kill(self):
        self.killed = True
        self.exit_code = -9

    def wait(self, timeout=None):
        self.waited = True
        if self.exit_code is None:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        return self.exit_code


class BuildCommandTests(unittest.TestCase):
    def test_command_uses_local_native_and_output_rtsp_paths(self):
        command = build_ffmpeg_command("/usr/bin/ffmpeg", "salon", PROFILE)
        joined = " ".join(command)
        self.assertIn("rtsp://127.0.0.1:8554/salon?video", joined)
        self.assertIn("rtsp://127.0.0.1:8554/salon_transcode", joined)

    def test_command_disables_audio_and_uses_hardware_h264(self):
        command = build_ffmpeg_command("/usr/bin/ffmpeg", "salon", PROFILE)
        self.assertIn("-an", command)
        self.assertIn("h264_v4l2m2m", command)
        self.assertEqual(command[command.index("-map") + 1], "0:v:0")

    def test_command_applies_resolution_fps_bitrate_and_two_second_gop(self):
        command = build_ffmpeg_command("/usr/bin/ffmpeg", "salon", PROFILE)
        video_filter = command[command.index("-vf") + 1]
        self.assertIn("scale=854:480", video_filter)
        self.assertIn("fps=10", video_filter)
        self.assertEqual(command[command.index("-b:v") + 1], "400k")
        self.assertEqual(command[command.index("-g") + 1], "20")

    def test_fractional_fps_produces_minimum_one_frame_gop(self):
        profile = dict(PROFILE, fps=0.2)
        command = build_ffmpeg_command("/usr/bin/ffmpeg", "salon", profile)
        self.assertIn("fps=0.2", command[command.index("-vf") + 1])
        self.assertEqual(command[command.index("-g") + 1], "1")

    def test_stream_name_is_deterministic(self):
        self.assertEqual(output_stream_name("salon"), "salon_transcode")

    def test_invalid_camera_id_is_rejected(self):
        with self.assertRaises(TranscodeEngineError):
            build_ffmpeg_command("/usr/bin/ffmpeg", "../salon", PROFILE)


class EngineLifecycleTests(unittest.TestCase):
    def make_engine(self, process, **kwargs):
        events = []
        engine = FFmpegTranscodeEngine(
            ffmpeg_bin="/usr/bin/ffmpeg",
            popen=lambda *args, **options: (events.append("ffmpeg-start"), process)[1],
            startup_timeout=0.1,
            sleep=lambda delay: None,
            **kwargs,
        )
        engine._create_output_stream = lambda camera_id: events.append("stream-create")
        engine._delete_output_stream = lambda camera_id: events.append("stream-delete")
        engine._stream_has_producer = lambda camera_id: True
        engine.test_events = events
        return engine

    @patch("transcode_engine.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_start_creates_destination_before_ffmpeg_and_deletes_after_stop(self, _which):
        process = FakeProcess()
        engine = self.make_engine(process)
        self.assertTrue(engine.start("salon", PROFILE))
        self.assertEqual(engine.test_events, ["stream-create", "ffmpeg-start"])
        self.assertTrue(engine.health("salon"))
        engine.stop("salon")
        self.assertTrue(process.terminated)
        self.assertTrue(process.waited)
        self.assertFalse(engine.health("salon"))
        self.assertEqual(
            engine.test_events, ["stream-create", "ffmpeg-start", "stream-delete"]
        )

    @patch("transcode_engine.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_start_rejects_a_second_process_for_same_camera(self, _which):
        process = FakeProcess()
        engine = self.make_engine(process)
        engine.start("salon", PROFILE)
        with self.assertRaises(TranscodeEngineError):
            engine.start("salon", PROFILE)

    @patch("transcode_engine.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_start_fails_if_ffmpeg_exits_before_stream_is_ready(self, _which):
        process = FakeProcess(exit_code=1)
        engine = self.make_engine(process)
        engine._stream_has_producer = lambda camera_id: False
        with self.assertRaises(TranscodeEngineError):
            engine.start("salon", PROFILE)
        self.assertFalse(engine.health("salon"))
        self.assertEqual(
            engine.test_events, ["stream-create", "ffmpeg-start", "stream-delete"]
        )

    @patch("transcode_engine.shutil.which", return_value=None)
    def test_start_fails_cleanly_when_ffmpeg_is_missing(self, _which):
        engine = self.make_engine(FakeProcess())
        with self.assertRaises(TranscodeEngineError):
            engine.start("salon", PROFILE)
        self.assertEqual(engine.test_events, [])

    @patch("transcode_engine.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_stop_is_idempotent(self, _which):
        process = FakeProcess()
        engine = self.make_engine(process)
        engine.start("salon", PROFILE)
        engine.stop("salon")
        engine.stop("salon")
        self.assertTrue(process.terminated)
        self.assertEqual(engine.test_events.count("stream-delete"), 1)


if __name__ == "__main__":
    unittest.main()
