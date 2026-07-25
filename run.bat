@echo off
echo =========================================
echo ZKTeco ADMS Server - Starting up...
echo =========================================
echo.

if not exist venv (
    echo [!] Creating virtual environment...
    python -m venv venv
    echo [!] Installing dependencies...
    venv\Scripts\pip install -r requirements.txt
)

echo [!] Starting server on port 8000...
echo [!] Please open your browser and go to: http://localhost:8000
echo [!] Press Ctrl+C to stop the server.
echo.

venv\Scripts\uvicorn main:app --host 0.0.0.0 --port 8000
pause
