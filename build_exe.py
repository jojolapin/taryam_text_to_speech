"""Build the Windows executable, portable ZIP and optional Inno Setup installer."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from app import APP_VERSION

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist" / "releases" / APP_VERSION
BUILD = ROOT / "build" / "releases" / APP_VERSION
EXE_PATH = DIST / "TextSpeakPro.exe"


def installer_compiler() -> Path:
    candidates = [os.environ.get("ISCC"), shutil.which("ISCC.exe")]
    for variable in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidates.append(str(Path(base) / "Inno Setup 6" / "ISCC.exe"))
            candidates.append(str(Path(base) / "Programs" / "Inno Setup 6" / "ISCC.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise SystemExit("Install Inno Setup 6 from https://jrsoftware.org/isdl.php, "
                     "or set ISCC to the full path of ISCC.exe. Then rerun build.bat.")


def preflight(with_installer: bool) -> Path | None:
    if sys.platform != "win32":
        raise SystemExit("Build Windows packages on Windows.")
    missing = [name for name in ("PyInstaller", "PySide6", "piper", "mutagen", "lameenc", "pypdf", "requests")
               if importlib.util.find_spec(name) is None]
    if missing:
        raise SystemExit("Missing packages: " + ", ".join(missing) + ". Run setup.bat first.")
    compiler = installer_compiler() if with_installer else None
    print(f"[build] Python: {sys.version.split()[0]}", flush=True)
    print(f"[build] Output: {DIST}", flush=True)
    if compiler:
        print(f"[build] Installer compiler: {compiler}", flush=True)
    return compiler


def checksum(path: Path) -> None:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    path.with_name(path.name + ".sha256").write_text(f"{digest}  {path.name}\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", action="store_true", help="Also create the Windows setup EXE")
    parser.add_argument("--check", action="store_true", help="Check prerequisites without building")
    args = parser.parse_args()
    compiler = preflight(args.installer)
    if args.check:
        return 0

    # These folders can contain portable user data. Never delete them wholesale.
    DIST.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    if not (ROOT / "resources" / "icon.ico").exists():
        import build_icon
        build_icon.generate()
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(DIST), "--workpath", str(BUILD),
                    str(ROOT / "textspeak_pro.spec")], cwd=ROOT, check=True)
    if not EXE_PATH.is_file():
        raise SystemExit("PyInstaller did not produce the expected executable.")
    checksum(EXE_PATH)

    portable = DIST / f"TextSpeakPro-{APP_VERSION}-portable.zip"
    temporary = portable.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.write(EXE_PATH, "TextSpeakPro.exe")
        for name in ("LICENSE", "NOTICE"):
            archive.write(ROOT / name, name)
        archive.writestr("portable.flag", "TextSpeak Pro portable mode\n")
        archive.writestr("voices/.keep", "Download voices from the in-app catalog.\n")
        archive.writestr("README.txt", "TextSpeak Pro - portable build\n(C) 2026 JojoLapin Inc.\n\n"
                         "Extract the entire ZIP into a writable folder, then open TextSpeakPro.exe.\n"
                         "Keep portable.flag alongside the EXE. Documents and voices stay in this folder.\n"
                         "If another copy is running, use its tray menu to Quit first.\n")
    temporary.replace(portable)
    checksum(portable)

    if compiler:
        subprocess.run([str(compiler), f"/DMyAppSource={EXE_PATH}", f"/O{DIST}",
                        str(ROOT / "installer" / "TextSpeakPro.iss")], cwd=ROOT, check=True)
        checksum(DIST / f"TextSpeakPro-Setup-{APP_VERSION}.exe")
    print(f"[build] Finished. Packages and SHA-256 checksums: {DIST}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"[build] Failed: {error}", file=sys.stderr)
        sys.exit(1)
