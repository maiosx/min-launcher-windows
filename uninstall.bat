@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File uninstall.ps1
pause
