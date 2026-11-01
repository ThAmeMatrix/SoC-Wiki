@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Opening SoCwiki local updater (GUI)...
python -X utf8 scripts\update_client_gui.py
if errorlevel 1 (
  echo.
  echo Failed to start. Please install dependencies: pip install -r requirements.txt
  pause
)
