#!/usr/bin/env python3
"""Feed the frames captured from the real accessory back through the decoder.

    python3 test_decode.py
"""
import aap_l2cap as A

# verbatim from the live dump (device-state.json / terminal output)
FRAMES = [
    ("04000400 1d00 01 af 00 0800 50726f204e657747656e 00 4132303834 00",
     "device-info"),
    ("04000400 3100 02 0100 1000 711b805ea65b01eaa93852727a2fd9fe0400 1000 314da606f45ae7d5fc7f3704228ccabc",
     "op 0x31"),
    ("04000400 0900 0d01 000000", "ListeningMode 1"),
    ("04000400 0900 0d00 000000", "ListeningMode 0"),
    ("04000400 0900 0d02 000000", "ListeningMode 2"),
    ("04000400 0e00 aea7a1e3dbf400", "op 0x0E gpio/vendor"),
    ("04000400 0200 0601 0e02020401000000100140018001", "op 0x02 capabilities"),
    ("04000400 0600 0000", "op 0x06"),
    ("04000400 0400 0304 015000 010201 5700 010801 640201", "battery"),
    ("04000400 2b00 0111 00963562 0000000000cb1a31 0000000000 41422376edb8 0b0023",
     "feature-flags"),
    ("04000400 0900 2621 230200", "0x26 raw"),
    ("04000400 0900 2601 000000", "AdaptiveVolume 1"),
    ("04000400 0900 2600 000000", "AdaptiveVolume 0"),
    ("04000400 0900 2801 000000", "ConversationDetect 1"),
    ("01000400 0000 0100 0000 0b00 0600 0000 0000", "handshake ack"),
]

def main():
    seen = {}
    bad = 0
    for hexs, label in FRAMES:
        pkt = bytes.fromhex(hexs.replace(" ", ""))
        try:
            d = A.describe(pkt)
        except Exception as e:                       # noqa: BLE001
            print(f"FAIL {label}: {e}")
            bad += 1
            continue
        print(f"{label:24} -> {d}")
        if len(pkt) >= 11 and pkt[:6] == A.HEADER + bytes([0x09, 0x00]):
            seen[pkt[6]] = bytes(pkt[7:11])

    print("\ndecoded control map:")
    for cid in sorted(seen):
        print("  " + A.pretty(cid, seen[cid]))

    # the semantics that bit the first version: 0x09 with zeroes is a write
    assert A.ctrl(0x0D).hex(" ") == "04 00 04 00 09 00 0d 00 00 00 00", A.ctrl(0x0D).hex(" ")
    assert A.MODE["anc"] == 1 and A.MODE["off"] == 0
    assert seen[0x0D] == b"\x02\x00\x00\x00"
    assert seen[0x26] == b"\x00\x00\x00\x00"
    print(f"\n{len(FRAMES) - bad}/{len(FRAMES)} frames decoded, asserts OK")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
