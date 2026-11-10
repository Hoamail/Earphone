#!/usr/bin/env python3
"""
gatt.py - BLE GATT explorer for TWS earbuds on Windows (bleak).

Vendor companion apps almost always drive the buds over BLE GATT, not over
classic Bluetooth. This dumps every service/characteristic the accessory
exposes, reads everything readable, subscribes to everything notifiable, and
prints the hex so you can diff what the official app does.

    python gatt.py scan
    python gatt.py scan --all
    python gatt.py dump --name "Pro" --seconds 15 --log dump.txt
    python gatt.py read  --name "Pro" --uuid 0000ae01-0000-1000-8000-00805f9b34fb
    python gatt.py write --name "Pro" --uuid 0000ae01-... --hex 5501...
    python gatt.py watch --name "Pro" --uuid 0000ae02-... --seconds 30
"""

import argparse
import asyncio
import sys
import time

from bleak import BleakClient, BleakScanner


def log(lines, path):
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


async def cmd_scan(args):
    devs = await BleakScanner.discover(timeout=args.timeout, return_adv=True)
    for dev, adv in sorted(devs.values(), key=lambda d: (d[1].local_name or "~")):
        if not args.all and not adv.local_name and not adv.manufacturer_data:
            continue
        print(f"{dev.address}  rssi={adv.rssi:4d}  name={adv.local_name!r}")
        if adv.manufacturer_data:
            print("   mfg  " + ", ".join(f"0x{k:04X}:{v.hex(' ')}"
                                         for k, v in adv.manufacturer_data.items()))
        if adv.service_uuids:
            print("   svc  " + " ".join(str(u) for u in adv.service_uuids))
        if adv.service_data:
            print("   sdat " + ", ".join(f"{k}:{v.hex(' ')}"
                                         for k, v in adv.service_data.items()))


async def find(name=None, addr=None):
    if addr:
        return addr
    devs = await BleakScanner.discover(timeout=6.0, return_adv=True)
    needle = (name or "").lower()
    hits = [d for d, adv in devs.values()
            if needle and needle in (adv.local_name or "").lower()]
    if not hits:
        raise SystemExit(f"no BLE device matching {name!r} in range "
                         "(BLE advertising stops while the buds are connected "
                         "to a phone; disconnect from the phone and retry)")
    print(f"using {hits[0].address} ({hits[0].name})")
    return hits[0].address


async def cmd_dump(args):
    addr = await find(args.name, args.addr)
    out = []
    async with BleakClient(addr, timeout=20.0) as client:
        print(f"connected {addr}  mtu={client.mtu_size}")
        for svc in client.services:
            out.append(f"[service] {svc.uuid}  {svc.description}")
            print(out[-1])
            for ch in svc.characteristics:
                out.append(f"  [char] {ch.uuid} {ch.properties} {ch.description}")
                print(out[-1])
                for d in ch.descriptors:
                    out.append(f"    [desc] {d.uuid} {d.description}")
                    print(out[-1])
                if "read" in ch.properties:
                    try:
                        val = await client.read_gatt_char(ch)
                        out.append(f"    read -> {val.hex(' ')}")
                        print(out[-1])
                    except Exception as e:
                        out.append(f"    read failed: {e}")

        def make_cb(uuid):
            def cb(_sender, data: bytearray):
                line = f"{time.strftime('%H:%M:%S')} {uuid} <- {bytes(data).hex(' ')}"
                print(line)
                out.append(line)
            return cb

        for svc in client.services:
            for ch in svc.characteristics:
                if ch.properties & 0x10 or "notify" in ch.properties or \
                   "indicate" in ch.properties:
                    try:
                        await client.start_notify(ch, make_cb(str(ch.uuid)))
                    except Exception as e:
                        out.append(f"  notify failed on {ch.uuid}: {e}")
        print(f"--- listening {args.seconds}s (use the official app now) ---")
        await asyncio.sleep(args.seconds)
    log(out, args.log)


async def cmd_read(args):
    addr = await find(args.name, args.addr)
    async with BleakClient(addr, timeout=20.0) as client:
        val = await client.read_gatt_char(args.uuid)
        print(f"{args.uuid} -> {val.hex(' ')}  ({bytes(val)!r})")


async def cmd_write(args):
    addr = await find(args.name, args.addr)
    payload = bytes.fromhex(args.hex.replace(" ", ""))
    async with BleakClient(addr, timeout=20.0) as client:
        resp = "response" in (args.mode or "")
        await client.write_gatt_char(args.uuid, payload, response=resp)
        print(f"wrote {len(payload)} bytes to {args.uuid}")


async def cmd_watch(args):
    async def run():
        addr = await find(args.name, args.addr)
        async with BleakClient(addr, timeout=20.0) as client:
            def cb(_s, data: bytearray):
                print(f"{time.strftime('%H:%M:%S')} <- {bytes(data).hex(' ')}")
            await client.start_notify(args.uuid, cb)
            print(f"watching {args.uuid} for {args.seconds}s")
            await asyncio.sleep(args.seconds)
    await run()


def main():
    ap = argparse.ArgumentParser(description="BLE GATT explorer for TWS buds")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, need_addr=True):
        p.add_argument("--addr")
        p.add_argument("--name")
        p.add_argument("--log", help="append everything to this file")
        p.add_argument("--seconds", type=float, default=15.0)

    s = sub.add_parser("scan")
    s.add_argument("--timeout", type=float, default=8.0)
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_scan)

    d = sub.add_parser("dump")
    common(d)
    d.set_defaults(fn=cmd_dump)

    r = sub.add_parser("read")
    common(r)
    r.add_argument("--uuid", required=True)
    r.set_defaults(fn=cmd_read)

    w = sub.add_parser("write")
    common(w)
    w.add_argument("--uuid", required=True)
    w.add_argument("--hex", required=True)
    w.add_argument("--mode", default="response")
    w.set_defaults(fn=cmd_write)

    t = sub.add_parser("watch")
    common(t)
    t.add_argument("--uuid", required=True)
    t.set_defaults(fn=cmd_watch)

    args = ap.parse_args()
    try:
        asyncio.run(args.fn(args))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
