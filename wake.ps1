# wake.ps1 - force Windows to page a paired classic-Bluetooth accessory.
#
# WSAE10049 from aap.py only means there is no ACL link. This asks the
# Bluetooth stack to enable a service on the device (A2DP sink), which makes
# Windows page it. If the buds are on and out of the case, the link comes up.
#
#   .\wake.ps1 -Mac 41:42:23:76:ED:B8
#   .\wake.ps1 -Mac 41:42:23:76:ED:B8 -Disconnect

param(
    [Parameter(Mandatory)][string]$Mac,
    [switch]$Disconnect
)

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Threading;

public static class Bth
{
    [StructLayout(LayoutKind.Sequential)]
    public struct BLUETOOTH_ADDRESS { public ulong ullLong; }

    [StructLayout(LayoutKind.Sequential)]
    public struct SYSTEMTIME
    {
        public ushort wYear, wMonth, wDayOfWeek, wDay, wHour, wMinute, wSecond, wMilliseconds;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct BLUETOOTH_DEVICE_INFO
    {
        public int dwSize;
        public BLUETOOTH_ADDRESS Address;
        public uint ulClassofDevice;
        public int fConnected;
        public int fRemembered;
        public int fAuthenticated;
        public SYSTEMTIME stLastSeen;
        public SYSTEMTIME stLastUsed;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 248)] public string szName;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct FIND_RADIO_PARAMS { public int dwSize; }

    [DllImport("bthprops.cpl", SetLastError = true)]
    public static extern IntPtr BluetoothFindFirstRadio(ref FIND_RADIO_PARAMS p, out IntPtr phRadio);

    [DllImport("bthprops.cpl", SetLastError = true)]
    public static extern uint BluetoothGetDeviceInfo(IntPtr hRadio, ref BLUETOOTH_DEVICE_INFO info);

    [DllImport("bthprops.cpl", SetLastError = true)]
    public static extern uint BluetoothSetServiceState(IntPtr hRadio,
        ref BLUETOOTH_DEVICE_INFO info, ref Guid service, uint flags);

    static ulong ParseMac(string mac)
    {
        ulong a = 0;
        foreach (var part in mac.Replace('-', ':').Split(':'))
            a = (a << 8) | Convert.ToByte(part, 16);
        return a;
    }

    static BLUETOOTH_DEVICE_INFO Device(string mac)
    {
        var d = new BLUETOOTH_DEVICE_INFO();
        d.dwSize = Marshal.SizeOf(typeof(BLUETOOTH_DEVICE_INFO));
        d.Address = new BLUETOOTH_ADDRESS { ullLong = ParseMac(mac) };
        d.szName = "";
        return d;
    }

    public static string Wake(string mac, bool enable)
    {
        var p = new FIND_RADIO_PARAMS { dwSize = 4 };
        IntPtr radio;
        if (BluetoothFindFirstRadio(ref p, out radio) == IntPtr.Zero)
            return "no Bluetooth radio found (radio off?)";

        var d = Device(mac);
        uint rc = BluetoothGetDeviceInfo(radio, ref d);
        int err = Marshal.GetLastWin32Error();
        string head = string.Format(
            "struct={0}B getInfo=0x{1:X} err={2} connected={3} remembered={4} name='{5}' lastSeen={6:D2}:{7:D2}",
            Marshal.SizeOf(typeof(BLUETOOTH_DEVICE_INFO)), rc, err,
            d.fConnected, d.fRemembered, (d.szName ?? "").Trim(),
            d.stLastSeen.wHour, d.stLastSeen.wMinute);

        var svc = new Guid("0000110B-0000-1000-8000-00805F9B34FB"); // A2DP sink
        uint flags = enable ? 1u : 0u;
        uint rc2 = BluetoothSetServiceState(radio, ref d, ref svc, flags);
        int err2 = Marshal.GetLastWin32Error();

        Thread.Sleep(3000);

        var d2 = Device(mac);
        BluetoothGetDeviceInfo(radio, ref d2);

        return head + string.Format(
            "\nsetServiceState({0}) rc=0x{1:X8} err={2}\nafter: connected={3} lastSeen={4:D2}:{5:D2}",
            enable ? "enable" : "disable", rc2, err2, d2.fConnected,
            d2.stLastSeen.wHour, d2.stLastSeen.wMinute);
    }
}
'@

$result = [Bth]::Wake($Mac, -not $Disconnect)
Write-Host $result

if ($result -match 'after: connected=True|after: connected=1') {
    Write-Host 'LINK IS UP - run: python aap.py --name "Pro NewGen" probe'
} else {
    Write-Host 'no ACL link yet: buds off / in the case / held by the phone / out of range'
}
