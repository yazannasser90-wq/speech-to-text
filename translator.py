# -*- coding: utf-8 -*-
"""
الترجمة بين العربية والإنجليزية.
يحاول أولًا خدمة Google Translate (عبر deep-translator)،
وإن تعذّرت (انشغال/حظر مؤقت) ينتقل تلقائيًا إلى خدمة MyMemory المجانية.
(الترجمة وحدها تحتاج إنترنت — التفريغ الصوتي يعمل محليًا)
"""

import re

ARABIC_RE = re.compile(r"[؀-ۿ]")
MYMEMORY_URL = "https://api.mymemory.translated.net/get"


def contains_arabic(text: str) -> bool:
    return bool(ARABIC_RE.search(text or ""))


def opposite_language(text: str) -> str:
    """إذا كان النص عربيًا نترجمه للإنجليزية، والعكس صحيح."""
    return "en" if contains_arabic(text) else "ar"


def detect_source(text: str) -> str:
    return "ar" if contains_arabic(text) else "en"


def _chunk_text(text: str, limit: int = 4000):
    """تقسيم النص الطويل إلى قطع لا تتجاوز حد الخدمة"""
    text = (text or "").strip()
    if len(text) <= limit:
        return [text] if text else []
    chunks, current = [], ""
    parts = re.split(r"(?<=[\.\!\?؛\n])\s+", text)  # التقسيم على حدود الجمل
    for part in parts:
        if len(current) + len(part) + 1 <= limit:
            current = f"{current} {part}".strip()
        else:
            if current:
                chunks.append(current)
            while len(part) > limit:  # جملة أطول من الحد: تقسيم قسري
                chunks.append(part[:limit])
                part = part[limit:]
            current = part
    if current:
        chunks.append(current)
    return chunks


# ------------------------------------------------------------------
# المزوّد 1: Google Translate
# ------------------------------------------------------------------
def _translate_google(text, target, source, progress_callback=None):
    from deep_translator import GoogleTranslator

    engine = GoogleTranslator(source=source or "auto", target=target)
    chunks = _chunk_text(text, limit=4000)
    out = []
    for i, chunk in enumerate(chunks):
        translated = engine.translate(chunk)
        if not translated:
            raise RuntimeError("أرجعت خدمة Google نتيجة فارغة")
        out.append(translated)
        if progress_callback:
            progress_callback((i + 1) / len(chunks))
    return "\n".join(out).strip()


# ------------------------------------------------------------------
# المزوّد 2: MyMemory (احتياطي مجاني بدون مفاتيح)
# ------------------------------------------------------------------
def _translate_mymemory(text, target, source, progress_callback=None):
    import requests

    src = source if source and source != "auto" else detect_source(text)
    if src == target:
        return text
    chunks = _chunk_text(text, limit=450)  # حد MyMemory هو 500 حرف للطلب
    out = []
    session = requests.Session()
    session.headers.update({"User-Agent": "SpeechToTextApp/1.0"})
    for i, chunk in enumerate(chunks):
        resp = session.get(
            MYMEMORY_URL,
            params={"q": chunk, "langpair": f"{src}|{target}"},
            timeout=25,
        )
        resp.raise_for_status()
        data = resp.json()
        translated = (data.get("responseData") or {}).get("translatedText", "")
        if data.get("quotaFinished"):
            raise RuntimeError("انتهت حصة الترجمة المجانية اليومية في MyMemory")
        if not translated or "INVALID" in translated.upper()[:30]:
            raise RuntimeError(f"استجابة غير صالحة من MyMemory: {translated!r}")
        out.append(translated)
        if progress_callback:
            progress_callback((i + 1) / len(chunks))
    return " ".join(out).strip()


# ------------------------------------------------------------------
# الواجهة العامة
# ------------------------------------------------------------------
def translate_text(text: str, target: str, source: str = "auto",
                   progress_callback=None) -> str:
    """
    ترجمة النص إلى اللغة الهدف ("ar" أو "en").
    ترفع استثناءً مفيدًا إذا فشل المزوّدان معًا (غالبًا: لا يوجد إنترنت).
    """
    if not text or not text.strip():
        return ""
    errors = []
    for provider in (_translate_google, _translate_mymemory):
        try:
            result = provider(text, target, source, progress_callback)
            if result:
                return result
        except Exception as e:  # جرّب المزوّد التالي
            errors.append(f"{provider.__name__}: {e}")
    raise RuntimeError(
        "تعذّرت الترجمة من جميع الخدمات. تأكد من اتصال الإنترنت وحاول مجددًا.\n"
        + "\n".join(errors)
    )
