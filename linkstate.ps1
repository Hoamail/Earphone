# linkstate.ps1 - the only trustworthy answer to "is it actually connected?"
#
# Windows Settings happily says "Connected" for a paired A2DP device even when
# there is no ACL link (stale presence cache). This asks the Bluetooth stack
# directly, via WinRT BluetoothDevice.ConnectionStatus.
#
#   .\linkstate.ps1
#   .\linkstate.ps1 -Mac 41:42:23:76:ED:B8

param([string]$Mac = '41:42:23:76:ED:B8')

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime

$null = [Windows.Devices.Bluetooth.BluetoothDevice, Windows.Devices.Bluetooth, ContentType = WindowsRuntime]
$null = [Windows.Devices.Bluetooth.BluetoothLEDevice, Windows.Devices.Bluetooth, ContentType = WindowsRuntime]

$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and
        $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

function Await($op, [Type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    if (-not $task.Wait(8000)) { throw 'WinRT call timed out' }
    $task.Result
}

$addr = [uint64]0
foreach ($p in $Mac.Split(':')) { $addr = ($addr -shl 8) -bor [Convert]::ToByte($p, 16) }

$dev = Await ([Windows.Devices.Bluetooth.BluetoothDevice]::FromBluetoothAddressAsync($addr)) `
             ([Windows.Devices.Bluetooth.BluetoothDevice])

if ($null -eq $dev) {
    Write-Host "no BluetoothDevice object for $Mac (never paired / radio off)"
    exit 1
}

Write-Host ("name       : {0}" -f $dev.Name)
Write-Host ("address    : {0}" -f $dev.BluetoothAddress.ToString('X12'))
Write-Host ("class      : {0}" -f $dev.BluetoothClass)
Write-Host ("CONNECTION : {0}" -f $dev.ConnectionStatus)   # Connected | Disconnected
Write-Host ("remembered : {0}" -f $dev.DeviceInformation.Pairing.IsPaired)

if ($dev.ConnectionStatus -eq 'Connected') {
    Write-Host 'ACL link is up - aap.py should be able to open PSM 0x1001'
} else {
    Write-Host 'no ACL link: Windows may still display "Connected" in Settings; it is lying'
}
