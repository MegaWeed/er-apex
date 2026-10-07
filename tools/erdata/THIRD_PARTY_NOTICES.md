# 第三方声明

## erextract

archive.rs、dcx.rs、bnd4.rs 改编自 deltarooo/er-mario，MIT，Copyright (c) 2026 Delta。
原始完整许可保留在 erextract/LICENSE；来源 commit：32ffb23cf4cd557fa062cb377e0f6f8b773e21a8。
修改包括 exe 文件扫描、CLI、错误检查；没有嵌入游戏的 RSA 公钥或复制游戏 DLL。

## ertool

SoulsFormatsNEXT：GPL-3.0，完整许可在 ertool/LICENSE 和第三方快照 LICENSE。
本目录 ertool 按 GPL-3.0 发布源码。它是开发期工具，不链接进模组，不随模组发布。
上游：https://github.com/soulsmods/SoulsFormatsNEXT

HKLib：MIT，完整许可如下（上游：https://github.com/The12thAvenger/HKLib）。

MIT License

Copyright (c) 2023 The12thAvenger

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## 本地研究资源

Paramdex 与 UXM-Selective-Unpack 的固定源码快照只用于本机研究，未在快照根目录找到独立 LICENSE 文件。
Paramdex 使用 ER/Defs 与 ER/Names；UXM 只使用 EldenRingDictionary.txt，不构建或调用其修改游戏功能。
快照及字典不入库、不随模组发布。来源和 commit 见 dependencies.lock.json。

NuGet 包版本及 SHA256 见 nuget.lock.json；包只放 third_party/nuget-feed 或 NuGet 缓存。
游戏及其 Oodle DLL 不属于上述开源许可，工具从玩家安装目录读取，游戏派生输出只放 er-data。
