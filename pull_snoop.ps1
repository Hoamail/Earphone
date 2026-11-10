# pull_snoop.ps1 - grab the Android Bluetooth HCI snoop log and decode it.
#
# Why: the vendor app is the only source of truth for what the buds accept.
# Turn on the snoop log, open the app, tap every setting once, then run this.
# The dump gives you the exact GATT/L2CAP writes to replay with gatt.py/aap.py.
#
# Usage:
#   .\pull_snoop.ps1                 # auto: enable props, pull, decode
#   .\pull_snoop.ps1 -NoProp         # phone not rooted / props already set

param(
    [string]$Serial,
    [string]$Out = "$PSScriptRoot\snoop",
    [switch]$NoProp
)

$ErrorActionPreference = 'Stop'
$adb = if ($env:ADB) { $env:ADB } else { 'adb' }
$serialArg = if ($Serial) { @('-s', $Serial) } else { @() }

function Adb { & $adb @serialArg @args }

New-Item -ItemType Directory -Force -Path $Out | Out-Null

Write-Host '== devices =='
$devices = Adb devices
$devices | ForEach-Object { Write-Host $_ }
if (-not ($devices -match '\sdevice$')) {
    throw 'no adb device. enable USB debugging and authorize this PC.'
}

if (-not $NoProp) {
    Write-Host '== enabling btsnoop (needs root or a userdebug build) =='
    Adb shell setprop persist.bluetooth.btsnooplogmode full 2>$null
    Adb shell setprop persist.bluetooth.btsnooppath /data/misc/bluetooth/logs/btsnoop_hci.log 2>$null
    Write-Host 'toggling bluetooth so the log restarts'
    Adb shell svc bluetooth disable 2>$null
    Start-Sleep -Seconds 3
    Adb shell svc bluetooth enable 2>$null
    Start-Sleep -Seconds 5
}

Write-Host ''
Write-Host 'NOW: open the vendor app, connect the buds, change every setting once.'
Read-Host 'Press Enter when done'

$paths = @(
    '/data/misc/bluetooth/logs/btsnoop_hci.log',
    '/storage/emulated/0/btsnoop_hci.log',
    '/sdcard/btsnoop_hci.log'
)

$pulled = $null
foreach ($p in $paths) {
    $exists = Adb shell "ls $p" 2>$null
    if ($exists -and $exists -notmatch 'No such file') {
        $dest = Join-Path $Out 'btsnoop_hci.log'
        Write-Host "pulling $p"
        Adb pull $p $dest 2>$null | Out-Null
        if (Test-Path $dest) { $pulled = $dest; break }
    }
}

if (-not $pulled) {
    Write-Host 'no snoop log found. fallback:'
    Write-Host '  adb bugreport bugreport.zip   (look for FS/data/misc/bluetooth/logs/*)'
    Adb bugreport (Join-Path $Out 'bugreport.zip')
    exit 1
}

Write-Host "log: $pulled"

$tshark = Get-Command tshark -ErrorAction SilentlyContinue
if (-not $tshark) {
    Write-Host 'tshark not on PATH (install Wireshark). Open the log manually:'
    Write-Host "  $pulled"
    exit 0
}

$txt = Join-Path $Out 'frames.txt'
& tshark -r $pulled -Y 'btatt || btl2cap || bta2dp || btrfcomm' -V 2>$null |
    Out-File -Encoding utf8 $txt
Write-Host "decoded: $txt"

& tshark -r $pulled -Y 'btatt' -T fields `
    -e frame.time_relative -e bthci_acl.src.bd_addr -e btatt.opcode `
    -e btatt.handle -e btatt.value 2>$null |
    Out-File -Encoding utf8 (Join-Path $Out 'gatt_ops.tsv')
Write-Host "gatt ops: $(Join-Path $Out 'gatt_ops.tsv')"
Write-Host 'look for Write Command (0x52) / Write Request (0x12) with changing values'
