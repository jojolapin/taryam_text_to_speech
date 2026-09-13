@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if /i "%~1"=="--help" goto help
if not "%~1"=="" (
  echo Unknown argument. Use setup.bat --help.
  exit /b 1
)
if exist ".venv-build\Scripts\python.exe" goto validate
py -3.13 -c "import struct; assert struct.calcsize('P') == 8" >nul 2>&1
if not errorlevel 1 (
  py -3.13 -m venv .venv-build
  if errorlevel 1 goto failed
  goto validate
)
python -c "import sys, struct; assert sys.version_info[:2] == (3, 13) and struct.calcsize('P') == 8" >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.13 for Windows x64 from https://www.python.org/downloads/windows/
  echo Include the Python launcher, then run setup.bat again.
  goto failed
)
python -m venv .venv-build
if errorlevel 1 goto failed
:validate
".venv-build\Scripts\python.exe" -c "import sys, struct; assert sys.version_info[:2] == (3, 13) and struct.calcsize('P') == 8, 'This setup requires Python 3.13 x64. Rename the existing .venv-build and rerun setup.bat.'"
if errorlevel 1 goto failed
".venv-build\Scripts\python.exe" -m pip --version >nul 2>&1
if errorlevel 1 (
  ".venv-build\Scripts\python.exe" -m ensurepip
  if errorlevel 1 goto failed
)
echo Installing the tested runtime and build dependencies...
".venv-build\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-windows-lock.txt
if errorlevel 1 goto failed
".venv-build\Scripts\python.exe" -m pip check
if errorlevel 1 goto failed
".venv-build\Scripts\python.exe" -c "from PySide6 import QtCore, QtWidgets, QtMultimedia; import piper, lameenc, mutagen, pypdf, requests, PyInstaller; print('Application dependencies are ready.')"
if errorlevel 1 goto failed
echo.
echo Setup complete. Double-click run.bat to open TextSpeak Pro.
echo To create packages, install Inno Setup 6 from https://jrsoftware.org/isdl.php
echo and double-click build.bat.
set "RC=0"
goto finish
:failed
echo Setup failed. See the message above, correct the problem and rerun setup.bat.
set "RC=1"
:finish
if not defined TEXTSPEAK_NO_PAUSE pause
exit /b %RC%
:help
 echo Prepares .venv-build with the tested Python 3.13 x64 dependencies.
 echo Run once before run.bat or build.bat. Internet is needed to download packages.
 echo Safe to rerun; existing documents, settings and voices are preserved.
 echo Set TEXTSPEAK_NO_PAUSE=1 for unattended execution.
exit /b 0
