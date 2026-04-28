"""Generate ``resources/icon.ico`` (multi-resolution) from ``resources/icon.png``.

Run directly or call ``generate()`` from ``build_exe.py``.
Requires Pillow. (C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESOURCES = ROOT / "resources"
SRC_PNG = RESOURCES / "icon.png"
OUT_ICO = RESOURCES / "icon.ico"


def generate() -> Path:
    try:
        from PIL import Image
    except ImportError as e:
        raise SystemExit(
            "Pillow is required to build the icon. Install with:\n"
            "    pip install Pillow\n"
            f"Original error: {e}"
        )

    if not SRC_PNG.exists():
        raise SystemExit(f"Source icon missing: {SRC_PNG}")

    RESOURCES.mkdir(parents=True, exist_ok=True)
    img = Image.open(SRC_PNG).convert("RGBA")

    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
             (128, 128), (256, 256)]
    img.save(OUT_ICO, format="ICO", sizes=sizes)
    print(f"Wrote {OUT_ICO} ({OUT_ICO.stat().st_size / 1024:.1f} KB)")
    return OUT_ICO


if __name__ == "__main__":
    generate()
