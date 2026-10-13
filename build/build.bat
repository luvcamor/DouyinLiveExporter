@echo off
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)
%PYTHON% -m PyInstaller --noconfirm --onefile --collect-all imageio_ffmpeg --collect-all pillow_heif --distpath dist\DouyinLiveExporter_v1 --name DouyinLiveExporter src\DouyinLiveExporter.py
if errorlevel 1 exit /b 1
copy /Y config.json dist\DouyinLiveExporter_v1\config.json >nul
copy /Y README.md dist\DouyinLiveExporter_v1\README.md >nul
pause
