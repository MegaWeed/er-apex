"""Meaningful negative checks for the default first_step.json; always restore the package."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gamedirs  # noqa: E402  (tools/gamedirs.py: the games' install folders)

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / "er-data/test_arena"
GAME = gamedirs.elden_ring()


def execute(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=HERE, capture_output=True, text=True, encoding="utf-8")


def main() -> None:
    work = DATA / "checks"
    work.mkdir(parents=True, exist_ok=True)
    build = execute(["dotnet", "build", str(HERE / "checks/Mutation.csproj"), "-c", "Release",
                     "--artifacts-path", str(work / "dotnet"), "--nologo"])
    (work / "fixture-build.log").write_text(build.stdout + build.stderr, encoding="utf-8")
    if build.returncode:
        raise RuntimeError(build.stdout + build.stderr)
    files = [DATA / "package/map/mapstudio/m60_42_36_00.msb.dcx",
             DATA / "package/event/m60_42_36_00.emevd.dcx"]
    before = {file: file.read_bytes() for file in files}
    for file, contents in before.items():
        (work / (file.name + ".backup")).write_bytes(contents)
    mutation = work / "dotnet/bin/Mutation/release/Mutation.dll"
    verify = ["dotnet", str(DATA / "dotnet/bin/testarena/release/testarena.dll"), "verify",
              str(HERE / "first_step.json"), "--data-dir", str(DATA), "--game-dir", str(GAME)]
    cases = {
        "original-part": "Original parts entry changed",
        "original-event": "Original event 0 instruction 0 changed",
        "generator-reference": "New generator fields/references differ",
        "duplicate-id": "New enemy differs from source/config",
        "new-instruction": "Incorrect new event instruction: 2",
    }
    results = []
    try:
        for name, expected in cases.items():
            for file, contents in before.items():
                file.write_bytes(contents)
            changed = execute(["dotnet", str(mutation), *(str(file) for file in files), name,
                               str(GAME / "oo2core_6_win64.dll")])
            if changed.returncode:
                raise RuntimeError(changed.stdout + changed.stderr)
            result = execute(verify)
            log = result.stdout + result.stderr
            (work / (name + ".log")).write_text(log, encoding="utf-8")
            if result.returncode != 1 or expected not in log:
                raise RuntimeError(f"Negative check {name} failed: {log}")
            results.append({"case": name, "exitCode": result.returncode, "expectedFailure": expected})
            print(f"PASS rejected {name}: exit 1, {expected}", flush=True)
    finally:
        for file, contents in before.items():
            file.write_bytes(contents)
        restored = execute(verify)
        (work / "restored-verify.log").write_text(restored.stdout + restored.stderr, encoding="utf-8")
        if restored.returncode:
            raise RuntimeError("Restored package did not verify: " + restored.stdout + restored.stderr)
    (work / "results.json").write_text(json.dumps({"status": "PASS", "cases": results,
                                                 "packageRestored": True}, indent=2) + "\n", encoding="utf-8")
    print("PASS five negative checks; package restored and verified", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
