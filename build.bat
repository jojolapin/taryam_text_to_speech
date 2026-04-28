@echo off
rem ============================================================
rem  TextSpeak Pro - Windows one-click build script
rem  Double-click me to produce:
rem      dist\TextSpeakPro.exe              (single-file app)
rem      dist\TextSpeakPro.sha256           (integrity checksum)
rem      dist\TextSpeakPro-portable.zip     (ready-to-share portable bundle)
rem  (C) 2026 JojoLapin Inc.
rem ============================================================
setlocal ENABLEEXTENSIONS ENABLEDELAYEDEXPANSION

cd /d "%~dp0"

set "VENV=.venv-build"
set "PY="

rem Prefer Python 3.13 -> 3.12 -> 3.11, then whatever's on PATH
for %%V in (3.13 3.12 3.11) do (
  if not defined PY (
    py -%%V -c "import sys; sys.exit(0)" >nul 2>&1
    if !ERRORLEVEL! == 0 set "PY=py -%%V"
  )
)
if not defined PY (
  python --version >nul 2>&1
  if !ERRORLEVEL! == 0 set "PY=python"
)
if not defined PY (
  echo.
  echo   Python 3.11+ is required but was not found on PATH.
  echo   Install it from https://www.python.org/downloads/ and retry.
  echo.
  pause
  exit /b 1
)

rem Dedicated build venv so PyInstaller + Pillow never pollute the run venv
if not exist "%VENV%\Scripts\python.exe" (
  echo Creating build virtual environment...
  %PY% -m venv "%VENV%"
  if errorlevel 1 (
    echo   Failed to create build virtual environment.
    pause
    exit /b 1
  )
)

set "VPY=%VENV%\Scripts\python.exe"

echo Installing runtime + build dependencies...
"%VPY%" -m pip install --upgrade --quiet pip wheel
"%VPY%" -m pip install --quiet -r requirements.txt -r requirements-build.txt
if errorlevel 1 (
  echo   Failed to install build requirements.
  pause
  exit /b 1
)

echo.
echo Building single-file executable (this takes 1-3 minutes)...
echo.
"%VPY%" build_exe.py
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo   Done. Look in the dist\ folder:
  echo     - TextSpeakPro.exe                ^<- double-clickable app
  echo     - TextSpeakPro.sha256             ^<- checksum (verify downloads)
  echo     - TextSpeakPro-portable.zip       ^<- ship this to another PC
  echo.
  start "" "%~dp0dist"
) else (
  echo   Build failed with code %RC%.
)

pause
exit /b %RC%
