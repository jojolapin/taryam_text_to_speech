"""PyInstaller runtime hook: retain startup tracebacks before app logging exists."""
import os
import sys
from pathlib import Path

try:
    override = os.environ.get("TEXTSPEAK_DATA_DIR", "")
    if "--data-dir" in sys.argv:
        override = sys.argv[sys.argv.index("--data-dir") + 1]
    if override:
        root = Path(override).resolve()
    elif (Path(sys.executable).parent / "portable.flag").exists():
        root = Path(sys.executable).parent
    else:
        root = Path(os.environ.get("APPDATA", str(Path.home()))) / "JojoLapin" / "TextSpeak Pro"
    folder = root / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    if sys.stderr is None:
        sys.stderr = open(folder / "startup.log", "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
except (OSError, IndexError):
    pass
