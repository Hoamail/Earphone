@echo off
rem TANG 2 (Windows) - mo Edge co cong debug, de bo quang cao YouTube.
rem Profile rieng, khong dung profile that cua ban.
setlocal
set PORT=9222
set PROFILE=%USERPROFILE%\.config\yt-ad-prof

if not exist "%PROFILE%" mkdir "%PROFILE%"

set EDGE="%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist %EDGE% set EDGE="%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not exist %EDGE% (
    echo Khong tim thay Microsoft Edge.
    echo Sua duong dan trong file nay, hoac dung Chrome/Chromium/Brave:
    echo   chrome.exe --remote-debugging-port=%PORT% --user-data-dir=...
    pause
    exit /b 1
)

echo Dang mo Edge voi cong debug %PORT% ...
start "" %EDGE% --remote-debugging-port=%PORT% --user-data-dir="%PROFILE%" --no-first-run
echo.
echo Xong. Mo youtube.com trong cua so vua hien ra, roi chay:
echo   run\windows\2-skip-ads-watch.cmd
exit /b 0
