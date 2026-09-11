"""Two-process IndexedDB migration verification against an isolated profile."""
import argparse
import json
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl

parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=["seed", "verify"])
parser.add_argument("profile")
args = parser.parse_args()
os.environ["TEXTSPEAK_DATA_DIR"] = str(Path(args.profile).resolve())
from app import paths
from app.legacy_migration import LegacyMigration
from app.documents import SessionStore

app = QApplication([])
snapshot = {"schema":1, "activeId":"legacy-b", "docs":[
    {"id":"legacy-a", "title":"Original A", "text":"Legacy text café 😀", "playbackPosition":7,
     "bookmarks":[{"position":4, "preview":"Marker"}], "pronunciationRules":[{"from":"DAIDALUS", "to":"Day-da-lus"}]},
    {"id":"legacy-b", "text":"Original B", "speakingStyle":"calm", "extraField":"preserved"}]}
result = []

if args.mode == "seed":
    profile = QWebEngineProfile("TextSpeakPro")
    profile.setPersistentStoragePath(str(paths.web_storage_dir()))
    page = QWebEnginePage(profile)
    view = QWebEngineView()
    view.setPage(page)
    view.show()
    def loaded(ok):
        print("loadFinished", ok, flush=True)
        if not ok:
            result.append({"error":"Page load failed"})
            return
        page.runJavaScript("""
            window.seedDone = null;
            const req = indexedDB.open('textspeak',1);
            req.onupgradeneeded = () => req.result.createObjectStore('workspace');
            req.onerror = () => window.seedDone = {error:'open failed'};
            req.onsuccess = () => {
              const db=req.result;
              const tx=db.transaction('workspace','readwrite');
              tx.objectStore('workspace').put(SNAPSHOT,'snapshot');
              tx.oncomplete=()=>{db.close();window.seedDone={ok:true};};
              tx.onerror=()=>window.seedDone={error:'write failed'};
            };
        """.replace("SNAPSHOT", json.dumps(snapshot)))
    page.loadFinished.connect(loaded)
    page.setHtml("<html>Migration fixture</html>", QUrl.fromLocalFile(str(paths.ui_dir()/"index.html")))
    until = time.monotonic()+20
    while not result and time.monotonic()<until:
        app.processEvents()
        page.runJavaScript("JSON.stringify(window.seedDone || null)", lambda value: result.append(json.loads(value)) if value and value != "null" else None)
        time.sleep(.05)
else:
    migration = LegacyMigration()
    migration.finished.connect(lambda value: result.append(value))
    migration.failed.connect(lambda message: result.append({"error":message}))
    migration.start()
    until = time.monotonic()+25
    while not result and time.monotonic()<until:
        app.processEvents()
        time.sleep(.05)
    assert result and result[0] == snapshot, result
    store = SessionStore(paths.user_data_dir()/"workspace-v2.json")
    store.save(result[0])
    assert store.load()["docs"][1]["extraField"] == "preserved"
    assert (paths.web_storage_dir()/"IndexedDB").exists()
assert result and not result[0].get("error"), result
print(args.mode, "PASS")
