@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 铃兰档案馆 · 本地更新：打开图形界面后本窗口自动关闭。
where pythonw >nul 2>nul
if %errorlevel%==0 (
  python -X utf8 -c "import tkinter, PIL, UnityPy" >nul 2>nul
  if not errorlevel 1 (
    start "" pythonw -X utf8 scripts\update_client_gui.py
    exit /b 0
  )
)
python -X utf8 scripts\update_client_gui.py
if errorlevel 1 (
  echo.
  echo 本地更新工具没有启动。请先安装依赖：
  echo     python -m pip install -r requirements.txt
  echo 详细原因见 output\client-update.log
  pause
)
