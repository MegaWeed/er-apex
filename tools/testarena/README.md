# The First Step 测试敌人生成器（T013）

开发期离线工具，C# / .NET 8，直接引用 `tools/third_party/SoulsFormatsNEXT` 的源码项目。它读取玩家自己的游戏档案，在 `m60_42_36_00` 添加一个按旗标触发的生成器。默认一波三名士兵；开发命令为 `setflag 1042360990 1`。

## 构建和生成：一个命令

需要 Windows x64、Python 3.11+、.NET SDK 8.0.425（`global.json` 固定 SDK），以及已经准备好的只读依赖：

- `tools/erdata/erextract/target/x86_64-pc-windows-msvc/release/erextract.exe`。
- `tools/third_party/SoulsFormatsNEXT/SoulsFormats/SoulsFormats.csproj`。
- `tools/third_party/nuget-feed/` 中的离线 NuGet 包。
- 游戏安装目录中的 `oo2core_6_win64.dll`，从原位加载。

从任意目录执行：

```powershell
python tools\testarena\run.py build
```

这一个命令依次列出游戏档案中的全部 MSB/EMEVD、提取输入、编译工具、扫描编号冲突、生成两个覆盖文件，并自动执行验证。成功退出码为 0，最后一行为 `PASS`。

输入缓存使用游戏 EXE、相关 BHD 索引和每个提取文件的 SHA256 验证。缓存缺失、输入哈希变化或游戏更新会重新提取；需要强制从档案提取全部输入时：

```powershell
python tools\testarena\run.py build --refresh
```

可用 `--game-dir` 指定其他安装位置，用 `--config` 指定配置。`--data-dir` 必须仍在 `er-data\test_arena` 内。所有 MSBuild 中间文件和两个项目的编译输出均用 `--artifacts-path` 定向到数据目录；NuGet 缓存使用 `C:\Users\umi\.nuget\packages`。不会向第三方源码目录写入 `obj` / `bin`，不会调用改变 git 状态的命令。

仅提取输入：

```powershell
python tools\testarena\run.py extract
```

## 独立验证

```powershell
python tools\testarena\run.py verify
```

验证器读取 `originals` 和生成后的二进制文件，检查：

1. 游戏档案清单中的全部 1,347 个 MSB 和 589 个 EMEVD 的大小与 SHA256。新增旗标、实体和事件编号在所有解压字节偏移中没有原有引用；另外检查旗标区间指令和初始化参数代入后的区间，包含 DLC 与 `common*.emevd`。
2. 原有模型、部件、区域、MSB 事件、路线、层和版本保持一致。
3. 原有 EMEVD 事件顺序、参数、指令、层、字符串和链接信息保持一致；事件 0 仅追加一条初始化。
4. 新条目的名称、实体编号、内部编号、位置、朝向和所有模板字段符合配置及原版参考。新增编号只出现在规定的条目或指令中。
5. 生成器引用三个新 Enemy 和三个新区域，其余引用槽为空；使用原版 `GenType=3` / `InitialSpawnCount=0` 的初始隐藏模式。
6. 新事件包含且仅包含“等待旗标开启 → 调用生成器 → 清旗标 → 重启”；显式按字节偏移解码并打印名称、参数、原始 hex。
7. MSB 和 EMEVD 保持各自原有 DCX 压缩参数，本机均为 KRAK / Kraken / level 6。
8. 从输出中移除所有新增内容后重新序列化，必须与同样序列化的原文件逐字节相等，检查隐藏序列化字段及恢复后的索引。

每次运行的命令、输出及退出码保存在 `er-data/test_arena/logs/`。主要结果文件：

- `corpus-manifest.json`：游戏和全库输入来源、档案名、大小、SHA256。
- `build-manifest.json`：配置、模板身份和包文件 SHA256。
- `verify-report.json`：PASS/FAIL、条目数量、新指令解码、引用、压缩参数和字节复原结果。
- `evidence/reference.json`：原版生成器、模板和区域的完整字段。
- `evidence/instruction-evidence.json`：指令布局及原版文件 / 事件 / 指令索引证据。
- `evidence/collision-scan.json`：最终编号及全库冲突扫描结果。

额外的反向验证用例会在生成包中临时修改原部件、原指令、生成器引用、实体编号和新指令，逐例要求验证器返回 1 并说明对应原因。它在 `finally` 中恢复包并再次验证，结果在 `er-data/test_arena/checks/`。请在默认配置已构建且其他程序未使用生成包时运行：

```powershell
python tools\testarena\checks.py
```

## 配置

`first_step.json` 指定目标地图、士兵来源、原版生成器参考、旗标、事件与实体编号，以及三个出生点的位置和 yaw。yaw 的单位为度；区域与 Enemy 使用相同朝向。`waveSize` 可为 1..3，最大活动模板容量为 3。

| 项目 | 默认值 |
|---|---|
| 来源 | `m10_00_00_00 / c3000_9117` |
| NPC / Think / 模型 | `30001014 / 30001000 / c3000` |
| 测试旗标 | `1042360990` |
| 新 EMEVD 事件 | `1042363990`，在赐福休息时重启 |
| 生成器实体 / MSB EventID | `1042363900 / 900` |
| Enemy 实体 | `1042360850, 1042360851, 1042360852` |
| Enemy 名称 / InstanceID | `c3000_9500 / 9500`，`c3000_9501 / 9501`，`c3000_9502 / 9502` |
| 区域实体 / RegionID | `1042362900 / 900`，`1042362901 / 901`，`1042362902 / 902` |

三个点均距赐福 `(-12.83, 90.7, -54.5)` 水平距离 10 米：

| 点 | 位置 XYZ | yaw |
|---|---|---:|
| 0 | `(-4.83, 91.7, -60.5)` | -53.13 |
| 1 | `(-12.83, 91.7, -64.5)` | 0 |
| 2 | `(-20.83, 91.7, -60.5)` | 53.13 |

**91.7 是暂定高度，即赐福高度加 1 米，不是测得的地面高度。** Claude 应在游戏中测量地面后修改各点的 Y，再运行构建与验证。验证器允许后续调整高度，仍检查有限数值和 8..12 米水平距离。

原版参考为 `m30_16_00_00` 的生成器实体 `30163256`（MSB EventID 7），其 EMEVD `30162621` 的零基指令 47 用 `2003[54]` 调用它。它引用普通 `Enemy c4314_9004` 和一个 `Other` 球形区域（半径 1），不使用 DummyEnemy。保留 `GenType=3`、`LimitNum=-1`、`InitialSpawnCount=0`、间隔 5/5、未知浮点 0/0；将 `MaxNum` 调整为 3，`MinGenNum/MaxGenNum` 调整为 `waveSize`。除明确的引用字段外，数量、模式、间隔等运行时含义来自原版搭配的推断；完整效果须在游戏验证。

模板保留源士兵的 NPC、Think、模型和其他行为字段。在新副本中将 `GameEditionDisable` 从源值 `DisableInNetworkTest` 改为参考模板的 `NeverDisable`，移除史东薇尔碰撞绑定，并采用目标赐福角色的显示组 `[1,0,0,0,0,0,0,0]`。未修改原版 `1042360951`、`1042360700` 或其他角色。目标地图原来没有 `c3000` 模型条目，工具添加一个；不向包中复制角色资源。

## 安装与触发

生成结果为：

```text
er-data\test_arena\package\
  map\mapstudio\m60_42_36_00.msb.dcx
  event\m60_42_36_00.emevd.dcx
```

由 Claude 把这两个文件按上述相对路径合并到 me3 已启用的模组 package 根目录，或将整个生成的 `package` 目录作为独立 me3 package 加载。若多个 package 覆盖同一地图，应先合并修改，避免覆盖其他地图或事件编辑。本工具只生成文件，不执行安装。

快启使用 `qb_place = first_step`。加载完成后先确认没有测试士兵，再在模组开发控制台执行：

```text
setflag 1042360990 1
```

事件调用生成器一次，随后自动把旗标置 0 并回到等待。完成一波后再次执行同一命令。三个模板构成固定容量，建议先杀掉上一波，再测下一波；存活模板、原版 5 秒间隔以及极快重复置旗标对调用的影响需要实测。

Claude 的游戏内验收应检查：未触发时模板隐藏；一次出现三人；出生点、朝向、落地高度、模型贴图动画与 AI 正常；邻近原版角色保持正常；杀掉后可重复触发；赐福休息、死亡、离开地图再返回后仍可触发。地图重载时若测试旗标仍为 1，等待事件可能立即触发；通常处理后会清为 0。

## 边界与许可

工具没有启动游戏、访问存档、写游戏目录、安装到 `scratch/mod` 或改变 git 状态。游戏数据只写到独占的 `er-data/test_arena`。静态扫描不能证明运行时动态计算的旗标或引擎内部编号分配没有冲突，也不能证明出生点的地面、导航网格或资源加载结果。

源码按 GPL-3.0 提供，见 [LICENSE](LICENSE)。[第三方声明](THIRD_PARTY_NOTICES.md) 记录 SoulsFormatsNEXT、现有 erextract 和游戏 DLL 的使用边界。本工具及游戏派生数据不随模组核心代码发布。
