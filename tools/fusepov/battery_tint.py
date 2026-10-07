"""Claude rework of T022 (2026-10-06): the shield battery's energy and window in blue.

Apex draws the battery's energy core (`v_loot_wep_iso_shield_battery_energy`, a grey caustic `_col`
lit by its `_ilm` and the shader's tint) glowing behind a transparent window
(`v_loot_wep_iso_shield_battery_glass`). The 998 materials are T011's opaque Metal approximation:
no emissive, no transparency, so the core showed as dark grey caustics behind an opaque grey pane,
which the game's red sky lit red (user 2026-10-05 23:00: "the shield battery should be blue, it
turned red"). Here both albedos are tinted blue before the build: the core's caustic as a blue
gradient (its brightest strands light blue), the window's pane blue keeping its dirt. The colours
are this mod's (推断): the shader's tint is not in the local data (the material's uber buffer is
empty).
"""
from pathlib import Path

import numpy as np
from PIL import Image

TINTED = ('v_loot_wep_iso_shield_battery_energy_a', 'v_loot_wep_iso_shield_battery_glass_a')

# energy: caustic intensity 0 -> DARK, 1 -> BRIGHT; window: its luminance times PANE, lifted
DARK = np.array([18.0, 70.0, 165.0])
BRIGHT = np.array([150.0, 225.0, 255.0])
PANE = np.array([0.42, 0.72, 1.0])
LIFT = np.array([10.0, 40.0, 95.0])


def _tint_energy(rgb):
    lum = rgb.mean(axis=2, keepdims=True) / 255.0
    # the caustic is dark on average (48/255): stretch it so its strands reach the bright end
    k = np.clip((lum - 0.05) / 0.55, 0.0, 1.0)
    return DARK * (1.0 - k) + BRIGHT * k


def _tint_glass(rgb):
    lum = rgb.mean(axis=2, keepdims=True)
    return np.clip(lum * PANE + LIFT, 0.0, 255.0)


def tint(folder):
    """Rewrites the two albedos in `folder` (a fusemesh part's textures). Returns what changed."""
    folder = Path(folder)
    done = {}
    for name, fn in ((TINTED[0], _tint_energy), (TINTED[1], _tint_glass)):
        path = folder / f'{name}.png'
        if not path.is_file():
            raise FileNotFoundError(path)
        im = Image.open(path).convert('RGBA')
        a = np.asarray(im).astype(float)
        out = a.copy()
        out[..., :3] = fn(a[..., :3])
        Image.fromarray(np.rint(out).astype(np.uint8), 'RGBA').save(path)
        done[name] = dict(path=str(path), mean_rgb=[round(float(x), 1) for x in out[..., :3].reshape(-1, 3).mean(axis=0)])
    return done
