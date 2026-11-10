# Earphone — bộ công cụ AAP/AACP cho tai nghe TWS

Reverse-engineer một đôi tai nghe "Pro NewGen" (clone AirPods Pro, model
`A2084`, MAC `41:42:23:76:ED:B8`), điều khiển nó từ Linux bằng giao thức AAP
thật của Apple, và xuất dữ liệu thành một file profile đọc được trên Windows.

Không cần app hãng, không cần driver, không cần cài package Python nào.

```
Linux  ──(L2CAP PSM 0x1001)──►  tai nghe
   │
   └── device-state.json ──► make_profile.py ──► device-profile.json
                                                     │
Windows / bất kỳ máy ──► profile.py ──────────────────┘
```

## Kết quả ngắn gọn

| Việc | Được? |
|---|---|
| Đọc pin L / R / hộp | ✅ |
| Đổi ANC / Transparency / Off / Adaptive | ✅ |
| Tắt Adaptive Volume, Conversation Detect | ✅ |
| Đọc tên, model, firmware, build, serial, service pack | ✅ |
| Đọc danh sách control mà firmware thật sự cài | ✅ |
| Đổi tên tai nghe | ✅ |
| Tắt tiếng bíp sạc / bíp hộp | ❌ firmware không cài `0x1F/0x31/0x40` |
| Remap cảm ứng | ❌ không có `0x14/0x15/0x16/0x39`, không có RemoteHID |
| Phân biệt tai trái / phải | ❌ cả hai gửi cùng một AVRCP `PlayPause` |
| Bỏ quảng cáo YouTube bằng cú chạm | ⚠️ làm được ở phía máy (xem `linux/yt_ad.py`) |

Chi tiết đầy đủ, kèm byte của từng frame: **[FINDINGS.md](FINDINGS.md)**.

## Cấu trúc repo

| Đường dẫn | Nội dung |
|---|---|
| `linux/aap_l2cap.py` | Client AAP trên BlueZ L2CAP: `read`, `dump`, `mode`, `probe-modes`, `stabilize`, `restore`, `monitor`, `cmd`, `rename`, `raw`, `probe`, `battery` |
| `linux/make_profile.py` | Biến capture Linux thành `device-profile.json` (có parse SDP, codec, link layer) |
| `profile.py` | Đọc profile trên **mọi OS**: text, `--json`, `--html`, `--check` |
| `linux/preflight.sh` | 5 bước kiểm tra trước khi động vào thiết bị |
| `linux/setup.sh` | Cài bluez, pair/trust, dump SDP, dump state (chỉ đọc) |
| `linux/beep_off.py` | Dò id tiếng bíp: ghi thử → bạn nghe → giữ cái đúng |
| `linux/yt_ad.py` | Bỏ quảng cáo YouTube qua CDP: one-shot, `--install` (observer ~1 ms), `--watch`, `--stats`, `--self-test` |
| `linux/aap_from_snoop.py` | Lôi frame AAP từ log HCI, **cờ đỏ mọi control id lạ** |
| `linux/test_decode.py` | Replay 15 frame thật qua decoder, có assert |
| `btsnoop.py` | Đọc log HCI/btsnoop không cần Wireshark (L2CAP, ATT, SDP) |
| `aap.py` | Cùng giao thức nhưng cho Windows, qua Winsock `AF_BTH` |
| `gatt.py`, `ble_gatt.ps1` | Dò BLE GATT (bleak + WinRT) |
| `ports.py` | Dò RFCOMM channel / L2CAP PSM mà firmware trả lời |
| `wake.ps1`, `linkstate.ps1` | Ép tạo ACL link; đọc trạng thái link thật thay vì cache "Connected" |
| `pull_snoop.ps1`, `pull_log.ps1` | Kéo + giải mã log HCI của điện thoại |
| `data/` | Capture gốc: frame, SDP, codec, link layer |
| `device-profile.json` | Profile đã tổng hợp, schema `airpods-profile/v1` |

## Chạy trên Linux

```bash
cd linux
sudo ./preflight.sh            # 5 cổng: adapter, link, echo L2CAP, AAP Server, PSM
sudo python3 aap_l2cap.py --mac 41:42:23:76:ED:B8 read
```

`read` in ra toàn bộ control mà tai nghe tự đẩy lên khi kết nối:

```
4 controls:
  ListeningMode        2  (anc)
  CallManagementConfig 21 23 02 00
  AdaptiveVolume       1
  ConversationDetect   2
```

Đổi mode, rồi áp cấu hình chống chập chờn (có snapshot + `restore`):

```bash
sudo python3 aap_l2cap.py --mac 41:42:23:76:ED:B8 mode anc
sudo python3 aap_l2cap.py --mac 41:42:23:76:ED:B8 stabilize
sudo python3 aap_l2cap.py --mac 41:42:23:76:ED:B8 restore
```

Dump toàn bộ frame ra file:

```bash
sudo python3 aap_l2cap.py --mac 41:42:23:76:ED:B8 --seconds 10 dump --out ../data/state.json
```

`sudo` là bắt buộc: mở L2CAP cần `CAP_NET_RAW`.

### Dựng profile để mang sang máy khác

```bash
cd linux
python3 make_profile.py ../data/device-state-linux.json \
        --sdp   ../data/sdp-linux.txt \
        --codec ../data/audio-codec.txt \
        --link  ../data/link-info.txt \
        --link  ../data/bluetooth-info.txt \
        -o ../device-profile.json
```

`--sdp` lấy từ `sdptool browse <MAC>`, `--codec` từ `pactl list cards`,
`--link` từ `hcitool info <MAC>` và/hoặc `bluetoothctl info <MAC>`.

## Chạy trên Windows

Windows **không mở được L2CAP PSM `0x1001`** trên stack MediaTek: `SOCK_SEQPACKET`
bị từ chối ngay từ `socket()` (`10044`), và mọi PSM trả `10050`, kể cả `0x0003`.
Đó là giới hạn của stack, không phải của tai nghe — SDP trong log HCI của điện
thoại cho thấy kênh AAP có thật và đang mở.

Nên trên Windows có hai việc làm được:

**1. Đọc profile do Linux bắt** (không cần quyền gì, không cần package):

```powershell
python profile.py
python profile.py --section battery --section controls
python profile.py --html report.html
python profile.py --check
```

**2. Thử mở kênh AAP** — để xem stack của bạn có khác không:

```powershell
python aap.py devices
python aap.py --name "Pro NewGen" probe
python aap.py --name "Pro NewGen" battery
python aap.py --name "Pro NewGen" anc anc      # off | anc | trans | adapt
python aap.py --name "Pro NewGen" caps
python wake.ps1 -Mac 41:42:23:76:ED:B8         # ép tạo ACL link
python linkstate.ps1                            # trạng thái link thật
```

Hai bẫy đã gặp và đã xử lý trong code:

- `SOCKADDR_BTH` là struct **byte-packed** (`sizeof` = 30). Khai báo theo căn
  chuẩn tự nhiên (40 byte) làm `btAddr` lệch 6 byte → mọi connect trả `10049`.
- `SDP live (GetRfcommServicesAsync)` chỉ trả HFP `0x111E`. Record `AAP2Server`
  chỉ có trong cache SDP của lần pairing trước.

## Thiết bị

| Trường | Giá trị |
|---|---|
| Tên | `Pro NewGen` |
| Model | `A2084` (clone) |
| MAC | `41:42:23:76:ED:B8` |
| VID/PID | `0x004C:0x2014` (Apple — clone ghi đè) |
| Modalias | `bluetooth:v004Cp2014d4C1B` |
| Class of Device | `0x00240404` |
| LMP | 5.2 (`0x0E`), subversion `0x3` |
| Firmware | `1.56.1` |
| Build | `21.620040031000000.695` |
| Serial / bud serials | `GWXZD0ZPLKKT` · `GX6ZPWA0JQH4` · `GXCZPBWFJQH3` |
| Codec | **chỉ SBC / SBC-XQ** — không AAC, không aptX, không LDAC |

Dòng cuối là dấu vân tay rõ nhất: A2084 thật có AAC.

## Giao thức trong một khung hình

```
04 00 04 00 <opcode LE> <payload>
```

| Opcode | Nghĩa |
|---|---|
| `0x00` | handshake (bắt buộc, không có thì thiết bị không trả lời gì) |
| `0x02` | capabilities (2 frame, giống hệt nhau mọi lần kết nối) |
| `0x04` | pin |
| `0x06` | ear detection |
| `0x09` | control command — `09 00 <id> <d1> <d2> <d3> <d4>` |
| `0x0E` | audio source response |
| `0x1D` | device info (3 báo cáo: `0xA4`, `0xAF`, `0x86`) |
| `0x2B` | paired devices (mang chính MAC của tai nghe) |
| `0x31` | BLE keys (32 byte, **giống hệt nhau mọi lần** — không đưa vào repo) |

Điều quan trọng nhất: `09 00 <id> 00 00 00 00` **là ghi, không phải đọc**. Thiết
bị chỉ đẩy bảng trạng thái một lần cho mỗi kết nối, sau handshake 6–9 giây.

## Hiệu năng (đo thật)

| Việc | Trước | Sau |
|---|---|---|
| `dump` 16 frame | ~20 s | **9.9 s** |
| Một lệnh ghi control | 0.8 s cố định | **~0.03 s** |
| Bỏ quảng cáo YouTube | 500–1500 ms | **1 ms** |
| Áp 4 setting | 4 kết nối | 1 kết nối |

9.9 s là sát sàn: bản thân tai nghe chờ 6–9 s mới đẩy dữ liệu. Nhanh hơn nữa thì
phải sửa firmware, không phải sửa client.

## Ghi chú

- Repo không chứa secret: registry backup của Windows (`backup/`), log HCI
  (`snoop/`), và 32 byte BLE key của `0x31` đều bị loại khỏi git.
- Mọi thứ ở đây chạy trên thiết bị của chính người viết.
- Tham khảo: librepods, zeffd/airpods, mousepods, OpenHuilian — xem cuối
  [FINDINGS.md](FINDINGS.md).

## Giấy phép

MIT — xem [LICENSE](LICENSE).
