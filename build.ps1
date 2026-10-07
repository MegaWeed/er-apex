<#
Build the mod's DLL: target\x86_64-pc-windows-msvc\release\er_apex.dll

  pwsh build.ps1          check the tool chain, cargo build --release
  pwsh build.ps1 -Test    also run the tests of the three crates in deps/
#>
param([switch]$Test)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

. "$Root\tools\dev\toolchain.ps1"
Write-Host ''
Test-Rust
Assert-Toolchain

Push-Location $Root
try {
    cargo build --release
    if ($LASTEXITCODE -ne 0) { throw 'cargo build failed' }
    if ($Test) {
        foreach ($crate in 'er-apex-move', 'er-apex-anim', 'er-apex-audio') {
            cargo test --release --manifest-path "deps/$crate/Cargo.toml"
            if ($LASTEXITCODE -ne 0) { throw "tests of $crate failed" }
        }
    }
} finally { Pop-Location }

$dll = Get-Item "$Root\target\x86_64-pc-windows-msvc\release\er_apex.dll"
"built $($dll.FullName) ($([int]($dll.Length / 1KB)) KB)"
