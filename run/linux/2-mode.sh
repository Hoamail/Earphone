#!/usr/bin/env bash
# TẦNG 2 - đổi chế độ chống ồn bằng một cú click.
#
#   ./2-mode.sh            -> đảo giữa ANC và Transparency
#   ./2-mode.sh anc        -> bật chống ồn
#   ./2-mode.sh trans      -> xuyên âm
#   ./2-mode.sh off        -> tắt
#   ./2-mode.sh adapt      -> adaptive
#
# Giá trị là 1-based: 1 off, 2 anc, 3 transparency, 4 adaptive.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
need_device
want="${1:-toggle}"

banner "TẦNG 2 - chế độ chống ồn ($MAC)"

if [ "$want" = "toggle" ]; then
    cur="$(as_root "$PY" "$LINUX/aap_l2cap.py" --mac "$MAC" read 2>/dev/null \
        | awk '/ListeningMode/{print $2}' | head -1)"
    case "$cur" in
        2) want=trans ;;
        3) want=anc ;;
        *) want=anc ;;
    esac
    printf 'Đang ở %s -> chuyển sang %s\n' "${cur:-?}" "$want"
fi

as_root "$PY" "$LINUX/aap_l2cap.py" --mac "$MAC" mode "$want"
rc=$?
pause_if_clicked
exit $rc
