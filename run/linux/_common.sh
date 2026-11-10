#!/usr/bin/env bash
# _common.sh - shared bits for the click-to-run scripts.
# Sourced, never executed directly.

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
LINUX="$ROOT/linux"
PROFILE="$ROOT/device-profile.json"
PY="${PYTHON:-python3}"

# MAC comes from the captured profile so there is one place to change it.
MAC="${EARPHONE_MAC:-}"
if [ -z "$MAC" ] && [ -f "$PROFILE" ]; then
    MAC="$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1])).get('device',{}).get('mac',''))" "$PROFILE" 2>/dev/null)"
fi
MAC="${MAC:-41:42:23:76:ED:B8}"

# One place for sudo: the password is not stored, sudo caches per terminal.
as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif sudo -n true 2>/dev/null; then
        sudo "$@"
    else
        printf 'Cần mật khẩu sudo để mở L2CAP (CAP_NET_RAW).\n'
        sudo "$@"
    fi
}

pause_if_clicked() {
    # Only pause when there is no terminal attached (double-click from a file manager).
    if [ ! -t 0 ] || [ "${1:-}" = "--pause" ]; then
        printf '\nNhấn Enter để đóng...'
        read -r _ || true
    fi
}

die() { printf 'LỖI: %s\n' "$*" >&2; exit 1; }

need_device() {
    command -v bluetoothctl >/dev/null 2>&1 || die "không có bluetoothctl (cài bluez)"
    [ -f "$LINUX/aap_l2cap.py" ] || die "không thấy $LINUX/aap_l2cap.py"
}

banner() {
    printf '\n=== %s ===\n' "$*"
}
