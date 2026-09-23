# Install with the setup .exe the way the in-app updater runs it, check that
# everything landed and works — including the scheduled task — then
# uninstall and check nothing is left.
#
#   check_windows.ps1 -Version 1.1.0 -Setup dist\installer\...-setup.exe
#
# Failures are also GitHub ::error:: annotations.
param(
    [Parameter(Mandatory)] [string] $Version,
    [Parameter(Mandatory)] [string] $Setup
)
$ErrorActionPreference = "Continue"
$App = "$env:LOCALAPPDATA\Programs\Random Wallpaper"
$Cli = "$App\random-wallpaper-cli.exe"
$Gui = "$App\random-wallpaper.exe"
$Uninstall = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{6E4B7B0C-2F0B-4E7E-9C57-3F1C2B6F7A11}_is1"
$Shortcut = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Random Wallpaper\Random Wallpaper.lnk"
$script:failures = 0

function Fail($msg) { Write-Output "::error::$msg"; Write-Output "FAIL  $msg"; $script:failures++ }
function Pass($msg) { Write-Output "PASS  $msg" }
function Check($label, [scriptblock] $test) { if (& $test) { Pass $label } else { Fail $label } }

# Wait for the installer process itself, not for everything it starts:
# Start-Process -Wait also waits on children, and [Run] starts the app,
# which never exits by itself — that is what hung this step before.
function Run-Setup($exe, $arguments) {
    $p = Start-Process $exe -ArgumentList $arguments -PassThru
    if (-not $p.WaitForExit(300000)) { Fail "$exe did not finish in 5 minutes"; return -1 }
    return $p.ExitCode
}

Write-Output "== install $Setup"
$code = Run-Setup $Setup @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
if ($code -ne 0) { Fail "setup exited with $code"; exit 1 }

Check "the app is in $App" { Test-Path $Gui }
Check "the console twin is next to it" { Test-Path $Cli }
Check "Qt's Windows platform plugin is bundled" {
    Get-ChildItem "$App\_internal" -Recurse -Filter qwindows.dll -ErrorAction SilentlyContinue | Select-Object -First 1 }
Check "the Start menu entry is there" { Test-Path $Shortcut }
$reg = Get-ItemProperty $Uninstall -ErrorAction SilentlyContinue
if ($reg -and $reg.DisplayVersion -eq $Version) { Pass "Apps & features lists $Version" }
else { Fail "Apps & features entry: '$($reg.DisplayVersion)', wanted $Version" }

$out = (& $Cli --version 2>&1 | Out-String).Trim()
if ($out -eq "random-wallpaper $Version (Windows app)") { Pass "--version: $out" }
else { Fail "--version said: $out (wanted $Version, Windows app)" }
& $Cli --period | Out-Null
if ($LASTEXITCODE -eq 0) { Pass "--period runs" } else { Fail "--period exited with $LASTEXITCODE" }

# [Run] started the window after installing. Still running some seconds
# later means Qt, its plugins and the app all loaded.
$deadline = (Get-Date).AddSeconds(20)
while (-not (Get-Process random-wallpaper -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) { Start-Sleep 1 }
Start-Sleep 8
if (Get-Process random-wallpaper -ErrorAction SilentlyContinue) { Pass "the window starts and stays up" }
else { Fail "the window was not running after install" }
Stop-Process -Name random-wallpaper -Force -ErrorAction SilentlyContinue

Write-Output "== scheduled task"
& $Cli --install-timer | Out-Null
schtasks /Query /TN RandomWallpaperAuto /XML > "$env:TEMP\task.xml" 2>$null
if ($LASTEXITCODE -eq 0) {
    Pass "the scheduled task is registered"
    $xml = Get-Content "$env:TEMP\task.xml" -Raw
    Check "it runs the windowed exe" { $xml -match [regex]::Escape($Gui) }
    Check "every minute" { $xml -match "<Interval>PT1M</Interval>" }
} else { Fail "--install-timer registered no task" }
Stop-Process -Name random-wallpaper -Force -ErrorAction SilentlyContinue
Start-Sleep 2

Write-Output "== uninstall"
# The uninstaller copies itself to %TEMP% and returns at once, so its exit
# proves nothing; wait for the files to go instead.
Run-Setup "$App\unins000.exe" @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") | Out-Null
$deadline = (Get-Date).AddSeconds(120)
while ((Test-Path $Gui) -and (Get-Date) -lt $deadline) { Start-Sleep 2 }
Check "the app is gone" { -not (Test-Path $Gui) }
Check "and its Apps & features entry" { -not (Test-Path $Uninstall) }
Check "and the Start menu entry" { -not (Test-Path $Shortcut) }
schtasks /Query /TN RandomWallpaperAuto 2>$null | Out-Null
Check "and the scheduled task" { $LASTEXITCODE -ne 0 }

Write-Output "== $script:failures failed"
exit [int]($script:failures -ne 0)
