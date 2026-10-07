"""T021 direct byte comparison of complete outputs from clean directories; no digests."""
import argparse
import sys
from pathlib import Path
sys.dont_write_bytecode = True
from common import ROOT,save,read
from mesh_battery import bc


def compare(left,right,files):
    for rel in files:
        bc.require((left/rel).read_bytes()==(right/rel).read_bytes(),f'Reproduction changed {rel}')
    return len(files)


def verify(repro,pack_repro=None,asset_repro=None):
    repro=bc.checked(repro,bc.MODEL_ROOT,create=False);report=dict(status='PASS',direct_content=True,model={})
    for directory,pattern in [('package','*.dcx'),('fusemesh','*'),('textures','*.png'),('inputs/live-templates','*.dcx'),('preview','*.png')]:
        files=[p.relative_to(bc.MODEL_ROOT) for p in (bc.MODEL_ROOT/directory).rglob(pattern) if p.is_file()]
        actual=[p.relative_to(repro) for p in (repro/directory).rglob(pattern) if p.is_file()]
        bc.require(set(actual)==set(files),f'Reproduction inventory differs: {directory}')
        report['model'][directory]=compare(bc.MODEL_ROOT,repro,files)
    for rel in ('inputs/fuse_pov.anim','inputs/battery_sequences.json'):
        compare(bc.MODEL_ROOT,repro,[Path(rel)])
    if pack_repro:
        pack_repro=bc.checked(pack_repro,bc.PACK_ROOT,create=False)
        report['pack']=compare(bc.PACK_ROOT,pack_repro,[Path('fuse_pov.anim'),Path('battery_sequences.json')])
    if asset_repro:
        asset_repro=bc.checked(asset_repro,bc.ASSETS,create=False);counts={}
        for directory in ('cast','raw','smd','dds','skeletons','sequences'):
            files=[p.relative_to(bc.ASSETS) for p in (bc.ASSETS/directory).rglob('*') if p.is_file()]
            actual=[p.relative_to(asset_repro) for p in (asset_repro/directory).rglob('*') if p.is_file()]
            bc.require(set(actual)==set(files),'Asset reproduction inventory differs')
            counts[directory]=compare(bc.ASSETS,asset_repro,files)
        report['assets']=counts
    save(bc.MODEL_ROOT/'battery-reproducibility.json',report)
    print('PASS T021 clean reproduction: '+str(report),flush=True)
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repro',type=Path,required=True)
    parser.add_argument('--pack-repro',type=Path);parser.add_argument('--asset-repro',type=Path)
    args=parser.parse_args();verify(args.repro,args.pack_repro,args.asset_repro)
