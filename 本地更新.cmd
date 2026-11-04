@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Opening SoCwiki local updater (GUI)...
echo 纯本地客户端解析：无需联网 wiki，所有页面与一图流均由本机客户端数据构建。
python -X utf8 scripts\update_client_gui.py
if errorlevel 1 (
  echo.
  echo Failed to start. Please install dependencies: pip install -r requirements.txt
  pause
)
