@echo off
rem TANG 3 (Windows) - kiem tra profile co hop le khong.
setlocal
cd /d "%~dp0\..\.."
python profile.py --check
echo.
pause
