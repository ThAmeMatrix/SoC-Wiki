@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在打开 SoCwiki 本地更新（图形界面）…
python -X utf8 scripts\update_client_gui.py
if errorlevel 1 (
  echo.
  echo 启动失败：请先安装依赖  pip install -r requirements.txt
  pause
)
