@echo off
rem TANG 3 (Windows) - xuat bao cao HTML tu profile va mo bang trinh duyet.
setlocal
cd /d "%~dp0\..\.."
python profile.py --html report.html
if errorlevel 1 (
    echo Khong tao duoc report.html
    pause
    exit /b 1
)
start "" report.html
exit /b 0
