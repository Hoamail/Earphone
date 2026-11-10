# pull_log.ps1 - pull the Android btsnoop HCI log and decode it.
#
# No Wireshark needed: decoding is done by ..\btsnoop.py (stdlib only).
#
#   1. Developer options -> "Enable Bluetooth HCI snoop log" (already done)
#   2. On the phone: toggle Bluetooth off/on so the log restarts
#   3. Open the earbuds' app (if any) / connect the buds / change every setting
#   4. Plug the phone in, authorize USB debugging, then:
#        .\pull_log.ps1
#
# Root is not required for the bugreport path, but it is much slower.

param(
    [string]$Out = "$PSScriptRoot\snoop",
    [string]$Adb = 'C:\adb\platform-tools\adb.exe',
    [switch]$BugreportOnly
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path $Adb)) { throw "adb not found at $Adb" }
New-Item -ItemType Directory -Force -Path $Out | Out-Null

function Adb { & $Adb @args 2>&1 }

$devices = Adb devices
$devices | ForEach-Object { Write-Host $_ }
if (-not ($devices -match '\sdevice$')) {
    throw 'no adb device: plug the phone in, unlock it, accept the USB debugging prompt'
}

$model = (Adb shell getprop ro.product.model) -join ''
$mode = (Adb shell getprop persist.bluetooth.btsnooplogmode) -join ''
Write-Host "phone: $model   btsnooplogmode: $mode"

$log = $null
if (-not $BugreportOnly) {
    foreach ($p in @('/data/misc/bluetooth/logs/btsnoop_hci.log',
                     '/sdcard/btsnoop_hci.log',
                     '/storage/emulated/0/btsnoop_hci.log')) {
        $exists = Adb shell "su -c 'ls -l $p'" 2>$null
        if (-not $exists -or $exists -match 'No such file|Permission denied') {
            $exists = Adb shell "ls -l $p" 2>$null
        }
        if ($exists -and $exists -notmatch 'No such file|Permission denied') {
            $dst = Join-Path $Out 'btsnoop_hci.log'
            Adb pull $p $dst 2>$null | Out-Null
            if ((Test-Path $dst) -and (Get-Item $dst).Length -gt 0) { $log = $dst; break }
        }
    }
}

if (-not $log) {
    Write-Host 'direct pull unavailable (not rooted) - falling back to bugreport'
    $zip = Join-Path $Out 'bugreport.zip'
    Adb bugreport $zip | Out-Null
    $ex = Join-Path $Out 'bugreport'
    if (Test-Path $ex) { Remove-Item $ex -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $ex -Force
    $found = Get-ChildItem $ex -Recurse -Filter 'btsnoop_hci.log' |
             Sort-Object Length -Descending | Select-Object -First 1
    if (-not $found) { throw 'bugreport contains no btsnoop_hci.log (snoop log was off)' }
    $log = Join-Path $Out 'btsnoop_hci.log'
    Copy-Item $found.FullName $log -Force
}

Write-Host "log: $log  ($([math]::Round((Get-Item $log).Length/1MB,2)) MB)"

$py = 'python'
Write-Host "`n=== ATT summary ==="
& $py "$PSScriptRoot\btsnoop.py" $log summary
Write-Host "`n=== SDP: does it announce the Apple AAP service? ==="
& $py "$PSScriptRoot\btsnoop.py" $log sdp
Write-Host "`nFull ATT stream saved to: $Out\att.txt"
& $py "$PSScriptRoot\btsnoop.py" $log att | Out-File -Encoding utf8 "$Out\att.txt"
