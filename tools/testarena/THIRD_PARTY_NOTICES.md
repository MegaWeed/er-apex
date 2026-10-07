# 第三方声明

本开发工具按 GPL-3.0 提供源码，完整许可见 `LICENSE`。

- **SoulsFormatsNEXT**：GPL-3.0，原作者 Joseph Anderson；引用本仓库只读源码快照 `tools/third_party/SoulsFormatsNEXT`，固定 commit `ee1dd61958f60bdc51ce3da548e9a90a8ab39905`。上游为 <https://github.com/soulsmods/SoulsFormatsNEXT>。使用 MSBE、EMEVD、DCX 读写；编译到独占数据目录，未修改上游源码。
- **erextract**：使用现有独立提取程序；其 MIT 许可与 er-mario 来源声明见 `tools/erdata/erextract/LICENSE`、`tools/erdata/THIRD_PARTY_NOTICES.md`。没有复制或链接其源码到本工具。
- **NuGet**：沿用 SoulsFormatsNEXT 项目声明的依赖和 `tools/third_party/nuget-feed` 中的现有包；版本及包 SHA256 见只读的 `tools/erdata/nuget.lock.json`。
- **DarkScript3 EMEDF**：仅将本机 `scratch/ref/er-common.emedf.json` 作为指令布局的第二来源，没有将该文件分发到源码目录；原版事件字节是主要证据。
- **游戏与 Oodle**：游戏文件和 `oo2core_6_win64.dll` 不属于本工具的开源许可。只从玩家安装目录读取和原位加载，不复制 DLL；游戏派生文件仅保存在 `er-data/test_arena`。

本工具是离线开发工具，不链接进 `er-fuse` 模组核心。
