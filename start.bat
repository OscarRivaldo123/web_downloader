@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
  echo [Setup] Virtual environment belum ada, membuat...
  python -m venv venv || goto :err
  "venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  "venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :err
)

echo [Unduhin] Server berjalan di http://127.0.0.1:8000  ^(Ctrl+C untuk berhenti^)
start "" "http://127.0.0.1:8000"
"venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8000
goto :eof

:err
echo [Error] Setup gagal. Pastikan Python 3.10+ terpasang, lalu jalankan setup.bat.
pause
