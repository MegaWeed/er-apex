"""Exports the Apex data the naming/parameter reference needs, with RSX's command-line build.

RSX 2.3.0 CLI quirk: CLI_HandleAssetTypeWhitelist is inverted (without --loadwhitelist every
asset type is marked "don't load", so -export silently writes nothing). Passing --loadwhitelist
with any value makes every type loadable; --exportthreads is passed explicitly as well.

Usage: python tools/apexdata/rsx_export.py  (outputs to <repo>\\apex-data\\export)
"""
import subprocess
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gamedirs  # noqa: E402  (tools/gamedirs.py: the games' install folders)

ROOT = Path(__file__).resolve().parents[2]
RSX = ROOT / "tools/rsx-2.3.0/rsx_nogui.exe"
PAKS = gamedirs.apex() / "paks/Win64"
OUT = ROOT / "apex-data/export"
COMMON = ["-nogui", "-export", "--loadwhitelist", "x", "--exportthreads", "8", "--parsethreads", "8",
          "--exportdir", str(OUT)]


def run(types: str, paks: list[Path], full_paths: bool = False, list_csv: Path | None = None):
    args = [str(RSX), *COMMON, "--exporttypes", types]
    if full_paths:
        args.append("-exportfullpaths")
    if list_csv:
        args += ["--list", str(list_csv), "--listformat", "csv"]
    # RSX keeps its cache (rsx_cache_db.bin) in the working folder
    subprocess.run(args + [str(p) for p in paks], check=True, cwd=OUT)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # RSX writes the --list CSV only into an existing folder
    (OUT.parent / "lists").mkdir(exist_ok=True)
    # localization: one locl asset per language (patch paks are applied by RSX itself)
    locl = sorted(p for p in PAKS.glob("localization_*.rpak") if "(" not in p.name and "dedi" not in p.name)
    run("locl", locl)
    # settings (characters, abilities, skins, player movement), weapon definitions, datatables
    core = [PAKS / n for n in ["common.rpak", "common_mp.rpak", "common_early.rpak", "ui.rpak", "startup.rpak"]]
    run("stgs,wepn,dtbl,stlt,rson", core, full_paths=True, list_csv=OUT.parent / "lists" / "data_named.csv")


if __name__ == "__main__":
    main()
