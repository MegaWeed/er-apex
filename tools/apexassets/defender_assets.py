"""T022 Charge Rifle Cast/raw/SMD/QC/textures and exact local provenance."""
import argparse
from pathlib import Path
import sys
sys.dont_write_bytecode=True
import weapons_assets_common as wc
OUT=wc.oa.REPO/'apex-data/assets/defender'
PREVIOUS=wc.oa.REPO/'apex-data/weapons/defender/pov'
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=OUT);p.add_argument('--analyze-only',action='store_true');a=p.parse_args()
    out=wc.checked(a.out,OUT)
    report=wc.analyze(out,PREVIOUS) if a.analyze_only else wc.export(out,[('defender_viewmodel','23125b0d4273152d')],PREVIOUS,'34b94a1efa946de5')
    print('PASS T022 defender export: '+wc.json.dumps(report,ensure_ascii=False),flush=True)
