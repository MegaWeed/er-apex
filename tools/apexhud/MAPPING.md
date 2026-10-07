# Apex HUD → ER-Fuse 映射（1920×1080）

集成入口：`apex-data/hud/hud_pack.json`。下表坐标均为本次**推荐推断**；资源名、GUID、译文和色值则来自本机游戏，证据在 `assets.json`、`rui/`、`palette.json`、`inputs/`。

| Apex 元素/数据 | ER-Fuse 显示 | 推荐框 `[x,y,w,h]` / 锚点 | 模组数据与接口缺口 |
|---|---|---|---|
| `ui/crosshair_tri` | R-301 腰射准星 | `[910,490,100,100]` / 中心 | `spike::gun::hud().spread_deg`；`CSCamera::pers_cam_1.fov`；按投影公式估算间隙，半角和 FOV 约定需确认 |
| 同 RUI 的 `adsFrac` | ADS 准星 | 同中心 | 当前 `HudState.aiming` 转 0/1；连续 ADS 进度需新增。推荐腰射线淡出、中心点保留；精确原逻辑待定 |
| `isReloading/isSprinting` | 准星显隐 | 同中心 | 换弹用 `hud().reload.is_some()`；冲刺当前未提供，需从 ER locomotion 取得；推荐隐藏为推断 |
| `crosshairMovementX/Y`、`teamColor`、`isAmped`、`playerFov` | 位移、颜色及武器状态 | 中心 + 动态偏移 | 位移、teamColor、Amped 均待接；本机定义确有这些参数，原单位及分支未解，不按短哈希硬认参数名 |
| `rui/weapon_icons/r5/weapon_r301` + `#WPN_RSPN101` | 主武器图片及玩家语言武器名 | `[1510,930,350,112]` / 右下 | 原逻辑 PNG 640×320，像素区457×144；`content_rect` 为 UV 推断并校验；文字按 `localization.json` 取玩家/模组语言 |
| `ui/weapon_hud_v2` 的数字/图片槽 | 弹匣、备弹、换弹进度 | 武器框内 / 右下 | 弹匣是 `HudState.ammo`；容量是 `.clip`；`.reload` 是进度。**没有备弹字段，`clip` 不能当备弹**；未接数据时显示 `--` |
| `ui/unitframe_survival_v3` + 暴雷 `galleryPortrait` | 暴雷肖像、玩家名、血条 | `[60,926,392,116]` / 左下 | `spike::lethal::fuse_hp()` / `FUSE_MAX_HP=100`；玩家名另取，角色本地化名不是玩家名 |
| 护盾/护甲 RUI 图片槽 + `sur_armor_icon` | 护盾分段和等级 | `[172,984,263,17]` / 左下 | 当前 `lethal.rs` 只保存血量；需新增 `shield_hp/max/level/segment_count`。无数据则隐藏。单段推荐25是推断，不由等级色推 HP |
| `ui/player_hit_indicator` | 中央命中标记 | `[943,523,34,34]` / 中心 | `HudState.last_hit: Option<(Instant,bool)>` 提供时间和爆头；护盾命中、等级待加入事件。X 形与0.15秒寿命是推断 |
| `ui/floating_damage_text`、`ui/stacking_damage_text` | 命中伤害数值 | `[1000,454,200,66]` / 中心 | 需从 `spike::combat::shoot` 的实际处理结果发布 damage/headshot/shield/position；不能仅用武器定义的基础伤害冒充实际伤害 |
| `ui/boss_guts_healthbar_hud`、`ui/targetinfo_npc_basic` | Apex 风格 ER Boss 血条 | `[480,854,960,47]` / 底部中心 | `CSFEMan::boss_health_displays`；现有 `combat.rs::is_boss` 已读取列表。用 handle 解析到 `ChrIns.modules.data.hp/max_hp`；名称由 Claude 从 ER 取，包中不硬编码 |
| 暴雷 tactical/ultimate/passive 图标 | M4 技能栏 | 参见 `optional_elements` / 底部 | 本机 PNG 已找到并导出；技能充能、冷却、被动条件与 UI 行为尚待模组实现 |

## 本地色值与应用建议

来源：本次 `inputs/datatable/0xC803BD35ABD0972B.csv`；`palette.json` 保留 CSV 行号和色觉变体。以下是 `default` 列，RGB8。

| 来源键 | RGB | 推荐用途 / 确定程度 |
|---|---|---|
| `DEFAULT` | 255,255,255 | 普通文本/血条/普通命中标记；色值为数据，应用到标记和血条为推断 |
| `HUD_LOOT_TIER1` | 183,183,183 | 护盾等级1；色值为数据，具体护盾脚本调用未解 |
| `HUD_LOOT_TIER2` | 28,137,243 | 护盾等级2；同上 |
| `HUD_LOOT_TIER3` | 152,41,245 | 护盾等级3；同上 |
| `HUD_LOOT_TIER4` | 243,195,56 | 护盾等级4；同上 |
| `HUD_LOOT_TIER5` | 243,2,2 | 护盾等级5；同上 |
| `HUD_LOOT_TIER6` | 0,229,184 | 本机另有等级6色；不据此宣称 ER 已实现该护盾等级 |
| `HUD_DAMAGE_TEXT_BLEED` | 210,60,64 | 血量命中伤害数字；名称直接支持该用途。Boss 填充使用它属于适配推断 |
| `HUD_DAMAGE_HEADSHOT` | 255,188,0 | 爆头伤害数字；用于命中标记属于适配推断 |

推荐颜色优先级为爆头 > 护盾等级 > 血量；这不是已恢复的原脚本逻辑。`HUD_PROGRESSBAR_COLOR_HEALTH` 也是本地键，但名称属于进度条，不能直接证明暴雷主血条使用其红色。色觉模式及玩家自定义 reticle 色需由运行时设置决定。

## 推荐运行时快照

Claude 可在现有 `HudState` 外构造一次每帧快照，避免 UI 在多次读取之间看到不同状态。下面是接口建议，全部新增字段都应以真实运行时来源实现：

```text
weapon: localized_name, icon, magazine, capacity, reserve: Option<u32>, reload: Option<f32>
aim: ads_frac, spread_half_angle_deg, vertical_fov_radians, sprinting, movement_xy
player: player_name, hp, hp_max, shield: Option<{hp,max,level,segment_count}>
hit_events: [{time, actual_damage, headshot, shield_hit, shield_level, world_position}]
bosses: [{display_handle, hp, hp_max, localized_er_name, active}]
abilities: future tactical/ultimate/passive state
```

`reserve=None` 显示 `--`；`shield=None` 隐藏护盾；无 active Boss 则不画 Boss 血条。不能把示意图里的 75 护盾、68% Boss、15 伤害当作每帧默认值。Boss 条用 ER 同一对象的 `hp/max_hp`，不要把 `boss_apex_hp_mult` 与 ER 原始 HP 混合计算。

图片上传建议使用 RGBA8 并保留 alpha；字体原图是 R8 **SDF 距离场**，不能把 alpha 恒255的 atlas PNG 当作已带透明背景的字体，也不能把原 R 值直接视作普通字形覆盖率。裁切图的 alpha 仍是原距离场值，正式显示需要 SDF 解码；预览阈值只是推断。

图集不含字形基线/偏移度量；`fonts/<guid>/font.json` 的 `source_rect` 只给纹理区域，`advance_px` 只是裁切宽度近似值。正式文本接入需另取或恢复 baseline、bearing/offset、advance/kerning 与 shader。精确原版准星/ADS 瞄具和 RUI 动画也仍需进一步解析。

## HUD v2（2026-10-04，D-016）

ER-Fuse 的 HUD 版式改按用户提供的 Apex 游戏截图实测（指南针、左下玩家栏、右下武器栏），上表的推荐框只剩 Boss 血条和准星仍在使用。v2 另用到的本机数据：`hud_pack.json` 的 `images`（强化图标 `upgrade_fuse_big_bang` / `upgrade_fuse_explosive_recharge`、轻型弹徽章 `sur_ammo_bullet`）、`localization.json` 的 `#FIRE_MODE_AUTO`、`#LEGEND_UPGRADE_MAX_LEVEL`，颜色 `MEMBER_COLOR0`（队伍色边）、`HUD_LOOT_TIER3`（强化条）、`AMMO_SMALL_COLOR`（R-301 弹药色）；调色板里没有的颜色（面板灰、黄色模式标题）取自截图像素。护盾按 D-016 不做，玩家栏不画护盾行。
