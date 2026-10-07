"""Fetch immutable upstream snapshots without changing Git state."""
import json, pathlib, urllib.request, zipfile, io
ROOT = pathlib.Path(__file__).resolve().parents[2] / 'third_party'
REPOS = {'SoulsFormatsNEXT':'soulsmods/SoulsFormatsNEXT', 'HKLib':'The12thAvenger/HKLib', 'Paramdex':'soulsmods/Paramdex', 'UXM-Selective-Unpack':'Nordgaren/UXM-Selective-Unpack'}
def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'ER-Fuse-tooling'}), timeout=180).read()
def main():
    ROOT.mkdir(exist_ok=True)
    lock_path = pathlib.Path(__file__).resolve().parents[1] / 'dependencies.lock.json'
    lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.exists() else {}
    for name, repo in REPOS.items():
        if name not in lock:
            info=json.loads(get(f'https://api.github.com/repos/{repo}'))
            commit=json.loads(get(f'https://api.github.com/repos/{repo}/commits/{info["default_branch"]}'))['sha']
            lock[name]={'repository':f'https://github.com/{repo}', 'commit':commit}
            lock_path.write_text(json.dumps(lock, indent=2)+'\n')
        commit=lock[name]['commit']
        target=ROOT/name
        if target.exists():
            marker=target/'.erdata-snapshot.json'
            if not marker.exists() or json.loads(marker.read_text(encoding='utf-8'))!=lock[name]:
                raise RuntimeError(f'Existing directory is not a completed pinned snapshot: {target}')
            print(name, commit, 'already present', flush=True); continue
        print('Downloading', name, commit, flush=True)
        archive=zipfile.ZipFile(io.BytesIO(get(f'https://codeload.github.com/{repo}/zip/{commit}')))
        target.mkdir()
        for entry in archive.infolist():
            rel=pathlib.PurePosixPath(entry.filename).parts[1:]
            if not rel: continue
            if any(part in ['..','.'] or ':' in part for part in rel): raise ValueError('Unsafe snapshot path')
            out=target.joinpath(*rel)
            if entry.is_dir(): out.mkdir(parents=True, exist_ok=True)
            else:
                out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(archive.read(entry))
        (target/'.erdata-snapshot.json').write_text(json.dumps(lock[name],indent=2)+'\n',encoding='utf-8')
    print('Dependencies ready', flush=True)
if __name__ == '__main__': main()
