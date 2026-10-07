# fusemesh v1

`fusemesh` 是目录格式：UTF-8 `mesh.json` 加小端二进制数组。必需数据如下；没有隐含坐标变换。

```json
{
  "format": "fusemesh",
  "version": 1,
  "space": "flver_model",
  "bones": ["Spine1", "Spine2", "Collar"],
  "materials": [
    {"name": "body", "template_matbin": "P[BD_M_1280]_Fabric",
     "textures": {"a": "body_a.png", "n": "body_n.png", "m": "body_m.png"}}
  ],
  "submeshes": [
    {"name": "body", "material": 0, "vertex_count": 1234, "index_count": 3000,
     "positions": "body.pos.f32", "normals": "body.nrm.f32", "tangents": "body.tan.f32",
     "uv0": "body.uv0.f32", "uv1": "body.uv1.f32", "colors": "body.col.u8",
     "bone_indices": "body.bi.u8", "bone_weights": "body.bw.f32", "indices": "body.idx.u32"}
  ]
}
```

## 坐标与数组

位置是 FLVER 模型空间，米，Y 向上；不做轴交换、镜像或 UV 翻转。索引的绕序原样写入。骨骼名大小写敏感；构建时逐名映射到模板 FLVER 节点表。`bones` 不同顺序不会改变蒙皮结果。因为输入和 layout 4 骨骼索引均为 u8，骨骼名表与模板节点表必须各自不超过 256。名字缺失、重复或越界即报错。

| 字段 | 每顶点数据 | 说明 |
|---|---|---|
| positions | f32×3 | 有限值；逐位保留 |
| normals | f32×3 | 写为 `(round(x×127+127))` 的 u8 |
| tangents | f32×4 | XYZW 同上，W 为副切线符号；调用方提供切线 |
| uv0、uv1 | f32×2 | 两组 UV，量化为有符号 i16：`round(uv×2048)` |
| colors | u8×4 | RGBA；可省略，默认四个 255 |
| bone_indices | u8×4 | 指向 `bones`，不是 FLVER 节点序号；零权重槽也必须在表内 |
| bone_weights | f32×4 | 每个值在 0..1，和为 1（容差 1e-4）；普通新网格用最大余数法量化，四字节和为 255 |
| indices | u32 | 小端三角形列表；`index_count` 必须为 3 的倍数；不得越界 |

所有文件长度必须与声明计数精确一致。拒绝 NaN/Infinity、绝对路径、目录穿越、不可编码的法线/切线或 UV。Normal/tangent 的偏置 u8 可表示范围为 -1..128/127；通常应提供单位方向。UV 编码范围为 -16..32767/2048。不重新计算法线、切线、UV、拓扑或权重绑定。

`materials[].name` 是唯一的 ASCII 字母/数字/下划线名字，用于 `P[XX_M_0999]_<name>.matbin`（XX=HD/BD/AM/LG）；`template_matbin` 是原始 MATBIN basename，可有或没有 `.matbin` 后缀，必须对应当前部位模板已经使用的材质。每个输入材质生成一个 FLVER 材质和一份 MATBIN。

`textures` 的键来自模板胸甲 TPF 的实际后缀，例如 `a/n/m/rope_a`，路径是相对于 fusemesh 目录的 PNG/DDS。只替换 MATBIN 引用的本地胸甲贴图，保留共享 AAT 细节贴图及材质参数。不指定某个贴图时复制模板对应 DDS。传入与模板 DXGI 格式相同且带 mipmap 的 DDS 时不重压缩；PNG、格式不同或无 mipmap 的 DDS 用 texconv 转成对应 BC/sRGB 格式和完整 mip 链。转换日志保存在输出包的 `.ertool-textures` 目录。

多个材质可使用不同的同后缀贴图：第一份为 `BD_M_0999_a`，发生输入路径冲突时为 `BD_M_0999_<material>_a`，MATBIN 按各自名字引用。相同输入路径复用同一个 TPF 条目。导出裸 FLVER 未提供 MATBIN 时会列出整个同目录 TPF；构建器允许这些已知但当前材质未使用的后缀。因此应选择有本地 `a/n/m` 槽的 `Fabric/Metal/Leather` 等模板来接自定义贴图；`Belt` 的底图来自共享 AAT，不适合作这个用途。

## 可选往返数据

基本 v1 足以构建普通蒙皮网格；以下扩展仅用于保留原版数据。修改原版网格时必须同步修改对应的扩展，或者移除不再适用的扩展。

- `materials[].flver_name`：保留原版材质名，包括 `#23#` 等装备隐藏标记。省略时使用 `name`。
- `submeshes[].node_name`：mesh 的辅助节点名称。省略时使用模板首个 mesh 的节点。
- `normal_w`：每顶点一字节，保留法线 W 的原始整数；普通新网格省略时为 0。
- `flver_bone_weights`：f32×4 原始 FLVER 权重。1280 的原始字节和为 252..255，导出必需的 `bone_weights` 会归一化到 1，原始权重另存在此文件。构建器校验其量化值与归一化权重一致，再原样恢复。外部新网格不需要该字段。
- `cull_backfaces`：主面组背面剔除，默认 true。
- `face_sets`：数组，每项有 `flags`（u32）、`cull_backfaces`、`unk06`、`index_count`、`indices`（u32 三角形数组路径）。保留独立 LOD 与 MotionBlur 面组；无扩展时生成 0、0x01000000、0x02000000、0x80000000、0x81000000、0x82000000 六组，复用基本三角形。不生成简化网格。`None` 面组必须与必需的 `indices` 一致。
- `flver_cloth`：仅支持原版 1280 三流布料（layout 1/5/3）。含 `positions`、`normals`（f32×3）、`tangents`、`bitangents`（f32×4）、`normal_w`（u8×1）的文件路径；前三项是第二组数据，bitangents 是中间流数据。保留原版三流布局。普通网格无此字段，写 layout 4。使用 `_Cloth` MATBIN 却没有这些流会报错；这不是为任意新网格自动生成布料物理数据的功能。

**1280 实测修正**：mesh 6–11、24 是三流布料；其余 19 个 mesh 使用 40 字节 layout 4。只保存第一组几何会失去原版布料数据。原版 26 个 mesh 共 152 个面组，其中 MotionBlur 副本不一定与主面组相同。

导出刚性 mesh 时将单骨绑定位置、法线与切线转换到模型空间，并转成权重 1 的动态蒙皮；这种情况不承诺原始缓冲字节相同。当前导出器支持普通单流及明确核验过的 1/5/3 多流；其他多流明确报错。TPF 导出 DDS 原样；MATBIN 中共享资源不复制到 fusemesh。

## 包围盒与序列化

头部使用全部模型空间位置的 AABB；节点使用非零权重顶点和该节点所属 mesh 顶点，变换到对应节点的局部空间后取 AABB。局部矩阵为 Scale·RotX·RotZ·RotY·Translation，沿父链累乘并求逆；未使用节点设零包围盒。布料第二组位置也参与计算。

ER 0x2001A 的 mesh 包围盒有九个 float。依据原版实际值，它们是半尺寸、旋转、中心；SoulsFormatsNEXT 名字仍叫 `Min/Max/Unk`，不能按名字直接写 AABB min/max。构建器写轴对齐形式：`Min=(max-min)/2`，`Max=(0,0,0)`，`Unk=(min+max)/2`。该语义判断来自本机数据与几何对照，仍须在游戏中核查剔除表现。`verify_armor_bounds.py` 独立验算全部 mesh/节点/头部包围盒。

每个指定输入的部位高低模使用同一份重建 FLVER 与 TPF，封包各自沿用高低模模板的辅助文件；未指定输入的部位保留节点及其他模板数据但移除所有 mesh。FLVER 的版本、标志、骨架表、dummy、GX 与材质槽定义沿用模板；空贴图路径仍保留槽名及 tiling 元数据。全部包用游戏 Oodle 原位加载的 KRAK level 6 压缩，不复制 DLL、不写游戏目录。

## 四部位输入与可选材质控制（T005）

旧 `--mesh` 等价于 `--bd-mesh`。支持 `--hd-mesh/--bd-mesh/--am-mesh/--lg-mesh` 各自指定目录；对应 `--hd-template/--bd-template/--am-template/--lg-template` 是高模 partsbnd 路径，低模从同目录 `_l` 文件取得。未覆写的模板仍取 `--template-dir` 和 `--template-model`。未指定网格的部位为空；允许全部为空。高低模启用节点表须一致；非零权重实际引用的骨必须是 Bone 且非 Disabled，未使用骨表项可以保留。40 字节布局按定义识别，不依赖固定索引 4。

每个部位分别生成 `XX_M_0999_<suffix>` 贴图与 `P[XX_M_0999]_<name>` MATBIN。为保持 v1 兼容，以下材质字段可省略：

- `sampler_textures`：字典，键为模板 MATBIN 完整 Sampler.Type，值为相对 PNG/DDS 路径。显式替换 AlbedoMap/NormalMap/MetallicMap，包括原先共享的 AAT；编码取当前部位本地 a/n/m，名称包含 material 和 sampler index。未指定的 sampler 保持原样。未知 Type 报错。
- `float_params`：字典，键为模板已存在的 Float 参数名，值须有限。仅可覆盖 Float，其他类型或不存在参数报错。普通往返不传此字段，保持参数原值。

PNG 转换强制 DX10 DDS 头，避免 BC4U legacy FourCC 的识别歧义，明确保留模板 DXGI/sRGB。
