#!/usr/bin/env bash
# TẦNG 2 - cú chạm tai nghe -> bỏ quảng cáo YouTube.
#
# Tai nghe gửi AVRCP PlayPause khi bạn chạm. Trình phát nhận nó và đổi trạng
# thái sang Paused. Script này bắt đúng tín hiệu đó qua D-Bus MPRIS: nếu tab
# YouTube đang chiếu quảng cáo, nó bỏ quảng cáo rồi cho video chạy tiếp; nếu
# không có quảng cáo, cú chạm giữ nguyên ý nghĩa pause như cũ.
#
# Điều kiện: trình duyệt phải chạy với --remote-debugging-port.
#
#   ./2-tap-skip.sh              # chạy nền, Ctrl-C để dừng
#   ./2-tap-skip.sh --once       # bắt một lần rồi thoát (để thử)
#
# Không phân biệt được tai trái/phải: cả hai gửi cùng một PlayPause.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
PORT="${CDP_PORT:-9222}"
MATCH="${CDP_MATCH:-youtube.com}"

banner "TẦNG 2 - chạm tai nghe = bỏ quảng cáo"

if ! "$PY" "$LINUX/yt_ad.py" --port "$PORT" --status >/dev/null 2>&1; then
    die "không thấy trình duyệt ở cổng $PORT. Bật bằng:
  microsoft-edge --remote-debugging-port=$PORT --user-data-dir=\$HOME/.config/yt-ad-prof"
fi

"$PY" - "$PORT" "$MATCH" "$LINUX" "${1:-}" <<'PYEOF'
import subprocess, sys, time

port, match, linux, once = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
sys.path.insert(0, linux)
import yt_ad


def ad_state():
    try:
        tab = yt_ad.find_target("127.0.0.1", int(port), match)
    except OSError:
        return None, None
    if not tab:
        return None, None
    try:
        return tab, yt_ad.evaluate(tab, yt_ad.AD_JS)
    except (OSError, RuntimeError):
        return tab, None


tab, res = ad_state()
if tab and res:
    print(f"tab  : {tab['url']}")
    print(f"state: ad={res.get('ad')} ({res.get('state')})")
else:
    print("chưa thấy tab YouTube nào")

proc = subprocess.Popen(
    ["dbus-monitor", "--session",
     "type='signal',interface='org.mpris.MediaPlayer2.Player',member='PropertiesChanged'"],
    stdout=subprocess.PIPE, text=True, bufsize=1)
print("đang chờ cú chạm... (Ctrl-C để dừng)\n")

try:
    for line in proc.stdout:
        if "PlaybackStatus" not in line or "Paused" not in line:
            continue
        tab, res = ad_state()
        if not tab or not res:
            continue
        if not res.get("ad"):
            print(f"{time.strftime('%H:%M:%S')}  chạm -> pause bình thường")
        else:
            out = yt_ad.evaluate(tab, yt_ad.AD_JS)
            print(f"{time.strftime('%H:%M:%S')}  chạm -> quảng cáo: {out.get('state')}")
            yt_ad.evaluate(tab, "(()=>{const v=document.querySelector('video');"
                                "if(v&&v.paused)v.play().catch(()=>{});return 1})()")
        if once == "--once":
            break
finally:
    proc.terminate()
PYEOF

pause_if_clicked
