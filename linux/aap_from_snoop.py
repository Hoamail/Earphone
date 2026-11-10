#!/usr/bin/env python3
"""
aap_from_snoop.py - pull AAP frames out of an Android / BlueZ HCI snoop log.

Built for one job: if the vendor's phone app has a chime switch, the write it
sends is in the log. This prints every AAP-shaped frame with the same decoder the
live client uses, and flags any control id this firmware does not normally push -
that flag is the payload worth replaying.

Android: Settings > Developer options > "Enable Bluetooth HCI snoop log", toggle
the setting in the app, then pull /sdcard/btsnoop_hci.log (may need root, or use
the bugreport copy). BlueZ: /var/lib/bluetooth/*/monitor/btsnoop or btmon -w x.

    python3 aap_from_snoop.py btsnoop_hci.log
    python3 aap_from_snoop.py btsnoop_hci.log --only-controls
    python3 aap_from_snoop.py btsnoop_hci.log --replay 0x1F        # print ready cmds
"""

import argparse
import sys

import btsnoop
import aap_l2cap as A

# What this unit actually reports. Anything else in a 0x09 frame is new.
KNOWN = {0x0D, 0x24, 0x26, 0x28}
AAP_HEADS = (bytes([0x04, 0x00, 0x04, 0x00]), bytes([0x01, 0x00, 0x04, 0x00]),
             bytes([0x00, 0x00, 0x04, 0x00]))


def looks_aap(payload):
    return len(payload) >= 6 and payload[:4] in AAP_HEADS


def main():
    ap = argparse.ArgumentParser(description="extract AAP frames from a btsnoop log")
    ap.add_argument("path")
    ap.add_argument("--only-controls", action="store_true",
                    help="hide handshake/device-info noise, keep 0x09 writes")
    ap.add_argument("--replay", metavar="CID",
                    help="print aap_l2cap commands that reproduce this id's writes")
    args = ap.parse_args()

    total = aap = 0
    unknown = []
    writes = []
    seen = {}

    for _handle, _cid, payload in btsnoop.l2cap_pdus(args.path):
        total += 1
        if not looks_aap(payload):
            continue
        aap += 1
        is_ctrl = len(payload) >= 11 and payload[:6] == A.HEADER + bytes([0x09, 0x00])
        if args.only_controls and not is_ctrl:
            continue
        mark = ""
        if is_ctrl:
            cid = payload[6]
            value = payload[7:11]
            prev = seen.get(cid)
            seen[cid] = value
            if cid not in KNOWN:
                mark = "   <-- NOT in this firmware's table"
                if (cid, value) not in unknown:
                    unknown.append((cid, value))
            if prev != value:
                writes.append((cid, value))
        print(f"{payload.hex(' '):<58} {A.describe(payload)}{mark}")

    print(f"\n{aap} AAP-shaped frames out of {total} L2CAP PDUs")

    if unknown:
        print("\ncontrol ids the live device never reports:")
        for cid, value in unknown:
            print(f"  0x{cid:02X} = {value.hex(' ')}")
        print("\nreplay them (same values, over L2CAP 0x1001):")
        for cid, value in unknown:
            nums = " ".join(str(b) for b in value)
            print(f"  sudo python3 aap_l2cap.py --mac <MAC> raw "
                  f"\"040004000900{cid:02x}{value.hex()}\"")
    elif aap and writes:
        print("\nno exotic control ids - the app only used the four known ones.")
    elif not aap:
        print("\nno AAP traffic in this log. Either the app used BLE/GATT instead of")
        print("L2CAP (run: python3 btsnoop.py <log> att), or the snoop log was empty.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
