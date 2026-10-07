"""HUD v3 supplement: UI images the T009 pack has no name for, from the local Apex install.

Names come from R5Reloaded's Season 3 client scripts (D-020: the local R5Reloaded copy is a
reference for behaviour and names), as tools/s3_evidence.json recorded where they name them
(tools/s3record.py: no R5Reloaded copy needed); every name is hashed (ui_image/<path>.rpak) and must
be found in the local Apex ui.rpak inventory (apex-data/hud/lists/images.csv) before it is exported,
so the pixels are always the local Apex build's. Writes apex-data/hud/extra/ and extra_images.json
there: {name: {guid, payload_image, size, evidence}}.

Run from the repository root: python tools/apexhud/export_extra.py
No game launch, injection, network access, or git commands.
"""
import argparse
import csv
import json
from pathlib import Path
import re
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gamedirs  # noqa: E402  (tools/gamedirs.py: the games' install folders)
import s3record  # noqa: E402  (tools/s3record.py: S3's evidence without R5Reloaded)

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'apexdata'))
from rtech_hash import string_to_guid  # noqa: E402
from prepare_rsx import ensure_tool  # noqa: E402
from export_hud import run_rsx, read_json, write_json, localization  # noqa: E402
from legend import LEGENDS, output_path  # noqa: E402
from PIL import Image  # noqa: E402

# what the HUD v3 draws with them (src/hud/apex.rs)
WANTED = [
    'rui/rui_screens/skull',                      # kills counter
    'rui/hud/poi_icons/poi_dealt_damage',         # damage dealt counter
    'rui/hud/poi_icons/poi_killed_other',
    'rui/hud/obituary/obituary_headshot',         # kill feed: headshot kill
    'rui/hud/obituary/obituary_downed',
    'rui/hud/gamestate/player_kills_leader_icon',
    # weapon frame (plan-gun-motion-hud.md 2.6, D-023): S3's fire mode icon and the R-301's empty
    # attachment slots (barrel, magazine, sight, stock)
    'rui/hud/weapon_toggle/automatic',
    'rui/pilot_loadout/mods/empty_barrel_stabilizer',
    'rui/pilot_loadout/mods/empty_mag',
    'rui/pilot_loadout/mods/empty_sight',
    'rui/pilot_loadout/mods/empty_stock_tactical',
    # the survival slot (key 4): the shield battery (D-032), mp_ability_consumable `shield_large`
    # `hud_icon`
    'rui/hud/loot/loot_stim_shield_large',
    # U3, the Charge Rifle in weapon slot 2: its icon (S3 weapon settings `hud_icon`), the sniper
    # ammo's badge (S3 `ammo_pool_type` "sniper": the local loot table's `hudIcon`), S3's fire mode
    # icon for a single-shot-only weapon (cl_weapon_status.gnut), the sniper stock's empty slot
    'rui/weapon_icons/r5/weapon_charge_rifle',
    'rui/hud/gametype_icons/survival/sur_ammo_sniper',
    'rui/hud/weapon_toggle/single_shot',
    'rui/pilot_loadout/mods/empty_stock_sniper',
    # the ordnance slot and the grenade indicator (U9): the frag grenade's `hud_icon`
    'rui/ordnance_icons/grenade_frag',
]


def evidence(name: str, out: Path = None):
    """Script lines naming the image ($"name"); S3 weapon settings naming it ("name"), both from S3's
    record; the local loot tables naming it (an ammo type's `hudIcon`), when the pack's inputs are at
    hand."""
    found = list(s3record.get('hud_image', name, lambda r5: s3_evidence(r5, name)))
    quoted = f'"{name}"'
    if out is not None:
        for p in sorted((out / 'inputs/datatable').glob('*.csv')):
            for i, line in enumerate(p.read_text(encoding='utf8', errors='replace').splitlines(), 1):
                if quoted in line:
                    found.append({'kind': 'local_loot_datatable', 'source': f'{p.relative_to(out).as_posix()}:{i}'})
    return found


def s3_evidence(r5: Path, name: str):
    """The R5Reloaded part of `evidence`: S3's script lines and weapon settings naming the image."""
    found = []
    needle = f'$"{name}"'
    for p in sorted((r5 / 'platform/scripts/vscripts').rglob('*')):
        if p.suffix not in ('.nut', '.gnut'):
            continue
        for i, line in enumerate(p.read_text(encoding='utf8', errors='replace').splitlines(), 1):
            if needle in line:
                found.append({'kind': 'R5Reloaded_S3_script', 'source': f'{p.relative_to(r5).as_posix()}:{i}'})
    quoted = f'"{name}"'
    for p in sorted((r5 / 'platform/scripts/weapons').glob('*.txt')):
        for i, line in enumerate(p.read_text(encoding='utf8', errors='replace').splitlines(), 1):
            if quoted in line and not line.lstrip().startswith('//'):
                found.append({'kind': 'R5Reloaded_S3_weapon_settings', 'source': f'{p.relative_to(r5).as_posix()}:{i}'})
    return found


def s3_text_references(r5: Path, needles):
    """S3's script, localization and weapon settings lines holding any of `needles`."""
    references = []
    roots = [r5 / 'platform/scripts/vscripts', r5 / 'platform/resource/localization', r5 / 'platform/scripts/weapons']
    for root in roots:
        settings = root.name == 'weapons'
        for p in sorted(root.rglob('*')):
            if settings:
                if p.suffix != '.txt':
                    continue
            elif p.suffix not in ('.nut', '.gnut') and p.name != 'base_english.txt':
                continue
            # S3's localization files are UTF-16; its scripts and weapon settings UTF-8
            text = p.read_bytes().decode('utf-16' if p.name == 'base_english.txt' else 'utf8', errors='replace')
            for i, line in enumerate(text.splitlines(), 1):
                if any(n in line for n in needles):
                    kind = ('R5Reloaded_S3_weapon_settings' if settings else 'R5Reloaded_S3_script'
                            if p.suffix != '.txt' else 'R5Reloaded_S3_localization')
                    references.append({'kind': kind, 'source': f'{p.relative_to(r5).as_posix()}:{i}'})
    return references


def export_extra(game, out):
    rows = {}
    with (out / 'lists/images.csv').open(encoding='utf8', errors='replace', newline='') as f:
        for r in csv.DictReader(f):
            rows[int(r['guid'], 16)] = r
    found = {}
    for name in WANTED:
        guid = string_to_guid('ui_image/' + name + '.rpak')
        row = rows.get(guid)
        ev = evidence(name, out)
        if not ev:
            raise RuntimeError(f'{name}: not named in the R5Reloaded scripts, weapon settings or local loot tables')
        if not row or row['type'] != 'uiia' or row['file_name'] != 'ui.rpak':
            print(f'{name}: 待定 (GUID {guid:016x} not in the local ui.rpak)')
            continue
        found[name] = {'guid': f'{guid:016x}', 'rsx_asset_name': row['asset_name'], 'evidence': ev}
    exe = ensure_tool()
    raw = out / 'raw/images_extra'
    if raw.exists():
        if not raw.resolve().is_relative_to(out.resolve()):
            raise ValueError(f'Extra output escapes pack: {raw}')
        shutil.rmtree(raw)
    names = ','.join(sorted(a['rsx_asset_name'] for a in found.values()))
    # run_rsx records its runs in run_manifest.json: keep T009's and file this run separately
    manifest = out / 'run_manifest.json'
    kept = manifest.read_bytes() if manifest.exists() else None
    try:
        run_rsx(exe, game, out, 'images_extra', 'raw/images_extra', 'uiia', ['--exportexact', names], packages=['ui.rpak'])
    finally:
        if manifest.exists():
            shutil.move(manifest, out / 'extra_run_manifest.json')
        if kept is not None:
            manifest.write_bytes(kept)
    meta_by_guid = {read_json(p)['guid']: p for p in raw.rglob('*.meta.json')}
    index = {}
    for name, a in found.items():
        meta = meta_by_guid.get(a['guid'])
        source = meta.with_name(meta.name.removesuffix('.meta.json') + '.png') if meta else None
        if source is None or not source.exists():
            raise RuntimeError(f'{name}: RSX gave no PNG')
        target = out / 'extra' / (name + '.png')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)  # the RSX PNG bytes, unchanged (the trimmed payload)
        if source.read_bytes() != target.read_bytes():
            raise RuntimeError(f'{name}: copied PNG differs from RSX source')
        with Image.open(target) as im:
            im.load()
            if im.format != 'PNG' or 'A' not in im.getbands():
                raise RuntimeError(f'{name}: expected PNG with alpha')
            size = list(im.size)
        index[name] = {'guid': a['guid'], 'payload_image': (Path('extra') / (name + '.png')).as_posix(), 'size': size,
            'evidence': a['evidence'], 'package': 'ui.rpak'}
        print(f'{name}: {size[0]}x{size[1]}')
    write_json(out / 'extra_images.json', index)
    # The existing weapon HUD also needs this general reload hint; the knock-down center message
    # (S3 score event "Sur_DownedPilot", cl_hud.gnut AddScoreEventMessage) its splash text, which
    # S3's English localization names (2026-10-05, the user's R5R video). Read the same local
    # locl files and preserve the original extra-localization format.
    keys = {'#HINT_RELOAD_TAP_TO_USE': ['#HINT_RELOAD_TAP_TO_USE'],
            '#SCORE_EVENT_SUR_DOWNED_PILOT_HUD': ['"Sur_DownedPilot"', 'SCORE_EVENT_SUR_DOWNED_PILOT_HUD'],
            # the shield battery (D-032): its name (mp_ability_consumable `shield_large` printname)
            # and the refusals (mp_ability_consumable.nut GetCanUseResultString)
            '#SURVIVAL_PICKUP_HEALTH_COMBO_LARGE': ['#SURVIVAL_PICKUP_HEALTH_COMBO_LARGE', '"SURVIVAL_PICKUP_HEALTH_COMBO_LARGE"'],
            '#DENY_SHIELD_FULL': ['#DENY_SHIELD_FULL', '"DENY_SHIELD_FULL"'],
            '#DENY_NO_SHIELDS': ['#DENY_NO_SHIELDS', '"DENY_NO_SHIELDS"'],
            # U3: the Charge Rifle's `shortprintname` (S3 weapon settings; the weapon slot's tab)
            '#WPN_CHARGE_RIFLE_SHORT': ['#WPN_CHARGE_RIFLE_SHORT']}
    entries = localization(out, keys=list(keys))
    result = {}
    for key, needles in keys.items():
        references = s3record.get('hud_text', key, lambda r5: s3_text_references(r5, needles))
        if not entries[key]['values']:
            raise RuntimeError(f'{key}: not in the local localization')
        result[key] = {'key_guid': entries[key]['key_guid'], 'values': entries[key]['values'], 'evidence': references}
    # By hash where the key's name is 待定: the tactical slot's cooldown "0 sec" in the user's R5R
    # video (2026-10-05) is the English entry "%s1 sec" with this hash.
    for guid, english in {'f90fd1bcaaced48a': '%s1 sec'}.items():
        values, sources = {}, {}
        for source in sorted((out / 'inputs/localization').glob('*.locl')):
            lang = source.stem.removeprefix('localization_')
            for line in source.read_text(encoding='utf8').splitlines():
                m = re.match(r'^\s*"([0-9a-fA-F]+)" "(.*)"$', line)
                if m and m[1].lower().lstrip('0') == guid.lstrip('0'):
                    values[lang] = m[2]
                    sources[lang] = source.relative_to(out).as_posix()
        if values.get('english') != english:
            raise RuntimeError(f'{guid}: expected "{english}" in English, got {values.get("english")!r}')
        result['0x' + guid] = {'key_guid': guid, 'key_name': '待定', 'values': values, 'sources': sources,
                               'evidence': [{'kind': 'user_R5R_video', 'source': '2026-10-05 16:53, tactical slot "0 sec"'}]}
    write_json(out / 'extra_localization.json', result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, help='Apex Legends install folder (default: APEX_LEGENDS_DIR)')
    parser.add_argument('--legend', choices=LEGENDS, default='fuse')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    export_extra(args.game or gamedirs.apex(), output_path(args.legend, args.out))


if __name__ == '__main__':
    main()
