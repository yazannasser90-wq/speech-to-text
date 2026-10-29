@echo off
chcp 65001 >nul
title Speech to Text - بناء ملف EXE
cd /d "%~dp0"

echo ==========================================================
echo    بناء نسخة تنفيذية EXE من التطبيق (PyInstaller)
echo ==========================================================
echo.
echo ملاحظة: الناتج مجلد كامل فيه ملف التشغيل - انسخه كما هو لأي مكان.
echo نموذج الذكاء الاصطناعي يُنزّل أول تشغيل فقط ويحتاج إنترنت وقتها.
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [خطأ] Python غير موجود. ثبته من https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo إنشاء البيئة الافتراضية...
    python -m venv venv
)
call "venv\Scripts\activate.bat"

echo تثبيت المكتبات وأداة البناء...
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [خطأ] فشل التثبيت. تحقق من الإنترنت.
    pause
    exit /b 1
)

echo.
echo جاري البناء... قد يستغرق عدة دقائق
PyInstaller --noconfirm --clean --windowed ^
  --name "SpeechToText" ^
  --icon "assets\icon.ico" ^
  --add-data "assets;assets" ^
  --collect-all PySide6 ^
  --collect-all faster_whisper ^
  --collect-all ctranslate2 ^
  --collect-all sounddevice ^
  --collect-all soundfile ^
  --collect-all deep_translator ^
  --collect-all tokenizers ^
  app.py

if errorlevel 1 (
    echo.
    echo [خطأ] فشل البناء - راجع الرسائل أعلاه.
    pause
    exit /b 1
)

echo.
echo ==========================================================
echo  تم البناء بنجاح!
echo  شغّل التطبيق من:  dist\SpeechToText\SpeechToText.exe
echo ==========================================================
pause
