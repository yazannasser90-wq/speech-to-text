@echo off
chcp 65001 >nul
title Speech to Text - تشغيل التطبيق
cd /d "%~dp0"

echo ================================================
echo    Speech to Text ^| مُفرِّغ الصوت - جاري التشغيل
echo ================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [خطأ] لم يتم العثور على Python في جهازك.
    echo.
    echo الحل:
    echo  1) نزّل Python من الموقع الرسمي: https://www.python.org/downloads/
    echo  2) أثناء التثبيت فعّل خيار "Add python.exe to PATH" في الأسفل
    echo  3) بعد التثبيت شغل هذا الملف مرة أخرى
    echo.
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo [1/3] إنشاء بيئة افتراضية لأول مرة...
    python -m venv venv
    if errorlevel 1 (
        echo [خطأ] تعذر إنشاء البيئة الافتراضية.
        pause
        exit /b 1
    )
)

echo [2/3] تفعيل البيئة وتثبيت المكتبات (أول مرة قد تأخذ بضع دقائق)...
call "venv\Scripts\activate.bat"
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [خطأ] فشل تثبيت المكتبات. تحقق من اتصال الإنترنت وحاول مجددًا.
    pause
    exit /b 1
)

echo [3/3] تشغيل التطبيق...
python app.py

echo.
echo أُغلق التطبيق.
pause
