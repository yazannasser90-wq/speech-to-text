# -*- coding: utf-8 -*-
"""
سجل التفريغات السابقة — يُحفظ في ملف JSON داخل مجلد بيانات المستخدم:
    Windows: C:\\Users\\<name>\\.speech_to_text\\history.json
"""

import json
import os
import uuid
from datetime import datetime

APP_DIR = os.path.join(os.path.expanduser("~"), ".speech_to_text")
HISTORY_FILE = os.path.join(APP_DIR, "history.json")
RECORDINGS_DIR = os.path.join(APP_DIR, "recordings")
MAX_ENTRIES = 200  # أقصى عدد عناصر محفوظة في السجل


def ensure_dirs():
    os.makedirs(RECORDINGS_DIR, exist_ok=True)


def load_history():
    ensure_dirs()
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_all(entries):
    ensure_dirs()
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(entries[:MAX_ENTRIES], f, ensure_ascii=False, indent=2)


def add_entry(text, source_name, language=None, duration=0,
              segments=None, translation="", audio_path=""):
    """إضافة تفريغ جديد إلى السجل وإرجاعه"""
    entry = {
        "id": uuid.uuid4().hex[:12],
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": source_name,          # اسم الملف أو "تسجيل مباشر"
        "language": language,           # ar / en / None
        "duration": round(float(duration or 0), 1),
        "text": text or "",
        "translation": translation or "",
        "segments": segments or [],
        "audio_path": audio_path or "",
    }
    entries = load_history()
    entries.insert(0, entry)
    _save_all(entries)
    return entry


def update_translation(entry_id, translation):
    entries = load_history()
    for e in entries:
        if e.get("id") == entry_id:
            e["translation"] = translation
            break
    _save_all(entries)


def delete_entry(entry_id):
    entries = [e for e in load_history() if e.get("id") != entry_id]
    _save_all(entries)


def clear_history():
    _save_all([])
