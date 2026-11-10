@echo off
rem TANG 2 (Windows) - bo quang cao dang chieu ngay bay gio, mot lan.
rem Can Edge/Chrome dang chay voi --remote-debugging-port (xem 2-start-edge-debug.cmd).
setlocal
cd /d "%~dp0\..\.."
python linux\yt_ad.py --status
echo.
python linux\yt_ad.py
echo.
pause
