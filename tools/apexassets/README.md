# Apex 默认角色资产导出（T001 暴雷、T014 动力小子）

动力小子（本机正式版默认 skin 0）：

```powershell
python tools/apexassets/export_assets.py --legend octane
python tools/apexassets/export_assets.py --legend octane --analyze-only
python tools/apexassets/verify_assets.py --legend octane
```

输出在 `apex-data/assets/octane/`，含身体、第一人称手臂、注射器、手持跳板、跳板道具，
以及骨架、材质、贴图、Cast/RSEQ/SMD/QC 动画和来源清单。`--analyze-only` 使用已导出的
文件；`--verify` 或 `verify_assets.py` 检查清单覆盖、尺寸、SMD/Cast 骨架与三角面、
RSEQ/Cast 时长以及 QC 活动。按 2026-10-05 用户要求，不计算资产 SHA256。

暴雷回归可导出到独立目录后直接比较内容：

```powershell
python tools/apexassets/export_assets.py --output-dir apex-data/assets/octane/fuse_check
python tools/apexassets/compare_exports.py
python -B tools/apexassets/test_metadata.py
```

`compare_exports.py` 按需直接比较文件内容、CSV 行集合和解压内容，不使用文件哈希。
源数据的 RTech GUID 是游戏自己的资源标识，保留在清单里。

从仓库根目录运行：

```powershell
python tools/apexassets/export_assets.py
```

输入：本机 Apex S30.1 的只读 RPak、StarPak、MBNK/MSTR。
输出：`apex-data/assets/`，不入库。不会启动游戏，不运行改变 git 状态的命令。
重复执行会覆盖同名产物；不会递归删除目录。

环境：Python 3.13、numpy、Pillow、matplotlib。当前机器已安装这些包。
冷启动工具构建还需要 VS2022 C++、Windows SDK 和网络。
`build_rsx.py` 自动下载固定 RSX 2.3.0 源码和上游指定且校验 SHA256 的
音频解码库，全部保存在此工具目录。`python tools/apexassets/build_rsx.py`
可以显式重建。原 `tools/rsx-2.3.0/` 中的可执行文件不改。
RSX 工作目录现在是 `assets/logs/rsx_runtime/`，缓存及诊断输出均留在资产目录。

## 工具副本的变更

`prepare_rsx.py` 对上游源码应用以下独立修正/扩展，不改变模型、动画或音频解码算法：

1. `--format-<fourCC> N` 暴露现有 Cast/RMDL/RRIG/RSEQ/SMD/材质/DDS 导出设置。
2. `-metadataonly -export` 完成 postload 后只写完整清单和依赖表。
3. 筛选导出列表时保留全局资产查找表，修复序列和依赖被过滤掉的问题。
4. `--exportexact` 和 `--audiostreams` 精确控制三个声音样本。
5. 按 MSTR 文件原名分目录，防止英文/国语共享名称和 GUID 的声音相互覆盖。
6. 修复材质及材质贴图导出器忽略 `--exportdir` 的硬编码路径。
7. ODL JSON 正确转义路径并补出 original/placeholder/pak GUID。
8. 对同一骨架下 basename 相同但资产路径不同的序列，保留原始完整路径，防止覆盖。

没有使用 `-exportdependencies`：它会连带导出默认模型的所有材质皮肤。
实际导出模型 skin 0 的材质及两套关联 3P 骨架的全部序列。
SMD/QC 中的皮肤表属于原始元数据，不代表已导出那些皮肤的模型或贴图。

## 读取与验证

```powershell
python tools/apexassets/export_assets.py --analyze-only
python tools/apexassets/inspect_assets.py "apex-data\assets\cast\mdl\Humans\class\medium\pilot_medium_fuse_LOD0.cast"
python tools/apexassets/verify_assets.py
```

`fuse_skeleton.json` 的变换保留导出 Cast 的坐标（Y 向上）和单位，四元数为 xyzw。
世界矩阵通过父骨链组合；不能按索引把 73 骨共享骨架、229 骨角色动画骨架
与 231 骨模型骨架直接对齐。
`fuse_sequences.json` 区分游戏序列与多个混合样本；无曲线的 Cast 占位样本
帧数为 null，不把它们伪造为有效运动。根运动判断只针对 Cast 根骨曲线，
不等价于原始 Source movement 数据是否存在。
事件、活动修饰符、混合空间、层信息保存在 `qc_metadata.json` 及原 QC/RSEQ。
材质用途直接抄自 `$textureTypes`；资源名称不可用时保留 RSX 的类型标记，
不猜测通道打包方法。

完整声音源清单为 `lists/audio_sources.csv.gz`（gzip CSV），含全部 v49 源记录；
`audio_named.csv` 是 RSX 能从本机 MSTR 读取的源子集。
音频事件只解析名称表，没有承诺完整解码事件播放图。
开火样本的 R101 名称对应武器定义中的 R101 事件族；事件到具体源的播放图
尚未独立解析，因此报告中明确区分事件引用与声音源样本。

## 许可证和来源

- `cast.py`：dtzxporter/cast，commit `363cb39`，未修改；MIT，见 `LICENSE.cast`。
- RSX：r-ex/rsx，2.3.0，commit `2c63d87`；AGPL-3.0，见 `LICENSE.rsx`。
  完整可重建源码及修改保留在 `rsx_source/`，第三方声明见 `THIRDPARTY.rsx.txt`。
- `rtech_hash.py` 复制自本仓库只读参考 `tools/apexdata/rtech_hash.py`，
  用于给 MBNK 原始名称计算与 RSX 一致的 RTech GUID。

首次调研时原 RSX 产生 `tools/rsx-2.3.0/exported_files/` 和 `latest_crash/`；
修正后的管线不会再写这些目录。清理命令被工具策略拒绝，残留需要由 Claude
按任务报告处理；没有绕过拦截。

## T021：护盾电池本机导出

从仓库根目录运行：

```powershell
python tools/apexassets/battery_assets.py
python tools/apexassets/battery_assets.py --analyze-only
```

只读使用现有 RSX 适配器和本机 `common.rpak`；不重建旧工具。输出仅在
`apex-data/assets/battery/`，`--out` 可选该目录内的子目录。导出电池模型全部
LOD Cast、raw、SMD/QC、108 骨 rig、109 骨模型、12 条序列的 22 个 Cast 混合样本，
以及三个材质和 17 张纹理的 PNG/DDS。`inventory.json` 记录来源、GUID、尺寸和
格式检查；复用 T014 的 SMD/Cast、RSEQ/Cast/QC 验证，不计算 SHA256。
`battery_layer` 原 Cast 无曲线，RSEQ 证明它是 224 帧恒等增量；原文件保持原样。

## U9：破片手雷视图模型与投掷物模型

```powershell
python tools/apexassets/frag_grenade_assets.py
# 在 git worktree 里：
python tools/apexassets/frag_grenade_assets.py --out apex-data/assets/frag_grenade --rsx tools/apexassets/rsx_source/bin/Release_NoGui/rsx.exe --retail apex-data/export/weapon/mp_weapon_frag_grenade.txt
python tools/apexassets/frag_grenade_assets.py --analyze-only
```

模型名取自武器设置（S3 R5R 与正式版的 `viewmodel`（MP_BASE）、`projectilemodel` 必须一致）：
`mdl/weapons/grenades/ptpov_frag_grenade_held.rmdl` 与 `mdl/weapons/grenades/m20_f_grenade_projectile.rmdl`。
导出到 `apex-data/assets/frag_grenade/`（目录名必须是 `frag_grenade`）：两个模型的 Cast/raw、材质与贴图、
视图模型骨架 `ptpov_frag_grenade_held.rrig` 及其 59 个序列（Cast、raw RSEQ）、SMD/QC；
`sequences/ptpov_frag_grenade_held.json` 列出每个序列的帧数、帧率、活动（RSEQ）和 QC 块里解析出的事件
（`AE_WPN_TOSS_RELEASE`、`AE_WPN_READYTOFIRE`、声音）。这是正式版（S30）资产；S3 的视图模型在 R5R 的包里，未对照。


## T022：Charge Rifle 与破片手雷本机资产

从仓库根目录运行：

```powershell
python tools/apexassets/defender_assets.py
python tools/apexassets/frag_assets.py
python tools/apexassets/defender_assets.py --analyze-only
python tools/apexassets/frag_assets.py --analyze-only
```

新增脚本及 `weapons_assets_common.py` 只读复用 T014/T021 的 RSX 和解析函数；
不重建 RSX，不改游戏安装。输出分别限于 `apex-data/assets/defender/` 和
`apex-data/assets/frag/`，`--out` 只接受相应目录内的子目录。导出全部本机 LOD、
Cast、raw、SMD/QC、骨架、序列、材质、DDS/PNG 和逐文件来源/格式清单。
`earlier-export-comparison.json` 直接比较早期导出的文件内容，不计算哈希。
手雷弹丸没有 rig；仍独立核对其 SMD/Cast 骨架、网格和全部 LOD。
