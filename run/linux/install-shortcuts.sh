#!/usr/bin/env bash
# Tạo shortcut bấm-được cho tất cả script trong run/linux.
#
# Cài vào ~/.local/share/applications (hiện trong menu ứng dụng) và ~/Desktop
# (nếu bạn dùng desktop có icon). Exec trỏ tuyệt đối tới thư mục hiện tại của
# repo, nên nếu bạn di chuyển repo thì chạy lại script này.
#
#   ./install-shortcuts.sh            # cài
#   ./install-shortcuts.sh remove     # gỡ

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

APPS="$HOME/.local/share/applications"
DESK="$HOME/Desktop"
action="${1:-install}"

declare -A TITLE=(
  ["1-fix-instability"]="Tai nghe: ổn định (tầng 1)"
  ["1-restore"]="Tai nghe: hoàn tác cấu hình"
  ["2-battery"]="Tai nghe: pin"
  ["2-mode"]="Tai nghe: đổi chống ồn"
  ["2-auto-apply"]="Tai nghe: tự áp khi kết nối"
  ["2-tap-skip"]="Tai nghe: chạm = bỏ quảng cáo"
  ["3-monitor"]="Tai nghe: theo dõi link"
  ["3-experiment"]="Tai nghe: thử control id"
  ["3-decode-snoop"]="Tai nghe: giải mã log HCI"
)
declare -A COMMENT=(
  ["1-fix-instability"]="Ghi 4 control trong một kết nối: tắt Adaptive Volume, Conversation Detect, AutoANC drift, OneBud ANC"
  ["1-restore"]="Nạp lại snapshot trước khi sửa"
  ["2-battery"]="Đọc pin tai trái, tai phải, hộp"
  ["2-mode"]="Đảo giữa ANC và Transparency"
  ["2-auto-apply"]="Cài systemd service tự áp cấu hình mỗi lần kết nối"
  ["2-tap-skip"]="Theo dõi MPRIS: chạm tai nghe để bỏ quảng cáo YouTube"
  ["3-monitor"]="Ghi log 10 phút để tìm nguyên nhân ngắt kết nối"
  ["3-experiment"]="Ghi thử một control id và xem thiết bị có echo"
  ["3-decode-snoop"]="Giải mã log HCI từ điện thoại"
)

write_desktop() {
    local name="$1" dir="$2"
    local file="$dir/earphone-$name.desktop"
    cat > "$file" <<EOF
[Desktop Entry]
Type=Application
Name=${TITLE[$name]}
Comment=${COMMENT[$name]}
Exec=$HERE/$name.sh
Path=$HERE
Icon=audio-headphones
Terminal=true
Categories=Utility;AudioVideo;
EOF
    chmod +x "$file"
}

case "$action" in
install)
    mkdir -p "$APPS"
    for name in "${!TITLE[@]}"; do
        chmod +x "$HERE/$name.sh" 2>/dev/null
        write_desktop "$name" "$APPS"
        if [ -d "$DESK" ]; then
            write_desktop "$name" "$DESK"
            gio set "$DESK/earphone-$name.desktop" metadata::trusted true 2>/dev/null || true
        fi
    done
    printf 'Đã cài %d shortcut vào:\n  %s\n' "${#TITLE[@]}" "$APPS"
    [ -d "$DESK" ] && printf '  %s\n' "$DESK"
    printf '\nMở menu ứng dụng, gõ "Tai nghe".\n'
    ;;
remove)
    for name in "${!TITLE[@]}"; do
        rm -f "$APPS/earphone-$name.desktop" "$DESK/earphone-$name.desktop"
    done
    printf 'Đã gỡ shortcut.\n'
    ;;
*)
    die "dùng: $0 install|remove"
    ;;
esac
pause_if_clicked
