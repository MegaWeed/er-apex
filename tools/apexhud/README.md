# 本机 Apex HUD → ER-Apex（Fuse / Octane）

在仓库根目录执行：

```powershell
python tools/apexhud/export_hud.py
```

## T017：Octane 独立包

在仓库根目录执行：

```powershell
python tools/apexhud/export_hud.py --legend octane
python tools/apexhud/verify_hud.py --legend octane
```

完整导出直接读取本机游戏包，写入 `apex-data/hud/octane/`；不读取 `apex-data/hud/` 中的 Fuse 包文件作为输入。`--legend` 可选 `fuse` / `octane`，默认仍为 `fuse`，默认输出仍为 `apex-data/hud/`。Octane 的 `--out` 只能位于 `apex-data/hud/octane/` 内；Fuse 的输出只能位于 `apex-data/hud/` 内。受派单 worker 还须遵守任务单的独占路径，不能直接重写默认 Fuse 包。

Octane 完整导出包括原有通用图片、RUI、颜色、两项原始字体图集、所需字形、14 种本地化、预览，以及 S3 本地脚本支持且当前 `ui.rpak` 中确有的通用补充图片和装填提示。图片、名称和色值只来自本机；`StringToGuid` 只用于 Apex 资产/本地化键定位，保留该算法。工具不再计算 SHA256：构建缓存比较小型源文件快照的大小与字节，产物校验检查 PNG/DDS 格式、尺寸、alpha，并直接比较原始导出、payload、逻辑画布、字体图集和字形内容。

仅重建包、补充图片或重建分析/预览时：

```powershell
python tools/apexhud/pack.py --legend octane
python tools/apexhud/export_extra.py --legend octane
python tools/apexhud/export_hud.py --legend octane --analyze-only
```

`schema_version` 保持 `1`，技能 id 保持 `tactical` / `ultimate` / `passive`。头像和名称键从角色设置读取，能力图标/名称键按角色引用读取；本机能力文件前缀实际为 `octance_`。`localization.json` 中 Octane 的角色/能力/强化键取代 Fuse 的角色键。两项字体的原始图集、字型编号和坐标格式不变，保留原字符集并补充 Octane 本地名称所需字形；兼容字符同样读自本次导出的游戏本地化，Fuse 字符串键不会写入 Octane 包。

新字段 `hud_pack.json.legend_upgrades` 为数组；每项含 `id`、`asset`（Apex 图标路径）、`guid`、`image`、原始尺寸和 payload 信息，以及 `level`、`level_status`、`name_key`、`name_text`（包默认语言 `schinese`）、能力/角色来源。角色的 `passives` 和 `extraPassives` 都会收集传奇专属强化，原始列表记入 `character_list`，不据此宣称强化当前启用。本机设置未给出的等级写为 `null`，并标记“待定”；`passiveScriptRef` 中的编号不作为等级。缺失名称或图标同样标记“待定”。Fuse 只新增该字段，原有本地化键和裁切字形范围保持不变。

T017 的 Fuse 兼容性验证只写入 Octane 的子目录：

```powershell
python tools/apexhud/export_hud.py --legend fuse --out apex-data\hud\octane\fuse_check
python tools/apexhud/export_extra.py --legend fuse --out apex-data\hud\octane\fuse_check
python tools/apexhud/verify_hud.py --legend fuse --out apex-data\hud\octane\fuse_check
python tools/apexhud/verify_reproduction.py --legend fuse --candidate apex-data\hud\octane\fuse_check
```

复现比较直接比较文件大小、字节和 JSON 内容，只允许移除 `sha256` / `payload_sha256` 和新增 `hud_pack.json.legend_upgrades`；覆盖登记图片、字体/字形、输入、RUI、预览及补充资源。包含输出绝对路径/运行耗时的运行清单与日志，以及未登记探索文件、验证摘要不参与复现比较。比较报告写入候选目录 `reproduction.json`，原 Fuse 包只读。

两个包都导出后可运行集成回归：

```powershell
python -B tools/apexhud/test_hud.py
```

检查 Octane 默认路径与越界拒绝、40 张通用主图片和 11 张补充图片/定义一致、六项通用 HUD 元素一致、原字体/1512 个字形保留、打包命令内容稳定；另用独立临时目录中的有效 PNG 改动一个 RGB 像素，确认直接内容校验会拒绝损坏。旧 schema-1 Fuse 包没有 `legend_upgrades` 时仍可只读验证。

输入游戏目录默认是 `E:\SteamLibrary\steamapps\common\Apex Legends`。脚本重新读取 `ui.rpak`、`common.rpak`、`common_early.rpak` 及本机 14 个非专服本地化包，把图片、字体、定义、颜色、本地化和预览全部写进 `apex-data/hud/`。**不依赖已有 `apex-data/export/` 或 `apex-data/assets/` 的产物。** 不启动游戏、不注入、不联网、不运行 git 命令。

依赖：本机 Python、Pillow、numpy；T001 修正过的 `tools/apexassets/rsx_source/` 源码及其本地静态解码库；Visual Studio C++/MSBuild。`prepare_rsx.py` 只读 T001 源码，复制到本工具的 `rsx_work/`，应用 `hud_export.h` 中的增量导出代码并构建；不写 T001 的目录。无 MSBuild/源码时直接报错，不绕过。`rsx_work/`、`build.log`、`__pycache__/` 已在本目录 `.gitignore` 排除。

其他命令：

```powershell
python tools/apexhud/verify_hud.py
python tools/apexhud/export_hud.py --analyze-only
python tools/apexhud/export_hud.py --out apex-data\hud\repro_final
python tools/apexhud/verify_reproduction.py --candidate apex-data\hud\repro_final
```

`--analyze-only` 保留既有 RSX 运行清单，把重新打包记录写到 `analysis_manifest.json`。`--out` 只能指向专属 `apex-data/hud/` 或其子目录。所有 RSX 子进程的工作目录都是输出下的 `logs/runtime/`，RSX 即便写自己的缓存也不会触碰游戏/T001/仓库其他目录。

验证从零复现时，候选目录应在运行前不存在或为空；工具不会替用户清空该目录。T009 首次独立空目录导出使用 `repro_final/`，当时比较 1245 个登记产物，缺失和差异均为零。T017 扩大登记范围后，`octane/fuse_check/reproduction.json` 记录 1881 个文件的兼容性比较；对比排除项见上述命令说明和报告。

## HUD 包格式

入口 `apex-data/hud/hud_pack.json`，UTF-8 JSON，`schema_version=1`。所有产物路径相对于此文件所在目录，采用 `/`。GUID 是 16 位十六进制字符串，不用浮点数存储。

| 字段 | 含义 |
|---|---|
| `canvas` | `[1920,1080]` 参考画布，原点左上，x 向右、y 向下 |
| `elements` | 7 项 MVP：`crosshair`、`weapon_slot`、`health`、`shield`、`hit_marker`、`damage_numbers`、`boss_health` |
| `optional_elements` | 所选传奇的战术/终极/被动图标；id 不变 |
| `legend_upgrades` | 所选传奇的强化图标、等级或待定状态、名称键及本机名称 |
| `layout.bounds_px` | `[x,y,w,h]` 推荐绘制包围框 |
| `layout.anchor` / `anchor_position_px` | 中心、左下、右下或底部中心锚点及其坐标；与框有明确关系 |
| `rendering` | 原图条目含 `image/guid/original_size`；几何条目含 `kind/status/basis` |
| `colors` | 本地颜色键、RGB、来源 CSV 行号；色值与应用规则分别标来源 |
| `states` / `binding` | 状态变化建议与 ER-Fuse 数据接口；未提供的接口标待实现 |
| `rui_sources` | 本机 RUI 默认参数、尺寸和样式原始字段的 JSON |
| `font_choice` | 字型 11 为正文、22 为数字；根据导出字形样张选择，属于推断 |
| `preview_state` | 示意状态；不是游戏采样。备弹为空，显示 `--` |
| `integration_gaps` / `limitations` | 当前模组缺少的状态以及解析边界 |

推荐按 `min(viewport_width/1920,viewport_height/1080)` 等比缩放并居中；这是工具建议。每项位置、锚点、尺寸和动画都有推断标记，不能冒充原游戏布局。`health` 的 `children`、武器栏的文字尺寸等继承父项的推断属性。

### 图片与资产证据

`assets.json` 保存名称、类型、GUID、包、用途、证据、状态。路径来自本机设置/武器/数据表的字符串或 RUI 默认值区中的可读字符串。定位规则：

```text
UIIA GUID = StringToGuid("ui_image/" + rui_path + ".rpak")
RUI  GUID = StringToGuid(ui_path + ".rpak")
```

算法使用仓库中经验证的 `tools/apexdata/rtech_hash.py`；导入前禁用 Python 字节码写入。哈希输入与命中的 RSX 清单均保留；未命中 ui/common/common_early 的候选保留为待定。仅发现的候选名称不等于已导出的 HUD 资源。

`images/rui/...png` 保留 header 的原始逻辑画布尺寸和 alpha；`payload_images/rui/...png` 保留 RSX 解出的裁切像素区及原始 PNG 字节。UIIA 会裁去透明留白，例如 R-301 逻辑尺寸为 **640×320**，实际像素区为 **457×144**。本次按 header 浮点字段推断裁切偏移 `round(-uv[0:2]*logical_size)`，再逐张检查 `round(uv[2:4]*logical_size)==offset+payload_size`；逻辑画布上仅原样复制 RGBA，不缩放、不进行 alpha 混合。该 UV 解释标为推断，原始八个浮点数仍保留，像素区与画布内容逐像素验证。

每个导出条目保存两张图的来源路径、alpha 范围、header/HQ/LQ 尺寸、`content_rect`、流式状态和 BC1/BC7 tile 数。UIIA 源编码是 RTech 分块 BC1/BC7，PNG 是解码后的 RGBA；它们不能用于还原压缩块原始字节。绘制时可用逻辑画布和 `content_rect`，或用未改动的 payload；预览使用后者避免透明留白影响示意图标的可见大小。

`raw/` 是 RSX 直接输出；`lists/` 是实际读取包的资产清单；`inputs/` 是本次直接从游戏重新导出的定义/设置/表格/本地化；`run_manifest.json` 保存命令、工作目录、退出码、输入来源路径及字节数。部分不相关数据表含非法 UTF-8，候选 ASCII 路径扫描使用 replacement 解码，计数写入输入清单；重要武器定义、颜色表和本地化按 UTF-8 严格读取。

### 字体

两项 `font` 均为 v12、`DXGI_FORMAT_R8_UNORM` 图集：

| GUID | 图集尺寸 | 本机字型编号 |
|---|---:|---|
| `a65dbf4a3b608536` | 8192×2976 | 15 |
| `3027e77deb37ce6e` | 8192×3904 | 11、22、2、19、14、10、0、26、29 |

保留原 R8 DDS、RSX 转换 PNG、完整 Unicode→texture→rect 元数据和图集字形信息，见 `fonts/<guid>/source.meta.json`。名字在本机资产中为空，不推测其商业字体名。字型 10 只含 19 个 Unicode，是特殊字符集合，不当作完整正文字体。

`fonts/<guid>/font.json` 中的 `profiles[].glyphs` 给出当前所需字符的裁切 PNG、原图集矩形、裁切尺寸和近似 advance。范围含 ASCII 32–126 以及本机 R-301/暴雷名称所需的字符。完整字符坐标仍在原始元数据中。

字体图集是**距离场（SDF）**，原 PNG alpha 恒为 255，R 通道存储距离场值，不能直接视作普通字形覆盖率。工具生成裁切图时只把原 R 通道复制到 alpha，RGB 设白；这些裁切图仍保留距离场值，尚不是原生字体 shader 渲染后的透明字形。预览额外用 `(R-176)/16` 的平滑阈值形成易读示意，**阈值、字距、基线排布和原 SDF shader 的具体解码规则未解，属于推断**。裁切图没有应用此阈值。

图集不含字形的**基线/偏移度量**。`source_rect` 只定位纹理区域，不提供相对排版基线的 bearing/offset；`advance_px` 是裁切宽度的近似值，不是恢复出的字距。精确排版需另取字体度量或从游戏文本渲染数据恢复，不能把矩形坐标当作基线/偏移。

它们不是 TTF/OTF，不能传给 ImGui `AddFontFromFileTTF`。可以上传 atlas/裁切纹理，根据 Unicode UV 用 `DrawList::AddImage` 逐字绘制，或由 Claude 接入自定义图集。需要精确文本时仍须恢复 shader、advance/kerning 和可能的字形 shaping；14 种本地化字符串不等于已实现 14 种语言的排版，尤其 RTL/阿拉伯文 shaping 待处理。

### RUI 解析程度

RSX TXT 提供参数类型、短哈希、偏移、默认值、参数簇和默认值区大小；参数名大多裁剪。本次补充导出 header 的参考尺寸/比例、样式原始字段、render-job 数量、无类型常量视图和默认值区的图片路径引用。

`rui/` 中重点分析 14 个资产。**没有还原 transform/render 程序，不能给出已验证的真实屏幕锚点、逐元素尺寸、动画条件或精确样式。** RSX 的 C++ 选项只有参数结构，render 函数是 `Not implemented`；TXT 不包含运行分支。参数短哈希会重复，例如 `crosshair_tri` 的 `6cc2` 在两个偏移出现，不能按导出顺序与名字一一硬配。

空目录对比还发现 RSX 在 `loot_stim_health_large` 的最后一列（133个像素）产生不确定内容：目标纹理未初始化，边缘矩形复制未覆盖的像素泄漏分配器内容。补丁在 UIIA 组装纹理前将其透明清零，不改变已复制的像素；最终再做两次独立导出的图片对比。该图片属于辅助候选，不是当前 MVP 直接使用的资源。

特别注意：RSX `UIAssetStyleDescriptor_t` 把若干 u16 命名成颜色/字号/字体。实际字段大量呈 4 字节步长，并超过默认值区，显然不能直接视作 RGBA/像素/字体编号。本包改用 `color_fields_raw_u16`、`text_size_field_raw_u16` 等中性名字保存，疑似运行时偏移的解释明确为推断。`shader_constants_f32` 也只是无类型 4 字节视图，有些是整数位模式；不拿它们冒充有语义的参数。

### 颜色与本地化

`palette.json` 来自本次 `inputs/datatable/0xC803BD35ABD0972B.csv`（GUID `c803bd35abd0972b`，`common_early.rpak`），保留 default、protanopia、deuteranopia、**本机原字段拼写 `trianopia`** 和 qa；每行有来源位置。护盾等级推荐用 `HUD_LOOT_TIER1..6`，头部伤害色用 `HUD_DAMAGE_HEADSHOT`，血量伤害数字用 `HUD_DAMAGE_TEXT_BLEED`。这些色值是数据；护盾/命中形状、优先级和原脚本调用关系未解，映射建议仍标推断。

`localization.json` 含 `#WPN_RSPN101`、短名称及暴雷名称的 14 种本机译文。查键哈希前去掉 `#`。包默认中文只是预览选择，没有读取玩家设置；运行时按玩家/模组语言取值。

## 预览及验证

`preview/hud_hip.png`、`hud_ads.png`、`hud_reload.png`、`hud_sprint.png`、`hud_transparent.png` 均为 1920×1080；`states.png` 是四态拼图；`assets.png` 是原图样张；`fonts.png` 是本机字形样张。

预览用真实武器、传奇及技能图片，示意血量/护盾/Boss 比例。准星重建为三条径向线和中心点；ADS 推荐淡出线、保留点，换弹/冲刺推荐隐藏。**这些动态规则不是已恢复的 Apex 分支**，依据是本机武器定义向 RUI 传入对应参数。原 ADS 瞄具属于武器/光学系统，不是已导出的这张腰射 HUD 图片。

`verify_hud.py` 验证 MVP 覆盖、PNG 格式/alpha/逻辑尺寸、payload 与原始导出字节一致、逻辑画布与 payload RGBA 一致、两项字体/字形与图集内容一致、传奇头像/技能/强化来源、RUI 引用、14 种本地化、关键颜色和预览尺寸；`PASS` 表示交付包完整，不表示与原游戏逐像素相同。

## 第三方许可

RSX 本机源副本为 r-ex/rsx 2.3.0，T001 修正版本；上游提交 `2c63d87`，AGPL-3.0。T009 的 RSX 补丁与新增头文件按其派生作品许可处理，完整源码可由本地 T001 源码加本工具中的可复现补丁获得。构建副本包含原 LICENSE。静态解码库的原始来源/许可说明沿用 `tools/apexassets/THIRDPARTY.rsx.txt`，此任务不下载或重新分发这些库。Pillow/numpy 使用本机已有安装。

## U9：破片手雷图标

`export_extra.py` 的 `WANTED` 加了 `rui/ordnance_icons/grenade_frag`（S3 `mp_weapon_frag_grenade.txt` 的
`hud_icon`/`menu_icon`；本机 `ui.rpak` GUID `613039ccdd41e834`，132×129）。证据除了脚本里的
`$"..."`，也收 R5R `platform/scripts/weapons/*.txt` 中以它为 `hud_icon` / `menu_icon` 的设置行
（`R5Reloaded_S3_weapon_setting`）。合并后在主工作区重跑 `python tools/apexhud/export_extra.py --legend octane`，
HUD 的投掷物格（G）和手雷指示才有图标；没有时投掷物格保持空格样式。

