# T007 / T018 本机 R-301 与 Octane 音效导出

从任意工作目录运行（示例从仓库根目录）：

```powershell
python tools/fuseaudio/export_audio.py
python tools/fuseaudio/export_audio.py --set octane
```

依赖 Python 3.13、numpy（本机已有），以及 **T001 已生成**的
`apex-data/fuse_data.json`、武器原始定义、`assets/qc_metadata.json`、
`assets/lists/audio_events.csv`、`audio_named.csv`、`audio_sources.csv.gz`，
以及 `tools/apexassets/rsx_source/bin/Release_NoGui/rsx.exe`。
缺失 T001 工具时报告错误，不在只读路径重建。

只读取本机 `E:\SteamLibrary\steamapps\common\Apex Legends\audio\ship\`。
默认 `--set r301` 保留 T007 的输出目录 `apex-data/audio/`。
`--set octane` 的所有游戏派生数据、RSX 工作目录和日志均写入
`apex-data/audio/octane/`，播放 WAV 在该目录的 `playback/` 中。
Octane 的名称引用额外读取本机
`F:\R5Reloaded\R5R Library\LIVE\platform\scripts/` 中的 S3 武器设置与脚本。
`--output-dir PATH` 可用于另存一套输出；Octane 的输出路径必须位于
`apex-data/audio/octane/` 内，路径在写入前解析并检查。
所有游戏派生数据、RSX 工作目录和日志写入所选输出目录，
不会启动游戏、注入进程或改变 git 状态。同名产物可重复覆盖，不递归删除目录。
删除/移走旧 `apex-data/audio` 后，上述命令可重新生成全部产物。

- `raw/general_stream/*.wav`：RSX 原始 float32，保留 1/2/6 声道。
- `r301/*.wav`：播放用 float32 stereo，保留原采样率及帧数。
- `manifest.json`：版本 1，主声音及每层试听名、变体、格式、时长、事件 GUID、引用字段。
- `event_map.json`：字段 → 事件 GUID/动作偏移 → 状态/选择器树 → 原始源索引及 MSTR 头/数据偏移。
- `source_inventory.json`：每个唯一源的来源路径、字节数、原始/下混格式、峰值、RMS、衰减系数；不计算内容哈希。
- `mapping.md`：完整逐条映射表，可直接用于 Claude 的接入审查。
- `verification.json`、`logs/run.json`、`logs/export.log`：头部、长度、帧数、非静音及实际命令验收。

事件从武器 `all_params`、原始定义的 `Mods.altfire`、共享 3P reload QC
取出，而非按名称族猜测源。MBNK v49 每个事件的两项 u16 长度及 LZB
压缩动作得到严格检查；解析 action 0 的状态/源选择器和 action 8 的事件引用。
选择器叶节点的索引直接查完整 MBNK 80-byte 源记录，并与 T001 gzip 完整源表
逐字段核对。**不用 RSX 过滤可用源后产生的 name-vector 索引。**
完整动作与选择器证据保留，不将多个 layer 自动混成随机源池。
权重和选择器类型已记录，游戏运行时控制器/距离混合语义仍待定。

主播放名采用第一个 play action 的核心层，`fire_loop_3p` 使用该 action 的
selector #1（实数据中为 close 源）；其他层以 `*_layerN` 名供试听。
`fire_3p` 来自 **Mods.altfire.fire_sound_2_player_3p** 的真实单发事件核心，
default automatic 的 3P 首发字段为空；没有伪造该字段的源。
首发、连发、尾音、空仓、ADS、低弹药、换弹六个动作，以及 QC 中额外的
RE45 插匣声音均保留。命中、爆头、击杀未在当前武器/player/global 设置找到
明确引用，manifest 标「待定」，不会从音频事件名称猜一个替代品。

Octane 导出任务单列出的 11 个事件：兴奋剂开始、持续、结束，战术就绪、
技能未就绪，跳板投掷、展开、弹射、上升风声、二段跳、终极就绪。
每个事件先检查本机 S3/正式版引用，然后不区分大小写查本机事件表，记录实际拼写。
主播放名使用事件名的小写，核心沿用第一个 play action；
每个 play action 另提供 `_layer0`、`_layer1` 等试听名（`_layer0` 含核心动作）。
不同选择器、距离层、控制器不等同于已经确认的随机池；
完整树、权重及未知控制字段的原始动作字节保留在 `event_map.json`。
`mapping.md` 给出各播放名的具体源索引和引用位置。
缺事件或本机缺源时登记「待定」，不换用其他事件或按源名称猜替代品。

Octane `source_inventory.json` 和 manifest 变体中的 `loop_data` 保存原始及播放
WAV 的 `smpl` 循环标记，以及直接读取的 MBNK 源标记（名称、帧位置、记录偏移）。
没有标记只说明相应源表/WAV 未声明标记。
Miles 动作的循环开关、次数、区间尚未确认，明确标「待定」。
现有 `deps/er-apex-audio` 每次 `play()` 播放一次完整 WAV，不自动循环。
S3 `mp_ability_heal.nut` 在开始时发出持续音，并在 `duration - 2` 秒时发出结束预警；
宿主应按脚本时机调度，完整 Miles 的动作延迟、音量/音高曲线与层混合仍需接入。

## 六声道下混

**待定：本机导出 6ch WAV 的实际游戏通道顺序、Apex 专用系数尚未确认。**
当前可替换默认假设顺序 `[FL, FR, FC, LFE, SL, SR]`，使用：

```text
L = (FL + 0.70710678 * FC + 0.70710678 * SL) / 2.41421356
R = (FR + 0.70710678 * FC + 0.70710678 * SR) / 2.41421356
LFE = 0
```

0.70710678 是本工具选用的中心/环绕 -3 dB 默认系数，**不是已证实的游戏系数**。
每行按绝对系数总和归一化提供峰值余量；mono 复制到 L/R，stereo 保持。
若输出峰值仍超过 0.98，整体等比例衰减至 0.98，系数写入清单；不逐采样剪波。
原始 WAV 完整保留以便替换。自定义矩阵 JSON 应是有限数值 2x6，
仍会按每行绝对值和归一化：

```powershell
python tools/fuseaudio/export_audio.py --analyze-only --matrix PATH.json
```

## 检查

```powershell
python tools/fuseaudio/test_export.py
python tools/fuseaudio/export_audio.py --analyze-only
python tools/fuseaudio/export_audio.py --set octane --analyze-only

# T018 的 R-301 回归：不覆盖只读的 T007 音效集。
python tools/fuseaudio/export_audio.py --set r301 --output-dir apex-data/audio/octane/r301_check
python tools/fuseaudio/compare_r301.py
```

导出命令自动检查 RIFF 声明长度、每个 chunk 边界、float32/frame 对齐、
有限值、原始源表采样率及精确帧数、输出峰值及非静音。
输出 WAV 还会与下混所得 float32 采样直接比较，并再次检查声道、采样率和帧数。
Octane `verification.json` 给出每个播放 WAV 的头部、帧数、峰值、RMS 与非静音结果。
`compare_r301.py` 比较全部原始/播放 WAV 的尺寸和每个字节、四份 JSON
（仅忽略已删除的 `sha256` 字段），以及 `mapping.md` 的每个字节。
运行日志保留实际输出目录、工作目录及耗时，并核对 RSX 参数和成功退出；
日志里的目录、耗时与并行导出顺序不是稳定的音效产物。
唯一允许的静音例外是实际引用的 `null_12s` 计时层，事件 action volume 为 -96 dB；
不会将它放入核心连发变体池。输出 manifest 仍暴露该层以便完整审计。

新增 Rust 依赖正常由 Cargo 下载；本机 Schannel 无凭据失败时，
`cache_deps.py` 用 Python 的证书验证 HTTPS 从官方 index/static.crates.io
补齐 crossbeam-queue、crossbeam-utils、hound，以格式、尺寸及与官方 HTTPS
下载档案的直接内容比较检查已有缓存，不计算内容哈希。
该脚本只写任务授权的 `C:\Users\umi\.cargo\registry`；不修改全局 Cargo 配置。
这个缓存辅助脚本不属于导出流程；T018 未运行它，当前任务也没有该目录写权限。

导出工具 AGPL-3.0-only，LZB 解码端保留 RAD MIT 许可；见 `LICENSE`、
`LICENSE.rad-lzb` 和 `THIRD_PARTY.md`。Rust 混音库单独为 MIT，不链接 RSX。

## U9：破片手雷（`--set frag`）

```powershell
python tools/fuseaudio/export_audio.py --set frag
# 在 git worktree 里（没有 apex-data/ 与 RSX 构建）：读主工作区的
python tools/fuseaudio/export_audio.py --set frag --root <另一份仓库的根目录>
```

输出只写 `apex-data/audio/frag_grenade/`（`--output-dir` 也必须在其内），`src/audio.rs`
与 `octane/` 一样从 `audio_dir` 下加载它。7 个事件各自核对本机引用后才导出：拿出
`weapon_fraggrenade_draw_1P`（视图模型 QC `draw_seq` 第 0 帧，`tools/apexassets/frag_grenade_assets.py`）、
拉环 `Weapon_FragGrenade_PinPull`（S3/正式版 `sound_deploy_1p`）、投出 `Weapon_FragGrenade_Throw`
（`sound_throw_1p`）、语音 `diag_mp_octane_bc_frag_1p`（`battle_chatter_event` "bc_frag"）、弹跳
`Phys_Imp_FragGrenade_Concrete`（S3 撞击表 `impacts/bounce_small.txt` 的 Sound "C"）、爆炸
`Explo_FragGrenade_Impact_1P`（`impacts/exp_frag_grenade.txt` 的 Sound_attacker "C"）、收起
`Weapon_P2011_UnEquip`（QC `holster_seq` 第 0 帧）。"C"（混凝土、岩石）是推断：艾尔登法环的表面
没有 Apex 材质。其余规则与 Octane 一组相同（核心 = 第一个 play action，另有 `_layerN`）。
`--root CHECKOUT` 把 `apex-data/` 与 RSX 都换成那个检出的；输出目录跟着换。

