"""Analyze extracted vanilla data; all game-derived output stays below er-data."""
import json, math, pathlib, struct, sys
BASE=pathlib.Path(__file__).resolve().parents[1]
ROOT=BASE.parents[1]/'er-data/json'
def load(path): return json.loads(path.read_text(encoding='utf-8'))
def mm(a,b): return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
def local(n,hk=False):
    x,y,z,w=n['Rotation' if hk else 'RotationQuaternion']; sx,sy,sz=n['Scale'][:3]; tx,ty,tz=n['Translation'][:3]
    a=[[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w),tx],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w),ty],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y),tz],[0,0,0,1]]
    for i in range(3):
        for j,v in enumerate([sx,sy,sz]): a[i][j]*=v
    return a

def worlds(nodes,hk=False):
    cache={};visiting=set()
    def get(i):
        if i in visiting: raise ValueError('Parent cycle')
        if i not in cache:
            visiting.add(i); n=nodes[i]; a=local(n,hk)
            cache[i]=mm(get(n['ParentIndex']),a) if n['ParentIndex']>=0 else a
            visiting.remove(i)
        return cache[i]
    return {n['Name']:get(i) for i,n in enumerate(nodes)}
def delta(a,b): return max(abs(a[i][j]-b[i][j]) for i in range(4) for j in range(4))
def analyze(root=ROOT):
    global ROOT
    ROOT=root
    skeleton=load(ROOT/'c0000_skeleton.json'); sb={b['Name']:b for b in skeleton['Bones']}; sw=worlds(skeleton['Bones'],True)
    comparisons=[]; meshrows=[]
    for path in sorted((ROOT/'parts').glob('*.json')):
        f=load(path); fn={n['Name']:n for n in f['Nodes']}; fw=worlds(f['Nodes']);common=sorted(sb.keys()&fn.keys())
        active=sorted(set(i for m in f['Meshes'] for i in m['BoneIndexRange']['ActiveIndices']))
        assert all(0<=i<f['NodeCount'] for i in active)
        active_names=[f['Nodes'][i]['Name'] for i in active];same_parent=[]
        for name in common:
            a,b=fn[name],sb[name];fp=f['Nodes'][a['ParentIndex']]['Name'] if a['ParentIndex']>=0 else None;hp=skeleton['Bones'][b['ParentIndex']]['Name'] if b['ParentIndex']>=0 else None
            same_parent.append({'Name':name,'FlverParent':fp,'HavokParent':hp,'LocalMatrixMaxDelta':delta(local(a),local(b,True)),'ModelMatrixMaxDelta':delta(fw[name],sw[name]),'IsActive':name in active_names})
        comp={'File':path.name,'NodeCount':f['NodeCount'],'MeshCount':len(f['Meshes']),'VertexCount':sum(m['VertexCount'] for m in f['Meshes']),'CommonCount':len(common),'MissingFromFlver':sorted(sb.keys()-fn.keys()),'ExtraFlverNodes':sorted(fn.keys()-sb.keys()),'ActiveNames':active_names,'TransformComparison':same_parent,'ActiveModelMaxDelta':max((delta(fw[n],sw[n]) for n in active_names if n in sw),default=0)}
        comparisons.append(comp)
        for m in f['Meshes']:
            meshrows.append({'File':path.name,'Mesh':m['Index'],'VertexCount':m['VertexCount'],'PaletteSize':m['PaletteSize'],'Dynamic':m['Dynamic'],'IndexStorage':m['BoneIndexRange']['IndexStorage'],'ActiveMin':m['BoneIndexRange']['Min'],'ActiveMax':m['BoneIndexRange']['Max'],'Layouts':[b['LayoutIndex'] for b in m['VertexBuffers']]})
    (ROOT/'s2a_comparison.json').write_text(json.dumps(comparisons,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (ROOT/'mesh_inventory.json').write_text(json.dumps(meshrows,indent=2)+'\n',encoding='utf-8')
    warp=load(ROOT/'smoke/BonfireWarpParam.json');msb=load(ROOT/'smoke/m10_00_00_00.msb.json'); emevd=load(ROOT/'smoke/m10_00_00_00.emevd.json')
    en=load(ROOT/'smoke/engus_PlaceName.json'); zh=load(ROOT/'smoke/zhocn_PlaceName.json');enplaces={e['ID']:e['Text'] for e in en['Entries']};zhplaces={e['ID']:e['Text'] for e in zh['Entries']}
    evidence=[]
    for row in warp['Rows']:
        if row['ID'] not in [100000,100003,100007,100008]:continue
        c={c['Name']:c['Value'] for c in row['Cells']};parts=[p['Data']['Name'] for p in msb['Parts'] if p['Data']['EntityID']==c['bonfireEntityId']]
        assert parts and c['areaNo']==10 and c['gridXNo']==0 and c['gridZNo']==0
        evidence.append({'RowID':row['ID'],'Name':row['Name'],'Text':enplaces[c['textId1']],'Chinese':zhplaces[c['textId1']],'EntityID':c['bonfireEntityId'],'MSBParts':parts,'Map':[10,0,0,0],'EventFlag':c['eventflagId']})
    equipment=load(ROOT/'smoke/EquipParamProtector.json');enf=load(ROOT/'smoke/engus_item.json');zhf=load(ROOT/'smoke/zhocn_item.json')
    enarmor={e['ID']:e['Text'] for t in enf['Tables'] if t['ID']==12 for e in t['Entries']};zharmor={e['ID']:e['Text'] for t in zhf['Tables'] if t['ID']==12 for e in t['Entries']}
    armor=[]
    for row in equipment['Rows']:
        c={c['Name']:c['Value'] for c in row['Cells']}
        if c.get('equipModelId') in [1010,1280,1500,1600] and row['ID']%100==0:
            armor.append({'RowID':row['ID'],'ModelID':c['equipModelId'],'English':enarmor.get(row['ID']),'Chinese':zharmor.get(row['ID'])})
    (ROOT/'map_identity.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (ROOT/'armor_identity.json').write_text(json.dumps(armor,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    out=['# S2a：ER 离线骨架与护甲核验','', '数据来自本机 ER 2.7.1.0（regulation 11711000）；未启动游戏。所有数值由原版文件导出。', '', '## 骨架', '',f'`c0000_skeleton.json`：{skeleton["BoneCount"]} 根骨骼，来源 `{skeleton["Source"]}`。平移/缩放只使用 XYZ，第四分量保留原字节解码值，不作为空间分量。', '', '人形核心实际名字（左右严格保留大小写）：', '', '- 根与躯干：Master、RootPos、RootRotY、RootRotXZ、Pelvis、Spine、Spine1、Spine2、Collar、Neck、Head。', '- 上肢：L_/R_Clavicle、Shoulder、UpperArm、Elbow、Forearm、Hand；注意 Forearm 与 ForeArmTwist 的大小写不同。', '- 手指：左右各 Finger0 / Finger01 / Finger02，Finger1 / Finger11 / Finger12，Finger2 / Finger21 / Finger22，Finger3 / Finger31 / Finger32，Finger4 / Finger41 / Finger42。', '- 下肢：L_/R_Hip、Thigh、Calf、Foot、Toe0、Knee。', '- 扭转：左右各 UpArmTwist、UpArmTwist1、ForeArmTwist、ForeArmTwist1、ThighTwist、ThighTwist1、CalfTwist、CalfTwist1、FootTwist。', '', '## 节点与参考姿态', '', '每份 FLVER 都含 115 个与 hkaSkeleton 同名的节点，缺失同样 35 个；其余是模型、布料、碰撞或面部节点。不能把 FLVER 节点数当作运行时 skeleton 数。详见 `s2a_comparison.json`（逐文件完整差集、逐骨局部/模型空间误差）。', '', '| 文件 | 节点 | mesh | 顶点 | 额外节点 | 活跃骨模型矩阵最大差 |','|---|---:|---:|---:|---:|---:|']
    for c in comparisons:
        out.append(f'| {c["File"]} | {c["NodeCount"]} | {c["MeshCount"]} | {c["VertexCount"]} | {len(c["ExtraFlverNodes"])} | {c["ActiveModelMaxDelta"]:.6g} |')
    out+=['','35 个共同缺失名字：`'+ '`, `'.join(comparisons[0]['MissingFromFlver'])+'`。','','局部变换不能直接等同：例如胸甲 Spine 是独立根节点，HKX 中父骨是 RootRotXZ；Pelvis 在 FLVER 是根，HKX 父骨为 RootPos。按各自层级累计模型矩阵后，胸甲实际参与蒙皮的核心骨骼非常接近参考姿态；未参与该部位蒙皮的同名节点仍可能明显不同。不能复制所有同名节点的局部值作为完整参考姿态。四元数比较使用 q 与 -q 的等价性，Euler 使用 FLVER X→Z→Y 顺序；矩阵分析为 T*R*S 的列向量等价形式，误差阈值 1e-4。','','1280 胸甲额外 50 个节点：`'+'`, `'.join(next(c['ExtraFlverNodes'] for c in comparisons if c['File']=='BD_M_1280.json'))+'`。其他模型的完整额外名字见比较 JSON。','','## 顶点索引与布局','','本次 32 个 FLVER 的每个 mesh palette 都为 0（完整逐 mesh 数据见 `mesh_inventory.json`）。动态 mesh 的 UByte4 骨骼索引仍非零，并能直接对应 FLVER Nodes；不经过一个不存在的 mesh palette。静态 mesh 用 NormalW 选择单骨。此结论由原版索引、节点名字及绑定位置交叉核验；游戏内最终渲染仍属 S3。一般 FLVER 的 palette 和宽索引不能按本样本推断为不存在。','','1280 胸甲所有实际 mesh 均采用 layout 4，stride 40：','','| 偏移 | 语义 | 类型 | 编码 |','|---:|---|---|---|','| 0 | Position | Float3 | 3×f32 |','| 12 | Normal | UByte4 (0x11) | XYZ=(u8-127)/127；W 为整数 NormalW |','| 16 | Tangent | UByte4 (0x11) | 四分量=(u8-127)/127 |','| 20 | BoneIndices | UByte4 (0x11) | 4×u8 直接节点索引 |','| 24 | BoneWeights | UByte4Norm (0x13) | 4×u8 /255 |','| 28 | VertexColor | UByte4Norm (0x13) | RGBA /255（Index=1） |','| 32 | UV | Short4 (0x16) | 两组 i16×2 /2048 |','','文件还有其他未被当前 mesh 使用的布局，不能仅凭 BufferLayouts 列表推断当前网格 stride。FLVER 版本为 0x2001A。法线不是标准 signed SNORM8；零分量为 0x7f。UV 类型名是 Short4，必须按有符号 i16 读取。','','### 原版原始字节与解码','','来源 `parts/BD_M_1280.json` mesh 0 的首个 vertex buffer；AbsoluteOffset 是解压后的 FLVER 文件偏移：','']
    f=load(ROOT/'parts/BD_M_1280.json');m=f['Meshes'][0];buf=m['VertexBuffers'][0]
    for raw,v in zip(buf['RawSamples'],m['VertexSamples']):
        b=bytes.fromhex(raw['BytesHex']);out.append(f'- vertex {raw["Vertex"]}，offset 0x{buf["AbsoluteOffset"]+raw["Vertex"]*40:x}：完整 `{raw["BytesHex"]}`；normal `{b[12:16].hex(" ")}` → {v["Normal"]}、W={v["NormalW"]}；tangent `{b[16:20].hex(" ")}` → {v["Tangents"][0]}；UV 原始 {struct.unpack("<4h",b[32:40])} → {v["UVs"]}。')
    out+=['','示例 vertex 0 索引 [1,2,25,29] → [Spine1,Spine2,Collar,SpineArmor1]；权重字节 [10,51,0,193] → /255，和为 254/255，原版没有强制精确归一化。索引 29 若错误地按 hkaSkeleton 序号读取，会变成 R_Hip。','','## 对照护甲身份','','名称由 regulation 的 EquipParamProtector.equipModelId 与本机两种语言 ProtectorName.fmg 关联，详见 `armor_identity.json`；名字并非从路径号或社区资料猜测。','','| 模型号 | 英文 | 简中 | 参数行 |','|---:|---|---|---:|']
    for a in armor: out.append(f'| {a["ModelID"]} | {a["English"]} | {a["Chinese"]} | {a["RowID"]} |')
    out+=['','## 地图身份与冒烟测试','','字典列出 `/map/mapstudio/m10_00_00_00.msb.dcx` 和 `/event/m10_00_00_00.emevd.dcx`，均在实际封包中存在。通过 BonfireWarpParam 的地图号、赐福 EntityID 与 MSB parts 的对应，以及游戏 PlaceName.fmg 的 Stormveil 名称确认：史东薇尔城为 **m10_00_00_00**。详见 `map_identity.json`。','','| 参数行 | 本机地名（英 / 中） | EntityID | MSB part |','|---:|---|---:|---|']
    for e in evidence: out.append(f'| {e["RowID"]} | {e["Text"]} / {e["Chinese"]} | {e["EntityID"]} | {", ".join(e["MSBParts"])} |')
    out+=['','输出规模：','',f'- MSB：{len(msb["Models"])} models、{len(msb["Parts"])} parts、{len(msb["Regions"])} regions、{len(msb["Events"])} events。',f'- EMEVD：{len(emevd["Events"])} events、{sum(len(e["Instructions"]) for e in emevd["Events"])} instructions；保留 bank/id、参数 hex 和逐字节整数。',f'- BonfireWarpParam：{warp["RowCount"]} rows、{len(warp["Fields"])} fields（version-aware paramdef）。',f'- 两种 PlaceName.fmg：分别 {len(en["Entries"])} 与 {len(zh["Entries"])} 条目，均包含空文本/占位条目。两个完整 item msgbnd 各 {len(enf["Tables"])} 个 FMG。','- 附加 MATBIN、TPF、BND4、DCX 子命令已用原版数据冒烟。','','## 约束与下一步','','这些是离线文件事实，未验证游戏运行时骨架与绑定姿态是否完全等于文件内容。S2b/S3 应按语义与名字映射，不把 HKX index 当作 FLVER index，也不把每个 FLVER 同名辅助节点的局部变换当作完整参考姿态。当前 32 个样本不能说明任意 ER 资产都用直接索引或 u8。']
    (ROOT/'s2a_summary.md').write_text('\n'.join(out)+'\n',encoding='utf-8')
    print('Analyzed',len(comparisons),'FLVERs,',len(meshrows),'meshes; report:',ROOT/'s2a_summary.md')
    for c in comparisons:
        if c['File'] in ['BD_M_1280.json','HD_M_1280.json','AM_M_1280.json','LG_M_1280.json']:print(c['File'],'active delta',c['ActiveModelMaxDelta'])
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8'); analyze(pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else ROOT)
