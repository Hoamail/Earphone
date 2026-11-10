#!/usr/bin/env bash
# TẦNG 1 - ẢNH HƯỞNG LỚN NHẤT
#
# Sửa đúng ba thứ làm tai nghe "chập chờn", trong MỘT kết nối:
#
#   0x26 AdaptiveVolume      = 2 (tắt)  -> âm lượng không tự tăng/giảm
#   0x28 ConversationDetect  = 2 (tắt)  -> không tự hạ tiếng khi bạn nói
#   0x2E AutoAncStrength     = 0 (tắt)  -> ANC không tự đổi cường độ
#   0x1B OneBudAnc           = 2 (tắt)  -> không lỗi khi tháo một tai
#
# Ghi 2 (disabled) chứ không phải 0: 0 là giá trị không hợp lệ và chính là thứ
# đã để hai control này kẹt ở trạng thái vô nghĩa trước đây.
#
# Script tự snapshot giá trị cũ trước khi ghi. Chạy `restore.sh` để trả lại.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
need_device
banner "TẦNG 1 - ổn định tai nghe ($MAC)"

printf 'Bản ghi trước khi sửa:\n'
as_root "$PY" "$LINUX/aap_l2cap.py" --mac "$MAC" read || die "không đọc được trạng thái"

printf '\nĐang áp cấu hình (1 kết nối, 4 lệnh ghi)...\n'
as_root "$PY" "$LINUX/aap_l2cap.py" --mac "$MAC" stabilize
rc=$?

if [ $rc -eq 0 ]; then
    printf '\nXong. Muốn trả lại như cũ: run/linux/1-restore.sh\n'
else
    printf '\nThất bại (mã %d). Kiểm tra tai nghe đang bật và không bị điện thoại giữ link.\n' "$rc"
fi
pause_if_clicked
exit $rc
