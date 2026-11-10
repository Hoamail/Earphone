#!/usr/bin/env python3
"""
ports.py - find which RFCOMM channels / L2CAP PSMs the accessory answers on.

Why: Windows reports the ACL link as Connected, but AAP still refuses to open
PSM 0x1001. AirPods clones put the vendor channel wherever the firmware author
felt like it, and some Windows stacks only implement L2CAP for profiles, not
for user sockets. This walks the port space and reports every port that
accepts a connection, then tries the AAP handshake on each one.

    python ports.py --mac 41:42:23:76:ED:B8
    python ports.py --mac ... --rfcomm 1-30 --psm 0x1001,0x1003,0x1007
"""

import argparse
import socket
import threading
import time

import aap

HANDSHAKE = aap.HANDSHAKE
ACK = bytes([0x01, 0x00, 0x04, 0x00])


def attempt(kind, port, out, timeout=2.5):
    fd = aap.ws2.socket(aap.AF_BTH,
                        aap.SOCK_STREAM,
                        aap.BTHPROTO_RFCOMM if kind == "rfcomm" else aap.BTHPROTO_L2CAP)
    if fd in (0, 0xFFFFFFFFFFFFFFFF):
        out[port] = ("socket", aap.ws2.WSAGetLastError(), b"")
        return
    sa = aap.SOCKADDR_BTH()
    sa.addressFamily = aap.AF_BTH
    sa.btAddr = aap.parse_mac(ARGS.mac)
    sa.port = port
    rc = aap.ws2.connect(fd, __import__("ctypes").byref(sa),
                         __import__("ctypes").sizeof(sa))
    if rc != 0:
        out[port] = ("err", aap.ws2.WSAGetLastError(), b"")
        aap.ws2.closesocket(fd)
        return

    reply = b""
    try:
        aap.ws2.send(fd, HANDSHAKE, len(HANDSHAKE), 0)
        time.sleep(1.0)
        buf = __import__("ctypes").create_string_buffer(512)
        n = aap.ws2.recv(fd, buf, 512, 0)
        if n > 0:
            reply = buf.raw[:n]
    except Exception:
        pass
    out[port] = ("open", 0, reply)
    aap.ws2.closesocket(fd)


def scan(kind, ports):
    print(f"--- {kind} ---")
    for port in ports:
        out = {}
        t = threading.Thread(target=attempt, args=(kind, port, out), daemon=True)
        t.start()
        t.join(3.5)
        if port not in out:
            out[port] = ("timeout", 0, b"")
        status, err, reply = out[port]
        if status == "open":
            extra = ""
            if reply:
                tag = "AAP-ACK" if reply[:4] == ACK else "reply"
                extra = f"  <- {tag} {reply.hex(' ')}"
            print(f"  {kind} 0x{port:04X} ({port:>3}) OPEN{extra}")
        elif status in ("err",) and err in (10049, 10050, 10051, 10061, 10022):
            continue  # normal refusal, stay quiet
        elif status != "timeout":
            print(f"  {kind} 0x{port:04X} ({port:>3}) {status} err={err}")
        else:
            print(f"  {kind} 0x{port:04X} ({port:>3}) no answer (timeout)")


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--mac", required=True)
    ap.add_argument("--rfcomm", default="1-20")
    ap.add_argument("--psm", default="0x1001,0x1003,0x1007,0x1009,0x100B,0x0003,0x0019")
    ARGS = ap.parse_args()

    def rng(spec):
        if "-" in spec and not spec.startswith("0x"):
            a, b = spec.split("-")
            return list(range(int(a), int(b) + 1))
        return [int(x, 0) for x in spec.split(",")]

    aap.wsa_init()
    scan("l2cap", rng(ARGS.psm))
    scan("rfcomm", rng(ARGS.rfcomm))


if __name__ == "__main__":
    main()
