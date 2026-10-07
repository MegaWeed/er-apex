# T016：Fuse / Octane 第一人称动画包

所有名称、绑定姿态和动画来自本机 Cast/QC/RSEQ。FPOV v1 保持 102 个动画骨、51 个载体、39 个剪辑及原有二进制布局；Octane 只替换载体的逆网格绑定。运行时文件名仍为 `fuse_pov.anim`。

从仓库根目录执行：

```powershell
python tools/apexpov/bake_pov.py --legend octane
python tools/apexpov/verify_pov_pack.py --legend octane
```

输出为 `apex-data/pov/octane/fuse_pov.anim`、`fuse_pov_sequences.json`、`pov-bind-audit.json`。`--legend` 默认 `fuse`，保留原 Fuse 默认路径。`--out`、`--sequences-out` 支持显式指定输出；缺省的序列表放在动画包旁边。Octane 输出限制在 `apex-data/pov/octane/` 或供自包含 998 预览使用的 `er-data/s3/octane_pov/` 内。

绑定来源按 owner 名称匹配，优先使用所选手臂模型，再使用原 R-301：

- Fuse：`apex-data/assets/cast/mdl/Weapons/arms/pov_pilot_medium_fuse_LOD0.cast`。
- Octane：`apex-data/assets/octane/cast/mdl/Weapons/arms/pov_pilot_medium_stim_LOD0.cast`。
- 枪械：`apex-data/pov/cast/mdl/techart/mshop/weapons/class/assault/r301/r301_base_v_LOD0.cast`。

owner 不在两个所选模型时，保留当前完整 Fuse pack 的精确 f32 逆绑定，并记录载体；禁止任何所选手臂顶点使用该 owner。本机 Octane 无需此回退。正权重缺 owner 或 owner 为 null 会立即失败。

验证器检查格式、EOF、骨架、全部剪辑和本机动画元数据、增量模式、重复混合样本、序列表、RSEQ 和四个常量 delta 样本，并直接核对所选模型绑定。Octane 与当前完整 Fuse pack 比较时只屏蔽每个逆绑定的 28 字节，再比较其余全部字节；载体名字、owner、ER 绑定和动画载荷均不得变。审计列出每个有字节变化的载体、owner、逆绑定平移差、owner 绑定平移差和旋转角差。角度以归一化四元数对应的矩阵计算，包含导出精度级差异。本机共有 44 个变化项。

不计算 SHA256。四个历史空 Cast 的来源改用路径、尺寸、空曲线/帧率/循环格式检查，并与包中恒等 delta 和 RSEQ 权重直接比较。若本机 Cast 仍未恢复，恢复仅写入指定输出旁的 `cast_recovery/`，不会修改只读来源或 `cast_original_empty/`。

Fuse 回归只写 T016 专属目录：

```powershell
python tools/apexpov/bake_pov.py --legend fuse --out apex-data/pov/octane/fuse_check/fuse_pov.anim --sequences-out apex-data/pov/octane/fuse_check/fuse_pov_sequences.json
python tools/apexpov/verify_pov_pack.py --legend fuse --new apex-data/pov/octane/fuse_check/fuse_pov.anim --sequences apex-data/pov/octane/fuse_check/fuse_pov_sequences.json
python tools/fusepov/verify_fuse_regression.py
```

`idle_0` 是增量动画；998 持枪预览使用本机 QC 指定减去的 `ads_in_0` 第 0 帧再叠加 `idle_0` 第 0 帧，并且只应用一次导出根旋转。参考帧 0 的选择仍是本机数据和握持几何支持的推断，QC 未保留明确 subtract 帧参数。运行时接入及游戏内验收由 Claude 完成。

## T020：Octane 技能道具，FPOV v2（修订 4）

从仓库根目录执行：

```powershell
python tools/apexpov/bake_ability.py
python tools/apexpov/verify_ability.py
```

新增脚本及 `ability_common.py` 只读复用当前工具。输出仅为 `apex-data/pov/octane_ability/`；`--out` 可以指定该目录内的子目录。生成 `fuse_pov.anim`、`ability_sequences.json`、`ability-pack-audit.json`、`ability-pack-verification.json`。

FPOV v2 在每个载体的 v1 字段后增加 group 字节：0 手臂、1 R-301、2 Base 注射器、3 手持跳板。保留原始 102 骨、51 载体的全部 v1 字段及 39 剪辑对原骨的字节；新增 24 骨、18 载体，合计 126 骨、69 载体、107 剪辑。技能数据为 43 个 stim、6 个 pad；R-301 指定序列共 23 样本，其中四个原剪辑数据一致并原样保留。

分别复制道具专用的 `ja_c_propGun → weapon_bone → def_c_base` 祖先链；技能剪辑中原同名骨权重为 0，避免道具动作移动步枪。所有 QC 权重（包括 absolute 的屏蔽权重）、活动、混合参数、淡入淡出、事件帧及秒数保存于序列表；未给出的参数为 null。排除序列名称含 surge 的动作及 Surge 网格，不改来源中的活动修饰符或事件。

修订 4 及项目负责人追加授权：HD/LG 模板副本添加 live 参考绑定的 20 根 Xtra 骨，动画包依序使用其中 18 根；全部新旧载体必须在 `er-data/skeleton/c0000_live_skeleton.json` 的 150 骨名单中。动画烘焙的 ER 绑定采用模板 Master 与 live Xtra 局部参考变换，构建后再与实际 FLVER 核对。

`idle_onehanded_1.cast` 无曲线，本机 RSEQ 的 ANIM_VALID 清零、ANIM_DELTA 置位证明它是恒等增量；按 T016 规则保留原空 Cast，只在新包中写入其帧数、帧率、权重及恒等值，并记录 RSEQ 来源。未计算 SHA256，未修改当前脚本或源包。

全部载体检查已纳入 pack 验证器：缺失 live 名称和主身体载体都会拒绝。实际旧包的 group 1 载体索引为 2、3、4（L_Pectoral、R_Pectoral、Collar）；其余 48 项为 group 0，保持实际 v1 顺序。

## T021：护盾电池 FPOV v2，group 4

从仓库根目录运行：

```powershell
python tools/apexassets/battery_assets.py
python tools/apexpov/bake_battery.py
python tools/apexpov/verify_battery.py
```

输出仅在 `apex-data/pov/octane_battery/`，`--out` 可选其中的子目录。新增
`battery_common.py`、`bake_battery.py`、`verify_battery.py`，只读复用 T020 工具。
完整保留 T020 的 126 骨、69 个含 group 的载体记录和 107 个旧剪辑载荷；
新增五根电池独立分支骨、两个 group 4 载体和 22 个本机样本，合计 131 骨、
71 载体、129 剪辑。旧剪辑中的新骨权重为零，absolute 用 bind，additive 用恒等。
两个正权重骨按总顶点权重分配：`def_c_top` → Xtra 02_09，`def_magazine` → 02_10。
同名原骨由 `battery:` 副本隔离；电池剪辑中注射器和跳板新增骨全部权重为零。
`battery_sequences.json` 保存活动、混合参数、帧数/帧率、loop/additive、完整权重、
零权重骨、淡入淡出、snap、QC 事件和秒数。空曲线的 `battery_layer` 用本机
RSEQ 的 ANIM_DELTA/ANIM_VALID 与 QC 权重证明恒等增量，不修复源 Cast，不算 SHA256。

## T022：Charge Rifle、手持手雷与双弹丸，groups 5–8

从仓库根目录运行：

```powershell
python tools/apexpov/bake_weapons.py
python tools/apexpov/verify_weapons.py
```

输出限于 `apex-data/pov/octane_weapons/`；`--out` 支持其中的子目录。
新增 `weapons_common.py`、`bake_weapons.py`、`verify_weapons.py` 只读复用 T020/T021。
保留 T021 的 131 骨、71 个含 group 的载体和 129 个剪辑对旧骨的精确字节，
追加 39 骨、18 载体与 172 样本，共 170 骨、89 载体、301 剪辑。
步枪与手持手雷分别使用 `cr:`、`frag:` 独立武器祖先分支；两份
`fragproj_{a,b}:static_prop` 在全部剪辑中权重为零。groups 5/6/7/8 分别为
步枪、手持手雷、弹丸 A/B。旧剪辑中新骨使用零权重及 bind/identity。
按任务排除序列；三对步枪重名序列按 QC 顺序用 `_b` 区分，完整保留其样本。
`defender_sequences.json`、`frag_sequences.json` 保存活动、混合参数、帧数/帧率、
loop/additive、逐骨权重、淡入淡出、addlayer、QC 事件及秒数。
`weapons_carriers.json` 保存载体绑定、源模型枪口/弹壳/基骨/弹丸绑定，以及
祖先载体合并的最大相对运动。没有修复或覆盖本机 Cast，没有哈希计算。

**运行时接入前必须由 Claude 调整 `src/spike/pov/pack.rs` 的 256 剪辑读取上限：
完整任务数据有 301 剪辑。** 本任务不写运行时代码；工具按 FPOV v2 的 u32 数量字段
完整读写，审计明确记录这项兼容性要求。

**Claude 返工（2026-10-06）**：步枪载体改为 10 根叶骨（`weapons_common.RIFLE_CARRIERS`），
不再用 `L_Forearm`/`R_Forearm`（它们是组 0 手部载体的父骨，隐藏时缩放会传给子骨）；
`def_c_detailC/D` 并到 `def_c_base`。包现在是 170 骨、87 载体、301 剪辑。运行时上限已调到 1024。
