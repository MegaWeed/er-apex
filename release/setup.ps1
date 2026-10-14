<#
er-apex's first-launch setup in a release (release/package.ps1; Melty runs er-apex-setup.exe, which
runs this, before the game's first start). Makes Octane's models, animations, sounds and HUD from
the player's own Apex Legends and ELDEN RING installs (export-assets.ps1 -Bundled: about 70
minutes and about 45 GB the first time), puts them where the mod and me3 read them, writes
er_apex.ini, and last `assets-ready.txt` (Melty starts the game once that is there).

Windows PowerShell 5.1 (every Windows has it). Needs Visual Studio 2022's C++ tools: RSX, the Apex
asset reader, is built from its source here (it holds Epic's audio decoders, which may not be
handed out built). Run again after a failure: what is done is kept.

The game folders: game_dirs.ini beside this file (Melty writes it: elden_ring = <folder>,
apex_legends = <folder>), else found through Steam.
#>
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
Set-Location $Root
New-Item -ItemType Directory -Force "$Root\logs" | Out-Null
Start-Transcript -Path "$Root\logs\setup.log" -Append | Out-Null
$Host.UI.RawUI.WindowTitle = 'er-apex: first-time setup'
Write-Host 'er-apex: making Octane from your own Apex Legends and ELDEN RING (first time only, about 70 minutes)' -ForegroundColor Cyan

function Read-Dirs {
    $dirs = @{}
    $file = "$Root\game_dirs.ini"
    if (Test-Path $file) {
        foreach ($line in Get-Content $file) {
            if ($line -match '^\s*([A-Za-z_]+)\s*=\s*(.+?)\s*$') { $dirs[$Matches[1].ToLower()] = $Matches[2].Trim('"') }
        }
    }
    $dirs
}

function Stop-Setup([string]$why, [string]$url) {
    Write-Host "`n$why" -ForegroundColor Red
    Add-Type -AssemblyName PresentationFramework
    $more = if ($url) { "`n`nOpen the download page now?" } else { '' }
    $answer = [System.Windows.MessageBox]::Show("$why$more", 'er-apex setup', $(if ($url) { 'YesNo' } else { 'OK' }), 'Warning')
    if ($url -and $answer -eq 'Yes') { Start-Process $url }
    Stop-Transcript | Out-Null
    exit 1
}

# Visual Studio 2022's C++ tools (MSBuild and MSVC) build RSX
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = if (Test-Path $vswhere) { & $vswhere -latest -products * -requires Microsoft.Component.MSBuild Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath }
if (-not $vs) {
    Stop-Setup ("er-apex needs Visual Studio 2022 with its C++ tools to read Apex Legends' files (once, during this setup).`n`n" +
        "Install 'Build Tools for Visual Studio 2022' (free) and tick 'Desktop development with C++', then press Play again.") 'https://visualstudio.microsoft.com/visual-cpp-build-tools/'
}

# (a folder that is not one, even with odd characters, is just not used: Steam's are then)
function Test-In([string]$dir, [string]$mark) { try { $dir -and (Test-Path -LiteralPath (Join-Path $dir $mark)) } catch { $false } }
$dirs = Read-Dirs
$er = $dirs['elden_ring']
if (Test-In $er 'Game\eldenring.exe') { $er = Join-Path $er 'Game' }
$apex = $dirs['apex_legends']
$exportArgs = @{ Bundled = $true; NoArena = $true }
if (Test-In $er 'eldenring.exe') { $exportArgs.EldenRingDir = $er }
if (Test-In $apex 'paks\Win64') { $exportArgs.ApexDir = $apex }
elseif (-not $env:APEX_LEGENDS_DIR) {
    $steam = (Get-ItemProperty 'HKCU:\Software\Valve\Steam' -ErrorAction SilentlyContinue).SteamPath
    $found = $false
    if ($steam) {
        $libs = @($steam)
        $vdf = Join-Path $steam 'steamapps\libraryfolders.vdf'
        if (Test-Path $vdf) { $libs += [regex]::Matches((Get-Content $vdf -Raw), '"path"\s+"([^"]+)"') | ForEach-Object { $_.Groups[1].Value -replace '\\\\', '\' } }
        foreach ($lib in $libs) { if (Test-Path (Join-Path $lib 'steamapps\common\Apex Legends\paks\Win64')) { $found = $true } }
    }
    if (-not $found) { Stop-Setup 'er-apex needs Apex Legends installed (its files are read, never changed). Install it, then press Play again.' $null }
}

try {
    & "$Root\export-assets.ps1" @exportArgs
} catch {
    Stop-Setup "Making the assets failed: $($_.Exception.Message)`n`nThe whole log is in $Root\logs\setup.log. Press Play to try again (finished steps are kept)." $null
}

# ---- into the mod folder: me3's package (the armour models), the mod's own files ----
$pkg = "$Root\package"
New-Item -ItemType Directory -Force "$pkg\parts", "$pkg\material" | Out-Null
$body = @("$Root\er-data\s3\octane_gun\package", "$Root\er-data\s3\octane\package") |
    Where-Object { @(Get-ChildItem "$_\parts" -Filter '*_m_0999*' -ErrorAction SilentlyContinue).Count -eq 8 } | Select-Object -First 1
$pov = "$Root\er-data\s3\octane_pov_wingman\package"
if (-not $body -or @(Get-ChildItem "$pov\parts" -Filter '*_m_0998*' -ErrorAction SilentlyContinue).Count -ne 8) {
    Stop-Setup "The models were not all made (see $Root\logs\setup.log). Press Play to try again." $null
}
Get-ChildItem "$body\parts" -Filter '*_m_0999*' | Copy-Item -Destination "$pkg\parts" -Force
Get-ChildItem "$pov\parts" -Filter '*_m_0998*' | Copy-Item -Destination "$pkg\parts" -Force
Copy-Item "$pov\material\allmaterial.matbinbnd.dcx" "$pkg\material\allmaterial.matbinbnd.dcx" -Force
Copy-Item "$Root\apex-data\pov\octane_wingman\fuse_pov.anim" "$Root\fuse_pov.anim" -Force
Copy-Item "$Root\er-data\s4\fuse_er.anim" "$Root\fuse_er.anim" -Force
Copy-Item "$Root\apex-data\pov\octane_padworld\padworld.json" "$Root\padworld.json" -Force

# er_apex.ini: the template (release/er_apex.ini) and where the assets are
$ini = Get-Content "$Root\er_apex.template.ini" -Raw
$ini += "`naudio_dir = $Root\apex-data\audio`nhud_dir = $Root\apex-data\hud\octane`nnpc_names = $Root\er-data\json\NpcName_zhocn.json" +
    "`nnpc_param_names = $Root\tools\third_party\Paramdex\ER\Names\NpcParam.txt`nmonster_names = $Root\tools\apexhud\monster_names_zhocn.json`n"
$user = "$Root\er_apex.user.ini"
if (Test-Path $user) { $ini += "`n# er_apex.user.ini`n" + (Get-Content $user -Raw) }
Set-Content "$Root\er_apex.ini" $ini -Encoding UTF8

Set-Content "$Root\assets-ready.txt" "made $(Get-Date -Format s)"
Write-Host "`ner-apex is ready. The game starts now." -ForegroundColor Green
Stop-Transcript | Out-Null
exit 0
