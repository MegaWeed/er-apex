# T005 暴雷身体 → ER 四部位护甲

从本机已导出的 LOD0 Cast 和 c0000 HKX 参考姿态，生成模型号 999 的四部位护甲。Python 3.13、NumPy、Pillow；构建器沿用本机 .NET 8、SoulsFormatsNEXT、erextract 和 texconv。没有联网下载资产，也不启动游戏。

在仓库根目录运行：

```powershell
python tools/fusemesh/convert_fuse.py
```

输出固定在独占目录 `er-data/s3/fuse/`；可用 `--out` 指定该目录下的子目录。从零运行会重新计算、导出贴图和网格、从本机 ER 档案提取模板、构建两个包、读回验证。输出不依赖此前生成的 Fuse 产物。输入背景数据仍需要任务单列出的 T001/T003/S2b 导出，包括 `er-data/s3/original_mesh/` 与材质证据 JSON。

单独复算几何和预览：`python tools/fusemesh/convert_fuse.py --geometry-only`。迭代包时可 `--skip-previews`。独立复核已生成包：`python tools/fusemesh/verify_fuse.py`。

主要输出：

- `package/`、`package_flipy/`：各八个 `parts/{hd,bd,am,lg}_m_0999{,_l}.partsbnd.dcx` 和 `material/allmaterial.matbinbnd.dcx`；后者只翻转主法线贴图绿通道。
- `fusemesh/{hd,bd,am,lg}/`、`fusemesh_flipy/`：fusemesh v1 输入及实际使用的 PNG。
- `align.json`：轴/单位矩阵、统一缩放、231 根 P/A、61 对 P/E/O 与对齐规则，使用列向量。
- `geometry-summary.json`、`texture-audit.json`、`verification.json`：坐标、绕序、权重损失、拆分/祖先重绑的位置、变形、贴图语义及包读回结果。
- `preview/`：四张部位着色图；正/侧/背纹理图叠加 ER 骨架；两个变形图。
- `inputs/`、`readback/`、`logs/`：本机模板、独立 erextract 读回与命令输出。

## 几何约定

Apex 左 +X、上 +Y、前 +Z；ER 左 +X、上 +Y、前 −Z。脚尖、手指、嘴唇方向由本机骨架计算并记录。源单位按 0.0254 米换算；原 JSON 只写“unchanged Source model units”，所以英寸解释是结合本机导出器 `s_MetersToInches` 与骨盆 39.37 的推断，不能称为 JSON 的明示事实。最终几何比例由两边骨盆高度之比确定，和这个中间单位解释无关。

`Q=diag(0.0254*s,0.0254*s,-0.0254*s,1)`。顶点用 Q，骨架 A 用 `Q @ A_original @ Q^-1`，同时反射局部骨轴。映射关节位置放到 E；用骨段主轴及解剖次轴建立两个正交坐标框架，旋转为 `frame_ER @ frame_Apex.T`。躯干/头次轴为前 −Z，手臂/手指为掌面法线，腿为前 −Z，足/趾为侧 +X。终端手指沿父骨方向；头用语义向上而非 Head→Jaw，因为两边 Jaw 相对 Head 的高度不一致。未映射骨保持 A 局部矩阵、跟随最近映射祖先。

全部源影响（最多 16）先做 `Σ w*P*A^-1*v`，再按 mapping-v0 owner 合并、取四权重。方向用旋转部分并归一化。Cast 没有切线：先从原始 UV 求 U/V，保留所有权重变换 V，重新正交化；ER 实测存储 V，`cross(N,V)*W` 对应 U。Z 镜像翻转 W。

镜像先翻一次三角绕序保留原向，再为 ER 的 against-normal 序列化约定翻一次，因此最终索引顺序和源 Cast 相同。沿/逆法线统计单独记录；不能仅按“镜像就交换索引”决定最终 ER 绕序。

逐三角选择丢失启用骨权重最少的部位，按祖先层数和主导解剖区域打破并列；复制边界顶点。模板分别为 HD/BD/LG 1280、AM 1500。每部位只能用 `Bone` 且非 `Disabled` 的节点。Jaw 在头部模板中未启用，少量下颌顶点改绑 Head；没有启用 Disabled 节点。

## 材质与待定项

实际 Cast 是 **7 个网格、6 个唯一材质**，第二个 gear 是肩部发射器；没有 v_arms。各部位选自己的 Metal，头发/眼部透明覆盖层选 HD Fabric（alpha ref=50，已有 `[A]` discard shader 证据）。

`_a.RGB` 直接取 `_col`，不乘 AO。身体/装备/头 A=255；头发、eyeshadow A 取 `_col.A`。本机 cornea 是黑 RGB/不透明 A 加混合材质，alpha test 无法重现；保留全部 460 个三角但 A=0 隐藏该覆盖层，避免黑眼球。透明混合与毛发高光仍需后续材质工作。

`_n.R/G` 取原始 `_nml` 两通道，B 取 `_gls.R`，A=255。保留 UV 并修正切线手性，不因模型镜像额外翻法线通道。Apex 绿通道约定未经源 shader 证实，因此额外打出只翻 G 的包；在斜向光照下比较面部/衣料凹凸。

`_m.R` 采用明确标为**待定**的 specular→metalness 近似：`clamp((max(linear(spc))-0.04)/max(max(linear(col))-0.04,0.04),0,1)`。头/头发/眼部限制为非金属。已有导出数据不能唯一恢复物理金属度，须在游戏里检查皮肤、机械臂、手雷/发射器的反射。

A=255 只关闭第二细节层，不能独自取消第一层。输入通过构建器的新可选 `sampler_textures` 把 AAT 细节替换为平坦小图：albedo sRGB=129（线性约 1/4.55）、normal=(128,128,128,255)、metal=0；`float10=0` 关闭已反汇编的 detail normal，`float2=0` 去掉金属偏移、`float0/float15=0` 去掉细节光泽偏移。AM 1500 的 static switch 0 已对照本机 `C[DetailBlend]_0_Gbuf.ppo.asm` 核对 R/G 法线、B 光泽和 R 金属度；0 变体不读取主法线 A。其 Rich 槽绑定及最终游戏表现仍需核对。13 与 0 中 float2 是金属偏移、float0 是光泽偏移，已分别归零；不能误把 float15 当作金属偏移。

PNG→DDS 明确使用 DX10 头，避免 BC4U legacy FourCC 被固定解析器误判；底色 PNG 转 sRGB DDS 显式传 `-srgb`，避免二次 gamma 编码；格式仍按每部位模板实际编码确定。读回中性色块必须在输入 129 的 BC1 量化误差范围内。

## 回归验证与写入范围

测试仅写到本任务独占的 `er-data/s3/fuse/`。原 T003 两个脚本不改动：

```powershell
python tools/erdata/scripts/s3a_roundtrip.py --data-dir er-data\s3\fuse\regression
python tools/fusemesh/regression.py
```

`regression.py` 调用原 `verify_armor_builder.main()`，仅把它的 DATA 改为上述 regression 目录；原验证逻辑不变。包验证会额外拒绝胸甲中实际引用的 Disabled Head，验证两种包、八个高低模的精确位置/索引/骨名/最大余数量化权重和包围盒。低模复用 LOD0，不做网格简化。

代码：`geometry.py`（对齐/拆分）、`textures.py`（通道/材质）、`preview.py`（NumPy/Pillow 软件光栅化）、`convert_fuse.py`（编排）、`verify_fuse.py`（读回）。`cast.py` 和 `LICENSE.cast` 原样复制自 T001 的 MIT 读取器。
