<#
Builds the one-click release (for Melty) into scratch\melty\er-apex and zips it to
scratch\melty\er-apex.zip. It holds no game files: the player's first start makes them
(setup.ps1, run by er-apex-setup.exe).

What goes in: er_apex.dll, me3 (me3\, the loader) and its profile er-apex.me3, the first-start setup
(er-apex-setup.exe, setup.ps1, er_apex.template.ini), the repository's tools\ and export-assets.ps1,
and what they would need built or installed: Python 3.11 with numpy, pillow and matplotlib
(tools\python), erextract and ertool (self-contained .NET 8) built, texconv. What the setup fetches
on the player's PC instead: the pinned tools/erdata sources (SoulsFormatsNEXT, HKLib, Paramdex,
UXM), RSX's source and its audio decoders (built there with Visual Studio), RSX 2.3.0.

  pwsh release/package.ps1            (needs what build.ps1 and export-assets.ps1 need, and the network)
#>
$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot
$Out = "$Root\scratch\melty\er-apex"
Set-Location $Root

if (Test-Path $Out) { Remove-Item $Out -Recurse -Force }
New-Item -ItemType Directory -Force $Out | Out-Null

# the DLL and the setup launcher
& "$Root\build.ps1"
if ($LASTEXITCODE) { throw 'build.ps1 failed' }
Copy-Item "$Root\target\x86_64-pc-windows-msvc\release\er_apex.dll" $Out
cargo build --release --manifest-path "$Root\release\launcher\Cargo.toml"
if ($LASTEXITCODE) { throw 'launcher build failed' }
Copy-Item "$Root\release\launcher\target\x86_64-pc-windows-msvc\release\er-apex-setup.exe" $Out
foreach ($f in 'setup.ps1', 'er_apex.template.ini', 'er-apex.me3', 'THIRD_PARTY.md') { Copy-Item "$Root\release\$f" $Out }
# me3 (MIT / Apache-2.0), the loader: its programs and licenses
New-Item -ItemType Directory -Force "$Out\me3" | Out-Null
Copy-Item "$Root\tools\bin\me3\bin" "$Out\me3\bin" -Recurse
foreach ($f in 'LICENSE-MIT', 'LICENSE-APACHE') { Copy-Item "$Root\tools\bin\me3\$f" "$Out\me3" }

# the repository's tools and scripts, as git has them
foreach ($f in git ls-files tools export-assets.ps1 LICENSE README.md README.zh-CN.md) {
    $to = Join-Path $Out $f
    New-Item -ItemType Directory -Force (Split-Path $to) | Out-Null
    Copy-Item (Join-Path $Root $f) $to
}

# erextract (ours) and ertool (ours, with SoulsFormatsNEXT and HKLib: GPL-3.0, their sources come
# with the setup's fetch), built; the .NET runtime inside ertool's folder
$erextract = "$Root\tools\erdata\erextract\target\x86_64-pc-windows-msvc\release\erextract.exe"
cargo build --release --manifest-path "$Root\tools\erdata\erextract\Cargo.toml"
if ($LASTEXITCODE) { throw 'erextract build failed' }
$to = "$Out\tools\erdata\erextract\target\x86_64-pc-windows-msvc\release"
New-Item -ItemType Directory -Force $to | Out-Null
Copy-Item $erextract $to
Push-Location "$Root\tools\erdata"
try {
    # (the runtime packs from nuget.org, the rest from the isolated feed tools/erdata builds with)
    dotnet publish ertool/ertool.csproj -c Release -r win-x64 --self-contained true -o "$Out\tools\erdata\ertool\bin\Release\net8.0" '-p:RestoreAdditionalProjectSources=https://api.nuget.org/v3/index.json'
    if ($LASTEXITCODE) { throw 'ertool publish failed' }
} finally { Pop-Location }

# texconv (DirectXTex, MIT)
New-Item -ItemType Directory -Force "$Out\tools\bin\texconv" | Out-Null
Copy-Item "$Root\tools\bin\texconv\texconv.exe" "$Out\tools\bin\texconv"

# Python 3.11.9 (the NuGet package: a whole CPython, pip included) and the three libraries
$py = "$Out\tools\python"
$nupkg = "$Root\scratch\melty\python.3.11.9.nupkg"
if (-not (Test-Path $nupkg)) {
    Invoke-WebRequest 'https://www.nuget.org/api/v2/package/python/3.11.9' -OutFile $nupkg
}
$tmp = "$Root\scratch\melty\python-nupkg"
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
Expand-Archive $nupkg $tmp
Move-Item "$tmp\tools" $py
Remove-Item $tmp -Recurse -Force
& "$py\python.exe" -m pip install --no-warn-script-location --disable-pip-version-check numpy==2.4.6 pillow==12.3.0 matplotlib==3.11.2
if ($LASTEXITCODE) { throw 'pip install failed' }
Get-ChildItem $py -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force

$zip = "$Root\scratch\melty\er-apex.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive "$Out\*" $zip
$size = (Get-ChildItem $Out -Recurse -File | Measure-Object Length -Sum).Sum
"release in $Out ($([math]::Round($size / 1MB)) MB), zipped to $zip ($([math]::Round((Get-Item $zip).Length / 1MB)) MB)"
