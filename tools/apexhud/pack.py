"""Reviewable ER-Apex drawing recommendations, separate from recovered data."""
import argparse
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
from legend import LEGENDS, load_legend, output_path


VIDEO = "user's R5R S3 video 2026-10-05 16:53 (1600x900, x1.2 to 1080p; scratch/video/oct1653)"


def build_pack(out, assets, rui, loc, palette, fonts, legend='fuse', info=None, upgrade_loc=None):
    info = info or load_legend(out, legend)
    if upgrade_loc is None:
        from export_hud import localization
        upgrade_loc = localization(out, keys=[u['name_key'] for u in info['upgrades']])
    lookup = {a['name']: a for a in assets if a['name']}

    def image(name):
        a = lookup.get(name)
        if not a or not a.get('image'):
            return None
        return {'asset': name, 'image': a['image'], 'guid': a['guid'], 'original_size': a['size'],
            'payload_image': a['payload_image'], 'payload_size': a['payload_size'], 'content_rect': a['content_rect']}

    def color(key, application='data row name supports intended use'):
        row = palette['colors'][key]
        return {'palette_key': key, 'rgb8': row['variants']['default'], 'alpha': 1.0,
            'source': row['source'], 'line': row['line'], 'value_status': 'data',
            'application_status': application}

    def layout(bounds, anchor):
        x, y, w, h = bounds
        return {'canvas': [1920, 1080], 'bounds_px': bounds, 'anchor': anchor,
            'anchor_position_px': {'center': [x+w/2, y+h/2], 'bottom_left': [x, y+h],
                'bottom_right': [x+w, y+h], 'bottom_center': [x+w/2, y+h]}[anchor],
            'size_px': [w, h], 'status': '推断：ER-Fuse 推荐布局',
            'basis': '任务指定中心准星/右下武器/左下生命；本机 RUI 的 element_size 为 1920×1080；精确锚点程序未解'}

    def geom(kind, reason):
        return {'kind': kind, 'status': '推断：用几何图形绘制', 'basis': reason}

    def base(id, names, bounds, anchor, rendering, states, binding):
        sources = ['rui/' + name + '.json' for name in names if name in rui]
        return {'id': id, 'mvp': True, 'rui_sources': sources,
            'recovered_rui_canvas': {name: rui[name]['element_size'] for name in names if name in rui},
            'layout': layout(bounds, anchor), 'rendering': rendering,
            'states': states, 'binding': binding, 'animation_status': '原 RUI 渲染/动画程序未解；推荐规则逐项标推断'}

    white = color('DEFAULT')
    hip_color = color('DEFAULT', '推断：普通腰射准星使用 DEFAULT；teamColor 由模组提供')
    head = color('HUD_DAMAGE_HEADSHOT')
    bleed = color('HUD_DAMAGE_TEXT_BLEED')
    tier_colors = {str(t): color(f'HUD_LOOT_TIER{t}', '推断：用于同等级护盾显示；没有解出原脚本调用') for t in range(1, 7)}
    weapon = image('rui/weapon_icons/r5/weapon_r301')
    portrait = image(info['portrait'])
    armor = image('rui/hud/gametype_icons/survival/sur_armor_icon')
    if weapon is None or portrait is None:
        raise RuntimeError(f'Required weapon icon / local {legend} portrait was not exported')
    # These names are read from the local weapon definition, including isAmped.
    # Resolve the repository input independently of the --out child directory.
    weapon_source = out / 'inputs/weapon/mp_weapon_rspn101.txt'
    text = weapon_source.read_text(encoding='utf8')
    crosshair_block = text[text.index('"RUI_CrosshairData"'):]
    bindings = dict(re.findall(r'"(adjustedSpread|adsFrac|isSprinting|isReloading|teamColor|isAmped|crosshairMovementX|crosshairMovementY|playerFov)"\s+"([^"]+)"', crosshair_block))
    elements = []
    cross = base('crosshair', ['crosshair_tri', 'crosshair_single_dot_helper'], [910, 490, 100, 100], 'center',
        [geom('three_radial_ticks_and_center_dot', '本机 ui/crosshair_tri 名称支持 tri 候选；没有默认图片引用；8 个 render jobs；具体几何与方向为推荐重建')],
        {'hip': {'rule': 'three ticks + dot; gap from adjustedSpread and playerFov', 'status': '推断'},
         'ads': {'rule': 'hip tick alpha = 1 - adsFrac; center dot remains', 'status': '推断：原分支/是否保留中心点待定'},
         'reload': {'rule': 'hide ticks and dot while isReloading', 'status': '推断：RUI 确有该输入，隐藏逻辑待定'},
         'sprint': {'rule': 'hide ticks and dot while isSprinting', 'status': '推断：RUI 确有该输入，隐藏逻辑待定'},
         'movement': {'rule': 'center follows crosshairMovementX/Y in screen pixels', 'status': '推断：原单位/缩放待定'}},
        {'adjustedSpread': 'spike::gun::hud().spread_deg', 'adsFrac': 'hud().aiming converted to 0/1; continuous zoom requires new state',
         'isReloading': 'hud().reload.is_some()', 'isSprinting': '待接 ER locomotion；当前 HudState 没有',
         'playerFov': 'CSCamera::pers_cam_1.fov (ER radians; convert to degrees if using original RUI input)',
         'teamColor': 'mod reticle/team color; player preference', 'crosshairMovementX/Y': '待接相机/武器位移；推荐默认为0'})
    cross['data_parameters'] = {'source': 'inputs/weapon/mp_weapon_rspn101.txt:RUI_CrosshairData',
        'bindings': bindings, 'base_spread': 0.0, 'status': 'data：名字和变量来源；不是已恢复的渲染规则'}
    # 2026-10-05 measured on the user's R5R (S3) video: one tick up, two down to the left and right,
    # each a white bar with a dark outline all round; the dot a white square, outlined too
    cross['geometry'] = {'tick_angles_degrees': [90, 210, 330],
        'angle_convention': 'counterclockwise from +x with y up: 90 is the top tick',
        'tick_length_px': 22, 'thickness_px': 2.4, 'outline_px': 1.2,
        'center_dot_shape': 'square', 'center_dot_radius_px': 1.2, 'minimum_gap_px': 5,
        'gap_formula': 'tan(spread_deg*pi/180) / tan(vertical_fov_radians/2) * viewport_height/2',
        'measured': {'source': VIDEO, 'frames_s': [28.0, 29.0, 30.0],
            'tick_900p': 'white 18.5 x 2 px, outline 1 px round it (ends too)', 'dot_900p': 'white 2 x 2 px, outline 1 px',
            'gap_900p': '55-78 px while moving (state and FOV unknown)'},
        'status': '实测（视频）：方向、刻度长宽、描边与中心点；推断：间隙公式与最小间隙（spread_deg 半角、ER fov 垂直角，原 adjustedSpread 单位未解）'}
    cross['colors'] = {'normal': hip_color, 'team_override': 'teamColor input'}
    elements.append(cross)
    weapon_element = base('weapon_slot', ['weapon_hud_v2', 'weapon_and_player_info', 'weapon_name'],
        [1510, 930, 350, 112], 'bottom_right', [weapon, geom('slanted_panel_and_bitmap_text',
            'weapon_hud_v2 的 RUI 包含文字/图片槽；实际面板轮廓和字号未解')],
        {'normal': 'show localized name, magazine and reserve separately',
         'empty': {'color': color('DANGER_WARNING_RED'), 'status': '推断：选用同名本机警告色'},
         'reloading': {'show_progress': True, 'status': '推断：下沿进度条'},
         'no_reserve_source': 'display --; never interpret magazine capacity as reserve'},
        {'name': 'localization[#WPN_RSPN101][player_language]', 'magazine': 'spike::gun::hud().ammo',
         'capacity': 'spike::gun::hud().clip', 'reserve': '待实现：HudState 没有 reserve；当前不能显示真实备弹',
         'reload_progress': 'spike::gun::hud().reload'})
    weapon_element['colors'] = {'text': white}
    weapon_element['localization_key'] = '#WPN_RSPN101'
    weapon_element['children'] = {'icon': [135, 6, 174, 49], 'weapon_name': [18, 8, 110, 28],
        'magazine_text': [18, 47, 100, 52], 'reserve_text': [115, 59, 76, 30], 'reload_track': [18, 104, 308, 3]}
    weapon_element['text_sizes_px'] = {'name': 24, 'magazine': 46, 'reserve': 27, 'status': '推断'}
    elements.append(weapon_element)
    health = base('health', ['unitframe_survival_v3'], [60, 926, 392, 116], 'bottom_left',
        [portrait, geom('slanted_identity_panel_and_health_bar',
            'unitframe_survival_v3 的数据中有 white 图片、文字和多个图片槽；暴雷头像来自角色 galleryPortrait；形状/尺寸为推荐')],
        {'normal': 'fill fraction = hp/max_hp', 'damaged': {'trail_seconds': 0.35, 'status': '推断'},
         'dead': 'show empty bar', 'name': 'player_name; legend label from local character localization'},
        {'hp': 'spike::lethal::fuse_hp()', 'max_hp': 'spike::lethal::FUSE_MAX_HP (100)',
         'player_name': '待接玩家名；不要把暴雷本地化名字当作玩家名'})
    health['colors'] = {'fill': white, 'damage_trail': bleed}
    health['children'] = {'portrait': [0, 0, 94, 94], 'player_name': [112, 3, 250, 28],
        'legend_name': [112, 33, 180, 23], 'health_track': [112, 79, 263, 14], 'hp_text': [112, 97, 220, 18]}
    if legend == 'octane':
        health['localization_key'] = info['name_key']
        health['rendering'][1]['basis'] = health['rendering'][1]['basis'].replace('暴雷', '动力小子')
        health['binding']['player_name'] = health['binding']['player_name'].replace('暴雷', '动力小子')
    elements.append(health)
    shield = base('shield', ['unitframe_survival_v3'], [172, 984, 263, 17], 'bottom_left',
        ([armor] if armor else []) + [geom('segmented_bar',
            'unitframe_survival_v3 有多个整型/百分比输入；同包命中 RUI 引用 sur_armor_icon；分段几何没有解出')],
        {'level': 'HUD_LOOT_TIER<level> palette', 'damage': 'fill each segment by shield fraction',
         'no_source': 'hide when shield_max is absent or zero',
         'segment_unit_hp': {'recommended': 25, 'status': '推断：未从本机数据确认，需模组配置/护盾系统提供'}},
        {'hp': '待实现：lethal.rs 当前只保存血量', 'max_hp': '待实现', 'level': '待实现',
         'segment_count': 'shield system/config; must not infer HP from tier color'})
    shield['colors'] = {'by_level': tier_colors}
    elements.append(shield)
    hit = base('hit_marker', ['player_hit_indicator'], [943, 523, 34, 34], 'center',
        [geom('four_diagonal_ticks', 'player_hit_indicator 没有默认十字图片引用；用几何重建，X 的形状/寿命为推断')],
        {'body': {'palette': 'DEFAULT', 'status': '推断：仅默认白色数据已知'},
         'headshot': {'palette': 'HUD_DAMAGE_HEADSHOT', 'status': '颜色数据；用于标记的映射为推断'},
         'shield': {'palette': 'HUD_LOOT_TIER<level>', 'status': '颜色数据；标记映射和优先级为推断'},
         'fade_seconds': {'recommended': 0.15, 'status': '推断：沿用现有 er-fuse/src/hud.rs 时长'}},
        {'event': 'spike::gun::hud().last_hit (Instant, headshot)',
         'shield_hit': '待扩展命中事件：当前没有 shield bool/level'})
    hit['colors'] = {'body': white, 'headshot': head, 'shield_by_level': tier_colors}
    hit['geometry'] = {'legs_degrees': [45, 135, 225, 315], 'inner_radius_px': 24, 'outer_radius_px': 40,
        'thickness_px': 2.4, 'outline_px': 1.2,
        'measured': {'source': VIDEO, 'frames_s': [17.5, 18.0, 18.4, 18.6, 19.0],
            'legs_900p': 'from 20.0 to 33.5 px off the centre along the diagonals, about 2 px wide, faint dark edge'},
        'status': '实测（视频，开镜命中）；腰射时是否随散布外移待定'}
    elements.append(hit)
    damage = base('damage_numbers', ['floating_damage_text', 'stacking_damage_text', 'stacking_damage_text_simple'],
        [1000, 454, 200, 66], 'center', [geom('bitmap_text',
            '本机 RUI 的 Color/string/int/时间参数以及 font 图集支持文字；位置轨迹和字型选择未解')],
        {'health_hit': {'palette': 'HUD_DAMAGE_TEXT_BLEED', 'status': 'data row supports health damage text'},
         'headshot': {'palette': 'HUD_DAMAGE_HEADSHOT', 'status': 'data row supports headshot'},
         'shield_hit': {'palette': 'HUD_LOOT_TIER<level>', 'status': '推断：使用护盾等级色；原脚本映射待定'},
         'priority': {'recommended': 'headshot > shield > health', 'status': '推断'},
         'rise_px': {'recommended': 28, 'status': '推断'},
         'lifetime_seconds': {'recommended': 0.6, 'status': '推断'}},
        {'damage': '待从 spike::combat::shoot 发布实际伤害事件',
         'headshot': 'gun last_hit.1 可用于标记，但伤害事件应统一带该字段',
         'shield': '待实现', 'position': '待从命中世界点投影；推荐默认准星旁'})
    damage['colors'] = {'health': bleed, 'headshot': head, 'shield_by_level': tier_colors}
    elements.append(damage)
    boss = base('boss_health', ['boss_guts_healthbar_hud', 'targetinfo_npc_basic'],
        [480, 854, 960, 47], 'bottom_center', [geom('target_health_bar_and_bitmap_name',
            '本机确有 boss_guts_healthbar_hud：4个样式、9个参数、4个render jobs；本次用 Apex 色和几何重建')],
        {'normal': 'fraction = ER displayed boss hp / hp_max', 'damage': {'trail_seconds': 0.4, 'status': '推断'},
         'inactive': 'hide if no active ER boss health display'},
        {'list': 'CSFEMan::boss_health_displays (combat.rs::is_boss 已读取此列表)',
         'hp': 'handle resolved ChrIns.modules.data.hp', 'max_hp': 'ChrIns.modules.data.max_hp',
         'name': 'Claude 从 ER 名称/血条列表取；包不硬编码 Boss 名称',
         'apex_hp_multiplier': '不能用于血条比例；显示应取同一目标的 ER hp/max_hp'})
    boss['colors'] = {'fill': color('HUD_DAMAGE_TEXT_BLEED', '推断：为 ER Boss 使用本机血量伤害色'), 'name': white}
    boss['children'] = {'name': [0, 0, 960, 28], 'track': [0, 31, 960, 14]}
    elements.append(boss)
    abilities = []
    for id, ability in info['abilities'].items():
        path = ability['asset']
        icon = image(path)
        entry = {'id': id, 'mvp': False, 'image': icon,
            'layout': layout([880 if id == 'ultimate' else 530 if id == 'tactical' else 485, 974, 72, 68], 'bottom_center'),
            'states': 'M4：就绪/冷却/充能；当前模组接口待实现', 'binding': 'future ability state',
            'status': 'located' if icon else '待定'}
        if legend == 'octane':
            values = loc.get(ability['name_key'], {}).get('values', {})
            entry.update({'name_key': ability['name_key'], 'name_text': values.get('schinese'),
                          'name_status': 'data' if values.get('schinese') else '待定：本机中文名称缺失',
                          'source': ability['source']})
        abilities.append(entry)
    upgrades = []
    for upgrade in info['upgrades']:
        icon = image(upgrade['asset'])
        values = upgrade_loc.get(upgrade['name_key'], {}).get('values', {})
        entry = dict(upgrade)
        entry.update(icon or {'image': None})
        entry.update({'name_text': values.get('schinese'),
                      'name_status': 'data' if values.get('schinese') else '待定：本机中文名称缺失',
                      'status': 'located' if icon else '待定：本机图标未定位'})
        upgrades.append(entry)
    candidates = [p for f in fonts for p in f['profiles'] if p['font_index'] == 11 and all(str(ord(c)) in p['glyphs'] for c in 'R301')]
    if not candidates:
        raise RuntimeError('No local font profile has required R301 glyphs')
    chosen = next(f for f in fonts if any(p is candidates[0] for p in f['profiles']))
    # Every located image by its Apex path, for HUD layouts beyond the MVP elements (ER-Fuse HUD v2).
    images = {a['name']: image(a['name']) for a in assets if a['name'] and a.get('payload_image')}
    return {'schema_version': 1, 'task': 'T017' if legend == 'octane' else 'T009', 'canvas': [1920, 1080],
        'images': images,
        'legend_upgrades': upgrades,
        'path_base': 'directory containing hud_pack.json',
        'coordinate_system': 'top-left origin; +x right; +y down; px on reference canvas',
        'scaling': {'recommended': 'uniform scale=min(viewport_width/1920,viewport_height/1080), center canvas', 'status': '推断'},
        'provenance_policy': 'data = local files; 推断 = integration recommendation; 待定 = unresolved',
        'assets': 'assets.json', 'palette': 'palette.json', 'localization': 'localization.json',
        'font_catalog': 'fonts/fonts.json', 'font_choice': {'guid': chosen['guid'], 'font_index': 11,
            'numeric_font_index': 22, 'bold_font_index': 19,
            'status': '推断：目视字形样张选择本机字型11正文、22数字；19（粗体、斜杠零）按用户 10-04 的 Apex 截图里弹匣/方位数字选择；未确认原武器 HUD 字型'},
        'default_language': 'schinese', 'language_status': '预览选择；运行时从玩家/模组语言选择，包保留14种本机本地化',
        'elements': elements, 'optional_elements': abilities,
        'integration_gaps': ['真实备弹', '冲刺/连续ADS', '护盾状态', '玩家名', '实际伤害事件', 'Boss显示列表/名称适配'],
        'preview_state': {'status': '示意状态，不是游戏采样', 'player_name': 'PLAYER', 'hp': 75, 'max_hp': 100,
            'shield_hp': 75, 'shield_max': 100, 'shield_level': 3, 'segment_count': 4,
            'magazine': 21, 'reserve': None, 'damage': 15, 'boss_fraction': 0.68, 'boss_name': '{ER BossName}',
            'hip_spread_deg': 3.0, 'fov_radians': 1.5707963267948966,
            'sample_values_status': 'magazine/spread/damage 来自 R-301 默认武器数据；其余数值为示意，尤其护盾/Boss并未采样'},
        'limitations': ['没有还原 RUI 渲染程序，所有位置/锚点/尺寸/几何/动画是推荐推断',
            '原始 font 字型名、字距和 shader 待解；原 R8 atlas 保留',
            '字体 mask 和预览用于审查，不代表原游戏逐像素截图']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legend', choices=LEGENDS, default='fuse')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    out = output_path(args.legend, args.out)
    read = lambda path: json.loads((out / path).read_text(encoding='utf8'))
    pack = build_pack(out, read('assets.json')['assets'], read('rui/summary.json')['assets'],
                      read('localization.json'), read('palette.json'), read('fonts/fonts.json')['fonts'],
                      args.legend)
    from export_hud import write_json
    write_json(out / 'hud_pack.json', pack)
    print(f'{args.legend}: wrote {out / "hud_pack.json"}')


if __name__ == '__main__':
    main()
