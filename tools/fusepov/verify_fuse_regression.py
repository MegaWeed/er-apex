"""Direct comparison against the read-only T011 Fuse output and complete Fuse FPOV."""
import argparse
from pathlib import Path
import sys
sys.dont_write_bytecode = True
from common import ROOT, OUT, OCTANE_OUT, checked_out, read, save

# Only provenance/check additions may change. Meshes, textures, previews and packs are exact comparisons.
PROVENANCE = {'sources', 'idle_source', 'reference_source', 'original_size', 'package_files',
              'material_source', 'material_bundle', 'preserved_input_entry_count', 'all_998_material_count',
              'source_texture_content_checked', 'preserved_999_matbins', 'installed_source_still_matches_snapshot',
              'elapsed_seconds'}


def normalize(value, directory):
    if isinstance(value, dict):
        return {key: normalize(item, directory) for key, item in value.items()
                if 'sha256' not in key and key not in PROVENANCE}
    if isinstance(value, list):
        return [normalize(item, directory) for item in value]
    if isinstance(value, str):
        return value.replace(str(directory), '{OUT}').replace(directory.as_posix(), '{OUT}')
    return value


def differences(old, new, path=''):
    if isinstance(old, dict) and isinstance(new, dict):
        result = []
        for key in sorted(old.keys() | new.keys()):
            if key not in old or key not in new:
                result.append(path+'/'+key)
            else:
                result.extend(differences(old[key], new[key], path+'/'+key))
        return result
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        return [field for i, (a, b) in enumerate(zip(old, new)) for field in differences(a, b, path+f'/{i}')]
    return [] if old == new else [path]


def reason(field, file):
    if 'sha256' in field:
        return '按 D-030 删除哈希字段；改用来源、尺寸、格式及内容检查'
    if field.endswith('/material_source'):
        return '同名材质替换适配器使用输出目录内的暂存输入；原包快照另存并逐字节核对'
    if field.endswith('/installed_source_still_matches_snapshot'):
        return '原 T011 审计跨越安装包更新；本次快照与当前明确指定的输入逐字节相同'
    if field.endswith('/elapsed_seconds'):
        return '构建用时变化'
    if file == 'package/build-manifest.json' and (field.endswith('/template') or field.endswith('/mesh_dir') or field.endswith('/source')):
        return '输出迁移到专属 fuse_check 目录；相应模板/网格/贴图绝对路径随之变化，文件内容直接比较不变'
    if file == 'inputs/source-material.json':
        return '按任务改用当前安装包快照，记录尺寸及复制一致性；原 T011 输入只有 999，当前输入还含原 998 三项'
    if field.startswith('/preserved_999_matbins/'):
        return '原 MATBIN 哈希值改为字节尺寸；各载荷仍逐字节验证'
    return '新增来源/尺寸记录或直接内容验证结果；二进制交付物另行逐字节比较'


def compare(out=None, baseline=OUT, pack_dir=None):
    out = checked_out(out or OCTANE_OUT/'fuse_check')
    baseline = Path(baseline).resolve()
    pack_dir = Path(pack_dir or ROOT/'apex-data/pov/octane/fuse_check').resolve()
    report = dict(status='PASS', baseline=str(baseline), candidate=str(out), byte_identical_counts={},
                  metadata_changes=[], unexpected_differences=[])
    for directory, pattern in [('package', '*.dcx'), ('fusemesh', '*'), ('textures', '*.png'), ('preview', '*.png')]:
        old = {p.relative_to(baseline/directory): p for p in (baseline/directory).rglob(pattern) if p.is_file()}
        new = {p.relative_to(out/directory): p for p in (out/directory).rglob(pattern) if p.is_file()}
        if old.keys() != new.keys():
            report['unexpected_differences'].append(dict(directory=directory, missing=list(map(str, old.keys()-new.keys())), extra=list(map(str, new.keys()-old.keys()))))
        same = 0
        for key in old.keys() & new.keys():
            if old[key].read_bytes() == new[key].read_bytes():
                same += 1
            else:
                report['unexpected_differences'].append(dict(file=str(Path(directory)/key), reason='交付物内容不同'))
        report['byte_identical_counts'][directory] = same
    audits = ['bodygroups.json', 'pov-mesh-summary.json', 'texture-audit.json',
              'preview-verification.json', 'readback-verification.json', 'verification.json',
              'package/build-manifest.json', 'inputs/source-material.json']
    for file in audits:
        old, new = read(baseline/file), read(out/file)
        a, b = normalize(old, baseline), normalize(new, out)
        if file == 'package/build-manifest.json':
            a.pop('material_source', None)
            b.pop('material_source', None)
        if file == 'inputs/source-material.json':
            for key in ('size', 'snapshot_size', 'snapshot_byte_identical', 'note'):
                a.pop(key, None)
                b.pop(key, None)
        for field in differences(a, b):
            report['unexpected_differences'].append(dict(file=file, field=field, reason='非来源字段改变'))
        for field in differences(old, new):
            report['metadata_changes'].append(dict(file=file, field=field, reason=reason(field, file)))
    baseline_pack = ROOT/'apex-data/pov/fuse_pov.anim'
    candidate_pack = pack_dir/'fuse_pov.anim'
    report['fuse_pack_byte_identical'] = baseline_pack.read_bytes() == candidate_pack.read_bytes()
    if not report['fuse_pack_byte_identical']:
        report['unexpected_differences'].append(dict(file=str(candidate_pack), reason='Fuse 动画包字节不同'))
    old, new = read(ROOT/'apex-data/pov/fuse_pov_sequences.json'), read(pack_dir/'fuse_pov_sequences.json')
    for field in differences(normalize(old, baseline), normalize(new, out)):
        report['unexpected_differences'].append(dict(file='fuse_pov_sequences.json', field=field, reason='非来源字段改变'))
    for field in differences(old, new):
        report['metadata_changes'].append(dict(file='fuse_pov_sequences.json', field=field, reason=reason(field, 'fuse_pov_sequences.json')))
    if report['unexpected_differences']:
        report['status'] = 'FAIL'
    save(out/'fuse-regression.json', report)
    print(f'{report["status"]} Fuse regression: {report["byte_identical_counts"]}; '
          f'pack byte-identical={report["fuse_pack_byte_identical"]}; '
          f'{len(report["metadata_changes"])} metadata fields with recorded causes; '
          f'{len(report["unexpected_differences"])} unexpected differences', flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--baseline', type=Path, default=OUT)
    parser.add_argument('--pack-dir', type=Path)
    args = parser.parse_args()
    raise SystemExit(compare(args.out, args.baseline, args.pack_dir))
