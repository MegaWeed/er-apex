"""T009: reproduce an evidence-labelled HUD pack from the local Apex install.

Run from the repository root: python tools/apexhud/export_hud.py
No game launch, injection, network access, or git mutations.
"""
import argparse
import csv
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gamedirs  # noqa: E402  (tools/gamedirs.py: the games' install folders)
import time

sys.dont_write_bytecode = True
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf8')
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / 'apexdata'))
from rtech_hash import string_to_guid
from prepare_rsx import ensure_tool
from legend import HUD_ROOT, LEGENDS, output_path, load_legend
from PIL import Image
import numpy as np

DEFAULT_OUT = HUD_ROOT
RUI_NAMES = [
    'crosshair_tri', 'crosshair_single_dot_helper', 'weapon_hud_v2',
    'weapon_and_player_info', 'weapon_name', 'unitframe_survival_v3',
    'player_hit_indicator', 'floating_damage_text', 'stacking_damage_text',
    'stacking_damage_text_simple', 'boss_guts_healthbar_hud',
    'targetinfo_npc_basic', 'targetinfo_npc_trainingdummy', 'ability_hud',
]
PATH_RE = re.compile(r'(?<![\w/])(?:rui|ui)/[A-Za-z0-9_./-]+')
RUNS = []


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf8')


def read_json(path):
    return json.loads(path.read_text(encoding='utf8'))


def rel(path, root):
    return path.relative_to(root).as_posix()


def run_rsx(exe, game, out, name, destination, types, extra=(), packages=None):
    runtime = out / 'logs/runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    (out / destination).mkdir(parents=True, exist_ok=True)
    command = [str(exe), '-nogui', '-export', '-nocachedb', '-exportfullpaths',
        '--loadwhitelist', 'x', '--exportthreads', '4', '--parsethreads', '8',
        '--exporttypes', types, '--exportdir', str(out / destination),
        '--list', str(out / f'lists/{name}.csv'), '--listformat', 'csv']
    command += list(extra)
    command += [str(game / 'paks/Win64' / p) for p in (packages or ['ui.rpak', 'common.rpak', 'common_early.rpak'])]
    start = time.perf_counter()
    print(f'{name}: exporting {types}', flush=True)
    with (out / f'logs/{name}.log').open('wb') as log:
        result = subprocess.run(command, cwd=runtime, stdout=log, stderr=subprocess.STDOUT)
    RUNS.append({'name': name, 'command': command, 'cwd': str(runtime),
        'exit_code': result.returncode, 'seconds': round(time.perf_counter() - start, 3)})
    write_json(out / 'run_manifest.json', {'runs': RUNS})
    if result.returncode:
        raise RuntimeError(f'RSX {name}: exit {result.returncode}')
    if not (out / f'lists/{name}.csv').exists():
        raise RuntimeError(f'RSX {name}: no CSV output')


def parse_rui(txt):
    args = []
    for line in txt.splitlines():
        m = re.match(r'(\w+) (\w+)@(\d+)\t(.*)', line)
        if not m:
            continue
        kind, short_hash, offset, raw = m.groups()
        if kind in ('asset', 'Image', 'string'):
            value = raw.lstrip('$').strip('"')
        elif kind == 'bool':
            value = raw == 'true'
        elif kind == 'int':
            value = int(raw)
        elif kind in ('float', 'float2', 'float3', 'Color', 'GameTime'):
            values = [float(v.strip()) for v in raw.split(',')]
            value = values[0] if len(values) == 1 else values
            if isinstance(value, float) and not math.isfinite(value):
                value = None
        else:
            value = raw
        args.append({'type': kind, 'short_hash': short_hash, 'offset': int(offset),
            'default': value, 'raw': raw, 'name_status': '待定：本机 RUI 未保留参数名'})
    return args


def collect_sources(out, legend='fuse'):
    """Use only locally exported game data, recording the exact source location."""
    evidence = defaultdict(list)
    snapshots = []
    export = out / 'inputs'
    specific = [export / 'weapon/mp_weapon_rspn101.txt',
        export / f'settings/itemflav/character/{legend}.json']
    # Include references from the character rather than assuming the ability prefix.
    info = load_legend(out, legend)
    specific += [out / a['source'] for a in info['abilities'].values()]
    specific += [out / a['source'] for a in info['upgrades']]
    specific += list((export / 'datatable').glob('*.csv'))
    for source in sorted(set(specific)):
        if not source.exists():
            continue
        text = source.read_text(encoding='utf8', errors='replace')
        for i, line in enumerate(text.splitlines(), 1):
            for m in PATH_RE.finditer(line):
                path = m.group().removesuffix('.rpak')
                # Discovery is bounded to HUD/weapon and this legend's icons.
                if path.startswith('ui/') or path.startswith('rui/hud/') or any(s in path for s in ('weapon_r301', '/' + legend, '_' + legend)):
                    evidence[path].append({'kind': 'local_export_string',
                        'source': rel(source, out), 'line': i})
        snapshots.append({'path': str(source), 'size_bytes': source.stat().st_size,
            'utf8_replacement_characters': text.count('\ufffd')})
    for meta in sorted((out / 'raw/ui').glob('*.meta.json')):
        d = read_json(meta)
        for ref in d['string_references']:
            if ref['path'] == 'white':
                continue
            evidence[ref['path']].append({'kind': 'RUI_relocated_string_reference',
                'source': rel(meta, out), 'default_data_offset': ref['default_data_offset'],
                'rui_guid': d['guid']})
    return evidence, snapshots


def localization(out, legend='fuse', info=None, keys=None):
    # Fire modes: the R-301 definition's fire_mode_1/2 keys. Max level: the key whose hash matches
    # the legend-upgrade "最高等级/Max Level" rows (ER-Fuse HUD v2, 2026-10-04).
    if keys is None:
        info = info or load_legend(out, legend)
        keys = ['#WPN_RSPN101', '#WPN_RSPN101_SHORT', info['name_key'], info['short_name_key'],
            '#FIRE_MODE_AUTO', '#FIRE_MODE_SINGLE', '#LEGEND_UPGRADE_MAX_LEVEL']
        # Preserve the original Fuse localization/font corpus exactly.
        if legend == 'octane':
            keys += [a['name_key'] for a in info['abilities'].values()]
            keys += [a['name_key'] for a in info['upgrades']]
    keys = list(dict.fromkeys(k for k in keys if k))
    # '0x<guid>': a row known only by its hash (export_extra.py, key name 待定)
    guid = lambda k: int(k[2:], 16) if k.startswith('0x') else string_to_guid(k.lstrip('#'))
    hashes = {f'{guid(k):x}': k for k in keys}
    result = {k: {'key_guid': f'{guid(k):016x}', 'values': {}} for k in keys}
    for source in sorted((out / 'inputs/localization').glob('*.locl')):
        lang = source.stem.removeprefix('localization_')
        for line in source.read_text(encoding='utf8').splitlines():
            m = re.match(r'^\s*"([0-9a-fA-F]+)" "(.*)"$', line)
            if m and m[1].lower().lstrip('0') in hashes:
                key = hashes[m[1].lower().lstrip('0')]
                result[key]['values'][lang] = m[2]
        for d in result.values():
            d.setdefault('sources', {})[lang] = rel(source, out)
    if '#WPN_RSPN101' in result and not result['#WPN_RSPN101']['values']:
        raise RuntimeError('Local R-301 localization was not found')
    return result


def palette(out):
    for source in sorted((out / 'inputs/datatable').glob('*.csv')):
        with source.open(encoding='utf8', newline='') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != ['colorName', 'default', 'protanopia', 'deuteranopia', 'trianopia', 'qa']:
                continue
            colors = {}
            for line_no, row in enumerate(reader, 2):
                if not re.fullmatch(r'<[-\d.,]+>', row['default']):
                    continue  # RSX's last CSV row carries column type names.
                colors[row['colorName']] = {'variants': {mode: [int(x) for x in row[mode].strip('<>').split(',')]
                    for mode in reader.fieldnames[1:]}, 'source': rel(source, out), 'line': line_no}
            required = ['DEFAULT', 'HUD_DAMAGE_TEXT_BLEED', 'HUD_DAMAGE_HEADSHOT', 'HUD_LOOT_TIER1', 'HUD_LOOT_TIER5']
            if all(k in colors for k in required):
                return {'colors': colors, 'default_mode': 'default',
                    'mode_status': '推断：预览采用 default；未读取玩家设置',
                    'source_guid': source.stem.removeprefix('0x').lower().zfill(16)}
    raise RuntimeError('Local color data table was not found')


def resolve_assets(out, rows, evidence, legend='fuse'):
    lookup = {int(r['guid'], 16): r for r in rows}
    assets = []
    # RUI names come from the postloaded in-package names, never guessed paths.
    for r in rows:
        if r['type'] == 'ui' and Path(r['asset_name']).stem in RUI_NAMES:
            path = r['asset_name'].replace('\\', '/').removesuffix('.rpak')
            evidence[path].append({'kind': 'RSX_postloaded_asset_name', 'source': 'lists/ui.csv'})
    for path, sources in sorted(evidence.items()):
        candidates = [path + '.rpak'] if path.startswith('ui/') else ['ui_image/' + path + '.rpak']
        matches = [(canonical, lookup.get(string_to_guid(canonical))) for canonical in candidates]
        canonical, row = matches[0]
        purpose = 'reference_discovery'
        if 'weapon_r301' in path:
            purpose = 'weapon_slot'
        elif legend in path:
            purpose = legend + '_identity_or_ability'
        elif any(x in path for x in ('crosshair', 'hit', 'armor', 'health', 'damage')):
            purpose = 'combat_hud_candidate'
        asset = {'name': path, 'canonical_hash_input': canonical,
            'guid': f'{string_to_guid(canonical):016x}', 'type': row['type'] if row else None,
            'package': row['file_name'] if row else None, 'rsx_asset_name': row['asset_name'] if row else None,
            'purpose': purpose, 'evidence': sources,
            'status': 'located_by_hash' if row else '待定：ui/common 中没有该 GUID'}
        assets.append(asset)
    for r in sorted(rows, key=lambda r: r['guid']):
        if r['type'] == 'font':
            assets.append({'name': None, 'guid': r['guid'].zfill(16).lower(), 'type': 'font',
                'package': r['file_name'], 'rsx_asset_name': r['asset_name'], 'purpose': 'font_atlas',
                'evidence': [{'kind': 'asset_inventory', 'source': 'lists/ui.csv'}], 'status': 'located_by_inventory'})
    return assets


def export_local_inputs(exe, game, out, rows, legend='fuse'):
    selected = []
    # octance_ is the spelling in the local character references/inventory.
    ability_prefix = 'octance_' if legend == 'octane' else 'fuse_'
    weapons = {'weapon/mp_weapon_rspn101.rpak'}
    if legend == 'octane':
        weapons.update(['weapon/mp_ability_octane_stim.rpak', 'weapon/mp_weapon_jump_pad.rpak'])
    for row in rows:
        name = row['asset_name'].replace('\\', '/')
        if row['type'] == 'dtbl' or name in weapons or name == f'settings/itemflav/character/{legend}.rpak' or name.startswith('settings/itemflav/ability/' + ability_prefix) or name.startswith(f'settings/itemflav/ability/upgrade_{legend}_'):
            selected.append(row['asset_name'])
    run_rsx(exe, game, out, 'game_inputs', 'inputs', 'stgs,wepn,dtbl', ['--exportexact', ','.join(sorted(selected))])
    locale_paks = [p.name for p in sorted((game / 'paks/Win64').glob('localization_*.rpak'))
        if '(' not in p.name and 'dedi' not in p.name]
    run_rsx(exe, game, out, 'localization', 'inputs', 'locl', packages=locale_paks)


def export_images(exe, game, out, assets):
    wanted = [a for a in assets if a['type'] == 'uiia' and (a['purpose'] != 'reference_discovery' or
        any(x in a['name'] for x in ['ammo', 'background', 'bg_', 'obj_background']))]
    if not wanted:
        raise RuntimeError('No UI images resolved')
    # RSX exact filter uses its unresolved displayed name, NOT the recovered name.
    names = ','.join(sorted({a['rsx_asset_name'] for a in wanted}))
    run_rsx(exe, game, out, 'images', 'raw/images', 'uiia', ['--exportexact', names])
    image_root = out / 'images'
    meta_by_guid = {read_json(p)['guid']: p for p in (out / 'raw/images').rglob('*.meta.json')}
    for a in wanted:
        guid = a['guid']
        meta = meta_by_guid.get(guid)
        source = meta.with_name(meta.name.removesuffix('.meta.json') + '.png') if meta else None
        if source is None or not source.exists():
            raise RuntimeError(f'UIIA {a["name"]}: missing PNG/metadata')
        target = image_root / (a['name'] + '.png')
        target.parent.mkdir(parents=True, exist_ok=True)
        d = read_json(meta)
        payload = out / 'payload_images' / (a['name'] + '.png')
        payload.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, payload)  # Original RSX PNG bytes, unchanged.
        original = Image.open(source).convert('RGBA')
        width, height = d['original_size']
        uv = d['header_floats_raw']
        offset = [round(-uv[0] * width), round(-uv[1] * height)]
        endpoint = [round(uv[2] * width), round(uv[3] * height)]
        if endpoint != [offset[0] + original.width, offset[1] + original.height] or min(offset) < 0 or endpoint[0] > width or endpoint[1] > height:
            raise RuntimeError(f'UIIA {a["name"]}: UV trim bounds do not agree with logical/payload dimensions')
        canvas = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        canvas.paste(original, tuple(offset))  # Exact RGBA copy; no alpha blending/resampling.
        canvas.save(target)
        im = Image.open(target)
        im.load()
        a.update({'image': rel(target, out), 'size': list(im.size), 'png_mode': im.mode,
            'alpha_range': list(im.getchannel('A').getextrema()) if 'A' in im.getbands() else None,
            'original_encoding': 'RTech UIIA tiled BC1/BC7',
            'original_metadata': d, 'metadata': rel(meta, out),
            'payload_image': rel(payload, out), 'payload_size': list(original.size),
            'content_rect': offset + list(original.size),
            'logical_canvas_restoration': {'status': '推断：header 浮点字段解释为裁切 UV；所有导出图片尺寸关系逐项校验',
                'offset_formula': 'round(-header_floats_raw[0:2] * original_size)',
                'extent_check': 'round(header_floats_raw[2:4] * original_size) == offset + payload_size',
                'pixel_operation': '透明画布上原样复制 payload RGBA；无缩放、无混合'}})
    return wanted


def export_fonts(exe, game, out, assets, loc, legend='fuse'):
    # Retain R8 original pixels in DDS in addition to RSX's RGBA PNG conversion.
    run_rsx(exe, game, out, 'font_dds', 'raw/font_dds', 'font', ['--format-font', '2'])
    fonts = []
    display_chars = set(map(chr, range(32, 127)))
    font_loc = dict(loc)
    if legend == 'octane':
        # Keep the original pack's glyph coverage, then add Octane characters.
        # These compatibility characters come from THIS export's local locl;
        # no Fuse pack is read, and its keys are never serialized in Octane loc.
        font_loc.update(localization(out, keys=['#character_fuse_NAME', '#character_fuse_NAME_SHORT']))
    for entry in font_loc.values():
        for value in entry['values'].values():
            display_chars.update(value)
    for asset in [a for a in assets if a['type'] == 'font']:
        guid = asset['guid']
        meta = next((p for p in (out / 'raw').rglob('*.meta.json')
            if 'ui_font_atlas' in str(p) and guid.upper() in p.name.upper() and 'font_dds' not in str(p)), None)
        if meta is None:
            raise RuntimeError(f'Missing exported font {guid}')
        source_png = meta.with_name(meta.name.removesuffix('.meta.json') + '.png')
        source_dds = next((p for p in (out / 'raw/font_dds').rglob('*.dds') if guid.upper() in p.name.upper()), None)
        if not source_png.exists() or source_dds is None:
            raise RuntimeError(f'Missing font PNG/DDS {guid}')
        destination = out / 'fonts' / guid
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_png, destination / 'atlas.png')
        shutil.copyfile(source_dds, destination / 'atlas.dds')
        shutil.copyfile(meta, destination / 'source.meta.json')
        d = read_json(meta)
        atlas = Image.open(source_png).convert('RGBA')
        profiles = []
        for f in d['fonts']:
            glyphs = {}
            for cp, texture, x, y, w, h in f['unicode_to_texture_rect']:
                if chr(cp) not in display_chars or not w or not h:
                    continue
                if x + w > atlas.width or y + h > atlas.height:
                    continue
                image = atlas.crop((x, y, x + w, y + h))
                # R8 is replicated to RGB and exported with alpha=255 by RSX.
                # For a convenient mask put the ORIGINAL R channel into alpha.
                mask = image.getchannel('R')
                rgba = Image.new('RGBA', image.size, (255, 255, 255, 0))
                rgba.putalpha(mask)
                file = destination / 'glyphs' / f'font_{f["font_index"]}' / f'U+{cp:04X}.png'
                file.parent.mkdir(parents=True, exist_ok=True)
                rgba.save(file)
                glyphs[str(cp)] = {'image': rel(file, out), 'source_rect': [x, y, w, h],
                    'texture_index': texture, 'size': [w, h],
                    'advance_px': w, 'advance_status': '推断：以裁切宽度代替；未恢复 kerning/advance'}
            profiles.append({'font_index': f['font_index'], 'name': f['name'],
                'name_status': '本机 font 未保留字型名' if f['name'] is None else 'data',
                'unicode_count': len(f['unicode_to_texture_rect']), 'glyph_texture_count': f['glyph_texture_count'],
                'glyphs': glyphs})
        entry = {'guid': guid, 'version': d['version'], 'atlas_guid': d['atlas_guid'],
            'atlas_png': rel(destination / 'atlas.png', out), 'atlas_dds': rel(destination / 'atlas.dds', out),
            'atlas_size': d['atlas_size'], 'original_format': 'DXGI_FORMAT_R8_UNORM' if d['dxgi_format'] == 61 else d['dxgi_format'],
            'metadata': rel(destination / 'source.meta.json', out), 'profiles': profiles,
            'ttf_otf': False, 'imgui_direct_load': False,
            'integration': '用 atlas 的 R 通道作 mask，按 Unicode UV/rect 绘制；ImGui AddFontFromFileTTF 不能直接加载。原生字距、SDF shader 与精确字型选择待解。',
            'derived_mask_status': 'R → alpha 为工具转换；未经原游戏 shader 验证'}
        write_json(destination / 'font.json', entry)
        fonts.append(entry)
        asset.update({'font': rel(destination / 'font.json', out), 'original_format': entry['original_format']})
    write_json(out / 'fonts/fonts.json', {'fonts': fonts})
    return fonts


def analyze_rui(out, assets):
    parsed = {}
    for name in RUI_NAMES:
        txt = out / 'raw/ui' / (name + '.txt')
        meta = out / 'raw/ui' / (name + '.meta.json')
        if not txt.exists() or not meta.exists():
            continue
        d = read_json(meta)
        d['arguments'] = parse_rui(txt.read_text(encoding='utf8'))
        d['sources'] = [rel(txt, out), rel(meta, out)]
        d['limitations'] = [
            '布局头的 element_size 是数据；元素屏幕位置、锚点和渲染分支未解出。',
            '样式 u16 字段多数呈 4 字节步长，且超过默认值区：疑为运行时偏移，不能当作颜色/字号/字体编号。',
            'shader_constants_f32 是无类型 4 字节视图；含整数位模式，不能据此宣称某个数值的语义。',
            '参数短哈希未恢复名称；同一短哈希可多次出现，不允许按顺序硬配名称。',
            'RSX C++ exporter 只生成数据结构，渲染函数为 Not implemented；没有解编译渲染程序。',
        ]
        parsed[name] = d
        write_json(out / 'rui' / (name + '.json'), d)
    write_json(out / 'rui/summary.json', {'assets': parsed, 'render_program_decoded': False})
    for a in assets:
        if a['type'] == 'ui' and Path(a['name']).name in parsed:
            a['layout'] = 'rui/' + Path(a['name']).name + '.json'
    return parsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, help='Apex Legends install folder (default: APEX_LEGENDS_DIR)')
    parser.add_argument('--legend', choices=LEGENDS, default='fuse')
    parser.add_argument('--out', type=Path, help='Defaults to hud/ for Fuse, hud/octane/ for Octane')
    parser.add_argument('--analyze-only', action='store_true', help='Rebuild pack/preview from current exported raw artifacts')
    args = parser.parse_args()
    if not args.analyze_only:
        args.game = args.game or gamedirs.apex()
    out = output_path(args.legend, args.out)
    RUNS.clear()
    for directory in ['logs', 'lists', 'preview', 'raw']:
        (out / directory).mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    if not args.analyze_only:
        exe = ensure_tool()
        run_rsx(exe, args.game, out, 'ui', 'raw', 'ui,font')
    rows = list(csv.DictReader((out / 'lists/ui.csv').open(encoding='utf8', newline='')))
    if not args.analyze_only:
        export_local_inputs(exe, args.game, out, rows, args.legend)
    info = load_legend(out, args.legend)
    evidence, inputs = collect_sources(out, args.legend)
    assets = resolve_assets(out, rows, evidence, args.legend)
    loc = localization(out, args.legend, info)
    upgrade_loc = localization(out, keys=[u['name_key'] for u in info['upgrades']])
    colors = palette(out)
    color_row = next((r for r in rows if r['guid'].lower().zfill(16) == colors['source_guid']), None)
    if color_row:
        assets.append({'name': None, 'guid': colors['source_guid'], 'type': 'dtbl', 'package': color_row['file_name'],
            'rsx_asset_name': color_row['asset_name'], 'purpose': 'HUD_palette', 'status': 'located_by_inventory',
            'evidence': [{'kind': 'CSV_schema_and_color_rows', 'source': 'palette.json'}]})
    write_json(out / 'localization.json', loc)
    write_json(out / 'palette.json', colors)
    if not args.analyze_only:
        export_images(exe, args.game, out, assets)
        fonts = export_fonts(exe, args.game, out, assets, loc, args.legend)
    else:
        existing = {a['guid']: a for a in read_json(out / 'assets.json')['assets']}
        for a in assets:
            if a['guid'] in existing:
                a.update(existing[a['guid']])
                a.pop('sha256', None)
                a.pop('payload_sha256', None)
        fonts = read_json(out / 'fonts/fonts.json')['fonts']
    parsed = analyze_rui(out, assets)
    write_json(out / 'assets.json', {'hash_algorithm': 'local tools/apexdata/rtech_hash.py StringToGuid',
        'image_hash_pattern': 'ui_image/<rui path>.rpak', 'rui_hash_pattern': '<ui path>.rpak',
        'assets': assets})
    from pack import build_pack
    pack = build_pack(out, assets, parsed, loc, colors, fonts, args.legend, info, upgrade_loc)
    write_json(out / 'hud_pack.json', pack)
    from preview import render_previews
    render_previews(out, pack)
    if args.legend == 'octane' and not args.analyze_only:
        from export_extra import export_extra
        export_extra(args.game, out)
    from verify_hud import verify
    summary = verify(out, args.legend)
    write_json(out / 'verification.json', summary)
    write_json(out / ('analysis_manifest.json' if args.analyze_only else 'run_manifest.json'), {'game': str(args.game), 'tool': str(exe) if not args.analyze_only else 'analyze-only',
        'inputs': inputs, 'runs': RUNS, 'elapsed_seconds': round(time.perf_counter() - start, 3), 'summary': summary})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
