#!/usr/bin/env bash
# TẦNG 2 - tự áp cấu hình ổn định mỗi lần tai nghe kết nối.
#
# Cài một systemd service (chạy root vì L2CAP cần CAP_NET_RAW). Service poll
# `bluetoothctl info` mỗi 3 s và chỉ ghi khi link vừa lên - mỗi kết nối đúng
# một lần, không đập vào tai nghe liên tục.
#
#   ./2-auto-apply.sh install     # cài + bật
#   ./2-auto-apply.sh remove      # gỡ
#   ./2-auto-apply.sh status      # xem log
#
# Gỡ bằng `remove` bất cứ lúc nào; không có gì bị ghi vào firmware.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
need_device

UNIT=earphone-stabilize
SERVICE="/etc/systemd/system/$UNIT.service"
action="${1:-install}"

case "$action" in
install)
    banner "TẦNG 2 - cài tự động áp cấu hình"

    tmp="$(mktemp)"
    cat > "$tmp" <<EOF
[Unit]
Description=Apply the Earphone stability profile when the buds connect
After=bluetooth.service
Wants=bluetooth.service

[Service]
Type=simple
ExecStart=$PY $HERE/stabilize_daemon.py --mac $MAC
Restart=always
RestartSec=5
Nice=10

[Install]
WantedBy=multi-user.target
EOF

    as_root install -m 0644 "$tmp" "$SERVICE" || die "không ghi được $SERVICE"
    rm -f "$tmp"
    as_root systemctl daemon-reload
    as_root systemctl enable --now "$UNIT" || die "không bật được $UNIT"
    printf '\nĐã bật. Log:\n'
    as_root systemctl --no-pager --lines=8 status "$UNIT" || true
    printf '\nXem tiếp:  journalctl -u %s -f\n' "$UNIT"
    ;;
remove)
    banner "TẦNG 2 - gỡ tự động áp cấu hình"
    as_root systemctl disable --now "$UNIT" 2>/dev/null || true
    as_root rm -f "$SERVICE"
    as_root systemctl daemon-reload
    printf 'Đã gỡ. Cấu hình đang lưu trên tai nghe vẫn giữ nguyên.\n'
    ;;
status)
    as_root systemctl --no-pager status "$UNIT" || true
    as_root journalctl -u "$UNIT" --no-pager -n 20 || true
    ;;
*)
    die "dùng: $0 install|remove|status"
    ;;
esac
pause_if_clicked
