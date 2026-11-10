#!/usr/bin/env python3
"""
btsnoop.py - read Android Bluetooth HCI snoop logs without Wireshark.

Pure stdlib. Handles the btsnoop container, HCI ACL reassembly, L2CAP, ATT
(so you can see GATT writes) and SDP (so you can see which RFCOMM channels and
L2CAP PSMs the accessory announces - that is how you find a vendor channel).

    python btsnoop.py log.btsnoop summary
    python btsnoop.py log.btsnoop att
    python btsnoop.py log.btsnoop att --handle 0x0015
    python btsnoop.py log.btsnoop sdp
    python btsnoop.py log.btsnoop grep 74ec2172
"""

import argparse
import struct
import sys

ATT_OPS = {
    0x01: "ERROR_RSP", 0x02: "MTU_REQ", 0x03: "MTU_RSP",
    0x04: "FIND_INFO_REQ", 0x05: "FIND_INFO_RSP",
    0x06: "FIND_BY_TYPE_REQ", 0x07: "FIND_BY_TYPE_RSP",
    0x08: "READ_BY_TYPE_REQ", 0x09: "READ_BY_TYPE_RSP",
    0x0A: "READ_REQ", 0x0B: "READ_RSP",
    0x0C: "READ_BLOB_REQ", 0x0D: "READ_BLOB_RSP",
    0x0E: "READ_MULTI_REQ", 0x0F: "READ_MULTI_RSP",
    0x10: "READ_BY_GRP_REQ", 0x11: "READ_BY_GRP_RSP",
    0x12: "WRITE_REQ", 0x13: "WRITE_RSP",
    0x16: "PREP_WRITE_REQ", 0x17: "PREP_WRITE_RSP",
    0x18: "EXEC_WRITE_REQ", 0x19: "EXEC_WRITE_RSP",
    0x1B: "NOTIFY", 0x1D: "INDICATE", 0x1E: "CONFIRM",
    0x52: "WRITE_CMD", 0xD2: "SIGNED_WRITE_CMD",
}


def u16(b, o=0):
    return b[o] | (b[o + 1] << 8)


def be16(b, o=0):
    """SDP is big-endian; L2CAP headers are not."""
    return (b[o] << 8) | b[o + 1]


def iter_hci(path):
    with open(path, "rb") as f:
        head = f.read(16)
        if head[:8] != b"btsnoop\x00":
            raise SystemExit(f"{path}: not a btsnoop file (magic {head[:8]!r})")
        version, datalink = struct.unpack(">II", head[8:16])
        print(f"# btsnoop v{version} datalink={datalink}", file=sys.stderr)
        while True:
            rec = f.read(24)
            if len(rec) < 24:
                return
            orig, incl, flags, drops, ts = struct.unpack(">IIIIQ", rec)
            data = f.read(incl)
            if len(data) < incl:
                return
            yield datalink, data


def l2cap_pdus(path):
    """Yield (handle, cid, payload) with L2CAP reassembly."""
    pending = {}
    for datalink, data in iter_hci(path):
        if not data:
            continue
        if datalink == 1002:            # HCI UART (H4): type byte first
            ptype, body = data[0], data[1:]
            if ptype != 0x02:           # ACL only
                continue
        elif datalink == 1001:          # unencapsulated HCI
            body = data
        else:
            continue
        if len(body) < 4:
            continue
        v = u16(body)
        handle, pb = v & 0x0FFF, (v >> 12) & 0x3
        dlen = u16(body, 2)
        frag = body[4:4 + dlen]
        if pb == 0x2:                   # start of L2CAP PDU
            if len(frag) < 4:
                continue
            l2len, cid = struct.unpack("<HH", frag[:4])
            pending[handle] = [cid, bytearray(frag[4:]), l2len]
        elif pb == 0x1 and handle in pending:
            pending[handle][1] += frag
        else:
            continue
        cid, acc, need = pending[handle]
        while len(acc) >= need:
            yield handle, cid, bytes(acc[:need])
            rest = acc[need:]
            if len(rest) < 4:
                acc.clear()
                break
            l2len, cid = struct.unpack("<HH", rest[:4])
            pending[handle] = [cid, bytearray(rest[4:]), l2len]
            cid, acc, need = pending[handle]
            if need == 0:
                break


def decode_att(b):
    op = b[0]
    name = ATT_OPS.get(op, f"op_{op:02X}")
    if op in (0x12, 0x52) and len(b) >= 3:
        return name, u16(b, 1), b[3:]
    if op in (0x1B, 0x1D) and len(b) >= 3:
        return name, u16(b, 1), b[3:]
    if op in (0x0B, 0x0D) and len(b) >= 1:
        return name, None, b[1:]
    if op == 0x13 and len(b) >= 1:
        return name, None, b[1:]
    return name, None, b[1:]


def cmd_att(args):
    shown = 0
    for handle, cid, pdu in l2cap_pdus(args.path):
        if cid != 0x0004:               # ATT
            continue
        if not pdu:
            continue
        name, h, val = decode_att(pdu)
        if args.handle is not None and h != args.handle:
            continue
        hs = f"0x{h:04X}" if h is not None else "   -  "
        print(f"acl={handle:03X} {name:<14} {hs} {val.hex(' ')}")
        shown += 1
    if not shown:
        print("no ATT traffic matched", file=sys.stderr)


def cmd_summary(args):
    stats = {}
    for handle, cid, pdu in l2cap_pdus(args.path):
        if cid != 0x0004 or not pdu:
            continue
        name, h, val = decode_att(pdu)
        key = (name, h)
        cnt, last = stats.get(key, (0, b""))
        stats[key] = (cnt + 1, val)
    if not stats:
        print("no ATT traffic")
        return
    print(f"{'op':<14} {'handle':<8} {'n':>5}  last value")
    for (name, h), (cnt, last) in sorted(stats.items(), key=lambda kv: (str(kv[0][1]), kv[0][0])):
        hs = f"0x{h:04X}" if h is not None else "-"
        print(f"{name:<14} {hs:<8} {cnt:>5}  {last.hex(' ')[:96]}")


SDP_ATTRS = {
    0x0000: "ServiceRecordHandle",
    0x0001: "ServiceClassIDList",
    0x0002: "ServiceRecordState",
    0x0003: "ServiceID",
    0x0004: "ProtocolDescriptorList",
    0x0005: "BrowseGroupList",
    0x0006: "LanguageBaseAttributeIDList",
    0x0008: "ServiceAvailability",
    0x0009: "BluetoothProfileDescriptorList",
    0x000A: "DocumentationURL",
    0x000B: "ClientExecutableURL",
    0x000C: "IconURL",
    0x0100: "ServiceName",
    0x0101: "ServiceDescription",
    0x0102: "ProviderName",
    0x0200: "GroupID",
    0x0201: "GroupType",
    0x0300: "IPSubnet",
}

UUID_NAMES = {
    0x0001: "SDP", 0x0003: "RFCOMM", 0x0007: "ATT", 0x0008: "OBEX",
    0x000C: "HTTP", 0x000D: "L2CAP(cid)", 0x000F: "BNEP", 0x0100: "L2CAP",
    0x1000: "ServiceDiscoveryServer", 0x1001: "BrowseGroupDescriptor",
    0x1101: "SerialPort", 0x1105: "OBEXObjectPush", 0x110A: "A2DP-Source",
    0x110B: "A2DP-Sink", 0x110C: "AVRCP-Target", 0x110D: "AVRCP",
    0x110E: "A/V RemoteControl", 0x110F: "AVRCP-Controller",
    0x1112: "Headset-AG", 0x111E: "Handsfree", 0x111F: "HandsfreeAudioGateway",
    0x1124: "HID", 0x112D: "PnPInformation", 0x112E: "PhonebookAccessPSE",
    0x112F: "PhonebookAccess", 0x1132: "MessageAccessServer",
    0x1200: "PnPInformation", 0x1303: "MPS", 0x1800: "GAP", 0x1801: "GATT",
}


def _de(b, o):
    """Parse one SDP data element. Returns (value, next_offset)."""
    dtd = b[o]
    typ = dtd >> 3
    si = dtd & 0x07
    o += 1
    if si <= 4:
        n = 1 << si
    elif si == 5:
        n = b[o]
        o += 1
    elif si == 6:
        n = be16(b, o)
        o += 2
    elif si == 7:
        n = int.from_bytes(b[o:o + 4], "big")
        o += 4
    else:
        n = 0
    end = o + n
    if typ in (0, 5):                       # nil / boolean
        return (None if typ == 0 else bool(n)), end
    if typ in (1, 2):                       # uint / int
        return int.from_bytes(b[o:end], "big"), end
    if typ == 3:                            # uuid
        if n == 2:
            return ("u16", be16(b, o)), end
        if n == 4:
            return ("u32", int.from_bytes(b[o:end], "big")), end
        return ("u128", b[o:end].hex()), end
    if typ in (4, 8):                       # text / url
        return b[o:end].decode("utf-8", "replace"), end
    if typ in (6, 7):                       # sequence / alternative
        items, p = [], o
        while p < end:
            v, p = _de(b, p)
            items.append(v)
        return items, end
    return b[o:end].hex(), end


def _uuid_str(u):
    if isinstance(u, tuple) and u[0] == "u16":
        return UUID_NAMES.get(u[1], f"0x{u[1]:04X}")
    if isinstance(u, tuple) and u[0] == "u32":
        v = u[1]
        return UUID_NAMES.get(v & 0xFFFF, f"0x{v:08X}")
    if isinstance(u, tuple):
        h = u[1]
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
    return str(u)


def _proto_chain(node):
    """Walk a ProtocolDescriptorList / -List-List into [(uuid, params...)]."""
    out = []
    if not isinstance(node, list):
        return out
    for stage in node:
        if not isinstance(stage, list) or not stage:
            continue
        uuid = _uuid_str(stage[0])
        params = []
        for p in stage[1:]:
            if isinstance(p, tuple) and p[0].startswith("u"):
                params.append(p[1])
            else:
                params.append(p)
        out.append((uuid, params))
    return out


def parse_sdp_record(body):
    """Decode one attribute-list blob into {attr_id: value}."""
    # Two encodings exist in the wild:
    #   database form : attrID(2) length(1) DE-value
    #   response form : DE(attrID) DE-value   (i.e. 09 XX XX before every value)
    # Real Android logs use the response form for attribute lists.
    attrs = {}
    o = 0
    while o + 3 <= len(body):
        if body[o] == 0x09:                  # DE unsigned-16 attribute ID
            aid = be16(body, o + 1)
            try:
                v, o = _de(body, o + 3)
            except IndexError:
                break
        else:
            aid = be16(body, o)
            l = body[o + 2]
            o += 3
            if l == 0xFF or (l and o + l > len(body)):
                break
            try:
                v, o = _de(body, o)
            except IndexError:
                break
        attrs[aid] = v
    return attrs


def decode_sdp_pdu(pdu):
    """Yield decoded attribute dicts from one SDP PDU (all response types)."""
    if len(pdu) < 5:
        return
    pdu_id = pdu[0]
    plen = be16(pdu, 3)
    params = pdu[5:5 + plen]
    if pdu_id == 0x05:                       # ServiceAttributeResponse
        if len(params) < 3:
            return
        n = be16(params, 0)
        attrs = parse_sdp_record(params[2:2 + n])
        if attrs:
            yield attrs
    elif pdu_id == 0x07:                     # ServiceSearchAttributeResponse
        o = 0
        while o + 2 <= len(params):
            n = be16(params, o)
            o += 2
            chunk = params[o:o + n]
            o += n
            if not chunk:
                break
            attrs = parse_sdp_record(chunk)
            if attrs:
                yield attrs
            if o >= len(params) - 1:
                break


def looks_like_sdp(pdu):
    """SDP rides PSM 0x0001, so its L2CAP CID is dynamic - match on shape."""
    if len(pdu) < 5 or pdu[0] not in (0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07):
        return False
    plen = be16(pdu, 3)
    return 5 + plen + 1 == len(pdu) or plen == len(pdu) - 5


def cmd_records(args):
    seen = {}
    order = []
    for handle, cid, pdu in l2cap_pdus(args.path):
        if cid == 0x0001 or not looks_like_sdp(pdu):
            continue
        for attrs in decode_sdp_pdu(pdu):
            h = attrs.get(0x0000)
            key = h if h is not None else len(order)
            if key not in seen:
                seen[key] = {}
                order.append(key)
            seen[key].update(attrs)

    if not order:
        print("no SDP responses decoded (log may start after service discovery)")
        return

    for key in order:
        a = seen[key]
        print(f"=== record 0x{key:08X} ===" if isinstance(key, int) else f"=== record {key} ===")
        for aid in (0x0001, 0x0009, 0x0004, 0x0100, 0x0102, 0x0008):
            if aid not in a:
                continue
            v = a[aid]
            label = SDP_ATTRS.get(aid, f"0x{aid:04X}")
            if aid == 0x0004:
                chain = _proto_chain(v)
                parts = []
                for uuid, params in chain:
                    if uuid == "L2CAP" and params:
                        parts.append(f"L2CAP(psm=0x{params[0]:04X}/{params[0]})")
                    elif uuid == "RFCOMM" and params:
                        parts.append(f"RFCOMM(ch={params[0]})")
                    elif params:
                        parts.append(f"{uuid}({params})")
                    else:
                        parts.append(uuid)
                print(f"  {label:<26}: " + " -> ".join(parts))
            elif aid == 0x0001:
                print(f"  {label:<26}: " + ", ".join(_uuid_str(u) for u in v)
                      if isinstance(v, list) else f"  {label:<26}: {v}")
            elif aid == 0x0009:
                flat = []
                if isinstance(v, list):
                    for item in v:
                        if isinstance(item, list) and item:
                            ver = ""
                            for x in item[1:]:
                                if isinstance(x, int):
                                    ver = f" v{x >> 8}.{x & 0xFF}"
                                    break
                            flat.append(f"{_uuid_str(item[0])}{ver}")
                print(f"  {label:<26}: " + (", ".join(flat) if flat else str(v)))
            else:
                print(f"  {label:<26}: {v}")


def cmd_sdp(args):
    blob = bytearray()
    n = 0
    for handle, cid, pdu in l2cap_pdus(args.path):
        if not looks_like_sdp(pdu):     # SDP has no fixed CID
            continue
        n += 1
        blob += pdu
        if args.hex:
            print(f"--- sdp pdu {n} ({len(pdu)}B) ---")
            print(pdu.hex(" "))
    print(f"# {n} SDP PDUs, {len(blob)} bytes", file=sys.stderr)

    if not args.uuid:
        return
    needle = args.uuid.replace("-", "")
    for order, raw in (("as-is", bytes.fromhex(needle)),
                       ("reversed", bytes.fromhex(needle)[::-1])):
        idx = 0
        while True:
            i = blob.find(raw, idx)
            if i < 0:
                break
            ctx = blob[max(0, i - 24):i + 40]
            print(f"uuid {args.uuid} found ({order}) at {i}: ...{ctx.hex(' ')}...")
            idx = i + 1


def cmd_grep(args):
    needle = bytes.fromhex(args.hex.replace(" ", ""))
    hits = 0
    for handle, cid, pdu in l2cap_pdus(args.path):
        i = pdu.find(needle)
        if i >= 0:
            hits += 1
            print(f"cid=0x{cid:04X} handle={handle:03X} off={i} {pdu.hex(' ')[:160]}")
    print(f"# {hits} hits", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="decode btsnoop HCI logs")
    ap.add_argument("path")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("att")
    a.add_argument("--handle", type=lambda s: int(s, 0))
    a.set_defaults(fn=cmd_att)

    sub.add_parser("summary").set_defaults(fn=cmd_summary)

    s = sub.add_parser("sdp")
    s.add_argument("--uuid", default="74ec2172-0bad-4d01-8f77-997b2be0722a")
    s.add_argument("--hex", action="store_true")
    s.set_defaults(fn=cmd_sdp)

    sub.add_parser("records").set_defaults(fn=cmd_records)

    g = sub.add_parser("grep")
    g.add_argument("hex")
    g.set_defaults(fn=cmd_grep)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
