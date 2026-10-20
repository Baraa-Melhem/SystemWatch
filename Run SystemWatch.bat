@echo off
REM Starts SystemWatch with no console window.
REM Tries the Anaconda interpreter first, then whatever is on PATH.

set "HERE=%~dp0"

if exist "%USERPROFILE%\anaconda3\pythonw.exe" (
    start "" "%USERPROFILE%\anaconda3\pythonw.exe" "%HERE%main.py" %*
    exit /b
)

where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw "%HERE%main.py" %*
    exit /b
)

echo Could not find pythonw.exe.
echo Edit this file and point it at your Python installation.
pause
