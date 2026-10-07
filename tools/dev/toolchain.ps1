# Tool chain checks for build.ps1 and export-assets.ps1 (dot-source it; $Root must be set).
# configure-style: "checking for <what>... <version>", or "no"; the misses collect in $missing.

$missing = @()

function Check([string]$what, [scriptblock]$probe, [string]$fix) {
    # Windows PowerShell turns a native command's redirected stderr into errors: keep them from stopping the script
    $ErrorActionPreference = 'Continue'
    Write-Host "checking for $what... " -NoNewline
    $found = try { & $probe } catch { $null }
    if ($found) {
        Write-Host $found -ForegroundColor Green
    } else {
        Write-Host 'no' -ForegroundColor Red
        $script:missing += "${what}: $fix"
    }
}

function Py([string]$code) {
    $out = & python -c $code 2>$null
    if ($LASTEXITCODE -eq 0) { "$out".Trim() }
}

function Have([string]$file) { if (Test-Path "$Root\$file") { $file } }

function Assert-Toolchain {
    Write-Host ''
    if ($script:missing) { throw "the tool chain is not complete:`n  " + ($script:missing -join "`n  ") }
}

# Rust and the MSVC linker: the DLL, the crates in deps/ and tools/erdata/erextract
function Test-Rust {
    Check 'cargo' { $v = & cargo --version 2>$null; if ($LASTEXITCODE -eq 0) { ("$v" -split ' ')[1] } } 'install Rust from https://rustup.rs'
    Check 'rust target x86_64-pc-windows-msvc' {
        # .cargo/config.toml builds for this target; rust-toolchain.toml picks the stable channel
        $vv = & rustc -vV 2>$null
        if ($LASTEXITCODE -ne 0) { return }
        $installed = & rustup target list --installed 2>$null
        if (($installed -contains 'x86_64-pc-windows-msvc') -or ($vv -match '^host: x86_64-pc-windows-msvc$')) { 'rustc ' + ($vv[0] -split ' ')[1] }
    } 'rustup target add x86_64-pc-windows-msvc (or rustup default stable-x86_64-pc-windows-msvc)'
    Check 'MSVC linker (Visual Studio C++ tools)' { Get-VisualStudio 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64' } 'install Visual Studio 2022 with "Desktop development with C++"'
}

function Get-VisualStudio([string[]]$components) {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $v = & $vswhere -latest -products * -requires @components -property catalog_productDisplayVersion
        if ($v) { "Visual Studio $v" }
    }
}
