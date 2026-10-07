<#
Gives the foreground back once a newly started game window takes it (D-010: test runs must not
take the user's focus). Started detached by game.ps1 start; ends after the first hand-back or after
-Timeout seconds, so a later click into the game is left alone.

  pwsh tools/dev/focus-back.ps1 -Prev <hwnd> [-Process eldenring] [-Timeout 120]
#>
param(
    [Parameter(Mandatory)][long]$Prev,
    [string]$Process = 'eldenring',
    [int]$Timeout = 120
)
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class FgBack {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
}
'@
$prev = [IntPtr]$Prev
$t0 = Get-Date
while (((Get-Date) - $t0).TotalSeconds -lt $Timeout) {
    Start-Sleep -Milliseconds 300
    if (-not [FgBack]::IsWindow($prev)) { return }
    $fg = [FgBack]::GetForegroundWindow()
    $procId = 0
    $thread = [FgBack]::GetWindowThreadProcessId($fg, [ref]$procId)
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -eq $Process) {
        $me = [FgBack]::GetCurrentThreadId()
        [void][FgBack]::AttachThreadInput($me, $thread, $true)
        [void][FgBack]::SetForegroundWindow($prev)
        [void][FgBack]::AttachThreadInput($me, $thread, $false)
        return
    }
}
