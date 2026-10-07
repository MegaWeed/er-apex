# T007 许可与来源

- `miles.py` 的 MBNK v49/event/source 结构与选择器遍历依据只读本机
  `tools/apexassets/rsx_source/src/game/audio/{miles,event,source}.{h,cpp}`，
  RSX 2.3.0 / commit 2c63d87，r-ex/rsx，AGPL-3.0。
  导出 Python 工具按 AGPL-3.0-only 发布，完整源码即本目录的 Python 文件，
  许可全文见 `LICENSE`。未更改、复制或重编译 T001 的 RSX。
- `miles.py` 的 `lzb_decode` 是 `rad_lzb_simple.c` 的有边界检查 Python 改写，
  移除了优化性过量读写；保留同样的 LZB 控制字、长度扩展、重叠复制和 false-9 末尾。
  Copyright (c) Epic Games Tools，MIT，见 `LICENSE.rad-lzb`。
  原始许可来自本机 RSX `thirdpartylegalnotices.txt` 的 rad_lzb_simple 项。
- 音频解码通过现有 T001 RSX 独立进程完成，不将 RSX 或解码库链接到
  `deps/er-apex-audio`。RSX 和其解码依赖的声明沿用 `tools/apexassets/THIRDPARTY.rsx.txt`。
- Rust crate 使用 crates.io 的 CPAL（Apache-2.0）、crossbeam-queue/utils
  （MIT OR Apache-2.0）、hound（Apache-2.0）、serde/serde_json（MIT OR Apache-2.0）、
  thiserror（MIT OR Apache-2.0）；准确版本见 `deps/er-apex-audio/Cargo.lock`，
  许可文本保留在 Cargo registry 的各依赖源码中。
- Apex 原始及派生 WAV 的权利属于游戏权利人，只放 `apex-data/audio/`，不入库。

