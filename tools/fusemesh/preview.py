"""Small orthographic z-buffer renderer; no Blender or GPU dependency."""
import numpy as np
from PIL import Image, ImageDraw
from geometry import unit

COLORS=dict(hd=(235,173,58),bd=(63,158,221),am=(228,91,122),lg=(82,181,116))


def render(path, parts, bones, matrices, title, yaw=0, textures=None):
    width,height=720,920
    theta=np.deg2rad(yaw)
    right=np.array([np.cos(theta),0,np.sin(theta)]);up=np.array([0.,1.,0.]);towards=np.cross(right,up)
    basis=np.stack([right,up,towards],axis=1)
    allp=np.concatenate([m['positions'] for meshes in parts.values() for m in meshes]);proj=allp@basis
    lo=proj[:,:2].min(0);hi=proj[:,:2].max(0);scale=min((width-80)/max(hi[0]-lo[0],.1),(height-150)/max(hi[1]-lo[1],.1))
    center=(lo+hi)/2
    def project(p):
        v=p@basis;v[:,0]=(v[:,0]-center[0])*scale+width/2;v[:,1]=-(v[:,1]-center[1])*scale+height/2+20
        return v
    rgb=np.full((height,width,3),(21,27,35),np.uint8);depth=np.full((height,width),-np.inf)
    light=unit(towards+np.array([-.2,.65,0]))
    for part,meshes in parts.items():
        for m in meshes:
            p=project(m['positions']);norm=m['normals'];f=m['indices'];tex=(textures or {}).get(m['material'])
            for face in f:
                v=p[face];xmin=max(0,int(np.floor(v[:,0].min())));xmax=min(width-1,int(np.ceil(v[:,0].max())))
                ymin=max(0,int(np.floor(v[:,1].min())));ymax=min(height-1,int(np.ceil(v[:,1].max())))
                if xmax<xmin or ymax<ymin:continue
                x,y=np.meshgrid(np.arange(xmin,xmax+1)+.5,np.arange(ymin,ymax+1)+.5)
                a,b,c=v;den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
                if abs(den)<1e-8:continue
                w0=((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/den
                w1=((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/den;w2=1-w0-w1
                z=w0*a[2]+w1*b[2]+w2*c[2];d=depth[ymin:ymax+1,xmin:xmax+1]
                mask=(w0>=0)&(w1>=0)&(w2>=0)&(z>d)
                if not mask.any():continue
                color=np.asarray(COLORS[part],float)
                if tex is not None:
                    uv=w0[...,None]*m['uv0'][face[0]]+w1[...,None]*m['uv0'][face[1]]+w2[...,None]*m['uv0'][face[2]]
                    tx=np.clip((uv[...,0]%1*tex.shape[1]).astype(int),0,tex.shape[1]-1);ty=np.clip((uv[...,1]%1*tex.shape[0]).astype(int),0,tex.shape[0]-1)
                    sample=tex[ty,tx];color=sample[...,:3].astype(float);mask &= sample[...,3]>=50
                brightness=.32+.68*max(0,float(np.dot(unit(norm[face].mean(0)),light)))
                region=rgb[ymin:ymax+1,xmin:xmax+1];colored=np.clip(color*brightness,0,255).astype(np.uint8)
                region[mask]=colored[mask] if colored.ndim==3 else colored;d[mask]=z[mask]
    im=Image.fromarray(rgb);draw=ImageDraw.Draw(im);bp=project(matrices[:,:3,3])
    # Core bones only, overlay intentional so hidden joints remain readable.
    core=lambda n: n in ('Pelvis','Spine','Spine1','Spine2','Neck','Head') or n.split('_')[-1] in ('Clavicle','UpperArm','Forearm','Hand','Thigh','Calf','Foot','Toe0')
    for i,b in enumerate(bones):
        j=b['ParentIndex']
        if j>=0 and core(b['Name']) and core(bones[j]['Name']):
            draw.line([tuple(bp[i,:2]),tuple(bp[j,:2])],fill=(244,246,247),width=2)
            x,y=bp[i,:2];draw.ellipse((x-2,y-2,x+2,y+2),fill=(255,255,255))
    draw.text((24,20),title,fill='white')
    for i,(part,color) in enumerate(COLORS.items()):draw.text((24+150*i,height-32),part.upper(),fill=color)
    im.save(path)


def posed(state,parts):
    ab,eb,ai,ei,A,P,E,Q,mapping,enabled,align=state
    local=np.stack([trs_from_world(i,eb,E) for i in range(len(eb))])
    def rotation(axis,angle):
        x,y,z=unit(axis);a=np.deg2rad(angle);c=np.cos(a);s=np.sin(a);k=1-c
        return np.array([[c+x*x*k,x*y*k-z*s,x*z*k+y*s],[y*x*k+z*s,c+y*y*k,y*z*k-x*s],[z*x*k-y*s,z*y*k+x*s,c+z*z*k]])
    # World anatomical bend axes are converted to the reference joint's local frame.
    rotations={}
    for name,axis,angle in [('L_Forearm',[0,0,1],90),('Head',[0,1,0],45),('R_Thigh',[1,0,0],60)]:
        i=ei[name];r=rotation(np.linalg.solve(E[i,:3,:3],np.array(axis)),angle)
        local[i,:3,:3]=local[i,:3,:3]@r;rotations[name]=dict(world_axis=axis,degrees=angle)
    F=np.zeros_like(E)
    for i,b in enumerate(eb):F[i]=(F[b['ParentIndex']] if b['ParentIndex']>=0 else np.eye(4))@local[i]
    D=F@np.linalg.inv(E);output={};maxdisp=0;maxedge=0;edge_ratios=[];seams={};welds={};worst_edges=[]
    for part,meshes in parts.items():
        output[part]=[]
        for m in meshes:
            sub=m.copy();bi=m['bone_indices'];bw=m['bone_weights'];p=m['positions'];n=m['normals'];v=np.zeros_like(p);nr=np.zeros_like(n)
            # Use exactly the largest-remainder 8-bit weights written by the builder.
            scaled=bw*255;ints=np.floor(scaled).astype(int);order=np.argsort(-(scaled-ints),axis=1,kind='stable')
            for i,left in enumerate(255-ints.sum(1)):ints[i,order[i,:left]]+=1
            weights=ints/255
            for k in range(4):
                v+=weights[:,k,None]*(np.einsum('nij,nj->ni',D[bi[:,k],:3,:3],p)+D[bi[:,k],:3,3])
                nr+=weights[:,k,None]*np.einsum('nij,nj->ni',D[bi[:,k],:3,:3],n)
            assert np.isfinite(v).all();sub['positions']=v;sub['normals']=unit(nr);output[part].append(sub)
            maxdisp=max(maxdisp,float(np.max(np.linalg.norm(v-p,axis=1))))
            f=m['indices'];edges=np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]]);old=np.linalg.norm(p[edges[:,0]]-p[edges[:,1]],axis=1);new=np.linalg.norm(v[edges[:,0]]-v[edges[:,1]],axis=1)
            maxedge=max(maxedge,float(new.max()));edge_ratios.extend((new[old>.002]/old[old>.002]).tolist())
            ratio=new/np.maximum(old,1e-12)
            candidates=np.flatnonzero((old>.002)&(ratio>2))
            for j in candidates[np.argsort(-ratio[candidates])[:5]]:
                worst_edges.append(dict(mesh=m['name'],part=part,ratio=float(ratio[j]),reference_length_m=float(old[j]),posed_length_m=float(new[j]),
                                        reference_midpoint=p[edges[j]].mean(0).tolist()))
            for j,sid in enumerate(m['source_vertex_ids']):seams.setdefault((m['source_mesh'],int(sid)),[]).append((part,v[j]))
            for j,p0 in enumerate(m['source_positions']):welds.setdefault(tuple(np.rint(p0*1e5).astype(int)),[]).append(v[j])
    gaps=[np.linalg.norm(a[1]-b[1]) for values in seams.values() for a in values for b in values if a[0]<b[0]]
    weld_gaps=[float(np.linalg.norm(np.ptp(np.array(values),axis=0))) for values in welds.values() if len(values)>1]
    return output,F,dict(rotations=rotations,finite=True,max_vertex_displacement_m=maxdisp,max_edge_m=maxedge,
                        edge_stretch_quantiles={str(q):float(np.quantile(edge_ratios,q)) for q in [.5,.95,.99,1]},
                        split_duplicate_pairs=len(gaps),max_duplicate_gap_m=float(max(gaps,default=0)),
                        opened_duplicate_pairs_gt_1mm=int(sum(g>.001 for g in gaps)),source_coincident_groups=len(weld_gaps),
                        max_source_coincident_gap_m=max(weld_gaps,default=0),worst_stretched_edges=sorted(worst_edges,key=lambda x:-x['ratio'])[:10])


def trs_from_world(i,bones,E):
    p=bones[i]['ParentIndex']
    return np.linalg.inv(E[p])@E[i] if p>=0 else E[i].copy()
