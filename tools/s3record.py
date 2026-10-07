"""Season 3 evidence from R5Reloaded, recorded once into tools/s3_evidence.json.

Some converters take names from S3 (the HUD's extra images and texts, the audio events, the frag
grenade's models) and keep, as evidence, where S3's scripts and weapon settings name them: file and
line. The assets themselves always come from the local Apex Legends install. The evidence is kept in
git, so a user needs no R5Reloaded copy: only file names, line numbers and the short values those
lines hold, never the scripts.

To make the record again, run the converters with R5RELOADED_RECORD set to an R5Reloaded LIVE folder
(the one with platform\\scripts); each lookup then reads that folder and the record is written back.

R5_ROOT is where the record was made. Outputs name R5Reloaded files under it, as before; nothing
reads it unless R5RELOADED_RECORD points there.
"""
import atexit
import json
import os
from pathlib import Path

R5_ROOT = Path(r'F:\R5Reloaded\R5R Library\LIVE')
RECORD = Path(__file__).with_name('s3_evidence.json')

_record = None
_live = os.environ.get('R5RELOADED_RECORD')


def _load():
    global _record
    if _record is None:
        _record = json.loads(RECORD.read_text(encoding='utf-8')) if RECORD.is_file() else {}
    return _record


def _save():
    RECORD.write_text(json.dumps(_record, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def under(path):
    """Whether `path` names a file in R5Reloaded (under R5_ROOT)."""
    return Path(path).is_relative_to(R5_ROOT)


def get(tool, key, compute):
    """The recorded value for (tool, key). compute(real) works it out from the R5Reloaded folder
    `real` (a Path); it runs only when R5RELOADED_RECORD is set, and its result is recorded."""
    record = _load()
    if _live:
        value = compute(Path(_live))
        if record.setdefault(tool, {}).get(key) != value:
            record[tool][key] = value
            if not getattr(get, 'registered', False):
                atexit.register(_save)
                get.registered = True
        return value
    try:
        return record[tool][key]
    except KeyError:
        raise SystemExit(f'{RECORD.name} has no S3 evidence for {tool}: {key}. Make the record again with '
                         f'R5RELOADED_RECORD set to an R5Reloaded LIVE folder (see tools/s3record.py).')


def real(live_root, path):
    """`path` (under R5_ROOT) inside the R5Reloaded folder `live_root`."""
    return Path(live_root) / Path(path).relative_to(R5_ROOT)
