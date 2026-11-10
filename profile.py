#!/usr/bin/env python3
"""
profile.py - read a captured device-profile.json on any OS.

The Linux side does the talking; this renders what it captured, so the same
file is useful on Windows or anywhere else without BlueZ, without root and
without any package.

    python profile.py                     # pretty report
    python profile.py -f other.json      # another profile
    python profile.py --json             # the raw document
    python profile.py --section battery  # one section
    python profile.py --html out.html    # standalone page, opens in a browser
    python profile.py --check            # validate, exit 1 on problems

Pure standard library. Python 3.8+, Windows and Linux.
"""

import argparse
import json
import os
import sys

DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "device-profile.json")
SCHEMA = "airpods-profile/v1"
SECTIONS = ("device", "protocol", "services", "controls", "capabilities",
            "battery", "codec", "link", "absent", "raw")


# ------------------------------------------------------------------ formatting
def bar(pct, width=20):
    try:
        pct = int(pct)
    except (TypeError, ValueError):
        return ""
    filled = max(0, min(width, round(width * pct / 100)))
    return "[" + "#" * filled + "." * (width - filled) + "]"


def table(rows, headers):
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(str(cell)))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    out = [line, "  ".join("-" * w for w in widths)]
    for r in rows:
        out.append("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))
    return "\n".join(out)


def kv(pairs, indent="  "):
    rows = [(k, "" if v is None else str(v)) for k, v in pairs]
    w = max((len(k) for k, _ in rows), default=0)
    return "\n".join(f"{indent}{k.ljust(w)}  {v}" for k, v in rows)


# -------------------------------------------------------------------- sections
def sec_device(p):
    d = p.get("device", {})
    out = ["DEVICE", kv([
        ("name", d.get("name")),
        ("mac", d.get("mac")),
        ("model", d.get("model")),
        ("manufacturer (reported)", d.get("manufacturer_reported")),
        ("firmware", d.get("firmware")),
        ("build", d.get("build")),
        ("hardware revision", d.get("hardware_rev")),
        ("updater app", d.get("updater_app")),
        ("serial", d.get("serial")),
        ("serial left", (d.get("bud_serials") or {}).get("left")),
        ("serial right", (d.get("bud_serials") or {}).get("right")),
    ])]
    ids = d.get("numeric_ids") or {}
    if ids:
        out.append("  numeric ids            " +
                   ", ".join(f"{k}={v}" for k, v in ids.items() if v))
    return "\n".join(out)


def sec_protocol(p):
    pr = p.get("protocol", {})
    rows = [(k, v) for k, v in pr.items() if k != "opcodes_seen"]
    out = ["PROTOCOL", kv(rows)]
    ops = pr.get("opcodes_seen") or {}
    if ops:
        out.append("  opcodes seen           " +
                   ", ".join(f"{k} x{n}" for k, n in sorted(ops.items())))
    return "\n".join(out)


def sec_services(p):
    svcs = p.get("services") or []
    if not svcs:
        return "SERVICES\n  (none captured - pass --sdp when building the profile)"
    rows = []
    for s in svcs:
        where = (f"PSM 0x{s['psm']:04X}" if s.get("psm") is not None
                 else f"RFCOMM ch {s['channel']}" if s.get("channel") is not None
                 else "-")
        rows.append((s.get("name"), where, s.get("version") or "-", s.get("uuid") or "-"))
    return "SERVICES\n" + table(rows, ["service", "transport", "version", "uuid"])


def sec_controls(p):
    ctrls = p.get("controls") or {}
    if not ctrls:
        return "CONTROLS\n  (none captured)"
    rows = []
    for key in sorted(ctrls):
        c = ctrls[key]
        rows.append((c.get("id"), c.get("name"), c.get("hex"),
                     c.get("decoded") or c.get("raw")))
    out = ["CONTROLS (pushed once per connection - this is the whole implemented set)",
           table(rows, ["id", "name", "raw", "decoded"])]
    notes = [c for c in ctrls.values() if c.get("decoded") == "unset/invalid"]
    if notes:
        out.append("  note: " + ", ".join(c["id"] for c in notes) +
                   " read 0, which is not a valid toggle value (1/2) - a host wrote 0 earlier")
    return "\n".join(out)


def sec_capabilities(p):
    caps = p.get("capabilities") or []
    if not caps:
        return "CAPABILITIES\n  (none captured)"
    out = ["CAPABILITIES (opcode 0x02, identical on every connection)"]
    for i, c in enumerate(caps, 1):
        out.append(f"  frame {i}: {c.get('bytes')} bytes")
        out.append("    " + " ".join(c.get("pairs") or []))
    out.append("  pairs are (key, value) with 0x01/0x02 = on/off; the 0x50-0xD0 keys "
               "look like feature groups. Not fully decoded.")
    return "\n".join(out)


def sec_battery(p):
    b = p.get("battery") or {}
    if not b:
        return "BATTERY\n  (none captured)"
    out = ["BATTERY"]
    for comp in ("left", "right", "case"):
        if comp not in b:
            continue
        e = b[comp]
        out.append(f"  {comp:<6} {str(e.get('percent')):>3}%  {bar(e.get('percent'))}  "
                   f"{e.get('state')}")
    return "\n".join(out)


def sec_codec(p):
    c = p.get("codec")
    if not c:
        return "AUDIO\n  (no codec capture - pass pactl output as --codec)"
    out = ["AUDIO", kv([("card", c.get("card")),
                        ("active profile", c.get("active_profile")),
                        ("vendor id", c.get("vendor_id")),
                        ("product id", c.get("product_id"))])]
    rows = [(x.get("profile"), x.get("codec") or "-") for x in c.get("profiles", [])]
    if rows:
        out.append(table(rows, ["profile", "codec"]))
    return "\n".join(out)


def sec_link(p):
    l = p.get("link")
    if not l:
        return "LINK\n  (no link capture - pass hcitool/bluetoothctl output as --link)"
    out = ["LINK"]
    acl = l.get("acl") or {}
    out.append(kv([
        ("lmp version", l.get("lmp_version")),
        ("lmp subversion", l.get("lmp_subversion")),
        ("manufacturer", l.get("manufacturer")),
        ("features page 0", l.get("features_page0")),
        ("features page 1", l.get("features_page1")),
        ("class of device", l.get("class_of_device")),
        ("modalias", l.get("modalias")),
        ("link quality", l.get("link_quality")),
        ("rssi", l.get("rssi")),
    ]))
    if acl:
        out.append("  acl                    " +
                   f"handle {acl.get('handle')} {acl.get('role')} {acl.get('security')}")
    return "\n".join(out)


def sec_absent(p):
    a = p.get("controls_absent") or []
    if not a:
        return "ABSENT CONTROLS\n  (not recorded)"
    names = ", ".join(x.get("id") for x in a)
    return ("ABSENT CONTROLS (real Apple ids, not implemented by this firmware)\n"
            "  " + names + "\n"
            "  Writing them produced no echo and no behaviour change.")


def sec_raw(p):
    pd = p.get("paired_devices")
    bk = p.get("ble_keys")
    out = ["RAW EXTRAS"]
    if pd:
        out.append("  paired-devices (0x2B)  mac=" + str(pd.get("mac")) +
                   f"  counter1={pd.get('counter1')} counter2={pd.get('counter2')}" +
                   "  tail=" + str(pd.get("tail")))
        out.append("    " + str(pd.get("hex")))
    if bk:
        out.append("  ble keys (0x31)        " +
                   (f"{bk.get('payload_bytes')} bytes, static across connections, "
                    "content withheld" if not bk.get("redacted")
                    else "present, static across connections, content withheld"))
    else:
        out.append("  ble keys (0x31)        not present in this capture")
    src = p.get("source") or {}
    out.append("  source                 " + ", ".join(
        f"{k}={v}" for k, v in src.items() if v is not None))
    return "\n".join(out)


SECTION_FUNCS = {
    "device": sec_device, "protocol": sec_protocol, "services": sec_services,
    "controls": sec_controls, "capabilities": sec_capabilities,
    "battery": sec_battery, "codec": sec_codec, "link": sec_link,
    "absent": sec_absent, "raw": sec_raw,
}


def render(p, sections):
    blocks = []
    for name in sections:
        fn = SECTION_FUNCS.get(name)
        if fn:
            blocks.append(fn(p))
    return "\n\n".join(blocks)


# ------------------------------------------------------------------------ html
HTML = """<!doctype html><meta charset="utf-8">
<title>{title}</title>
<style>
 body{{font:14px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;background:#0f1115;color:#e6e6e6;margin:0;padding:28px}}
 h1{{font-size:19px;margin:0 0 18px}} h2{{font-size:13px;letter-spacing:.12em;color:#8ab4f8;margin:26px 0 8px;text-transform:uppercase}}
 table{{border-collapse:collapse;margin:6px 0}} td,th{{border-bottom:1px solid #262a33;padding:4px 14px 4px 0;text-align:left;vertical-align:top}}
 th{{color:#9aa0a6;font-weight:400}} pre{{background:#161a21;padding:10px 12px;border-radius:6px;overflow-x:auto}}
 .pct{{color:#81c995}} .dim{{color:#9aa0a6}}
</style>
<h1>{title}</h1>
{body}
"""


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def to_html(p):
    d = p.get("device", {})
    parts = ["<h2>Device</h2>", "<table>"]
    for k, v in [("name", d.get("name")), ("mac", d.get("mac")),
                 ("model", d.get("model")), ("firmware", d.get("firmware")),
                 ("build", d.get("build")), ("serial", d.get("serial")),
                 ("updater app", d.get("updater_app"))]:
        parts.append(f'<tr><th>{k}</th><td>{esc(v)}</td></tr>')
    parts.append("</table>")

    b = p.get("battery") or {}
    if b:
        parts.append("<h2>Battery</h2><table>")
        for comp in ("left", "right", "case"):
            if comp in b:
                parts.append(f'<tr><th>{comp}</th><td class="pct">{esc(b[comp].get("percent"))}%</td>'
                             f'<td class="dim">{esc(b[comp].get("state"))}</td></tr>')
        parts.append("</table>")

    ctrls = p.get("controls") or {}
    if ctrls:
        parts.append("<h2>Controls</h2><table><tr><th>id</th><th>name</th><th>raw</th><th>decoded</th></tr>")
        for k in sorted(ctrls):
            c = ctrls[k]
            parts.append(f'<tr><td>{esc(c.get("id"))}</td><td>{esc(c.get("name"))}</td>'
                         f'<td>{esc(c.get("hex"))}</td><td>{esc(c.get("decoded"))}</td></tr>')
        parts.append("</table>")

    caps = p.get("capabilities") or []
    if caps:
        parts.append("<h2>Capabilities (0x02)</h2>")
        for c in caps:
            parts.append("<pre>" + esc(" ".join(c.get("pairs") or [])) + "</pre>")

    for title, key in (("Services", "services"), ("Link", "link")):
        block = p.get(key)
        if block:
            parts.append(f"<h2>{title}</h2><pre>" + esc(json.dumps(block, indent=1)) + "</pre>")

    return HTML.format(title=esc(f"{d.get('name')} ({d.get('model')}) - {SCHEMA}"),
                       body="\n".join(parts))


# ----------------------------------------------------------------------- check
def check(p):
    problems, notes = [], []
    if p.get("schema") != SCHEMA:
        problems.append(f"schema is {p.get('schema')!r}, expected {SCHEMA!r}")
    d = p.get("device") or {}
    for field in ("name", "mac", "model", "firmware"):
        if not d.get(field):
            problems.append(f"device.{field} is empty")
    mac = d.get("mac") or ""
    if mac and len(mac.split(":")) != 6:
        problems.append(f"device.mac {mac!r} is not a 6-part MAC")
    if not p.get("controls"):
        problems.append("no controls captured")
    for key, c in (p.get("controls") or {}).items():
        if c.get("name") == "":
            notes.append(f"control {key} has no known name")
        if key in ("0x26", "0x28") and c.get("decoded") == "unset/invalid":
            notes.append(f"control {key} holds 0 (invalid); valid range is 1/2")
    if not p.get("services"):
        notes.append("no SDP services captured")
    if not p.get("battery"):
        notes.append("no battery report captured")
    return problems, notes


def main():
    ap = argparse.ArgumentParser(description="render an airpods-profile/v1 capture")
    ap.add_argument("-f", "--file", default=DEFAULT)
    ap.add_argument("--json", action="store_true", help="print the raw document")
    ap.add_argument("--html", metavar="OUT", help="write a standalone HTML page")
    ap.add_argument("--section", action="append", choices=["all"] + list(SECTIONS),
                    help="one or more sections (default: all)")
    ap.add_argument("--check", action="store_true", help="validate and exit")
    args = ap.parse_args()

    if not os.path.exists(args.file):
        sys.exit(f"no profile at {args.file}\n"
                 "Build it on the machine that has the earbuds:\n"
                 "  cd linux && python3 aap_l2cap.py --mac <MAC> dump --out ../data/state.json\n"
                 "  python3 make_profile.py ../data/state.json --sdp ../data/sdp.txt -o ../device-profile.json")

    with open(args.file, encoding="utf-8") as f:
        p = json.load(f)

    if args.check:
        problems, notes = check(p)
        for n in notes:
            print("note   :", n)
        for pr in problems:
            print("PROBLEM:", pr)
        print("OK" if not problems else f"{len(problems)} problem(s)")
        return 0 if not problems else 1

    if args.json:
        print(json.dumps(p, indent=1, ensure_ascii=False))
        return 0

    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(to_html(p))
        print(f"wrote {args.html}")
        return 0

    sections = args.section or list(SECTIONS)
    if "all" in sections:
        sections = list(SECTIONS)
    print(render(p, sections))
    return 0


if __name__ == "__main__":
    sys.exit(main())
