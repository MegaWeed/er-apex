"""Builds Fuse's naming and parameter reference from the local Apex install's own data (RSX
exports under <repo>\\apex-data\\export). Nothing here comes from wikis or patch notes.

Outputs:
  <repo>\\apex-data\\fuse_data.json  everything, all 14 languages
  <repo>\\apex-data\\fuse_names.md   readable summary (zh-CN / zh-TW / en / ja / ko)
"""
import csv
import json
import re
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gamedirs  # noqa: E402  (tools/gamedirs.py: the games' install folders)

from apexdata import EXPORT, LANGS, loc, settings, settings_doc, weapon
from rtech_hash import string_to_guid

OUT = Path(__file__).resolve().parents[2] / "apex-data"
SHOW = ["schinese", "tchinese", "english", "japanese", "korean"]
CHARACTER = "settings/itemflav/character/fuse.rpak"
GUNS = ["mp_weapon_rspn101", "mp_weapon_energy_shotgun", "mp_weapon_wingman", "mp_weapon_sniper"]
GRENADES = ["mp_weapon_frag_grenade", "mp_weapon_thermite_grenade", "mp_weapon_grenade_emp"]
WEAPON_KEYS = [
    "damage_near_value", "damage_far_value", "damage_very_far_value", "damage_near_distance",
    "damage_far_distance", "damage_very_far_distance", "damage_headshot_scale", "damage_leg_scale",
    "damage_shield_scale", "fire_rate", "ammo_clip_size", "ammo_per_shot", "ammo_pool_type",
    "projectiles_per_shot", "blast_pattern", "projectile_launch_speed", "projectile_gravity_scale",
    "projectile_drag_coefficient", "reload_time", "reload_time_late1", "deploy_time", "holster_time",
    "raise_time", "zoom_fov", "ads_move_speed_scale", "viewkick_pattern", "explosion_damage",
    "explosion_damage_heavy_armor", "explosion_inner_radius", "explosionradius", "impulse_force",
    "regen_ammo_refill_rate", "regen_ammo_refill_start_delay", "ammo_default_total",
    "charge_time", "fire_mode", "weapon_type_flags",
]
NAME_KEYS = ["printname", "shortprintname", "description", "longdesc"]
LOC_KEYS = ["localizationKey_NAME", "localizationKey_NAME_SHORT", "localizationKey_DESCRIPTION_SHORT",
            "localizationKey_DESCRIPTION_LONG"]
MOVE_KEYS = [
    "stepHeight", "jumpHeight", "airSpeed", "airAcceleration", "airFriction", "gravityScale",
    "mantleHeight", "climbHeight", "climbSpeedStart", "climbSpeedEnd", "slide", "slideRequiredStartSpeed",
    "slideSpeedBoost", "slideSpeedBoostCap", "player_slideBoostCooldown", "slideDecel",
    "slideVelocityDecay", "slideJumpHeight", "slideStopSpeed", "slideMaxJumpSpeed", "sprintStartDelay",
    "health", "fov", "automantle", "climbEnabled", "sprint", "crouch",
]


def localized(fields: dict, keys: list[str]) -> dict:
    return {k: {"token": fields.get(k) or None, "text": loc(fields.get(k))} for k in keys if fields.get(k)}


LOOT_TABLE = "datatable/survival_loot.rpak"
LOOT_ITEMS = re.compile(r"^(health_pickup_(health|combo)_|health_pickup_ultimate$|armor_pickup_lv)")


def loot_items() -> list[dict]:
    """Healing and armour items from the survival loot table (exported under its GUID)."""
    path = EXPORT / "datatable" / f"0x{string_to_guid(LOOT_TABLE):X}.csv"
    rows = csv.DictReader(path.open(encoding="utf-8", errors="replace"))
    return [{"ref": r["ref"], "type": r["type"], "tier": r["tier"], "pickupModel": r["pickupModel"],
             "token": r["pickupString"], "names": loc(r["pickupString"]),
             "descToken": r["desc"], "desc": loc(r["desc"])}
            for r in rows if LOOT_ITEMS.match(r["ref"])]


def weapon_entry(classname: str) -> dict:
    kv = weapon(classname)
    return {
        "classname": classname,
        "names": localized(kv, NAME_KEYS),
        "params": {k: kv[k] for k in WEAPON_KEYS if k in kv},
        "all_params": {k: v for k, v in kv.items() if k != "__blocks"},
        "blocks": sorted(kv["__blocks"]),
    }


def main():
    ch = settings(CHARACTER)
    data = {
        "source": {
            "apex_build": ((gamedirs.apex() / "build.txt")
                           .read_text().strip()),
            "extractor": "RSX 2.3.0 (CLI) + tools/apexdata",
            "languages": LANGS,
        },
        "character": {"asset": CHARACTER, "setFile": ch["setFile"], "names": localized(ch, LOC_KEYS)},
        "abilities": [],
        "weapons": [weapon_entry(w) for w in GUNS],
        "grenades": [weapon_entry(w) for w in GRENADES],
        "ultimate_legacy": weapon_entry("mp_weapon_mortar_ring"),
        "items": {"table": LOOT_TABLE, "rows": loot_items()},
        "skins": [],
    }
    for slot in ["passives", "tacticalAbilities", "ultimateAbilities", "extraPassives"]:
        for i, e in enumerate(ch[slot]):
            a = settings(e["flavor"])
            entry = {"slot": slot, "index": i, "featureFlag": e.get("featureFlag", ""), "asset": e["flavor"],
                     "names": localized(a, LOC_KEYS), "icon": a.get("icon"),
                     "passiveScriptRef": a.get("passiveScriptRef"), "passiveWeaponMod": a.get("passiveWeaponMod"),
                     "weaponAsset": a.get("weaponAsset")}
            if a.get("weaponAsset"):
                entry["weapon"] = weapon_entry(Path(a["weaponAsset"]).stem)
            data["abilities"].append(entry)
    for e in ch["skins"]:
        flavor = e["flavor"]
        if "/fuse/" not in flavor:
            continue
        s = settings(flavor)
        data["skins"].append({
            "asset": flavor, "featureFlag": e.get("featureFlag", ""),
            "token": s.get("localizationKey_NAME") or None,
            "names": loc(s.get("localizationKey_NAME")) if s.get("localizationKey_NAME") else {},
            "skinName": s.get("skinName"), "quality": s.get("quality"), "qualitySubTier": s.get("qualitySubTier"),
            "bodyModel": s.get("bodyModel"), "armsModel": s.get("armsModel"),
            "bodyModel_odlBlob": s.get("bodyModel_odlBlob"), "armsModel_odlBlob": s.get("armsModel_odlBlob"),
            "camoIndex": s.get("camoIndex"), "recolorParent": s.get("recolorParent"),
            "cosmeticSet": s.get("cosmeticSet"), "exclusive": s.get("exclusive"),
        })
    player = settings_doc(ch["setFile"])["settings"]
    data["movement"] = {
        "units": "game units, as stored in the player settings asset",
        "poseSettings": player.get("poseSettings"),
        "fields": {k: player[k] for k in MOVE_KEYS if k in player},
    }
    (OUT / "fuse_data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "fuse_names.md").write_text(markdown(data), encoding="utf-8")
    print(f"abilities {len(data['abilities'])}, weapons {len(data['weapons'])}, skins {len(data['skins'])}")


def row(label: str, texts: dict, token: str | None) -> str:
    cells = [(texts.get(l) or "—").replace("|", "\\|").replace("\n", " ") for l in SHOW]
    return f"| {label} | `{token}` | " + " | ".join(cells) + " |"


def markdown(d: dict) -> str:
    head = "| 项目 | 本地化键 | 简中 | 繁中 | 英文 | 日文 | 韩文 |\n|---|---|---|---|---|---|---|"
    out = [
        "# 暴雷（Fuse）命名与参数对照（游戏文件原始数据）",
        "",
        f"> 来源：本机 Apex `{d['source']['apex_build']}`，用 {d['source']['extractor']} 导出；",
        "> 全部 14 种语言和完整参数见 `fuse_data.json`。",
        "",
        "## 角色",
        "",
        head,
    ]
    for k, v in d["character"]["names"].items():
        if k != "localizationKey_DESCRIPTION_LONG":
            out.append(row(k.replace("localizationKey_", ""), v["text"], v["token"]))
    out += ["", "## 技能与传奇升级", "", "| 槽位 | 开关标志 | 资产 | 名称键 | 简中 | 繁中 | 英文 | 日文 | 韩文 |",
            "|---|---|---|---|---|---|---|---|---|"]
    for a in d["abilities"]:
        n = a["names"].get("localizationKey_NAME", {"text": {}, "token": None})
        cells = [(n["text"].get(l) or "—") for l in SHOW]
        out.append(f"| {a['slot']}[{a['index']}] | `{a['featureFlag'] or '-'}` | `{Path(a['asset']).stem}` | "
                   f"`{n['token']}` | " + " | ".join(cells) + " |")
    out += ["", "### 技能描述（简中）", ""]
    for a in d["abilities"]:
        n = a["names"].get("localizationKey_NAME", {"text": {}})["text"].get("schinese")
        desc = a["names"].get("localizationKey_DESCRIPTION_LONG") or a["names"].get("localizationKey_DESCRIPTION_SHORT")
        if desc:
            out.append(f"- **{n}**（`{Path(a['asset']).stem}`）：{(desc['text'].get('schinese') or '—').replace(chr(10), ' ')}")
    out += ["", "### 技能对应的武器参数", ""]
    for a in d["abilities"]:
        if "weapon" in a:
            w = a["weapon"]
            out.append(f"- `{w['classname']}`：" + "，".join(f"`{k}`={v}" for k, v in w["params"].items()))
    for title, key in [("枪械", "weapons"), ("手雷", "grenades")]:
        out += ["", f"## {title}", "", head]
        for w in d[key]:
            n = w["names"].get("printname")
            if n:
                out.append(row(w["classname"], n["text"], n["token"]))
        out += [""]
        for w in d[key]:
            out.append(f"- `{w['classname']}`：" + "，".join(f"`{k}`={v}" for k, v in w["params"].items()))
    legacy = d["ultimate_legacy"]
    out += ["", "## 旧版终极技能（游戏文件中仍保留）", "", head]
    for k in ["printname", "description"]:
        if k in legacy["names"]:
            out.append(row(f"{legacy['classname']}.{k}", legacy["names"][k]["text"], legacy["names"][k]["token"]))
    out += ["", f"- `{legacy['classname']}`：" + "，".join(f"`{k}`={v}" for k, v in legacy["params"].items())]
    out += ["", f"## 治疗与护盾道具（`{d['items']['table']}`）", "",
            "| ref | tier | 本地化键 | 简中 | 繁中 | 英文 | 日文 | 韩文 |", "|---|---|---|---|---|---|---|---|"]
    for it in d["items"]["rows"]:
        cells = [(it["names"].get(l) or "—") for l in SHOW]
        out.append(f"| `{it['ref']}` | {it['tier']} | `{it['token']}` | " + " | ".join(cells) + " |")
    out += ["", "## 移动参数（玩家设置 `" + d["character"]["setFile"] + "`）", ""]
    for i, p in enumerate(d["movement"]["poseSettings"] or []):
        keys = ["hull_min", "hull_max", "viewheight", "speed", "sprintspeed", "lowSpeed", "acceleration", "deceleration", "sprintAcceleration"]
        out.append(f"- `poseSettings[{i}]`：" + "，".join(f"`{k}`={p.get(k)}" for k in keys))
    out.append("- 其他：" + "，".join(f"`{k}`={v}" for k, v in d["movement"]["fields"].items()))
    out += ["", f"## 皮肤（{len(d['skins'])} 个）", "",
            "| 资产 | 品质 | 名称键 | 简中 | 繁中 | 英文 | 日文 | 韩文 | 身体模型 |", "|---|---|---|---|---|---|---|---|---|"]
    for s in d["skins"]:
        cells = [(s["names"].get(l) or "—").replace("|", "\\|") for l in SHOW] if s["names"] else ["—"] * len(SHOW)
        out.append(f"| `{Path(s['asset']).stem}` | {s['quality']} | `{s['token']}` | " + " | ".join(cells)
                   + f" | `{s['bodyModel']}` |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    main()
