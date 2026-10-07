"""Check model/node/mesh bounds against exported vertices, independent of the writer."""
import json, math
from pathlib import Path
from analyze_s2a import worlds

def inverse(matrix):
    a=[list(row)+[float(i==j) for j in range(4)] for i,row in enumerate(matrix)]
    for i in range(4):
        k=max(range(i,4),key=lambda k:abs(a[k][i]));a[i],a[k]=a[k],a[i]
        assert abs(a[i][i])>1e-12
        factor=a[i][i];a[i]=[x/factor for x in a[i]]
        for j in range(4):
            if j!=i:
                factor=a[j][i];a[j]=[x-factor*y for x,y in zip(a[j],a[i])]
    return [row[4:] for row in a]
def transform(m,p):return [sum(m[i][k]*p[k] for k in range(3))+m[i][3] for i in range(3)]
def xyz(v):return [v[k] for k in ['X','Y','Z']]
def verify(flver,doc,mesh_dir,arrays):
    names={n['Name']:n['Index'] for n in flver['Nodes']}; world=worlds(flver['Nodes']);inv=[inverse(world[n['Name']]) for n in flver['Nodes']]
    ranges=[[[math.inf]*3,[-math.inf]*3] for _ in flver['Nodes']];global_lo=[math.inf]*3;global_hi=[-math.inf]*3
    def include(r,p):
        for k in range(3):r[0][k]=min(r[0][k],p[k]);r[1][k]=max(r[1][k],p[k])
    def close(a,b):assert max(abs(x-y) for x,y in zip(a,b))<0.00005,(a,b)
    for mesh,s in zip(flver['Meshes'],doc['submeshes']):
        p=arrays(mesh_dir/s['positions']);cloth=arrays(mesh_dir/s['flver_cloth']['positions']) if s.get('flver_cloth') else None
        bi=(mesh_dir/s['bone_indices']).read_bytes();bw=arrays(mesh_dir/s.get('flver_bone_weights',s['bone_weights']));box=[[math.inf]*3,[-math.inf]*3]
        for i in range(s['vertex_count']):
            for vertices in ([p,cloth] if cloth else [p]):
                position=vertices[3*i:3*i+3];include(box,position)
                active={names[doc['bones'][bi[4*i+k]]] for k in range(4) if bw[4*i+k]>0}
                if mesh['NodeIndex']>=0:active.add(mesh['NodeIndex'])
                for node in active:include(ranges[node],transform(inv[node],position))
        include([global_lo,global_hi],box[0]);include([global_lo,global_hi],box[1])
        b=mesh['BoundingBox'];close(xyz(b['Min']),[(x-y)/2 for x,y in zip(box[1],box[0])]);close(xyz(b['Max']),[0,0,0]);close(xyz(b['Unk']),[(x+y)/2 for x,y in zip(box[1],box[0])])
    close(xyz(flver['Header']['BoundingBoxMin']),global_lo);close(xyz(flver['Header']['BoundingBoxMax']),global_hi)
    for node,r in zip(flver['Nodes'],ranges):
        if not math.isfinite(r[0][0]):r=[[0,0,0],[0,0,0]]
        close(node['BoundingBoxMin'],r[0]);close(node['BoundingBoxMax'],r[1])
    return dict(meshes=len(doc['submeshes']),nodes=len(flver['Nodes']),tolerance=0.00005,status='PASS')
