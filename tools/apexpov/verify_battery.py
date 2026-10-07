"""T021 pack readback: old byte ranges, local Cast/QC/RSEQ and carrier bindings."""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import numpy as np
import battery_common as bc
from bake_battery import generate


def verify(out=None, write_report=True, pack_path=None, sequence_path=None):
    out = bc.checked(out or bc.PACK_ROOT,bc.PACK_ROOT,create=False) if pack_path is None else Path(out)
    actual = bc.read_pack(pack_path or out/'fuse_pov.anim'); base = bc.read_pack(bc.BASE_PACK)
    old = len(base['bones']); nc = len(base['carrier_records'])
    req = bc.require
    req(actual['camera'] == base['camera'], 'Camera changed')
    req([b['raw'] for b in actual['bones'][:old]] == [b['raw'] for b in base['bones']], 'T020 bone bytes changed')
    req([c['raw_v2'] for c in actual['carrier_records'][:nc]] == [c['raw_v2'] for c in base['carrier_records']], 'T020 carrier/group bytes changed')
    req(list(actual['clips'])[:len(base['clips'])] == list(base['clips']), 'T020 clip order changed')
    for name,c in base['clips'].items():
        new = actual['clips'][name]
        req(new['header'] == c['header'] and new['weights'][:old].tobytes() == c['weights'].tobytes() and
            new['poses'][:,:old].tobytes() == c['poses'].tobytes(), f'T020 clip bytes changed: {name}')
        req(not new['weights'][old:].any(), 'Extended bones must be masked')
        default = np.tile([0,0,0,0,0,0,1],(len(actual['bones'])-old,1)) if c['additive'] else [b['rest'] for b in actual['bones'][old:]]
        req(np.array_equal(new['poses'][:,old:],np.broadcast_to(np.asarray(default,'<f4'),new['poses'][:,old:].shape)), 'Wrong extended poses')
    expected,table,audit = generate()
    req(list(actual['clips']) == list(expected['clips']), 'Clip inventory changed')
    req(len(actual['bones']) == len(expected['bones']) and len(actual['carrier_records']) == len(expected['carrier_records']), 'Wrong counts')
    for a,b in zip(actual['bones'],expected['bones']):
        req(a['name'] == b['name'] and a['parent'] == b['parent'] and np.array_equal(a['rest'],np.asarray(b['rest'],'<f4')), 'Bone differs from local rig')
    live = {b['name'] for b in bc.ac.live_skeleton()['bones']}
    for a,b in zip(actual['carrier_records'],expected['carrier_records']):
        req((a['name'],a['owner'],a['group']) == (b['name'],b['owner'],b['group']), 'Carrier identity differs')
        req(a['name'] in live, 'Carrier missing in live skeleton')
        for k in ('inverse_mesh_bind','er_bind'):
            req(np.array_equal(a[k],np.asarray(b[k],'<f4')), f'Carrier bind differs: {a["name"]}/{k}')
    for name,a in actual['clips'].items():
        b = expected['clips'][name]
        req(all(a[k] == b[k] for k in ('fps','frames','loop','additive')), f'Clip header differs: {name}')
        req(a['poses'].tobytes() == b['poses'].astype('<f4').tobytes() and a['weights'].tobytes() == b['weights'].astype('<f4').tobytes(),f'Clip values differ: {name}')
    req(json.loads(Path(sequence_path or out/'battery_sequences.json').read_text(encoding='utf8')) == table, 'Sequence/QC events differ')
    data = bc.layout(); rig = data['sources']['battery']; mapping = data['maps']['battery']; mdl,_,_ = bc.selected()
    binds = bc.model_world(mdl); max_error=0.; qc=bc.read_qc(bc.CONFIG['qc'])
    other_props = [b['index'] for b in json.loads((bc.ac.PACK_ROOT/'ability-pack-audit.json').read_text())['added_bones']]
    for c in actual['carrier_records'][nc:]:
        req(c['owner'] >= old and c['group'] == 4, 'Battery carrier uses old owner/group')
        source = next(b['source_bone'] for b in audit['added_bones'] if b['index'] == c['owner'])
        req(np.array_equal(c['inverse_mesh_bind'],bc.bp.rigid(np.linalg.inv(binds[source]),source).astype('<f4')), 'Wrong model inverse bind')
    for row in table['clips']:
        a = actual['clips'][row['name']]
        req(not a['weights'][other_props].any(), 'Injector/jump pad has battery weight')
        source = bc.decode_source(bc.ROOT/row['source']['path'],rig,qc['sequences'][row['sequence']],qc)
        for si,b in enumerate(rig):
            if b['name'] not in mapping: continue
            dest=mapping[b['name']]
            req(np.array_equal(a['weights'][dest],source['weights'][si].astype('<f4')), 'QC weight differs')
            if not any(not d.get('copied_for_battery') for d in data['parent_differences']):
                req(np.array_equal(a['poses'][:,dest],source['poses'][:,si].astype('<f4')), 'Cast local differs')
        if not a['additive']:
            for f in (0,a['frames']-1):
                sw=bc.world7(rig,source['poses'][f]); tw=bc.world7(actual['bones'],a['poses'][f])
                for si,b in enumerate(rig):
                    if b['name'] in mapping: max_error=max(max_error,float(abs(sw[si]-tw[mapping[b['name']]]).max()))
    req(max_error < 2e-4,'Battery FK differs')
    report=dict(status='PASS',version=2,bones=len(actual['bones']),carriers=len(actual['carrier_records']),clips=len(actual['clips']),
        baseline_byte_identical=dict(bones=old,carriers_including_group=nc,clips=len(base['clips'])),battery_samples=len(table['clips']),
        battery_carrier_owners_new=True,injector_jumppad_weights_zero=True,extended_old_clips_masked=True,
        cast_qc_rseq_values_exact=True,events_frames_times_exact=True,carrier_binds_exact=True,all_carriers_live=True,max_source_fk_error=max_error)
    if write_report: bc.save(out/'battery-pack-verification.json',report)
    print(f'PASS T021 pack: T020 {old} bones / {nc} carriers (group included) / {len(base["clips"])} clips byte-identical; {len(table["clips"])} Cast/QC/RSEQ samples; FK {max_error:.3g}',flush=True)
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--out',type=Path)
    verify(parser.parse_args().out)
