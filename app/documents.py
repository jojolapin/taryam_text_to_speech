"""Document state and atomic, versioned session recovery. No playback ownership."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import uuid
from pathlib import Path


def new_document(**values):
    doc = dict(id=str(uuid.uuid4()), title="Untitled", text="", cursor=0,
               selStart=0, selEnd=0, scrollTop=0, playbackPosition=0,
               bookmarks=[], pronunciationRules=[], provider="piper", voice="",
               speed=1.0, volume=1.0, markdownMode="auto", speakingStyle="neutral",
               speakingInstructions="", path="", dirty=False)
    doc.update(copy.deepcopy(values))
    if not doc.get("id"):
        doc["id"] = str(uuid.uuid4())
    return doc


def validate_snapshot(value):
    if not isinstance(value, dict) or not isinstance(value.get("docs"), list):
        raise ValueError("The saved workspace is not a document library.")
    if value.get("schema", 1) not in (1, 2):
        raise ValueError("This workspace was saved by a newer application version.")
    docs, seen = [], set()
    for raw in value["docs"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("text", ""), str):
            raise ValueError("A saved document has invalid text.")
        doc = new_document(**raw)
        if not isinstance(doc["id"], str) or not isinstance(doc.get("title", ""), str):
            raise ValueError("A saved document has an invalid identifier or title.")
        for field in ("bookmarks", "pronunciationRules"):
            if not isinstance(doc.get(field), list):
                doc[field] = []
        for field in ("cursor", "selStart", "selEnd", "scrollTop", "playbackPosition"):
            try:
                doc[field] = max(0, int(doc.get(field) or 0))
            except (ValueError, TypeError):
                doc[field] = 0
        if doc["id"] in seen:
            doc["id"] = str(uuid.uuid4())
        seen.add(doc["id"])
        if not doc.get("title"):
            doc["title"] = next((s.strip()[:80] for s in doc["text"].splitlines() if s.strip()), "Untitled")
        # Legacy workspace documents have no external saved-file baseline.
        if "dirty" not in raw:
            doc["dirty"] = bool(doc["text"])
        docs.append(doc)
    if not docs:
        docs = [new_document()]
    selected = value.get("activeId")
    if selected not in {d["id"] for d in docs}:
        selected = docs[0]["id"]
    return dict(schema=2, docs=docs, activeId=selected)


def atomic_write(path: Path, data: bytes):
    """Replace only after bytes are flushed; preserve original on write failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class SessionStore:
    def __init__(self, path):
        self.path = Path(path)
        self.backup = self.path.with_suffix(".backup.json")
        self.recovered = False

    def load(self):
        if not self.path.exists() and not self.backup.exists():
            return None
        errors = []
        for candidate in (self.path, self.backup):
            try:
                result = validate_snapshot(json.loads(candidate.read_text(encoding="utf-8")))
                self.recovered = candidate == self.backup
                return result
            except (OSError, ValueError, TypeError) as error:
                errors.append(str(error))
        raise ValueError("Could not recover the saved workspace. Original files were preserved. " + "; ".join(errors))

    def save(self, snapshot):
        checked = validate_snapshot(snapshot)
        data = json.dumps(checked, ensure_ascii=False).encode("utf-8")
        if self.path.exists():
            old = self.path.read_bytes()
            try:
                validate_snapshot(json.loads(old))
            except (ValueError, TypeError):
                pass  # Never overwrite a good recovery backup with corrupt data.
            else:
                atomic_write(self.backup, old)
        atomic_write(self.path, data)


def decode_text(raw: bytes):
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
    if "\x00" in text:
        raise ValueError("This file contains binary data or an unsupported encoding.")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_txt(path):
    path = Path(path)
    if path.suffix.lower() not in {".txt", ".md", ".markdown"}:
        raise ValueError("Choose a TXT or Markdown file.")
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("This file exceeds the 32 MB text editor limit. Split it into smaller files.")
    return decode_text(path.read_bytes())
