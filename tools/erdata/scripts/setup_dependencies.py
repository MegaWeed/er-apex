"""Set up pinned source snapshots and their documented .NET 8 and T003 FLVER writer patches."""
from pathlib import Path
import fetch_dependencies, fetch_nuget
BASE=Path(__file__).resolve().parents[1]
def main():
    fetch_dependencies.main();fetch_nuget.main()
    third=BASE.parent/'third_party'
    projects=[third/'SoulsFormatsNEXT/SoulsFormats/SoulsFormats.csproj']
    projects += [third/'HKLib'/n/(n+'.csproj') for n in ['HKLib','HKLib.Reflection','HKLib.Serialization']]
    for p in projects:
        original=p.read_text(encoding='utf-8');new=original.replace('<TargetFramework>net9.0</TargetFramework>','<TargetFramework>net8.0</TargetFramework>').replace('<TargetFramework>net7.0</TargetFramework>','<TargetFramework>net8.0</TargetFramework>')
        if new!=original:p.write_text(new,encoding='utf-8')
    faces=third/'SoulsFormatsNEXT/SoulsFormats/Formats/FLVER/FLVER2/FaceSet.cs'
    text=faces.read_text(encoding='utf-8')
    patches=[('if (index > ushort.MaxValue + 1)', 'if (index > ushort.MaxValue)'),
             ('totalFaceCount += Indices.Count / 3;\n                    trueFaceCount += Indices.Count / 3;',
              'totalFaceCount += Indices.Count / 3;\n                    if ((Flags & FSFlags.MotionBlur) == 0)\n                        trueFaceCount += Indices.Count / 3;')]
    for old,new in patches:
        if old in text:text=text.replace(old,new)
        elif new not in text:raise ValueError('Pinned FaceSet source does not match the documented T003 patch')
    faces.write_text(text,encoding='utf-8')
    (third/'Directory.Build.props').write_text('<Project><PropertyGroup><RestorePackagesPath>$(MSBuildThisFileDirectory)nuget-packages</RestorePackagesPath></PropertyGroup></Project>\n',encoding='utf-8')
    (third/'NuGet.Config').write_text('<?xml version="1.0" encoding="utf-8"?>\n<configuration><packageSources><clear/><add key="local-erdata" value="nuget-feed" /></packageSources></configuration>\n',encoding='utf-8')
    (third/'ERDATA_PATCHES.md').write_text('Pinned snapshots: tools/erdata/dependencies.lock.json.\nTarget patches: SoulsFormats.csproj net9.0 -> net8.0; HKLib, HKLib.Reflection and HKLib.Serialization csproj net7.0 -> net8.0.\nNuGet.Config uses the isolated nuget-feed folder; Directory.Build.props fixes the package cache in third_party/nuget-packages; package hashes: tools/erdata/nuget.lock.json.\nT003 FaceSet.cs writer fixes: select 32-bit indices for any index > 65535 (upstream used > 65536); exclude MotionBlur triangle-list copies from trueFaceCount (matching upstream triangle-strip behavior and original ER header). Applied idempotently by setup_dependencies.py; all other format implementation code remains upstream.\n',encoding='utf-8')
    print('Ready for cargo build --release and dotnet build -c Release')
if __name__=='__main__':main()
