#!/usr/bin/env python3
"""Generate Chrome Web Store promo PNGs (stdlib only — no Pillow).

Creates branded solid canvases with the extension icon centered.
Screenshots for CWS still need human capture (see docs/store/).

Usage:
  python scripts/generate_store_assets.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICON_PATH = ROOT / "extension" / "icons" / "icon-128.png"
OUT_DIR = ROOT / "docs" / "store" / "assets"


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_rgba_png(path: Path, width: int, height: int, rgba: bytes) -> None:
    if len(rgba) != width * height * 4:
        raise ValueError("rgba buffer size mismatch")
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)  # filter None
        raw.extend(rgba[y * stride : (y + 1) * stride])
    compressed = zlib.compress(bytes(raw), 9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


def read_png_rgba(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    width = height = None
    idat = bytearray()
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        tag = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk[:10])
            if bit_depth != 8 or color_type != 6:
                raise ValueError(f"unsupported PNG: depth={bit_depth} type={color_type}")
        elif tag == b"IDAT":
            idat.extend(chunk)
        elif tag == b"IEND":
            break
    if width is None or height is None:
        raise ValueError("missing IHDR")
    raw = zlib.decompress(bytes(idat))
    stride = width * 4
    out = bytearray(width * height * 4)
    i = 0
    for y in range(height):
        filt = raw[i]
        i += 1
        row = bytearray(raw[i : i + stride])
        i += stride
        if filt == 1:  # Sub
            for x in range(4, stride):
                row[x] = (row[x] + row[x - 4]) & 0xFF
        elif filt == 2:  # Up
            if y:
                prev = out[(y - 1) * stride : y * stride]
                for x in range(stride):
                    row[x] = (row[x] + prev[x]) & 0xFF
        elif filt == 3:  # Average
            prev = out[(y - 1) * stride : y * stride] if y else bytes(stride)
            for x in range(stride):
                left = row[x - 4] if x >= 4 else 0
                up = prev[x]
                row[x] = (row[x] + ((left + up) // 2)) & 0xFF
        elif filt == 4:  # Paeth
            prev = out[(y - 1) * stride : y * stride] if y else bytes(stride)

            def paeth(a: int, b: int, c: int) -> int:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                if pa <= pb and pa <= pc:
                    return a
                if pb <= pc:
                    return b
                return c

            for x in range(stride):
                a = row[x - 4] if x >= 4 else 0
                b = prev[x]
                c = prev[x - 4] if x >= 4 else 0
                row[x] = (row[x] + paeth(a, b, c)) & 0xFF
        elif filt != 0:
            raise ValueError(f"unsupported filter {filt}")
        out[y * stride : (y + 1) * stride] = row
    return width, height, bytes(out)


def _blend(dst: bytearray, x: int, y: int, dw: int, sw: int, sh: int, src: bytes) -> None:
    for sy in range(sh):
        for sx in range(sw):
            si = (sy * sw + sx) * 4
            di = ((y + sy) * dw + (x + sx)) * 4
            sa = src[si + 3]
            if sa == 0:
                continue
            if sa == 255:
                dst[di : di + 4] = src[si : si + 4]
                continue
            inv = 255 - sa
            for c in range(3):
                dst[di + c] = (src[si + c] * sa + dst[di + c] * inv) // 255
            dst[di + 3] = 255


def make_canvas(width: int, height: int, rgb: tuple[int, int, int], icon: bytes, iw: int, ih: int) -> bytes:
    r, g, b = rgb
    buf = bytearray([r, g, b, 255] * (width * height))
    # subtle top band
    band_h = max(8, height // 14)
    for y in range(band_h):
        for x in range(width):
            i = (y * width + x) * 4
            buf[i] = min(255, r + 18)
            buf[i + 1] = min(255, g + 18)
            buf[i + 2] = min(255, b + 22)
    ox = (width - iw) // 2
    oy = (height - ih) // 2
    _blend(buf, ox, oy, width, iw, ih, icon)
    return bytes(buf)


def make_schematic_screenshot(width: int, height: int, label_rows: list[str]) -> bytes:
    """Wireframe-style placeholder screenshot (replace with real captures before CWS upload)."""
    bg = (245, 247, 250)
    panel = (255, 255, 255)
    accent = (36, 99, 235)
    muted = (148, 163, 184)
    buf = bytearray([*bg, 255] * (width * height))

    def fill_rect(x0: int, y0: int, w: int, h: int, rgb: tuple[int, int, int], a: int = 255) -> None:
        for y in range(y0, min(y0 + h, height)):
            for x in range(x0, min(x0 + w, width)):
                i = (y * width + x) * 4
                if a == 255:
                    buf[i] = rgb[0]
                    buf[i + 1] = rgb[1]
                    buf[i + 2] = rgb[2]
                    buf[i + 3] = 255
                else:
                    inv = 255 - a
                    buf[i] = (rgb[0] * a + buf[i] * inv) // 255
                    buf[i + 1] = (rgb[1] * a + buf[i + 1] * inv) // 255
                    buf[i + 2] = (rgb[2] * a + buf[i + 2] * inv) // 255
                    buf[i + 3] = 255

    # chrome frame
    fill_rect(40, 30, width - 80, height - 60, panel)
    fill_rect(40, 30, width - 80, 48, accent)
    # fake text bars for each label row
    y = 100
    for idx, _ in enumerate(label_rows):
        fill_rect(70, y, min(420, width - 140), 18, muted if idx else (30, 41, 59))
        fill_rect(70, y + 28, min(280, width - 140), 12, (203, 213, 225))
        y += 70
    # watermark strip
    fill_rect(40, height - 90, width - 80, 40, (254, 243, 199))
    return bytes(buf)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    iw, ih, icon = read_png_rgba(ICON_PATH)

    assets = {
        "promo-small-440x280.png": (440, 280, (15, 23, 42)),
        "marquee-1400x560.png": (1400, 560, (15, 23, 42)),
    }
    for name, (w, h, rgb) in assets.items():
        rgba = make_canvas(w, h, rgb, icon, iw, ih)
        write_rgba_png(OUT_DIR / name, w, h, rgba)
        print(f"wrote {OUT_DIR / name}")

    shots = [
        ("screenshot-01-observe-placeholder.png", ["Currently Observing", "Ready to Save", "YouTube"]),
        ("screenshot-02-command-placeholder.png", ["Command bar", "search MCP servers", "Results"]),
        ("screenshot-03-bookmarks-placeholder.png", ["Import bookmarks", "Preview", "Confirm"]),
        ("screenshot-04-workspace-search-placeholder.png", ["Universal search", "Why matched", "Citations"]),
        ("screenshot-05-ask-placeholder.png", ["Ask Memory", "Grounded answer", "Sources"]),
    ]
    for name, labels in shots:
        rgba = make_schematic_screenshot(1280, 800, labels)
        write_rgba_png(OUT_DIR / name, 1280, 800, rgba)
        print(f"wrote {OUT_DIR / name} (PLACEHOLDER)")

    readme = OUT_DIR / "README.md"
    readme.write_text(
        """# Store assets (V1-9)

| File | Status |
|------|--------|
| `promo-small-440x280.png` | Generated — ready for CWS small promo tile |
| `marquee-1400x560.png` | Generated — optional marquee |
| `screenshot-*-placeholder.png` | **Placeholders** — replace with real UI captures before upload |

Capture real screenshots using the shot list in `../CHROME_WEB_STORE_LISTING.md` and `docs/V1_DEMO_SCRIPT.md`.

Regenerate: `python scripts/generate_store_assets.py`
""",
        encoding="utf-8",
    )
    print(f"wrote {readme}")


if __name__ == "__main__":
    main()
