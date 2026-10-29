# -*- coding: utf-8 -*-
"""
محرك تحويل الصوت إلى نص (Speech-to-Text Engine)
يعتمد على مكتبة faster-whisper التي تعمل محليًا على الجهاز بدون إنترنت.
يدعم العربية والإنجليزية وأكثر من 90 لغة أخرى، مع اكتشاف تلقائي للغة.
"""

import threading


# معلومات النماذج المتاحة: الحجم التقريبي عند التنزيل + ملاحظة للمستخدم
MODELS = {
    "tiny":   {"size": "75 MB",   "note": "الأسرع — دقة منخفضة (للتجربة فقط)"},
    "base":   {"size": "145 MB",  "note": "سريع — دقة متوسطة"},
    "small":  {"size": "490 MB",  "note": "توازن ممتاز بين السرعة والدقة (موصى به)"},
    "medium": {"size": "1.5 GB",  "note": "دقة عالية جدًا — يحتاج جهازًا قويًا ووقتًا أطول"},
}

# أكواد اللغات الشائعة (Whisper يدعم لغات أكثر من ذلك بكثير)
LANGUAGES = {
    None: "اكتشاف تلقائي",
    "ar": "العربية",
    "en": "English",
}


def format_timestamp(seconds: float) -> str:
    """تحويل الثواني إلى صيغة 00:01:23"""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _srt_timestamp(seconds: float) -> str:
    ms = int(round((seconds - int(seconds)) * 1000))
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments) -> str:
    """تحويل المقاطع إلى ملف ترجمة SRT"""
    lines = []
    for i, seg in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(f"{_srt_timestamp(seg['start'])} --> {_srt_timestamp(seg['end'])}")
        lines.append(seg["text"].strip())
        lines.append("")
    return "\n".join(lines)


def segments_to_text(segments, with_timestamps: bool = False) -> str:
    """دمج المقاطع في نص واحد (اختياريًا مع الطوابع الزمنية)"""
    if with_timestamps:
        return "\n".join(
            f"[{format_timestamp(seg['start'])}] {seg['text'].strip()}"
            for seg in segments
        )
    return " ".join(seg["text"].strip() for seg in segments).strip()


class Transcriber:
    """
    غلاف (Wrapper) حول faster-whisper.
    النموذج يُحمّل مرة واحدة عند أول استخدام ويُعاد استخدامه.
    """

    def __init__(self, model_size: str = "small"):
        self.model_size = model_size
        self._model = None
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def set_model(self, model_size: str):
        """تغيير النموذج (سيُحمّل النموذج الجديد عند أول استخدام قادم)"""
        if model_size != self.model_size:
            self.model_size = model_size
            self._model = None

    def load_model(self, status_callback=None):
        """تحميل النموذج إلى الذاكرة (يُنزّل من الإنترنت أول مرة فقط)"""
        with self._lock:
            if self._model is not None:
                return
            if status_callback:
                info = MODELS.get(self.model_size, {})
                status_callback(
                    f"جاري تحميل نموذج {self.model_size} "
                    f"({info.get('size', '')}) — أول مرة فقط، قد يستغرق بضع دقائق..."
                )
            # استيراد كسول حتى لا يتعطل البرنامج كله لو المكتبة غير مثبتة
            from faster_whisper import WhisperModel

            try:
                self._model = WhisperModel(
                    self.model_size, device="cpu", compute_type="int8"
                )
            except Exception:
                # محاولة احتياطية بدقة حسابية افتراضية
                self._model = WhisperModel(self.model_size, device="cpu")
            if status_callback:
                status_callback(f"النموذج {self.model_size} جاهز ✓")

    def transcribe(self, audio, language=None, progress_callback=None,
                   status_callback=None, vad_filter=True, beam_size=5):
        """
        تفريغ الصوت إلى نص.

        audio: مسار ملف صوتي (mp3/wav/m4a/ogg/flac/webm/mp4...)
               أو مصفوفة NumPy بصيغة float32 بمعدل 16000Hz (للتسجيل المباشر).
        language: ‏"ar" أو "en" أو None للاكتشاف التلقائي.
        progress_callback(ratio, segment): يُستدعى مع كل مقطع (0.0 - 1.0)

        يُرجع قاموسًا: text, segments, language, language_probability, duration
        """
        self.load_model(status_callback=status_callback)

        segments_gen, info = self._model.transcribe(
            audio,
            language=language or None,
            beam_size=beam_size,
            vad_filter=vad_filter,
            vad_parameters=dict(min_silence_duration_ms=500) if vad_filter else None,
        )

        segments = []
        duration = float(getattr(info, "duration", 0) or 0)
        for seg in segments_gen:
            item = {
                "start": float(seg.start),
                "end": float(seg.end),
                "text": seg.text,
            }
            segments.append(item)
            if progress_callback and duration > 0:
                progress_callback(min(1.0, item["end"] / duration), item)

        return {
            "text": segments_to_text(segments),
            "segments": segments,
            "language": getattr(info, "language", language),
            "language_probability": float(getattr(info, "language_probability", 0) or 0),
            "duration": duration,
        }
