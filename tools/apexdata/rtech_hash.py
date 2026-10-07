"""RTech StringToGuid (the pak asset/localization key hash), ported from the decompiled game
function (r5sdk / RSX utils.cpp). Case-insensitive; backslash is treated as a forward slash."""
M32 = (1 << 32) - 1
M64 = (1 << 64) - 1


def _fold(x: int) -> int:
    t = x ^ 0x5C5C5C5C
    mask = ((~t & M32) >> 7) & (((t - 0x01010101) & M32) >> 7) & 0x01010101
    return ((x - 45 * mask) & M32) & 0xDFDFDFDF


def string_to_guid(s: str | bytes) -> int:
    data = (s.encode("utf-8") if isinstance(s, str) else s) + b"\x00" * 8
    u32 = lambda o: int.from_bytes(data[o:o + 4], "little")
    off, v2, v3 = 0, 0, 0
    a = u32(off)
    v4 = _fold(a)
    i = (~a & M32) & ((a - 0x01010101) & M32) & 0x80808080
    while i == 0:
        v6 = v4
        off += 4
        v7 = u32(off)
        v3 += 4
        t = ((((0xFB8C4D96501 * v6) & M64) >> 24) + ((0x633D5F1 * v2) & M64)) & M64
        v2 = (t >> 61) ^ t
        v8 = (~v7 & M32) & ((v7 - 0x01010101) & M32)
        v4 = _fold(v7)
        i = v8 & 0x80808080
    v10 = ((i & (-i & M32)) - 1) & M32
    v9 = v10.bit_length() - 1 if v10 else -1
    n = (v3 + int(v9 / 8)) & M32
    return (((0x633D5F1 * v2) & M64) + (((0xFB8C4D96501 * (v4 & v10)) & M64) >> 24) - ((0xAE502812AA7333 * n) & M64)) & M64


if __name__ == "__main__":
    for s in ["spray_heart_01", "SPRAY_HEART_01", "#spray_heart_01"]:
        print(f"{s:20s} {string_to_guid(s):016x}")
