@echo off
setlocal
cd /d "%~dp0"
set "BASE_PY=%~dp0..\.venv-build\Scripts\python.exe"
if not exist "%BASE_PY%" (
  echo TextSpeak Pro build environment was not found. Run setup.bat in the project folder first.
  exit /b 1
)
echo Creating the Pocket TTS runtime next to this script.
"%BASE_PY%" -m venv "%~dp0.venv"
if errorlevel 1 exit /b 1
"%~dp0.venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
"%~dp0.venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 exit /b 1
echo.
echo Pocket TTS runtime is ready.
echo Remove this feature by deleting the clone_runtime\.venv folder.
echo The main TextSpeak Pro environment was not changed.
exit /b 0
