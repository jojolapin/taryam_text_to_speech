@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if /i "%~1"=="--help" goto help
if not exist ".venv-build\Scripts\python.exe" (
  echo Run setup.bat first to prepare the build environment.
  set "RC=1"
  goto finish
)
".venv-build\Scripts\python.exe" build_exe.py --installer %*
set "RC=%ERRORLEVEL%"
:finish
if not "%RC%"=="0" echo Build failed. See the message above.
if not defined TEXTSPEAK_NO_PAUSE pause
exit /b %RC%
:help
 echo Builds the executable, portable ZIP and Windows installer.
 echo Output: dist\releases\APP_VERSION\
 echo Prerequisites: setup.bat and Inno Setup 6.
 echo build.bat --check checks prerequisites without building.
 echo Set TEXTSPEAK_NO_PAUSE=1 for unattended execution.
exit /b 0
