"""Two-stage FFmpeg adapter for on-demand per-camera H.264 transcoding."""
from __future__ import annotations

import json
import logging
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

LOGGER = logging.getLogger("go2rtc-control.transcode")
DEFAULT_RTSP_HOST = "127.0.0.1"
DEFAULT_RTSP_PORT = 8554
DEFAULT_UDP_HOST = "127.0.0.1"
STARTUP_TIMEOUT_SECONDS = 20.0
STOP_TIMEOUT_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.25
NATIVE_DIMENSIONS = {"720p": (1280, 720), "1080p": (1920, 1080)}


class TranscodeEngineError(RuntimeError):
    """The FFmpeg producer could not be started, checked, or stopped."""


def output_stream_name(camera_id: str) -> str:
    return camera_id + "_transcode"


def allocate_udp_port() -> int:
    """Ask the OS for an unused loopback UDP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind((DEFAULT_UDP_HOST, 0))
        return int(probe.getsockname()[1])


def build_ffmpeg_commands(
    ffmpeg_bin: str,
    camera_id: str,
    profile: dict[str, object],
    udp_port: int,
    *,
    rtsp_host: str = DEFAULT_RTSP_HOST,
    rtsp_port: int = DEFAULT_RTSP_PORT,
    udp_host: str = DEFAULT_UDP_HOST,
) -> tuple[list[str], list[str]]:
    """Build relay and encoder argv lists; never invoke a shell."""
    width = int(profile["width"])
    height = int(profile["height"])
    fps = float(profile["fps"])
    bitrate = int(profile["bitrate_kbps"])
    source = str(profile["source"])
    if source not in NATIVE_DIMENSIONS:
        raise TranscodeEngineError("Qualité native invalide.")
    if not camera_id or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
        for char in camera_id
    ):
        raise TranscodeEngineError("Identifiant logique de caméra invalide.")
    if width <= 0 or height <= 0 or fps <= 0 or bitrate <= 0:
        raise TranscodeEngineError("Profil FFmpeg invalide.")
    if isinstance(udp_port, bool) or not 1 <= udp_port <= 65535:
        raise TranscodeEngineError("Port UDP invalide.")

    gop = max(1, round(fps * 2))
    input_url = f"rtsp://{rtsp_host}:{rtsp_port}/{camera_id}?video"
    output_url = f"rtsp://{rtsp_host}:{rtsp_port}/{output_stream_name(camera_id)}"
    udp_url = f"udp://{udp_host}:{udp_port}"
    udp_input_url = f"{udp_url}?fifo_size=5000000&overrun_nonfatal=1"

    # Native dimensions bypass the expensive software scaler.
    if (width, height) == NATIVE_DIMENSIONS[source]:
        video_filter = f"fps={fps:g}"
    else:
        video_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1,fps={fps:g}"
        )

    relay_command = [
        ffmpeg_bin,
        "-hide_banner", "-nostdin", "-loglevel", "warning",
        "-i", udp_input_url,
        "-map", "0:v:0", "-an", "-c:v", "copy",
        "-f", "rtsp", "-rtsp_transport", "tcp", output_url,
    ]
    encoder_command = [
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
        "-flush_packets", "1",
        "-f", "mpegts", f"{udp_url}?pkt_size=1316",
    ]
    return relay_command, encoder_command


class FFmpegTranscodeEngine:
    """Own two FFmpeg processes and one temporary go2rtc destination per camera."""

    def __init__(
        self,
        *,
        ffmpeg_bin: str = "/usr/bin/ffmpeg",
        rtsp_host: str = DEFAULT_RTSP_HOST,
        rtsp_port: int = DEFAULT_RTSP_PORT,
        go2rtc_api: str = "http://127.0.0.1:1984",
        udp_host: str = DEFAULT_UDP_HOST,
        udp_port_allocator: Callable[[], int] = allocate_udp_port,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        startup_timeout: float = STARTUP_TIMEOUT_SECONDS,
    ) -> None:
        self.ffmpeg_bin = ffmpeg_bin
        self.rtsp_host = rtsp_host
        self.rtsp_port = rtsp_port
        self.go2rtc_api = go2rtc_api.rstrip("/")
        self.udp_host = udp_host
        self._udp_port_allocator = udp_port_allocator
        self._popen = popen
        self._clock = clock
        self._sleep = sleep
        self.startup_timeout = startup_timeout
        self._lock = threading.RLock()
        self._processes: dict[str, tuple[subprocess.Popen, subprocess.Popen]] = {}
        self._udp_ports: dict[str, int] = {}
        self._owned_streams: set[str] = set()

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

    def _stream_producers(self, camera_id: str) -> list[dict[str, object]] | None:
        """Return the producer records for this stream, or None if unreadable."""
        request = urllib.request.Request(self.go2rtc_api + "/api/streams", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        stream = payload.get(output_stream_name(camera_id)) if isinstance(payload, dict) else None
        if not isinstance(stream, dict):
            return None
        producers = stream.get("producers")
        if not isinstance(producers, list):
            return None
        return [item for item in producers if isinstance(item, dict)]

    def _stream_has_producer(self, camera_id: str) -> bool:
        """Only a real RTSP publisher means that the relay has attached."""
        producers = self._stream_producers(camera_id)
        return producers is not None and any(
            item.get("format_name") == "rtsp"
            and item.get("protocol") in ("rtsp+tcp", "rtsp+udp")
            for item in producers
        )

    def _stream_can_be_reclaimed(self, camera_id: str) -> bool:
        """Allow recovery only for an empty stream or our inert webrtc: placeholder."""
        producers = self._stream_producers(camera_id)
        if producers is None:
            return False
        return not producers or all(item.get("url") == "webrtc:" for item in producers)

    def _stream_has_placeholder(self, camera_id: str) -> bool:
        producers = self._stream_producers(camera_id)
        return producers is not None and any(
            item.get("url") == "webrtc:" for item in producers
        )

    def _create_output_stream(self, camera_id: str) -> None:
        """Register a publishable destination before starting the RTSP relay."""
        name = output_stream_name(camera_id)
        if self._stream_visible(camera_id):
            if not self._stream_can_be_reclaimed(camera_id):
                raise TranscodeEngineError(
                    "Le flux de destination existe déjà avec un producteur étranger ; refus de le remplacer."
                )
            self._delete_stream(camera_id)
        self._owned_streams.add(camera_id)
        query = urllib.parse.urlencode({"name": name, "src": "webrtc:"})
        request = urllib.request.Request(
            self.go2rtc_api + "/api/streams?" + query, method="PUT"
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                if not 200 <= response.status < 300:
                    raise TranscodeEngineError(
                        f"Création du flux de destination refusée (HTTP {response.status})."
                    )
            if not self._stream_visible(camera_id):
                raise TranscodeEngineError(
                    "Le flux de destination créé n'est pas visible dans go2rtc."
                )
            if not self._stream_has_placeholder(camera_id):
                raise TranscodeEngineError(
                    "Le flux de destination ne possède pas le producteur WebRTC d'attente attendu."
                )
        except urllib.error.HTTPError as exc:
            self._cleanup_failed_creation(camera_id)
            raise TranscodeEngineError(
                f"Création du flux de destination refusée (HTTP {exc.code})."
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self._cleanup_failed_creation(camera_id)
            raise TranscodeEngineError(
                "Impossible de créer le flux de destination dans go2rtc."
            ) from exc
        except TranscodeEngineError:
            self._cleanup_failed_creation(camera_id)
            raise

    def _cleanup_failed_creation(self, camera_id: str) -> None:
        try:
            self._delete_output_stream(camera_id)
        except TranscodeEngineError:
            LOGGER.exception(
                "Échec du nettoyage du flux de destination %s après une création incomplète.",
                output_stream_name(camera_id),
            )

    def _delete_stream(self, camera_id: str) -> None:
        query = urllib.parse.urlencode({"src": output_stream_name(camera_id)})
        request = urllib.request.Request(
            self.go2rtc_api + "/api/streams?" + query, method="DELETE"
        )
        try:
            with urllib.request.urlopen(request, timeout=8):
                pass
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise TranscodeEngineError(
                    f"Suppression du flux de destination refusée (HTTP {exc.code})."
                ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TranscodeEngineError(
                "Impossible de supprimer le flux de destination dans go2rtc."
            ) from exc

    def _delete_output_stream(self, camera_id: str) -> None:
        if camera_id not in self._owned_streams:
            return
        self._delete_stream(camera_id)
        self._owned_streams.discard(camera_id)

    def _reserve_udp_port(self, camera_id: str) -> int:
        for _ in range(20):
            port = int(self._udp_port_allocator())
            if 1 <= port <= 65535 and port not in self._udp_ports.values():
                self._udp_ports[camera_id] = port
                return port
        raise TranscodeEngineError("Impossible de réserver un port UDP local.")

    def _release_udp_port(self, camera_id: str) -> None:
        self._udp_ports.pop(camera_id, None)

    @staticmethod
    def _terminate_process(process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=STOP_TIMEOUT_SECONDS)

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
            if current is not None:
                if any(process.poll() is None for process in current):
                    raise TranscodeEngineError("Un transcodeur existe déjà pour cette caméra.")
                self._processes.pop(camera_id, None)
                self._release_udp_port(camera_id)
                self._delete_output_stream(camera_id)

            binary = shutil.which(self.ffmpeg_bin)
            if binary is None:
                raise TranscodeEngineError("Binaire FFmpeg introuvable.")

            udp_port = self._reserve_udp_port(camera_id)
            relay = None
            try:
                relay_command, encoder_command = build_ffmpeg_commands(
                    binary, camera_id, profile, udp_port,
                    rtsp_host=self.rtsp_host, rtsp_port=self.rtsp_port,
                    udp_host=self.udp_host,
                )
                self._create_output_stream(camera_id)
                relay = self._popen(
                    relay_command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=None,
                    close_fds=True,
                )
                encoder = self._popen(
                    encoder_command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=None,
                    close_fds=True,
                )
                self._processes[camera_id] = (relay, encoder)
            except Exception as exc:
                if relay is not None:
                    try:
                        self._terminate_process(relay)
                    except Exception:
                        LOGGER.exception("Échec de l'arrêt du relais FFmpeg caméra %s.", camera_id)
                try:
                    self._delete_output_stream(camera_id)
                except Exception:
                    LOGGER.exception("Échec du nettoyage du flux caméra %s.", camera_id)
                self._release_udp_port(camera_id)
                if isinstance(exc, TranscodeEngineError):
                    raise
                raise TranscodeEngineError("Impossible de démarrer les deux processus FFmpeg.") from exc

        deadline = self._clock() + self.startup_timeout
        while self._clock() < deadline:
            if relay.poll() is not None or encoder.poll() is not None:
                self.stop(camera_id)
                raise TranscodeEngineError(
                    "Un processus FFmpeg s'est arrêté pendant l'initialisation."
                )
            if self._stream_has_producer(camera_id):
                return True
            self._sleep(POLL_INTERVAL_SECONDS)
        self.stop(camera_id)
        raise TranscodeEngineError(
            "Le relais FFmpeg n'a pas publié de producteur RTSP dans go2rtc."
        )

    def stop(self, camera_id: str) -> None:
        with self._lock:
            processes = self._processes.pop(camera_id, None)
        errors: list[Exception] = []
        if processes is not None:
            relay, encoder = processes
            for process in (encoder, relay):
                try:
                    self._terminate_process(process)
                except Exception as exc:
                    errors.append(exc)
        try:
            self._delete_output_stream(camera_id)
        except Exception as exc:
            errors.append(exc)
        finally:
            with self._lock:
                self._release_udp_port(camera_id)
        if errors:
            raise TranscodeEngineError("Arrêt incomplet du moteur FFmpeg.") from errors[0]

    def health(self, camera_id: str) -> bool:
        with self._lock:
            processes = self._processes.get(camera_id)
            return processes is not None and all(
                process.poll() is None for process in processes
            )

    def close(self) -> None:
        with self._lock:
            camera_ids = set(self._processes) | set(self._owned_streams) | set(self._udp_ports)
        for camera_id in camera_ids:
            try:
                self.stop(camera_id)
            except Exception:
                LOGGER.exception("Échec de l'arrêt du moteur FFmpeg caméra %s.", camera_id)
