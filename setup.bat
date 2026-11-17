@echo off
setlocal
cd /d "%~dp0"
where ollama >nul 2>nul
if errorlevel 1 (
  echo Ollama is needed for free, local AI. No pip packages are required by JARVIS.
  echo Install the Ollama Windows app once, then run this file again.
  start "" "https://ollama.com/download/windows"
  pause
  exit /b 1
)
echo Downloading the local Qwen 3.5 4B model (about 3-4 GB, one time)...
ollama pull qwen3.5:4b
if errorlevel 1 (
  echo Model download did not finish. Check Ollama and run setup.bat again.
  pause
  exit /b 1
)
echo.
echo JARVIS setup is ready. Start it with start_jarvis.bat.
pause
