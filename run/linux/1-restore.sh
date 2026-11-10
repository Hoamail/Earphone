#!/usr/bin/env bash
# TẦNG 1 - trả lại cấu hình trước khi "ổn định".
#
# `stabilize` ghi snapshot ra file; script này nạp lại đúng snapshot đó.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
need_device
banner "TẦNG 1 - hoàn tác cấu hình ($MAC)"

# stabilize ghi `settings-before-<timestamp>.json`; lấy bản mới nhất.
snap="$(ls -1t "$LINUX"/settings-before-*.json 2>/dev/null | head -1)"
if [ -z "$snap" ]; then
    die "không có snapshot nào trong $LINUX (chưa chạy 1-fix-instability.sh?)"
fi
printf 'Dùng snapshot: %s\n\n' "$snap"

as_root "$PY" "$LINUX/aap_l2cap.py" --mac "$MAC" restore "$snap"
rc=$?
[ $rc -eq 0 ] && printf '\nĐã trả lại giá trị trước khi sửa.\n'
pause_if_clicked
exit $rc
