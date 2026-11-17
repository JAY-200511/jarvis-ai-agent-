@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0enable_startup.ps1"
pause
