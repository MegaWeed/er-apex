"""Build the T001 RSX CLI adapter entirely inside this exclusive directory.

Pinned upstream: r-ex/rsx tag 2.3.0, commit 2c63d87 (AGPL-3.0).
Decoder download URLs and SHA256 values are upstream tools/prebuild.ps1 values.
No git commands, vcpkg installs, or writes to the installed RSX are performed.
"""
from pathlib import Path
import gzip
import hashlib
import io
import subprocess
import urllib.request
import zipfile
from prepare_rsx import prepare

ROOT = Path(__file__).resolve().parent
EXE = ROOT / 'rsx_source/bin/Release_NoGui/rsx.exe'
DECODERS = [
    ('binka/binka_ue_decode_win64_static_x64D.lib', 'UnrealEngine-31312565', '7e2a40af2d9721f69c43e48fee940332c37cf3c4', 797396, 452462, 'F1CD322361BFDF25708E06CD4941DFC50D59C9C6EFAA3C87E383F51E71EB87B5'),
    ('binka/binka_ue_decode_win64_static_x64.lib', 'UnrealEngine-25887585', '9ce4a076844fff6f758111f2d38b6dbabbc2ecee', 8, 149056, '63A0B56048090841A1D867924B65C4273C6C929DF3A616527F0C671956C114B9'),
    ('radaudio/radaudio_decoder_win64.lib', 'UnrealEngine-40594131', '3578368bc5d11cd2e80c63f7063c2828954c1562', 1693906, 330314, 'F7089A7A48B304CB54D00EB2BB75FD56A30923550BA4B74BAAE6FD7697BD1807'),
]


def download_source():
    source = ROOT / 'rsx_source'
    if (source / 'src/rsx.vcxproj').exists():
        return
    data = urllib.request.urlopen('https://api.github.com/repos/r-ex/rsx/zipball/2c63d87').read()
    archive = zipfile.ZipFile(io.BytesIO(data))
    prefix = archive.namelist()[0]
    for member in archive.namelist():
        rel = Path(member[len(prefix):])
        if member.endswith('/') or not rel.parts:
            continue
        target = (source / rel).resolve()
        if not target.is_relative_to(source.resolve()):
            raise ValueError(f'Unsafe archive path: {member}')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(member))


def ensure_tool(rebuild=False):
    if EXE.exists() and not rebuild:
        return EXE
    download_source()
    for file, remote, pack, offset, size, sha in DECODERS:
        target = ROOT / 'rsx_source/src/thirdparty' / file
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest().upper() == sha:
            continue
        blob = urllib.request.urlopen(f'https://cdn.unrealengine.com/dependencies/{remote}/{pack}').read()
        data = gzip.decompress(blob)[offset:offset + size]
        if hashlib.sha256(data).hexdigest().upper() != sha:
            raise ValueError(f'Decoder SHA256 mismatch: {file}')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    prepare()
    vswhere = Path(r'C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe')
    install = subprocess.check_output([str(vswhere), '-latest', '-products', '*',
                                      '-requires', 'Microsoft.Component.MSBuild',
                                      '-property', 'installationPath'], text=True).strip()
    msbuild = Path(install) / 'MSBuild/Current/Bin/MSBuild.exe'
    command = [str(msbuild), str(ROOT / 'rsx_source/src/rsx.vcxproj'),
               '/p:Configuration=Release_NoGui', '/p:Platform=x64',
               '/p:VcpkgEnabled=false', '/p:VcpkgEnableManifest=false',
               '/m:8', '/v:minimal', '/nologo']
    with (ROOT / 'build.log').open('w', encoding='utf8') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    if not EXE.exists():
        raise FileNotFoundError(EXE)
    return EXE


if __name__ == '__main__':
    print(ensure_tool(rebuild=True))
