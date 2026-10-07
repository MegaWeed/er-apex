# fuse.anim v0 / er-apex-anim

T006：从本机 Cast/QC 导出 MVP 动作，供无游戏依赖的 Rust 库读取与采样。
保持 Apex 骨架空间、英寸和 Cast 导出坐标系；不转换到 ER，不做 c0000 重定向。

## 复现

在仓库根目录运行：

```powershell
python tools/fuseanim/export_anim.py
```

脚本通过自身路径定位仓库，只读取 `apex-data/assets/`，派生数据只写
`apex-data/anim/`；Rust 编译产物只写 `deps/er-apex-anim/target/`。
Python 需要本机已安装的 NumPy、Pillow；Rust edition 2024，无第三方 crate。
本任务没有联网或下载依赖。Cast MIT 读取器和许可证复制自 `tools/apexassets/`。

默认命令生成二进制包、清单、逐帧校验数据、三张 PNG，并运行两个 Rust 校验：

- `fuse.anim`：30 序列、52 个子剪辑、231 骨；精确字节数见 `verification.json`。
- `selected_sequences.json` / `.md`：原始资产路径、GUID、骨架、样本路径/帧数、
  循环标志、活动/修饰符、事件、混合坐标与原始 QC。
- `validation.bin`：全部 6,152 个整帧/半帧姿态，以及原始根轨道区间增量。
- `validation.json`：每子剪辑首帧、中间、末帧，共 156 个姿态，便于文本检查。
- `rust_validation.json` / `rust_json_validation.json`：独立 Rust 采样误差。
- `verification.json`：尺寸、SHA-256、量化误差、骨架 SMD 核对、待定项。
- `fuse_run_rifle_F_frames.png`、`fuse_slide_rifle_frames.png`、
  `mp_pt_medium_WallMantle_Level_frames.png`：六帧骨架剪影；保留根运动高度，
  仅在视图中居中水平位移。只画主要关节，不把辅助骨/装备骨当作人体四肢。

`--skip-rust` 只用于导出调试，不能作为完整验收。独立复跑：

```powershell
cd deps/er-apex-anim
cargo test --release --offline
cargo fmt -- --check
cargo clippy --all-targets --offline -- -D warnings
cargo bench --offline
cargo run --release --offline --example validate -- ../../apex-data/anim/fuse.anim ../../apex-data/anim/validation.json ../../apex-data/anim/rust_json_validation.json
```

基准默认读取仓库的生成包，也支持 `FUSE_ANIM_PACK` 指定包路径。
每种动作预热 1,000 次、测量五组各 30,000 次，变化的时间包含小数帧，
`black_box` 保留工作；报告单次完整 231 骨姿态的中位数/min/max，断言中位数 <20 μs。

## Cast 语义与映射证据

本机源数据为 `assets/fuse_skeleton.json`、`fuse_rigs.json`、`fuse_sequences.json`、
`qc_metadata.json` 及对应 `.cast`/`.qc`。曲线单位/坐标不作额外转换，TRS 为父骨局部，
四元数 xyzw，世界矩阵为 `parent_world @ local_TRS`。

读取器 `cast.py` 的 `Bone.LocalPosition/LocalRotation`、`Curve.Mode`、
`Curve.AdditiveBlendWeight` 与本机 RSX 源码提供交叉证据：

- `tools/apexassets/rsx_source/src/core/mdl/modeldata.cpp:1708`：
  `ANIM_DELTA` 导出为 additive，其他为 absolute；每骨权重来自 `seqdesc->weight(i)`。
- 同文件 1730–1767：无动画通道时仍导出常量曲线；absolute 常量是 rig 静止值，
  additive 为零平移、单位四元数、单位缩放。因此 Cast 中的平移曲线不必都是原始作者的活动轨道。
- `animdata.cpp:1049`：delta 的解码默认值为零位移/单位旋转/单位缩放；
  `animdata.cpp:883` 的 `ParseAnimDesc_Origin` 会把原始 movement 叠加到第零骨，
  并施加导出器坐标调整。导出后的根变换必须保留，不能仅按 model rest 推断轴向。
- 本任务 52 样本均有非空曲线，无 mode override；仅两条开火序列为 additive。
  对未支持的 relative、混合模式、部分向量通道、空样本、override，导出器报错。

absolute 直接替换局部通道，不再加一次静止值。additive 按每通道权重 `w`：

```text
translation = base.translation + w * delta.translation
rotation    = normalize(base.rotation * slerp(identity, delta.rotation, w))
scale       = base.scale * (1 + w * (delta.scale - 1))
```

`sample` 每次先填满 **模型静止姿态**，保证缺失骨骼不会继承前一帧垃圾；
absolute 缺失通道保留该静止值，additive 缺失通道为无操作。
`apply` 则在调用者现有姿态上求值，缺失骨骼/通道保持输入，适合开火叠加。
静止姿态上的 additive 采样仅用于独立预览/验证；实际持枪开火应叠加到 idle/run 等基础姿态。

映射严格按名字，不按 rig 索引。73 骨共享骨架全数映射；229 骨中 226 骨映射到模型，
三个模型不存在的名字 `def_c_backShell`、`def_c_backShellCap`、`def_l_eyeball`
不进入姿态表，逐剪辑记录在 metadata 中。模型独有
`def_r_cuff_1..4`、`def_r_outterwrist` 保留模型局部静止值，仍继承动画父骨。
已断言所有共同骨的父骨名字一致。模型顺序始终为原始 231 骨。

## 选择与混合样本

完整 30 序列清单见生成的 `selected_sequences.md`，其中所有活动/事件逐字取自对应骨架的 QC。
常见短标签不用于跨骨架拼接；通过序列完整资产路径和骨架确定 QC。

v0 把多样本命名为 `sequence#0`、`#1`、`#2`，单样本保持序列名。
保留 sample index/count、QC sample token、blend 参数及坐标，没有在库里实现 blend space：

- walk/run/F、crouch/F、jump/F、float/F：`move_yaw` = -90 / 0 / 90；
  QC 样本 token 分别是 right / forward / left。
- 共享 walk/B、run/B、crouch/B、jump/B、float/B：`move_yaw_backward` = -90 / 0 / 90；
  QC token 分别是 backward-left / backward / backward-right。
- sprint：`sprinttilt` = -1 / 0 / 1，token 是 left / forward / right，不能按 move_yaw 解释。

对应方向的 walk 与 run 的 QC 引用同一组三个动作 token，活动不同。
实际 Cast 数值仍有差异（F 最大平移分量差约 0.249256 英寸，B 约 0.133858 英寸），
不能按 QC token 合并或去重；本包分别保留所有原始样本。
后向实际使用共享骨架的 `medium_walk_rifle_B` / `medium_run_rifle_B`；
不要制造不存在的暴雷专名 B/L/R 序列。蹲伏 idle 在 fuse rig 内实际名为 `mirage_crouch_rifle`，
其活动为 `ACT_MP_CROUCH_IDLE`；独立暴雷专名 rifle 蹲伏 idle 待定。
本包不执行 QC 中 AIM/脸部 addlayer 和活动选择，原文保存在 metadata。

## 字节格式

**小端、无结构体填充**。所有计数都先校验剩余字节。字符串 `str` 是
`u16 byte_length + UTF-8 bytes`，无 NUL。浮点为 IEEE 754 f32；文件总长为 u64。
magic/version/长度/CRC 任一不符均拒绝，CRC32 为标准 IEEE（Python `zlib.crc32`），
只覆盖偏移 32 起的 payload。

| 头部偏移 | 类型 | 值 |
|---|---|---|
| 0 | 8 bytes | `FUSEANIM` |
| 8 | u32 | version = 0 |
| 12 | u64 | 文件总字节数 |
| 20 | u32 | bone_count（本包 231） |
| 24 | u32 | clip_count（本包 52） |
| 28 | u32 | payload CRC32 |

骨骼表连续 bone_count 项：`name:str, parent:i32, translation:3*f32,
rotation:4*f32, scale:3*f32`。parent=-1 表示无父骨，其余必须指向先前骨骼。
名字唯一，静止旋转必须接近单位四元数，解析时归一化。

随后连续 clip_count 项，每项先存 `u32 block_length`（不含长度字段本身），再存：

```text
name:str, sequence:str, source_cast_path:str, rig_asset_path:str
guid:u64, fps:f32, frame_count:u32, flags:u32
sample_index:u32, sample_count:u32, track_count:u32
metadata_json:str
root_bone:i32                     (-1 = 不分离根轨道)
if root_bone != -1:
    root_translation:channel3
    root_rotation:channel4q
tracks[track_count]:
    model_bone:u16, mode:u8, channel_mask:u8
    translation_weight:f32, rotation_weight:f32, scale_weight:f32
    translation:channel3, rotation:channel4q, scale:channel3
event_count:u32
events[event_count]: frame:u32, name:str, parameter:str
```

flags 位 0 = Cast 原始循环标志，位 1 = 存在 additive 轨道；其他位必须为零。
mode 为 0 absolute / 1 additive；mask 的 T/R/S 位分别为 1/2/4，必须与非空通道一致。
各权重为 [0,1]。根骨必须无父骨，不得又出现在普通轨道中；每骨只能一条轨道。
事件帧必须 < frame_count 并按帧非降序，允许同帧多个事件。
metadata 是 UTF-8 JSON 原文；库把它作为 opaque 字符串，不引入 JSON 运行时依赖。

`channel3` 为 `u32 count + count * 3*f32`，`channel4q` 为
`u32 count + count * 4*i16`。count 仅允许 0、1、frame_count：
0 表示缺失，1 表示常量，其余每帧一值。只存 Cast 中存在的平移通道；
常量化按实际编码后的完全相等值判断，不设置近似丢弃阈值。缩放同理。

旋转采用 **四分量 i16**（8 bytes），不是 smallest-three：
`round(normalize(q)*32767)`，还原后再归一化；禁止 -32768、零/异常范数。
选择此方案便于审计、无隐含符号/分量索引，当前包仍小于 3 MiB。
单分量绝对误差 ≤1/(2*32767)，四分量向量误差 ≤1/32767，
归一化后的保守角误差界为 `4*asin(1/32767)`，即 **0.00699433°**。
所有真实旋转关键帧实测最大 **0.00328966°**。
该界针对一个旋转值，根增量涉及多个量化旋转的乘积，其误差可能累积。

## 时间、采样、根运动与事件

Rust `Pack::parse(&[u8]) -> Result<Pack, Error>` 拥有解析后数据，源 buffer 可释放。
轨道在 parse 时解码；sample/apply 不分配内存，输出切片至少 bone_count 项，尾部不修改。
先用 `clip_by_name` 找 usize ID，再用 `clips()[id]` 查看元数据。

```rust
# use er_apex_anim::{Pack, Trs};
# fn demo(bytes: &[u8]) -> Result<(), Box<dyn std::error::Error>> {
let pack = Pack::parse(bytes)?;
let run = pack.clip_by_name("fuse_run_rifle_F#1").ok_or("missing run")?;
let fire = pack.clip_by_name("fuse_idle_rifle_fire").ok_or("missing fire")?;
let mut pose = vec![Trs::default(); pack.bones().len()];
pack.sample(run, 0.25, true, &mut pose)?;
pack.apply(fire, 0.1, false, &mut pose)?;
let motion = pack.root_motion_delta(run, 0.25, 0.27, true)?;
let events = pack.events_between(run, 0.25, 0.27, true)?;
# let _ = (motion, events);
# Ok(())
# }
```

非循环时间钳制到 `[0,(N-1)/fps]`；循环周期为 `(N-1)/fps`，末帧是 Source 的
cycle=1 端点，与下一轮首帧接壤，不额外加一帧。单帧剪辑周期为 1/fps。
循环支持负时间；非有限时间或超过 10^9 周期的时间返回 InvalidTime。
平移/缩放线性插值，旋转 shortest-path slerp；极小角使用归一化线性插值。

从 **jx_c_delta（模型索引 0）** 分离 absolute 根平移和旋转，不把骨盆当根运动。
sample 输出该根骨的 Cast 首帧变换 G0，其他骨骼仍是原始父局部值。
根轨道完整另存，`root_motion_delta(start,end,looping)` 返回区间刚体增量
`G(start)^-1 * G(end)`，坐标在区间起点根轴，单位英寸；不自动乘米制尺度、不写游戏位置。
需要完整世界轨道时，将连续增量右乘到起始根变换；控制器自行决定如何采用位移，
避免 KCC 移动与动画位移重复应用。

循环累计 SE(3) 而非仅做端点平移相减，因此转向/多轮/逆向区间也正确。
计算时先消去起止时间共同经过的循环，再求剩余循环幂，避免长播放时间下的大位置相减。
无根轨道（例如 additive fire）返回单位增量。
Cast 实际已有 movement：run 中心样本 71 帧端点位移 **424.774963 英寸**；
不能沿用 T001 摘要里的“该根无运动”。`animdata.cpp:883` 解释了这些 movement 的来源。
旧 `tools/apexassets/inspect_assets.py:158` 检查的是 px/py/pz，真实 Cast 使用 tx/ty/tz，
导致根平移和骨盆平移摘要漏报；本任务直接读取实际 tx/ty/tz，没有修改只读工具。

事件从 QC 提取、保持名字和参数，不过滤看似奇怪的脚本/机器人事件，也不执行回调。
`events_between` 返回 `(start,end]`，跨循环返回所有发生项，按绝对秒排序；
开始播放时用 `(-epsilon,0]` 获取 frame-0 事件。末帧事件和下一循环 frame-0 事件
若同在边界，两者都会返回；同帧顺序稳定。反向区间返回错误，最多返回 1,000,000 项。

## 验证范围与限制

Python 直接解码 Cast，先按本契约求原始局部姿态，再与 Rust 实际解析/采样比较；
整帧和所有半帧都覆盖全部 231 骨。根轨道另外比较从零到每个时间点及再跨一轮的增量。
`validation.bin`：`FAVAL001` magic、u32 bone_count/record_count，随后每记录
`u32 clip_id, f64 time, bone_count*10*f32 TRS, 7*f32 nonloop_root_delta, 7*f32 loop_root_delta`。
JSON 是 `[1,bone_count,case_count,cases]`；每 case 为
`[clip_id,time,[[TRS10],...],[root_delta7],[loop_root_delta7]]`。
示例只为这个受控的纯数字数组 JSON 读取数值，不把它当通用 JSON 解析器。

验收阈值：局部旋转 <0.02°、局部平移/缩放 <0.0001；
根增量旋转 <0.02°、平移 <0.05 英寸（量化根方向误差会影响长位移）。
实际局部最大旋转 0.003289°、平移 0 英寸（浮点验证精度内）；
根增量最大旋转 0.007577°、平移 0.003413 英寸。

两个 rig 的 SMD 静止姿态均按 Euler 独立解算世界位置，全部 73/229 骨比较，
最大误差约 0.00016242 英寸。已扫描 QC 的 **2,477 个动画 SMD 引用，实际存在 0 个**。
所以对应动作的 SMD 动态世界位置核对仍为 **待定**，没有以静止验证冒充动态验证。
后续补出动作 SMD 后再增加这条独立解码链路。PNG 只核对明显骨架动作，不证明原游戏
自动层、武器 attachment、IK 或活动选择逻辑；这些属于运行时集成。
