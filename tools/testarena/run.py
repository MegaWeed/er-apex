"""T013: extract vanilla inputs, build in exclusive paths, and run the arena tool."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gamedirs  # noqa: E402  (tools/gamedirs.py: the games' install folders)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATA = REPO / "er-data" / "test_arena"
GAME = gamedirs.elden_ring()
LOG: Path | None = None


def run(command: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(command, cwd=HERE, check=False, text=True,
                            encoding="utf-8", errors="strict",
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if LOG is not None:
        with LOG.open("a", encoding="utf-8") as log:
            log.write(json.dumps(command, ensure_ascii=False) + "\n")
            log.write(result.stdout)
            log.write(result.stderr)
            log.write(f"Exit code: {result.returncode}\n")
    if not capture:
        print(result.stdout, end="", flush=True)
        print(result.stderr, end="", file=sys.stderr, flush=True)
    if result.returncode:
        if capture:
            print(result.stdout, end="", file=sys.stderr)
            print(result.stderr, end="", file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, command)
    return result.stdout if capture else ""


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def extract(data: Path, game: Path, refresh: bool) -> None:
    executable = REPO / "tools/erdata/erextract/target/x86_64-pc-windows-msvc/release/erextract.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"Required read-only erextract binary: {executable}")
    base = [str(executable), "--game-dir", str(game)]
    entries = []
    for pattern in (".msb.dcx", ".emevd.dcx"):
        output = run(base + ["list", "--filter", pattern], capture=True)
        for line in output.splitlines():
            if not line.startswith(("/map/mapstudio/", "/event/")):
                continue
            path, archive, size = line.split("\t")
            entries.append({"path": path, "archive": archive, "size": int(size)})
    entries.sort(key=lambda entry: entry["path"])
    if not entries or len({e["path"] for e in entries}) != len(entries):
        raise ValueError("Empty or duplicate archive inventory")
    originals = data / "originals"
    executable_sha = digest(game / "eldenring.exe")
    archive_hashes = {name: digest(game / Path(name).with_suffix(".bhd"))
                      for name in sorted({entry["archive"] for entry in entries})}
    manifest_path = data / "corpus-manifest.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    old_entries = {entry["path"]: entry for entry in previous.get("entries", [])}
    changed_game = (previous.get("eldenringExeSha256") != executable_sha
                    or previous.get("archiveIndexSha256") != archive_hashes)
    pending = []
    for entry in entries:
        file = originals / entry["path"].lstrip("/")
        old = old_entries.get(entry["path"], {})
        if (refresh or changed_game or not file.is_file() or file.stat().st_size != entry["size"]
                or digest(file) != old.get("sha256")):
            pending.append(entry)
    print(f"Archive inventory: {len(entries)} MSB/EMEVD files; extract {len(pending)}", flush=True)
    for start in range(0, len(pending), 80):
        batch = pending[start:start + 80]
        run(base + ["get"] + [e["path"] for e in batch] + ["--out", str(originals)], capture=True)
        print(f"Extracted {min(start + 80, len(pending))}/{len(pending)}", flush=True)
    for entry in entries:
        file = originals / entry["path"].lstrip("/")
        if file.stat().st_size != entry["size"]:
            raise ValueError(f"Archive size differs: {file}")
        entry["sha256"] = digest(file)
    manifest = {
        "gameDirectory": str(game), "eldenringExeSha256": executable_sha,
        "archiveIndexSha256": archive_hashes,
        "erextractSha256": digest(executable), "entries": entries,
    }
    data.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    global LOG
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify", "extract"), nargs="?", default="build")
    parser.add_argument("--config", type=Path, default=HERE / "first_step.json")
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--game-dir", type=Path, default=GAME)
    parser.add_argument("--refresh", action="store_true", help="Extract every vanilla input again")
    args = parser.parse_args()
    data = args.data_dir.resolve()
    if not data.is_relative_to(DATA.resolve()):
        raise ValueError(f"--data-dir must stay within the exclusive output root: {DATA}")
    (data / "logs").mkdir(parents=True, exist_ok=True)
    LOG = data / "logs" / f"{args.command}-{datetime.now():%Y%m%d-%H%M%S-%f}.log"
    if args.command in ("build", "extract"):
        extract(data, args.game_dir, args.refresh)
    if args.command == "extract":
        return 0
    artifacts = data / "dotnet"
    run(["dotnet", "build", str(HERE / "testarena.csproj"), "-c", "Release",
         "--artifacts-path", str(artifacts), "--source", str(REPO / "tools/third_party/nuget-feed"),
         "-p:RestorePackagesPath=" + str(Path.home() / ".nuget/packages"),
         "-p:NuGetAudit=false", "--nologo"])
    tool = artifacts / "bin/testarena/release/testarena.dll"
    run(["dotnet", str(tool), args.command, str(args.config.resolve()),
         "--data-dir", str(data), "--game-dir", str(args.game_dir)])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"testarena: {error}", file=sys.stderr)
        sys.exit(1)
