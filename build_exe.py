"""Build a single-file ``TextSpeakPro.exe`` with PyInstaller.

Run this from the IDE (right-click -> Run) or the CLI. Produces:

- ``dist/TextSpeakPro.exe``      (the one-file app)
- ``dist/TextSpeakPro.sha256``   (checksum)
- ``dist/TextSpeakPro-portable.zip`` (exe + empty voices/ + portable.flag)

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import hashlib
import importlib.util
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
SPEC = ROOT / "textspeak_pro.spec"
EXE_NAME = "TextSpeakPro.exe" if sys.platform.startswith("win") else "TextSpeakPro"
EXE_PATH = DIST / EXE_NAME


def _preflight() -> None:
    """Fail fast with a readable message when build-time deps are missing."""
    missing = []
    if importlib.util.find_spec("PyInstaller") is None:
        missing.append("PyInstaller")
    # Runtime deps must also be importable (they get traced by PyInstaller)
    for mod, label in (
        ("PySide6.QtCore", "PySide6"),
        ("piper", "piper-tts"),
        ("mutagen", "mutagen"),
        ("lameenc", "lameenc"),
        ("pypdf", "pypdf"),
        ("requests", "requests"),
    ):
        if importlib.util.find_spec(mod) is None:
            missing.append(label)
    if missing:
        print("[build] Missing required packages: " + ", ".join(sorted(set(missing))))
        print("[build] Install them with:")
        print(f"        {sys.executable} -m pip install -r requirements.txt -r requirements-build.txt")
        raise SystemExit(1)
    # Pillow is optional (only used for generating the icon)
    if importlib.util.find_spec("PIL") is None:
        print("[build] Pillow is not installed; icon generation will be skipped.")


def _ensure_icon() -> None:
    try:
        import build_icon
        build_icon.generate()
    except SystemExit as e:
        print(f"[build] Icon generation skipped: {e}")
    except Exception as e:  # noqa: BLE001
        print(f"[build] Icon generation failed: {e!r}")


def _run_pyinstaller() -> None:
    if not SPEC.exists():
        raise SystemExit(f"Missing spec file: {SPEC}")
    print("[build] Running PyInstaller...")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)]
    r = subprocess.run(cmd, cwd=str(ROOT))
    if r.returncode != 0:
        raise SystemExit(f"PyInstaller failed with code {r.returncode}")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _package_portable_zip() -> Path | None:
    if not EXE_PATH.exists():
        return None
    zip_path = DIST / "TextSpeakPro-portable.zip"
    print(f"[build] Packaging portable zip -> {zip_path.name}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(EXE_PATH, arcname=EXE_NAME)
        zf.writestr("portable.flag", "TextSpeak Pro portable mode\n")
        zf.writestr("voices/.keep", "Download voices from the in-app catalog.\n")
        zf.writestr("README.txt", (
            "TextSpeak Pro - portable build\n"
            "(C) 2026 JojoLapin Inc. All rights reserved.\n\n"
            "Just double-click TextSpeakPro.exe.\n"
            "All settings and downloaded voices stay in this folder.\n"
        ))
    return zip_path


def main() -> int:
    print(f"[build] Python: {sys.version.split()[0]} at {sys.executable}")
    print(f"[build] Working in: {ROOT}")
    _preflight()

    # Clean previous artifacts
    if BUILD.exists(): shutil.rmtree(BUILD, ignore_errors=True)
    if DIST.exists():  shutil.rmtree(DIST,  ignore_errors=True)

    _ensure_icon()
    _run_pyinstaller()

    if not EXE_PATH.exists():
        print(f"[build] ERROR: expected {EXE_PATH} was not produced.")
        return 1

    digest = _sha256(EXE_PATH)
    checksum_path = DIST / "TextSpeakPro.sha256"
    checksum_path.write_text(f"{digest}  {EXE_NAME}\n", encoding="utf-8")
    size_mb = EXE_PATH.stat().st_size / (1024 * 1024)

    zip_path = _package_portable_zip()

    print("\n[build] Done.")
    print(f"        EXE:       {EXE_PATH} ({size_mb:.1f} MB)")
    print(f"        SHA-256:   {digest}")
    if zip_path and zip_path.exists():
        print(f"        Portable:  {zip_path} ({zip_path.stat().st_size / (1024 * 1024):.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
