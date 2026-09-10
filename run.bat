@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo MPSS Pilot
echo.

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  set "PY=py"
) else (
  where python >nul 2>&1
  if %ERRORLEVEL%==0 (
    set "PY=python"
  ) else (
    echo Python was not found.
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH".
    pause
    exit /b 1
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Failed to create .venv
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -c "import streamlit, pymodbus, pycomm3" >nul 2>&1
if errorlevel 1 (
  echo Installing dependencies ^(first run can take a few minutes^)...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo pip install failed. Check your network connection and try again.
    pause
    exit /b 1
  )
)

echo Starting SoftPLC on 127.0.0.1:5502 ...
start "MPSS SoftPLC" ".venv\Scripts\python.exe" soft_plc.py

echo Starting Streamlit UI ...
echo.
echo The UI opens in your browser ^(usually http://localhost:8501^).
echo Close this window to stop the UI.
echo Close the "MPSS SoftPLC" window to stop the SoftPLC.
echo Windows Firewall may ask to allow Python — allow it on private networks.
echo.
".venv\Scripts\python.exe" -m streamlit run app.py

echo.
echo Streamlit has stopped.
pause
