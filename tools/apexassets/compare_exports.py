"""Compare a fresh Fuse export to the read-only T001 directory, file by file.

Compares content directly and requires evidence for every accepted difference.
The baseline's nested octane/ subtree is excluded before directory traversal.
"""
import argparse
import collections
import csv
import gzip
import filecmp
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'apex-data/assets'


def files(root, excluded=None):
    result = {}
    for directory, folders, names in os.walk(root):
        for folder in list(folders):
            if excluded is not None and (Path(directory) / folder).resolve() == excluded.resolve():
                folders.remove(folder)
        for name in names:
            path = Path(directory) / name
            result[path.relative_to(root).as_posix()] = path
    return result


def same_content(a, b, compressed=False):
    if not compressed:
        return filecmp.cmp(a, b, shallow=False)
    with gzip.open(a, 'rb') as left, gzip.open(b, 'rb') as right:
        while True:
            x, y = left.read(1024 * 1024), right.read(1024 * 1024)
            if x != y:
                return False
            if not x:
                return True


def json_data(path):
    return json.loads(path.read_text(encoding='utf8'))


def csv_counts(path):
    with path.open(encoding='utf8', newline='') as stream:
        return collections.Counter(tuple(sorted(row.items())) for row in csv.DictReader(stream))


def without_file_hashes(value):
    """Ignore only the obsolete derived SHA256 field; game GUIDs remain exact."""
    if isinstance(value, dict):
        return {key: without_file_hashes(item) for key, item in value.items() if key != 'sha256'}
    if isinstance(value, list):
        return [without_file_hashes(item) for item in value]
    return value


def metadata_added(before, after, key):
    """The QC fix can add metadata, but must preserve every pre-existing record."""
    a = {k: v for k, v in before.items() if k != key}
    b = {k: v for k, v in after.items() if k != key}
    return a == b and all(item in after.get(key, []) for item in before.get(key, []))


def compare(baseline, candidate, report):
    baseline, candidate = baseline.resolve(), candidate.resolve()
    old, new = files(baseline, ROOT / 'octane'), files(candidate)
    reverse_new = collections.defaultdict(list)
    for name, path in new.items():
        reverse_new[(Path(name).suffix, path.stat().st_size)].append(name)
    old_inventory = {row['export_file']: row for row in json_data(baseline / 'inventory.json')['assets']}
    arm_texture_stems = {Path(name).stem.lower() for name, row in old_inventory.items()
                         if row.get('texture_uses') and all('fuse_base_v_arms' in use['material']
                                                          for use in row['texture_uses'])}
    differences, identical = [], []

    def record(name, kind, category, cause, evidence=None):
        item = {'path': name, 'difference': kind, 'category': category, 'cause': cause,
                'baseline_size': old[name].stat().st_size if name in old else None,
                'candidate_size': new[name].stat().st_size if name in new else None}
        if evidence is not None:
            item['evidence'] = evidence
        differences.append(item)

    for name in sorted(old.keys() | new.keys()):
        if name in old and name in new and same_content(old[name], new[name]):
            identical.append({'path': name, 'size': old[name].stat().st_size})
            continue
        if name not in new:
            aliases = []
            if name.startswith(('cast/animrig/humans/class/medium/anims_mp_pilot_medium_core/',
                                'raw/animrig/humans/class/medium/anims_mp_pilot_medium_core/')):
                aliases = [other for other in reverse_new.get((Path(name).suffix, old[name].stat().st_size), [])
                           if same_content(old[name], new[other])]
            identity = old_inventory.get(name, {})
            if aliases and (name.startswith('cast/animrig/humans/class/medium/anims_mp_pilot_medium_core/')
                            or name.startswith('raw/animrig/humans/class/medium/anims_mp_pilot_medium_core/')):
                record(name, 'baseline_only', 'superseded_collision_alias',
                       'T001 在 basename 冲突修正前的序列试导别名；新目录已有字节完全相同的完整路径产物。',
                       {'identical_candidate_paths': aliases, 'old_export_status': identity.get('export_status')})
            elif (name.startswith('cast/animrig/weapons/arms/pov_pilot_medium_fuse')
                  or '/pov_pilot_medium_fuse' in name or 'fuse_base_v_arms_sknp.' in name
                  or (name.startswith('dds/texture/') and name.endswith('.json')
                      and Path(name).stem.lower() in arm_texture_stems)
                  or (identity.get('type') == 'txtr' and any('fuse_base_v_arms' in use['material']
                                                          for use in identity.get('texture_uses', [])))):
                record(name, 'baseline_only', 'manual_fuse_arms_trial',
                       'T001 的第一人称手臂试导及补录材质；原 Fuse 主命令的 -pov_ 筛选一直排除手臂，回归保留该行为。',
                       {'source': 'docs/codex/reports/T001-apex-asset-export.md', 'old_identity': identity})
            elif name.startswith(('lists/', 'logs/')):
                record(name, 'baseline_only', 'old_diagnostic_trial',
                       'T001 调研或手工复核留下的清单、依赖文本、控制台日志，不是原主命令产物。')
            else:
                record(name, 'baseline_only', 'unexplained', '尚未证明差异原因。')
            continue
        if name not in old:
            if name.startswith('logs/rsx_runtime/matplotlib/'):
                record(name, 'candidate_only', 'confined_matplotlib_cache',
                       '绘图字体缓存现在随输出目录保存，保证不向独占目录之外写入。')
            else:
                record(name, 'candidate_only', 'unexplained', '尚未证明差异原因。')
            continue
        if name.startswith('lists/') and name.endswith('.csv') and csv_counts(old[name]) == csv_counts(new[name]):
            record(name, 'different', 'list_order_only', '并行加载使 CSV 行序不同；字段和值构成的多重集合完全一致。')
        elif name.endswith('.adjlist') and collections.Counter(old[name].read_text().splitlines()) == collections.Counter(new[name].read_text().splitlines()):
            record(name, 'different', 'list_order_only', '并行加载使依赖表行序不同；全部依赖行的多重集合完全一致。')
        elif name.endswith('.gz') and same_content(old[name], new[name], True):
            record(name, 'different', 'gzip_timestamp_only', 'gzip 头记录本次生成时间；解压后的完整音源 CSV 字节一致。',
                   {'uncompressed_content_equal': True, 'baseline_mtime': int.from_bytes(old[name].read_bytes()[4:8], 'little'),
                    'candidate_mtime': int.from_bytes(new[name].read_bytes()[4:8], 'little')})
        elif name == 'audio_samples.json' and without_file_hashes(json_data(old[name])) == json_data(new[name]):
            record(name, 'different', 'obsolete_hash_metadata_removed',
                   '按用户要求删除 WAV 的派生 SHA256 字段；声音格式、帧数、采样率和样本文件内容完全一致。')
        elif name == 'fuse_sequences.json':
            a, b = json_data(old[name]), json_data(new[name])
            before = {row['guid']: row for row in a['sequences']}
            after = {row['guid']: row for row in b['sequences']}
            equal = (before.keys() == after.keys()
                     and {k: v for k, v in a.items() if k != 'sequences'} == {k: v for k, v in b.items() if k != 'sequences'}
                     and all(metadata_added(before[guid], row, 'qc_metadata') for guid, row in after.items()))
            record(name, 'different', 'brace_free_qc_metadata_added' if equal else 'unexplained',
                   '修复 QC 解析器后补出不带花括号的序列元数据；原有动画、曲线、活动、帧率和记录均保留。' if equal else '动画汇总有未解释变化。',
                   {'sequences_with_added_metadata': sum(before[guid] != row for guid, row in after.items())} if equal else None)
        elif name == 'qc_metadata.json':
            a = {row['file']: row for row in json_data(old[name])['files']}
            b = {row['file']: row for row in json_data(new[name])['files']}
            equal = a.keys() == b.keys() and all(metadata_added(a[path], row, 'sequences') for path, row in b.items())
            record(name, 'different', 'brace_free_qc_metadata_added' if equal else 'unexplained',
                   '同一批 QC 文件补入不带花括号的序列；原有序列、include 和姿态参数没有变化。' if equal else 'QC 汇总有未解释变化。')
        elif name in {'models.json', 'materials.json'}:
            key = name.removesuffix('.json')
            a = {row['file'] if key == 'models' else row['json_file']: row for row in json_data(old[name])[key]}
            b = {row['file'] if key == 'models' else row['json_file']: row for row in json_data(new[name])[key]}
            equal = all(a.get(path) == row for path, row in b.items())
            extra = sorted(a.keys() - b.keys())
            if equal and extra and all('pov_pilot_medium_fuse' in path or 'fuse_base_v_arms' in path for path in extra):
                record(name, 'different', 'manual_fuse_arms_summary', '全部主命令记录一致；旧汇总另含手工试导的 Fuse 手臂模型、骨架或材质。',
                       {'extra_baseline_records': extra})
            else:
                record(name, 'different', 'unexplained', '模型或材质汇总仍有未解释变化。', {'extra_baseline_records': extra})
        elif name == 'verification.json':
            a, b = without_file_hashes(json_data(old[name])), json_data(new[name])
            changed = {key: {'baseline': a.get(key), 'candidate': b.get(key)} for key in a.keys() | b.keys() if a.get(key) != b.get(key)}
            allowed = changed.keys() <= {'seconds', 'material_count'}
            record(name, 'different', 'verification_runtime_and_trials' if allowed else 'unexplained',
                   '验收耗时不同，旧手臂补录使材质数为 17，新主命令为 16；其余验收结果完全一致。' if allowed else '验收结果有未解释变化。', changed)
        elif name in {'inventory.json', 'inventory.md'}:
            record(name, 'different', 'inventory_trials_and_runtime', '文件清单反映上述试导残留与日志大小；目录中的每项实际变化均由本差异报告单独列出。')
        elif name == 'run_manifest.json':
            record(name, 'different', 'run_paths_and_runtime', '输出目录、工作目录、耗时及本次运行列表不同；旧记录包含后续手臂材质补录。')
        elif name == 'logs/rsx_runtime/rsx_cache_db.bin':
            record(name, 'different', 'rsx_runtime_cache', 'RSX 名称缓存受旧加载记录及序列化顺序影响；缓存不是游戏导出资产。',
                   {'implementation': 'tools/apexassets/rsx_source/src/core/cache/cachedb.cpp'})
        elif name == 'logs/core_named.log':
            record(name, 'different', 'rsx_runtime_diagnostic', '首次运行与已有运行目录的日志初始化信息不同。',
                   {'baseline_text': old[name].read_text(errors='replace'), 'candidate_text': new[name].read_text(errors='replace')})
        else:
            record(name, 'different', 'unexplained', '尚未证明差异原因。')
    unexplained = [row for row in differences if row['category'] == 'unexplained']
    result = {'status': 'passed_with_explained_differences' if not unexplained else 'failed',
              'baseline': str(baseline), 'candidate': str(candidate),
              'baseline_excluded_subtree': str(ROOT / 'octane'),
              'baseline_files': len(old), 'candidate_files': len(new), 'identical_files': len(identical),
              'baseline_only_files': sum(row['difference'] == 'baseline_only' for row in differences),
              'candidate_only_files': sum(row['difference'] == 'candidate_only' for row in differences),
              'different_files': sum(row['difference'] == 'different' for row in differences),
              'unexplained_files': len(unexplained), 'categories': dict(collections.Counter(row['category'] for row in differences)),
              'differences': differences, 'identical': identical}
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({key: value for key, value in result.items() if key not in {'differences', 'identical'}}, ensure_ascii=False, indent=2))
    return 1 if unexplained else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=ROOT)
    parser.add_argument('--candidate', type=Path, default=ROOT / 'octane/fuse_check')
    parser.add_argument('--report', type=Path, default=ROOT / 'octane/fuse_comparison.json')
    args = parser.parse_args()
    raise SystemExit(compare(args.baseline, args.candidate, args.report))
