# Findings — Pro NewGen (A2084) over AAP/AACP

Everything below was measured on the live unit, not taken from a spec sheet.
Where a value is a clone's lie, it is labelled as such.

- Device: `Pro NewGen`, MAC `41:42:23:76:ED:B8`
- Host: Linux, BlueZ 5.7x, adapter `F0:68:E3:BB:69:ED`
- Captures: `data/device-state-linux.json` (raw frames), `data/sdp-linux.txt`,
  `data/audio-codec.txt`, `data/link-info.txt`, `data/bluetooth-info.txt`

---

## 1. Identity

| Field | Value | Source |
|---|---|---|
| Advertising name | `Pro NewGen` | advertisement + `0x1D` |
| Model | `A2084` | `0x1D` |
| Manufacturer string | `Apple Inc.` | `0x1D` (clone spoof) |
| VID / PID | `0x004C` / `0x2014` | `device.vendor.id` / `product.id` in BlueZ |
| Modalias | `bluetooth:v004Cp2014d4C1B` | PnP record |
| Class of Device | `0x00240404` (audio / wearable headset) | `bluetoothctl info` |
| LMP | version `0x0E` (BT 5.2), subversion `0x3` | HCI |
| Serial | `GWXZD0ZPLKKT` | `0x1D` subtype `0xA4` |
| Bud serials | `GX6ZPWA0JQH4` (L), `GXCZPBWFJQH3` (R) | `0x1D` |
| Firmware | `1.56.1` | `0x1D` subtype `0x86` |
| Build | `21.620040031000000.695` | `0x1D` subtype `0xAF` / `0xA4` |
| Hardware revision | `1.0.0` | `0x1D` field 7 |
| Updater app | `com.apple.accessory.updater.app.60-ANC` | `0x1D` subtype `0x86` |
| Updater app (multi-asset) | `com.apple.accessory.updater.app.multiasset.60` | `0x1D` subtype `0xAF` |
| Numeric ids | `2172096` (build report), `79873` (firmware report) | `0x1D` field 11 |

The unit sends **three** device-info reports on every connection, distinguished
by the byte at payload offset 1 (`0x1D 00 01 <subtype> 00 <len> 00 <strings>`):

| Subtype | Carries |
|---|---|
| `0xA4` | base build (`21.620040031000000.695`), updater `.60` |
| `0xAF` | multi-asset build, updater `.multiasset.60` |
| `0x86` | running firmware `1.56.1`, updater `.60-ANC` |

All three carry the same name/model/manufacturer/serial/bud serials, so the
string layout is stable and can be parsed once:

```
name, model, manufacturer, serial, firmware, firmware2, hardware_rev,
updater_app, serial_left, serial_right, numeric_id
```

Two further fields exist on genuine AirPods (documented as encrypted blobs);
this firmware sends none.

## 2. Transport and SDP

The accessory advertises exactly two usable services:

| Service | Where | Notes |
|---|---|---|
| Handsfree `0x111E` | RFCOMM channel 2, v1.7 | HFP only |
| AAP Server | **L2CAP PSM `0x1001`** (4097), v1.0 | UUID `74ec2172-0bad-4d01-8f77-997b2be0722a` |

Also present: Service Discovery `0x1000`, Audio Sink `0x110B`, AVRCP Target
`0x110C`, AVRCP Controller `0x110E`, PnP `0x1200`.

**Not present:** any vendor RFCOMM/L2CAP PSM, any vendor GATT service, and the
RemoteHID channel `0x800` that AirPods 3 use to expose motion sensors. That
absence is what closes off host-side gesture remapping — see §8.

Linux opens PSM `0x1001` directly (`AF_BLUETOOTH` `SOCK_SEQPACKET`, needs
`CAP_NET_RAW`). Windows cannot: this stack rejects `SOCK_SEQPACKET` at
`socket()` and returns `10050` for every PSM, including `0x0003`, so the AAP
path is unavailable there (see `README.md`).

## 3. Frame format

```
04 00 04 00 <opcode LE u16> <payload>
```

Handshake (required, or nothing else answers):

```
00 00 04 00 01 00 02 00 00 00 00 00 00 00 00 00
```

Set-features (what macOS sends; unlocks some behaviours):

```
04 00 04 00 4D 00 D7 00 00 00 00 00 00 00
```

Subscribe to notifications:

```
04 00 04 00 0F 00 FF FF FF FF
```

### The read rule (this one cost the most time)

`04 00 04 00 09 00 <id> 00 00 00 00` is **not a query**. It is a write with the
value 0. The accessory pushes its entire control table exactly **once per
connection**, unprompted, 6–9 s after the handshake. Everything the tool calls
"read" is therefore an accumulator over all frames seen on the socket, not a
request/response pair. A mid-session `0x0F` re-subscribe returns nothing, and
writing zeros is what left `0x26`/`0x28` stuck at an invalid value.

## 4. Everything the unit sends on connect

| Op | Payload | Meaning |
|---|---|---|
| `0x00` | `01 00 00 00 0B 00 06 00 00 00 00 00` | handshake ACK |
| `0x1D` | 3 reports | device information (see §1) |
| `0x31` | `02 01 00 10 00 <16> 04 00 10 00 <16>` | BLE key material, **identical on every connection** |
| `0x09` | `0D 02 00 00 00` | ListeningMode = 2 (ANC) |
| `0x0E` | `AE A7 A1 E3 DB F4 00` | audio source response, **identical on every connection** |
| `0x02` | 16 bytes | capabilities, frame 1 |
| `0x04` | `03 04 01 44 00 01 02 01 45 00 01 08 01 64 02 01` | battery |
| `0x2B` | 28 bytes | paired-devices record, **changes every connection** |
| `0x02` | 54 bytes | capabilities, frame 2 |
| `0x09` | `24 21 23 02 00` | CallManagementConfig |
| `0x09` | `26 02 00 00 00` | AdaptiveVolume = 2 (disabled) |
| `0x09` | `28 02 00 00 00` | ConversationDetect = 2 (disabled) |
| `0x06` | `00 00` | ear detection: both in ear |

### Battery (`0x04`)

```
04 00 04 00 04 00 <count> ( <component> 01 <level> <status> 01 ) * count
```

| Byte | Meaning |
|---|---|
| component | `04` left, `02` right, `08` case |
| level | 0–100 |
| status | `00` unknown, `01` charging, `02` discharging, `04` disconnected |

Captured: left 68 % (unknown), right 67 % (unknown), case 100 % (discharging).
The trailing `01` is a fixed per-entry terminator.

### Capabilities (`0x02`)

Two frames, **byte-identical on every connection** (so they are a firmware
constant, not state). They read as (key, value) byte pairs with the same
`01`/`02` on/off encoding as the control table:

```
0601 0e02 0204 0100 0000 1001 4001 8001
1301 0e02 0204 0100 0000 1002 4001 0302 0000 0006 0300 0000
0a01 0901 0f01 0701 0000 0030 0100 0000
5002 a001 9001 b001 c001 d001 6001
```

Keys `0x50`–`0xD0` do not collide with any control id and look like feature
groups. The exact schema is not public; this is recorded, not claimed.

### Paired devices (`0x2B`)

```
01 11 00 [u32] 00 00 00 00 [u32] 00 00 00 00 <6-byte MAC> <3 bytes>
```

Captured twice, 20 minutes apart:

| Field | Session A | Session B |
|---|---|---|
| counter 1 | `238277` | `325789` |
| counter 2 | `70471` | `179819` |
| MAC | `41:42:23:76:ED:B8` | `41:42:23:76:ED:B8` |
| tail | `23 23 23` | `00 00 23` |

The MAC is the **accessory's own**, not the host's (`F0:68:E3:BB:69:ED`), so the
clone reports itself in a "paired devices" list. The two counters are random per
connection — most likely nonces, not counters.

### BLE keys (`0x31`)

```
02 01 00 10 00 <16 bytes> 04 00 10 00 <16 bytes>
```

32 bytes of key material, pushed unprompted, **the same 32 bytes on every
connection**. That makes it static key material, not a per-session exchange —
so it is excluded from this repository (`data/device-state-linux.json` has the
frame removed, the profile records only its presence). Anyone reproducing the
capture will see the same bytes.

## 5. Control table — the whole implemented set

The connect-time push is authoritative: it lists exactly four controls.

| ID | Name | Value | Writable |
|---|---|---|---|
| `0x0D` | ListeningMode | `1` off, `2` ANC, `3` transparency, `4` adaptive | yes |
| `0x24` | CallManagementConfig | `21 23 02 00` (4-byte bitfield, undecoded) | no echo on write |
| `0x26` | AdaptiveVolume | `1` enabled, `2` disabled | yes |
| `0x28` | ConversationDetect | `1` enabled, `2` disabled | yes |

Toggle encoding across the protocol is **`1` = enabled, `2` = disabled**, not
boolean. Values outside that range are accepted and stored but meaningless —
which is how `0x26` and `0x28` sat at `0` until the tier-1 script wrote `2` back.
The capture in `data/` was taken after that write, so it shows `02`.

### Verified absent (41 ids)

Writing each produced no echo and no behaviour change:

`0x01` `0x05` `0x06` `0x0A` `0x12` `0x14` `0x15` `0x16` `0x17` `0x18` `0x1A`
`0x1B` `0x1C` `0x1E` `0x1F` `0x20` `0x23` `0x25` `0x27` `0x29` `0x2C` `0x2E`
`0x2F` `0x30` `0x31` `0x32` `0x33` `0x34` `0x35` `0x36` `0x37` `0x38` `0x39`
`0x3A` `0x3B` `0x3C` `0x3D` `0x3E` `0x3F` `0x40` `0x41`

These are real Apple ids — `0x14/0x15/0x16` are single/double/press-and-hold,
`0x1F` chime volume, `0x31` in-case tone, `0x39` raw-gesture bitmask — the
firmware simply does not implement them. Calling the wrong id was never the
problem.

## 6. Audio

BlueZ offers exactly five profiles for this device:

| Profile | Codec |
|---|---|
| `a2dp-sink` (active) | **SBC** |
| `a2dp-sink-sbc_xq` | SBC-XQ |
| `headset-head-unit-cvsd` | CVSD |
| `headset-head-unit-msbc` | mSBC |
| `headset-head-unit` | HFP |

**No AAC, no aptX, no LDAC, no LC3.** A genuine A2084 offers AAC; a firmware
that only does SBC is the single clearest fingerprint that this is a clone, and
it is one you can confirm without root:

```bash
pactl list cards | grep -A3 bluez_card.41_42_23_76_ED_B8
```

The sink reports `s16le 2ch 48000Hz` from PipeWire. SBC at that rate is the
bandwidth floor for the whole device.

## 7. Link layer

| Item | Value |
|---|---|
| LMP version | `0x0E` (Bluetooth 5.2), subversion `0x3` |
| Manufacturer | `Apple, Inc. (76)` — spoofed |
| Features page 0 | `0xbf 0x2e 0x4d 0xfa 0xd8 0x3d 0x7b 0x87` |
| Features page 1 | `0x01 00 00 00 00 00 00 00` |
| Link quality | `127` |
| RSSI | `0` |
| ACL | handle `51`, role `CENTRAL`, `AUTH ENCRYPT` |
| BlueZ battery cache | `0x46` (70 %) |

Page 0 advertises 3-/5-slot packets, EDR, encryption, sniff, SCO/eSCO, LE and
BR/EDR, secure simple pairing. Nothing exotic, nothing that would explain the
instability beyond a weak radio.

## 8. Three hard limits

1. **The charging / case chime cannot be disabled over AAP.** The tone fires
   with no host link at all, so no host command can reach the code that plays
   it. The ids that would do it (`0x1F`, `0x31`, `0x40`) are absent anyway.
2. **Touch gestures cannot be remapped.** `0x14/0x15/0x16/0x39` are absent, and
   the alternative path (RemoteHID `0x800`, where taps become HID events that
   `evdev` could remap per side) is not advertised by this unit.
3. **The two buds cannot be told apart.** Both emit the same AVRCP
   `PlayPause`; HCI carries no side byte. Any "left bud does X" idea is
   impossible at the protocol level, not merely unimplemented here.

What *is* reachable: mode control, the two toggles, battery, identity, rename,
and anything host-side (see `linux/yt_ad.py`).

## 9. Security observations

- **Static BLE key material.** `0x31` delivers the same 32 bytes on every
  connection to every host that completes the handshake. Genuine AirPods
  negotiate per-host material.
- **Spoofed identity.** Apple VID/PID, `Modalias v004Cp2014d4C1B`, and the
  `Apple Inc.` string are all clone-controlled claims, contradicted by the SBC
  only codec list.
- **Self-report in `0x2B`.** The "paired devices" record lists the accessory's
  own MAC where a host address belongs.
- **Unauthenticated control channel.** PSM `0x1001` accepts the documented
  handshake from any host that pairs; there is no per-command authorisation.
  Anything paired can change modes and rename the device.

## 10. Performance, measured

| Operation | Before | After | Why |
|---|---|---|---|
| `dump` (16 frames) | ~20 s | **9.9 s** | `xfer()`/`collect()` stop on an idle window instead of sleeping a fixed time |
| One control write | 0.8 s fixed | **~0.03 s** | `xfer()` returns as soon as the reply lands |
| Ad skip latency | 500–1500 ms | **1 ms** | MutationObserver in the page, not polling |
| 4 settings applied | 4 connections | 1 connection | `stabilize` batches the writes |
| State read | missed half the time | complete | parse every frame seen on the socket (`SEEN`) |

9.9 s is close to the floor: the accessory itself waits 6–9 s after the
handshake before pushing anything. Smaller numbers require a firmware change,
not a client change.

## 11. Next steps

1. **Bind the tap to the ad skipper.** Watch `org.mpris.MediaPlayer2.Player`
   `PlayPause` on D-Bus; when a tap arrives while the page has `.ad-showing`,
   run the skip and resume. ~40 lines, and the only route to "the tap does
   something better than pause".
2. **Auto-apply the stabilize profile on connect.** A BlueZ `Device1.Connected`
   signal handler that writes the four controls. Turns "flaky" into
   self-healing.
3. **Battery widget** on the bar (Waybar/QML) from the same session — the
   decoding already exists.
4. **Capture the vendor app.** The existing HCI log is our own session (23 AAP
   frames, 4 controls), not the app's. If a companion app ever writes a chime or
   gesture id, `linux/aap_from_snoop.py` flags it immediately. Until then there
   is nothing to find.
5. **Firmware: not viable.** The updater is signed, the flash layout is not
   Huilian's, and there is no recovery path. A brick is permanent.

## 12. References

- [librepods-org/librepods](https://github.com/librepods-org/librepods) —
  AAP/AACP reference implementation and the best opcode/control-id tables
  (`docs/opcodes.md`, `docs/control_commands.md`, `docs/AAP Definitions.md`).
  Source of the control-id names used here.
- [zeffd/airpods](https://github.com/zeffd/airpods) — single-file stdlib client;
  confirmed the 1-based listening-mode values and the `1`/`2` toggle encoding.
- [starman-tech/mousepods](https://github.com/starman-tech/mousepods) — first
  public documentation of RemoteHID (HID over AACP) on channel `0x800`.
- [spacedouut/OpenHuilian](https://github.com/spacedouut/OpenHuilian) — Huilian
  377H3 firmware tooling and a decompiled StarFun app, for the other clone
  family. Not applicable to A2084, but the closest prior art.

## 13. Verification status

- `linux/test_decode.py` — 15/15 captured frames decode, assertions pass.
- `profile.py --check` — schema and sanity checks pass (2 known notes).
- `linux/yt_ad.py --self-test` — PASS on Edge 157 (one-shot + observer).
- `linux/preflight.sh` — 5/5 gates OK on the live device.
- `read`, `mode`, `stabilize`, `dump` — run against hardware; values echo back.
