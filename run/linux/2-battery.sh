#!/usr/bin/env bash
# TẦNG 2 - pin còn bao nhiêu, nhanh.
#
# Đọc cả frame pin mà tai nghe đẩy lên (L / R / hộp) và in ra gọn.
# Cần ~10 s vì bản thân tai nghe chờ 6-9 s mới chịu nói.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
need_device
banner "TẦNG 2 - pin ($MAC)"

out="$(as_root "$PY" "$LINUX/aap_l2cap.py" --mac "$MAC" --seconds 10 probe 2>&1)"
rc=$?

if [ $rc -ne 0 ]; then
    printf '%s\n' "$out" | tail -5
    die "không đọc được pin (tai nghe tắt, trong hộp, hoặc điện thoại đang giữ link?)"
fi

line="$(printf '%s\n' "$out" | grep -m1 'battery')"
if [ -z "$line" ]; then
    printf '%s\n' "$out" | tail -8
    die "không thấy frame pin"
fi

printf '  %s\n' "$line"
printf '\nĐọc từ frame 0x04; trạng thái: 01 charging, 02 discharging, 04 disconnected.\n'
pause_if_clicked
