"""Mastiff (`mp_weapon_mastiff`) Cast/raw/SMD/QC/textures and exact local provenance (the
Wingman's export): its default view model `mastiff_base_v` on `mastiff_base_v_animRig.rrig` and its
sequences."""
import argparse
from pathlib import Path
import sys
sys.dont_write_bytecode=True
import weapons_assets_common as wc
OUT=wc.oa.REPO/'apex-data/assets/mastiff'
# no earlier Mastiff export: the comparison finds nothing and lists every file as added
PREVIOUS=wc.oa.REPO/'apex-data/weapons/mastiff/pov'
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=OUT);p.add_argument('--analyze-only',action='store_true');a=p.parse_args()
    out=wc.checked(a.out,OUT)
    report=wc.analyze(out,PREVIOUS) if a.analyze_only else wc.export(out,[('mastiff_viewmodel','ad266c2de7d2180f')],PREVIOUS,'7c1acd873593a4d6')
    print('PASS mastiff export: '+wc.json.dumps(report,ensure_ascii=False),flush=True)
