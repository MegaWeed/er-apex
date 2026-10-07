"""Populate Cargo's ordinary cache over verified Python TLS when Schannel fails.

No registry mirror, certificate disabling, or permission override. Archive hashes
are checked against Cargo.lock. Writes only to this crate and ~/.cargo/registry.
Run from this crate: python tools/cache_dependencies.py; cargo test --offline
"""
import hashlib
import json
import pathlib
import re
import subprocess
import tomllib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY = pathlib.Path.home() / '.cargo' / 'registry'
INDEX = REGISTRY / 'index' / 'index.crates.io-1949cf8c6b5b557f'
CACHE = REGISTRY / 'cache' / 'index.crates.io-1949cf8c6b5b557f'


def fetch(url):
    return urllib.request.urlopen(url, timeout=60).read()


def main():
    INDEX.mkdir(parents=True, exist_ok=True)
    (INDEX / 'config.json').write_bytes(fetch('https://index.crates.io/config.json'))
    for _ in range(200):
        result = subprocess.run(['cargo', 'generate-lockfile', '--offline'], cwd=ROOT,
                                capture_output=True, text=True)
        if result.returncode == 0:
            break
        match = re.search(r"no matching package named `([^`]+)` found", result.stderr)
        if not match:
            raise RuntimeError(result.stderr)
        name = match[1].lower()
        key = (f'1/{name}' if len(name) == 1 else f'2/{name}' if len(name) == 2
               else f'3/{name[0]}/{name}' if len(name) == 3
               else f'{name[:2]}/{name[2:4]}/{name}')
        lines = fetch(f'https://index.crates.io/{key}').splitlines()
        payload = b'\x03\x02\x00\x00\x00etag: "python-cache"\x00'
        for line in lines:
            payload += json.loads(line)['vers'].encode() + b'\x00' + line + b'\x00'
        destination = INDEX / '.cache' / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        print('index', name, flush=True)
    else:
        raise RuntimeError('Dependency resolution did not converge')
    CACHE.mkdir(parents=True, exist_ok=True)
    for package in tomllib.loads((ROOT / 'Cargo.lock').read_text())['package']:
        if 'checksum' not in package:
            continue
        name, version = package['name'], package['version']
        destination = CACHE / f'{name}-{version}.crate'
        data = (destination.read_bytes() if destination.exists() else
                fetch(f'https://static.crates.io/crates/{name}/{name}-{version}.crate'))
        if hashlib.sha256(data).hexdigest() != package['checksum']:
            raise RuntimeError(f'Checksum mismatch: {name}-{version}')
        destination.write_bytes(data)
        print('verified', name, version, flush=True)


if __name__ == '__main__':
    main()
