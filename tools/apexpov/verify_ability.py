"""T020: read FPOV v2 again; verify baseline bytes and local Cast/QC/model data."""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import numpy as np
from ability_common import (ROOT, PACK_ROOT, BASE_PACK, CONFIGS, bp, checked, save,
    require, read_pack, selected, model_world, read_qc, decode_source, world7)
from bake_ability import generate


def verify(out=None, write_report=True):
    out = checked(out or PACK_ROOT, PACK_ROOT, create=False)
    actual, base = read_pack(out/'fuse_pov.anim'), read_pack(BASE_PACK)
    require(actual['version'] == 2, 'Expected FPOV v2')
    from ability_common import live_skeleton, forbidden_prop_carrier, XTRA_NAMES
    live_names = {b['name'] for b in live_skeleton()['bones']}
    require(all(c['name'] in live_names for c in actual['carrier_records']), 'Carrier name missing from live skeleton')
    require(all(c['name'] in XTRA_NAMES and not forbidden_prop_carrier(c['name']) for c in actual['carrier_records'][51:]), 'Forbidden prop carrier')
    require(actual['camera'] == base['camera'], 'Camera changed')
    require([b['raw'] for b in actual['bones'][:102]] == [b['raw'] for b in base['bones']], 'Old bone bytes changed')
    require([c['raw'] for c in actual['carrier_records'][:51]] == [c['raw'] for c in base['carrier_records']], 'Old v1 carrier bytes changed')
    require(list(actual['clips'])[:39] == list(base['clips']), 'Old clip order changed')
    for name, c in base['clips'].items():
        new = actual['clips'][name]
        require(new['header'] == c['header'] and new['weights'][:102].tobytes() == c['weights'].tobytes()
                and new['poses'][:, :102].tobytes() == c['poses'].tobytes(), f'{name}: old clip bytes changed')
        require(not new['weights'][102:].any(), f'{name}: new bone weight')
        default = np.tile([0, 0, 0, 0, 0, 0, 1], (len(actual['bones'])-102, 1)) if c['additive'] else [b['rest'] for b in actual['bones'][102:]]
        require(np.array_equal(new['poses'][:, 102:], np.broadcast_to(np.asarray(default, '<f4'), new['poses'][:, 102:].shape)), f'{name}: wrong extended pose')
    expected, table, audit = generate()
    require(list(actual['clips']) == list(expected['clips']), 'Clip inventory/order differs')
    require(len(actual['bones']) == len(expected['bones']) and len(actual['carrier_records']) == len(expected['carrier_records']), 'New counts differ')
    for a, b in zip(actual['bones'], expected['bones']):
        require(a['name'] == b['name'] and a['parent'] == b['parent'] and np.array_equal(a['rest'], np.asarray(b['rest'], '<f4')), f'Bone differs: {a["name"]}')
    for a, b in zip(actual['carrier_records'], expected['carrier_records']):
        require((a['name'], a['owner'], a['group']) == (b['name'], b['owner'], b['group']), f'Carrier differs: {a["name"]}')
        for field in ('inverse_mesh_bind', 'er_bind'):
            require(np.array_equal(a[field], np.asarray(b[field], '<f4')), f'Carrier {field} differs: {a["name"]}')
    for name, a in actual['clips'].items():
        b = expected['clips'][name]
        require(all(a[k] == b[k] for k in ('fps', 'frames', 'loop', 'additive')), f'Clip header differs: {name}')
        require(a['poses'].tobytes() == b['poses'].astype('<f4').tobytes() and a['weights'].tobytes() == b['weights'].astype('<f4').tobytes(), f'Clip values differ: {name}')
    require(json.loads((out/'ability_sequences.json').read_text(encoding='utf8')) == table, 'Sequence metadata/QC events differ')
    index = {b['name']: i for i, b in enumerate(actual['bones'])}
    max_source_world_error = 0.
    for key, config in CONFIGS.items():
        mdl, meshes = selected(key)
        binds = model_world(mdl)
        rig = bp.skeleton(config['rig']); qc = read_qc(config['qc'])
        copies = {b['source_bone']: index[b['name']] for b in audit['added_bones'] if b['rig'] == key}
        for carrier in actual['carrier_records'][51:]:
            if carrier['group'] != config['group']:
                continue
            owner = actual['bones'][carrier['owner']]['name']
            require(carrier['owner'] >= 102, f'Prop carrier uses old owner: {owner}')
            source_name = next(b['source_bone'] for b in audit['added_bones'] if b['name'] == owner)
            expected_bind = bp.rigid(np.linalg.inv(binds[source_name]), owner).astype('<f4')
            require(np.array_equal(expected_bind, carrier['inverse_mesh_bind']), f'Inverse mesh bind differs: {owner}')
        for row in [r for r in table['clips'] if r['rig'] == key]:
            a = actual['clips'][row['name']]
            seq = qc['sequences'][row['sequence']]
            source = decode_source(ROOT/row['source']['path'], rig, seq, qc)
            for n in copies:
                if n in index and index[n] < 102:
                    require(not a['weights'][index[n]].any(), f'{row["name"]}: copied pack bone has weight {n}')
            # Independent source FK checks all prop bones and parent changes.
            # For deltas, compare raw local channels when parent topology agrees.
            for si, b in enumerate(rig):
                dest = copies.get(b['name'], index.get(b['name']))
                if dest is None:
                    continue
                require(np.array_equal(a['weights'][dest], source['weights'][si].astype('<f4')), f'{row["name"]}: source weight {b["name"]}')
                if not audit['parent_differences']:
                    require(np.array_equal(a['poses'][:, dest], source['poses'][:, si].astype('<f4')), f'{row["name"]}: source local {b["name"]}')
            if not source['additive']:
                for f in (0, source['frames']-1):
                    sw = world7(rig, source['poses'][f])
                    tw = world7(actual['bones'], a['poses'][f])
                    for si, b in enumerate(rig):
                        dest = copies.get(b['name'], index.get(b['name']))
                        if dest is not None:
                            max_source_world_error = max(max_source_world_error, float(np.max(abs(sw[si]-tw[dest]))))
    require(max_source_world_error < 2e-4, 'Source/pack FK differs')
    report = dict(status='PASS', version=2, bones=len(actual['bones']), carriers=len(actual['carrier_records']),
        clips=len(actual['clips']), source_bytes_unchanged=dict(bones=102, carriers_v1_fields=51, clips=39),
        cast_qc_clips_checked=len(table['clips']), prop_owners_all_new=True, copied_pack_bones_zero_weight=True,
        inverse_mesh_binds_exact=True, new_bones_and_values_exact=True, events_frames_times_exact=True,
        max_source_world_matrix_error=max_source_world_error, duplicates_kept=audit['duplicate_clips_kept'],
        all_69_carriers_in_live_skeleton=True, prop_carriers_only_live_xtra=True)
    if write_report:
        save(out/'ability-pack-verification.json', report)
    print(f'PASS T020 pack: baseline 102 bones / 51 carriers / 39 clips byte-identical; '
          f'{len(table["clips"])} Cast/QC samples checked; all prop owners new; FK error {max_source_world_error:.3g}', flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    verify(parser.parse_args().out)
