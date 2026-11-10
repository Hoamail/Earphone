# run/ — bấm là chạy, chia theo mức ảnh hưởng

Ba tầng, xếp theo **mức cải thiện thật** đo được trên thiết bị này, không theo
độ phức tạp. Tầng 1 sửa được nhiều nhất và an toàn nhất; tầng 3 là để vọc tiếp.

Mọi script Linux đều tự đọc MAC từ `device-profile.json`
(hoặc biến `EARPHONE_MAC`), tự snapshot trước khi ghi, và tự dừng chờ Enter khi
bạn bấm đúp từ file manager.

Cài shortcut vào menu ứng dụng + Desktop:

```bash
cd run/linux && ./install-shortcuts.sh
```

---

## Tầng 1 — ảnh hưởng lớn nhất (sửa ngay)

| File | Việc | Vì sao đáng làm |
|---|---|---|
| `linux/1-fix-instability.sh` | Ghi 4 control trong **một** kết nối: `0x26=2`, `0x28=2`, `0x2E=0`, `0x1B=2` | Đây là nguyên nhân của "âm lượng tự tăng giảm", "tự hạ tiếng khi mình nói", "ANC tự đổi cường độ". Trước đây tốn 4 kết nối và 4 lần handshake; giờ 1 |
| `linux/1-restore.sh` | Nạp lại snapshot `settings-before-*.json` mới nhất | Đường lui, luôn có sẵn |

Giá trị ghi là **2 = disabled**, không phải 0. Số 0 là giá trị không hợp lệ và
chính là thứ đã để hai toggle kẹt ở trạng thái vô nghĩa.

Windows: không có tầng 1, vì Windows không mở được L2CAP `0x1001` trên stack
MediaTek (`10044` khi tạo socket, `10050` cho mọi PSM). Đó là giới hạn của
stack, không phải của tai nghe.

## Tầng 2 — tự động hoá (bớt phải nghĩ)

| File | Việc | Ảnh hưởng |
|---|---|---|
| `linux/2-auto-apply.sh install` | Cài systemd service, tự áp cấu hình tầng 1 mỗi lần tai nghe kết nối | Biến "thỉnh thoảng lại chập chờn" thành tự chữa. Chỉ ghi khi link **vừa** lên, đúng một lần mỗi kết nối |
| `linux/2-battery.sh` | Đọc pin L / R / hộp | ~10 s, vì bản thân tai nghe chờ 6–9 s mới chịu nói |
| `linux/2-mode.sh [anc\|trans\|off\|adapt]` | Không tham số thì đảo giữa ANC và Transparency | Một phím thay vì mở app |
| `linux/2-tap-skip.sh` | Bắt MPRIS `PlaybackStatus`: chạm tai nghe khi đang có quảng cáo thì bỏ quảng cáo rồi chạy tiếp | Cú chạm giữ nguyên nghĩa pause khi không có quảng cáo. Không phân biệt trái/phải — cả hai gửi cùng một `PlayPause` |
| `windows/1-open-profile.cmd` | Mở `device-profile.json` trên Windows | Cách duy nhất để "xem tai nghe" từ máy Windows |
| `windows/2-start-edge-debug.cmd` | Mở Edge với cổng debug + profile riêng | Điều kiện bắt buộc cho ad skipper |
| `windows/2-skip-ads-now.cmd` | Bỏ quảng cáo đang chiếu, một lần | Kiểm tra nhanh |
| `windows/2-skip-ads-watch.cmd` | Chạy nền, quảng cáo nào hiện là bị giết (~1 ms) | Thay cho việc poll 0.5–1.5 s |

## Tầng 3 — sâu / chẩn đoán

| File | Việc | Khi nào dùng |
|---|---|---|
| `linux/3-monitor.sh [phút]` | Theo dõi link: socket rơi, control đổi liên tục, pin nhảy | Khi cần trả lời "tại sao nó ngắt" bằng log |
| `linux/3-experiment.sh <id> [byte...]` | Ghi thử một control id, xem thiết bị có echo | Để tự kiểm chứng 41 id vắng mặt, hoặc thử id mới |
| `linux/3-decode-snoop.sh [log]` | Giải mã btsnoop: SDP + mọi frame AAP, cờ đỏ id lạ | Đường duy nhất còn lại để tìm lệnh chime/gesture |
| `windows/3-report-html.cmd` | Xuất `report.html` rồi mở | Báo cáo để đọc/xem |
| `windows/3-check-profile.cmd` | `profile.py --check` | Sau khi sửa tay file profile |

---

## Vì sao chia như vậy

Tầng 1 tác động lên **hành vi của tai nghe** — nó sửa đúng ba thứ làm thiết bị
khó dùng. Tầng 2 không sửa thiết bị mà sửa **cách bạn chạm vào nó**: không phải
nhớ lệnh, không phải mở app, không phải chờ. Tầng 3 không cải thiện gì cả — nó
là công cụ để tìm ra tầng 1 tiếp theo.

Ba thứ **không** làm được, ở bất kỳ tầng nào, đã kiểm chứng bằng ghi thật:
tắt tiếng bíp (`0x1F/0x31/0x40` không tồn tại), remap cảm ứng (`0x14/0x15/0x16/
0x39` không tồn tại), phân biệt trái/phải (không có byte side trong HCI).
Xem `FINDINGS.md` §8.
