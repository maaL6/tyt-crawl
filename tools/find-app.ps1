# Tim app tren dien thoai qua adb va (tuy chon) pull APK ve may.
#
#   powershell -File tools\find-app.ps1              # liet ke app ben thu 3
#   powershell -File tools\find-app.ps1 truyen       # loc theo tu khoa
#   powershell -File tools\find-app.ps1 -Pull com.truyen.tyt   # pull APK ve .\apk\

param(
    [string]$Filter = "",
    [string]$Pull = ""
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Get-Adb {
    $c = Get-Command adb -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $p = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter adb.exe -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($p) { return $p.FullName }
    throw "Khong tim thay adb. Cai bang: winget install Google.PlatformTools"
}

function Get-AdbPaths {
    param([string]$Package)
    & $script:adb shell pm path $Package |
        ForEach-Object { $_ -replace '^package:', '' } |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ }
}

$adb = Get-Adb
$script:adb = $adb
Write-Host "adb: $adb" -ForegroundColor DarkGray

& $adb start-server | Out-Null
$state = (& $adb get-state 2>&1) -join ""
if ($state -ne "device") {
    Write-Host "Chua thay thiet bi (state='$state')." -ForegroundColor Yellow
    Write-Host " - Bat: Cai dat > Gioi thieu dien thoai > So ban dung > USB debugging" -ForegroundColor Yellow
    Write-Host " - Cam cap USB, tren dien thoai bam 'Cho phep go loi USB'" -ForegroundColor Yellow
    exit 1
}
Write-Host "Thiet bi: OK" -ForegroundColor Green

if ($Pull) {
    $dest = Join-Path $Root "apk\$Pull"
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    $paths = Get-AdbPaths -Package $Pull
    if (-not $paths) { throw "Khong tim thay package '$Pull' tren may." }
    foreach ($p in $paths) {
        $name = Split-Path $p -Leaf
        Write-Host "pull $name ..." -ForegroundColor Cyan
        & $adb pull $p (Join-Path $dest $name) | Out-Null
    }
    Write-Host ""
    Write-Host "Xong -> $dest" -ForegroundColor Green
    Get-ChildItem $dest | ForEach-Object { "{0,-40} {1:N0} KB" -f $_.Name, ($_.Length / 1KB) }
    Write-Host ""
    Write-Host "Tiep theo:" -ForegroundColor DarkGray
    Write-Host "  tools\jadx\bin\jadx.bat -d apk\decompiled `"$dest`"" -ForegroundColor DarkGray
    exit 0
}

$label = ""
if ($Filter) { $label = " (loc: '$Filter')" }
Write-Host ""
Write-Host "App ben thu ba$label" -ForegroundColor Cyan

$pkgs = & $adb shell pm list packages -3 |
    ForEach-Object { $_ -replace '^package:', '' } |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ } |
    Sort-Object
if ($Filter) {
    $pkgs = $pkgs | Select-String -Pattern $Filter -CaseSensitive:$false | ForEach-Object { $_.Line.Trim() }
}
foreach ($pkg in $pkgs) {
    $n = (Get-AdbPaths -Package $pkg).Count
    "{0,-45} {1} apk" -f $pkg, $n
}
Write-Host ""
Write-Host "Pull APK:  powershell -File tools\find-app.ps1 -Pull [package]" -ForegroundColor DarkGray
