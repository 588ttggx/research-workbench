@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0工具\科研流程\distribution\Launch.ps1" -Action start %*
if errorlevel 1 pause
