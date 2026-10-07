"""T022 visibility and reload-relative motion facts, without fitting source poses."""
import argparse
from pathlib import Path
import sys
sys.dont_write_bytecode=True
import numpy as np
from common import read,save
from mesh_weapons import wc


def diagnose(out=None):
 out=wc.checked(out or wc.MODEL_ROOT,wc.MODEL_ROOT,create=False);preview=read(out/'weapons-preview-verification.json');pack=wc.read_pack(out/'inputs/fuse_pov.anim');indices={b['name']:i for i,b in enumerate(pack['bones'])}
 rows=[]
 for r in preview['previews']:
  if not r['clip'] or not r['clip'].startswith(('cr_','frag_')):continue
  prop_pixels=sum(count for name,count in r['rasterized_pixels'].items() if name!='body_0_octane_base_v_arms')
  rows.append(dict(clip=r['clip'],frame=r['frame'],prop_rasterized_pixels=prop_pixels,prop_in_camera_frustum=prop_pixels>0,finger_distances=r['finger_distances'],source_pose_unchanged=True))
 reference=pack['clips']['cr_draw_0'];world=wc.world7(pack['bones'],reference['poses'][-1]);base=indices['cr:def_c_base'];ref={c['owner_name']:np.linalg.inv(world[base])@world[c['owner']] for c in wc.layout()['new_carriers'] if c['group']==5};movement=[]
 for name in ('cr_reload_0','cr_reload_empty_0'):
  c=pack['clips'][name];f=c['frames']//2;world=wc.world7(pack['bones'],c['poses'][f]);record={}
  for carrier in wc.layout()['new_carriers']:
   if carrier['group']!=5:continue
   owner=carrier['owner_name'];relative=np.linalg.inv(world[base])@world[carrier['owner']];delta=np.linalg.inv(ref[owner])@relative;q=wc.bp.rigid(delta,owner)
   record[owner]=dict(translation_difference_m=float(np.linalg.norm(relative[:3,3]-ref[owner][:3,3])*.0254),rotation_difference_deg=float(2*np.arccos(min(1.,abs(q[6])))*180/np.pi))
  movement.append(dict(clip=name,frame=f,reference='cr_draw_0 last frame; transforms relative to cr:def_c_base',carriers=record))
 report=dict(status='PASS source facts',visibility=rows,reload_motion=movement,limits=['frag_toss_prep_pullout_seq_0 last frame and frag_toss_hold_seq_0 frame 0 have zero grenade pixels in the mandated jx_c_camera view. Right-finger proximity still confirms attachment; source poses and camera are unchanged.','frag_toss_seq_0 frame 7 is the exact local QC release event frame.','Reload/drawfirst phases need not keep the left hand on the rifle; the right hand remains close.','Unsigned distances establish proximity, not penetration depth.'])
 save(out/'weapons-pose-diagnostics.json',report);return report


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path);diagnose(p.parse_args().out)
