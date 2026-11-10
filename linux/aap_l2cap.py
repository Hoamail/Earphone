#!/usr/bin/env python3
"""
aap_l2cap.py - AAP/AACP client for Linux (BlueZ L2CAP), stdlib only.

Why Linux: Windows cannot open a user-space L2CAP client socket (the stack hides
PSM 0x1001 behind its A2DP/profile layer). BlueZ exposes AF_BLUETOOTH sockets
directly, so the same frames the accessory speaks to an iPhone are available here.

READ vs WRITE - the thing that bites everyone:
    0x09 <cid> <d1..d4>  is a WRITE of that value to that control.
    Zeroes are a real value ("off"), NOT a query. The only read path is to
    subscribe and let the accessory push its state:

        0x0F 00 FF FF FF FF   -> requests notifications for every control
                                 accessory then pushes each 0x09 <cid> <value>

So `read`/`dump` subscribe and listen. They never send a 0x09 frame.

Commands:
    sudo python3 aap_l2cap.py --mac 41:42:23:76:ED:B8 read
    sudo python3 aap_l2cap.py --mac ... dump --out before.json
    sudo python3 aap_l2cap.py --mac ... mode anc
    sudo python3 aap_l2cap.py --mac ... set 0x26 0
    sudo python3 aap_l2cap.py --mac ... probe-modes
    sudo python3 aap_l2cap.py --mac ... stabilize
    sudo python3 aap_l2cap.py --mac ... monitor --minutes 30
    sudo python3 aap_l2cap.py --mac ... restore before.json
    sudo python3 aap_l2cap.py --mac ... raw "040004000D0001000000"
    sudo python3 aap_l2cap.py --mac ... --transport rfcomm --channel 3 probe

Frames: 04 00 04 00 <op LE> <payload>
"""

import argparse
import json
import os
import socket
import sys
import time

AF_BLUETOOTH = getattr(socket, "AF_BLUETOOTH", 31)
BTPROTO_L2CAP = getattr(socket, "BTPROTO_L2CAP", 0)
BTPROTO_RFCOMM = getattr(socket, "BTPROTO_RFCOMM", 3)
SOCK_SEQPACKET = getattr(socket, "SOCK_SEQPACKET", 5)

AAP_PSM = 0x1001
HEADER = bytes([0x04, 0x00, 0x04, 0x00])
HANDSHAKE = bytes([0x00, 0x00, 0x04, 0x00, 0x01, 0x00, 0x02, 0x00,
                   0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
SET_FEATURES = bytes([0x04, 0x00, 0x04, 0x00, 0x4D, 0x00, 0xD7, 0x00,
                      0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
REQ_NOTIFICATIONS = bytes([0x04, 0x00, 0x04, 0x00, 0x0F, 0x00, 0xFF, 0xFF, 0xFF, 0xFF])
REQ_DEVICE_INFO = bytes([0x04, 0x00, 0x04, 0x00, 0x1D, 0x00])
REQ_BATTERY = bytes([0x04, 0x00, 0x04, 0x00, 0x04, 0x00])

# Every frame the accessory sends during this connection, in order. The push of
# the full control table happens ONCE, immediately after connect - before any
# subscribe request - so the handshake/set-features replies already carry it.
# Missing it is why a second REQ_NOTIFICATIONS appears to return nothing.
SEEN = []

CTRL_NAMES = {
    0x01: "MicMode", 0x05: "ButtonSendMode", 0x06: "OwnsConnection",
    0x0A: "EarDetection", 0x0D: "ListeningMode", 0x12: "VoiceTrigger",
    0x14: "SingleClick", 0x15: "DoubleClick", 0x16: "ClickHold",
    0x17: "DoubleClickInterval", 0x18: "ClickHoldInterval",
    0x1A: "ListeningModeConfigs", 0x1B: "OneBudAnc", 0x1C: "CrownDirection",
    0x1E: "AutoAnswer", 0x1F: "ChimeVolume", 0x20: "AutoConnect",
    0x23: "VolumeSwipeInterval", 0x24: "CallManagementConfig",
    0x25: "VolumeSwipe", 0x26: "AdaptiveVolume", 0x27: "SoftwareMute",
    0x28: "ConversationDetect", 0x29: "SSL",
    0x2C: "HearingAid", 0x2E: "AutoAncStrength", 0x2F: "HpsGainSwipe",
    0x30: "HrmEnabled", 0x31: "InCaseTone", 0x32: "SiriMultitone",
    0x33: "HearingAssist", 0x34: "AllowOffOption",
    0x35: "SleepDetection", 0x36: "AllowAutoConnect", 0x37: "PpeToggle",
    0x38: "PpeCapLevel", 0x39: "RawGestures", 0x3A: "TemporaryPairing",
    0x3B: "DynamicEndOfCharge", 0x3C: "SystemSiriMessage",
    0x3D: "HearingAidGeneric", 0x3E: "UplinkEqBud", 0x3F: "UplinkEqSource",
    0x40: "InCaseToneVolume", 0x41: "DisableButtonInput",
}

# Listening mode, Apple AAP values (1-based: Off=1, ANC=2, Transparency=3,
# Adaptive=4). Confirmed against zeffd/airpods and librepods tables.
MODE = {"off": 1, "anc": 2, "trans": 3, "transparency": 3, "adapt": 4, "adaptive": 4}
MODE_NAMES = {1: "off", 2: "anc", 3: "transparency", 4: "adaptive"}

BATT_COMP = {0x02: "right", 0x04: "left", 0x08: "case"}
BATT_ST = {0: "unknown", 1: "charging", 2: "discharging", 4: "disconnected",
           5: "opt-charging"}

# Settings that make these firmwares feel "unstable": they pump the volume,
# duck and unduck mid-sentence, or fight the ANC level on their own.
# Toggle encoding on Apple AAP is NOT boolean: 0x01 = enabled, 0x02 = disabled.
STABILIZE = [
    (0x26, (2, 0, 0, 0), "AdaptiveVolume disabled - stops the volume rising/falling by itself"),
    (0x28, (2, 0, 0, 0), "ConversationDetect disabled - stops random ducking when you speak"),
    (0x2E, (0, 0, 0, 0), "AutoAncStrength 0 - fixed ANC instead of drifting strength"),
    (0x1B, (2, 0, 0, 0), "OneBudAnc disabled - no one-bud ANC quirk"),
]


# --------------------------------------------------------------------------- io
def connect(mac, psm=AAP_PSM, transport="l2cap", channel=None):
    SEEN.clear()
    if transport == "l2cap":
        s = socket.socket(AF_BLUETOOTH, SOCK_SEQPACKET, BTPROTO_L2CAP)
        s.settimeout(10.0)
        s.connect((mac, psm))
        return s, f"l2cap psm 0x{psm:04X}"
    s = socket.socket(AF_BLUETOOTH, socket.SOCK_STREAM, BTPROTO_RFCOMM)
    s.settimeout(10.0)
    s.connect((mac, channel))
    return s, f"rfcomm ch {channel}"


def ctrl(cid, d1=0, d2=0, d3=0, d4=0):
    return HEADER + bytes([0x09, 0x00, cid, d1 & 0xFF, d2 & 0xFF, d3 & 0xFF, d4 & 0xFF])


def xfer(s, pkt, wait=1.0, quiet=False):
    """Send one frame and drain the reply.

    `wait` is a deadline, not a sleep: we read with a short socket timeout and
    stop as soon as the accessory goes quiet for IDLE seconds. A control write
    that used to burn a fixed 0.8 s now returns in ~30 ms, and a slow device
    still gets the full window.
    """
    s.send(pkt)
    if not quiet:
        print("  ->", pkt.hex(" "))
    out = []
    end = time.time() + wait
    s.settimeout(0.25)
    while time.time() < end:
        try:
            data = s.recv(2048)
        except socket.timeout:
            if out:                      # got everything it was going to say
                break
            continue
        if not data:
            break
        out.append(data)
        if len(out) > 32:
            break
        s.settimeout(0.15)               # follow-up frames arrive back-to-back
    SEEN.extend(out)
    return out


def collect(s, seconds, idle=0.8):
    """Drain whatever the accessory has queued.

    `seconds` is a hard cap; `idle` is the quiet window that ends the read
    early. The accessory pushes its whole state in one burst, so waiting for
    the burst to end is both faster and more complete than a fixed sleep.
    """
    frames = []
    end = time.time() + seconds
    last = time.time()
    s.settimeout(0.25)
    while time.time() < end:
        try:
            data = s.recv(2048)
        except socket.timeout:
            if frames and time.time() - last >= idle:
                break
            continue
        except OSError:
            break
        if not data:
            break
        frames.append(data)
        last = time.time()
    SEEN.extend(frames)
    return frames


# ---------------------------------------------------------------------- decode
def describe(pkt):
    if len(pkt) < 5:
        return "short " + pkt.hex(" ")
    op = pkt[4]
    if pkt[:6] == bytes([0x04, 0x00, 0x04, 0x00, 0x04, 0x00]) and len(pkt) >= 7:
        n, parts = pkt[6], []
        for i in range(n):
            o = 7 + 5 * i
            if o + 4 >= len(pkt):
                break
            parts.append(f"{BATT_COMP.get(pkt[o], hex(pkt[o]))}={pkt[o+2]}%"
                         f"({BATT_ST.get(pkt[o+3], hex(pkt[o+3]))})")
        return "battery " + ", ".join(parts)
    if op == 0x1D:
        fields = [f.decode("utf-8", "replace") for f in pkt[5:].split(b"\x00") if f]
        labels = ["name", "model", "manufacturer", "serial", "firmware",
                  "firmware2", "hardware_rev", "updater_app",
                  "serial_left", "serial_right", "numeric_id"]
        return "device-info " + ", ".join(
            f"{labels[i] if i < len(labels) else i}={v!r}" for i, v in enumerate(fields))
    if op == 0x09 and len(pkt) >= 11:
        cid = pkt[6]
        return f"ctrl {CTRL_NAMES.get(cid, hex(cid))}(0x{cid:02X}) {pkt[7:11].hex(' ')}"
    if op == 0x2B:
        p = pkt[6:]
        mac = ":".join(f"{b:02X}" for b in p[19:25]) if len(p) >= 28 else "?"
        c1 = int.from_bytes(p[3:7], "little") if len(p) >= 7 else 0
        c2 = int.from_bytes(p[11:15], "little") if len(p) >= 15 else 0
        return f"paired-devices mac={mac} n1={c1} n2={c2} tail={p[25:].hex(' ')}"
    if op == 0x31:
        p = pkt[6:]
        return (f"ble-keys {len(p)} bytes, 2 x 16-byte key blobs "
                f"({p[:5].hex(' ')} | {p[21:25].hex(' ')}) - content redacted")
    if op == 0x0E:
        return "audio-source resp " + pkt[6:].hex(" ")
    if op == 0x02:
        p = pkt[6:]
        pairs = " ".join(p[i:i + 2].hex() for i in range(0, len(p) - 1, 2))
        return f"capabilities {len(p)} bytes: {pairs}"
    return f"op 0x{op:02X} " + pkt[6:].hex(" ")


def pretty(cid, value):
    name = CTRL_NAMES.get(cid, f"0x{cid:02X}")
    v = value[0] if value else 0
    if cid == 0x0D:
        return f"{name:<20} {v}  ({MODE_NAMES.get(v, 'unknown')})"
    if len(value) >= 4 and any(value[1:]):
        return f"{name:<20} {value.hex(' ')}"
    return f"{name:<20} {v}"


# ----------------------------------------------------------------------- state
def parse_controls(frames):
    """Later frames win: the accessory re-pushes a control when its value changes."""
    state = {}
    for pkt in frames:
        if len(pkt) >= 11 and pkt[:6] == HEADER + bytes([0x09, 0x00]):
            state[pkt[6]] = bytes(pkt[7:11])
    return state


def read_controls(s, seconds=3.0):
    """Non-mutating read: the accessory pushes its whole control table on connect,
    so this parses everything seen on this connection, and pokes 0x0F in case a
    firmware also honours a mid-session re-push."""
    s.send(REQ_NOTIFICATIONS)
    collect(s, seconds)
    return parse_controls(SEEN), list(SEEN)


def open_session(args):
    s, label = connect(args.mac, args.psm, args.transport, args.channel)
    print(f"connected: {label}")
    replies = xfer(s, HANDSHAKE, 1.2)
    acked = any(r[:4] == bytes([0x01, 0x00, 0x04, 0x00]) for r in replies)
    print("  handshake:", "ACK" if acked else "no ACK")
    if not acked and not args.force:
        print("accessory did not ACK: it is not speaking AAP on this channel.")
        s.close()
        sys.exit(2)
    xfer(s, SET_FEATURES, 0.4, quiet=True)
    return s


def write_ctrl(s, cid, values, wait=0.8):
    pkt = ctrl(cid, *values)
    print(f"  -> {pkt.hex(' ')}   {CTRL_NAMES.get(cid, hex(cid))} = "
          f"{bytes(v & 0xFF for v in values).hex(' ')}")
    acks = xfer(s, pkt, wait, quiet=True)
    for r in acks:
        print("     <-", describe(r))
    return acks


# ------------------------------------------------------------------- commands
def cmd_read(s, args):
    state, frames = read_controls(s, args.seconds)
    if not state:
        print("\nno control frames arrived. The accessory only pushes state right "
              "after a fresh connection - re-run, or try `probe`.")
    else:
        print(f"\n{len(state)} controls:\n")
        for cid in sorted(state):
            print("  " + pretty(cid, state[cid]))
    return state, frames


def cmd_dump(s, args):
    frames = []
    t0 = time.time()

    def rec(direction, pkt):
        frames.append({"t": round(time.time() - t0, 3), "dir": direction,
                       "hex": pkt.hex(" "),
                       "what": describe(pkt) if direction == "in" else ""})

    for pkt in (REQ_DEVICE_INFO, REQ_BATTERY):
        s.send(pkt)
        rec("out", pkt)
        time.sleep(0.3)

    state, incoming = read_controls(s, args.seconds)
    for pkt in incoming:
        rec("in", pkt)
        print("  <-", pkt.hex(" "), "\n     ", describe(pkt))

    doc = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mac": args.mac,
        "known_frames": {"HANDSHAKE": HANDSHAKE.hex(" "),
                         "SET_FEATURES": SET_FEATURES.hex(" "),
                         "REQ_NOTIFICATIONS": REQ_NOTIFICATIONS.hex(" "),
                         "REQ_DEVICE_INFO": REQ_DEVICE_INFO.hex(" "),
                         "REQ_BATTERY": REQ_BATTERY.hex(" ")},
        "controls": {f"0x{cid:02X}": v.hex(" ") for cid, v in sorted(state.items())},
        "control_names": {f"0x{cid:02X}": CTRL_NAMES.get(cid, "") for cid in sorted(state)},
        "frames": frames,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    print(f"\nsaved {len(frames)} frames -> {args.out}")
    return doc


def cmd_mode(s, args):
    if args.mode.isdigit():
        value = int(args.mode)
    else:
        value = MODE[args.mode]
    print(f"listening mode -> {value} ({MODE_NAMES.get(value, '?')})")
    write_ctrl(s, 0x0D, (value, 0, 0, 0), 1.2)
    state, _ = read_controls(s, 2.0)
    if 0x0D in state:
        print("  now:", pretty(0x0D, state[0x0D]))


def cmd_probe_modes(s, args):
    """Walk 0..3 so you can name them by ear. Nothing persists a bad guess:
    whatever you leave it on is what it stays on."""
    print("\nlisten to each step, note which one cancels noise (ANC).\n")
    for value in (1, 2, 3, 4):
        print(f"--- mode {value} ({MODE_NAMES.get(value, "?")}) ---")
        write_ctrl(s, 0x0D, (value, 0, 0, 0), 0.6)
        for i in range(args.gap, 0, -1):
            print(f"    {i}s ... {'ANC?' if value == 1 else MODE_NAMES.get(value)}",
                  end="\r")
            time.sleep(1)
        print(" " * 40, end="\r")
    print("\ndone. set the one that felt right:  mode anc | trans | off\n")


def cmd_stabilize(s, args):
    print("\n--- reading current values (no writes yet) ---")
    before, _ = read_controls(s, 3.0)
    for cid, _v, note in STABILIZE:
        if cid in before:
            print("  " + pretty(cid, before[cid]))
        else:
            print(f"  {CTRL_NAMES.get(cid)}: not reported by this firmware")

    path = args.out or f"settings-before-{time.strftime('%Y%m%d-%H%M%S')}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({f"0x{c:02X}": v.hex(" ") for c, v in before.items()}, f, indent=1)
    print(f"  snapshot -> {path}   (restore with: restore {path})")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return

    print("\n--- writing ---")
    for cid, values, note in STABILIZE:
        print(f"\n  [{note}]")
        write_ctrl(s, cid, values, 0.6)

    print("\n--- verifying ---")
    after, _ = read_controls(s, 3.0)
    stale = []
    for cid, values, note in STABILIZE:
        cur = after.get(cid)
        name = CTRL_NAMES.get(cid, hex(cid))
        if cur is None:
            print(f"  {name:22} not implemented (no echo) - write ignored")
        elif cur[0] == values[0]:
            print(f"  OK   {pretty(cid, cur)}")
        else:
            stale.append(name)
            print(f"  ?    {name:22} still {cur[0]} on this socket")
    if stale:
        print("  state is pushed once per connection, so a value read from the same\n"
              "  socket can be the pre-write copy. Run `read` again to confirm.")
    print("\nNow play music for a few minutes, then run `monitor --minutes 10`.")


def cmd_restore(s, args):
    with open(args.file, encoding="utf-8") as f:
        data = json.load(f)
    values = data.get("controls", data)
    print(f"restoring {len(values)} controls from {args.file}")
    for key in sorted(values):
        cid = int(key, 0)
        raw = bytes.fromhex(values[key].replace(" ", ""))
        raw = (raw + b"\x00\x00\x00\x00")[:4]
        write_ctrl(s, cid, raw, 0.4)
    print("done")


def cmd_monitor(s, args):
    """Watch the live link. This is what actually tells you what 'unstable' means:
    dropped socket, mode flapping, volume jumping, battery lying."""
    print(f"\nwatching for {args.minutes:.1f} min. Use the buds normally.\n")
    s.send(REQ_NOTIFICATIONS)
    t0 = time.time()
    end = t0 + args.minutes * 60
    s.settimeout(1.0)
    last = {}
    changes = {}
    events = []
    frames = 0
    while time.time() < end:
        try:
            data = s.recv(2048)
        except socket.timeout:
            continue
        except OSError as e:
            events.append(f"t={time.time()-t0:7.1f}s  LINK DROPPED: {e}")
            print(events[-1])
            break
        if not data:
            events.append(f"t={time.time()-t0:7.1f}s  peer closed the socket")
            print(events[-1])
            break
        frames += 1
        d = describe(data)
        stamp = f"t={time.time()-t0:7.1f}s"
        if len(data) >= 11 and data[:6] == HEADER + bytes([0x09, 0x00]):
            cid = data[6]
            val = bytes(data[7:11])
            if cid in last and last[cid] != val:
                changes[cid] = changes.get(cid, 0) + 1
                line = f"{stamp}  CHANGED {pretty(cid, val)}  (was {last[cid].hex(' ')})"
                print(line)
                events.append(line)
            last[cid] = val
        elif "battery" in d:
            print(f"{stamp}  {d}")
            events.append(f"{stamp}  {d}")
        elif data[4] not in (0x09, 0x04):
            print(f"{stamp}  {d}")
            events.append(f"{stamp}  {d}")

    print(f"\n--- summary: {frames} frames in {(time.time()-t0)/60:.1f} min ---")
    for cid, n in sorted(changes.items(), key=lambda kv: -kv[1]):
        print(f"  {CTRL_NAMES.get(cid, hex(cid)):<20} changed {n}x")
    flap = {c: n for c, n in changes.items() if n >= 3}
    if flap:
        print("\n  flapping (>=3 changes) -> these are the settings fighting each other:")
        for cid in flap:
            print(f"    {CTRL_NAMES.get(cid, hex(cid))} 0x{cid:02X}")
    if not frames:
        print("  no frames at all: the accessory stayed silent while idle (normal),")
        print("  or it is not connected to this host anymore.")
    if events:
        with open("monitor.log", "a", encoding="utf-8") as f:
            f.write(f"\n=== {time.strftime('%Y-%m-%dT%H:%M:%S')} ===\n")
            f.write("\n".join(events) + "\n")
        print("  events appended to monitor.log")


# ------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="AAP client over BlueZ L2CAP")
    ap.add_argument("--mac", required=True)
    ap.add_argument("--transport", choices=("l2cap", "rfcomm"), default="l2cap")
    ap.add_argument("--psm", type=lambda x: int(x, 0), default=AAP_PSM)
    ap.add_argument("--channel", type=int, default=3)
    ap.add_argument("--force", action="store_true", help="continue even without handshake ACK")
    ap.add_argument("--seconds", type=float, default=4.0)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("read", help="current control values (non-mutating)")
    sub.add_parser("probe")
    sub.add_parser("battery")

    d = sub.add_parser("dump", help="full state snapshot -> json (non-mutating)")
    d.add_argument("--out", default=None)

    m = sub.add_parser("mode", help="set listening mode")
    m.add_argument("mode", help="off | anc | trans | adaptive | 0-3")

    sub.add_parser("probe-modes", help="walk modes 0..3 so you can name them by ear")
    sub.epilog = ""
    pm = sub.choices["probe-modes"]
    pm.add_argument("--gap", type=int, default=5)

    st = sub.add_parser("stabilize", help="turn off settings that cause flapping")
    st.add_argument("--dry-run", action="store_true")
    st.add_argument("--out", default=None)

    rs = sub.add_parser("restore", help="write back a snapshot from dump/stabilize")
    rs.add_argument("file")

    mo = sub.add_parser("monitor", help="watch the link and report anomalies")
    mo.add_argument("--minutes", type=float, default=10.0)

    c = sub.add_parser("cmd", help="write an arbitrary control id")
    c.add_argument("cid")
    c.add_argument("data", nargs="*")

    rp = sub.add_parser("rename")
    rp.add_argument("name")

    w = sub.add_parser("raw")
    w.add_argument("hex")

    args = ap.parse_args()
    if args.cmd == "dump" and args.out is None:
        args.out = f"device-state-{time.strftime('%Y%m%d-%H%M%S')}.json"

    s = open_session(args)
    try:
        if args.cmd == "read":
            cmd_read(s, args)
        elif args.cmd == "dump":
            cmd_dump(s, args)
        elif args.cmd == "probe" or args.cmd == "battery":
            for pkt in collect(s, args.seconds):
                print("  <-", pkt.hex(" "), describe(pkt))
        elif args.cmd == "mode":
            cmd_mode(s, args)
        elif args.cmd == "probe-modes":
            cmd_probe_modes(s, args)
        elif args.cmd == "stabilize":
            cmd_stabilize(s, args)
        elif args.cmd == "restore":
            cmd_restore(s, args)
        elif args.cmd == "monitor":
            cmd_monitor(s, args)
        elif args.cmd == "cmd":
            vals = [int(x, 0) for x in (args.data + ["0", "0", "0", "0"])[:4]]
            write_ctrl(s, int(args.cid, 0), vals, 1.0)
        elif args.cmd == "rename":
            raw_name = args.name.encode()
            pkt = HEADER + bytes([0x1A, 0x00, 0x01, len(raw_name), 0x00]) + raw_name
            for r in xfer(s, pkt, 1.0):
                print("  <-", r.hex(" "), describe(r))
        elif args.cmd == "raw":
            for r in xfer(s, bytes.fromhex(args.hex.replace(" ", "")), 1.0):
                print("  <-", r.hex(" "), describe(r))
    finally:
        s.close()


if __name__ == "__main__":
    main()
