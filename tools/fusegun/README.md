# T008 / T019：Fuse 或 Octane 手部护甲并入 R-301

在仓库根目录运行；`--legend` 可选 `fuse`、`octane`，默认 `fuse`。所有新产物只写入本次独占目录 `er-data/s3/octane_gun/`。旧 `er-data/s3/fuse_gun/` 只作为回归输入。

```powershell
python tools/fusegun/build_gun.py --legend octane
python tools/fusegun/verify_gun.py --legend octane
python tools/fusegun/preview_gun.py --legend octane
python tools/fusegun/regression.py --legend octane
```

Octane 默认输出 `er-data/s3/octane_gun/`，默认材质输入为只读的 `er-data/s3/octane_pov/package/material/allmaterial.matbinbnd.dcx`。`--matbin-bnd <path>` 可指定另一份本机材质包。输入先复制并直接比较；私有构建副本临时移除所有生成材质的同名条目，最终恢复原条目的顺序、名称、ID、标志、压缩元数据和内容。已有身体及 POV 材质不重写，缺少的材质追加；已有枪械材质 `P[AM_M_0999]_r301_base_main` 用生成结果替换并记录。

为保持 T008 的 Fuse 包内容，Fuse 默认仍使用 T005 的原始材质输入 `er-data/s3/fuse/inputs/material/allmaterial.matbinbnd.dcx`，默认输出改为本次允许写入的 `er-data/s3/octane_gun/fuse_check/`：

```powershell
python tools/fusegun/build_gun.py
python tools/fusegun/verify_gun.py --legend fuse
python tools/fusegun/verify_repro.py --legend fuse
python tools/fusegun/regression.py --legend fuse
```

`verify_repro.py --legend fuse` 默认直接比较旧 T008 产物：九个 DCX、全部网格输入、贴图、六张预览应逐字节一致；旧握持数据只允许来源摘要字段改成路径、大小及角色说明。指定不同材质输入时，可用 `--reference` 指定与该输入对应的基线。

空目录复现与一致性核对：

```powershell
python tools/fusegun/build_gun.py --legend octane --out er-data/s3/octane_gun/repro
python tools/fusegun/verify_repro.py --legend octane --repro er-data/s3/octane_gun/repro
```

全部脚本接受 `--out`，并拒绝此独占目录以外的输出。`--skip-previews` 只省略构建时的渲染。预览可独立重跑；回归的 `--only legend` 仅验证所选角色，`--only builder` 仅执行 T003。原 T005 验证输出通过 `DEFAULT` 重定向到副本；原 T003 的摘要元数据仅在内存中改成文件大小，原断言保留，不编辑只读工具。

## 数据与变换

依赖本机 T005/T015 的完整输入和模板、T001 的 R-301 Cast/QC/材质导出，以及预构建的 `ertool.exe`、`erextract.exe`、texconv、RSX 和现有 SoulsFormats DLL。Python 使用 NumPy/Pillow，材质辅助程序使用本机 .NET 8；其 bin/obj 和 NuGet HTTP 缓存均在本次输出目录内，用户缓存只使用指定的 `.dotnet`、`.nuget`。不构建或修改 RSX、ertool、erextract，不生成只读 Python 工具的字节码缓存。

Octane 从本机 `apex-data/assets/octane/lists/core_named.csv` 查找 `octane_idle_rifle.rseq`，确认它属于身体的 `pilot_medium_stim.rrig` 依赖，再用 RSX 精确导出待机和父 rig；RSX 输出、清单及运行目录全部放入输出的 `rsx/`。不调用存在空指针问题的独立 raw ASEQ 导出。找不到本机序列时记录「待定」，回退到 T008 的 Fuse 握持，并明确标记预览使用按骨名套用的 Fuse 动作。

```text
G = inverse(W_def_r_wrist) @ W_ja_c_propGun    # selected idle frame 0
H = inverse(E_AM_R_Hand) @ P_wrist @ Q @ G @ inverse(Q)
bind_vertex = E_AM_R_Hand @ H @ Q @ source_vertex
```

Octane 使用 T015 的对齐，Fuse 使用 T005 的对齐；重新计算的 Q/P 必须与对应 `align.json` 完全相同。R-301 只保留 `body_0_r301_base_main` 和前机瞄 `r101_sight_front_on_1_r301_base_main`（studio 1）；15 个倍镜、消音器和激光网格移除。枪的四个骨索引槽都是 `R_Hand`，权重 `[1,0,0,0]`；原 AM 数组、材质定义和贴图保留，HD/BD/LG 原样复制并逐字节验证包。

## 输出

- `package/parts/{hd,bd,am,lg}_m_0999{,_l}.partsbnd.dcx` 和 `package/material/allmaterial.matbinbnd.dcx`：完整模型 999，共九个压缩包。
- `fusemesh/`、`textures/`、`inputs/`：构建输入、枪械贴图、原始材质快照与私有构建副本。
- `grip.json`：Apex/ER 握持矩阵、相对 `R_Hand` 的枪口与方向、逐帧统计、来源路径/大小；Octane 还含 Fuse 握持及两骨绑定关系的比较。
- `bodygroups.json`、`geometry-summary.json`、`texture-audit.json`、`source-manifest.json`：筛选、数量、包大小、材质近似和来源。
- `material-bundle-*.json`：输入条目的保留、追加、同名替换以及独立直接字节比较。
- `preview/`、`preview-verification.json`：ER 绑定姿态和实际待机首帧的正/侧/手部近景，共六图；青色为右手，橙色为枪口和枪管方向；验证姿态后的枪与直接 Cast 变换一致。
- `verification.json`、`readback-verification.json`、`readback/`、`logs/`：八个 FLVER、MATBIN、TPF 的独立读回、权重、引用及包围盒核验。
- `regression/`、`regression-verification.json`、`reproducibility.json`：原工具回归及直接内容比较，全部不计算内容摘要。

## 限制

整枪刚性跟手，弹匣、枪栓和机瞄不动；高低模及六个面组均复用 LOD0。固定握持取待机首帧，不能复现其他动作的相对变化。Octane QC 的 `octane_combat_idle_aims` 叠加层未合成；预览使用实际导出的基础剪辑。ER 绑定姿态下枪随右手斜向下；朝前在持枪待机姿态验证，需要相应游戏动作。没有左手 IK、手指闭合或瞄准修正。法线绿通道、金属度近似、AM Rich 材质仍沿用 T005 待定项。未启动游戏，运行时验证由 Claude 完成。
