@echo off
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pyw -3 "%~dp0app.py"
    exit /b
)
where pythonw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pythonw "%~dp0app.py"
    exit /b
)
where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 app.py
) else (
    python app.py
)
if errorlevel 1 pause
