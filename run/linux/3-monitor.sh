#!/usr/bin/env bash
# TẦNG 3 - theo dõi link và ghi log.
#
# Bắt: socket rơi, control đổi liên tục (>=3 lần), pin nhảy bất thường.
# Dùng để trả lời "tại sao nó lại ngắt" bằng dữ liệu, không bằng cảm giác.
#
#   ./3-monitor.sh            # 10 phút
#   ./3-monitor.sh 60         # 60 phút
#
# Log: ~/earphone-monitor.log

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
need_device
MINUTES="${1:-10}"
LOG="$HOME/earphone-monitor.log"

banner "TẦNG 3 - theo dõi $MINUTES phút ($MAC)"
printf 'Log: %s\n\n' "$LOG"

as_root "$PY" "$LINUX/aap_l2cap.py" --mac "$MAC" --minutes "$MINUTES" monitor 2>&1 | tee -a "$LOG"
pause_if_clicked
