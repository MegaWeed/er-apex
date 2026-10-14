# Third-party software in this release

No Apex Legends or ELDEN RING files are in this release. The first start makes them on your PC
from your own installs (`setup.ps1`); your game folders are only read.

er-apex is MIT (`LICENSE`), by umi ([umiiii/er-apex](https://github.com/umiiii/er-apex)), with this
fork's additions by MegaWeed ([MegaWeed/er-apex](https://github.com/MegaWeed/er-apex)); its
architecture comes from [er-mario](https://github.com/deltarooo/er-mario) (MIT).

## Shipped built

| What | Where | License |
|---|---|---|
| Python 3.11.9 (NuGet `python` package) | `tools\python` | PSF License 2.0 |
| numpy 2.4.6 | `tools\python\Lib\site-packages` | BSD-3-Clause |
| Pillow 12.3.0 | same | MIT-CMU (HPND) |
| matplotlib 3.11.2 and its dependencies | same | matplotlib License (PSF-based) and theirs |
| .NET 8 runtime (inside ertool's folder) | `tools\erdata\ertool\bin\Release\net8.0` | MIT |
| ertool (this repository, `tools/erdata/ertool`) with [SoulsFormatsNEXT](https://github.com/soulsmods/SoulsFormatsNEXT) and [HKLib](https://github.com/The12thAvenger/HKLib) | same | ertool: MIT; SoulsFormatsNEXT: GPL-3.0; HKLib: MIT. Their sources, at the commits in `tools/erdata/dependencies.lock.json`, are fetched into `tools\third_party` by the setup and are at those links |
| erextract (this repository, `tools/erdata/erextract`) | `tools\erdata\erextract\target\...` | MIT |
| texconv ([DirectXTex](https://github.com/microsoft/DirectXTex)) | `tools\bin\texconv` | MIT |
| [me3](https://me3.help) 0.13.0 ([garyttierney/me3](https://github.com/garyttierney/me3)), the loader | `me3` | MIT or Apache-2.0 (`me3\LICENSE-MIT`, `me3\LICENSE-APACHE`) |

## Fetched on your PC by the setup

| What | From | License |
|---|---|---|
| RSX 2.3.0 release, and RSX's source built with your Visual Studio | [r-ex/rsx](https://github.com/r-ex/rsx) | AGPL-3.0 |
| BinkA and RadAudio decoders (built into your RSX) | Epic Games' Unreal Engine dependency CDN | Epic's terms |
| SoulsFormatsNEXT, HKLib, Paramdex, UXM-Selective-Unpack | their GitHub repositories (pinned commits) | theirs |

Apex Legends is © Electronic Arts / Respawn Entertainment; ELDEN RING is © FromSoftware / Bandai
Namco. This is a fan project made with neither.
