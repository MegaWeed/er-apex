# T015：Octane 身体 → ER 模型 999 四部位护甲

从本机 Octane 默认身体 LOD0 Cast、87 骨骨架、Fuse S2b owner 和 c0000 HKX 参考姿态生成护甲；沿用 T005 的轴转换、骨盆比例、绑定姿态、全部源权重蒙皮、四部位拆分及材质通道规则。Python 3.13、NumPy、Pillow、现有 .NET、ertool、erextract、texconv；无资产下载，不启动游戏。

在仓库根目录运行：

```powershell
python tools/octanemesh/convert_octane.py
python tools/octanemesh/verify_octane.py
```

默认输入材质包是 `scratch/mod/package/material/allmaterial.matbinbnd.dcx`。可指定其它本机输入：

```powershell
python tools/octanemesh/convert_octane.py --matbin-bnd er-data\extract\material\allmaterial.matbinbnd.dcx
```

`--out` 只接受 `er-data\s3\octane` 及其子目录；独立验证接受同一参数。默认完整转换从空目录工作，不依赖已生成的 Fuse/Octane 护甲包。所需 T003 原版网格/材质证据、S2b 映射和已编译工具仍是只读输入。

```powershell
# 几何、通道和预览；不封包
python tools/octanemesh/convert_octane.py --geometry-only

# 完整封包和验证，迭代时省略预览
python tools/octanemesh/convert_octane.py --skip-previews

# 空子目录复现完整结果
python tools/octanemesh/convert_octane.py --out er-data\s3\octane\repro
python tools/octanemesh/verify_octane.py --out er-data\s3\octane\repro
```

## 输出

- `package/`、`package_flipy/`：各八个 `parts/{hd,bd,am,lg}_m_0999{,_l}.partsbnd.dcx` 和 `material/allmaterial.matbinbnd.dcx`；第二套仅翻转主法线绿通道。
- `fusemesh/`、`fusemesh_flipy/`：构建器兼容的 fusemesh v1，四部位二进制数组和实际输入 PNG。
- `owner-map.json`：87 根骨的 owner、同名继承/最近祖先规则、父骨和继承链；71 根同名、16 根新辅助骨。
- `align.json`：T005 `fuse-align` v1、列向量；87 根 A/P、60 对 P/E/O、骨名顺序、轴矩阵和缺失 Jaw 声明，供后续重定向使用。
- `geometry-summary.json`：源影响数、四权重损失、绕序、四部位、每个祖先重绑顶点及位置、量化权重变形统计。
- `deformation-contacts.json`：源重合点的参考/变形间隙及最差顶点位置；与拆分复制顶点的接缝统计分开记录。
- `texture-audit.json`：材质模板、每张本机源贴图、DDS 编码、透明判断及所有待定项。
- `source-manifest.json`：输入路径、大小和材质包逐字节复制结果。
- `material-bundle-preparation.json`、`material-bundle-{package,package_flipy}.json`、`material-bundle-verification-*.json`：全量条目保留、同名替换、新增记录；直接比较原始内容、顺序、ID、名称、标志与压缩元数据。
- `verification.json`、`readback-verification.json`：转换内验证和独立验证。
- `preview/`：四张部位颜色图、正/侧/背纹理图叠加 ER 骨架、两张变形图，共九张 PNG。
- `inputs/`、`readback/`、`logs/`、`checks/`、`helper/`：材质快照、模板、独立解包、贴图独立重编码、日志和输出内编译的小辅助程序。

## 几何与蒙皮

`C=diag(0.0254,0.0254,-0.0254,1)`，`Q[:3,:3]=s*C[:3,:3]`，`s=ER Pelvis.y/(0.0254*Octane hip.y)`。两边 Y 向上、左侧 +X，脚尖 Z 相反。源单位元数据没有明示英寸，0.0254 的解释沿用本机导出器标定推断；最终比例直接来自两边骨盆高度。

映射关节的位置放到 ER 参考位置，骨段主轴和解剖次轴决定旋转。Octane 缺 `def_c_jawA`，过滤该对，不创建虚构骨；头主轴 +Y、次轴 −Z，与 T005 头部规则一致。其余骨保持原局部矩阵跟随最近映射祖先。新增 right-leg shock 辅助骨按同名无 `_shock` 父骨的 owner 合并，随 ER 大腿/小腿/足/趾动画运动。

全部源权重先执行 `sum(w * P * inverse(A) * v)`，然后按 owner 合并、取前四、归一化。逐三角按不支持权重成本、祖先层数和主导解剖区域拆分，只引用当前模板 Bone 且非 Disabled 的节点。记录必要的最近 HKX 祖先回退；本机默认模型没有强制回退顶点。镜像和 ER against-normal 绕序各翻一次，最终索引顺序同源 Cast；切线来自 UV 的 V 导数，W 随镜像翻转。

变形试验使用与现有构建器一致的 float32 最大余数 8 位量化权重，L_Forearm +90°、Head +45°、R_Thigh +60°。高低模和各内置面组都复用 LOD0，没有简化。

## 材质包保留与替换

不重编译或修改 `tools/erdata/`。转换器先逐字节复制输入包到输出，`bundle/` 小程序只引用现有 SoulsFormats DLL，编译的 obj/bin 全部位于输出目录。NuGet/.NET 常规缓存限于任务允许的用户缓存根目录。

现有 `ertool build-armor` 只接受新增目标名称。因此转换器在私有 builder 副本中去掉同名 Octane 999 条目，然后调用原构建器；finish 步骤将替换内容放回输入条目的原位置，保留原名称、ID、标志和压缩元数据。其余输入条目逐字节保留；新增 Octane 条目追加。默认输入没有 Octane 名称冲突。所有替换均记录，输入本身保持只读。没有使用 SHA256。

## 通道、待定项与读回验证

六个身体材质都用所在部位的 Metal：HD/BD/LG 1280，AM 1500；这些模板均有本地 a/n/m 槽。本机六份源材质的 blend mask=0、八个 blend state 都为 `0xF0000000`，没有识别到透明混合材质；源底色零 alpha 像素仍记录，其语义待定，输出 A=255。

`a.RGB=_col.RGB`，不乘 AO；`n.RG=_nml.RG`、`n.B=_gls.R`、`n.A=255`。`m.R` 沿用 T005 的待定 specular→metalness 近似，头材质固定非金属。法线绿通道和光泽数值映射待定，提供 flipy 包。共享 AAT 细节以平坦图替换，底色 sRGB=129、法线=(128,128,128,255)、金属=0；float0/2/10/15=0、float19=1，仅覆盖模板存在的对应 Float 参数。

验证用独立 erextract 解包，再用现有 ertool 读取 FLVER/TPF/MATBIN；两套包共 16 个高低模都检查位置/索引字节、骨名、量化权重、模板节点、方向/UV 量化、六面组、材料和头/mesh/节点包围盒。从原 PNG 独立调用 texconv 重编码，要求所有 DDS 与读回字节一致，并检查通道、DXGI、完整 mip 链、颜色量化。完整材质包逐条直接比较，不依赖哈希；实际引用 Disabled Head 的负测试必须在写出 DCX 前拒绝。

游戏内仍须由 Claude 检查正常动画与剔除、髋/裆短边拉伸和原重合点微小间隙、法线绿通道、肤色/假肢/装备反射、光泽强度、AM Rich 采样器、眼镜/面罩与零 alpha 区域、未转移的 `_ilm/_sctr/_msk/_cav/_ao` 效果和 LOD0 性能。
