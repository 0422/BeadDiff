@echo off
rem 2026-10-10: Start the desktop app with the existing learner interpreter.
setlocal
set "BEADDIFF_PYTHON=E:\pySpace\anaconda\envs\learner\python.exe"
if not exist "%BEADDIFF_PYTHON%" (
    echo learner Python was not found. Activate learner and run python main.py.
    pause
    exit /b 1
)
cd /d "%~dp0"
"%BEADDIFF_PYTHON%" -B main.py
set "BEADDIFF_EXIT=%ERRORLEVEL%"
if not "%BEADDIFF_EXIT%"=="0" pause
exit /b %BEADDIFF_EXIT%
