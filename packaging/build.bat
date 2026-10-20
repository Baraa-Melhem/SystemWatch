@echo off
REM SPDX-License-Identifier: GPL-3.0-or-later
REM Builds release\SystemWatch-Setup-<version>.exe from the source in this repo.
REM First run creates a private build venv in packaging\.buildenv; the Python
REM it is made from is never modified.
REM
REM Needs Python 3.11 (64-bit) and Inno Setup 6. Set SW_PYTHON to pick a
REM specific interpreter; otherwise Anaconda, then the py launcher, then the
REM python on PATH are tried in that order.

setlocal
set "HERE=%~dp0"
set "VENV=%HERE%.buildenv"

if not exist "%VENV%\Scripts\python.exe" (
    set "BASE="
    if defined SW_PYTHON set "BASE=%SW_PYTHON%"
    if not defined BASE if exist "%USERPROFILE%\anaconda3\python.exe" set "BASE=%USERPROFILE%\anaconda3\python.exe"
    if not defined BASE (
        py -3.11 -c "" >nul 2>&1 && set "BASE=py -3.11"
    )
    if not defined BASE set "BASE=python"
    call :make_venv || exit /b 1
)

"%VENV%\Scripts\python.exe" "%HERE%build.py"
exit /b %errorlevel%

:make_venv
echo Creating build environment with %BASE% ...
%BASE% -m venv "%VENV%" || (echo Could not create a venv. Set SW_PYTHON to a Python 3.11. & exit /b 1)
"%VENV%\Scripts\python.exe" -m pip install -q -r "%HERE%requirements-build.txt" || exit /b 1
exit /b 0
