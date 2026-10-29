# -*- coding: utf-8 -*-
"""
🎙️ مُفرِّغ الصوت — تحويل التسجيلات الصوتية إلى نص (عربي / إنجليزي)
واجهة احترافية بمكتبة Qt (PySide6) مع دعم أصيل كامل للعربية واتجاه RTL.

المزايا:
- تسجيل مباشر من الميكروفون (مع تفريغ فوري اختياري أثناء التسجيل)
- تفريغ ملفات: MP3, WAV, M4A, OGG, FLAC, WEBM, MP4...
- محرك Whisper يعمل محليًا (faster-whisper) — بدون إنترنت بعد تنزيل النموذج
- اكتشاف تلقائي للغة + اختيار يدوي (العربية / English)
- ترجمة عربي ⇄ إنجليزي، حفظ TXT / Word / SRT، نسخ، سجل كامل للتفريغات

التشغيل:  python app.py
"""

import os
import sys
import time
import traceback
from datetime import datetime

from PySide6.QtCore import Qt, QObject, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QIcon, QTextBlockFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

import history
import translator
from recorder import SAMPLE_RATE, Recorder, play_file, stop_playback
from transcriber import (
    MODELS, Transcriber, format_timestamp, segments_to_srt, segments_to_text,
)

APP_NAME = "مُفرِّغ الصوت"
SUPPORTED_FILTER = (
    "ملفات صوتية (*.mp3 *.wav *.m4a *.ogg *.flac *.webm *.aac *.wma *.mp4 *.mkv *.mov);;"
    "كل الملفات (*.*)"
)
LANG_CODE_TO_NAME = {"ar": "العربية", "en": "English"}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def resource_path(relative_path):
    """مسار صحيح للملفات المرفقة في وضعَي التشغيل: كود مصدري أو نسخة EXE مدمجة."""
    base = getattr(sys, "_MEIPASS", BASE_DIR)  # _MEIPASS يضعه PyInstaller عند البناء
    return os.path.join(base, relative_path)


# ================================================================
# خيوط الخلفية (Workers) — التفريغ والترجمة لا يجمّدان الواجهة
# ================================================================
class TranscribeWorker(QObject):
    progress = Signal(float, object)
    status = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, engine: Transcriber, audio, language, model_size):
        super().__init__()
        self.engine, self.audio = engine, audio
        self.language, self.model_size = language, model_size

    def run(self):
        try:
            self.engine.set_model(self.model_size)
            result = self.engine.transcribe(
                self.audio, language=self.language,
                progress_callback=lambda r, s: self.progress.emit(r, s),
                status_callback=self.status.emit,
            )
            self.finished.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())


class LiveWorker(QObject):
    """تفريغ فوري: يفرّغ مقاطع قصيرة أثناء استمرار التسجيل."""
    chunk = Signal(str)
    detected = Signal(str)
    status = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, engine: Transcriber, recorder: Recorder, language, model_size):
        super().__init__()
        self.engine, self.recorder = engine, recorder
        self.language = language  # None يعني تلقائي
        self.model_size = model_size
        self._last_sample = 0
        self._locked_lang = language

    def run(self):
        try:
            self.engine.set_model(self.model_size)
            self.engine.load_model(status_callback=self.status.emit)
            while self.recorder.is_recording:
                time.sleep(1.0)
                if self.recorder.total_samples - self._last_sample < int(3.5 * SAMPLE_RATE):
                    continue
                audio = self.recorder.get_audio(from_sample=self._last_sample)
                self._last_sample += len(audio)
                try:
                    result = self.engine.transcribe(
                        audio, language=self._locked_lang,
                        vad_filter=False, beam_size=1)
                except Exception:
                    continue  # تجاهل خطأ مقطع واحد حتى لا يتوقف الفوري
                if (self._locked_lang is None and result.get("language")
                        and result.get("language_probability", 0) > 0.5):
                    self._locked_lang = result["language"]
                if result.get("language"):
                    self.detected.emit(result["language"])
                text = (result.get("text") or "").strip()
                if text:
                    self.chunk.emit(text)
        except Exception:
            self.failed.emit(traceback.format_exc())
        finally:
            self.finished.emit()


class TranslateWorker(QObject):
    progress = Signal(float)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, text, target):
        super().__init__()
        self.text, self.target = text, target

    def run(self):
        try:
            result = translator.translate_text(
                self.text, target=self.target,
                progress_callback=self.progress.emit)
            self.finished.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())


# ================================================================
# النافذة الرئيسية
# ================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} | Speech to Text — عربي / English")
        self.resize(1180, 740)
        self.setMinimumSize(960, 600)
        icon_path = resource_path(os.path.join("assets", "icon.png"))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # الحالة الداخلية
        self.transcriber = Transcriber("small")
        self.recorder = Recorder()
        self.selected_file = None
        self.last_segments = []
        self.last_entry_id = None
        self.detected_language = None
        self._busy = False
        self._dark = True
        self._threads = []
        self._workers = []  # مراجع دائمة للعمّال حتى تنتهي خيوطهم (مهم جدًا في Qt)
        self._pending_live = None  # (path, duration) بانتظار انتهاء العامل الفوري
        self._history_by_id = {}
        self._pending_source = ""  # مصدر التفريغ الجاري
        self._pending_audio_path = ""
        self._translation_target_name = ""

        self._build_ui()
        self._apply_theme(dark=True)
        self.refresh_history()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(150)

    # ------------------------------------------------------------
    # بناء الواجهة
    # ------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 8)
        root.setSpacing(10)

        # الترويسة
        header = QHBoxLayout()
        title = QLabel(f"🎙️ {APP_NAME} — تحويل الصوت إلى نص")
        title.setObjectName("appTitle")
        header.addWidget(title)
        subtitle = QLabel("العربية • English • اكتشاف تلقائي للغة")
        subtitle.setObjectName("subtitle")
        header.addWidget(subtitle)
        header.addStretch(1)
        self.theme_btn = QPushButton("☀️ الوضع الفاتح")
        self.theme_btn.setObjectName("ghostBtn")
        self.theme_btn.clicked.connect(self._toggle_theme)
        header.addWidget(self.theme_btn)
        root.addLayout(header)

        # الجسم: لوحة تحكم (يمين بفضل RTL) + تبويبات (يسار)
        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_tabs(), stretch=1)
        root.addLayout(body, stretch=1)

        # شريط الحالة
        self.status_label = QLabel("جاهز. سجّل من الميكروفون أو اختر ملفًا صوتيًا للبدء.")
        self.stats_label = QLabel("")
        self.stats_label.setObjectName("subtitle")
        self.statusBar().addWidget(self.status_label, stretch=1)
        self.statusBar().addPermanentWidget(self.stats_label)

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("panel")
        side.setFixedWidth(335)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        def section(text):
            lbl = QLabel(text)
            lbl.setObjectName("sectionLabel")
            lay.addWidget(lbl)
            return lbl

        def separator():
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setObjectName("sep")
            lay.addWidget(line)

        # لغة الكلام
        section("🌍 لغة الكلام في الصوت")
        lang_row = QHBoxLayout()
        self.lang_group = QButtonGroup(self)
        self.lang_buttons = {}
        for label, code in [("تلقائي", None), ("العربية", "ar"), ("English", "en")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setObjectName("segBtn")
            self.lang_group.addButton(btn)
            self.lang_buttons[btn] = code
            lang_row.addWidget(btn)
        # الافتراضي: تلقائي
        first_btn = next(iter(self.lang_buttons))
        first_btn.setChecked(True)
        lay.addLayout(lang_row)

        # النموذج
        section("🧠 نموذج الذكاء الاصطناعي")
        self.model_combo = QComboBox()
        self.model_combo.addItems(list(MODELS.keys()))
        self.model_combo.setCurrentText("small")
        self.model_combo.currentTextChanged.connect(self._on_model_change)
        lay.addWidget(self.model_combo)
        self.model_note = QLabel("")
        self.model_note.setObjectName("subtitle")
        self.model_note.setWordWrap(True)
        lay.addWidget(self.model_note)
        self._on_model_change("small")

        separator()

        # التسجيل المباشر
        section("🎙️ التسجيل من الميكروفون")
        self.record_btn = QPushButton("🔴  بدء التسجيل")
        self.record_btn.setObjectName("recordBtn")
        self.record_btn.setMinimumHeight(46)
        self.record_btn.clicked.connect(self.toggle_recording)
        lay.addWidget(self.record_btn)
        rec_row = QHBoxLayout()
        self.timer_label = QLabel("00:00")
        self.timer_label.setObjectName("timerLabel")
        rec_row.addWidget(self.timer_label)
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setValue(0)
        self.level_bar.setTextVisible(False)
        self.level_bar.setFixedHeight(10)
        rec_row.addWidget(self.level_bar, stretch=1)
        lay.addLayout(rec_row)
        self.live_check = QCheckBox("تفريغ فوري أثناء التسجيل (تجريبي — أسرع ملاحظة للنص)")
        lay.addWidget(self.live_check)

        separator()

        # ملف صوتي جاهز
        section("📁 ملف صوتي جاهز")
        self.file_btn = QPushButton("اختيار ملف صوتي...")
        self.file_btn.setObjectName("primaryBtn")
        self.file_btn.setMinimumHeight(38)
        self.file_btn.clicked.connect(self.choose_file)
        lay.addWidget(self.file_btn)
        self.file_label = QLabel("لم يتم اختيار ملف")
        self.file_label.setObjectName("subtitle")
        self.file_label.setWordWrap(True)
        lay.addWidget(self.file_label)
        play_row = QHBoxLayout()
        self.play_btn = QPushButton("▶ تشغيل")
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self._play_selected)
        play_row.addWidget(self.play_btn)
        self.stop_play_btn = QPushButton("⏹ إيقاف")
        self.stop_play_btn.setEnabled(False)
        self.stop_play_btn.clicked.connect(stop_playback)
        play_row.addWidget(self.stop_play_btn)
        play_row.addStretch(1)
        lay.addLayout(play_row)
        self.transcribe_file_btn = QPushButton("📝  تفريغ الملف إلى نص")
        self.transcribe_file_btn.setObjectName("goBtn")
        self.transcribe_file_btn.setMinimumHeight(46)
        self.transcribe_file_btn.setEnabled(False)
        self.transcribe_file_btn.clicked.connect(lambda: self.transcribe_selected_file())
        lay.addWidget(self.transcribe_file_btn)

        self.timestamps_check = QCheckBox("⏱️ إظهار الطوابع الزمنية قبل كل جملة")
        self.timestamps_check.toggled.connect(lambda _: self._refresh_text_from_segments())
        lay.addWidget(self.timestamps_check)

        lay.addStretch(1)

        # التقدم
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(12)
        lay.addWidget(self.progress)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("subtitle")
        lay.addWidget(self.progress_label)
        return side

    def _build_tabs(self):
        tabs = QTabWidget()
        self.tabs = tabs

        # ---- تبويب النص ----
        tab_text = QWidget()
        v = QVBoxLayout(tab_text)
        v.setContentsMargins(8, 8, 8, 8)
        actions = QHBoxLayout()
        for label, handler in [
            ("📋 نسخ النص", self.copy_text),
            ("💾 حفظ TXT", lambda: self.save_text("txt")),
            ("📄 حفظ Word", lambda: self.save_text("docx")),
            ("🎬 حفظ ترجمة SRT", lambda: self.save_text("srt")),
            ("🗑 مسح", self.clear_text),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            actions.addWidget(btn)
        actions.addStretch(1)
        v.addLayout(actions)
        self.textbox = QPlainTextEdit()
        self.textbox.setPlaceholderText(
            "سيظهر النص المُفرَّغ هنا...\n\n"
            "🎙️ اضغط «بدء التسجيل» وتحدث بالعربية أو الإنجليزية\n"
            "أو\n📁 اختر ملفًا صوتيًا واضغط «تفريغ الملف إلى نص»")
        self._set_editor_font(self.textbox)
        self._apply_editor_direction(self.textbox, "مرحبًا")
        self.textbox.textChanged.connect(self._update_word_count)
        v.addWidget(self.textbox, stretch=1)
        tabs.addTab(tab_text, "📝 النص المُفرَّغ")

        # ---- تبويب الترجمة ----
        tab_tr = QWidget()
        v2 = QVBoxLayout(tab_tr)
        v2.setContentsMargins(8, 8, 8, 8)
        tr_actions = QHBoxLayout()
        for label, handler in [
            ("🌐 ترجمة تلقائية (عربي ⇄ إنجليزي)", lambda: self.translate("auto")),
            ("إلى العربية", lambda: self.translate("ar")),
            ("To English", lambda: self.translate("en")),
            ("📋 نسخ الترجمة", self.copy_translation),
            ("💾 حفظ الترجمة", lambda: self.save_text("txt", translation=True)),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            tr_actions.addWidget(btn)
        tr_actions.addStretch(1)
        v2.addLayout(tr_actions)
        self.translation_box = QPlainTextEdit()
        self.translation_box.setPlaceholderText(
            "ستظهر الترجمة هنا...\n"
            "(الترجمة تحتاج إنترنت — التفريغ الصوتي يعمل بالكامل على جهازك)")
        self._set_editor_font(self.translation_box)
        self._apply_editor_direction(self.translation_box, "مرحبًا")
        v2.addWidget(self.translation_box, stretch=1)
        tabs.addTab(tab_tr, "🌐 الترجمة")

        # ---- تبويب السجل ----
        tab_hist = QWidget()
        v3 = QVBoxLayout(tab_hist)
        v3.setContentsMargins(8, 8, 8, 8)
        hist_actions = QHBoxLayout()
        for label, handler, obj in [
            ("📂 عرض المحدد", self._load_selected_history, None),
            ("🔄 تحديث", self.refresh_history, None),
            ("🗑 حذف المحدد", self._delete_selected_history, "dangerBtn"),
            ("مسح السجل بالكامل", self.clear_all_history, "dangerBtn"),
        ]:
            btn = QPushButton(label)
            if obj:
                btn.setObjectName(obj)
            btn.clicked.connect(handler)
            hist_actions.addWidget(btn)
        hist_actions.addStretch(1)
        v3.addLayout(hist_actions)
        self.history_list = QListWidget()
        self.history_list.itemDoubleClicked.connect(lambda _i: self._load_selected_history())
        v3.addWidget(self.history_list, stretch=1)
        tabs.addTab(tab_hist, "🕘 السجل")
        return tabs

    @staticmethod
    def _set_editor_font(editor):
        font = QFont()
        font.setFamilies(["Segoe UI", "Noto Sans Arabic UI", "Tahoma", "Arial"])
        font.setPointSize(13)
        editor.setFont(font)

    # ------------------------------------------------------------
    # المظهر (داكن / فاتح)
    # ------------------------------------------------------------
    def _toggle_theme(self):
        self._apply_theme(dark=not self._dark)

    def _apply_theme(self, dark=True):
        self._dark = dark
        self.theme_btn.setText("☀️ الوضع الفاتح" if dark else "🌙 الوضع الداكن")
        if dark:
            bg, panel, field, text, sub, border = "#1b1e27", "#232733", "#171a21", "#e8eaf0", "#9aa3b2", "#343a4a"
            btn_bg, btn_hover = "#2c3242", "#39415a"
        else:
            bg, panel, field, text, sub, border = "#f3f5f9", "#ffffff", "#ffffff", "#1c2333", "#5c6a7d", "#d3dae6"
            btn_bg, btn_hover = "#e5eaf3", "#d7dfed"
        qss = f"""
        QMainWindow {{ background: {bg}; }}
        QWidget {{ color: {text};
            font-family: "Segoe UI","Noto Sans Arabic UI",Tahoma; font-size: 13px; }}
        #panel {{ background: {panel}; border: 1px solid {border}; border-radius: 14px; }}
        #appTitle {{ font-size: 20px; font-weight: bold; }}
        #subtitle {{ color: {sub}; font-size: 11px; }}
        #sectionLabel {{ font-size: 14px; font-weight: bold; margin-top: 6px; }}
        #sep {{ color: {border}; }}
        #timerLabel {{ font-size: 15px; font-weight: bold; }}
        QPushButton {{ background: {btn_bg}; border: 1px solid {border};
            border-radius: 9px; padding: 7px 12px; }}
        QPushButton:hover {{ background: {btn_hover}; }}
        QPushButton:disabled {{ color: {sub}; }}
        #segBtn:checked {{ background: #1f6feb; color: white; border-color: #1f6feb; }}
        #primaryBtn {{ background: #1f6feb; color: white; border: none; }}
        #primaryBtn:hover {{ background: #1a5fd0; }}
        #goBtn {{ background: #1f7a4d; color: white; border: none; font-size: 15px; font-weight: bold; }}
        #goBtn:hover {{ background: #145c39; }}
        #goBtn:disabled {{ background: {btn_bg}; color: {sub}; }}
        #recordBtn {{ background: #c0392b; color: white; border: none; font-size: 15px; font-weight: bold; }}
        #recordBtn:hover {{ background: #96281b; }}
        #dangerBtn {{ background: #7b241c; color: white; border: none; }}
        #dangerBtn:hover {{ background: #5d1a14; }}
        #ghostBtn {{ background: transparent; }}
        QPlainTextEdit, QListWidget, QComboBox {{ background: {field}; color: {text};
            border: 1px solid {border}; border-radius: 10px; padding: 6px; }}
        QComboBox {{ padding: 6px 10px; }}
        QTabWidget::pane {{ border: 1px solid {border}; border-radius: 12px; background: {panel}; }}
        QTabBar::tab {{ background: {btn_bg}; border: 1px solid {border};
            border-radius: 8px; padding: 7px 16px; margin: 2px; }}
        QTabBar::tab:selected {{ background: #1f6feb; color: white; }}
        QProgressBar {{ background: {field}; border: 1px solid {border}; border-radius: 6px; }}
        QProgressBar::chunk {{ background: #1f6feb; border-radius: 5px; }}
        QListWidget::item {{ padding: 8px; border-bottom: 1px solid {border}; }}
        QListWidget::item:selected {{ background: #1f6feb; color: white; }}
        QStatusBar {{ background: {panel}; border-top: 1px solid {border}; }}
        QCheckBox {{ spacing: 7px; }}
        """
        QApplication.instance().setStyleSheet(qss)

    # ------------------------------------------------------------
    # أدوات عامة
    # ------------------------------------------------------------
    def set_status(self, text):
        self.status_label.setText(text)

    def set_progress(self, ratio, label=""):
        self.progress.setValue(int(max(0.0, min(1.0, ratio)) * 1000))
        self.progress_label.setText(label)

    def _set_busy(self, busy):
        self._busy = busy
        self.record_btn.setEnabled(not busy)
        self.file_btn.setEnabled(not busy)
        self.transcribe_file_btn.setEnabled(bool(self.selected_file) and not busy)

    def _selected_language(self):
        checked = self.lang_group.checkedButton()
        return self.lang_buttons.get(checked)

    def _on_model_change(self, model_size):
        info = MODELS.get(model_size, {})
        self.model_note.setText(f"الحجم: {info.get('size', '')} — {info.get('note', '')}\n"
                                "(يُنزّل النموذج مرة واحدة فقط عند أول استخدام له)")
        self.transcriber.set_model(model_size)

    def _tick(self):
        if self.recorder.is_recording:
            self.timer_label.setText(format_timestamp(self.recorder.elapsed))
            self.level_bar.setValue(int(self.recorder.level * 100))
        else:
            self.level_bar.setValue(0)

    def _start_worker(self, worker, on_finished_thread=None):
        """تشغيل عامل في خيط مستقل مع تنظيف تلقائي بعد الانتهاء."""
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        for sig_name in ("finished", "failed"):
            sig = getattr(worker, sig_name, None)
            if sig is not None:
                sig.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._threads.remove(t) if t in self._threads else None)
        thread.finished.connect(lambda wk=worker: self._workers.remove(wk) if wk in self._workers else None)
        if on_finished_thread:
            thread.finished.connect(on_finished_thread)
        self._threads.append(thread)
        self._workers.append(worker)  # بدون هذا المرجع يُحذف العامل من الذاكرة قبل بدء عمله
        thread.start()
        return thread

    # ---------- محرر النص ----------
    def get_text(self):
        return self.textbox.toPlainText().strip()

    def set_text(self, text):
        self.textbox.setPlainText(text)
        self._apply_editor_direction(self.textbox, text)
        self._update_word_count()

    def append_text(self, text):
        cursor = self.textbox.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.textbox.setTextCursor(cursor)
        self.textbox.ensureCursorVisible()

    @staticmethod
    def _apply_editor_direction(editor, text):
        """ضبط اتجاه ومحاذاة فقرات المحرر بحسب لغة النص (عربي=يمين، إنجليزي=يسار)."""
        rtl = translator.contains_arabic((text or "")[:300])
        direction = (Qt.LayoutDirection.RightToLeft if rtl
                     else Qt.LayoutDirection.LeftToRight)
        alignment = (Qt.AlignmentFlag.AlignRight if rtl
                     else Qt.AlignmentFlag.AlignLeft)
        editor.setLayoutDirection(direction)
        option = QTextOption()
        option.setTextDirection(direction)
        option.setAlignment(alignment)
        option.setWrapMode(QTextOption.WrapMode.WordWrap)
        editor.document().setDefaultTextOption(option)
        # تطبيق المحاذاة على الفقرات الموجودة حاليًا أيضًا
        cursor = editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = QTextBlockFormat()
        fmt.setAlignment(alignment)
        fmt.setLayoutDirection(direction)
        cursor.mergeBlockFormat(fmt)
        cursor.clearSelection()

    def _update_word_count(self):
        text = self.textbox.toPlainText().strip()
        words = len(text.split()) if text else 0
        lang = LANG_CODE_TO_NAME.get(self.detected_language, self.detected_language or "—")
        self.stats_label.setText(
            f"اللغة المكتشفة: {lang}   |   الكلمات: {words}   |   الأحرف: {len(text)}  ")

    def _refresh_text_from_segments(self):
        if self.last_segments:
            self.set_text(segments_to_text(
                self.last_segments,
                with_timestamps=self.timestamps_check.isChecked()))

    # ------------------------------------------------------------
    # التسجيل من الميكروفون
    # ------------------------------------------------------------
    def toggle_recording(self):
        if self.recorder.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        if self._busy:
            return
        try:
            self.recorder.start()
        except Exception as e:
            QMessageBox.critical(
                self, "خطأ في الميكروفون",
                "تعذّر الوصول إلى الميكروفون.\n"
                "تأكد أنه متصل، وأنه مسموح به في ويندوز: "
                "الإعدادات ← الخصوصية والأمان ← الميكروفون.\n\n"
                f"تفاصيل الخطأ:\n{e}")
            return
        self.record_btn.setText("⏹  إيقاف التسجيل")
        self.timer_label.setText("00:00")
        self.set_status("🎙️ جاري التسجيل... تحدّث الآن بوضوح بالقرب من الميكروفون.")
        if self.live_check.isChecked():
            self.set_text("")
            self.last_segments = []
            worker = LiveWorker(self.transcriber, self.recorder,
                                self._selected_language(), self.model_combo.currentText())
            worker.chunk.connect(lambda t: self.append_text(t + " "))
            worker.detected.connect(self._on_live_detected)
            worker.status.connect(self.set_status)
            worker.failed.connect(lambda tb: self._on_error("خطأ في التفريغ الفوري", tb))
            self._live_thread_ref = self._start_worker(
                worker, on_finished_thread=self._finalize_live_if_pending)
            self.set_status("🎙️ تسجيل مع تفريغ فوري... قد يتأخر النص بضع ثوانٍ عن كلامك.")

    def _on_live_detected(self, lang):
        self.detected_language = lang
        self._update_word_count()
        self._apply_editor_direction(self.textbox, self.get_text() or ("ا" if lang == "ar" else "a"))

    def stop_recording(self):
        audio = self.recorder.stop()
        self.record_btn.setText("🔴  بدء التسجيل")
        duration = len(audio) / float(SAMPLE_RATE or 16000)
        if duration < 0.5:
            self._pending_live = None
            self.set_status("التسجيل قصير جدًا — حاول مرة أخرى وتحدّث لبضع ثوانٍ.")
            return
        history.ensure_dirs()
        fname = f"rec_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        path = os.path.join(history.RECORDINGS_DIR, fname)
        try:
            self.recorder.save_wav(path, audio)
            self._set_selected_file(path)
        except Exception:
            path = ""

        if self.live_check.isChecked():
            # النص ظاهر مسبقًا — عند انتهاء العامل الفوري سيُحفظ في السجل
            self._pending_live = (path, duration)
            self.set_status("⏹ توقف التسجيل — جاري إنهاء آخر مقطع فوري...")
            # إن لم يكن العامل موجودًا لأي سبب، نفّذ الحفظ فورًا
            if not getattr(self, "_live_thread_ref", None):
                self._finalize_live_if_pending()
            self._live_thread_ref = None
        elif path:
            self.transcribe_selected_file(source_name="تسجيل مباشر")
        else:
            self._transcribe_async(audio, source_name="تسجيل مباشر", audio_path="")

    def _finalize_live_if_pending(self):
        if not self._pending_live:
            return
        path, duration = self._pending_live
        self._pending_live = None
        text = self.get_text()
        if text:
            entry = history.add_entry(
                text=text, source_name="تسجيل مباشر (فوري)",
                language=self.detected_language, duration=duration,
                segments=[], audio_path=path)
            self.last_entry_id = entry["id"]
            self.refresh_history()
        self.set_status(
            "✓ انتهى التسجيل الفوري. تلميح: لدقة أعلى اضغط «تفريغ الملف إلى نص» — "
            "تسجيلك محفوظ ومُختار تلقائيًا، وسيُفرَّغ بالنموذج الكامل.")

    # ------------------------------------------------------------
    # الملفات الصوتية الجاهزة
    # ------------------------------------------------------------
    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "اختر ملفًا صوتيًا", "", SUPPORTED_FILTER)
        if path:
            self._set_selected_file(path)
            self.set_status(f"تم اختيار: {os.path.basename(path)} — اضغط «تفريغ الملف إلى نص».")

    def _set_selected_file(self, path):
        self.selected_file = path
        self.file_label.setText(f"📄 {os.path.basename(path)}")
        self.transcribe_file_btn.setEnabled(not self._busy)
        self.play_btn.setEnabled(True)
        self.stop_play_btn.setEnabled(True)

    def _play_selected(self):
        if not self.selected_file:
            return
        try:
            play_file(self.selected_file)
            self.set_status(f"▶ جاري تشغيل: {os.path.basename(self.selected_file)}")
        except Exception as e:
            QMessageBox.information(
                self, "التشغيل غير متاح لهذا التنسيق",
                "لا يمكن تشغيل هذا الملف داخل البرنامج (قد يكون بتنسيق M4A/MP4)، "
                "لكن التفريغ إلى نص سيعمل بشكل طبيعي.\n\n"
                f"تفاصيل: {e}")

    def transcribe_selected_file(self, source_name=None):
        if not self.selected_file or self._busy:
            return
        self._transcribe_async(
            self.selected_file,
            source_name=source_name or os.path.basename(self.selected_file),
            audio_path=self.selected_file)

    # ------------------------------------------------------------
    # التفريغ
    # ------------------------------------------------------------
    def _transcribe_async(self, audio, source_name, audio_path=""):
        self._set_busy(True)
        self.tabs.setCurrentIndex(0)
        self.set_text("")
        self.last_segments = []
        self._pending_source = source_name
        self._pending_audio_path = audio_path
        self.set_progress(0, "جاري التحضير...")
        self.set_status("جاري التفريغ... (الملفات الطويلة تأخذ وقتًا أطول — يظهر النص تدريجيًا أثناء العمل)")
        worker = TranscribeWorker(self.transcriber, audio,
                                  self._selected_language(),
                                  self.model_combo.currentText())
        worker.progress.connect(self._on_transcribe_progress)
        worker.status.connect(lambda s: (self.set_status(s), self.set_progress(0, s)))
        worker.finished.connect(self._on_transcribe_done)
        worker.failed.connect(lambda tb: self._on_error("حدث خطأ أثناء التفريغ", tb))
        self._start_worker(worker)

    def _on_transcribe_progress(self, ratio, segment):
        self.set_progress(ratio, f"{int(ratio * 100)}%")
        line = (segment.get("text") or "").strip()
        if not line:
            return
        if self.timestamps_check.isChecked():
            self.append_text(f"[{format_timestamp(segment['start'])}] {line}\n")
        else:
            self.append_text(line + " ")

    def _on_transcribe_done(self, result):
        self._set_busy(False)
        self.set_progress(1, "اكتمل التفريغ ✓")
        self.last_segments = result.get("segments", [])
        self.detected_language = result.get("language")
        self.set_text(segments_to_text(
            self.last_segments, with_timestamps=self.timestamps_check.isChecked()))
        plain = segments_to_text(self.last_segments)
        if plain.strip():
            entry = history.add_entry(
                text=plain, source_name=self._pending_source,
                language=self.detected_language,
                duration=result.get("duration", 0),
                segments=self.last_segments,
                audio_path=self._pending_audio_path)
            self.last_entry_id = entry["id"]
            self.refresh_history()
            lang_name = LANG_CODE_TO_NAME.get(self.detected_language, self.detected_language)
            self.set_status(
                f"✓ تم التفريغ بنجاح — اللغة: {lang_name}، "
                f"مدة الصوت: {format_timestamp(result.get('duration', 0))}. "
                "يمكنك تعديل النص أو نسخه أو حفظه أو ترجمته.")
        else:
            self.set_status("انتهى التفريغ لكن لم يُكتشف كلام واضح. جرّب تسجيلًا أوضح، أو اختر لغة الكلام يدويًا، أو نموذجًا أكبر.")
        self._update_word_count()

    def _on_error(self, title, tb_text):
        self._set_busy(False)
        self.set_progress(0, "")
        self.set_status(f"❌ {title}")
        last_line = (tb_text or "").strip().splitlines()[-1] if tb_text else ""
        hint = ""
        if "No module named" in tb_text:
            hint = ("\n\n💡 يبدو أن المكتبات غير مثبتة بالكامل. شغّل run.bat "
                    "أو نفّذ:  pip install -r requirements.txt")
        elif any(k in tb_text for k in ("Connection", "getaddrinfo", "Max retries", "offline")):
            hint = ("\n\n💡 تحقق من اتصال الإنترنت — يُحتاج إليه فقط "
                    "لتنزيل النموذج أول مرة وللترجمة.")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(title)
        box.setText(f"{last_line}{hint}")
        box.setDetailedText(tb_text)
        box.exec()

    # ------------------------------------------------------------
    # النسخ والحفظ والمسح
    # ------------------------------------------------------------
    def _copy_to_clipboard(self, text, done_msg):
        if not text.strip():
            QMessageBox.information(self, "لا يوجد نص", "لا يوجد نص لنسخه بعد.")
            return
        QApplication.clipboard().setText(text)
        self.set_status(done_msg)

    def copy_text(self):
        self._copy_to_clipboard(self.get_text(), "✓ تم نسخ النص إلى الحافظة — يمكنك لصقه في أي برنامج.")

    def copy_translation(self):
        self._copy_to_clipboard(
            self.translation_box.toPlainText().strip(), "✓ تم نسخ الترجمة إلى الحافظة.")

    def clear_text(self):
        self.set_text("")
        self.last_segments = []
        self.detected_language = None
        self.set_progress(0, "")
        self.set_status("تم مسح النص من المحرر. (تبقى نسخة محفوظة في السجل)")

    def save_text(self, kind, translation=False):
        if kind == "srt":
            if not self.last_segments:
                QMessageBox.information(
                    self, "لا توجد توقيتات",
                    "ملف SRT يحتاج توقيتات المقاطع — فرّغ ملفًا صوتيًا أولًا "
                    "(وضع التفريغ الفوري لا يوفّر توقيتات).")
                return
            content, default = segments_to_srt(self.last_segments), "subtitles.srt"
            filter_ = "ملف ترجمة (*.srt)"
        else:
            content = (self.translation_box.toPlainText().strip()
                       if translation else self.get_text())
            if not content:
                QMessageBox.information(self, "لا يوجد نص", "لا يوجد نص لحفظه بعد.")
                return
            default = ("translation" if translation else "transcript") + f".{kind}"
            filter_ = "ملف نصي (*.txt)" if kind == "txt" else "مستند Word (*.docx)"
        path, _ = QFileDialog.getSaveFileName(self, "حفظ باسم", default, filter_)
        if not path:
            return
        if not path.lower().endswith(f".{kind}"):
            path += f".{kind}"
        try:
            if kind == "docx":
                self._save_docx(path, content)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            self.set_status(f"💾 تم الحفظ في: {path}")
        except Exception:
            self._on_error("تعذّر الحفظ", traceback.format_exc())

    @staticmethod
    def _save_docx(path, text):
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        doc = Document()
        is_arabic = translator.contains_arabic(text)
        for line in text.split("\n"):
            p = doc.add_paragraph(line)
            if is_arabic:
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        doc.save(path)

    # ------------------------------------------------------------
    # الترجمة
    # ------------------------------------------------------------
    def translate(self, target):
        text = self.get_text()
        if not text:
            QMessageBox.information(self, "لا يوجد نص", "فرّغ صوتًا إلى نص أولًا، ثم ترجمه.")
            return
        if self.last_segments:  # ترجمة النص النظيف بدون طوابع زمنية
            text = segments_to_text(self.last_segments)
        if target == "auto":
            target = translator.opposite_language(text)
        self._translation_target_name = "العربية" if target == "ar" else "English"
        self.tabs.setCurrentIndex(1)
        self.translation_box.setPlainText(f"جاري الترجمة إلى {self._translation_target_name}...")
        self.set_status(f"🌐 جاري الترجمة إلى {self._translation_target_name}... (تحتاج إنترنت)")
        self.set_progress(0, "ترجمة...")
        worker = TranslateWorker(text, target)
        worker.progress.connect(lambda r: self.set_progress(r, f"ترجمة: {int(r * 100)}%"))
        worker.finished.connect(self._on_translate_done)
        worker.failed.connect(lambda tb: self._on_error(
            "تعذّرت الترجمة — تحقق من الإنترنت وحاول مجددًا", tb))
        self._start_worker(worker)

    def _on_translate_done(self, result):
        self.set_progress(1, "اكتملت الترجمة ✓")
        self.translation_box.setPlainText(result)
        self._apply_editor_direction(self.translation_box, result)
        self.set_status(f"✓ تمت الترجمة إلى {self._translation_target_name}.")
        if self.last_entry_id:
            history.update_translation(self.last_entry_id, result)
            self.refresh_history()

    # ------------------------------------------------------------
    # السجل
    # ------------------------------------------------------------
    def refresh_history(self):
        self.history_list.clear()
        self._history_by_id = {}
        entries = history.load_history()
        if not entries:
            item = QListWidgetItem("لا توجد تفريغات محفوظة بعد — ستظهر هنا كل تسجيلاتك وملفاتك المفرّغة تلقائيًا.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.history_list.addItem(item)
            return
        for entry in entries:
            self._history_by_id[entry.get("id")] = entry
            lang = LANG_CODE_TO_NAME.get(entry.get("language"), entry.get("language") or "—")
            preview = (entry.get("text") or "").replace("\n", " ")
            if len(preview) > 130:
                preview = preview[:130] + "..."
            label = (f"{entry.get('date', '')}  •  {entry.get('source', '')}  •  {lang}  •  "
                     f"{format_timestamp(entry.get('duration', 0))}\n{preview}")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, entry.get("id"))
            self.history_list.addItem(item)

    def _selected_history_entry(self):
        item = self.history_list.currentItem()
        if item is None:
            return None
        return self._history_by_id.get(item.data(Qt.ItemDataRole.UserRole))

    def _load_selected_history(self):
        entry = self._selected_history_entry()
        if entry is None:
            QMessageBox.information(self, "السجل", "اختر عنصرًا من السجل أولًا.")
            return
        self.last_entry_id = entry.get("id")
        self.last_segments = entry.get("segments", []) or []
        self.detected_language = entry.get("language")
        if self.last_segments:
            self._refresh_text_from_segments()
        else:
            self.set_text(entry.get("text", ""))
        tr = entry.get("translation") or ""
        self.translation_box.setPlainText(tr)
        self._apply_editor_direction(self.translation_box, tr)
        audio_path = entry.get("audio_path")
        if audio_path and os.path.exists(audio_path):
            self._set_selected_file(audio_path)
        self.tabs.setCurrentIndex(0)
        self.set_status(f"تم تحميل عنصر من السجل: {entry.get('source', '')} ({entry.get('date', '')})")

    def _delete_selected_history(self):
        entry = self._selected_history_entry()
        if entry is None:
            QMessageBox.information(self, "السجل", "اختر عنصرًا من السجل أولًا.")
            return
        history.delete_entry(entry.get("id"))
        self.refresh_history()

    def clear_all_history(self):
        answer = QMessageBox.question(
            self, "مسح السجل", "سيتم حذف كل التفريغات المحفوظة من السجل. هل أنت متأكد؟")
        if answer == QMessageBox.StandardButton.Yes:
            history.clear_history()
            self.refresh_history()
            self.set_status("تم مسح السجل بالكامل.")

    # ------------------------------------------------------------
    def closeEvent(self, event):
        try:
            if self.recorder.is_recording:
                self.recorder.stop()
            stop_playback()
            # إعطاء خيوط الخلفية فرصة قصيرة للإنهاء النظيف
            for t in list(self._threads):
                t.quit()
                t.wait(2500)
        finally:
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    font = QFont()
    font.setFamilies(["Segoe UI", "Noto Sans Arabic UI", "Tahoma", "Arial"])
    font.setPointSize(10)
    app.setFont(font)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
