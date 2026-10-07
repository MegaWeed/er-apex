"""Column-vector skeleton alignment and full-influence rest-pose skinning."""
import json
from pathlib import Path
import numpy as np
from cast import Cast, Model

PARTS = ('hd', 'bd', 'am', 'lg')
MODELS = dict(hd=1280, bd=1280, am=1500, lg=1280)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def trs(t, q, scale):
    x, y, z, w = unit(q)
    m = np.eye(4)
    m[:3, :3] = np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                          [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                          [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]) @ np.diag(scale[:3])
    m[:3, 3] = t[:3]
    return m


def world(bones, local, parent):
    result = {}; active = set()
    def visit(i):
        if i in result: return result[i]
        if i in active: raise ValueError('Cyclic skeleton')
        active.add(i); p = parent(bones[i])
        result[i] = (visit(p) if p >= 0 else np.eye(4)) @ local(bones[i])
        active.remove(i); return result[i]
    return np.stack([visit(i) for i in range(len(bones))])


def frame(primary, secondary):
    x = unit(primary); y = secondary - x * np.dot(x, secondary)
    if np.linalg.norm(y) < 1e-6:
        # Deterministic least-parallel global axis for degenerate terminal frames.
        secondary = np.eye(3)[np.argmin(abs(x))]; y = secondary - x*np.dot(x, secondary)
    y = unit(y)
    return np.stack([x, y, np.cross(x, y)], axis=1)


def octane_owner_map(root, bones):
    """Reuse Fuse by name only; new helpers inherit their nearest owned ancestor."""
    original = read(root/'er-data/s2b/mapping-v0.json')
    names = {b['name']: i for i, b in enumerate(bones)}
    existing = {o['source']: o for o in original['source_owners']}
    pairs = [p.copy() for p in original['mapping'] if p['source'] in names]
    missing = [dict(source=p['source'], target=p['target']) for p in original['mapping'] if p['source'] not in names]
    new_names = {'def_r_'+n+'_shock' for n in ('thigh','knee','ankle','ball')} | {'def_l_camera','def_r_pack','def_l_pouch'} | {'def_loc_collar'+str(n) for n in range(9)}
    assert len(bones) == 87 and len(pairs) == 60 and missing == [dict(source='def_c_jawA',target='Jaw')]
    assert set(names)-set(existing) == new_names and len(set(names)&set(existing)) == 71
    records = []
    for i, b in enumerate(bones):
        j = i; chain = []
        while bones[j]['name'] not in existing:
            chain.append(bones[j]['name']); j = bones[j]['parent_index']
            if j < 0: raise ValueError('No owner ancestor for '+b['name'])
        entry = existing[bones[j]['name']]
        parent = bones[b['parent_index']]['name'] if b['parent_index'] >= 0 else None
        if b['name'] in new_names:
            expected = b['name'].removesuffix('_shock') if b['name'].endswith('_shock') else 'def_c_hip' if b['name'] in ('def_r_pack','def_l_pouch') else 'def_c_spineC'
            assert parent == expected, (b['name'],parent,expected)
        records.append(dict(source=b['name'],apex_index=i,parent=parent,target=entry['target'],
            rule='fuse_same_name' if i == j else 'nearest_ancestor_with_fuse_owner',
            owner_ancestor=bones[j]['name'],ancestor_distance=len(chain),ancestor_chain=chain+[bones[j]['name']],
            fuse_rule=entry['rule']))
    for p in pairs: p['apex_index'] = names[p['source']]
    mapping = dict(mapping=pairs,source_owners=records)
    report = dict(format='octane-owner-map',version=1,
        source_skeleton=str(root/'apex-data/assets/octane/skeletons/pilot_medium_stim.json'),
        source_owner_map=str(root/'er-data/s2b/mapping-v0.json'),source_bones=87,
        inherited_by_name=71,inherited_by_ancestor=16,mapped_pairs=60,missing_mapping=missing,bones=records)
    return mapping, report


def loss_statistics(values):
    values = np.asarray(values, dtype=float)
    return dict(max=float(values.max()),mean=float(values.mean()),vertices=len(values),
        vertices_loss_gt_1e_8=int((values>1e-8).sum()),
        quantiles={str(q):float(np.quantile(values,q)) for q in [0,.5,.9,.95,.99,.999,1]})


def alignment(root):
    apex = read(root/'apex-data/assets/octane/skeletons/pilot_medium_stim.json'); ab = apex['bones']
    er = read(root/'er-data/json/c0000_skeleton.json'); eb = er['Bones']
    mapping, owner_report = octane_owner_map(root, ab); pairs = mapping['mapping']
    ai = {b['name']:i for i,b in enumerate(ab)}; ei = {b['Name']:i for i,b in enumerate(eb)}
    raw = world(ab, lambda b:trs(b['local_position'], b['local_rotation_xyzw'], b['local_scale']), lambda b:b['parent_index'])
    E = world(eb, lambda b:trs(b['Translation'], b['Rotation'], b['Scale']), lambda b:b['ParentIndex'])
    ap = raw[:, :3, 3]; ep = E[:, :3, 3]
    evidence = dict(apex_units_metadata=apex['units'], source_to_meters_status='inference from local exporter s_MetersToInches and pelvis 39.37 source units',
                    apex_toe_delta=(ap[ai['def_l_ball']]-ap[ai['def_l_ankle']]).tolist(),
                    er_toe_delta=(ep[ei['L_Toe0']]-ep[ei['L_Foot']]).tolist(),
                    apex_left_right_ankle=(ap[ai['def_l_ankle']]-ap[ai['def_r_ankle']]).tolist(),
                    er_left_right_foot=(ep[ei['L_Foot']]-ep[ei['R_Foot']]).tolist(),
                    apex_middle_finger_delta=(ap[ai['def_l_finMidC']]-ap[ai['def_l_wrist']]).tolist(),
                    er_middle_finger_delta=(ep[ei['L_Finger22']]-ep[ei['L_Hand']]).tolist())
    evidence['face_forward_status']='Octane has no jaw or lip joints; head uses semantic up and forward, with Z sign evidenced by feet'
    evidence['apex_head_neck_delta']=(ap[ai['def_c_head']]-ap[ai['def_c_neckB']]).tolist()
    assert evidence['apex_toe_delta'][2] > 0 and evidence['er_toe_delta'][2] < 0
    assert evidence['apex_left_right_ankle'][0] > 0 and evidence['er_left_right_foot'][0] > 0
    # Reflection conjugates both world and bone-local bases, preserving proper bone rotations.
    C = np.diag([.0254, .0254, -.0254, 1.]); s = ep[ei['Pelvis'],1]/(.0254*ap[ai['def_c_hip'],1])
    Q = C.copy(); Q[:3,:3] *= s
    A = Q @ raw @ np.linalg.inv(Q)
    target_source = {p['target']:p['source'] for p in pairs}; source_target = {v:k for k,v in target_source.items()}
    # Endpoints represent the anatomical segment rather than arbitrary twist/helper children.
    children = dict(Master='RootPos', RootPos='Pelvis', Pelvis='Spine', Spine='Spine1', Spine1='Spine2', Spine2='Neck', Neck='Head')
    for side in ('L','R'):
        for a,b in [('Clavicle','UpperArm'),('UpperArm','Forearm'),('UpArmTwist','Forearm'),('Forearm','Hand'),('ForeArmTwist','Hand'),('Hand','Finger2'),('Thigh','Calf'),('Calf','Foot'),('Foot','Toe0')]:
            children[side+'_'+a] = side+'_'+b
        for digit in range(5):
            children[f'{side}_Finger{digit}'] = f'{side}_Finger{digit}1'
            children[f'{side}_Finger{digit}1'] = f'{side}_Finger{digit}2'
    positions_a = {t:A[ai[n],:3,3] for t,n in target_source.items()}; positions_e = {t:ep[ei[t]] for t in target_source}
    def axes(t, pos, is_apex):
        side = t[:1] if t.startswith(('L_','R_')) else None
        child = children.get(t)
        if t in ('Master','RootPos','Pelvis','Spine','Spine1','Spine2','Neck','Head','Jaw'):
            # Head/Jaw semantic up avoids Apex/ER Jaw placement changing skull orientation.
            primary = pos[child]-pos[t] if child and t not in ('Master','Head') else np.array([0.,1.,0.])
            if np.linalg.norm(primary)<1e-5: primary=np.array([0.,1.,0.])
            return primary, np.array([0.,0.,-1.]), 'spine/head up-chain; secondary anatomical forward -Z'
        if side and any(k in t for k in ('Clavicle','Arm','Hand','Finger','Weapon')):
            hand=pos[side+'_Hand']; mid=pos[side+'_Finger2']; pinky=pos[side+'_Finger4']; thumb=pos[side+'_Finger0']
            palm=unit(np.cross(mid-hand, pinky-thumb))
            if child: primary=pos[child]-pos[t]
            elif 'Finger' in t:
                parent=t[:-1] if t[-1]=='2' else side+'_Hand'; primary=pos[t]-pos[parent]
            else: primary=mid-hand
            return primary,palm,'arm/finger segment; secondary palm normal cross(hand->middle, thumb->pinky)'
        if side:
            primary=pos[child]-pos[t] if child else pos[t]-pos[side+'_Foot']
            secondary=np.array([1.,0.,0.]) if any(k in t for k in ('Foot','Toe')) else np.array([0.,0.,-1.])
            return primary,secondary,'leg segment; secondary forward -Z; foot/toe secondary lateral +X'
        raise ValueError(t)
    P = np.zeros_like(A); records = []; aligned={}
    for t,n in target_source.items():
        i=ai[n]; aa,sa,rule=axes(t,positions_a,True); ae,se,_=axes(t,positions_e,False)
        D=frame(ae,se) @ frame(aa,sa).T
        p=np.eye(4); p[:3,:3]=D @ A[i,:3,:3]; p[:3,3]=ep[ei[t]]; aligned[i]=p
        records.append(dict(er_bone=t,owner_apex_bone=n,apex_index=i,er_index=ei[t],method=rule,
                            source_primary=unit(aa).tolist(),target_primary=unit(ae).tolist(),
                            source_secondary=unit(sa).tolist(),target_secondary=unit(se).tolist(),
                            P=p.tolist(),E=E[ei[t]].tolist(),O_b=(np.linalg.inv(p)@E[ei[t]]).tolist()))
    def follow(i):
        if i in aligned:return aligned[i]
        parent=ab[i]['parent_index']
        if parent<0:raise ValueError('Unowned root')
        aligned[i]=follow(parent) @ np.linalg.inv(A[parent]) @ A[i]
        return aligned[i]
    P=np.stack([follow(i) for i in range(len(ab))]); error=max(np.linalg.norm(P[ai[n],:3,3]-ep[ei[t]]) for t,n in target_source.items())
    enabled={}; template_errors={}
    for part in PARTS:
        d=read(root/f'er-data/json/parts/{part.upper()}_M_{MODELS[part]}.json'); nodes=d['Nodes']
        enabled[part]=set(b['Name'] for b in nodes if 'Bone' in b['Flags'] and 'Disabled' not in b['Flags'])
        F=world(nodes,lambda b:trs(b['Translation'],b['RotationQuaternion'],b['Scale']),lambda b:b['ParentIndex'])
        template_errors[part]=float(max(np.max(abs(F[i]-E[ei[b['Name']]])) for i,b in enumerate(nodes) if b['Name'] in enabled[part] and b['Name'] in ei))
    result=dict(format='fuse-align',version=1,matrix_convention='column_vectors_parent_world_at_local_TRS',axis_unit_matrix=C.tolist(),
                scaled_axis_unit_matrix=Q.tolist(),uniform_scale=s,source_unit_meters=.0254,reflection_axis='Z',
                local_basis_rule='A=Q @ A_original @ inverse(Q); vertex=Q @ vertex_original',
                mapped_bones=records,apex_aligned_world=P.tolist(),apex_rest_er_space=A.tolist(),
                max_joint_position_error_m=float(error),enabled_template_world_max_error=template_errors,coordinate_evidence=evidence,
                source_character='Octane', source_bone_names=[b['name'] for b in ab], owner_map=owner_report,
                missing_mapping=owner_report['missing_mapping'], head_alignment='def_c_head -> Head; primary +Y, secondary -Z; no jaw substitute')
    return ab,eb,ai,ei,A,P,E,Q,mapping,enabled,result


def winding(p,n,f):
    cross=np.cross(p[f[:,1]]-p[f[:,0]],p[f[:,2]]-p[f[:,0]])
    area=np.linalg.norm(cross,axis=1); dot=(cross*n[f].mean(1)).sum(1)
    valid=area>1e-12; along=valid&(dot>area*1e-5); against=valid&(dot<-area*1e-5)
    return dict(along=int(along.sum()),against=int(against.sum()),degenerate=int((~valid).sum()),orthogonal=int((valid&~along&~against).sum()))


def tangent_basis(p,n,uv,f):
    dp=p[f[:,1:]]-p[f[:,0,None]]; du=uv[f[:,1:]]-uv[f[:,0,None]]
    det=du[:,0,0]*du[:,1,1]-du[:,0,1]*du[:,1,0]; good=abs(det)>1e-12
    u=np.zeros((len(f),3));v=u.copy()
    u[good]=(dp[:,0]*du[:,1,1,None]-dp[:,1]*du[:,0,1,None])[good]/det[good,None]
    v[good]=(-dp[:,0]*du[:,1,0,None]+dp[:,1]*du[:,0,0,None])[good]/det[good,None]
    U=np.zeros_like(p);V=U.copy()
    # Normalize per-face derivatives so tiny UV islands cannot dominate adjacent faces.
    area=np.linalg.norm(np.cross(dp[:,0],dp[:,1]),axis=1)
    for k in range(3):
        np.add.at(U,f[:,k],unit(u)*area[:,None]);np.add.at(V,f[:,k],unit(v)*area[:,None])
    U=unit(U-n*(U*n).sum(1)[:,None]);V=unit(V-n*(V*n).sum(1)[:,None])
    bad=np.linalg.norm(V,axis=1)<.5
    V[bad]=unit(np.cross(n[bad],np.eye(3)[np.argmin(abs(n[bad]),axis=1)]))
    # ER stores V tangent. W defines the U bitangent as cross(N,V)*W.
    w=np.where((np.cross(n,V)*U).sum(1)<0,-1.,1.)
    return U,V,w,int(bad.sum())


def meshes(root, state):
    ab,eb,ai,ei,A,P,E,Q,mapping,enabled,align=state
    path=root/'apex-data/assets/octane/cast/mdl/Humans/class/medium/pilot_medium_stim_LOD0.cast'
    model=Cast.load(str(path)).Roots()[0].ChildrenOfType(Model)[0]
    assert [b.Name() for b in model.Skeleton().Bones()]==[b['name'] for b in ab]
    owners={x['source']:ei[x['target']] for x in mapping['source_owners']}; owner=np.array([owners[b['name']] for b in ab])
    deform=P @ np.linalg.inv(A); R=deform[:,:3,:3]; transform=Q[:3,:3]; reflection=transform/np.linalg.norm(transform[:,0])
    out=[]; drops=[]; counts=[]
    for mesh in model.Meshes():
        p=np.array(mesh.VertexPositionBuffer()).reshape(-1,3); n=unit(np.array(mesh.VertexNormalBuffer()).reshape(-1,3))
        uv=np.array(mesh.VertexUVLayerBuffer(0)).reshape(-1,2); uv1=np.array(mesh.VertexUVLayerBuffer(1)).reshape(-1,2)
        f=np.array(mesh.FaceBuffer()).reshape(-1,3); U,V,w,bad=tangent_basis(p,n,uv,f)
        original_winding=winding(p,n,f)
        p=p@transform.T;n=n@reflection.T;V=V@reflection.T;w*=-1
        # Mirroring reverses geometry handedness; swap exactly once.
        f=f[:,[0,2,1]]
        bi=np.array(mesh.VertexWeightBoneBuffer()).reshape(len(p),-1);bw=np.array(mesh.VertexWeightValueBuffer()).reshape(len(p),-1)
        assert np.isfinite(bw).all() and bw.min()>=0 and np.max(abs(bw.sum(1)-1))<.001
        raw_sum_error=float(np.max(abs(bw.sum(1)-1)))
        bw=bw/bw.sum(1)[:,None]
        pos=np.zeros_like(p);normal=np.zeros_like(n);tangent=np.zeros_like(V)
        for k in range(bw.shape[1]):
            ids=bi[:,k]; weights=bw[:,k,None]
            pos+=weights*(np.einsum('nij,nj->ni',R[ids],p)+deform[ids,:3,3])
            normal+=weights*np.einsum('nij,nj->ni',R[ids],n)
            tangent+=weights*np.einsum('nij,nj->ni',R[ids],V)
        normal=unit(normal);tangent=unit(tangent-normal*(tangent*normal).sum(1)[:,None])
        merged=np.zeros((len(p),len(eb)));np.add.at(merged,(np.arange(len(p))[:,None],owner[bi]),bw)
        indices=np.argsort(-merged,axis=1,kind='stable')[:,:4];weights=np.take_along_axis(merged,indices,axis=1)
        drop=np.maximum(0,1-weights.sum(1));drops.extend(drop.tolist());weights/=weights.sum(1)[:,None]
        # ER serializes clockwise (against-normal) triangles. This is distinct from
        # the reflection correction above: Apex source is counterclockwise.
        f=f[:,[0,2,1]]
        out.append(dict(name=mesh.Name(),material=mesh.Material().Name(),positions=pos,normals=normal,tangents=np.c_[tangent,w],
                        uv0=uv,uv1=uv1,bone_indices=indices,bone_weights=weights,indices=f,source_positions=p,
                        original_winding=original_winding,converted_winding=winding(pos,normal,f),tangent_fallback_vertices=bad))
        counts.append(dict(name=mesh.Name(),material=mesh.Material().Name(),vertices=len(p),triangles=len(f),influences=bw.shape[1],raw_weight_sum_max_error=raw_sum_error,tangent_missing=mesh.VertexTangentBuffer() is None,weight_loss=loss_statistics(drop)))
    allp=np.concatenate([np.array(m.VertexPositionBuffer()).reshape(-1,3) for m in model.Meshes()])
    align['raw_mesh_height_source_units']=float(np.ptp(allp[:,1]));align['raw_mesh_height_m']=float(np.ptp(allp[:,1])*.0254)
    return out,dict(source_meshes=counts,weight_loss=loss_statistics(drops))


def split(meshes, state):
    ab,eb,ai,ei,A,P,E,Q,mapping,enabled,align=state
    fallback={}; distances={}
    for part in PARTS:
        target=[];depth=[]
        for i,b in enumerate(eb):
            j=i;d=0
            while j>=0 and eb[j]['Name'] not in enabled[part]:j=eb[j]['ParentIndex'];d+=1
            target.append(j);depth.append(d)
        fallback[part]=np.array(target);distances[part]=np.array(depth)
    output={p:[] for p in PARTS};report={p:dict(vertices=0,triangles=0,forced_vertices=0,forced_weight=0.,remaps=[]) for p in PARTS}
    for m in meshes:
        bi=m['bone_indices'];bw=m['bone_weights'];f=m['indices']
        costs=[]
        for part in PARTS:
            fb=fallback[part][bi];unsupported=((fb!=bi)*bw).sum(1);steps=(distances[part][bi]*bw).sum(1)
            c=unsupported[f].sum(1)+.001*steps[f].sum(1)
            c[(np.any((fb<0)&(bw>0),axis=1))[f].any(1)]=np.inf
            costs.append(c)
        # Dominant anatomical region resolves zero-cost overlap without moving fingers or feet.
        region=[]
        for b in eb:
            name=b['Name']
            region.append(0 if name in ('Head','Jaw','Neck') or 'Face' in name else
                          2 if any(x in name for x in ('Hand','Finger','Forearm','ForeArm')) else
                          3 if any(x in name for x in ('Thigh','Calf','Foot','Toe','Knee','Leg')) or name=='Pelvis' else 1)
        votes=np.zeros((len(m['positions']),4))
        np.add.at(votes,(np.arange(len(bi))[:,None],np.array(region)[bi]),bw)
        desired=votes[f].sum(1).argmax(1);costs=np.stack(costs,axis=1)
        costs+=np.where(np.arange(4)[None,:]==desired[:,None],0.,1e-6)
        assignment=costs.argmin(1)
        assert np.isfinite(costs[np.arange(len(f)),assignment]).all()
        for pi,part in enumerate(PARTS):
            faces=f[assignment==pi]
            if not len(faces):continue
            used,inv=np.unique(faces,return_inverse=True);sub={k:v[used].copy() for k,v in m.items() if isinstance(v,np.ndarray) and k!='indices'}
            sub.update(name=m['name'],material=m['material'],indices=inv.reshape(-1,3),source_mesh=m['name'],source_vertex_ids=used)
            old=sub['bone_indices'].copy();new=fallback[part][old];weights=sub['bone_weights']
            affected=np.any((old!=new)&(weights>0),axis=1)
            # Zero weights must also have a legal index; use the first enabled bone for padding.
            padding=ei[next(n for n in sorted(enabled[part]) if n in ei)]
            new=np.where(weights>0,new,padding)
            merged=np.zeros((len(used),len(eb)));np.add.at(merged,(np.arange(len(used))[:,None],new),weights)
            inds=np.argsort(-merged,axis=1,kind='stable')[:,:4];ww=np.take_along_axis(merged,inds,axis=1)
            inds=np.where(ww>0,inds,padding)
            sub['bone_indices']=inds;sub['bone_weights']=ww/ww.sum(1)[:,None];output[part].append(sub)
            r=report[part];r['vertices']+=len(used);r['triangles']+=len(faces);r['forced_vertices']+=int(affected.sum())
            r['forced_weight']+=float(((old!=new)*weights).sum())
            if affected.any():
                pos=sub['positions'][affected];r['remaps'].append(dict(mesh=m['name'],vertices=int(affected.sum()),
                   bbox_min=pos.min(0).tolist(),bbox_max=pos.max(0).tolist(),source_vertex_ids=used[affected].tolist(),
                   positions_m=pos.tolist(), vertex_remaps=[dict(source_vertex_id=int(used[j]),position_m=sub['positions'][j].tolist(),
                       transitions=[dict(source=eb[a]['Name'],target=eb[b]['Name'],weight=float(w)) for a,b,w in zip(old[j],new[j],weights[j]) if a!=b and w>0]) for j in np.flatnonzero(affected)],
                   transitions=sorted({eb[a]['Name']+' -> '+eb[b]['Name'] for a,b,w in zip(old[affected].ravel(),new[affected].ravel(),weights[affected].ravel()) if a!=b and w>0})))
    for part in PARTS:
        report[part]['bones']=sorted({eb[i]['Name'] for m in output[part] for i in m['bone_indices'][m['bone_weights']>0]})
        report[part]['bone_count']=len(report[part]['bones']);report[part]['enabled_count']=len(enabled[part])
    assert sum(r['triangles'] for r in report.values())==sum(len(m['indices']) for m in meshes)
    return output,report
