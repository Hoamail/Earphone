# ble_gatt.ps1 - dump the BLE GATT tree of the accessory through WinRT.
#
# bleak failed to connect ("device not found") because the accessory is
# dual-mode and already bonded on classic BR/EDR; WinRT's BluetoothLEDevice
# resolves it from the pairing database instead of from advertising.
#
#   .\ble_gatt.ps1
#   .\ble_gatt.ps1 -Mac 41:42:23:76:ED:B8 -Read

param(
    [string]$Mac = '41:42:23:76:ED:B8',
    [switch]$Read
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime

$null = [Windows.Devices.Bluetooth.BluetoothLEDevice, Windows.Devices.Bluetooth, ContentType = WindowsRuntime]
$null = [Windows.Devices.Bluetooth.GenericAttributeProfile.GattDeviceServicesResult, Windows.Devices.Bluetooth, ContentType = WindowsRuntime]
$null = [Windows.Devices.Bluetooth.GenericAttributeProfile.GattCharacteristicsResult, Windows.Devices.Bluetooth, ContentType = WindowsRuntime]
$null = [Windows.Devices.Bluetooth.GenericAttributeProfile.GattReadResult, Windows.Devices.Bluetooth, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime]

$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and
        $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

function Await($op, [Type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    if (-not $task.Wait(20000)) { throw "WinRT timeout for $($type.Name)" }
    $task.Result
}

function To-Hex($buffer) {
    if ($null -eq $buffer) { return '' }
    $len = [int]$buffer.Length
    if ($len -eq 0) { return '' }
    $reader = [Windows.Storage.Streams.DataReader]::FromBuffer($buffer)
    $bytes = New-Object byte[] $len
    $reader.ReadBytes($bytes)
    ($bytes | ForEach-Object { $_.ToString('X2') }) -join ' '
}

$addr = [uint64]0
foreach ($p in $Mac.Split(':')) { $addr = ($addr -shl 8) -bor [Convert]::ToByte($p, 16) }

$dev = Await ([Windows.Devices.Bluetooth.BluetoothLEDevice]::FromBluetoothAddressAsync($addr)) `
             ([Windows.Devices.Bluetooth.BluetoothLEDevice])
if ($null -eq $dev) { Write-Host 'BluetoothLEDevice is null: OS has no LE record for this address'; exit 1 }

Write-Host ("name={0} connection={1}" -f $dev.Name, $dev.ConnectionStatus)

$svcRes = Await ($dev.GetGattServicesAsync()) `
                ([Windows.Devices.Bluetooth.GenericAttributeProfile.GattDeviceServicesResult])
Write-Host ("services status={0} count={1}" -f $svcRes.Status, $svcRes.Services.Count)

foreach ($svc in $svcRes.Services) {
    Write-Host ("[svc] {0}" -f $svc.Uuid)
    $chRes = Await ($svc.GetCharacteristicsAsync()) `
                   ([Windows.Devices.Bluetooth.GenericAttributeProfile.GattCharacteristicsResult])
    foreach ($ch in $chRes.Characteristics) {
        $props = $ch.CharacteristicProperties
        $line = "   [chr] {0}  {1}" -f $ch.Uuid, $props
        if ($Read -and ($props -band 0x02)) {
            try {
                $r = Await ($ch.ReadValueAsync()) `
                          ([Windows.Devices.Bluetooth.GenericAttributeProfile.GattReadResult])
                $line += "  = " + (To-Hex $r.Value)
            } catch {
                $line += "  (read failed: $($_.Exception.Message))"
            }
        }
        Write-Host $line
    }
}
