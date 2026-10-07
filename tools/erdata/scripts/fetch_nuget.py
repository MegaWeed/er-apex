"""Fetch the five fixed NuGet packages into an isolated local feed."""
from pathlib import Path
import hashlib, json, urllib.request
BASE=Path(__file__).resolve().parents[1]
def main():
    root=BASE.parent/'third_party/nuget-feed';root.mkdir(parents=True,exist_ok=True)
    for name,record in json.loads((BASE/'nuget.lock.json').read_text(encoding='utf-8')).items():
        version=record['version'];dest=root/f'{name.lower()}.{version}.nupkg'
        if not dest.exists():
            print('Downloading',name,version,flush=True)
            dest.write_bytes(urllib.request.urlopen(f'https://api.nuget.org/v3-flatcontainer/{name.lower()}/{version}/{name.lower()}.{version}.nupkg',timeout=120).read())
        if hashlib.sha256(dest.read_bytes()).hexdigest()!=record['sha256']:raise ValueError(f'Package checksum mismatch: {dest}')
    print('Verified local NuGet feed',flush=True)
if __name__=='__main__':main()
