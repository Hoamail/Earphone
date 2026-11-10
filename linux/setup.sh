#!/bin/bash
# setup.sh - prepare Linux Mint to talk AAP to the earbuds, then dump state.
#
# Why Linux: Windows' MediaTek stack refuses user-space L2CAP client sockets
# (every PSM, including 0x0003, returns WSAE10050). BlueZ opens PSM 0x1001
# normally. The accessory does announce it: Android's HCI log shows
#   74ec2172-0bad-4d01-8f77-997b2be0722a  "AAP Server"  L2CAP psm 0x1001
#
#   chmod +x setup.sh
#   ./setup.sh                 # everything
#   ./setup.sh --no-install    # skip apt, just do the Bluetooth part
#
# The MAC below is the one measured on this pair of buds; override with MAC=..

set -uo pipefail

MAC="${MAC:-41:42:23:76:ED:B8}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL=1
[ "${1:-}" = "--no-install" ] && INSTALL=0

say() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

if [ "$INSTALL" = 1 ]; then
    say "packages"
    sudo apt-get update -qq
    sudo apt-get install -y bluez bluez-tools rfkill python3
fi

say "radio"
sudo rfkill unblock bluetooth
sudo systemctl enable --now bluetooth
sleep 1
if have bluetoothctl; then
    bluetoothctl show | sed -n '1,12p'
fi

say "is the accessory reachable?"
# It must not be held by another host. Take it out of the case, close the lid
# of any other paired device, and make sure Windows has released it.
if have bluetoothctl; then
    bluetoothctl --timeout 15 scan on 2>/dev/null | grep -i -m1 "Pro NewGen" \
        && echo "seen" || echo "NOT seen in 15s - power the buds / free them from Windows"
fi

say "pair + trust"
# Safe to repeat: if it is already paired this is a no-op.
if have bluetoothctl; then
    bluetoothctl --timeout 20 pair "$MAC"  || true
    bluetoothctl --timeout 10 trust "$MAC" || true
    bluetoothctl --timeout 10 connect "$MAC" 2>/dev/null || true
fi

say "SDP: what does it actually announce?"
if have sdptool; then
    sudo sdptool browse "$MAC" | sed -n '/Service Name/,+12p'
else
    echo "sdptool missing (bluez-tools) - skipping"
fi

say "AAP: dump device state (read-only, nothing is written)"
# L2CAP needs CAP_NET_RAW, so: sudo. The dump is deliberately read-only.
sudo python3 "$HERE/aap_l2cap.py" --mac "$MAC" --seconds 12 dump --out "$HERE/device-state.json"

cat <<'EOF'

Next, and only after reading device-state.json:

  sudo python3 aap_l2cap.py --mac 41:42:23:76:ED:B8 anc anc
  sudo python3 aap_l2cap.py --mac 41:42:23:76:ED:B8 anc off
  sudo python3 aap_l2cap.py --mac 41:42:23:76:ED:B8 cmd 0x1A 0x0F
  sudo python3 aap_l2cap.py --mac 41:42:23:76:ED:B8 raw "04000400 0D00 02 00000000"

If the handshake prints "no ACK", stop: the channel opened but the accessory is
not speaking AAP on it, and every command after that is guesswork.
EOF
