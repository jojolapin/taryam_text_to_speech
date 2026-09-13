@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if /i "%~1"=="--help" goto help
if not "%~1"=="" if /i not "%~1"=="--console" (
  echo Unknown argument. Use run.bat --help.
  exit /b 1
)
if not exist ".venv-build\Scripts\pythonw.exe" (
  echo Run setup.bat first, then double-click run.bat again.
  if not defined TEXTSPEAK_NO_PAUSE pause
  exit /b 1
)
if /i "%~1"=="--console" goto console
start "TextSpeak Pro" ".venv-build\Scripts\pythonw.exe" "%~dp0main.py"
exit /b %ERRORLEVEL%
:console
".venv-build\Scripts\python.exe" "%~dp0main.py"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" if not defined TEXTSPEAK_NO_PAUSE pause
exit /b %RC%
:help
 echo Opens this checkout's application using the environment prepared by setup.bat.
 echo No packages are installed or updated when launching.
 echo run.bat --console keeps diagnostic output visible for troubleshooting.
 echo If the app is already running, use its tray menu to Show it or Quit first.
exit /b 0
