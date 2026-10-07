"""Reads data exported by RSX from the local Apex Legends install: localization (.locl, hashed
keys), settings (.json) and weapon definitions (KeyValues .txt). Names come only from these files."""
import json
import re
from functools import lru_cache
from pathlib import Path

from rtech_hash import string_to_guid

EXPORT = Path(__file__).resolve().parents[2] / "apex-data/export"
LANGS = ["schinese", "tchinese", "english", "japanese", "korean", "russian", "french", "german",
         "italian", "spanish", "mspanish", "portuguese", "polish", "arabic"]

_ENTRY = re.compile(r'^\t"([0-9a-f]+)" "(.*)"$')
_ESCAPE = re.compile(r"\\(.)")
_UNESCAPE = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def _unescape(s: str) -> str:
    return _ESCAPE.sub(lambda m: _UNESCAPE.get(m.group(1), m.group(0)), s)


@lru_cache(None)
def locl(lang: str) -> dict[int, str]:
    out = {}
    path = EXPORT / "localization" / f"localization_{lang}.locl"
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _ENTRY.match(line)
        if m:
            out[int(m.group(1), 16)] = _unescape(m.group(2))
    return out


def loc(token: str | None, langs=LANGS) -> dict[str, str | None]:
    """Localized strings of a token ('#character_fuse_NAME' or 'character_fuse_NAME')."""
    if not token:
        return {lang: None for lang in langs}
    h = string_to_guid(token.lstrip("#"))
    return {lang: locl(lang).get(h) for lang in langs}


def _strip_comments(text: str) -> str:
    """RSX writes settings as JSON with // comments and trailing commas (outside strings); drop
    them."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif c == "/" and text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif c == ",":
            j = i + 1
            while j < n and (text[j].isspace() or text.startswith("//", j)):
                if text.startswith("//", j):
                    while j < n and text[j] != "\n":
                        j += 1
                else:
                    j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue
            out.append(c)
        else:
            out.append(c)
        i += 1
    return "".join(out)


def settings_doc(asset_path: str) -> dict:
    """The whole exported settings document (layoutAsset, uniqueId, settings, $modNames...)."""
    p = EXPORT / Path(asset_path).with_suffix(".json")
    return json.loads(_strip_comments(p.read_text(encoding="utf-8")))


def settings(asset_path: str) -> dict:
    """A settings asset's fields by its game path ('settings/itemflav/character/fuse.rpak')."""
    return settings_doc(asset_path)["settings"]


_KV = re.compile(r'^"([^"]+)"\s+"(.*)"$')
_KEY = re.compile(r'^"([^"]+)"$')


def weapon(classname_or_asset: str) -> dict:
    """Top-level key/values of a weapon definition; nested blocks (mods...) kept as raw text in
    '__blocks'."""
    name = Path(classname_or_asset).stem
    text = (EXPORT / "weapon" / f"{name}.txt").read_text(encoding="utf-8", errors="replace")
    kv, blocks, depth, block_name, block_lines = {}, {}, 0, None, []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line == "{":
            depth += 1
            continue
        if line == "}":
            depth -= 1
            if depth == 1 and block_name:
                blocks[block_name] = "\n".join(block_lines)
                block_name, block_lines = None, []
            continue
        if depth == 1:
            m = _KV.match(line)
            if m:
                kv[m.group(1)] = m.group(2)
            else:
                m = _KEY.match(line)
                if m:
                    block_name = m.group(1)
        elif depth >= 2 and block_name:
            block_lines.append(raw)
    kv["__blocks"] = blocks
    return kv
