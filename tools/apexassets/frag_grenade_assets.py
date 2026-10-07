"""U9: the frag grenade's local assets, by the names its weapon settings give.

S3 (R5Reloaded `platform/scripts/weapons/mp_weapon_frag_grenade.txt`, MP_BASE) and the retail export
(`apex-data/export/weapon/mp_weapon_frag_grenade.txt`) both name the first-person model
`viewmodel` = mdl/weapons/grenades/ptpov_frag_grenade_held.rmdl and the thrown one
`projectilemodel` = mdl/weapons/grenades/m20_f_grenade_projectile.rmdl; the script checks they agree.
From the local common.rpak, with the existing RSX adapter (no rebuild): both models (Cast, raw),
their materials and textures, the view model's rig with its sequences (Cast, raw RSEQ) and the
SMD/QC. Then `sequences/ptpov_frag_grenade_held.json`: each sequence's frames, frame rate, activity
(RSEQ) and its QC block with the events (AE_WPN_TOSS_RELEASE, sounds) parsed out.

Run from the repository root (the RSX adapter of the main checkout when this one has none):
  python tools/apexassets/frag_grenade_assets.py [--out DIR] [--rsx EXE] [--retail TXT] [--analyze-only]
Output: apex-data/assets/frag_grenade/ (not in git). No game launch, no git, no hashing.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import s3record  # noqa: E402  (tools/s3record.py: S3's evidence without R5Reloaded)

sys.dont_write_bytecode = True
import export_assets as ea  # noqa: E402
import octane_assets as oa  # noqa: E402
from build_rsx import EXE  # noqa: E402
from cast import Model, Animation  # noqa: E402
from inspect_assets import nodes, qc_sections, rson_arrays, dump, normal, animation_data  # noqa: E402

ROOT = oa.REPO
OUT = ROOT / 'apex-data/assets/frag_grenade'
# S3's weapon settings, as tools/s3_evidence.json recorded them
R5_WEAPON = s3record.R5_ROOT / 'platform/scripts/weapons/mp_weapon_frag_grenade.txt'
RETAIL_WEAPON = ROOT / 'apex-data/export/weapon/mp_weapon_frag_grenade.txt'


def setting(path: Path, key: str, block: str | None = None) -> str:
    """One string setting (in `block` { ... } when given) of a weapon .txt."""
    text = path.read_text(encoding='utf8', errors='replace')
    if block:
        m = re.search(r'"?' + re.escape(block) + r'"?\s*\{(.*?)\}', text, re.S)
        if not m:
            raise ValueError(f'{path}: no {block} block')
        text = m.group(1)
    found = re.findall(r'"' + re.escape(key) + r'"\s+"([^"]*)"', text)
    if len(found) != 1:
        raise ValueError(f'{path}: expected one {key}, found {found}')
    return found[0]


def targets_from_settings(retail: Path) -> list[dict]:
    out = []
    for role, key, block in [('frag_viewmodel', 'viewmodel', 'MP_BASE'), ('frag_projectile', 'projectilemodel', None)]:
        s3 = s3record.get('frag_settings', f'{block}.{key}' if block else key,
                          lambda r5: setting(s3record.real(r5, R5_WEAPON), key, block)
                          if s3record.real(r5, R5_WEAPON).is_file() else None)
        now = setting(retail, key, block)
        if s3 is not None and normal(s3) != normal(now):
            raise ValueError(f'{key}: S3 {s3} differs from retail {now}')
        out.append(dict(role=role, asset_path=now, settings=[
            dict(source=str(R5_WEAPON), key=key, block=block, value=s3),
            dict(source=str(retail), key=key, block=block, value=now)]))
    return out


EVENT = re.compile(r'event\s+"?(\w+)"?\s+(\d+)(?:\s+"([^"]*)")?')


def qc_details(block: str) -> dict:
    """What the sequence's QC says: fps, activity, fades, loop, events by frame."""
    def number(name):
        m = re.search(r'\b' + name + r'\s+(-?[\d.]+)', block)
        return float(m.group(1)) if m else None
    m = re.search(r'\bactivity\s+"?(\w+)"?\s+(-?\d+)', block)
    return dict(fps=number('fps'), fadein=number('fadein'), fadeout=number('fadeout'),
                loop=bool(re.search(r'\bloop\b', block)), activity=m.group(1) if m else None,
                activity_weight=int(m.group(2)) if m else None,
                events=[dict(event=e, frame=int(f), options=o) for e, f, o in EVENT.findall(block)])


def analyze(out: Path) -> dict:
    by_guid, by_name = oa.indexes(oa.list_rows(out))
    selection = oa.load_json(out / 'export_selection.json')
    viewmodel = next(t for t in selection['targets'] if t['role'] == 'frag_viewmodel')
    parents = [viewmodel['asset']] + viewmodel['rigs']
    qc_paths = [oa.asset_file(out, 'smd', r, '.qc') for r in parents]
    qcs = {oa.relpath(p, out): qc_sections(p) for p in qc_paths if p.is_file()}
    casts = {}
    for path in sorted((out / 'cast').rglob('*.cast')):
        for node in nodes(path):
            if isinstance(node, Animation):
                index = int(re.search(r'_(\d+)\.cast$', path.name)[1])
                casts.setdefault(f'{node.Hash():016x}', {})[index] = dict(animation_data(node), file=oa.relpath(path, out))
    refs = {}
    for rig in viewmodel['rigs']:
        manifest = oa.asset_file(out, 'raw', rig, '.rson')
        for value in rson_arrays(manifest).get('seqs', []):
            row = oa.asset_reference(value, by_guid, by_name)
            if row is None:
                raise ValueError(f'待定: rig sequence {value} not in the local list')
            refs[row['guid']] = row
    refs.update({r['guid']: r for r in viewmodel['inline_sequences']})
    seqs = []
    for guid, row in refs.items():
        path = oa.linked_sequence_file(out, row, parents)
        meta = oa.rseq_metadata(path)
        blocks = [dict(file=p, raw_qc=block, **qc_details(block)) for p, (_, sections) in qcs.items()
                  for kind, name, block in sections if kind == 'sequence' and name.lower() == meta['name'].lower()]
        for sample in meta['blends']:
            clip = casts.get(guid, {}).get(sample['blend_index'])
            if clip is not None:
                if clip['framerate'] != sample['framerate']:
                    raise ValueError(f'Cast/RSEQ frame rate differs: {path}')
                sample.update(cast_file=clip['file'], cast_frame_count=clip['frame_count'])
        seqs.append(dict(meta, asset_path=row['asset_name'].replace('\\', '/'), guid=guid, source_rpak=row['file_name'],
                         raw_file=oa.relpath(path, out), qc=blocks))
    seqs.sort(key=lambda s: normal(s['asset_path']))
    table = dict(model=viewmodel['asset'], rigs=viewmodel['rigs'], sequence_count=len(seqs), sequences=seqs,
                 note='frames and frame rates from the RSEQ animdesc; events, fades and loops from the QC block')
    (out / 'sequences').mkdir(parents=True, exist_ok=True)
    dump(out / 'sequences/ptpov_frag_grenade_held.json', table)
    dump(out / 'qc_metadata.json', dict(files=[dict(file=p, raw_qc=t) for p, (t, _) in qcs.items()]))
    models = []
    for target in selection['targets']:
        lod0 = oa.asset_file(out, 'cast', target['asset'], '.cast')
        lod0 = lod0.with_name(lod0.stem + '_LOD0.cast')
        model = next((n for n in nodes(lod0) if isinstance(n, Model)), None) if lod0.is_file() else None
        models.append(dict(role=target['role'], asset=target['asset'], lod0=oa.relpath(lod0, out) if model else None,
                           bone_count=len(model.Skeleton().Bones()) if model and model.Skeleton() else None,
                           meshes=len(model.Meshes()) if model else None,
                           materials=[by_guid[f'{m.Hash():016x}']['asset_name'] for m in model.Materials()] if model else []))
    dump(out / 'models.json', dict(models=models))
    summary = dict(sequences=len(seqs), with_qc=sum(1 for s in seqs if s['qc']),
                   toss_release=[(s['name'], e['frame'], s['blends'][0]['frame_count'], s['blends'][0]['framerate'])
                                 for s in seqs for b in s['qc'][:1] for e in b['events'] if e['event'] == 'AE_WPN_TOSS_RELEASE'],
                   models=[(m['role'], m['bone_count'], m['meshes']) for m in models])
    dump(out / 'verification.json', summary)
    return summary


def export(out: Path, exe: Path, retail: Path) -> dict:
    if not exe.is_file():
        raise FileNotFoundError(f'Existing RSX adapter required (no rebuild here): {exe}')
    for directory in ('lists', 'logs', 'sequences'):
        (out / directory).mkdir(parents=True, exist_ok=True)
    ea.OUT, ea.CACHE, ea.PACKAGES, ea.RUNS = out, out / 'logs/rsx_runtime', ['common.rpak'], []
    os.environ['MPLCONFIGDIR'] = str(ea.CACHE / 'matplotlib')
    ea.run(exe, 'core_named', 'cast', flags=['-metadataonly'])
    by_guid, by_name = oa.indexes(oa.list_rows(out))
    targets = targets_from_settings(retail)
    for t in targets:
        row = by_name.get(normal(t['asset_path']))
        if row is None:
            raise ValueError(f'待定: {t["asset_path"]} not in the local common.rpak')
        t['asset'] = row
    names = [t['asset']['asset_name'] for t in targets]
    exact = ['--exportexact', ','.join(names)]
    ea.run(exe, 'models_cast', 'cast', 'mdl_', flags=exact + ['-matltextures', '--format-matl', '2'])
    ea.run(exe, 'models_raw', 'raw', 'mdl_', flags=exact + ['--format-mdl_', '2'])
    pending = []
    targets, rigs, _ = oa.model_links(out, targets, by_guid, by_name, pending)
    materials = set()
    for t in targets:
        lod0 = oa.asset_file(out, 'cast', t['asset'], '.cast')
        lod0 = lod0.with_name(lod0.stem + '_LOD0.cast')
        model = next(n for n in nodes(lod0) if isinstance(n, Model))
        materials.update(by_guid[f'{m.Hash():016x}']['asset_name'] for m in model.Materials())
    if materials:
        mats = ','.join(sorted(materials))
        ea.run(exe, 'materials', 'cast', 'matl', flags=['--exportexact', mats, '--format-matl', '2', '-matltextures'])
        ea.run(exe, 'materials_dds', 'dds', 'matl', flags=['--exportexact', mats, '--format-matl', '2', '--format-txtr', '2', '-matltextures'])
    rig_names = [r['asset_name'] for r in rigs.values()]
    if rig_names:
        ea.run(exe, 'rigs_cast', 'cast', 'arig', flags=['--exportexact', ','.join(rig_names), '-exportrigsequences'])
        ea.run(exe, 'rigs_raw', 'raw', 'arig', flags=['--exportexact', ','.join(rig_names), '--format-arig', '2',
                                                      '--format-aseq', '2', '-exportrigsequences'])
    ea.run(exe, 'smd_qc', 'smd', 'mdl_,arig', flags=['--exportexact', ','.join(names + rig_names), '--format-mdl_', '3',
                                                    '--format-arig', '3', '--format-aseq', '3'])
    dump(out / 'export_selection.json', dict(task='U9', targets=targets, rigs=list(rigs.values()), pending=pending))
    dump(out / 'run_manifest.json', dict(runs=ea.RUNS, adapter=str(exe)))
    return analyze(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--rsx', type=Path, default=EXE)
    parser.add_argument('--retail', type=Path, default=RETAIL_WEAPON, help='retail export of mp_weapon_frag_grenade.txt')
    parser.add_argument('--analyze-only', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    if out.name != 'frag_grenade':
        raise ValueError(f'Output must be a frag_grenade directory of its own: {out}')
    out.mkdir(parents=True, exist_ok=True)
    report = analyze(out) if args.analyze_only else export(out, args.rsx, args.retail)
    print('U9 frag grenade export: ' + json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
