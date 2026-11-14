@echo off
rem Double-click to start Latchwork on Windows.
cd /d "%~dp0"

rem Prefer the py launcher (installed with Python from python.org), then python on PATH.
set "PY="
set "PYW="
where py >nul 2>nul && (set "PY=py -3" & set "PYW=pyw -3")
if not defined PY (
    where python >nul 2>nul && (set "PY=python" & set "PYW=pythonw")
)
if not defined PY goto nopython

rem Check Python version and Tkinter with a console so problems can be read.
%PY% latchwork.py --check
if errorlevel 9009 goto nopython
if errorlevel 1 goto failed

rem Start without a console window.
start "" %PYW% latchwork.py
exit /b 0

:nopython
echo Python 3 was not found.
echo Install it from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during setup.
echo.
pause
exit /b 1

:failed
echo.
pause
exit /b 1
