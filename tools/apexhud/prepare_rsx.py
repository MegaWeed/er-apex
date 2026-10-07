"""T009 additive RSX metadata adapter; the T001 source tree is read-only.

All copies, patches, build intermediates and logs stay under tools/apexhud.
No downloads and no git operations are performed.
"""
from pathlib import Path
import json
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'apexassets/rsx_source'
WORK = HERE / 'rsx_work'
EXE = WORK / 'bin/Release_NoGui/rsx.exe'


def ensure_tool():
    adapter = HERE / 'hud_export.h'
    inputs = [adapter, Path(__file__), SOURCE / 'src/rsx.vcxproj']
    inputs += [SOURCE / 'src/game/rtech/assets' / name
               for name in ('ui.cpp', 'ui_image.cpp', 'ui_font_atlas.cpp')]
    cache = WORK / 't009_build_inputs'
    if EXE.is_file() and all(p.is_file() and (cache / p.name).is_file()
            and p.stat().st_size == (cache / p.name).stat().st_size
            and p.read_bytes() == (cache / p.name).read_bytes() for p in inputs):
        return EXE
    if not (SOURCE / 'src/rsx.vcxproj').exists():
        raise FileNotFoundError(f'T001 RSX source is required: {SOURCE}')
    # Avoid copying third-party git metadata and 300 MB of stale build outputs.
    if not (WORK / 'src/rsx.vcxproj').exists():
        shutil.copytree(SOURCE, WORK, ignore=shutil.ignore_patterns('.git', 'obj', 'bin', '.vs'))
    shutil.copyfile(adapter, WORK / 'src/game/rtech/assets/hud_export.h')
    for filename, hook in [
        ('ui.cpp', 'T009ExportUI(pakAsset, uiAsset, exportPath);'),
        ('ui_image.cpp', 'T009ExportImage(pakAsset, uiAsset, exportPath);'),
        ('ui_font_atlas.cpp', 'T009ExportFont(pakAsset, uiAsset, exportPath);'),
    ]:
        original = (SOURCE / 'src/game/rtech/assets' / filename).read_text(encoding='utf8')
        original = original.replace('#include <pch.h>', '#include <pch.h>\n#include "hud_export.h"', 1)
        if filename == 'ui.cpp':
            marker = '    exportPath.append(uiPath.stem().string());'
        elif filename == 'ui_image.cpp':
            blank = '    assertm(uiTexture, "uiTexture is nullptr.");'
            if original.count(blank) != 1:
                raise RuntimeError('Upstream UIIA initialization anchor changed')
            original = original.replace(blank, blank + '\n    // T009: deterministic transparent pixels if an edge CopyRectangle is rejected.\n    memset(uiTexture->GetPixels(), 0, uiTexture->GetSlicePitch());')
            marker = '    switch (setting)\n    {\n    case eUIImageExportSetting::PNG_HQ:'
        else:
            # Upstream creates the parent of the atlas directory, causing silent
            # missing font exports on a cold output tree. Create the directory.
            original = original.replace('CreateDirectories(exportPath.parent_path())', 'CreateDirectories(exportPath)')
            marker = '    exportPath.append(atlasPath.stem().string());'
        expected = 2 if filename == 'ui_image.cpp' else 1
        if original.count(marker) != expected:
            raise RuntimeError(f'Upstream patch anchor changed: {filename}')
        if filename == 'ui_image.cpp':
            before, after = original.rsplit(marker, 1)
            original = before + '    ' + hook + '\n\n' + marker + after
        else:
            original = original.replace(marker, marker + '\n    ' + hook)
        (WORK / 'src/game/rtech/assets' / filename).write_text(original, encoding='utf8')
    vswhere = Path(r'C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe')
    install = subprocess.check_output([str(vswhere), '-latest', '-products', '*',
        '-requires', 'Microsoft.Component.MSBuild', '-property', 'installationPath'], text=True).strip()
    if not install:
        raise RuntimeError('Visual Studio MSBuild was not found')
    command = [str(Path(install) / 'MSBuild/Current/Bin/MSBuild.exe'), str(WORK / 'src/rsx.vcxproj'),
        '/p:Configuration=Release_NoGui', '/p:Platform=x64', '/p:VcpkgEnabled=false',
        '/p:VcpkgEnableManifest=false', '/m:8', '/v:minimal', '/nologo']
    print('Building T009 RSX adapter (local source only)...', flush=True)
    with (HERE / 'build.log').open('w', encoding='utf8') as log:
        result = subprocess.run(command, cwd=WORK, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f'MSBuild exit {result.returncode}; see {HERE / "build.log"}')
    if not EXE.exists():
        raise FileNotFoundError(EXE)
    cache.mkdir(parents=True, exist_ok=True)
    for source in inputs:
        shutil.copyfile(source, cache / source.name)
    (cache / 'sources.json').write_text(json.dumps([
        {'source': str(p), 'size_bytes': p.stat().st_size, 'snapshot': p.name}
        for p in inputs], indent=2) + '\n', encoding='utf8')
    return EXE


if __name__ == '__main__':
    print(ensure_tool())
