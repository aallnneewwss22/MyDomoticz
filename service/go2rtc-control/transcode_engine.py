"""FFmpeg process adapter for on-demand per-camera H.264 transcoding."""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import json
from typing import Callable

LOGGER = logging.getLogger("go2rtc-control.transcode")
DEFAULT_RTSP_HOST = "127.0.0.1"
DEFAULT_RTSP_PORT = 8554
STARTUP_TIMEOUT_SECONDS = 20.0
STOP_TIMEOUT_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.25


class TranscodeEngineError(RuntimeError):
    """The FFmpeg producer could not be started, checked, or stopped."""


def output_stream_name(camera_id: str) -> str:
    return camera_id + "_transcode"


def build_ffmpeg_command(
    ffmpeg_bin: str,
    camera_id: str,
    profile: dict[str, object],
    *,
    rtsp_host: str = DEFAULT_RTSP_HOST,
    rtsp_port: int = DEFAULT_RTSP_PORT,
) -> list[str]:
    """Build an argv list; never pass camera-controlled data through a shell."""
    width = int(profile["width"])
    height = int(profile["height"])
    fps = float(profile["fps"])
    bitrate = int(profile["bitrate_kbps"])
    source = str(profile["source"])
    if source not in ("720p", "1080p"):
        raise TranscodeEngineError("Qualité native invalide.")
    if not camera_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for char in camera_id):
        raise TranscodeEngineError("Identifiant logique de caméra invalide.")
    if width <= 0 or height <= 0 or fps <= 0 or bitrate <= 0:
        raise TranscodeEngineError("Profil FFmpeg invalide.")
    gop = max(1, round(fps * 2))
    input_url = f"rtsp://{rtsp_host}:{rtsp_port}/{camera_id}?video"
    output_url = f"rtsp://{rtsp_host}:{rtsp_port}/{output_stream_name(camera_id)}"
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        f"setsar=1,fps={fps:g}"
    )
    return [
        ffmpeg_bin,
        "-hide_banner", "-nostdin", "-loglevel", "warning",
        "-fflags", "nobuffer", "-flags", "low_delay",
        "-rtsp_transport", "tcp", "-i", input_url,
        "-map", "0:v:0", "-an",
        "-vf", video_filter,
        "-c:v", "h264_v4l2m2m",
        "-b:v", f"{bitrate}k",
        "-maxrate", f"{bitrate}k",
        "-bufsize", f"{bitrate * 2}k",
        "-g", str(gop), "-keyint_min", str(gop),
        "-pix_fmt", "yuv420p",
        "-f", "rtsp", "-rtsp_transport", "tcp", output_url,
    ]


class FFmpegTranscodeEngine:
    """Own at most one FFmpeg process for each logical camera."""

    def __init__(
        self,
        *,
        ffmpeg_bin: str = "/usr/bin/ffmpeg",
        rtsp_host: str = DEFAULT_RTSP_HOST,
        rtsp_port: int = DEFAULT_RTSP_PORT,
        go2rtc_api: str = "http://127.0.0.1:1984",
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        startup_timeout: float = STARTUP_TIMEOUT_SECONDS,
    ) -> None:
        self.ffmpeg_bin = ffmpeg_bin
        self.rtsp_host = rtsp_host
        self.rtsp_port = rtsp_port
        self.go2rtc_api = go2rtc_api.rstrip("/")
        self._popen = popen
        self._clock = clock
        self._sleep = sleep
        self.startup_timeout = startup_timeout
        self._lock = threading.RLock()
        self._processes: dict[str, subprocess.Popen] = {}

    def _stream_visible(self, camera_id: str) -> bool:
        request = urllib.request.Request(self.go2rtc_api + "/api/streams", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        name = output_stream_name(camera_id)
        if isinstance(payload, dict):
            return name in payload
        if isinstance(payload, list):
            return any(isinstance(item, dict) and item.get("name") == name for item in payload)
        return False

    def available(self) -> bool:
        """Check FFmpeg's binary and the required hardware encoder declaration."""
        binary = shutil.which(self.ffmpeg_bin)
        if binary is None:
            return False
        try:
            result = subprocess.run(
                [binary, "-hide_banner", "-encoders"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=8, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0 and "h264_v4l2m2m" in result.stdout

    def start(self, camera_id: str, profile: dict[str, object]) -> bool:
        with self._lock:
            current = self._processes.get(camera_id)
            if current is not None and current.poll() is None:
                raise TranscodeEngineError("Un transcodeur existe déjà pour cette caméra.")
            if current is not None:
                self._processes.pop(camera_id, None)
            binary = shutil.which(self.ffmpeg_bin)
            if binary is None:
                raise TranscodeEngineError("Binaire FFmpeg introuvable.")
            command = build_ffmpeg_command(
                binary, camera_id, profile,
                rtsp_host=self.rtsp_host, rtsp_port=self.rtsp_port,
            )
            try:
                process = self._popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=None,
                    close_fds=True,
                )
            except OSError as exc:
                raise TranscodeEngineError("Impossible de lancer FFmpeg.") from exc
            self._processes[camera_id] = process

        deadline = self._clock() + self.startup_timeout
        while self._clock() < deadline:
            if process.poll() is not None:
                self.stop(camera_id)
                raise TranscodeEngineError("FFmpeg s'est arrêté pendant son initialisation.")
            if self._stream_visible(camera_id):
                return True
            self._sleep(POLL_INTERVAL_SECONDS)
        self.stop(camera_id)
        raise TranscodeEngineError("Le flux RTSP transcodé n'est pas apparu dans go2rtc.")

    def stop(self, camera_id: str) -> None:
        with self._lock:
            process = self._processes.pop(camera_id, None)
        if process is None:
            return
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=STOP_TIMEOUT_SECONDS)

    def health(self, camera_id: str) -> bool:
        with self._lock:
            process = self._processes.get(camera_id)
            return process is not None and process.poll() is None

    def close(self) -> None:
        with self._lock:
            camera_ids = list(self._processes)
        for camera_id in camera_ids:
            try:
                self.stop(camera_id)
            except Exception:
                LOGGER.exception("Échec de l'arrêt du transcodeur caméra %s.", camera_id)
