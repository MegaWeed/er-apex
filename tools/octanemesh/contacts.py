"""Locate T005 source-coincident contacts separately from split boundary duplicates."""
import numpy as np


def contact_report(parts, deformation):
    groups={}
    for part in parts:
        for mesh,posed in zip(parts[part],deformation[part]):
            for i,position in enumerate(mesh['source_positions']):
                key=tuple(np.rint(position*1e5).astype(int))
                groups.setdefault(key,[]).append(dict(part=part,mesh=mesh['name'],
                    source_vertex_id=int(mesh['source_vertex_ids'][i]),reference=mesh['positions'][i],posed=posed['positions'][i]))
    results=[]
    for vertices in groups.values():
        if len(vertices)<2:continue
        reference=np.array([v['reference'] for v in vertices]);posed=np.array([v['posed'] for v in vertices])
        results.append(dict(posed_gap_m=float(np.linalg.norm(np.ptp(posed,axis=0))),
            reference_gap_m=float(np.linalg.norm(np.ptp(reference,axis=0))),reference_midpoint_m=reference.mean(0).tolist(),
            vertices=[{k:v for k,v in vertex.items() if k not in ('reference','posed')} for vertex in vertices]))
    return dict(rule='T005 source coincident grouping rounded to 1e-5m; contact groups can already differ after alignment',
        groups=len(results),groups_posed_gap_gt_1mm=sum(v['posed_gap_m']>.001 for v in results),
        worst_groups=sorted(results,key=lambda v:-v['posed_gap_m'])[:10])
