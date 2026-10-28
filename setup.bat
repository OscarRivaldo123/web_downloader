@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python tidak ditemukan. Instal Python 3.10+ dari python.org terlebih dahulu.
  pause
  exit /b 1
)

if not exist "venv\Scripts\python.exe" (
  echo [1/3] Membuat virtual environment...
  python -m venv venv || (echo Gagal membuat venv. & pause & exit /b 1)
  echo [2/3] Memasang dependensi...
  "venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  "venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo Gagal memasang dependensi. & pause & exit /b 1)
) else (
  echo [2/3] Dependensi sudah terpasang.
)

where ffmpeg >nul 2>nul
if errorlevel 1 if not exist "bin\ffmpeg.exe" (
  echo [3/3] Mengunduh ffmpeg ^(sekali saja, sekitar 90 MB^)...
  if not exist bin mkdir bin
  curl -L -o ff.zip https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip || (echo Gagal mengunduh ffmpeg. & pause & exit /b 1)
  powershell -NoProfile -Command "Expand-Archive -Path ff.zip -DestinationPath ff -Force; Copy-Item 'ff\ffmpeg*\bin\ffmpeg.exe','ff\ffmpeg*\bin\ffprobe.exe' bin\; Remove-Item ff.zip; Remove-Item ff -Recurse -Force"
  if not exist "bin\ffmpeg.exe" (echo Gagal menyiapkan ffmpeg. Instal manual lalu jalankan ulang. & pause & exit /b 1)
) else (
  echo [3/3] ffmpeg sudah tersedia.
)

echo Setup selesai. Jalankan start.bat untuk memulai.
pause
