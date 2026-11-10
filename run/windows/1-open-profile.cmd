@echo off
rem TANG 1 (Windows) - xem du lieu da bat duoc tren Linux.
rem Windows khong mo duoc L2CAP PSM 0x1001, nen day la cach doc tai nghe
rem tren may nay: profile do Linux dung san.
setlocal
cd /d "%~dp0\..\.."
python profile.py %*
echo.
pause
