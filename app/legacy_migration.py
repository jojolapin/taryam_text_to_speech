"""Read the original Chromium store without deleting or overwriting it."""
import json
from PySide6.QtCore import QObject, Signal, QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from . import paths


class LegacyMigration(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.done = False
        self.profile = QWebEngineProfile("TextSpeakPro", self)
        self.profile.setPersistentStoragePath(str(paths.web_storage_dir()))
        self.profile.setCachePath(str(paths.web_storage_dir() / "cache"))
        self.page = QWebEnginePage(self.profile, self)
        self.view = QWebEngineView()
        self.view.setPage(self.page)
        self.page.loadFinished.connect(self._loaded)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self._fail("Reading the previous bookmark library timed out. Close other Text Speak Pro instances and retry."))

    def start(self):
        self.timer.start(20000)
        # Same file origin as the original workspace, with no old application JS.
        self.page.setHtml("<html><body>Reading saved bookmarks</body></html>",
                          QUrl.fromLocalFile(str(paths.ui_dir() / "index.html")))

    def _loaded(self, ok):
        if not ok:
            self._fail("Could not open the previous bookmark library.")
            return
        self.page.runJavaScript("""
            window.migrationResult = null;
            (async () => {
              try {
                const databases = await indexedDB.databases();
                if (!databases.some(d => d.name === 'textspeak')) {
                  window.migrationResult = {ok:true, snapshot:null}; return;
                }
                const req = indexedDB.open('textspeak');
                req.onerror = () => window.migrationResult = {error:'Cannot open IndexedDB'};
                req.onsuccess = () => {
                  const db = req.result;
                  if (!db.objectStoreNames.contains('workspace')) {
                    window.migrationResult = {error:'Workspace store is missing'}; db.close(); return;
                  }
                  const tx = db.transaction('workspace', 'readonly');
                  const get = tx.objectStore('workspace').get('snapshot');
                  get.onsuccess = () => { window.migrationResult = {ok:true, snapshot:get.result || null}; db.close(); };
                  get.onerror = () => { window.migrationResult = {error:'Cannot read workspace'}; db.close(); };
                };
              } catch (e) { window.migrationResult = {error:String(e)}; }
            })();
        """, lambda _: self._poll())

    def _poll(self):
        if not self.done:
            self.page.runJavaScript("JSON.stringify(window.migrationResult || null)", self._result)

    def _result(self, result):
        if self.done:
            return
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                self._fail("The previous bookmark library returned an invalid result.")
                return
        if not result:
            QTimer.singleShot(100, self._poll)
        elif result.get("error"):
            self._fail(result["error"])
        elif result.get("ok"):
            self.done = True
            self.timer.stop()
            self.finished.emit(result.get("snapshot"))

    def _fail(self, message):
        if not self.done:
            self.done = True
            self.timer.stop()
            self.failed.emit(message)
