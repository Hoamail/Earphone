#!/usr/bin/env bash
# TẦNG 3 - giải mã log HCI (btsnoop) mà không cần Wireshark.
#
# Dùng khi có log từ điện thoại (bật Bluetooth HCI snoop trong Developer
# options, bấm từng setting trong app hãng, rồi kéo log về). Đây là đường duy
# nhất còn lại để tìm một lệnh chime/gesture mà firmware này thật sự hiểu.
#
#   ./3-decode-snoop.sh                        # tự tìm log trong snoop/
#   ./3-decode-snoop.sh /path/to/btsnoop_hci.log
#   ./3-decode-snoop.sh log --controls         # chỉ frame AAP

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

LOG="${1:-}"
if [ -z "$LOG" ]; then
    LOG="$(ls -1t "$ROOT"/snoop/*.log "$ROOT"/snoop/*.btsnoop 2>/dev/null | head -1)"
fi
[ -n "$LOG" ] && [ -f "$LOG" ] || die "không thấy log. Dùng: $0 <file btsnoop>"
shift || true

banner "TẦNG 3 - giải mã $(basename "$LOG")"
printf 'Kích thước: %s\n\n' "$(du -h "$LOG" | cut -f1)"

printf '--- SDP (dịch vụ, PSM, kênh RFCOMM) ---\n'
"$PY" "$ROOT/btsnoop.py" "$LOG" records 2>&1 | head -40

printf '\n--- frame AAP + id lạ ---\n'
"$PY" "$LINUX/aap_from_snoop.py" "$LOG" --only-controls 2>&1 | tail -30

printf '\nGhi chú: id nào bị đánh dấu lạ = firmware thật sự hiểu nó. Đó là thứ\n'
printf 'không lấy được từ kết nối trực tiếp.\n'
pause_if_clicked
