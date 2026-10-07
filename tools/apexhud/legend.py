"""Legend settings and output paths shared by the HUD command-line tools."""
import json
from pathlib import Path

HUD_ROOT = Path(__file__).resolve().parents[2] / 'apex-data/hud'
LEGENDS = ('fuse', 'octane')


def output_path(legend='fuse', out=None):
    if legend not in LEGENDS:
        raise ValueError(f'Unsupported legend: {legend}')
    allowed = (HUD_ROOT / 'octane' if legend == 'octane' else HUD_ROOT).resolve()
    result = Path(out).resolve() if out is not None else allowed
    if not result.is_relative_to(allowed):
        raise ValueError(f'{legend} output must stay inside {allowed}')
    return result


def _settings(out, asset):
    path = (out / 'inputs' / (asset.removesuffix('.rpak') + '.json')).resolve()
    if not path.is_relative_to((out / 'inputs').resolve()):
        raise ValueError(f'Setting path escapes inputs: {asset}')
    source = path.relative_to(out.resolve()).as_posix()
    if not path.is_file():
        return {}, source
    return json.loads(path.read_text(encoding='utf8'))['settings'], source


def load_legend(out, legend='fuse'):
    """Follow the character's references, including the local spelling octance_."""
    character, source = _settings(out, f'settings/itemflav/character/{legend}.rpak')
    if not character:
        raise FileNotFoundError(out / source)
    abilities = {}
    ability_prefix = 'octance_' if legend == 'octane' else 'fuse_'
    for id, field in [('tactical', 'tacticalAbilities'), ('ultimate', 'ultimateAbilities'),
                      ('passive', 'passives')]:
        references = [r for r in character.get(field, [])
                      if Path(r['flavor']).name.startswith(ability_prefix)]
        if len(references) != 1:
            raise ValueError(f'{source}:{field}: expected one base ability, found {len(references)}')
        setting, setting_source = _settings(out, references[0]['flavor'])
        abilities[id] = {'asset': setting.get('icon'),
                         'name_key': setting.get('localizationKey_NAME'),
                         'source': setting_source,
                         'weapon_asset': setting.get('weaponAsset'),
                         'status': 'data' if setting else '待定：本机能力设置缺失'}
    upgrades = []
    seen = set()
    for field in ('passives', 'extraPassives'):
        for reference in character.get(field, []):
            asset = reference['flavor']
            # Generic class passives also occur here; the pack's legend upgrades
            # are the legend-specific flavors, as in the original Fuse export.
            if not Path(asset).name.startswith(f'upgrade_{legend}_') or asset in seen:
                continue
            seen.add(asset)
            setting, setting_source = _settings(out, asset)
            # The ability number in PAS_*_UPGRADE_* is an identifier, not a tier.
            # Only accept an explicit level from the setting; never infer it from order.
            level = setting.get('legendUpgradeLevel', setting.get('upgradeLevel'))
            if level is not None and (not isinstance(level, int) or isinstance(level, bool)):
                raise ValueError(f'{setting_source}: invalid explicit upgrade level {level!r}')
            upgrades.append({'id': Path(asset).stem, 'asset': setting.get('icon'),
                             'level': level,
                             'level_status': 'data' if level is not None else
                                 '待定：本机角色/能力设置未提供强化等级；不由排列或 passiveScriptRef 推断',
                             'name_key': setting.get('localizationKey_NAME'),
                             'source': setting_source, 'character_source': source,
                             'character_list': field,
                             'passive_script_ref': setting.get('passiveScriptRef'),
                             'feature_flag': reference.get('featureFlag', '')})
    return {'id': legend, 'source': source, 'portrait': character.get('galleryPortrait'),
            'name_key': character.get('localizationKey_NAME'),
            'short_name_key': character.get('localizationKey_NAME_SHORT'),
            'abilities': abilities, 'upgrades': upgrades}
