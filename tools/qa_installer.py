"""Install/uninstall the real Windows setup in a disposable workspace directory.

Refuses to run when TextSpeak Pro is already registered as installed. The user's
running application and profile are not used. Keeps logs and an unknown-file
sentinel for review rather than recursively deleting the test directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import winreg

ROOT = Path(__file__).resolve().parent.parent
KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{C3F46CCD-5B7E-4F2D-93F1-6E9B7F5DE2CA}_is1"


def registrations():
    found = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, KEY, 0, winreg.KEY_READ | view) as key:
                    found.append(winreg.QueryValueEx(key, "InstallLocation")[0])
            except FileNotFoundError:
                pass
    return found


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(command):
    result = subprocess.run(command, timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(f"Installer operation returned {result.returncode}; inspect the QA log.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("installer", type=Path)
    parser.add_argument("application", type=Path)
    args = parser.parse_args()
    if registrations():
        raise RuntimeError("A real TextSpeak Pro installation is registered. Refusing to replace its registration during QA.")
    qa_root = ROOT / "build" / "qa"
    qa_root.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="installer-", dir=qa_root))
    destination = output / "installed"
    assert destination.resolve().is_relative_to(qa_root.resolve())
    print("QA directory:", output, flush=True)
    uninstaller = destination / "unins000.exe"

    def uninstall():
        assert uninstaller.resolve().parent == destination.resolve()
        assert all(Path(location).resolve() == destination.resolve() for location in registrations())
        run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
             f"/LOG={output / 'uninstall.log'}"])

    try:
        run([str(args.installer.resolve()), "/CURRENTUSER", "/SP-", "/VERYSILENT",
             "/SUPPRESSMSGBOXES", "/NORESTART", "/NOCLOSEAPPLICATIONS",
             "/NORESTARTAPPLICATIONS", "/NOICONS", "/TASKS=",
             f"/DIR={destination}", f"/LOG={output / 'install.log'}"])
        installed = destination / "TextSpeakPro.exe"
        assert sha256(installed) == sha256(args.application), "Installed executable differs from the verified candidate."
        assert (destination / "LICENSE").is_file() and (destination / "NOTICE").is_file()
        assert not (destination / "portable.flag").exists()
        assert uninstaller.is_file()
        assert registrations() and all(Path(p).resolve() == destination.resolve() for p in registrations())
        sentinel = destination / "user-preservation-check.txt"
        sentinel.write_text("User-created files must survive uninstall.\n", encoding="utf-8")
        uninstall()
        assert not installed.exists() and not registrations()
        assert sentinel.read_text(encoding="utf-8") == "User-created files must survive uninstall.\n"
        report = dict(install_passed=True, executable_hash_matches=True,
                      notices_installed=True, uninstall_passed=True,
                      user_created_file_preserved=True, installer_sha256=sha256(args.installer))
        (output / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)
    finally:
        if uninstaller.exists() and registrations():
            uninstall()


if __name__ == "__main__":
    main()
