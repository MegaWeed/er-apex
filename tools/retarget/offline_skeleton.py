"""The c0000 skeleton in the running game's dump format (src/dev.rs `skeleton`), from the game files
alone: er-data/json/c0000_skeleton.json (tools/erdata run_s2a.py, Skeleton.hkx of c0000.anibnd).

The game's dump was only ever read for each bone's name, parent and reference pose, and
skeleton_map.py checks those against this file to 1e-6 (they are the same data). So a player's
first asset run needs no game start (the one-click setup, release/setup.ps1). `local` and `model`
(the live pose of the dump, read by nothing) are written as the reference pose.

Run from the repository root: python tools/retarget/offline_skeleton.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'er-data/json/c0000_skeleton.json'
OUTS = [ROOT / 'er-data/runtime/c0000_runtime.json', ROOT / 'er-data/skeleton/c0000_live_skeleton.json']


def main():
    src = json.loads(SOURCE.read_text(encoding='utf8'))
    bones = []
    for b in src['Bones']:
        ref = {'t': b['Translation'][:3], 'r': b['Rotation'][:4], 's': b['Scale'][:3]}
        bones.append({'i': b['Index'], 'name': b['Name'], 'parent': b['ParentIndex'], 'ref': ref, 'local': ref, 'model': ref})
    out = {'skeleton': 'c0000', 'bone_count': len(bones), 'reference_pose_offset': 'offline', 'reference_pose_valid': True, 'bones': bones}
    text = json.dumps(out)
    for path in OUTS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf8')
    print(f'c0000: {len(bones)} bones from {SOURCE.name} -> ' + ', '.join(str(p.relative_to(ROOT)) for p in OUTS))


if __name__ == '__main__':
    main()
