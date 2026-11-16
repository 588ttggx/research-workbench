@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install.ps1" %*
set "INSTALL_RESULT=%ERRORLEVEL%"
if not "%INSTALL_RESULT%"=="0" echo Installation did not finish. The message above explains the next step.
if "%~1"=="" pause
exit /b %INSTALL_RESULT%
