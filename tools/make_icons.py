#!/usr/bin/env python3
"""Génère icon-192.png et icon-512.png (stdlib uniquement) dans docs/."""
import struct
import sys
import zlib
from pathlib import Path

BG = (13, 15, 20)
PANEL = (22, 26, 34)
GOLD = (255, 210, 63)
SLATE = (37, 43, 55)
GREY = (139, 147, 165)
GREEN = (61, 220, 151)


def in_round_rect(x, y, x0, y0, x1, y1, r):
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def pixel(x, y):
    # coordonnées sur une grille 512x512
    if in_round_rect(x, y, 120, 76, 392, 436, 28):
        if not in_round_rect(x, y, 134, 90, 378, 422, 18):
            return GOLD
        if (x - 256) ** 2 + (y - 187) ** 2 <= 42 * 42:
            return GOLD
        if in_round_rect(x, y, 152, 112, 360, 262, 14):
            return SLATE
        if in_round_rect(x, y, 152, 292, 360, 308, 8):
            return GREY
        if in_round_rect(x, y, 152, 326, 292, 342, 8):
            return (61, 69, 87)
        if (x - 352) ** 2 + (y - 382) ** 2 <= 26 * 26:
            return GREEN
        return PANEL
    return BG


def png(size, path):
    rows = []
    scale = 512 / size
    for j in range(size):
        row = bytearray([0])
        for i in range(size):
            row += bytes(pixel(i * scale + scale / 2, j * scale + scale / 2))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    out = b"\x89PNG\r\n\x1a\n"
    out += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
    out += chunk(b"IDAT", zlib.compress(raw, 9))
    out += chunk(b"IEND", b"")
    Path(path).write_bytes(out)


if __name__ == "__main__":
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "docs"
    for s in (192, 512):
        png(s, dest / f"icon-{s}.png")
        print("écrit", dest / f"icon-{s}.png")
