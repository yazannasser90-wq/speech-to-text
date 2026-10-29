# -*- coding: utf-8 -*-
"""
التسجيل من الميكروفون وتشغيل الصوت — يعتمد على sounddevice + soundfile.
الاستيراد كسول (Lazy) حتى يعمل باقي البرنامج حتى لو لم يوجد ميكروفون.
"""

import threading
import time

import numpy as np

SAMPLE_RATE = 16000  # المعدل الذي يتوقعه نموذج Whisper


class Recorder:
    """يسجّل من الميكروفون في الخلفية ويحتفظ بالصوت في الذاكرة."""

    def __init__(self, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self._chunks = []
        self._stream = None
        self._recording = False
        self._start_time = None
        self._last_level = 0.0
        self._lock = threading.Lock()

    # ---------- خصائص ----------
    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def elapsed(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    @property
    def level(self) -> float:
        """مستوى الصوت الحالي 0.0 - 1.0 (لعداد الصوت في الواجهة)"""
        return self._last_level

    @property
    def total_samples(self) -> int:
        with self._lock:
            return sum(len(c) for c in self._chunks)

    # ---------- التسجيل ----------
    def _callback(self, indata, frames, time_info, status):
        chunk = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
        with self._lock:
            self._chunks.append(chunk)
        # حساب مستوى الصوت (RMS) مع تضخيم بسيط للعرض
        rms = float(np.sqrt(np.mean(np.square(chunk)))) if len(chunk) else 0.0
        self._last_level = min(1.0, rms * 4)

    def start(self):
        import sounddevice as sd  # استيراد كسول

        if self._recording:
            return
        with self._lock:
            self._chunks = []
        self._last_level = 0.0
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()
        self._recording = True
        self._start_time = time.time()

    def stop(self) -> np.ndarray:
        """إيقاف التسجيل وإرجاع الصوت كاملًا كمصفوفة float32"""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
        self._recording = False
        self._last_level = 0.0
        return self.get_audio()

    def get_audio(self, from_sample: int = 0) -> np.ndarray:
        """إرجاع الصوت المسجل من نقطة معينة حتى الآن"""
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._chunks)
        if from_sample:
            audio = audio[from_sample:]
        return audio.astype(np.float32)

    def save_wav(self, path: str, audio: np.ndarray = None) -> str:
        import soundfile as sf

        if audio is None:
            audio = self.get_audio()
        sf.write(path, audio, self.sample_rate, subtype="PCM_16")
        return path


# ---------- تشغيل الملفات الصوتية ----------
_playing = {"stream": None}


def play_file(path: str):
    """تشغيل ملف صوتي (wav/mp3/ogg/flac بحسب دعم libsndfile)"""
    import sounddevice as sd
    import soundfile as sf

    stop_playback()
    data, sr = sf.read(path, dtype="float32", always_2d=False)
    sd.play(data, sr)
    _playing["stream"] = True


def stop_playback():
    try:
        import sounddevice as sd

        sd.stop()
    except Exception:
        pass
    _playing["stream"] = None


def list_input_devices():
    """قائمة أجهزة الإدخال المتاحة (الميكروفونات)"""
    import sounddevice as sd

    devices = []
    for i, d in enumerate(sd.query_devices()):
        if d.get("max_input_channels", 0) > 0:
            devices.append((i, d.get("name", f"Device {i}")))
    return devices
