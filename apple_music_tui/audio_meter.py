"""
Standalone audio metering module.  No imports from the rest of apple_music_tui.

Two operating modes, selected automatically by whether load() is called first:

Monitor mode  (default — what the TUI uses)
    AudioMeter().start() taps the system audio output via ScreenCaptureKit.
    Requires Screen Recording permission (System Settings → Privacy & Security).
    Works on macOS 12.3+.  Captures whatever is playing through the speakers,
    including Apple Music, without needing any extra software.

Playback mode  (used by tests)
    AudioMeter().load(path).start() plays the given audio file through an
    AVAudioEngine graph, taps the mixer node, and meters that audio.
    No Screen Recording permission needed.

Public API
----------
    meter = AudioMeter()
    meter.start()           # monitor system audio
    left, right = meter.levels  # RMS floats in [0.0, 1.0]
    meter.stop()

    # or as a context manager (start/stop handled automatically):
    with AudioMeter() as meter:
        time.sleep(0.5)          # let the stream warm up
        print(meter.levels)

PyObjC notes captured from implementation
------------------------------------------
- floatChannelData() on AVAudioPCMBuffer returns a tuple of objc.varlist.
  Index as fcd[ch][i].  Never call list() or iterate — varlist has no length.
- installTapOnBus:bufferSize:format:block: is callable_retained=False in PyObjC
  metadata, so keep self._tap_block alive or the GC will collect it immediately.
- initForReading:error: and startAndReturnError: return (result, error) tuples.
- ObjC completion-handler blocks must return None; lambdas with side-effects
  (e.g. comma expressions) return tuples and crash with OC_PythonException.
"""
from __future__ import annotations

import ctypes
import math
import struct
import threading
from typing import Tuple

# ---------------------------------------------------------------------------
# Optional framework imports (guarded so the module loads on non-macOS)
# ---------------------------------------------------------------------------

try:
    import objc
    from AVFoundation import AVAudioEngine, AVAudioFile, AVAudioPlayerNode
    from Foundation import NSObject, NSURL
    _PYOBJC_AVAILABLE = True
except ImportError:
    _PYOBJC_AVAILABLE = False
    NSObject = object  # type: ignore[assignment,misc]

try:
    import ScreenCaptureKit as _SCK
    import CoreMedia as _CM
    _SCK_AVAILABLE = True
except ImportError:
    _SCK_AVAILABLE = False

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Spectrum / ring-buffer configuration
# ---------------------------------------------------------------------------

FFT_SIZE = 2048            # samples per FFT window (~43 ms @ 48 kHz, 23 Hz bins)
RING_CAPACITY = 8192       # ~4x the FFT window, absorbs variable SCK buffer sizes
SPECTRUM_FMIN = 20.0       # lowest band edge (Hz)
SPECTRUM_FMAX = 16000.0    # highest band edge (Hz)
SPECTRUM_DB_FLOOR = -70.0  # dBFS mapped to band value 0.0
SPECTRUM_DB_CEIL = -10.0   # dBFS mapped to band value 1.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

def _rms(sum_sq: float, count: int) -> float:
    """Compute RMS amplitude, clamped to [0.0, 1.0]."""
    return min(1.0, math.sqrt(sum_sq / count)) if count else 0.0


class AudioMeterError(Exception):
    """Base class for audio meter errors."""

class AudioMeterNotAvailable(AudioMeterError):
    """Required framework (PyObjC / SCK) not importable."""

class AudioMeterEngineError(AudioMeterError):
    """AVAudioEngine failed to start."""

class AudioMeterFileError(AudioMeterError):
    """Audio file could not be opened."""

class AudioMeterPermissionError(AudioMeterError):
    """Screen Recording permission denied."""


# ---------------------------------------------------------------------------
# Ring buffer (raw samples for FFT)
# ---------------------------------------------------------------------------

class _RingBuffer:
    """Per-channel float ring buffer.

    Single-writer (the real-time audio callback, via :meth:`push`) and
    single-reader (the UI consumer thread, via :meth:`snapshot`).  A single
    lock guards both; the writer's critical section is just index assignments
    so it never blocks the audio thread meaningfully.
    """

    def __init__(self, capacity: int, channels: int = 2) -> None:
        self._cap = capacity
        self._chan = channels
        self._buf = [[0.0] * capacity for _ in range(channels)]
        self._write = 0
        self._filled = 0
        self._lock = threading.Lock()

    def push(self, channels) -> None:
        """Append per-channel samples.

        ``channels[c]`` is a sequence of float samples for channel ``c``.  All
        channels advance by the same count (the shortest channel's length);
        channel 0 is duplicated when a channel is missing (mono input).
        """
        if not channels:
            return
        n = min(len(ch) for ch in channels)
        if not n:
            return
        with self._lock:
            cap = self._cap
            w = self._write
            first = min(n, cap - w)  # samples before wrapping
            for c in range(self._chan):
                src = channels[c] if c < len(channels) else channels[0]
                buf = self._buf[c]
                buf[w:w + first] = src[:first]
                if n > first:
                    buf[:n - first] = src[first:n]
            self._write = (w + n) % cap
            self._filled = min(cap, self._filled + n)

    def snapshot(self, n: int):
        """Return the most recent *n* samples per channel in time order.

        Returns a list of per-channel lists, or ``None`` if fewer than *n*
        samples have been buffered.
        """
        with self._lock:
            if self._filled < n:
                return None
            start = (self._write - n) % self._cap
            out = []
            for c in range(self._chan):
                buf = self._buf[c]
                if start + n <= self._cap:
                    out.append(buf[start:start + n])
                else:
                    tail = self._cap - start
                    out.append(buf[start:] + buf[:n - tail])
            return out

    def reset(self) -> None:
        """Drop buffered samples so the next snapshot returns ``None``."""
        with self._lock:
            self._write = 0
            self._filled = 0


# ---------------------------------------------------------------------------
# SCStreamOutput delegate (monitor mode)
# Defined at module level — PyObjC needs to register it as an ObjC class.
# ---------------------------------------------------------------------------

if _PYOBJC_AVAILABLE and _SCK_AVAILABLE:
    class _SCKDelegate(NSObject):  # type: ignore[valid-type]
        """
        Receives audio sample buffers from an SCStream.

        Owns its own _levels list and _lock.  AudioMeter reads from these
        directly rather than passing shared references through the PyObjC
        bridge (which can cause GC issues with custom init selectors).
        """

        def init(self):
            self = objc.super(_SCKDelegate, self).init()
            if self is None:
                return None
            self._levels: list[float] = [0.0, 0.0]
            self._lock = threading.Lock()
            self._ring = _RingBuffer(RING_CAPACITY, 2)
            return self

        def stream_didOutputSampleBuffer_ofType_(self, stream, sample_buf, type_):
            try:
                if type_ != _SCK.SCStreamOutputTypeAudio:
                    return
                block_buf = _CM.CMSampleBufferGetDataBuffer(sample_buf)
                if not block_buf:
                    return
                total_len = _CM.CMBlockBufferGetDataLength(block_buf)
                if not total_len:
                    return
                raw_buf = (ctypes.c_uint8 * total_len)()
                # CMBlockBufferCopyDataBytes returns (OSStatus, dest_array) in PyObjC
                copy_status, _ = _CM.CMBlockBufferCopyDataBytes(block_buf, 0, total_len, raw_buf)
                if copy_status != 0:
                    return
                n_floats = total_len // 4
                if n_floats == 0:
                    return
                # Pass the ctypes array directly — avoids a full buffer copy
                floats = struct.unpack_from(f'{n_floats}f', raw_buf)
                # Interleaved stereo: L, R, L, R, …
                # Tuple step-slicing runs in C, splitting channels without a Python loop.
                left = floats[::2]
                right = floats[1::2]
                rms = [
                    _rms(sum(v * v for v in left), len(left)),
                    _rms(sum(v * v for v in right), len(right)),
                ]
                with self._lock:
                    self._levels[0] = rms[0]
                    self._levels[1] = rms[1]
                # Stash raw samples for the consumer-side FFT spectrum.
                self._ring.push([left, right])
            except Exception:
                pass  # never raise from a Core Audio / SCK callback thread


# ---------------------------------------------------------------------------
# AudioMeter
# ---------------------------------------------------------------------------

class AudioMeter:
    """
    Real-time stereo RMS meter.

    Monitor mode (no load() call — used by the TUI)::

        meter = AudioMeter()
        meter.start()              # blocks briefly while SCK permission is verified
        left, right = meter.levels # floats in [0.0, 1.0]
        meter.stop()

    Playback mode (load() first — used by tests)::

        meter = AudioMeter()
        meter.load("/path/to/track.wav")
        meter.start()
        time.sleep(1)
        print(meter.levels)
        meter.stop()
    """

    def __init__(self) -> None:
        self._levels: list[float] = [0.0, 0.0]
        self._lock = threading.Lock()

        # Raw-sample ring for the FFT spectrum (playback mode; monitor mode
        # uses the delegate's own ring).  Sample rate is set at start().
        self._ring = _RingBuffer(RING_CAPACITY, 2)
        self._sample_rate: int = 48000

        # Cached FFT tables, rebuilt when (FFT_SIZE, num_bands, rate) changes.
        self._window = None
        self._band_bins = None
        self._spec_cache_key: tuple | None = None

        # Playback-mode state
        self._file = None        # AVAudioFile
        self._engine = None      # AVAudioEngine
        self._player = None      # AVAudioPlayerNode
        self._tap_block = None   # strong ref (callable_retained=False in PyObjC)

        # Monitor-mode state
        self._stream = None      # SCStream
        self._delegate = None    # _SCKDelegate

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, path: str) -> "AudioMeter":
        """Open *path* as an AVAudioFile for playback-mode metering."""
        if not _PYOBJC_AVAILABLE:
            raise AudioMeterNotAvailable("PyObjC / AVFoundation not available")
        import os
        if not os.path.exists(path):
            raise AudioMeterFileError(f"File not found: {path!r}")
        url = NSURL.fileURLWithPath_(path)
        if not url:
            raise AudioMeterFileError(f"Cannot form URL for path: {path!r}")
        audio_file, _ = AVAudioFile.alloc().initForReading_error_(url, None)
        if not audio_file:
            raise AudioMeterFileError(f"Cannot open {path!r}: unsupported format")
        self._file = audio_file
        return self

    def start(self) -> None:
        """
        Start metering.

        If load() was called first, plays the file through AVAudioEngine.
        Otherwise, opens a ScreenCaptureKit stream to monitor system audio.
        Blocks until the stream is ready (up to 10 s).
        """
        if self._file is not None:
            self._start_playback()
        else:
            self._start_monitor()

    def stop(self) -> None:
        """Stop metering and reset levels to zero."""
        self._stop_playback()
        self._stop_monitor()
        with self._lock:
            self._levels[0] = 0.0
            self._levels[1] = 0.0
        self._ring.reset()

    @property
    def levels(self) -> Tuple[float, float]:
        """Current RMS levels as ``(left, right)`` in ``[0.0, 1.0]``."""
        if self._delegate is not None:
            with self._delegate._lock:
                return (self._delegate._levels[0], self._delegate._levels[1])
        with self._lock:
            return (self._levels[0], self._levels[1])

    def spectrum(
        self, num_bands: int = 24, sample_rate: int | None = None
    ) -> Tuple[list[float], list[float]]:
        """Instantaneous log-spaced magnitude spectrum per channel.

        Returns ``(left_bands, right_bands)``, each a list of ``num_bands``
        floats in ``[0.0, 1.0]``.  Computed on the calling (consumer) thread —
        never call this from an audio callback.  Returns zeros if numpy is
        unavailable or the ring has not yet buffered a full FFT window.
        """
        if not _NUMPY_AVAILABLE:
            return ([0.0] * num_bands, [0.0] * num_bands)
        ring = self._delegate._ring if self._delegate is not None else self._ring
        snap = ring.snapshot(FFT_SIZE)
        if snap is None:
            return ([0.0] * num_bands, [0.0] * num_bands)
        window, edges = self._spectrum_tables(num_bands, sample_rate or self._sample_rate)
        left = self._channel_bands(snap[0], window, edges)
        right = self._channel_bands(snap[1] if len(snap) > 1 else snap[0], window, edges)
        return (left, right)

    def _spectrum_tables(self, num_bands: int, sr: int):
        """Return cached (Hann window, log-spaced band->bin edges) for *sr*."""
        key = (FFT_SIZE, num_bands, sr)
        if self._spec_cache_key != key:
            self._window = np.hanning(FFT_SIZE)
            edges_hz = np.logspace(
                math.log10(SPECTRUM_FMIN),
                math.log10(min(SPECTRUM_FMAX, sr / 2.0)),
                num_bands + 1,
            )
            bins = np.round(edges_hz * FFT_SIZE / sr).astype(int)
            self._band_bins = np.clip(bins, 0, FFT_SIZE // 2)
            self._spec_cache_key = key
        return self._window, self._band_bins

    def _channel_bands(self, samples, window, edges) -> list[float]:
        """FFT one channel's samples into ``len(edges)-1`` normalized bands."""
        x = np.asarray(samples, dtype=np.float64) * window
        # Coherent-gain normalization: a full-scale sine peaks near 1.0 (0 dBFS).
        mag = np.abs(np.fft.rfft(x)) / (window.sum() * 0.5)
        bands: list[float] = []
        for i in range(len(edges) - 1):
            lo = int(edges[i])
            hi = max(int(edges[i + 1]), lo + 1)
            peak = float(mag[lo:hi].max())
            db = 20.0 * math.log10(peak + 1e-12)
            val = (db - SPECTRUM_DB_FLOOR) / (SPECTRUM_DB_CEIL - SPECTRUM_DB_FLOOR)
            bands.append(min(1.0, max(0.0, val)))
        return bands

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "AudioMeter":
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Monitor mode (ScreenCaptureKit)
    # ------------------------------------------------------------------

    def _start_monitor(self) -> None:
        if not _SCK_AVAILABLE:
            raise AudioMeterNotAvailable(
                "ScreenCaptureKit not available — install pyobjc-framework-ScreenCaptureKit"
            )
        if not _PYOBJC_AVAILABLE:
            raise AudioMeterNotAvailable("PyObjC not available")

        delegate = _SCKDelegate.alloc().init()

        # Step 1: request shareable content (triggers permission prompt if needed)
        content_ready = threading.Event()
        content_box: list = [None]

        def got_content(content, err) -> None:
            if err:
                content_box[0] = err
            else:
                content_box[0] = content
            content_ready.set()

        _SCK.SCShareableContent.getShareableContentWithCompletionHandler_(got_content)
        content_ready.wait(timeout=10)

        result = content_box[0]
        if result is None:
            raise AudioMeterEngineError("Timed out waiting for SCShareableContent")

        # Check if result is an error (NSError) rather than content
        if not hasattr(result, 'displays'):
            raise AudioMeterPermissionError(
                "Screen Recording permission denied — grant it in "
                "System Settings → Privacy & Security → Screen Recording"
            )

        displays = result.displays()
        if not displays:
            raise AudioMeterEngineError("No displays found for SCContentFilter")

        # Step 2: build audio-only stream
        filt = _SCK.SCContentFilter.alloc().initWithDisplay_excludingApplications_exceptingWindows_(
            displays[0], [], []
        )
        cfg = _SCK.SCStreamConfiguration.alloc().init()
        cfg.setCapturesAudio_(True)
        cfg.setExcludesCurrentProcessAudio_(False)  # capture all system audio
        cfg.setSampleRate_(48000)
        cfg.setChannelCount_(2)
        cfg.setWidth_(2)    # minimise video processing overhead
        cfg.setHeight_(2)

        stream = _SCK.SCStream.alloc().initWithFilter_configuration_delegate_(filt, cfg, None)
        ok, err = stream.addStreamOutput_type_sampleHandlerQueue_error_(
            delegate, _SCK.SCStreamOutputTypeAudio, None, None
        )
        if not ok:
            raise AudioMeterEngineError(f"addStreamOutput failed: {err}")

        # Step 3: start capture
        stream_ready = threading.Event()
        start_error: list = [None]

        def on_start(err) -> None:
            if err:
                start_error[0] = err
            stream_ready.set()

        stream.startCaptureWithCompletionHandler_(on_start)
        stream_ready.wait(timeout=10)
        if start_error[0]:
            raise AudioMeterEngineError(f"SCStream failed to start: {start_error[0]}")

        self._stream = stream
        self._delegate = delegate
        self._sample_rate = 48000

    def _stop_monitor(self) -> None:
        if self._stream is None:
            return
        stopped = threading.Event()
        def on_stop(err) -> None:
            stopped.set()
        self._stream.stopCaptureWithCompletionHandler_(on_stop)
        stopped.wait(timeout=5)
        self._stream = None
        self._delegate = None

    # ------------------------------------------------------------------
    # Playback mode (AVAudioEngine)
    # ------------------------------------------------------------------

    def _start_playback(self) -> None:
        if not _PYOBJC_AVAILABLE:
            raise AudioMeterNotAvailable("PyObjC / AVFoundation not available")

        engine = AVAudioEngine.alloc().init()
        player = AVAudioPlayerNode.alloc().init()
        engine.attachNode_(player)
        engine.connect_to_format_(player, engine.mainMixerNode(), None)

        success, _ = engine.startAndReturnError_(None)
        if not success:
            raise AudioMeterEngineError("AVAudioEngine failed to start")

        mixer = engine.mainMixerNode()
        tap_fmt = mixer.outputFormatForBus_(0)
        if tap_fmt is None or tap_fmt.sampleRate() == 0:
            tap_fmt = None
        else:
            # The tap delivers buffers in the mixer's output format, so the
            # spectrum must bin against that rate (not the source file's).
            self._sample_rate = int(tap_fmt.sampleRate())

        self._tap_block = self._make_tap_block()
        mixer.installTapOnBus_bufferSize_format_block_(0, 4096, tap_fmt, self._tap_block)

        player.scheduleFile_atTime_completionHandler_(self._file, None, None)
        player.play()
        self._engine = engine
        self._player = player

    def _stop_playback(self) -> None:
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:
                pass
        if self._engine is not None:
            try:
                self._engine.mainMixerNode().removeTapOnBus_(0)
            except Exception:
                pass
            try:
                self._engine.stop()
            except Exception:
                pass
        self._engine = None
        self._player = None
        self._tap_block = None

    def _make_tap_block(self):
        """
        AVAudioEngine tap callback for playback mode.

        floatChannelData() returns a tuple of objc.varlist — index with
        fcd[ch][i] bounded by frameLength().  Never iterate or list() it.
        """
        lock = self._lock
        levels = self._levels
        ring = self._ring

        def _tap(buffer, when) -> None:  # noqa: ARG001
            try:
                if buffer is None:
                    return
                n = int(buffer.frameLength())
                if not n:
                    return
                fcd = buffer.floatChannelData()
                if fcd is None:
                    return
                results: list[float] = []
                chan_samples: list[list[float]] = []
                for ch_data in fcd:
                    samples = [ch_data[i] for i in range(n)]
                    results.append(_rms(sum(v * v for v in samples), n))
                    chan_samples.append(samples)
                    if len(results) >= 2:
                        break
                if len(results) == 1:
                    results.append(results[0])
                elif not results:
                    results = [0.0, 0.0]
                with lock:
                    levels[0] = results[0]
                    levels[1] = results[1]
                # Stash raw samples for the consumer-side FFT spectrum.
                if chan_samples:
                    ring.push(chan_samples)
            except Exception:
                pass  # never raise from a Core Audio callback thread

        return _tap
