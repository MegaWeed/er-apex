"""Optional cache bootstrap when Windows Cargo/Schannel lacks TLS credentials.

Uses Python's normal verified HTTPS to the official crates.io index/static host.
Writes only three new dependency entries in the task-authorized Cargo cache.
Archives are format/size checked and compared directly with official downloads.
No content hashes are calculated. No TLS checks disabled.
After this, `cargo test --offline` resolves the existing cached CPAL dependencies.
"""
import io
import json
from pathlib import Path
import urllib.request
import tarfile

PACKAGES = [('crossbeam-queue', '0.3.12'), ('crossbeam-utils', '0.8.21'), ('hound', '3.5.1')]
ROOT = Path(r'C:\Users\umi\.cargo\registry')
REGISTRY = 'index.crates.io-1949cf8c6b5b557f'


def main():
    for name, version in PACKAGES:
        key = f'{name[:2]}/{name[2:4]}/{name}'
        with urllib.request.urlopen(f'https://index.crates.io/{key}', timeout=30) as response:
            lines = response.read().splitlines()
            etag = response.headers.get('ETag', '')
        records = [json.loads(line) for line in lines]
        if not any(r['vers'] == version for r in records):
            raise ValueError(f'Official package version missing: {name} {version}')
        target = ROOT / 'cache' / REGISTRY / f'{name}-{version}.crate'
        url = f'https://static.crates.io/crates/{name}/{name}-{version}.crate'
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
            expected_bytes = response.headers.get('Content-Length')
        if not data or (expected_bytes is not None and len(data) != int(expected_bytes)):
            raise ValueError(f'Official package size mismatch: {name}')
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            members = archive.getmembers()
            if not members or any(not m.name.startswith(f'{name}-{version}/') for m in members):
                raise ValueError(f'Official package archive format mismatch: {name}')
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        elif target.stat().st_size != len(data) or target.read_bytes() != data:
            raise ValueError(f'Existing package differs from official download: {name}')
        index = ROOT / 'index' / REGISTRY / '.cache' / key
        if not index.exists():
            data = b'\x03\x02\x00\x00\x00' + f'etag: {etag}'.encode() + b'\0'
            for record, line in zip(records, lines):
                data += record['vers'].encode() + b'\0' + line + b'\0'
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_bytes(data)
        print(f'cached; archive/size/direct content verified: {name} {version}')


if __name__ == '__main__':
    main()
