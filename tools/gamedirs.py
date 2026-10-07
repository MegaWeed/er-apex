"""The install folders of the games the converters read (read only), from the environment.

  APEX_LEGENDS_DIR   Apex Legends install folder, the one with paks\\Win64 (required; this
                     repository ships nothing from the game)
  ELDEN_RING_DIR     ELDEN RING's Game folder, the one with eldenring.exe and regulation.bin

ELDEN_RING_DIR falls back to the folder this project was made with. What the converters take from
Season 3 (R5Reloaded) is recorded in tools/s3_evidence.json (tools/s3record.py).
"""
import os
from pathlib import Path

ELDEN_RING_DEFAULT = r'E:\SteamLibrary\steamapps\common\ELDEN RING\Game'


def _folder(variable, default, what, check):
    value = os.environ.get(variable) or default
    if not value:
        raise SystemExit(f'{variable} is not set. Set it to your {what}, for example:\n'
                         f'  $env:{variable} = "D:\\SteamLibrary\\steamapps\\common\\Apex Legends"')
    path = Path(value)
    if not (path / check).exists():
        raise SystemExit(f'{variable} = {path}: no {check} there; set it to your {what}')
    return path


def apex():
    return _folder('APEX_LEGENDS_DIR', None, 'Apex Legends install folder', 'paks/Win64')


def elden_ring():
    return _folder('ELDEN_RING_DIR', ELDEN_RING_DEFAULT, "ELDEN RING's Game folder", 'eldenring.exe')
