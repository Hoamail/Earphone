#!/usr/bin/env bash
# TẦNG 3 - thử một control id chưa biết (dùng khi vọc tiếp).
#
# Thiết bị chỉ cài 4 control id; 41 id còn lại của Apple đều vắng. Script này
# để bạn tự kiểm chứng điều đó với một id bất kỳ: ghi -> xem có echo lại không.
#
#   ./3-experiment.sh 0x1A 0x0F      # ListeningModeConfigs = off|anc|trans|adapt
#   ./3-experiment.sh 0x2E 0x32      # AutoANC strength = 50
#   ./3-experiment.sh 0x39 0x0F      # Raw gestures bitmask (single|double|triple|long)
#
# KHÔNG echo = firmware không cài id đó. Có echo = id đó thật, và bạn vừa đổi
# nó -> chạy 1-restore.sh để trả lại.
#
# Script tự dump trạng thái trước khi ghi.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
need_device

CID="${1:-}"
shift || true
DATA=("$@")
[ -n "$CID" ] || die "dùng: $0 <id hex> [byte...]  ví dụ: $0 0x1A 0x0F"

banner "TẦNG 3 - thử id $CID"

snap="$LINUX/settings-before-$(date +%Y%m%d-%H%M%S).json"
printf 'Snapshot trước khi ghi -> %s\n' "$snap"
as_root "$PY" "$LINUX/aap_l2cap.py" --mac "$MAC" dump --out "$snap" >/dev/null 2>&1 \
    || printf '  (không dump được, vẫn tiếp tục)\n'

printf '\nGhi: %s %s\n' "$CID" "${DATA[*]:-}"
out="$(as_root "$PY" "$LINUX/aap_l2cap.py" --mac "$MAC" cmd "$CID" "${DATA[@]}" 2>&1)"
printf '%s\n' "$out" | tail -12

if printf '%s\n' "$out" | grep -qi "0x$(printf '%02x' "$((CID))")"; then
    printf '\n=> Có echo: firmware cài id này.\n'
else
    printf '\n=> Không echo: gần như chắc chắn firmware không cài id này.\n'
fi

printf '\nĐọc lại để chắc chắn:\n'
as_root "$PY" "$LINUX/aap_l2cap.py" --mac "$MAC" read 2>&1 | tail -8
printf '\nHoàn tác: run/linux/1-restore.sh\n'
pause_if_clicked
