@echo off
rem ============================================================
rem  TextSpeak Pro - Windows developer launcher
rem  (C) 2026 JojoLapin Inc.
rem ============================================================
setlocal ENABLEEXTENSIONS ENABLEDELAYEDEXPANSION

cd /d "%~dp0"

set "VENV=.venv"
set "PY="

rem Prefer Python 3.13, then 3.12, then 3.11, then whatever's first
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

rem Create venv on first run
if not exist "%VENV%\Scripts\python.exe" (
  echo Creating virtual environment...
  %PY% -m venv "%VENV%"
  if errorlevel 1 (
    echo   Failed to create virtual environment.
    pause
    exit /b 1
  )
)

set "VPY=%VENV%\Scripts\python.exe"

rem Bootstrap pip
"%VPY%" -m pip --version >nul 2>&1
if errorlevel 1 "%VPY%" -m ensurepip --upgrade

rem Install / upgrade deps (quiet unless something changes)
"%VPY%" -m pip install --upgrade --quiet pip wheel
"%VPY%" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
  echo   Failed to install runtime requirements.
  pause
  exit /b 1
)

echo Launching TextSpeak Pro...
"%VPY%" main.py
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo   TextSpeak Pro exited with code %RC%.
  pause
)
exit /b %RC%
