#!/bin/bash
# preflight.sh - check the five things that actually break this, before you run
# anything that writes to the earbuds. Read-only.
#
#   chmod +x preflight.sh && ./preflight.sh

MAC="${MAC:-41:42:23:76:ED:B8}"
say() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
ok()  { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; }
warn(){ printf '  \033[33mWARN\033[0m %s\n' "$*"; }

say "1. adapter"
if ! command -v bluetoothctl >/dev/null; then
    bad "bluez not installed: sudo apt install bluez bluez-tools"
    exit 1
fi
CTRL="$(bluetoothctl list 2>/dev/null)"
if [ -z "$CTRL" ]; then
    bad "no Bluetooth controller. Check: dmesg | grep -i -E 'btusb|firmware'"
    echo "     MediaTek needs firmware: sudo apt install linux-firmware && sudo modprobe -r btusb && sudo modprobe btusb"
    echo "     If that fails, a USB dongle (CSR 4.0 / Realtek RTL8761) works out of the box."
    exit 1
fi
echo "$CTRL" | sed 's/^/     /'
ok "controller present"

if command -v rfkill >/dev/null && rfkill list bluetooth | grep -q "Soft blocked: yes"; then
    bad "soft-blocked: sudo rfkill unblock bluetooth"
else
    ok "not rfkill-blocked"
fi

say "2. who owns the link right now"
bluetoothctl show 2>/dev/null | grep -E "Powered|Discovering" | sed 's/^/     /'
INFO="$(bluetoothctl info "$MAC" 2>/dev/null)"
if echo "$INFO" | grep -q "Connected: yes"; then
    ok "connected to $MAC"
else
    warn "not connected - normal before pairing; must be freed from Windows AND phone"
fi
echo "$INFO" | grep -E "Paired:|Trusted:|Name:" | sed 's/^/     /'

say "3. does it answer pings (is it awake)"
if command -v l2ping >/dev/null; then
    if sudo l2ping -c 2 -t 4 "$MAC" >/dev/null 2>&1; then
        ok "L2CAP echo answered - radio link works"
    else
        warn "no echo: buds asleep / in case / held by another host. Open the case, take them out."
    fi
else
    warn "l2ping missing (apt install bluez) - skipping"
fi

say "4. does it still announce AAP Server"
if command -v sdptool >/dev/null; then
    if sudo sdptool browse "$MAC" 2>/dev/null | grep -q "AAP"; then
        ok "AAP Server announced"
    else
        warn "AAP not in SDP right now. Try: disconnect A2DP stream, then re-run."
        echo "     (BlueZ caches SDP; 'sudo sdptool browse' re-queries live.)"
    fi
else
    warn "sdptool missing - newer BlueZ dropped it; the python client can still open PSM 0x1001"
fi

say "5. the socket itself"
sudo python3 - "$MAC" <<'PY'
import socket, sys
mac = sys.argv[1]
try:
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
except AttributeError:
    sys.exit("  FAIL this python has no AF_BLUETOOTH - use the distro python3")
s.settimeout(8)
try:
    s.connect((mac, 0x1001))
except OSError as e:
    print(f"  FAIL PSM 0x1001: {e}")
    sys.exit(1)
print("  OK   PSM 0x1001 opened")
s.close()
PY

printf '\nIf all five are OK: sudo python3 aap_l2cap.py --mac %s --seconds 12 dump\n' "$MAC"
