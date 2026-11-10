#!/usr/bin/env python3
"""
stabilize_daemon.py - apply the stability profile every time the buds connect.

Why a daemon: the accessory forgets nothing, but a host that writes 0 again (or
a phone that syncs its own settings) puts the two toggles back into the invalid
state. Watching for the rising edge of `Connected: yes` and writing the profile
once per connection makes "flaky" self-healing.

Runs as root (L2CAP needs CAP_NET_RAW):

    sudo python3 run/linux/stabilize_daemon.py --mac 41:42:23:76:ED:B8

Install it as a service with run/linux/2-auto-apply.sh.
"""

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "linux"))

import aap_l2cap as A                                    # noqa: E402

# (control id, four bytes, why)
PROFILE = [
    (0x26, (2, 0, 0, 0), "AdaptiveVolume off"),
    (0x28, (2, 0, 0, 0), "ConversationDetect off"),
    (0x2E, (0, 0, 0, 0), "AutoAncStrength 0"),
    (0x1B, (2, 0, 0, 0), "OneBudAnc off"),
]


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S ") + msg, flush=True)


def connected(mac):
    try:
        out = subprocess.run(["bluetoothctl", "info", mac], capture_output=True,
                             text=True, timeout=8).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "Connected: yes" in out


def apply_profile(mac):
    s, label = A.connect(mac)
    try:
        log(f"connected: {label}")
        replies = A.xfer(s, A.HANDSHAKE, 2.0, quiet=True)
        if not any(r[:4] == bytes([0x01, 0x00, 0x04, 0x00]) for r in replies):
            log("no handshake ACK - accessory busy, will retry next connect")
            return False
        A.xfer(s, A.SET_FEATURES, 0.5, quiet=True)
        for cid, values, why in PROFILE:
            A.xfer(s, A.ctrl(cid, *values), 0.6, quiet=True)
            log(f"  0x{cid:02X} = {values[0]}  ({why})")
        state, _ = A.read_controls(s, 4.0)
        if state:
            summary = ", ".join(f"0x{k:02X}={v[0]}" for k, v in sorted(state.items()))
            log("  state now: " + summary)
        return True
    except OSError as e:
        log(f"apply failed: {e}")
        return False
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mac", default=os.environ.get("EARPHONE_MAC",
                                                    "41:42:23:76:ED:B8"))
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--settle", type=float, default=1.5,
                    help="seconds to wait after the link comes up")
    args = ap.parse_args()

    log(f"watching {args.mac} every {args.interval}s")
    was = False
    while True:
        now = connected(args.mac)
        if now and not was:
            log("link up")
            time.sleep(args.settle)
            apply_profile(args.mac)
        elif was and not now:
            log("link down")
        was = now
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
