"""T022 direct content comparison of empty-directory reproductions, without hashes."""
import argparse
from pathlib import Path
import sys
sys.dont_write_bytecode=True
from common import read,save
from mesh_weapons import wc


def compare_tree(primary,repro,folders):
 counts={}
 for folder in folders:
  source=primary/folder;copy=repro/folder
  paths=sorted(p.relative_to(source) for p in source.rglob('*') if p.is_file())
  other=sorted(p.relative_to(copy) for p in copy.rglob('*') if p.is_file())
  wc.require(paths==other,f'Reproduction file inventory differs: {folder}')
  for p in paths:wc.require((source/p).read_bytes()==(copy/p).read_bytes(),f'Reproduction bytes differ: {folder}/{p}')
  counts[folder]=len(paths)
 return counts


def normalize(value,primary,repro):
 if isinstance(value,str):return value.replace(str(repro),str(primary)).replace(repro.as_posix(),primary.as_posix())
 if isinstance(value,list):return [normalize(v,primary,repro) for v in value]
 if isinstance(value,dict):return {k:normalize(v,primary,repro) for k,v in value.items() if k!='elapsed_seconds'}
 return value


def verify(repro=None,pack_repro=None,defender_repro=None,frag_repro=None):
 repro=wc.checked(repro or wc.MODEL_ROOT/'repro_clean',wc.MODEL_ROOT,create=False)
 pack_repro=wc.checked(pack_repro or wc.PACK_ROOT/'repro_clean',wc.PACK_ROOT,create=False)
 result=dict(status='PASS',model=compare_tree(wc.MODEL_ROOT,repro,['package/parts','package/material','fusemesh','textures','inputs/live-templates','preview']),assets={})
 for filename in ('fuse_pov.anim','defender_sequences.json','frag_sequences.json','weapons_carriers.json'):
  wc.require((wc.PACK_ROOT/filename).read_bytes()==(pack_repro/filename).read_bytes(),f'Pack reproduction differs: {filename}')
 result['pack_files_byte_identical']=4
 for filename in ('weapons-mesh-summary.json','weapons-texture-audit.json','weapons-template-audit.json','material-bundle-audit.json','weapons-readback-verification.json','weapons-preview-verification.json','weapons-verification.json','package/build-manifest.json'):
  a=read(wc.MODEL_ROOT/filename);b=read(repro/filename);wc.require(normalize(a,wc.MODEL_ROOT,repro)==normalize(b,wc.MODEL_ROOT,repro),f'Reproduction audit differs: {filename}')
 result['audits_equal_except_output_paths_and_elapsed']=8
 for key,root,explicit in [('defender',wc.CONFIGS['cr']['assets'],defender_repro),('frag',wc.CONFIGS['frag']['assets'],frag_repro)]:
  copy=wc.checked(explicit or root/'repro_clean',root,create=False)
  result['assets'][key]=compare_tree(root,copy,['cast','raw','smd','dds','skeletons','sequences'])
 save(wc.MODEL_ROOT/'weapons-reproducibility.json',result);print('PASS T022 empty-directory reproduction: '+str(result),flush=True);return result


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repro',type=Path);p.add_argument('--pack-repro',type=Path);p.add_argument('--defender-repro',type=Path);p.add_argument('--frag-repro',type=Path);a=p.parse_args();verify(a.repro,a.pack_repro,a.defender_repro,a.frag_repro)
