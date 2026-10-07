"""T022 frag held view model and projectile, all local formats and provenance."""
import argparse
from pathlib import Path
import sys
sys.dont_write_bytecode=True
import weapons_assets_common as wc
OUT=wc.oa.REPO/'apex-data/assets/frag'
PREVIOUS=wc.oa.REPO/'apex-data/assets/frag_grenade'
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=OUT);p.add_argument('--analyze-only',action='store_true');a=p.parse_args()
    out=wc.checked(a.out,OUT)
    report=wc.analyze(out,PREVIOUS) if a.analyze_only else wc.export(out,[('frag_viewmodel','667da704f5a37052'),('frag_projectile','802e433a92d565c1')],PREVIOUS)
    print('PASS T022 frag export: '+wc.json.dumps(report,ensure_ascii=False),flush=True)
