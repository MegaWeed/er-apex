"""Disassemble locally extracted shader bytecode with the installed Windows SDK DXC."""
import argparse, hashlib, json, subprocess
from pathlib import Path
DEFAULT_DXC = Path('C:/Program Files (x86)/Windows Kits/10/bin/10.0.26100.0/x64/dxc.exe')
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='+', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--dxc', type=Path, default=DEFAULT_DXC)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    records = []
    for file in args.files:
        data = file.read_bytes()
        if data[:4] != b'DXBC':
            raise ValueError(f'Not DXBC: {file}')
        length = int.from_bytes(data[24:28], 'little')
        output = args.out / (file.name + '.asm')
        result = subprocess.run([str(args.dxc), '-dumpbin', str(file)], capture_output=True, encoding='utf-8', check=True)
        output.write_text(result.stdout, encoding='utf-8')
        records.append(dict(source=str(file.resolve()), sha256=hashlib.sha256(data).hexdigest(), dxbc_size=length, output=output.name))
        print(output)
    (args.out / 'manifest.json').write_text(json.dumps(dict(dxc=str(args.dxc), dxc_sha256=hashlib.sha256(args.dxc.read_bytes()).hexdigest(), files=records), indent=2) + '\n', encoding='utf-8')
if __name__ == '__main__':
    main()
