"""Prepare a licensed RSX 2.3.0 source copy with additive CLI export settings.

The upstream CLI has no format selection and filters its list before writing.
These changes expose existing exporters, and add a postload-only list mode.
The installed RSX executable is never modified. See rsx_source/LICENSE.
"""
from pathlib import Path
import re


def prepare():
    root = Path(__file__).parent / 'rsx_source'
    main = root / 'src/core/main.cpp'
    text = main.read_text()
    marker = '    RegisterAssetTypeBindings(&cli);'
    addition = '''
    // T001: expose existing export formats without changing their implementations.
    for (auto& [fourCC, binding] : g_assetData.m_assetTypeBindings)
    {
        const std::string param = "--format-" + fourCCToString(fourCC, true);
        if (const char* value = cli.GetParamValue(param.c_str()))
        {
            const int setting = atoi(value);
            if (setting >= 0 && setting < static_cast<int>(binding.e.exportSettingArrSize))
                binding.e.exportSetting = setting;
        }
    }
'''
    if '// T001:' not in text:
        main.write_text(text.replace(marker, marker + addition))
    load = root / 'src/core/filehandling/load.cpp'
    text = load.read_text()
    text = text.replace('else if (cli->HasParam("-export"))',
                        'else if (cli->HasParam("-export") && !cli->HasParam("-metadataonly"))')
    # Upstream filtering overwrites v_assets, which FindAssetByGUID searches.
    # Keep the complete dependency lookup alive while exporting a subset.
    text = text.replace('std::vector<CGlobalAssetData::AssetLookup_t>& assets = g_assetData.v_assets;',
                        'std::vector<CGlobalAssetData::AssetLookup_t> assets = g_assetData.v_assets;')
    marker = '        if (!assets.empty())\n            CThread(HandleExportAllPakAssets'
    addition = '''        // T001: exact names and container filters keep audio samples bounded.
        for (const char* param : { "--exportexact", "--audiostreams" })
        {
            if (const char* value = cli->GetParamValue(param))
            {
                std::vector<std::string> values;
                std::istringstream input(value);
                for (std::string part; std::getline(input, part, ','); )
                    values.push_back(part);
                std::erase_if(assets, [&](const auto& lookup) {
                    const std::string name = strcmp(param, "--exportexact") == 0
                        ? lookup.m_asset->GetAssetName() : lookup.m_asset->GetContainerFileName();
                    return std::ranges::none_of(values, [&](const std::string& v) {
                        return _stricmp(v.c_str(), name.c_str()) == 0;
                    });
                });
            }
        }

'''
    if '// T001: exact names' not in text:
        text = text.replace(marker, addition + marker)
    load.write_text(text)
    audio = root / 'src/game/audio/source.cpp'
    text = audio.read_text()
    marker = '\tif (!CreateDirectories(exportPath))'
    if '// T001: separate language' not in text:
        text = text.replace(marker, '''\t// T001: separate language variants sharing the same asset name and GUID.
\texportPath.append(std::filesystem::path(audioAsset->GetContainerFileName()).stem().string());

''' + marker)
    audio.write_text(text)
    material = root / 'src/game/rtech/assets/material.cpp'
    text = material.read_text()
    text = text.replace('std::filesystem::path exportPath = /*std::filesystem::current_path().append(*/EXPORT_DIRECTORY_NAME/*)*/;',
                        'std::filesystem::path exportPath = g_rsxSettings.GetExportDirectory();')
    text = text.replace('std::filesystem::path exportPath = EXPORT_DIRECTORY_NAME;',
                        'std::filesystem::path exportPath = g_rsxSettings.GetExportDirectory();')
    material.write_text(text)
    odl = root / 'src/game/rtech/assets/odl_asset.cpp'
    text = odl.read_text()
    if '// T001: valid JSON' not in text:
        text = text.replace('    std::string stringStream;', '''    // T001: valid JSON and explicit original/placeholder dependency identifiers.
    std::string originalName(odlAsset->GetOriginalAssetName());
    FixSlashes(originalName);
    std::string stringStream;''')
        text = text.replace('std::string(odlAsset->GetOriginalAssetName())', 'originalName')
        text = text.replace('"\\t\\\"pak\\\": \\\"" + std::string(pakName) + "\\\"\\n"',
                            '''"\\t\\\"originalAssetGuid\\\": \\\"" + std::format("{:016x}", odlAsset->GetOriginalAssetGuid()) + "\\\",\\n"
        "\\t\\\"placeholderAssetGuid\\\": \\\"" + std::format("{:016x}", odlAsset->GetPlaceholderAssetGuid()) + "\\\",\\n"
        "\\t\\\"odlPakGuid\\\": \\\"" + std::format("{:016x}", odlAsset->GetPakAssetGuid()) + "\\\",\\n"
        "\\t\\\"pak\\\": \\\"" + std::string(pakName) + "\\\"\\n"''')
    odl.write_text(text)
    sequence = root / 'src/game/rtech/assets/animseq.cpp'
    text = sequence.read_text()
    if '// T001: avoid basename' not in text:
        marker = '\t\tstd::atomic<uint32_t> remainingSeqs = 0;'
        addition = '''\t\t// T001: avoid basename collisions between different game asset paths.
\t\tstd::unordered_map<uint64_t, std::string> sequenceNames;
\t\tfor (const auto& lookup : g_assetData.v_assets)
\t\t\tif (lookup.m_asset->GetAssetType() == static_cast<uint32_t>(AssetType_t::ASEQ))
\t\t\t\tsequenceNames.emplace(lookup.m_guid, lookup.m_asset->GetAssetName());
\t\tstd::unordered_map<std::string, std::unordered_set<uint64_t>> basenameGuids;
\t\tfor (int idx = 0; idx < numAnimSeqs; ++idx)
\t\t{
\t\t\tconst uint64_t guid = animSeqs[idx].guid;
\t\t\tif (!sequenceNames.contains(guid)) continue;
\t\t\tstd::string base = std::filesystem::path(sequenceNames.at(guid)).filename().string();
\t\t\tstd::transform(base.begin(), base.end(), base.begin(), [](unsigned char c) { return static_cast<char>(tolower(c)); });
\t\t\tbasenameGuids[base].insert(guid);
\t\t}

'''
        text = text.replace(marker, addition + marker)
        marker = '\t\t\toutputPath.replace_filename(std::filesystem::path(animSeqAsset->name).filename());'
        replacement = '''\t\t\tconst std::filesystem::path sequencePath(animSeqAsset->name);
\t\t\tstd::string base = sequencePath.filename().string();
\t\t\tstd::transform(base.begin(), base.end(), base.begin(), [](unsigned char c) { return static_cast<char>(tolower(c)); });
\t\t\toutputPath = exportPath / ("anims_" + stem) / sequencePath.filename();
\t\t\tif (g_rsxSettings.exportPathsFull && basenameGuids[base].size() > 1)
\t\t\t\toutputPath = g_rsxSettings.GetExportDirectory() / sequencePath;
\t\t\tif (!CreateDirectories(outputPath.parent_path())) return false;'''
        text = text.replace(marker, replacement)
    sequence.write_text(text)
    project = root / 'src/rsx.vcxproj'
    text = project.read_text()
    text = text.replace('BUILD_NOGUI;%(PreprocessorDefinitions)',
                        'BUILD_NOGUI;NO_LIBCURL;%(PreprocessorDefinitions)')
    text = text.replace('<TreatWarningAsError>true</TreatWarningAsError>',
                        '<TreatWarningAsError>false</TreatWarningAsError>')
    text = re.sub(r'<PreBuildEvent>.*?</PreBuildEvent>', '', text, flags=re.S)
    project.write_text(text)


if __name__ == '__main__':
    prepare()
