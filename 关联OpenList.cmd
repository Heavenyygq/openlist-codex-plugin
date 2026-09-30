@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-browser-link.ps1" %*
if errorlevel 1 (
  echo.
  echo OpenList link did not finish. See the error above.
  pause
)
