#!/usr/bin/env python3
"""
aap.py - Apple Accessory Protocol (AAP/AACP) client for Windows.

Talks to AirPods and AirPods-compatible TWS over classic Bluetooth L2CAP
PSM 0x1001, using Winsock's AF_BTH socket family (no driver, no Linux, no
companion app). Pure stdlib: ctypes + winreg.

Typical use:
    python aap.py probe                     # handshake + dump everything ~8s
    python aap.py monitor                   # stay connected, print decoded events
    python aap.py battery                   # one battery snapshot
    python aap.py anc anc|off|trans|adapt   # listening mode
    python aap.py cmd 0x1A 0x0F             # raw control command + 4 data bytes
    python aap.py rename "My Buds"
    python aap.py raw 0400040009000d01000 00 00
    python aap.py caps                      # feature-flags probe (0x4D)
"""

import argparse
import ctypes
import sys
import time
import winreg

# --------------------------------------------------------------------------
# Winsock / BTH constants
# --------------------------------------------------------------------------
AF_BTH = 32
SOCK_STREAM = 1
SOCK_SEQPACKET = 5
BTHPROTO_RFCOMM = 3
BTHPROTO_L2CAP = 0x0100
AAP_PSM = 0x1001
AAP_SERVICE_UUID = "74ec2172-0bad-4d01-8f77-997b2be0722a"  # SDP "AAP2Server"

HEADER = bytes([0x04, 0x00, 0x04, 0x00])
HANDSHAKE = bytes([0x00, 0x00, 0x04, 0x00, 0x01, 0x00, 0x02, 0x00,
                   0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
SET_FEATURES = bytes([0x04, 0x00, 0x04, 0x00, 0x4D, 0x00, 0xD7, 0x00,
                      0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
REQ_NOTIFICATIONS = bytes([0x04, 0x00, 0x04, 0x00, 0x0F, 0x00, 0xFF, 0xFF, 0xFF, 0xFF])

OP_CTRL = 0x09
OP_BATTERY = 0x04
OP_EAR = 0x06
OP_METADATA = 0x1D
OP_FEATURES = 0x2B
OP_AUDIO_SOURCE = 0x0E
OP_STEM_PRESS = 0x19

CTRL_NAMES = {
    0x01: "MicMode", 0x05: "ButtonSendMode", 0x06: "OwnsConnection",
    0x0A: "EarDetection", 0x0D: "ListeningMode", 0x12: "VoiceTrigger",
    0x14: "SingleClickMode", 0x15: "DoubleClickMode", 0x16: "ClickHoldMode",
    0x17: "DoubleClickInterval", 0x18: "ClickHoldInterval",
    0x1A: "ListeningModeConfigs", 0x1B: "OneBudAncMode",
    0x1C: "CrownRotationDirection", 0x1E: "AutoAnswerMode",
    0x1F: "ChimeVolume", 0x20: "AutomaticConnection",
    0x23: "VolumeSwipeInterval", 0x24: "CallManagement",
    0x25: "VolumeSwipeMode", 0x26: "AdaptiveVolume",
    0x27: "SoftwareMute", 0x28: "ConversationDetect", 0x29: "SSL",
    0x2C: "HearingAid", 0x2E: "AutoAncStrength", 0x2F: "HpsGainSwipe",
    0x30: "HrmState", 0x31: "InCaseTone", 0x32: "SiriMultitone",
    0x33: "HearingAssist", 0x34: "AllowOffOption",
    0x35: "SleepDetection", 0x36: "AllowAutoConnect", 0x37: "PpeToggle",
    0x38: "PpeCapLevel", 0x39: "StemConfig", 0x3A: "TemporaryPairing",
    0x3B: "DynamicEndOfCharge", 0x3C: "SystemSiriMessage",
    0x3D: "HearingAidGeneric", 0x3E: "UplinkEqBud", 0x3F: "UplinkEqSource",
    0x40: "InCaseToneVolume", 0x41: "DisableButtonInput",
}

MODE_NAMES = {1: "off", 2: "anc", 3: "transparency", 4: "adaptive"}
MODE_BYTES = {"off": 1, "anc": 2, "transparency": 3, "trans": 3, "adaptive": 4, "adapt": 4}
BATT_STATUS = {1: "charging", 2: "discharging", 4: "disconnected", 5: "opt-charging"}
BATT_COMP = {0x02: "right", 0x04: "left", 0x08: "case"}


# --------------------------------------------------------------------------
# Win32 plumbing
# --------------------------------------------------------------------------
class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


class SOCKADDR_BTH(ctypes.Structure):
    # ws2bth.h wraps this struct in pshpack1.h: it is byte-packed, so the
    # fields sit at 0/2/10/26 and sizeof() is 30 - NOT the natural-aligned
    # layout that ctypes picks by default. Getting this wrong makes every
    # connect fail with WSAEADDRNOTAVAIL because the address is garbled.
    _pack_ = 1
    _fields_ = [("addressFamily", ctypes.c_ushort),
                ("btAddr", ctypes.c_uint64),
                ("serviceClassId", GUID),
                ("port", ctypes.c_ulong)]


class WSADATA(ctypes.Structure):
    _fields_ = [("wVersion", ctypes.c_ushort), ("wHighVersion", ctypes.c_ushort),
                ("szDescription", ctypes.c_char * 257),
                ("szSystemStatus", ctypes.c_char * 129),
                ("iMaxSockets", ctypes.c_ushort), ("iMaxUdpDg", ctypes.c_ushort),
                ("lpVendorInfo", ctypes.c_char_p)]


class TIMEVAL(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]


ws2 = ctypes.WinDLL("ws2_32", use_last_error=True)
ws2.socket.restype = ctypes.c_uint64
ws2.socket.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
ws2.connect.restype = ctypes.c_int
ws2.connect.argtypes = [ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
ws2.send.restype = ctypes.c_int
ws2.send.argtypes = [ctypes.c_uint64, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
ws2.recv.restype = ctypes.c_int
ws2.recv.argtypes = [ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
ws2.select.restype = ctypes.c_int
ws2.select.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.POINTER(TIMEVAL)]
ws2.closesocket.restype = ctypes.c_int
ws2.closesocket.argtypes = [ctypes.c_uint64]
ws2.WSAGetLastError.restype = ctypes.c_int

WSA_STARTED = False


def wsa_init():
    global WSA_STARTED
    if WSA_STARTED:
        return
    data = WSADATA()
    rc = ws2.WSAStartup(0x0202, ctypes.byref(data))
    if rc != 0:
        raise OSError(f"WSAStartup failed: {rc}")
    WSA_STARTED = True


def parse_mac(mac: str) -> int:
    parts = mac.replace("-", ":").split(":")
    if len(parts) != 6:
        raise ValueError(f"bad bluetooth address: {mac}")
    value = 0
    for p in parts:
        value = (value << 8) | int(p, 16)
    return value


def guid_from_string(uuid: str) -> GUID:
    """Build a Win32 GUID (mixed-endian) from a textual UUID."""
    hexs = uuid.replace("-", "")
    d1 = int(hexs[0:8], 16)
    d2 = int(hexs[8:12], 16)
    d3 = int(hexs[12:16], 16)
    rest = bytes.fromhex(hexs[16:32])
    g = GUID()
    g.Data1, g.Data2, g.Data3 = d1, d2, d3
    for i, b in enumerate(rest):
        g.Data4[i] = b
    return g


def win_error(code: int) -> str:
    return f"{code}: {ctypes.FormatError(code).strip()}"


class AapLink:
    """One L2CAP connection to PSM 0x1001 carrying AAP frames."""

    def __init__(self, mac: str, psm: int = AAP_PSM):
        wsa_init()
        self.mac = mac
        self.transport = None
        self.sock = None
        errors = []

        # Route 1: L2CAP to the AAP PSM.
        for stype, label in ((SOCK_SEQPACKET, "l2cap/seqpacket"),
                             (SOCK_STREAM, "l2cap/stream")):
            fd = ws2.socket(AF_BTH, stype, BTHPROTO_L2CAP)
            if fd in (0, 0xFFFFFFFFFFFFFFFF):
                errors.append(f"{label}: socket -> {win_error(ws2.WSAGetLastError())}")
                continue
            if self._connect(fd, psm):
                self.sock, self.transport = fd, label
                break
            errors.append(f"{label} PSM 0x{psm:04X}: {win_error(ws2.WSAGetLastError())}")
            ws2.closesocket(fd)

        # Route 2: RFCOMM to the "AAP2Server" service UUID from SDP. This is the
        # only route some clones expose (their L2CAP PSM 0x1001 is absent).
        if self.sock is None:
            fd = ws2.socket(AF_BTH, SOCK_STREAM, BTHPROTO_RFCOMM)
            if fd in (0, 0xFFFFFFFFFFFFFFFF):
                errors.append(f"rfcomm: socket -> {win_error(ws2.WSAGetLastError())}")
            elif self._connect(fd, 0, AAP_SERVICE_UUID):
                self.sock, self.transport = fd, "rfcomm/AAP2Server"
            else:
                errors.append(f"rfcomm/AAP2Server: {win_error(ws2.WSAGetLastError())}")
                ws2.closesocket(fd)

        if self.sock is None:
            raise OSError(
                f"cannot reach {mac}.\n  " + "\n  ".join(errors) +
                "\n  WSAEADDRNOTAVAIL (10049) means the accessory has no live ACL "
                "link: power it on, take it out of the case, and disconnect it from "
                "the phone so Windows owns the connection.")

    def _connect(self, fd, port, service_uuid=None):
        sa = SOCKADDR_BTH()
        sa.addressFamily = AF_BTH
        sa.btAddr = parse_mac(self.mac)
        sa.port = port
        if service_uuid:
            g = guid_from_string(service_uuid)
            ctypes.memmove(ctypes.byref(sa.serviceClassId), ctypes.byref(g),
                           ctypes.sizeof(g))
        return ws2.connect(fd, ctypes.byref(sa), ctypes.sizeof(sa)) == 0

    # -- io ---------------------------------------------------------------
    def send(self, data: bytes) -> int:
        n = ws2.send(self.sock, data, len(data), 0)
        if n < 0:
            raise OSError(f"send failed -> {win_error(ws2.WSAGetLastError())}")
        return n

    def recv(self, timeout: float = 1.0):
        """Return one AAP frame or None on timeout."""
        buf = ctypes.create_string_buffer(2048)
        readfds = ctypes.create_string_buffer(16)
        ctypes.memset(readfds, 0, 16)
        word = ctypes.cast(readfds, ctypes.POINTER(ctypes.c_uint64))
        word[0] = 1 << (self.sock % 64)  # FD_SET for a single socket index
        tv = TIMEVAL(int(timeout), int((timeout % 1) * 1_000_000))
        rc = ws2.select(0, ctypes.byref(readfds), None, None, ctypes.byref(tv))
        if rc <= 0:
            return None
        n = ws2.recv(self.sock, buf, 2048, 0)
        if n < 0:
            raise OSError(f"recv failed -> {win_error(ws2.WSAGetLastError())}")
        if n == 0:
            raise ConnectionResetError("accessory closed the AAP channel")
        return buf.raw[:n]

    def close(self):
        if self.sock:
            ws2.closesocket(self.sock)
            self.sock = None

    # -- protocol ---------------------------------------------------------
    def handshake(self, verbose=True, wait=1.5):
        self.send(HANDSHAKE)
        acked = False
        deadline = time.time() + wait
        while time.time() < deadline:
            pkt = self.recv(0.4)
            if not pkt:
                continue
            if verbose:
                print("  <- " + pkt.hex(" "))
            if pkt[:4] == bytes([0x01, 0x00, 0x04, 0x00]):
                acked = True
                break
        return acked

    def subscribe(self):
        self.send(SET_FEATURES)
        self.send(REQ_NOTIFICATIONS)


# --------------------------------------------------------------------------
# Decoding
# --------------------------------------------------------------------------
def parse_battery(pkt: bytes):
    if len(pkt) < 7 or pkt[:6] != bytes([0x04, 0x00, 0x04, 0x00, 0x04, 0x00]):
        return None
    count = pkt[6]
    out = {}
    for i in range(count):
        off = 7 + 5 * i
        if off + 4 >= len(pkt):
            break
        comp = BATT_COMP.get(pkt[off], f"0x{pkt[off]:02X}")
        out[comp] = (pkt[off + 2], BATT_STATUS.get(pkt[off + 3], hex(pkt[off + 3])))
    return out


def parse_metadata(pkt: bytes):
    if len(pkt) < 5 or pkt[4] != OP_METADATA:
        return None
    body = pkt[5:]
    fields = [f.decode("utf-8", "replace") for f in body.split(b"\x00") if f]
    labels = ["name", "model", "manufacturer", "serial", "version1", "version2",
              "hardware", "updater", "serial_left", "serial_right", "extra"]
    return {labels[i] if i < len(labels) else f"field{i}": v
            for i, v in enumerate(fields)}


def describe(pkt: bytes) -> str:
    if len(pkt) < 5:
        return "short frame " + pkt.hex(" ")
    opcode = pkt[4]
    batt = parse_battery(pkt)
    if batt is not None:
        return "battery " + ", ".join(f"{k}={v[0]}%({v[1]})" for k, v in batt.items())
    meta = parse_metadata(pkt)
    if meta is not None:
        return "device-info " + ", ".join(f"{k}={v!r}" for k, v in meta.items())
    if opcode == OP_CTRL and len(pkt) >= 11:
        cid = pkt[6]
        return (f"control-command {CTRL_NAMES.get(cid, hex(cid))} "
                f"data={pkt[7:11].hex(' ')}")
    if opcode == OP_EAR and len(pkt) >= 8:
        return f"ear-detection {pkt[6:].hex(' ')}"
    if opcode == OP_FEATURES:
        return f"feature-flags {pkt[6:].hex(' ')}"
    if opcode == OP_AUDIO_SOURCE:
        return f"audio-source {pkt[6:].hex(' ')}"
    if opcode == OP_STEM_PRESS:
        return f"stem-press {pkt[6:].hex(' ')}"
    return f"opcode 0x{opcode:02X} " + pkt[6:].hex(" ")


# --------------------------------------------------------------------------
# Packet builders
# --------------------------------------------------------------------------
def ctrl(cid: int, d1=0, d2=0, d3=0, d4=0) -> bytes:
    return HEADER + bytes([OP_CTRL, 0x00, cid, d1 & 0xFF, d2 & 0xFF, d3 & 0xFF, d4 & 0xFF])


def listening_mode(mode: int) -> bytes:
    return ctrl(0x0D, mode)


def rename_packet(name: str) -> bytes:
    raw = name.encode("utf-8")
    return HEADER + bytes([0x1A, 0x00, 0x01, len(raw), 0x00]) + raw


# --------------------------------------------------------------------------
# Device discovery (registry, avoids any pairing prompt)
# --------------------------------------------------------------------------
def paired_devices():
    out = {}
    key = r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key)
    except OSError:
        return out
    i = 0
    while True:
        try:
            sub = winreg.EnumKey(root, i)
        except OSError:
            break
        i += 1
        try:
            k = winreg.OpenKey(root, sub)
            name = winreg.QueryValueEx(k, "Name")[0]
            if isinstance(name, bytes):
                name = name.decode("utf-8", "replace").strip("\x00")
            mac = ":".join(sub[i:i + 2] for i in range(0, 12, 2)).upper()
            out[mac] = name
        except OSError:
            continue
    return out


def resolve(args) -> str:
    if args.addr:
        return args.addr
    devs = paired_devices()
    if args.name:
        needle = args.name.lower()
        for mac, name in devs.items():
            if needle in name.lower():
                return mac
        raise SystemExit(f"no paired device matching {args.name!r}; "
                         f"paired: {devs}")
    raise SystemExit("need --addr AA:BB:CC:DD:EE:FF or --name <substring>\n"
                     + "paired devices:\n"
                     + "\n".join(f"  {m}  {n}" for m, n in sorted(devs.items())))


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def cmd_probe(args):
    mac = resolve(args)
    print(f"connecting {mac} PSM 0x{AAP_PSM:04X} ...")
    link = AapLink(mac)
    try:
        ok = link.handshake()
        print("  handshake:", "ACK" if ok else "NO ACK (not speaking AAP?)")
        link.subscribe()
        deadline = time.time() + args.seconds
        while time.time() < deadline:
            pkt = link.recv(0.5)
            if pkt:
                print(f"  <- {pkt.hex(' '):<60} {describe(pkt)}")
    finally:
        link.close()


def cmd_monitor(args):
    mac = resolve(args)
    link = AapLink(mac)
    try:
        if not link.handshake(verbose=False):
            print("no handshake ACK; continuing anyway")
        link.subscribe()
        last_ping = time.time()
        print(f"monitoring {mac} - ctrl-c to stop")
        while True:
            pkt = link.recv(0.5)
            if pkt:
                print(time.strftime("%H:%M:%S"), describe(pkt))
            elif time.time() - last_ping > 20:
                link.send(REQ_NOTIFICATIONS)
                last_ping = time.time()
    except KeyboardInterrupt:
        pass
    finally:
        link.close()


def cmd_battery(args):
    mac = resolve(args)
    link = AapLink(mac)
    try:
        link.handshake(verbose=args.verbose)
        link.subscribe()
        deadline = time.time() + args.seconds
        seen = False
        while time.time() < deadline:
            pkt = link.recv(0.5)
            if not pkt:
                continue
            batt = parse_battery(pkt)
            if batt:
                seen = True
                print(", ".join(f"{k}: {v[0]}% {v[1]}" for k, v in batt.items()))
                if not args.watch:
                    return
        if not seen:
            print("no battery notification received")
    finally:
        link.close()


def cmd_anc(args):
    mode = MODE_BYTES[args.mode.lower()]
    mac = resolve(args)
    link = AapLink(mac)
    try:
        link.handshake(verbose=args.verbose)
        link.send(listening_mode(mode))
        deadline = time.time() + 1.5
        while time.time() < deadline:
            pkt = link.recv(0.4)
            if pkt:
                print("<-", pkt.hex(" "), describe(pkt))
        print(f"sent listening-mode {args.mode} (byte {mode})")
    finally:
        link.close()


def cmd_cmd(args):
    data = [int(x, 0) for x in (args.data + ["0", "0", "0", "0"])[:4]]
    pkt = ctrl(int(args.cid, 0), *data)
    mac = resolve(args)
    link = AapLink(mac)
    try:
        link.handshake(verbose=args.verbose)
        print("->", pkt.hex(" "))
        link.send(pkt)
        deadline = time.time() + 1.5
        while time.time() < deadline:
            r = link.recv(0.4)
            if r:
                print("<-", r.hex(" "), describe(r))
    finally:
        link.close()


def cmd_rename(args):
    pkt = rename_packet(args.name_new)
    mac = resolve(args)
    link = AapLink(mac)
    try:
        link.handshake(verbose=args.verbose)
        link.send(pkt)
        print("->", pkt.hex(" "))
        deadline = time.time() + 1.5
        while time.time() < deadline:
            r = link.recv(0.4)
            if r:
                print("<-", r.hex(" "), describe(r))
    finally:
        link.close()


def cmd_raw(args):
    pkt = bytes.fromhex(args.hex.replace(" ", ""))
    mac = resolve(args)
    link = AapLink(mac)
    try:
        link.handshake(verbose=args.verbose)
        print("->", pkt.hex(" "))
        link.send(pkt)
        deadline = time.time() + args.seconds
        while time.time() < deadline:
            r = link.recv(0.4)
            if r:
                print("<-", r.hex(" "), describe(r))
    finally:
        link.close()


def cmd_caps(args):
    mac = resolve(args)
    link = AapLink(mac)
    try:
        link.handshake(verbose=args.verbose)
        link.send(SET_FEATURES)
        deadline = time.time() + 2.5
        while time.time() < deadline:
            r = link.recv(0.4)
            if r:
                print("<-", r.hex(" "), describe(r))
    finally:
        link.close()


def cmd_devices(args):
    for mac, name in sorted(paired_devices().items(), key=lambda kv: kv[1].lower()):
        print(f"{mac}  {name}")


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="AAP client for Windows (L2CAP PSM 0x1001)")
    ap.add_argument("--addr", help="device MAC, e.g. 41:42:23:76:ED:B8")
    ap.add_argument("--name", help="match a paired device by name substring")
    ap.add_argument("-v", "--verbose", action="store_true", help="print raw frames")
    ap.add_argument("-s", "--seconds", type=float, default=8.0)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="handshake + dump frames").set_defaults(fn=cmd_probe)
    sub.add_parser("monitor", help="live decode").set_defaults(fn=cmd_monitor)
    b = sub.add_parser("battery", help="battery snapshot")
    b.add_argument("-w", "--watch", action="store_true")
    b.set_defaults(fn=cmd_battery)
    a = sub.add_parser("anc", help="set listening mode")
    a.add_argument("mode", choices=sorted(MODE_BYTES))
    a.set_defaults(fn=cmd_anc)
    c = sub.add_parser("cmd", help="raw control command")
    c.add_argument("cid")
    c.add_argument("data", nargs="*")
    c.set_defaults(fn=cmd_cmd)
    r = sub.add_parser("rename", help="rename the accessory")
    r.add_argument("name_new")
    r.set_defaults(fn=cmd_rename)
    w = sub.add_parser("raw", help="send raw hex frame")
    w.add_argument("hex")
    w.set_defaults(fn=cmd_raw)
    sub.add_parser("caps", help="feature flags probe").set_defaults(fn=cmd_caps)
    sub.add_parser("devices", help="list paired devices").set_defaults(fn=cmd_devices)

    args = ap.parse_args()
    try:
        args.fn(args)
    except OSError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
