@echo off
setlocal
cd /d "%~dp0"
echo Starting local JARVIS at http://127.0.0.1:8765
python jarvis_server.py
pause
