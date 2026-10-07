# ER 护甲材质约定：本机 1280 与 1010/1500/1600 对照

结论针对所检查的本机资源和具体 shader。`_m` 在这些护甲中是 **BC4 单通道金属度图**；`_n` 的 B 是 **光泽度控制**，A 是 **细节材质混合遮罩**，不能把 `_n.B` 当作法线 Z，也不能把 `_m` 当四通道 ORM 图。

## 可复核来源

运行 `python scripts/s3a_material_evidence.py`，派生数据全部在 `er-data\s3\material_evidence\`：

| 文件 | 内容 |
|---|---|
| matbins.json | 16 个部位引用的 82 份唯一 MATBIN：完整 ShaderPath、SourcePath、Key、所有参数的名字/类型/数值、采样器名字/路径/Key/Unk14 |
| textures.json | 53 个 TPF 条目：源封包与内部路径、TPF Format/Flags1/Mipmaps、DDS FourCC/DXGI、尺寸和 sRGB |
| parts.json | 1280、1010、1500、1600 四套的 hd/bd/am/lg 与 FLVER 材质引用 |
| shader_asm/*.asm | 从本机 `shaderbdle.shaderbdlebnd.dcx` 中的 `C[DetailBlend].shaderbdle` 读出的 0/6/13 Gbuf、13 Fwd、13 Gbuf_[A] 的 DXIL 反汇编 |
| shader_asm/manifest.json | Windows SDK DXC 路径、工具及输入 bytecode 的 SHA256 |
| provenance.json | 本机原始 MATBIN/shader 封包路径、大小、SHA256、完整命令 |

未使用 wiki、社区通道表、游戏名称记忆或 Apex 网页。对照套装身份沿用 T002 本机参数与 FMG 的关联，来源 `er-data\json\armor_identity.json`。本次以实际模型号区分数据。

## 1280 套装的 MATBIN

共有 **19** 份唯一材质：

- HD：Metal、Fabric、Belt。
- BD：Metal、Fabric、Rope、Leather、Chainmail、Belt、Leather_Cloth、Fabric_Cloth、Rope_Cloth。
- AM：Metal、Leather。
- LG：Metal、Fabric、Leather、Belt、Leather_Chain。

其 ShaderPath 是 `N:\GR\data\Material\sat\OutputData\SPX\C[DetailBlend].spx`；三份胸甲 `_Cloth` 用 `C[DetailBlend]_cloth.spx`。静态变体由 `GXFT_SATStaticSwitch` 指定，例如 BD Fabric=6、Metal/Leather/Chainmail=13、Rope=0、Belt=8；不能只看文件扩展名推定 shader 行为。

1280 胸甲共有 26 份 FLVER 材质，复用上述 9 份 MATBIN。每份 FLVER 材质仍有 **14 个 texture slot 定义**，仅 `Path` 为空：slot 名、tiling 和未知字段必须保留。实际贴图路径由 MATBIN 指定，不能将“空路径”理解为删掉整个槽列表。

典型 `P[BD_M_1280]_Metal` / `Fabric` 的本地槽：

| MATBIN Sampler.Type 后段 | 对应路径 basename | 作用证据 |
|---|---|---|
| Texture2D_7_AlbedoMap | BD_M_1280_a.tif | 本地底色；DXIL 资源 `C_DetailBlend_snp_0_Texture2D_7`（t1） |
| Texture2D_0_NormalMap | BD_M_1280_n.tif | 主法线、光泽、混合图；DXIL 资源 Texture2D_0（t2） |
| Texture2D_3_MetallicMap | BD_M_1280_m.tif | 单通道金属度；DXIL 资源 Texture2D_3（t8） |

Fabric 的 AAT100_Fabric_02_a、AAT100_Fabric_01_n、AAT100_Fabric_03_a/n、AAT100_Fur_01_a/n 等共享细节资源保留；Metal 使用 AAT100_Metal_02 与 AAT100_Rust_01。所有完整路径、参数已在 JSON 中。`g_AlphaRef`：BD Fabric 及 Fabric_Cloth 为 `[50,0]`，Metal 为 `[0,0]`。

Rope 的主 AlbedoMap 是 `BD_M_1280_rope_a.tif`，法线来自共享 AAT；其本地 MetallicMap 为空。Belt 的底色/法线/金属度来自 AAT500_Belt_01，不引用胸甲 TPF 的本地 a/n/m。不能假设每个模板材质都消费同样三个本地图。

## DDS 编码与通道

1280 胸甲实测：

| 名字 | TPF Format / Flags1 | DDS 编码 | sRGB | 尺寸 / mip |
|---|---|---|---|---|
| BD_M_1280_a | 1 / 0 | DX10 BC1_UNORM_SRGB | 是 | 2048×2048 / 12 |
| BD_M_1280_n | 107 / 0 | DX10 BC7_UNORM | 否 | 2048×2048 / 12 |
| BD_M_1280_m | 103 / 0 | ATI1 → BC4_UNORM | 否 | 1024×1024 / 11 |
| BD_M_1280_rope_a | 0 / 0 | DX10 BC1_UNORM_SRGB | 是 | 512×256 / 10 |

TPF Format 0/1 都出现 BC1 sRGB，106/107 都出现 BC7 linear；因此不能仅凭 TPF 数字推断 DXGI/sRGB，必须解析实际 DDS。

| 通道 | 已证实的用途与限制 |
|---|---|
| _a.RGB | sRGB 底色/反照率，经采样器色彩空间转换和材质颜色/细节图组合；不是直接写入最终屏幕的颜色 |
| _a.A | 在 `[A]` shader 变体进入 alpha test/discard；BC1 最多支持二值透明。非 alpha-test 变体不消费其透明裁剪功能 |
| _n.R/G | 两分量法线，解码为 `2R−1, 2G−1`；Z=`sqrt(1−saturate(x²+y²))`。实际 13 Gbuf 中 R 系数乘副切线，G 系数乘切线，移植时须核对 Apex 的坐标/切线定义，不能凭文件名决定翻哪一轴 |
| _n.B | 光泽度控制，与细节 NormalMap.B 组合：主项为 `saturate(2×base.B×detail.B)`；不是法线 Z。13 Fwd 中此值经 decal/wet 等修正后影响环境反射 mip，mip 约为 `levels×(1−gloss)`，值越大反射越清晰 |
| _n.A | 细节材质混合遮罩，参与 Albedo、Normal 和 Metallic 的 detail 层选择；13 变体中 `w=clamp(2.05×(0.5−float19×(A−0.5))−1.05,0,1)`。不是 AO，也不是 alpha test 的那一张图 |
| _m.R | 金属度主值，材质可附加偏移或按 `_n.A` 混合；13 Fwd 明确出现 `diffuse=albedo×(1−metallic)` 与 `F0=lerp(0.04,albedo,metallic)` |
| _m.G/B/A | BC4 没有独立的 G/B/A 贴图数据，不能承载 roughness/AO/额外 mask。本机额外 `decoded/channels.json` 验证 texconv 展开为灰度 R=G=B（0..255）、A=255；RGB 复制不构成独立通道 |
| _rope_a | 仍为 AlbedoMap；独立 atlas/分辨率，不能误并到普通 a 后缀 |
| _v（1600 头部） | BC5_UNORM、linear、TPF Format 104；`P[HD_M_1600]_Shell` 的 `C_Shell__FurBlur_snp_Texture2D_1_VectorMap` 引用。能确认双通道向量图及用途类别；本次未反推具体缩放和轴约定 |

### 反汇编可直接定位的证据

文件名均相对 `material_evidence/shader_asm/`，SSA 编号不是推测标签：

- `C[DetailBlend]_13_Gbuf.ppo.asm`：`%77` 采样 t2；`%78/%79/%80/%81` 提取 RGBA。`%231..%238` 将 RG 解码并重建 Z；`%253..%261` 组合切线空间方向。`%84..%90` 由 A 生成混合系数；`%228/%229/%264` 从 B 与细节 B 生成光泽值。
- 同文件：`%186/%187` 从 t8 仅提取 R，`%190..%193/%268` 形成金属度；没有提取该采样的 G/B/A。
- `C[DetailBlend]_13_Fwd.ppo.asm`：主 NormalMap.B 从 `%104/%107` 到 `%255/%256/%294`；经修正到 `%425`，再经 `%945/%946/%947` 计算反射 mip；`%1083/%1091` 用该 mip 采样环境反射。金属度修正后的 `%495` 用于 `%516..%528` 的 diffuse/F0 分支。
- `C[DetailBlend]_13_Gbuf_[A].ppo.asm`：Texture2D_7 采样及其 A，之后出现 `dx.op.discard`。这是 alpha test 的证据，不是仅凭 `g_AlphaRef` 参数名推断。
- 0、6 Gbuf 也已保存，供 Rope/Fabric 的具体变体逐项核对。上面的详细公式以 13 变体为准，不能推广到所有 ER shader。

## 三套对照与对暴雷转换的含义

1010、1500、1600 同样出现本地 a=BC1 sRGB、m=BC4 linear、n=BC7 linear，但包含 Chain、Scale、Gauntlet、PantsBoots、Fur_Color、met_n、1m、v 等额外后缀，且 1600 有独立 Shell shader。全部 53 个条目的实际格式已逐条记录，不把这些后缀硬编码为全游戏通用通道表。

选择 1280 Fabric 模板时，应供给底色 a、金属度 m 的 R，以及正确两分量法线/光泽/细节混合打包的 n。Apex roughness 如果后续本机数据证实是 0..1 粗糙度，转换到这里的光泽通道需要相应反向处理，并结合模板 detail.B；不能直接把普通 XYZ 法线塞入 n 的 RGB。`_n.A` 应按希望保留的模板细节层设计，不能直接塞 AO。本任务不解析 Apex 资源，因此没有给出暴雷贴图的具体通道读取方式或轴翻转结论。

构建器只保证编码、槽名映射与模板参数克隆，不替代这个语义转换步骤。原版往返保留 AAT 和所有参数；自定义图若仍带原版细节会改变外观，后续应基于需要显式调整材质，而不是默认删掉共享图。
