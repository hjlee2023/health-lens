@echo off
chcp 65001 >nul
REM Keep this file saved with CRLF line endings - LF-only breaks the batch parser

REM --- 1) Start the Ollama server if it isn't already running ---
set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
netstat -ano | findstr ":11434" | findstr LISTENING >nul
if errorlevel 1 (
  echo [HealthLens] Starting Ollama server...
  start "Ollama" /B "%OLLAMA_EXE%" serve
  REM Wait up to 30 seconds for the port to open
  for /l %%i in (1,1,15) do (
    timeout /t 2 /nobreak >nul
    netstat -ano | findstr ":11434" | findstr LISTENING >nul && goto :ollama_ready
  )
  echo [HealthLens] Warning: Ollama did not come up within 30 seconds.
) else (
  echo [HealthLens] Ollama already running
)
:ollama_ready

REM --- 2) Kill any old server still holding port 8000 ---
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
  echo [HealthLens] Killing existing server PID %%a
  taskkill /F /PID %%a >nul 2>&1
)

REM --- 3) Start the backend ---
pushd "%~dp0backend"
echo ================================================
echo  HealthLens backend  -^>  http://localhost:8000
echo  Stop: press Ctrl+C in this window
echo ================================================
python -m uvicorn main:app --port 8000
popd
pause
