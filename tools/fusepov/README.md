# T016 / T011：Octane、Fuse 第一人称手臂及 R-301，模型 998

从仓库根目录运行：

```powershell
python tools/fusepov/build_pov.py
python tools/fusepov/verify_pov.py
```

`--legend fuse|octane` 默认是 `fuse`。Fuse 默认生成目录为 `er-data/s3/fuse_pov/`，Octane 为 `er-data/s3/octane_pov/`。构建仅在所选输出目录写派生产物，关闭只读复用模块的 Python 字节码缓存；不编译或修改 `fusemesh`、`fusegun`、`erdata`，不写游戏、`scratch`、`apex-data` 或 git 状态。T016 的 Fuse 回归必须显式指定下面的专属 `fuse_check/` 目录。

前置输入是任务单指定的本机 Cast/QC/PNG、`tools/apexpov/carriers.json`、T002 模板 JSON、T005/T008 绕序证据 JSON，以及已构建的 `ertool.exe`、`erextract.exe`、`tools/bin/texconv/texconv.exe`。Python 需要 NumPy、Pillow；无需 Blender/GPU。构建器只读提取本机 ER 模板。`--matbin-bnd <path>` 默认读取 `scratch/mod/package/material/allmaterial.matbinbnd.dcx`；先逐字节复制到本任务 `inputs/`。本目录的 .NET 8 适配器直接引用现成 SoulsFormats DLL，首次在所选输出的 `inputs/material-adapter/bin`、`obj` 内编译；构建不在工具目录写缓存，不重建只读工具，禁用共享编译服务。

## Octane 一条命令与验收

在仓库根目录执行：

```powershell
python tools/fusepov/build_pov.py --legend octane
python tools/fusepov/verify_pov.py --legend octane
python tools/apexpov/bake_pov.py --legend octane
python tools/apexpov/verify_pov_pack.py --legend octane
python tools/fusepov/preview_pov.py --legend octane --pack apex-data/pov/octane/fuse_pov.anim
```

只取 `apex-data/assets/octane/cast/mdl/Weapons/arms/pov_pilot_medium_stim_LOD0.cast` 的 `body_0_octane_base_v_arms`，使用 `octane_base_v_arms` 材质。body、gear、head 的顶点、正权重骨和 Source 空间包围盒保存在 `bodygroups.json`；已用骨、owner 和载体见 `pov-mesh-summary.json`。禁止骨的正权重会立即报错。

T011 的坐标、权重、AM 优先分配、模板、切线和绕序约定保持不变。Octane 产物为 AM 5,101 顶点 / 8,497 面，BD 15,546 顶点 / 17,810 面，HD/LG 空网格；四权重最大损失约 1.174783%，部位分配损失为 0。

材质适配器仅从暂存构建输入里移除三个目标名称的冲突项，让只读 `ertool` 生成材质，再把目标载荷合并回原始快照。原条目的顺序、ID、Name、Flags 和非目标载荷逐字节不变；同名条目原位替换且记录，即使新旧载荷相同。新增条目附加到末尾。`material-bundle-audit.json` 和 `material-bundle-verification.json` 覆盖输入的全部条目，另核对 999 内容。

Octane 构建可在动画包尚未生成时独立运行：它从本机完整 Fuse FPOV 生成输出目录内的 `inputs/preview-fuse_pov.anim`，只改载体逆绑定。独立 bake 完整解码同一组本机动画；已存在的 Octane pack 必须与预览 pack 逐字节相同。Octane 载体图读取实际 998 FLVER 的位置、UV、索引、法线和 8 位权重，使用 FPOV 的 f32 参考/idle 动画、权重和逆绑定。`preview-verification.json` 保存手指顶点到全部枪械三角面的精确无符号最近距离；该距离不能判断穿插深度。

本工具不计算 SHA256。来源用路径、尺寸、Cast/PNG/FPOV/BND 格式检查；转换流从原 Cast 重算比较，贴图从本机源 PNG 重算逐像素比较，材质载荷、回归产物和动画包用直接内容比较。

## T016 Fuse 回归与空目录复现

```powershell
python tools/fusepov/build_pov.py --legend fuse --out er-data/s3/octane_pov/fuse_check
python tools/apexpov/bake_pov.py --legend fuse --out apex-data/pov/octane/fuse_check/fuse_pov.anim --sequences-out apex-data/pov/octane/fuse_check/fuse_pov_sequences.json
python tools/apexpov/verify_pov_pack.py --legend fuse --new apex-data/pov/octane/fuse_check/fuse_pov.anim --sequences apex-data/pov/octane/fuse_check/fuse_pov_sequences.json
python tools/fusepov/verify_fuse_regression.py
python tools/fusepov/build_pov.py --legend octane --out er-data/s3/octane_pov/repro_final
python tools/fusepov/verify_repro.py --legend octane --repro er-data/s3/octane_pov/repro_final
```

回归逐字节比较原 `er-data/s3/fuse_pov/` 的九个 DCX、全部 fusemesh 输入、PNG 贴图、九张预览，以及原完整 Fuse pack。审计 JSON 只允许删除旧哈希和增加来源/内容检查字段；逐字段原因记录在 `fuse_check/fuse-regression.json`。复现审计和 manifest 只归一化输出目录路径。

## 几何与材质

- 仅保留 `body_0_fuse_base_v_arms`，以及枪的 body、`sight_front` studio 1、`r101_magazine` studio 0。QC 的前机瞄首选项 studio 0 是折叠版本；任务选择立起版本 studio 1，不把选项顺序当作游戏默认状态的证据。
- 按任务单 2026-10-04 13:47 更正：`v_bind = float32(diag(0.0254,0.0254,-0.0254) * v_cast)`，镜像 Z；不旋转、平移、对齐或使用 0.97 缩放。
- 源影响归一化后，严格经 `owner_of_bone`、`carriers` 合并；缺 owner 或 null 的正权重影响报错。稳定取最大的四项、归一化，按三角形优先 AM、然后 BD。若两者都不满足，选择三个顶点总丢失权重最小的部位，去掉该部位未启用影响并重新归一化；全部影响丢失则报错。本机输入无需此回退。
- 边界顶点复制；`source_vertex_ids`、`source_triangle_ids` 可追溯到 Cast。
- 原 Cast 没有切线，调用 T005 的 `tangent_basis` 从原位置/法线/UV 推导 ER 的 V 切线；法线和切线 XYZ 镜像 Z 后归一化，切线 W 取反。与 T005 相同，镜像翻一次、ER against-normal 约定再翻一次，最终索引顺序等于源 Cast。
- 使用各部位 Metal MATBIN，分别转换手臂、枪的 a/n/m。RGB 保留、不乘 AO，法线 RG 保留、B 放 gloss、A=255；金属度继承 T005/T008 近似，允许机械臂和枪金属化。中性细节贴图及参数处理沿用 T005。
- 只向构建器提供 AM/BD 网格；HD/LG 由它移除全部 mesh。它仍保留空部位模板材质槽及 TPF 等辅助资源；这些不产生可见网格。
- 节点包围盒复用 `ArmorBuilder.Bounds`：非零**量化**权重顶点乘模板节点世界矩阵的逆，再取骨局部 AABB；同时包含 mesh 所属节点。验证器独立复用 T003 包围盒核验。

`verify_pov.py` 从原 Cast 重新合并权重、计算部位分配，独立核对读回 FLVER 的 `diag(k,k,-k)` 位置、镜像后的法线和切线、反号的切线 W、与源 Cast 一致的索引、骨名、四权重量化、UV/法线/切线编码误差、六组面、完整三角形覆盖、启用节点、未改变的模板节点变换、骨局部包围盒、材质/贴图引用。它逐字节比较原安装包所有 999 MATBIN，并比较 BND 条目 ID、名字、Flags、长度。

## 预览及增量动画发现

`preview/` 含两个模型各自绑定姿态正/侧视图，以及 `idle_0.cast` 第 0 帧的相机/侧面/斜视和实际量化载体网格相机视图。**显示空间统一为反镜像后的 Apex 空间**：绑定预览使用修正后的实际 ER 几何，再把 Z 镜像撤销；标题和审计均标明此约定。

**本机 `idle_0.cast` 是 additive，不能单独提供完整持枪姿态。** QC 的 `$sequence "idle"` 带 `delta`，实际动画文件名为 `ptpov_rspn101_idle_02_dmx__loop_sub_ptpov_rspn101_iron_ads_in_dmx_8CDE779D.smd`。因此输出两种明确标注的预览：

- `idle_frame0_literal_camera.png`：按 Cast additive 语义叠加到 rig 绑定姿态，作为诊断；手不握枪。
- `idle_frame0_camera.png`：采用 QC 指明减去的 `iron_ads_in` 对应 `ads_in_0.cast` **第 0 帧**作为参考，再叠加指定 `idle_0` 第 0 帧。参考帧 0 是基于本机数据及握持吻合的推断，导出的 QC 没有保留明确 subtract 帧参数。此图双手握枪。

`ParseAnimDesc_Origin`（本机 RSX 源码 `src/core/mdl/animdata.cpp`）会给 delta 根也附加 -90° yaw。预览的指定第 0 帧检查该根为纯导出旋转，保留 absolute 参考的根，只应用导出坐标变换一次。此处理仅影响预览，不改变打包绑定位置。

原生预览严格用同名动画骨 `W_anim @ inverse(W_model_bind) @ p_cast`，直接在 Apex 空间绘制；未出现在动画 rig 的机械附属骨沿最近同名动画祖先保持绑定偏移。另输出 `idle_frame0_carriers_camera.png`，用实际序列化的镜像 ER 绑定顶点及四权重量化，先在 **ER 空间**计算 `D_er = Q @ W_anim_owner @ inverse(B_model_owner) @ inverse(Q)` 蒙皮，再乘 `inverse(Q)` 回到 Apex 显示空间。脚本验证该结果与直接在 Apex 空间计算一致，报告最大误差及与原生蒙皮的差别。

反镜像 Apex 显示空间中的相机为 `jx_c_camera` 的实际世界位姿，局部前方 **+Z**、上方 **+Y**、屏幕右方 **-X**；经 Q 转换后，ER 对应前方为 **-Z**。报告同时保存 `camera_apex` 和 `Q @ camera_apex @ inverse(Q)`。枪口相对消音器挂点的方向作为本机前轴证据。水平 FOV=90° 仅为软件检视设置，不声称是游戏参数。

## 空目录复现

在尚不存在的目录运行完整构建、读回和预览，然后比对：

```powershell
python tools/fusepov/build_pov.py --out er-data/s3/fuse_pov/repro_final
python tools/fusepov/verify_repro.py --repro er-data/s3/fuse_pov/repro_final
```

九个 DCX、fusemesh、PNG 预览及五份审计逐字节比较；构建 manifest 仅忽略输出目录绝对路径差异。

## 相对 attempt 1 的更正

第一版的完整复现目录保存在 `er-data/s3/fuse_pov/attempt1/`。本次只更正位置/法线/切线的 Z 镜像、切线 W、两次翻转后的索引顺序，以及随之变化的包围盒、预览和验证。载体、权重、部位选择、UV、材质和贴图保持不变。可运行 `python tools/fusepov/verify_attempt1.py` 独立比较；它还验证 allmaterial、四个空部位 DCX 及全部 TPF 与第一版逐字节一致。

## 限制

未启动游戏；运行时载体矩阵、动画参考层合成和游戏内剔除由 Claude 负责。原生动画助手骨合并、四权重截断及 8 位量化会产生毫米级偏差；高低模和六面组复用 LOD0。源数据的少量反向/退化面原样保留。法线绿通道、金属度近似、AM Rich shader 的最终光照需要游戏内核对。

## T020：Base 注射器和手持跳板，完整模型 998（修订 4）

从仓库根目录执行：

```powershell
python tools/apexpov/bake_ability.py
python tools/fusepov/build_ability.py
python tools/apexpov/verify_ability.py
python tools/fusepov/verify_ability.py
```

新脚本 `build_ability.py`、`verify_ability.py`、`mesh_ability.py`、`preview_ability.py`、`template_ability.py` 及 `ability_templates/` 不修改当前工具。构建仅写 `er-data/s3/octane_pov_ability/`，`--out` 可选该目录内的子目录。独立构建从同一本机 Cast/QC 数据生成输出内的预览包；已存在的正式 v2 包必须与它逐字节相同。`--pack` 可显式传入 v2 包。

默认 `--matbin-bnd` 是只读 `er-data/s3/octane_gun/package/material/allmaterial.matbinbnd.dcx`。先复制输入，再仅暂存三个 HD/LG 目标 MATBIN 的冲突条目，生成后合并回原包，保持全部原条目的顺序、ID、Name、Flags 和非目标载荷。已有同名目标原位替换并记录。

AM/BD 高低模直接复制 `er-data/s3/octane_pov/package/parts/`，逐字节核对。HD 为两个 Base 注射器网格（1,708 顶点 / 2,186 面），LG 为跳板（4,387 顶点 / 4,990 面）。绑定位置、镜像、切线 W、绕序、四权重及节点局部包围盒沿用 T011。三个本机道具只有一套 UV，ER 第二套复用 UV0，细节采样使用中性贴图；原始第二套 UV 语义无本机数据。玻璃使用 Metal 不透明近似，源 msk 等未用通道保存于审计。

项目负责人授权的 HD/LG 模板副本位于 `inputs/live-templates/`：移除不在 live 骨架中的旧面部/网格节点，重映射节点引用并重建兄弟关系，追加 20 根 enabled Xtra 骨，使用 live 父关系和参考局部绑定。原模板只读。注射器使用 01_01..01_03，跳板使用 01_04..01_10、02_01..02_08；不用躯干或腿部主骨作为道具载体。每个新 FLVER 节点及包中全部载体都必须存在于 live 骨架；20 根新增节点的父关系、局部/世界绑定及载体 ER 绑定均读回核验。

`preview/` 包含指定五帧各自的技能组图和 groups 0..3 图，以及 `idle_0` 的 groups 0/1 图，共十一张。实际读取量化 FLVER 和 v2 包，从 jx_c_camera 显示。idle_onehanded 使用 QC 指名减去的 ads_in_onehanded 第 0 帧，沿用 T011/T016 的参考帧推断及只应用一次导出根旋转。技能叠加严格使用本机骨权重；普通 pad 序列控制双臂，onehanded pad 序列屏蔽左臂，不能把两者当作相同的左手动作。全组图还会显示另一道具的零权重绑定姿态。

所有记录在 `ability-*-audit.json`、`ability-readback-verification.json`、`ability-preview-verification.json`、`ability-verification.json`；事件和零权重骨明细在动画目录的 `ability_sequences.json`。不计算 SHA256，不修改游戏/存档，不启动游戏。

空目录复现和已有材质目标的替换验收：

```powershell
python tools/apexpov/bake_ability.py --out apex-data/pov/octane_ability/repro_clean
python tools/apexpov/verify_ability.py --out apex-data/pov/octane_ability/repro_clean
python tools/fusepov/build_ability.py --out er-data/s3/octane_pov_ability/repro_clean
python tools/fusepov/verify_ability.py --out er-data/s3/octane_pov_ability/repro_clean
python tools/fusepov/build_ability.py --out er-data/s3/octane_pov_ability/material_reuse --matbin-bnd er-data/s3/octane_pov_ability/package/material/allmaterial.matbinbnd.dcx
```

最终预览按第 14 步只在 `def_l_clav` 子树和当前道具子树应用技能的原始权重，其余骨保持 onehanded。包内权重完全不变。指定十一张图外，补充 `pad_toss_0` 第 5 帧的技能组／全组握持诊断图；第 9 帧已在第 8 帧释放事件之后，throwAway 第 20 帧也已脱手，prep 第 0 帧的道具在视锥上缘之外。最初的全 QC 权重图保存在 `preview/diagnostic_full_qc_weights/`。最终 `idle_0` 量化图与 T016 逐像素一致。

最终代码的空目录复现及直接内容比较：

```powershell
python tools/fusepov/build_ability.py --out er-data/s3/octane_pov_ability/repro_final
python tools/fusepov/verify_ability.py --out er-data/s3/octane_pov_ability/repro_final
python tools/fusepov/verify_repro_ability.py --repro er-data/s3/octane_pov_ability/repro_final
```

`verify_repro_ability.py` 比较九个 DCX、45 个网格输入、12 个 PNG、四个模板副本、十三张相机图、FPOV，以及八份审计／manifest；审计仅归一化输出路径和耗时。已有目标材质输入的复用验收保存在 `material_reuse/`。四项损坏拒绝记录位于动画输出的 `ability-rejection-verification.json`。

## T021：电池与原注射器共用 HD，完整模型 998

从仓库根目录运行：

```powershell
python tools/apexassets/battery_assets.py
python tools/apexpov/bake_battery.py
python tools/fusepov/build_battery.py
python tools/apexpov/verify_battery.py
python tools/fusepov/verify_battery.py
```

输出仅在 `er-data/s3/octane_pov_battery/`，`--out` 可选其中的子目录。
默认 `--matbin-bnd` 为 T020 包的 `package/material/allmaterial.matbinbnd.dcx`。
先复制输入，保留全部条目及元数据；三个电池 HD 998 MATBIN 新增，同名条目原位
替换并记录。两个注射器 MATBIN 会重建并原位合并，读回要求其载荷不变。
AM/BD/LG 六个高低模包直接复制 T020；HD 保留注射器的全部输入流、量化网格、
材料和节点布局，并添加 QC 唯一 `$body` 的三个默认电池网格。HD 合计五网格、
6,852 顶点、8,832 三角面。T011 的原始绑定坐标、Z 镜像、切线 W、源绕序、
四权重和骨局部包围盒约定不变。两根剩余 Xtra 已在 Claude 返工后的 T020 模板中
启用，HD 模板副本逐字节复制，不新增面部节点，不修改模板程序。

构建可独立生成输出内的预览 pack；已有正式电池 pack 必须与它逐字节一致。
六张电池相机图按本机剪辑控制双臂，显示 groups 0/4；stim_idle 和 idle 两张
回归图与 T020 逐像素一致。`preview/battery-contact-sheet.png` 为八图总览。
raise 第 0 帧是本机动画在视野下方的准备姿态。玻璃/能量使用 T011 的不透明
Metal 近似，次级颜色/法线及自发光未重现；完整来源仍在导出目录。

空目录复现：

```powershell
python tools/apexassets/battery_assets.py --out apex-data/assets/battery/repro_clean
python tools/apexpov/bake_battery.py --out apex-data/pov/octane_battery/repro_clean
python tools/apexpov/verify_battery.py --out apex-data/pov/octane_battery/repro_clean
python tools/fusepov/build_battery.py --out er-data/s3/octane_pov_battery/repro_clean
python tools/fusepov/verify_battery.py --out er-data/s3/octane_pov_battery/repro_clean
python tools/fusepov/verify_repro_battery.py --repro er-data/s3/octane_pov_battery/repro_clean --pack-repro apex-data/pov/octane_battery/repro_clean --asset-repro apex-data/assets/battery/repro_clean
```

`verify_repro_battery.py` 直接比较全部导出数据、正式/预览 FPOV、九个 DCX、
网格输入、PNG 和两份 HD 模板副本。不计算 SHA256，不改旧脚本或源输出。

## T022：Charge Rifle、破片手雷与双弹丸，完整模型 998

从仓库根目录运行：

```powershell
python tools/apexassets/defender_assets.py
python tools/apexassets/frag_assets.py
python tools/apexpov/bake_weapons.py
python tools/fusepov/build_weapons.py
python tools/apexpov/verify_weapons.py
python tools/fusepov/verify_weapons.py
python tools/fusepov/preview_weapons.py
```

新增脚本与 `weapons_templates/` 仅写 `er-data/s3/octane_pov_weapons/`；
`--out` 只接受其中的子目录。只读复用 T011/T020/T021 工具和输出。
BD 在全部 T021 数据后追加 MAINBODY 0、sight_front 1、reloader 1、heat_charge 0
四个步枪网格；HD 保留注射器/电池后追加手持手雷及弹丸 A/B。
AM/LG 四个包与 T021 逐字节一致。原 BD 节点与骨架表不变，HD 副本在原
32 个启用节点后加入六根 live 面部骨，再排列原其余节点；保留所有原节点绑定、
网格挂点、dummies、GX 和旧材质/贴图，重映射引用与两张骨架映射表。

`--matbin-bnd` 默认为 T021 的只读 allmaterial；输入快照后仅暂存目标冲突项，
生成并合并回原条目顺序/ID/Name/Flags，记录替换。弹丸 A/B 共用材质；
手持/弹丸源主贴图内容一致，也可共用 T011 Metal 近似条目。
热充能源只有 col/ilm，缺 nml/gls/spc 的源值为待定，使用 T005 中性缺省通道。
坐标、镜像、切线、绕序、权重、骨局部包围盒遵守 T011，无拟合变换或哈希。

`preview/` 有六张步枪图、四张手持手雷图、两张弹丸绑定图和两张 T021 回归图。
读取实际量化 FLVER 与序列化 FPOV；回归必须逐像素一致。
`weapons-*-audit.json`、`weapons-*-verification.json` 保存来源和独立读回证据。
完整动画包为 301 剪辑，运行时读取上限 256 必须由 Claude 接入时调整。

空目录复现和材质替换验收：

```powershell
python tools/apexassets/defender_assets.py --out apex-data/assets/defender/repro_clean
python tools/apexassets/frag_assets.py --out apex-data/assets/frag/repro_clean
python tools/apexpov/bake_weapons.py --out apex-data/pov/octane_weapons/repro_clean
python tools/fusepov/build_weapons.py --out er-data/s3/octane_pov_weapons/repro_clean
python tools/apexpov/verify_weapons.py --out apex-data/pov/octane_weapons/repro_clean
python tools/fusepov/verify_weapons.py --out er-data/s3/octane_pov_weapons/repro_clean
python tools/fusepov/build_weapons.py --out er-data/s3/octane_pov_weapons/material_reuse --matbin-bnd er-data/s3/octane_pov_weapons/package/material/allmaterial.matbinbnd.dcx
```

**Claude 返工（2026-10-06）**：`battery_tint.py` 在构建时把电池能量芯和窗口玻璃的反照率改成蓝色
（颜色为推断，结果写 `battery-tint.json`），电池预览因此不再与 T021 逐像素一致；预览回归只比 R-301 的 idle。
