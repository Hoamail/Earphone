@echo off
rem TANG 2 (Windows) - chay nen: quang cao nao hien la bi giet trong ~1 ms.
rem Chen MutationObserver vao trang, tu chen lai sau moi lan load.
setlocal
cd /d "%~dp0\..\.."
echo Dang theo doi tab YouTube. Dong cua so nay de dung.
echo.
python linux\yt_ad.py --watch
pause
