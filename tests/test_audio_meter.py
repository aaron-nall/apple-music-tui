"""
Tests for apple_music_tui.audio_meter.

Unit tests (no audio device required) run on all platforms.
Integration tests require PyObjC + AVFoundation and are skipped when absent.
They use a synthesised 440 Hz sine-wave WAV file so they don't depend on the
user's music library format.
"""
from __future__ import annotations

import asyncio
import math
import struct
import wave
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Check PyObjC availability once at import time (used by skipif markers).
# ---------------------------------------------------------------------------
try:
    import objc as _objc  # noqa: F401
    _PYOBJC_AVAILABLE = True
except ImportError:
    _PYOBJC_AVAILABLE = False


# ---------------------------------------------------------------------------
# Fixture: synthesise a stereo 440 Hz tone as a temporary WAV file
# ---------------------------------------------------------------------------

def _write_sine_wav(path: str, duration_s: float = 2.0, freq: float = 440.0,
                    sample_rate: int = 44100, amplitude: float = 0.5) -> None:
    """Write a stereo 16-bit PCM WAV containing a sine tone."""
    n_samples = int(sample_rate * duration_s)
    vals = [
        int(amplitude * 32767 * math.sin(2 * math.pi * freq * i / sample_rate))
        for i in range(n_samples)
    ]
    # Interleaved stereo (L, R, L, R, …) packed in one call
    data = struct.pack(f"<{n_samples * 2}h", *[v for v in vals for _ in range(2)])
    with wave.open(path, "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframesraw(data)


@pytest.fixture
def audio_file_path(tmp_path) -> str:
    path = str(tmp_path / "tone.wav")
    _write_sine_wav(path)
    return path


# ---------------------------------------------------------------------------
# Unit tests — no audio device, no PyObjC required
# ---------------------------------------------------------------------------

class TestAudioMeterUnit:
    def test_instantiation_does_not_crash(self):
        from apple_music_tui.audio_meter import AudioMeter
        meter = AudioMeter()
        assert meter is not None

    def test_levels_before_start_returns_zero(self):
        from apple_music_tui.audio_meter import AudioMeter
        meter = AudioMeter()
        assert meter.levels == (0.0, 0.0)

    def test_stop_before_start_is_safe(self):
        from apple_music_tui.audio_meter import AudioMeter
        meter = AudioMeter()
        meter.stop()  # must not raise

    def test_context_manager_calls_stop(self):
        from apple_music_tui.audio_meter import AudioMeter
        with AudioMeter() as meter:
            assert meter.levels == (0.0, 0.0)
        assert meter.levels == (0.0, 0.0)

    def test_start_without_load_uses_monitor_mode(self):
        # start() without load() should not raise — it enters SCK monitor mode.
        # If SCK isn't available it raises AudioMeterNotAvailable (still an
        # AudioMeterError), so we accept either outcome without crashing.
        from apple_music_tui.audio_meter import AudioMeter, AudioMeterError
        meter = AudioMeter()
        try:
            meter.start()
            meter.stop()
        except AudioMeterError:
            pass  # no SCK or no permission — acceptable in unit test environment

    def test_load_missing_file_raises(self):
        if not _PYOBJC_AVAILABLE:
            pytest.skip("PyObjC not available")
        from apple_music_tui.audio_meter import AudioMeter, AudioMeterFileError
        meter = AudioMeter()
        with pytest.raises(AudioMeterFileError):
            meter.load("/nonexistent/path/track.m4a")


# ---------------------------------------------------------------------------
# Integration tests — require PyObjC + a real audio file
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _PYOBJC_AVAILABLE, reason="PyObjC / AVFoundation not available")
class TestAudioMeterIntegration:
    async def test_levels_nonzero_during_playback(self, audio_file_path: str):
        from apple_music_tui.audio_meter import AudioMeter
        meter = AudioMeter()
        try:
            meter.load(audio_file_path)
            meter.start()
            # Allow the tap callback to fire for several render cycles.
            await asyncio.sleep(0.5)
            left, right = meter.levels
            assert left > 0.0 or right > 0.0, (
                f"Expected non-zero RMS after 500 ms playback, got ({left:.4f}, {right:.4f}). "
                f"File: {audio_file_path}"
            )
        finally:
            meter.stop()

    async def test_levels_return_to_zero_after_stop(self, audio_file_path: str):
        from apple_music_tui.audio_meter import AudioMeter
        meter = AudioMeter()
        try:
            meter.load(audio_file_path)
            meter.start()
            await asyncio.sleep(0.3)
        finally:
            meter.stop()
        assert meter.levels == (0.0, 0.0)

    async def test_levels_are_clamped_to_one(self, audio_file_path: str):
        from apple_music_tui.audio_meter import AudioMeter
        meter = AudioMeter()
        try:
            meter.load(audio_file_path)
            meter.start()
            await asyncio.sleep(0.5)
            left, right = meter.levels
            assert 0.0 <= left <= 1.0
            assert 0.0 <= right <= 1.0
        finally:
            meter.stop()

    async def test_context_manager_stops_on_exit(self, audio_file_path: str):
        from apple_music_tui.audio_meter import AudioMeter
        meter = AudioMeter()
        meter.load(audio_file_path)
        with meter:
            await asyncio.sleep(0.3)
        assert meter.levels == (0.0, 0.0)


# ---------------------------------------------------------------------------
# Monitor-mode integration tests — require SCK permission + external audio
# ---------------------------------------------------------------------------

try:
    import ScreenCaptureKit as _sck_check  # noqa: F401
    _SCK_AVAILABLE = True
except ImportError:
    _SCK_AVAILABLE = False


@pytest.mark.skipif(
    not _PYOBJC_AVAILABLE or not _SCK_AVAILABLE,
    reason="PyObjC / ScreenCaptureKit not available",
)
class TestAudioMeterMonitor:
    """
    These tests require:
    - Screen Recording permission granted to Terminal / the test runner
      (System Settings → Privacy & Security → Screen Recording)
    - Audio playing through the system speakers at test time
    """

    async def test_monitor_start_stop_does_not_crash(self):
        from apple_music_tui.audio_meter import AudioMeter, AudioMeterPermissionError
        meter = AudioMeter()
        try:
            meter.start()  # monitor mode (no load() call)
            await asyncio.sleep(0.1)
        except AudioMeterPermissionError:
            pytest.skip("Screen Recording permission not granted")
        finally:
            meter.stop()
        assert meter.levels == (0.0, 0.0)

    async def test_monitor_levels_clamped(self):
        from apple_music_tui.audio_meter import AudioMeter, AudioMeterPermissionError
        meter = AudioMeter()
        try:
            meter.start()
            await asyncio.sleep(0.5)
            left, right = meter.levels
            assert 0.0 <= left <= 1.0
            assert 0.0 <= right <= 1.0
        except AudioMeterPermissionError:
            pytest.skip("Screen Recording permission not granted")
        finally:
            meter.stop()
