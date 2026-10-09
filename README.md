# er-apex

English | [中文](README.zh-CN.md)

An offline fan mod for ELDEN RING: play as Octane from Apex Legends. A Rust DLL loaded by [me3](https://me3.help), built on the architecture of [er-mario](https://github.com/deltarooo/er-mario).

**This repository ships no game files and no game assets**: no models, textures, animations, sounds, HUD images or text from Apex Legends or ELDEN RING. You make them yourself from your own game installs with the converters in this repository's `tools/` (see [Building](#building)). You must give the Apex Legends install folder yourself.

## Fastest start

Copy this to any agent:

```markdown
Help me get https://github.com/umiiii/er-apex up and running
```

## Getting started

### Tool chain

**System and disk**

- Windows 10/11 x64, PowerShell 7 (`pwsh`).
- ELDEN RING (the game bindings support 2.7.1.0 / 2.7.1.1) and Apex Legends installed.
- Keep the repository path short (for example `D:\er-apex`): the exported file paths are deep, and they fail when Windows long paths are off.
- About 45 GB of disk for the generated assets.
- The first asset run needs a network connection: it downloads the RSX source and its audio decoders, `tools/erdata`'s pinned dependencies, NuGet packages and Rust crates.

**Software to install**

| Software | Version and use |
|---|---|
| Python | 3.11 or later (tested with 3.13). Only three third-party packages: `pip install numpy pillow matplotlib` |
| Rust | stable, MSVC toolchain (`x86_64-pc-windows-msvc`, see `rust-toolchain.toml`); builds the DLL, the crates in `deps/` and `tools/erdata/erextract` |
| .NET SDK | 8.0.425 or a later patch of 8.0 (pinned by `global.json` in `tools/erdata` and `tools/testarena`); builds `ertool` and a few small C# tools |
| Visual Studio 2022 | with the "Desktop development with C++" workload (MSVC and a Windows 10/11 SDK); `build_rsx.py` builds RSX with MSBuild, and Rust's MSVC linker needs it too |

**Three programs you download into `tools/`** (not in git)

| Program | Put it at | From |
|---|---|---|
| me3 | `tools\bin\me3\bin\me3.exe` | the Windows release from [me3.help](https://me3.help); unzip the whole folder into `tools\bin\me3\` |
| texconv | `tools\bin\texconv\texconv.exe` | `texconv.exe` from a [DirectXTex](https://github.com/microsoft/DirectXTex/releases) release |
| RSX 2.3.0 | `tools\rsx-2.3.0\rsx_nogui.exe` | the 2.3.0 release of [r-ex/rsx](https://github.com/r-ex/rsx/releases), unzipped into `tools\rsx-2.3.0\`. Only `rsx_export.py` uses it; the other exports use the patched RSX that `build_rsx.py` builds from source |

### 1. Build the DLL

```powershell
pwsh build.ps1          # -> target\x86_64-pc-windows-msvc\release\er_apex.dll
pwsh build.ps1 -Test    # also run the tests of the crates in deps/
```

### 2. Make the game assets

```powershell
pwsh export-assets.ps1
```

- It asks for the Apex Legends install folder (with `paks\Win64`) and ELDEN RING's `Game` folder (with `eldenring.exe`). It finds them through Steam when it can and shows them as the default: press Enter to take it. The folders are only read, never written.
- It checks the tool chain, then runs the seven steps of [Making the game assets](#making-the-game-assets-apex-data-er-data) in order: about an hour. Step 4 starts the game once for about a minute to read the player skeleton; leave the game window alone until it quits.
- A command whose outputs are already there is skipped, so after a failure fix the cause and run the script again: it goes on where it stopped. A command that was cut off runs again from the start. To make everything again: `-Force`; only steps 5 to 7: `-From 5 -Force`. No questions: `-ApexDir <folder> -EldenRingDir <folder>`. No test area (no soldiers to shoot): `-NoArena`.

### 3. Play

```powershell
pwsh play.ps1
```

- It backs up the test save to `scratch\saves`, installs the mod into `scratch\mod` and starts the game offline through me3, in a 1920×1080 window. The game skips the title screen and continues the test save's last character at the grace "The First Step" in Limgrave: Octane in first person, R-301 in hand, three soldiers next to the grace as targets.
- The test save `ER0000_fuse.sl2` needs at least one character. me3 copies it from your normal save the first time it starts the game.
- **Click the game window** to play with keyboard and mouse.
- **F5** switches back to the Elden Ring character (the game's own movement and collision, camera, HUD, armour and weapons; the mod's guns and abilities are off). F5 again: Octane.
- By default gun damage is ×3 and the Jump Pad has no cooldown; `-Season3` uses the Season 3 values. `-NoSpawn`: no soldiers.
- More soldiers: `pwsh tools/dev/game.ps1 spawn`. A friendly NPC stands about 10.5 m from the grace; do not shoot it. Back to the grace: `pwsh tools/dev/game.ps1 cmd "warp 1042361951"`. Quit: `pwsh tools/dev/game.ps1 stop`.

## Building

`build.ps1` and `export-assets.ps1` run what this section describes. The commands here are for running a part by hand.

### The DLL

The three crates of this project are in `deps/`: `er-apex-move` (Apex movement controller), `er-apex-audio` (sound mixer) and `er-apex-anim` (the first-person animation pack format; step 7's `export_anim.py` runs it). A clone of this repository alone builds the DLL.

```powershell
cargo build --release
# output: target\x86_64-pc-windows-msvc\release\er_apex.dll

# tests of the three crates
cargo test --release --offline --manifest-path deps/er-apex-move/Cargo.toml
cargo test --release --offline --manifest-path deps/er-apex-anim/Cargo.toml
cargo test --release --offline --manifest-path deps/er-apex-audio/Cargo.toml
```

### Making the game assets (`apex-data/`, `er-data/`)

The converters in `tools/` make every asset the mod uses from your local game installs; none of it goes into git (`apex-data/`, `er-data/` and `scratch/` are in `.gitignore`). The commands below were run in this order in an empty copy, and the result was checked in game. For each tool's details and checks (`verify_*.py`), see the README in its folder under `tools/`.

**Game folders**

The converters read two game folders from environment variables. They only read them, never write.

| Variable | Points to | Required |
|---|---|---|
| `APEX_LEGENDS_DIR` | the Apex Legends install folder (with `paks\Win64`) | **yes**, no default |
| `ELDEN_RING_DIR` | ELDEN RING's `Game` folder (with `eldenring.exe`) | when it is not `E:\SteamLibrary\steamapps\common\ELDEN RING\Game` |

```powershell
$env:APEX_LEGENDS_DIR = 'D:\SteamLibrary\steamapps\common\Apex Legends'   # your install folder
$env:ELDEN_RING_DIR   = 'D:\SteamLibrary\steamapps\common\ELDEN RING\Game'
# To keep them: [Environment]::SetEnvironmentVariable('APEX_LEGENDS_DIR', '<folder>', 'User')
```

Without `APEX_LEGENDS_DIR`, or when the folder has no `paks\Win64`, the converters stop with a message that tells you how to set it.

You do not need R5Reloaded. The HUD, frag grenade and audio exports check which Season 3 script lines name what they export; that evidence (file names, line numbers and the short values on those lines, never the scripts) is recorded in `tools/s3_evidence.json` and comes with the repository. The assets themselves all come from your Apex Legends install. To make the record again, set `R5RELOADED_RECORD` to an R5Reloaded `LIVE` folder and run those three exports (see `tools/s3record.py`).

Run every command at the root of this repository, in this order: each step uses what the steps before it made. The times are measured.

Some steps use outputs with `fuse` in their names. The project first played Fuse and then changed to Octane; the Apex skeleton, the R-301 third-person model, the R-301 first-person animation pack and the first-person base pose were made with Fuse first, and the Octane converters still take them as input. The steps below make only these shared parts, not Fuse's own body, HUD or sounds.

**1. Apex exports (about 31 min)**

```powershell
python tools/apexassets/build_rsx.py                     # build the patched RSX (first time; needs the network)
python tools/apexdata/rsx_export.py                       # character settings, weapon definitions, localization -> apex-data\export
python tools/apexdata/extract_fuse.py                     # weapon parameter table apex-data\fuse_data.json (the audio export reads it)
python tools/apexassets/export_assets.py                  # shared input: Apex skeleton, R-301 third-person model, first-person arms (T001)
python tools/apexassets/export_assets.py --legend octane  # Octane's body, arms, injector, jump pad (T014)
python tools/apexpov/export_pov.py                        # R-301 first-person model and animations, raw RSEQ, QC/SMD -> apex-data\pov
python tools/apexpov/export_defender_pov.py               # Charge Rifle first-person QC/SMD
python tools/apexassets/frag_grenade_assets.py            # frag grenade
python tools/apexassets/battery_assets.py                 # shield battery (T021)
python tools/apexassets/defender_assets.py                # Charge Rifle (T022)
python tools/apexassets/frag_assets.py                    # grenade and thrown grenade (T022)
```

**2. HUD and sounds (about 5 min)**

```powershell
python tools/apexhud/export_hud.py --legend octane      # -> apex-data\hud\octane (T017)
python tools/apexhud/export_extra.py --legend octane    # extra images, frag grenade icon included (U9)
python tools/fuseaudio/export_audio.py                  # R-301 -> apex-data\audio
python tools/fuseaudio/export_audio.py --set octane     # abilities and voice lines (T018)
python tools/fuseaudio/export_audio.py --set defender   # Charge Rifle
python tools/fuseaudio/export_audio.py --set frag       # frag grenade
```

**3. ELDEN RING extraction (about 2 min)**

```powershell
Push-Location tools/erdata
python scripts/setup_dependencies.py                     # fetch the pinned dependency sources and patch them
cargo build --release --manifest-path erextract/Cargo.toml
dotnet build ertool/ertool.csproj -c Release
python scripts/run_s2a.py              # c0000 skeleton, armour templates, text -> er-data\extract, er-data\json (T002)
python scripts/s3a_roundtrip.py        # armour builder round trip, original meshes and material bundle -> er-data\s3 (T003)
python scripts/s3a_material_evidence.py
Pop-Location

# NPC names for the kill feed
$fmg = Get-ChildItem er-data\extract\msg\zhocn\item.msgbnd -Recurse -Filter NpcName.fmg | Select-Object -First 1
& tools\erdata\ertool\bin\Release\net8.0\ertool.exe fmg $fmg.FullName --json --out er-data\json\NpcName_zhocn.json

python tools/testarena/run.py build    # optional: the test area -> er-data\test_arena (T013, see below)
```

`testarena` is for development tests: from your own copy of the map it makes The First Step's map and event files with an enemy generator next to the grace, so `game.ps1 spawn` brings three soldiers as targets. You do not need it to play; skip this line if you like. Without it `game.ps1 install` says the test area is missing and `spawn` does nothing; or give `install` the `-NoArena` switch.

**4. The skeleton from the running game (about 1 min)**

The skeleton mapping and the first-person props need the player skeleton as the running game has it. This step starts the game once and dumps it. Octane's models do not exist yet, so leave `first_person` off.

```powershell
$root = (Get-Location).Path
pwsh tools/dev/game.ps1 build
pwsh tools/dev/game.ps1 install -Set "quickboot = 1;qb_place = first_step"
pwsh tools/dev/game.ps1 start
$log = "$root\scratch\mod\logs\er_apex.log"
while (-not ((Test-Path $log) -and (Select-String -Quiet 'quickboot: done' $log))) { Start-Sleep 1 }
pwsh tools/dev/game.ps1 cmd "skeleton c0000_runtime.json"    # written to scratch\mod\dev\
pwsh tools/dev/game.ps1 stop
New-Item -ItemType Directory -Force er-data\runtime, er-data\skeleton | Out-Null
Copy-Item scratch\mod\dev\c0000_runtime.json er-data\runtime\c0000_runtime.json
Copy-Item scratch\mod\dev\c0000_runtime.json er-data\skeleton\c0000_live_skeleton.json

python tools/retarget/skeleton_map.py    # Apex bone -> ER bone mapping -> er-data\s2b\mapping-v0.json
```

**5. Body model 999 (about 2.5 min)**

```powershell
python tools/octanemesh/convert_octane.py --matbin-bnd er-data\s3\inputs\material\allmaterial.matbinbnd.dcx   # -> er-data\s3\octane (T015)
```

**6. First-person model 998, R-301 in hand and the animation packs (about 17 min)**

Each step builds on the one before it: the material bundle (`allmaterial.matbinbnd.dcx`) and the animation pack (`fuse_pov.anim`) start from the previous step's output, so keep the order.

```powershell
python tools/apexpov/bake_pov.py                    # shared input: R-301 first-person animation pack -> apex-data\pov\fuse_pov.anim (T012)
python tools/fusepov/build_pov.py --legend octane --matbin-bnd er-data\s3\octane\package\material\allmaterial.matbinbnd.dcx   # arms + R-301 (T016)
python tools/apexpov/bake_pov.py --legend octane    # -> apex-data\pov\octane\fuse_pov.anim
python tools/fusegun/build_gun.py --legend octane   # R-301 in 999's right hand (T019)
python tools/apexpov/bake_ability.py                # injector, hand-held jump pad (T020)
python tools/fusepov/build_ability.py
python tools/apexpov/bake_battery.py                # shield battery (T021)
python tools/fusepov/build_battery.py
python tools/apexpov/bake_weapons.py                # Charge Rifle, frag grenade (T022)
python tools/fusepov/build_weapons.py               # also turns the battery blue (battery_tint.py)
python tools/apexpov/bake_padworld.py               # jump pad on the ground (R4)
```

**7. First-person base pose (about 1 min)**

Each frame, first person plays the base pose `fuse_idle_rifle_ADS` first; the view model reaches the bones through this pose hook. Without it, the first-person arms and gun are not where they should be.

```powershell
python tools/fuseanim/export_anim.py                    # Apex third-person animation pack (T006) -> apex-data\anim\fuse.anim
python tools/fusemesh/convert_fuse.py --geometry-only   # skeleton alignment only -> er-data\s3\fuse\align.json (no model)
python tools/retarget/bake_er_anim.py fuse_idle_rifle_ADS   # -> er-data\s4\fuse_er.anim
```

Then start the game with `pwsh play.ps1`. `game.ps1 install -Legend octane` takes the last stage of each chain: 999 from `octane_gun`; 998, the material bundle and the animation pack from `octane_pov_weapons` / `octane_weapons`; plus the base pose `fuse_er.anim` and the ground jump pad `padworld.json`. When a stage is incomplete, it uses the stage before it.

Most of `apex-data` and `er-data` is intermediate data. The game reads about 490 MB of it: models about 147 MB, animation pack about 61 MB, HUD about 45 MB, sounds about 235 MB.

## Credits

- [er-mario](https://github.com/deltarooo/er-mario) by Delta: the architecture of this mod. `tools/erdata/erextract`'s archive, DCX and BND4 readers are adapted from it (MIT).
- [fromsoftware-rs](https://github.com/vswarte/fromsoftware-rs): the ELDEN RING game bindings, at the same pinned commit as er-mario.
- [me3](https://me3.help): the mod loader.
- [hudhook](https://crates.io/crates/hudhook), [ilhook](https://crates.io/crates/ilhook), [pelite](https://crates.io/crates/pelite), [glam](https://crates.io/crates/glam) and the other crates in `Cargo.toml`.
- [RSX](https://github.com/r-ex/rsx) by r-ex: the Apex Legends asset exports (2.3.0 release and a patched build from source).
- [SoulsFormatsNEXT](https://github.com/soulsmods/SoulsFormatsNEXT) (originally by Joseph Anderson, GPL-3.0) and [HKLib](https://github.com/The12thAvenger/HKLib) (MIT): ELDEN RING file formats in `ertool` and `testarena`.
- [Paramdex](https://github.com/soulsmods/Paramdex) and [UXM Selective Unpack](https://github.com/Nordgaren/UXM-Selective-Unpack): param definitions and the archive file name dictionary, used locally only.
- [DirectXTex](https://github.com/microsoft/DirectXTex) (`texconv`): texture conversion.

For the licences and pinned commits of the converter dependencies, see `tools/erdata/THIRD_PARTY_NOTICES.md`, `tools/testarena/THIRD_PARTY_NOTICES.md` and `tools/erdata/dependencies.lock.json`.

Apex Legends belongs to Respawn Entertainment and Electronic Arts; ELDEN RING to FromSoftware and Bandai Namco. This is fan work, not affiliated with any of them. This repository has source code only, and no game files or game assets. The assets you make are for your own use with game copies you own; do not redistribute them.

License: MIT (see `LICENSE`). `tools/erdata/ertool` and `tools/testarena` are GPL-3.0 because they use SoulsFormatsNEXT; they are development tools and are not linked into the mod.
