"""Validate deliverables against local source content, without launching a game."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from PIL import Image
from legend import LEGENDS, load_legend, output_path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf8')


def verify(root, legend='fuse'):
    root = root.resolve()

    def path(name):
        result = (root / name).resolve()
        assert result.is_relative_to(root), f'Path escapes pack: {name}'
        assert result.is_file() and result.stat().st_size > 0, name
        return result

    def read(name):
        return json.loads(path(name).read_text(encoding='utf8'))

    def png(name):
        result = path(name)
        with Image.open(result) as im:
            assert im.format == 'PNG', name
            im.verify()  # Includes PNG chunk/CRC checks.
        return result

    pack = read('hud_pack.json')
    assets = read('assets.json')['assets']
    fonts = read('fonts/fonts.json')['fonts']
    info = load_legend(root, legend)
    assert pack['schema_version'] == 1
    required = {'crosshair', 'weapon_slot', 'health', 'shield', 'hit_marker', 'damage_numbers', 'boss_health'}
    present = {e['id'] for e in pack['elements'] if e['mvp']}
    assert required <= present, required - present
    image_count = 0
    for a in assets:
        if not a.get('image'):
            continue
        target = png(a['image'])
        payload = png(a['payload_image'])
        metadata = path(a['metadata'])
        assert read(a['metadata']) == a['original_metadata'], a['name']
        source = metadata.with_name(metadata.name.removesuffix('.meta.json') + '.png')
        assert source.is_file(), source
        assert source.stat().st_size == payload.stat().st_size, a['name']
        assert source.read_bytes() == payload.read_bytes(), f'Payload differs from raw source: {a["name"]}'
        assert a['size'] == a['original_metadata']['original_size']
        x, y, w, h = a['content_rect']
        assert x >= 0 and y >= 0 and w > 0 and h > 0
        assert x + w <= a['size'][0] and y + h <= a['size'][1]
        with Image.open(target) as canvas, Image.open(payload) as pixels:
            canvas.load()
            pixels.load()
            assert list(canvas.size) == a['size']
            assert canvas.mode == a['png_mode'] == 'RGBA', a['name']
            assert list(canvas.getchannel('A').getextrema()) == a['alpha_range']
            assert list(pixels.size) == a['payload_size'] == [w, h]
            restored = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
            restored.paste(pixels.convert('RGBA'), (x, y))
            assert canvas.tobytes() == restored.tobytes(), f'Logical canvas differs from payload: {a["name"]}'
        image_count += 1
    for e in pack['elements']:
        assert e['layout']['status'].startswith('推断'), e['id']
        assert e['rendering'], e['id']
        for r in e['rendering']:
            assert 'image' in r or ('几何图形' in r['status'] and r['basis']), e['id']
        for source in e['rui_sources']:
            path(source)
    by_name = {a['name']: a for a in assets if a.get('name')}

    def check_icon(icon, asset):
        assert icon is not None and icon['asset'] == asset, asset
        actual = by_name[asset]
        assert actual['package'] == 'ui.rpak', asset
        for field, source in [('guid', 'guid'), ('image', 'image'), ('original_size', 'size'),
                              ('payload_image', 'payload_image'), ('payload_size', 'payload_size'),
                              ('content_rect', 'content_rect')]:
            assert icon[field] == actual[source], (asset, field)

    health = next(e for e in pack['elements'] if e['id'] == 'health')
    assert pack['images'].keys() == {a['name'] for a in assets if a.get('payload_image')}
    for name, icon in pack['images'].items():
        check_icon(icon, name)
    check_icon(next(r for r in health['rendering'] if 'image' in r), info['portrait'])
    abilities = {a['id']: a for a in pack['optional_elements']}
    assert set(abilities) == {'tactical', 'ultimate', 'passive'}
    for id, ability in info['abilities'].items():
        check_icon(abilities[id]['image'], ability['asset'])
    expected = {u['id']: u for u in info['upgrades']}
    # The additive field is optional in the original schema-1 Fuse baseline.
    legacy_fuse = legend == 'fuse' and 'legend_upgrades' not in pack
    upgrades = {u['id']: u for u in pack.get('legend_upgrades', [])}
    if not legacy_fuse:
        assert len(upgrades) == len(pack['legend_upgrades']) and upgrades.keys() == expected.keys()
    from export_hud import localization
    loc = read('localization.json')
    assert loc == localization(root, legend, info), 'Localization differs from local locl sources'
    upgrade_loc = localization(root, keys=[u['name_key'] for u in info['upgrades']])
    for id, upgrade in upgrades.items():
        for field, value in expected[id].items():
            assert upgrade[field] == value, (id, field)
        if upgrade['image'] is not None:
            check_icon(upgrade, expected[id]['asset'])
        else:
            assert upgrade['status'].startswith('待定')
        assert upgrade['name_text'] == upgrade_loc.get(upgrade['name_key'], {}).get('values', {}).get(pack['default_language'])
        if upgrade['name_text'] is None:
            assert upgrade['name_status'].startswith('待定')
        if upgrade['level'] is None:
            assert upgrade['level_status'].startswith('待定')
    if legend == 'octane':
        assert health['localization_key'] == info['name_key']
        assert not any('fuse' in k.lower() for k in loc), 'Fuse localization key in Octane pack'
        for id, ability in info['abilities'].items():
            assert abilities[id]['name_key'] == ability['name_key']
            assert abilities[id]['name_text'] == loc[ability['name_key']]['values'].get(pack['default_language'])
        for key in [info['name_key']] + [a['name_key'] for a in info['abilities'].values()]:
            assert len(loc[key]['values']) == 14 and loc[key]['values'][pack['default_language']], key
    assert len(fonts) == 2
    glyph_count = 0
    for f in fonts:
        assert not f['ttf_otf'] and not f['imgui_direct_load']
        assert f['original_format'] == 'DXGI_FORMAT_R8_UNORM'
        with path(f['atlas_dds']).open('rb') as stream:
            assert stream.read(4) == b'DDS '
        png(f['atlas_png'])
        metadata = read(f['metadata'])
        assert f['atlas_size'] == metadata['atlas_size']
        raw_meta = next(p for p in (root / 'raw').rglob('*.meta.json')
                        if 'ui_font_atlas' in str(p) and f['guid'].upper() in p.name.upper()
                        and 'font_dds' not in str(p))
        raw_png = raw_meta.with_name(raw_meta.name.removesuffix('.meta.json') + '.png')
        raw_dds = next(p for p in (root / 'raw/font_dds').rglob('*.dds') if f['guid'].upper() in p.name.upper())
        for original, copied in [(raw_meta, path(f['metadata'])), (raw_png, path(f['atlas_png'])),
                                 (raw_dds, path(f['atlas_dds']))]:
            assert original.stat().st_size == copied.stat().st_size
            assert original.read_bytes() == copied.read_bytes(), copied
        with Image.open(path(f['atlas_png'])) as atlas:
            atlas.load()
            assert list(atlas.size) == f['atlas_size']
            for profile in f['profiles']:
                for g in profile['glyphs'].values():
                    png(g['image'])
                    x, y, w, h = g['source_rect']
                    with Image.open(path(g['image'])) as im:
                        im.load()
                        assert list(im.size) == g['size'] == [w, h]
                        assert im.mode == 'RGBA'
                        assert all(v == (255, 255) for v in im.getextrema()[:3])
                        assert im.getchannel('A').tobytes() == atlas.crop((x, y, x+w, y+h)).getchannel('R').tobytes()
                    glyph_count += 1
    for name in ['hud_hip', 'hud_ads', 'hud_reload', 'hud_sprint', 'hud_transparent', 'states']:
        png(f'preview/{name}.png')
        with Image.open(path(f'preview/{name}.png')) as im:
            im.load()
            assert im.size == (1920, 1080)
            if name == 'hud_transparent':
                assert im.getchannel('A').getextrema()[0] == 0
    for name in ('assets', 'fonts'):
        png(f'preview/{name}.png')
    if (root / 'extra_images.json').is_file():
        raw_extra = {json.loads(p.read_text(encoding='utf8'))['guid']: p
                     for p in (root / 'raw/images_extra').rglob('*.meta.json')}
        for name, entry in read('extra_images.json').items():
            target = png(entry['payload_image'])
            metadata = raw_extra[entry['guid']]
            source = metadata.with_name(metadata.name.removesuffix('.meta.json') + '.png')
            assert source.read_bytes() == target.read_bytes(), name
            with Image.open(target) as im:
                im.load()
                assert list(im.size) == entry['size'] and 'A' in im.getbands()
            assert entry['package'] == 'ui.rpak' and entry['evidence'], name
    if (root / 'extra_localization.json').is_file():
        extra_loc = read('extra_localization.json')
        local_extra = localization(root, keys=list(extra_loc))
        for key, entry in extra_loc.items():
            assert entry['key_guid'] == local_extra[key]['key_guid']
            assert entry['values'] == local_extra[key]['values'] and entry['evidence']
    colors = read('palette.json')['colors']
    assert colors['HUD_DAMAGE_HEADSHOT']['variants']['default'] == [255, 188, 0]
    assert colors['HUD_DAMAGE_TEXT_BLEED']['variants']['default'] == [210, 60, 64]
    assert len(loc['#WPN_RSPN101']['values']) == 14
    font_chars = {cp for f in fonts for p in f['profiles'] for cp in p['glyphs']}
    for cp in map(ord, '0123456789R-301PLAYER'):
        assert str(cp) in font_chars, cp
    summary = {'result': 'PASS', 'mvp_elements': len(required), 'located_ui_images': image_count,
        'font_assets': len(fonts), 'font_profiles': sum(len(f['profiles']) for f in fonts),
        'derived_glyph_pngs': glyph_count, 'rui_metadata': len(list((root / 'raw/ui').glob('*.meta.json'))),
        'rui_layouts_analyzed': len(list((root / 'rui').glob('*.json'))) - 1,
        'localization_languages': 14, 'preview_states': 4,
        'unresolved_assets': sum(a['status'].startswith('待定') for a in assets),
        'source_image_resampling': False, 'game_launched': False,
        'logical_canvas_size_preserved': True, 'payload_rgba_preserved': True,
        'notes': ['几何/布局/动画为已标注的推断；PASS验证包完整性，不代表原生RUI逐像素一致。']}
    if legend == 'octane':
        summary.update({'legend': legend, 'ability_icons': len(abilities), 'legend_upgrades': len(upgrades),
                        'upgrade_levels_pending': sum(u['level'] is None for u in upgrades.values()),
                        'upgrade_names_pending': sum(u['name_text'] is None for u in upgrades.values()),
                        'content_comparison': 'PNG/alpha/尺寸校验；payload/atlas/字形与原始导出内容直接比较'})
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legend', choices=LEGENDS, default='fuse')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(output_path(args.legend, args.out), args.legend), ensure_ascii=False, indent=2))
