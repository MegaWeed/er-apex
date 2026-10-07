# 本机骨骼映射与转换配方

依赖 Python 3 + NumPy（本轮 2.5.0）。游戏原始/派生数据只从 apex-data、er-data 读取和再生成，不入库。

在仓库根目录运行 python tools/retarget/skeleton_map.py，生成 er-data/s2b/mapping-v0.json。前置：T001、T002、T003 的导出和 S2c 运行时转储就位。所有路径均可用命令行参数覆盖。

核心映射人工定义，辅助骨继承最近映射祖先；这是 v0 参考配方，使用时必须补偿各自参考姿态，不能直接复制欧拉角或四元数。
