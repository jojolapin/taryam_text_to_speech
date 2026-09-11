"""Read supported documents off-thread; imports never overwrite source files."""
from html.parser import HTMLParser
from pathlib import Path
from .documents import read_txt, decode_text


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"br", "p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden-1)
        if tag in {"p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def read_document(path):
    path = Path(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("This document exceeds the 32 MB import limit.")
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError("This PDF is encrypted. Export an unlocked text copy first.")
        result = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        if not result.strip():
            raise ValueError("This PDF contains no extractable text. Scanned pages need OCR before import.")
        return result
    if path.suffix.lower() in {".html", ".htm"}:
        parser = _HTMLText()
        parser.feed(decode_text(path.read_bytes()))
        return "".join(parser.parts).strip()
    return read_txt(path)


def editable_source(path):
    return Path(path).suffix.lower() in {".txt", ".md", ".markdown"}
