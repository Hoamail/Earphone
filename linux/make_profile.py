#!/usr/bin/env python3
"""
make_profile.py - turn a Linux capture into one portable device profile.

Input : device-state-*.json (from `aap_l2cap.py dump`)
        optional: SDP text (sdptool browse), pulseaudio card text (pactl list cards),
                  HCI link text (hcitool info / bluetoothctl info)
Output: device-profile.json (schema airpods-profile/v1)

Everything is decoded from the raw frames, using the same decoder the live tool
uses, so the profile is derived from what the accessory actually sent - not from
notes typed by hand.

    python3 make_profile.py ../data/device-state-linux.json \
            --sdp ../data/sdp-linux.txt \
            --codec ../data/audio-codec.txt \
            --link ../data/link-info.txt \
            -o ../device-profile.json

BLE key material (opcode 0x31) is recorded as a length and NEVER copied into the
profile: the accessory pushes the same 32 bytes on every connection, so it is a
static secret and does not belong in a published file.
"""

import argparse
import json
import re
import time

import aap_l2cap as A

# Control ids that exist in Apple's protocol but that this firmware does not
# implement. Verified on the live unit: write -> no echo, no behaviour change.
# The connect-time state push is the authoritative list; it never contains them.
ABSENT = [
    (0x01, "MicMode"), (0x05, "ButtonSendMode"), (0x06, "OwnsConnection"),
    (0x0A, "EarDetection"), (0x12, "VoiceTrigger"), (0x14, "SingleClick"),
    (0x15, "DoubleClick"), (0x16, "ClickHold"), (0x17, "DoubleClickInterval"),
    (0x18, "ClickHoldInterval"), (0x1A, "ListeningModeConfigs"),
    (0x1B, "OneBudAnc"), (0x1C, "CrownDirection"), (0x1E, "AutoAnswer"),
    (0x1F, "ChimeVolume"), (0x20, "AutoConnect"), (0x23, "VolumeSwipeInterval"),
    (0x25, "VolumeSwipe"), (0x27, "SoftwareMute"), (0x29, "SSL"),
    (0x2C, "HearingAid"), (0x2E, "AutoAncStrength"), (0x2F, "HpsGainSwipe"),
    (0x30, "HrmEnabled"), (0x31, "InCaseTone"), (0x32, "SiriMultitone"),
    (0x33, "HearingAssist"), (0x34, "AllowOffOption"),
    (0x35, "SleepDetection"), (0x36, "AllowAutoConnect"), (0x37, "PpeToggle"),
    (0x38, "PpeCapLevel"), (0x39, "RawGestures"), (0x3A, "TemporaryPairing"),
    (0x3B, "DynamicEndOfCharge"), (0x3C, "SystemSiriMessage"),
    (0x3D, "HearingAidGeneric"), (0x3E, "UplinkEqBud"), (0x3F, "UplinkEqSource"),
    (0x40, "InCaseToneVolume"), (0x41, "DisableButtonInput"),
]

TOGGLE_NAMES = {0: "unset/invalid", 1: "enabled", 2: "disabled"}

# 0x1D subtypes this unit sends. 0x86 carries the running firmware, 0xAF the
# multi-asset build, 0xA4 the base build (all three carry the same identity).
SUB_BASE = 0xA4
SUB_FW = 0x86
SUB_MULTI = 0xAF


def info_fields(pkt):
    """0x1D device-info: 1d 00 01 <sub> 00 <len> 00, then NUL-separated strings."""
    return [s.decode("utf-8", "replace") for s in pkt[11:].split(b"\x00") if s]


def decode_battery(pkt):
    """04 00 04 00 04 00 <count> (<component> 01 <level> <status> 01) * count"""
    if len(pkt) < 7 or pkt[4] != 0x04:
        return None
    out = {}
    for i in range(pkt[6]):
        o = 7 + 5 * i
        if o + 4 >= len(pkt):
            break
        comp = A.BATT_COMP.get(pkt[o], f"0x{pkt[o]:02X}")
        out[comp] = {"percent": pkt[o + 2],
                     "state": A.BATT_ST.get(pkt[o + 3], f"0x{pkt[o + 3]:02X}"),
                     "trailer": pkt[o + 4]}
    return out or None


def decode_control(cid, raw):
    v = raw[0]
    entry = {"id": f"0x{cid:02X}", "name": A.CTRL_NAMES.get(cid, ""),
             "hex": raw.hex(" "), "raw": v}
    if cid == 0x0D:
        entry["decoded"] = A.MODE_NAMES.get(v, f"unknown({v})")
        entry["values"] = {str(k): n for k, n in A.MODE_NAMES.items()}
    elif cid in (0x26, 0x28):
        entry["decoded"] = TOGGLE_NAMES.get(v, f"unknown({v})")
        entry["values"] = {str(k): n for k, n in TOGGLE_NAMES.items()}
    elif cid == 0x24:
        entry["decoded"] = "4-byte bitfield (Call Management Config), not decoded"
    else:
        entry["decoded"] = str(v)
    return entry


def parse_sdp(text):
    services, cur = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Service Name:"):
            cur = {"name": line.split(":", 1)[1].strip(), "uuid": None,
                   "channel": None, "psm": None, "version": None}
            services.append(cur)
        elif cur is None:
            continue
        elif line.startswith("UUID 128:"):
            cur["uuid"] = line.split(":", 1)[1].strip()
        elif line.startswith("Channel:"):
            cur["channel"] = int(line.split(":", 1)[1])
        elif line.startswith("PSM:"):
            cur["psm"] = int(line.split(":", 1)[1])
        elif line.startswith("Version:"):
            cur["version"] = line.split(":", 1)[1].strip()
    return services


def parse_codec(text):
    """Pull the A2DP/HFP profile list out of `pactl list cards`."""
    out = {"profiles": []}
    m = re.search(r"Name: (bluez_card\.[0-9A-Fa-f_]+)", text)
    if m:
        out["card"] = m.group(1)
    m = re.search(r"Active Profile: (\S+)", text)
    if m:
        out["active_profile"] = m.group(1)
    for name, desc in re.findall(r"^\t\t([a-z0-9_-]+): (.+?) \(sinks", text, re.M):
        codec = None
        mc = re.search(r"codec ([A-Za-z0-9-]+)", desc)
        if mc:
            codec = mc.group(1)
        out["profiles"].append({"profile": name, "description": desc, "codec": codec})
    for label, key in (("codec", "api.bluez5.codec"),
                       ("vendor_id", "device.vendor.id"),
                       ("product_id", "device.product.id")):
        m = re.search(re.escape(key) + r' = "([^"]*)"', text)
        if m:
            out[label] = m.group(1)
    active = out.get("active_profile", "")
    for prof in out["profiles"]:
        if prof["profile"] == active:
            out.setdefault("codec", prof["codec"])
            break
    return out


def parse_link(text):
    """LMP / feature page / link quality / ACL state from hcitool or bluetoothctl."""
    out = {}
    m = re.search(r"LMP Version:\s*\(?0x([0-9a-fA-F]+)\)?", text)
    if m:
        out["lmp_version"] = int(m.group(1), 16)
    m = re.search(r"LMP Subversion:\s*0x([0-9a-fA-F]+)", text)
    if m:
        out["lmp_subversion"] = int(m.group(1), 16)
    m = re.search(r"Manufacturer:\s*(.+)", text)
    if m:
        out["manufacturer"] = m.group(1).strip()
    m = re.search(r"Features page 0:\s*((?:0x[0-9a-fA-F]{2}\s*){8})", text)
    if m:
        out["features_page0"] = m.group(1).strip()
    m = re.search(r"Features page 1:\s*((?:0x[0-9a-fA-F]{2}\s*){8})", text)
    if m:
        out["features_page1"] = m.group(1).strip()
    m = re.search(r"Link quality:\s*(\d+)", text)
    if m:
        out["link_quality"] = int(m.group(1))
    m = re.search(r"RSSI return value:\s*(-?\d+)", text)
    if m:
        out["rssi"] = int(m.group(1))
    m = re.search(r"ACL\s+([0-9A-Fa-f:]{17})\s+handle\s+(\d+)\s+state\s+(\d+)\s+lm\s+(\w+)\s+(.*)", text)
    if m:
        out["acl"] = {"peer": m.group(1), "handle": int(m.group(2)),
                      "state": int(m.group(3)), "role": m.group(4),
                      "security": m.group(5).strip()}
    m = re.search(r"Class:\s*0x([0-9a-fA-F]{6,8})", text)
    if m:
        out["class_of_device"] = "0x" + m.group(1).lower()
    m = re.search(r"Modalias:\s*(\S+)", text)
    if m:
        out["modalias"] = m.group(1)
    m = re.search(r"Battery Percentage:\s*0x([0-9a-fA-F]+)\s*\((\d+)\)", text)
    if m:
        out["battery_percent_cache"] = int(m.group(2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("state", help="device-state-*.json from `aap_l2cap.py dump`")
    ap.add_argument("--sdp", help="sdptool browse output")
    ap.add_argument("--codec", help="`pactl list cards` output")
    ap.add_argument("--link", action="append",
                    help="hcitool info / bluetoothctl info output (repeatable)")
    ap.add_argument("-o", "--out", default="device-profile.json")
    args = ap.parse_args()

    with open(args.state, encoding="utf-8") as f:
        state = json.load(f)

    infos, battery, controls = {}, {}, {}
    caps, paired, ble_keys, opcodes = [], None, None, {}

    for frame in state.get("frames", []):
        if frame.get("dir") != "in":
            continue
        pkt = bytes.fromhex(frame["hex"].replace(" ", ""))
        if len(pkt) < 6:
            continue
        op = pkt[4]
        opcodes[f"0x{op:02X}"] = opcodes.get(f"0x{op:02X}", 0) + 1

        if op == 0x1D and len(pkt) > 12:
            fields = info_fields(pkt)
            if len(fields) < 8:
                continue
            infos[pkt[7]] = {
                "subtype": f"0x{pkt[7]:02X}",
                "name": fields[0], "model": fields[1],
                "manufacturer": fields[2], "serial": fields[3],
                "version1": fields[4], "version2": fields[5],
                "hardware_rev": fields[6] if len(fields) > 6 else None,
                "updater_app": fields[7],
                "serial_left": fields[8] if len(fields) > 8 else None,
                "serial_right": fields[9] if len(fields) > 9 else None,
                "numeric_id": fields[10] if len(fields) > 10 else None,
                # the next two fields are documented as encrypted blobs
                "extra_fields": len(fields) - 11 if len(fields) > 11 else 0,
            }
        elif op == 0x04:
            battery = decode_battery(pkt) or battery
        elif op == 0x02:
            body = pkt[6:]
            caps.append({"bytes": len(body), "hex": body.hex(" "),
                         "pairs": [body[i:i + 2].hex() for i in range(0, len(body) - 1, 2)]})
        elif op == 0x2B:
            p = pkt[6:]
            if len(p) >= 28:
                paired = {"hex": p.hex(" "),
                          "mac": ":".join(f"{b:02X}" for b in p[19:25]),
                          "counter1": int.from_bytes(p[3:7], "little"),
                          "counter2": int.from_bytes(p[11:15], "little"),
                          "tail": p[25:].hex(" ")}
        elif op == 0x31:
            ble_keys = {"present": True, "payload_bytes": len(pkt) - 6,
                        "blobs": [len(pkt) - 6 - 21, 16],
                        "note": "static 2x16-byte key material; content deliberately "
                                "omitted from this profile"}
        elif op == 0x0E:
            pass

    for key, raw_hex in state.get("controls", {}).items():
        raw = bytes.fromhex(raw_hex.replace(" ", ""))
        controls[key] = decode_control(int(key, 0), raw)

    if ble_keys is None and any("0x31" in r for r in state.get("redacted", [])):
        ble_keys = {"present": True, "redacted": True, "payload_bytes": 32,
                    "note": "static 2x16-byte key material, removed before publishing"}

    base = infos.get(SUB_BASE) or {}
    fw = infos.get(SUB_FW) or {}
    multi = infos.get(SUB_MULTI) or {}
    ident = base or fw or multi

    services = parse_sdp(open(args.sdp, encoding="utf-8").read()) if args.sdp else []
    codec = parse_codec(open(args.codec, encoding="utf-8").read()) if args.codec else None
    link = (parse_link("\n".join(open(f, encoding="utf-8").read() for f in args.link))
            if args.link else None)

    profile = {
        "schema": "airpods-profile/v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": {"os": "linux", "tool": "aap_l2cap.py", "capture": args.state,
                   "transport": "l2cap", "psm": "0x1001",
                   "device_state_json": state.get("captured_at")},
        "device": {
            "name": ident.get("name"),
            "mac": state.get("mac"),
            "model": ident.get("model"),
            "manufacturer_reported": ident.get("manufacturer"),
            "firmware": fw.get("version1"),
            "build": (multi or base).get("version1"),
            "hardware_rev": fw.get("hardware_rev"),
            "updater_app": fw.get("updater_app"),
            "serial": ident.get("serial"),
            "bud_serials": {"left": ident.get("serial_left"),
                            "right": ident.get("serial_right")},
            "numeric_ids": {i["subtype"]: i.get("numeric_id") for i in infos.values()},
        },
        "device_info_reports": list(infos.values()),
        "protocol": {
            "name": "AAP / AACP",
            "handshake": "00 00 04 00 01 00 02 00 00 00 00 00 00 00 00 00",
            "frame_header": "04 00 04 00 <op LE> <payload>",
            "control_frame": "04 00 04 00 09 00 <id> <d1> <d2> <d3> <d4>",
            "read_rule": "0x09 with zeros is a WRITE, not a query; state is pushed "
                         "once on connect, ~6-9 s after the handshake",
            "subscribe": "04 00 04 00 0F 00 FF FF FF FF",
            "opcodes_seen": opcodes,
        },
        "services": services,
        "controls": controls,
        "controls_absent": [{"id": f"0x{i:02X}", "name": n} for i, n in ABSENT],
        "capabilities": caps,
        "paired_devices": paired,
        "ble_keys": ble_keys,
        "battery": battery,
        "codec": codec,
        "link": link,
        "counts": {"controls": len(controls), "frames": len(state.get("frames", [])),
                   "device_info_reports": len(infos)},
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=1, ensure_ascii=False)

    d = profile["device"]
    print(f"{d['name']} ({d['model']}) fw {d['firmware']} build {d['build']} -> {args.out}")
    print(f"  controls : {', '.join(controls)}")
    print(f"  battery  : {battery}")
    print(f"  services : {len(services)} | caps frames: {len(caps)} | "
          f"ble keys: {'present' if ble_keys else 'absent'}")
    if codec:
        print(f"  codec    : {codec.get('codec', '?')} "
              f"via {codec.get('active_profile')}")


if __name__ == "__main__":
    main()
