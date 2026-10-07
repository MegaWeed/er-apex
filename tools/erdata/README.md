# ER 数据开发工具

本目录提供 `erextract`（Rust，离线提取）和 `ertool`（.NET 8，JSON 转储及护甲构建）。只读取玩家安装目录，不启动游戏或访问进程。源码、依赖和输出分开存放：源码在 `tools/erdata`，固定第三方快照/字典/包在 `tools/third_party`，游戏派生数据在 `er-data`。**ertool 是开发期工具，不随模组发布。**

## 编译

需要 Windows x64、Rust 1.91.1 或更新版本、.NET 8 SDK 8.0.425 或兼容补丁版本、Python 3。所有命令从 `tools\erdata` 执行，除非另注明。

```powershell
python scripts/setup_dependencies.py
cd erextract
cargo build --release
cd ../ertool
dotnet build -c Release
cd ..
```

`setup_dependencies.py` 从锁定 commit 下载源码快照（不调用 git），验证 NuGet 包 SHA256，并设置本地包源。Directory.Build.props 将 NuGet 恢复缓存固定在 third_party/nuget-packages，避免环境中的相对缓存路径落入源码目录。已有完整快照重复执行不下载。若目录存在但缺少完成标记，会报错，不自动覆盖。T002 将 SoulsFormats 的 net9.0 和 HKLib 三个项目的 net7.0 改成 net8.0；T003 另修正 FLVER FaceSet 写出器的运动模糊面数统计与 16/32 位索引边界，详见 `third_party/ERDATA_PATCHES.md`。

当前环境 Cargo/NuGet 原生 HTTPS 客户端报 TLS 凭据错误：Rust 依赖已在本机缓存，可用 `cargo build --release --offline`；NuGet 由 Python 通过官方 HTTPS 下载到隔离包源，未关闭证书验证。`Cargo.lock`、`dependencies.lock.json`、`nuget.lock.json` 均应保留。编译输出 target/bin/obj 已被主仓库忽略。

## erextract

```powershell
$extract = '.\erextract\target\x86_64-pc-windows-msvc\release\erextract.exe'
& $extract hash /parts/bd_m_1280.partsbnd.dcx
& $extract list --filter '/parts/*_m_1280*.partsbnd.dcx'
& $extract list --filter msb
& $extract get /parts/bd_m_1280.partsbnd.dcx --out er-data\acceptance --dcx --unbnd
& $extract get /map/mapstudio/m10_00_00_00.msb.dcx --out er-data\extract
```

全局选项：`--game-dir <目录>`（默认 `E:\SteamLibrary\steamapps\common\ELDEN RING\Game`）、`--dictionary <文件>`（默认固定 UXM EldenRingDictionary.txt）。`list` 按封包实际哈希过滤字典，输出 TSV：path / archive / size；过滤无通配符时为不分大小写子串，通配符支持 `*`、`?`；字典重复路径去重。文件大小是 BHD 记录的原始封包文件大小，通常包含 DCX。

`get` 可一次给多个路径。默认保留 DCX；`--dcx` 解压并去掉外层 `.dcx` 后缀；`--unbnd` 自动解压外层 DCX，然后把 BND4 写成同名目录。保留完整内部层级，例如：

```text
extract/parts/bd_m_1280.partsbnd/N/GR/data/INTERROOT_win64/parts/FullBody/BD_M_1280/BD_M_1280.flver
```

内部 `N:\` 的盘符标签转为相对目录 `N/`；拒绝 `..`、ADS 和已有输出链接，检测不分大小写的名字冲突。日志写 stderr；hash/list 的 stdout 可直接重定向。读取 RSA 公钥时扫描玩家自己的 `eldenring.exe`，不使用固定偏移或内嵌公钥。RSA、分段 AES 与 BND4/KRAK 代码改编自 er-mario。

范围：针对本机 ER 的 Data0–3 和 DLC 五个封包、little-endian UTF-16 BND4、DCX KRAK。其他 DCX 类型、非 DCX 的内部压缩 BND 条目会明确报错；当前任务的全部输入已验证。需要更广格式支持时，可使用 ertool 所链接的 SoulsFormats，而不要把不支持的压缩数据误当解压结果。

## ertool

```powershell
$tool = '.\ertool\bin\Release\net8.0\ertool.exe'
$flver = Get-ChildItem er-data\extract\parts\bd_m_1280.partsbnd -Recurse -Filter '*.flver' | Select-Object -First 1
$hkx = Get-ChildItem er-data\extract\chr\c0000.anibnd -Recurse -Filter Skeleton.hkx | Select-Object -First 1
& $tool flver $flver.FullName --json
& $tool hkx-skeleton $hkx.FullName --json --out er-data\json\c0000_skeleton.json
& $tool msb er-data\extract\map\mapstudio\m10_00_00_00.msb.dcx --json
& $tool emevd er-data\extract\event\m10_00_00_00.emevd.dcx --json
& $tool param 'E:\SteamLibrary\steamapps\common\ELDEN RING\Game\regulation.bin' BonfireWarpParam --json
& $tool fmg er-data\extract\msg\engus\item.msgbnd.dcx --json
```

默认 JSON 写 UTF-8 stdout，`--out <文件>` 可直接保存；所有输入可经 `.dcx` 包装，Oodle 从 `--game-dir` 的 DLL 原位加载。**不要复制游戏 DLL 到源码或构建目录。** 其余全局选项为 `--paramdex <Paramdex 根目录>`、`--samples 0..100`（FLVER 每个 mesh 的原始/解码顶点样本数，默认 3）、`--compendium <文件>`（需要外部类型库的 Havok tagfile）。

| 命令 | 输出 |
|---|---|
| flver | 全部节点、父/子/兄弟、变换和 bbox；材质/贴图；mesh 动态标志、NodeIndex、BoneIndices、活跃索引；所有布局；各 buffer 原始偏移/样本及解码值；BaseSkeleton/AllSkeletons |
| hkx-skeleton | HKLib 2018 hkaSkeleton 名字、父骨、参考平移/四元数/缩放；本机 c0000 tagfile 无需 compendium |
| msb | parts、models、regions、events 的具体类型和字段，包括 region 形状类型及尺寸 |
| emevd | 事件、bank/id、参数原始 hex/逐字节数值、参数替换、layer；未接 EMEDF 指令名 |
| param | ER regulation 解密；按表名找到 Paramdex，核对 ParamType/DataVersion/行大小；按 regulation version 应用定义与行名；保留原始内部行名 |
| fmg | 独立 FMG 文本，或 BND4 中全部 FMG 表（含空文本） |
| matbin / tpf | 材质参数/采样器；纹理名称/类型/尺寸元数据，不输出巨量纹理像素 |
| bnd / dcx | BND4 条目元数据；DCX 解压后的大小与文件 magic |

FLVER RotationEulerXZY 单位为弧度，RotationQuaternion 按上游 X→Z→Y 累积。顶点的 NormalW、UV 编码须结合 LayoutSemantic 与 LayoutType 判断。LayoutMember.Index 是语义标签，不能保证等于 VertexSamples 的数组位置；重复语义按 buffer/成员读取顺序累计。HKX 平移与缩放的 Vector4 第四分量原样保留，但姿态分析只用 XYZ。

## 复跑 S2a 与验证

```powershell
python scripts/run_s2a.py
cargo test --manifest-path erextract/Cargo.toml --offline
python scripts/verify_s2a.py
```

`run_s2a.py` 可用 `--game-dir` 与 `--data-dir` 覆盖默认路径（派生数据目录应放在被忽略的 er-data 中）；它提取 c0000、1280 高/低模八件、1010/1500/1600 三个对照模型族各八件，转储地图与事件、两张参数表和中英 FMG，另验证 MATBIN/TPF/BND/DCX。写入 `provenance.json`（exe/regulation/BHD 的 SHA256、BDT 大小、实际封包与命令）及 `artifact_manifest.json`（所有 JSON/分析文件的 SHA256）。

`er-data/json/s2a_summary.md` 回答全部任务核验问题；完整骨差集/逐骨变换误差在 `s2a_comparison.json`，逐 mesh 数据在 `mesh_inventory.json`，地图与护甲身份关联分别在 `map_identity.json` 和 `armor_identity.json`。数据路径记录在 JSON 的 Source 字段。验证脚本独立检查原始字节的法线/切线/UV/索引/权重解码，验证 CLI、重复提取一致性、DCX 前后 MSB 一致性、错误输入、骨架和地名规模。

## 依赖与许可

| 来源 | 固定 commit | 用途 / 许可 |
|---|---|---|
| [er-mario](https://github.com/deltarooo/er-mario) | 32ffb23cf4cd557fa062cb377e0f6f8b773e21a8 | 提取代码；MIT，Copyright (c) 2026 Delta，见 erextract/LICENSE |
| [SoulsFormatsNEXT](https://github.com/soulsmods/SoulsFormatsNEXT) | ee1dd61958f60bdc51ce3da548e9a90a8ab39905 | 格式解析；GPL-3.0，ertool/LICENSE |
| [HKLib](https://github.com/The12thAvenger/HKLib) | ac40bc9915d8caff0df154c2b9a79656dfca1d77 | Havok 2018；MIT |
| [Paramdex](https://github.com/soulsmods/Paramdex) | ff7245e524329bc3eab00036723d2bd53384cedf | ER paramdef / 行名；只作本机研究资源 |
| [UXM-Selective-Unpack](https://github.com/Nordgaren/UXM-Selective-Unpack) | 9501be87e272b6dae55e60a13c3f4753ca6fb3bb | ER 名字典；只作本机研究资源 |

完整第三方声明见 `THIRD_PARTY_NOTICES.md`。Paramdex 与 UXM 快照根目录未找到独立 LICENSE 文件，本任务不重新分发其资源。ertool 链接 GPL-3.0 的 SoulsFormatsNEXT，按 GPL-3.0 提供源码；与 MIT 的 erextract 是两个独立开发工具。两者均不随模组发布，不把游戏资源或 Oodle DLL 纳入源码仓库。

首次构建留下的 ertool/.nuget 旧缓存被本目录 .gitignore 排除；删除该缓存的命令被自动审批拒绝，未执行删除。后续构建使用 third_party/nuget-packages。

## 护甲构建：M0-S3a / T003

所有派生数据输出到 `er-data/s3`。模板是本机原版八个 partsbnd 与完整 MATBIN binder；只读游戏安装目录，KRAK 压缩从游戏路径加载 Oodle。

```powershell
$tool = '.\ertool\bin\Release\net8.0\ertool.exe'
$extract = '.\erextract\target\x86_64-pc-windows-msvc\release\erextract.exe'
$root = 'er-data\s3'
& $extract get /parts/hd_m_1280.partsbnd.dcx /parts/hd_m_1280_l.partsbnd.dcx /parts/bd_m_1280.partsbnd.dcx /parts/bd_m_1280_l.partsbnd.dcx /parts/am_m_1280.partsbnd.dcx /parts/am_m_1280_l.partsbnd.dcx /parts/lg_m_1280.partsbnd.dcx /parts/lg_m_1280_l.partsbnd.dcx /material/allmaterial.matbinbnd.dcx --out "$root\inputs"
& $tool export-mesh "$root\inputs\parts\bd_m_1280.partsbnd.dcx" --matbin-bnd "$root\inputs\material\allmaterial.matbinbnd.dcx" --out "$root\original_mesh"
& $tool build-armor --template-dir "$root\inputs\parts" --template-model 1280 --mesh "$root\original_mesh" --model 999 --matbin-bnd "$root\inputs\material\allmaterial.matbinbnd.dcx" --out "$root\roundtrip_package"
& $extract unpack "$root\roundtrip_package\parts\bd_m_0999.partsbnd.dcx" --out "$root\manual_readback"
```

`export-mesh` 可直接读 FLVER 或 partsbnd/DCX。裸 FLVER 会自动使用同名 `.tpf`，也可指定 `--tpf file`。推荐提供 `--matbin-bnd` 以列出材质实际消费的本地后缀；未提供时导出整个本地 TPF 的候选集合。DDS 原样导出，不做二次压缩。

`build-armor` 的 `--template-dir` 指向八个 `{hd,bd,am,lg}_m_XXXX{,_l}.partsbnd.dcx` 所在目录；输出包含八个重命名 partsbnd、追加材质后的 `material/allmaterial.matbinbnd.dcx` 及 `build-manifest.json`。每个指定输入的部位高低模使用同一重建 FLVER/TPF，未指定输入的部位是保留节点的空 mesh 模型。`--texconv` 默认 `tools\bin\texconv\texconv.exe`，支持 PNG/DDS，按实际模板 DDS 的 BC 与 sRGB 编码转换。原版无修改 DDS 不重压缩。每次序列化都解压读回并核对完整 BND 条目数据。

模型号范围 0..9999，须与模板不同；已有同名目标 MATBIN 报错。所有命令支持 `--game-dir`。数据格式、可选无损往返字段、布料限制和包围盒算法见 [fusemesh.md](docs/fusemesh.md)，材质槽/通道实证见 [armor-materials.md](docs/armor-materials.md)。1280 胸甲的 7 个 cloth mesh 使用原版 layout 1/5/3 三流，其余 19 个使用 layout 4；外部普通 v1 输入使用 layout 4，应选非 Cloth 材质模板。

```powershell
python scripts/setup_dependencies.py
cargo build --release --offline --manifest-path erextract/Cargo.toml
dotnet build ertool/ertool.csproj -c Release
python scripts/s3a_roundtrip.py
python scripts/verify_armor_builder.py
python scripts/s3a_material_evidence.py
```

`dotnet build -c Release` 也可在 `ertool` 目录执行。往返脚本每次从安装档案重新提取输入，不依赖 T002 输出；会逐数组比较、逐原始顶点流比较、核对独立 LOD/运动模糊面组、所有原始材质条目元数据、包围盒、四个 DDS 字节和九个包的 KRAK/内部路径，输出 `roundtrip_comparison.json` 与日志。`verify_armor_builder.py` 再验证基本 v1、骨骼表重排、颜色省略、PNG、贴图冲突、索引 65536 和错误输入，结果在 `builder_checks/results.json`。

材质证据脚本提取四套 16 个高模部位及材质/shader binder，使用本机 Windows SDK `10.0.26100.0/x64/dxc.exe` 反汇编；可用 `--dxc` 指定其他已安装 DXC。不需要新增 Python 包或网络。`disassemble_shader.py` 也可独立使用。游戏 shader 是 DXIL，旧 D3DDisassemble 不能处理，须用 DXC。

辅助命令：

```powershell
& $tool armor-evidence --template-dir "$root\inputs\parts" --models 1280,1010,1500,1600 --matbin-bnd "$root\inputs\material\allmaterial.matbinbnd.dcx" --out "$root\material_evidence"
& $tool unpack-bnd "$root\inputs\shader\shaderbdle.shaderbdlebnd.dcx" --filter 'C[DetailBlend]\C[DetailBlend].shaderbdle' --out "$root\shaders\detailblend"
& $extract unpack "$root\roundtrip_package\material\allmaterial.matbinbnd.dcx" --filter BD_M_0999 --out "$root\material_readback"
```

`erextract unpack` 先读取全部本地 BND4 条目，可用 `--filter` 减少落盘文件；不打开游戏档案索引。其 DCX 范围仍为 KRAK。`ertool unpack-bnd` 利用 SoulsFormats 处理其他受支持 DCX（例如 gxflvershader 的 DFLT）；`--filter` 为不分大小写的内部路径子串。源文件或原始游戏 DLL 不纳入提交。

T003 的两个上游写出修正可由 `setup_dependencies.py` 在固定 snapshot 上幂等复现，说明在 `third_party/ERDATA_PATCHES.md`；版本及依赖 commit 未变。不启动游戏；模型显示、布料、隐藏标记与剔除的运行时验证由 Claude 完成。

### 四部位构建（T005）

`--mesh` 保持原来只供给胸甲的行为。新增 `--{hd,bd,am,lg}-mesh` 和 `--{hd,bd,am,lg}-template`，分别给出 fusemesh 目录与高模 partsbnd（低模用同目录 `_l` 文件）。可以混用 HD/BD/LG 1280 与 AM 1500；未指定的部位为空。非零权重实际引用的骨必须在当前模板中为 Bone 且非 Disabled，否则封包前报错。可选精确 sampler 替换与 Float 参数控制见 [fusemesh.md](docs/fusemesh.md)。完整例子和一键转换见 [暴雷转换器](../fusemesh/README.md)。
