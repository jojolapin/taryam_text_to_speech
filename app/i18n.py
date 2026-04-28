"""Python-side i18n strings (tray, dialogs, splash).

The web UI has its own string table in ``ui/i18n.js``; this one only covers
native Qt chrome that never enters the webview.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

from PySide6.QtCore import QLocale


STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "app.loading": "Loading voices...",
        "app.ready": "Ready",
        "tray.show": "Show TextSpeak Pro",
        "tray.hide": "Hide window",
        "tray.read_clipboard": "Read clipboard now",
        "tray.stop": "Stop reading",
        "tray.quit": "Quit",
        "tray.tooltip": "TextSpeak Pro - (C) 2026 JojoLapin Inc.",
        "menu.file": "File",
        "menu.open": "Open text file...",
        "menu.recent": "Recent files",
        "menu.save_audio": "Export audio...",
        "menu.exit": "Exit",
        "menu.view": "View",
        "menu.theme": "Theme",
        "menu.theme.system": "Follow system",
        "menu.theme.light": "Light",
        "menu.theme.dark": "Dark",
        "menu.language": "Language",
        "menu.language.system": "Follow system",
        "menu.language.en": "English",
        "menu.language.fr": "Fran\u00e7ais",
        "menu.help": "Help",
        "menu.voices_folder": "Open voices folder",
        "menu.logs_folder": "Open logs folder",
        "menu.about": "About TextSpeak Pro",
        "dialog.open_text": "Open text file",
        "dialog.save_audio": "Save audio as",
        "dialog.text_filter": "Text files (*.txt *.md *.html *.htm *.json *.csv);;PDF files (*.pdf);;All files (*)",
        "dialog.audio_filter_mp3": "MP3 audio (*.mp3)",
        "dialog.audio_filter_wav": "WAV audio (*.wav)",
        "dialog.audio_filter_ogg": "OGG Vorbis (*.ogg)",
        "error.piper_missing": ("Piper TTS is not installed in this Python environment. "
                                 "Please reinstall the app or run:\n  pip install piper-tts"),
        "error.voice_load": "Could not load voice '{voice}': {error}",
        "error.synthesis": "Synthesis failed: {error}",
        "error.export": "Audio export failed: {error}",
        "error.download": "Voice download failed: {error}",
        "confirm.delete_voice.title": "Delete voice?",
        "confirm.delete_voice.body": "Are you sure you want to delete the voice '{voice}'?",
        "confirm.quit.title": "Quit TextSpeak Pro?",
        "confirm.quit.body": "A reading is still in progress. Quit anyway?",
        "about.title": "About TextSpeak Pro",
        "about.tagline": "Offline neural text-to-speech reader",
        "about.trademark": "TextSpeak Pro\u2122 by JojoLapin Inc.",
        "about.copyright": "(C) 2026 JojoLapin Inc. All rights reserved.",
        "about.credits": ("Powered by Piper TTS (OHF-Voice, GPL-3.0).\n"
                          "Voice models published by the Piper community.\n"
                          "Inter font (C) Rasmus Andersson, SIL OFL 1.1."),
    },
    "fr": {
        "app.loading": "Chargement des voix...",
        "app.ready": "Pr\u00eat",
        "tray.show": "Afficher TextSpeak Pro",
        "tray.hide": "Masquer la fen\u00eatre",
        "tray.read_clipboard": "Lire le presse-papiers",
        "tray.stop": "Arr\u00eater la lecture",
        "tray.quit": "Quitter",
        "tray.tooltip": "TextSpeak Pro - (C) 2026 JojoLapin Inc.",
        "menu.file": "Fichier",
        "menu.open": "Ouvrir un fichier texte...",
        "menu.recent": "R\u00e9cemment ouverts",
        "menu.save_audio": "Exporter l'audio...",
        "menu.exit": "Quitter",
        "menu.view": "Affichage",
        "menu.theme": "Th\u00e8me",
        "menu.theme.system": "Suivre le syst\u00e8me",
        "menu.theme.light": "Clair",
        "menu.theme.dark": "Sombre",
        "menu.language": "Langue",
        "menu.language.system": "Suivre le syst\u00e8me",
        "menu.language.en": "English",
        "menu.language.fr": "Fran\u00e7ais",
        "menu.help": "Aide",
        "menu.voices_folder": "Ouvrir le dossier des voix",
        "menu.logs_folder": "Ouvrir le dossier des journaux",
        "menu.about": "\u00c0 propos de TextSpeak Pro",
        "dialog.open_text": "Ouvrir un fichier texte",
        "dialog.save_audio": "Enregistrer l'audio sous",
        "dialog.text_filter": "Fichiers texte (*.txt *.md *.html *.htm *.json *.csv);;Fichiers PDF (*.pdf);;Tous les fichiers (*)",
        "dialog.audio_filter_mp3": "Audio MP3 (*.mp3)",
        "dialog.audio_filter_wav": "Audio WAV (*.wav)",
        "dialog.audio_filter_ogg": "OGG Vorbis (*.ogg)",
        "error.piper_missing": ("Piper TTS n'est pas install\u00e9 dans cet environnement Python. "
                                 "R\u00e9installez l'application ou ex\u00e9cutez :\n  pip install piper-tts"),
        "error.voice_load": "Impossible de charger la voix \u00ab {voice} \u00bb : {error}",
        "error.synthesis": "\u00c9chec de la synth\u00e8se : {error}",
        "error.export": "\u00c9chec de l'export audio : {error}",
        "error.download": "\u00c9chec du t\u00e9l\u00e9chargement de la voix : {error}",
        "confirm.delete_voice.title": "Supprimer la voix ?",
        "confirm.delete_voice.body": "Voulez-vous vraiment supprimer la voix \u00ab {voice} \u00bb ?",
        "confirm.quit.title": "Quitter TextSpeak Pro ?",
        "confirm.quit.body": "Une lecture est en cours. Quitter malgr\u00e9 tout ?",
        "about.title": "\u00c0 propos de TextSpeak Pro",
        "about.tagline": "Lecteur de synth\u00e8se vocale neuronale hors ligne",
        "about.trademark": "TextSpeak Pro\u2122 par JojoLapin Inc.",
        "about.copyright": "(C) 2026 JojoLapin Inc. Tous droits r\u00e9serv\u00e9s.",
        "about.credits": ("Propuls\u00e9 par Piper TTS (OHF-Voice, GPL-3.0).\n"
                          "Mod\u00e8les de voix publi\u00e9s par la communaut\u00e9 Piper.\n"
                          "Police Inter (C) Rasmus Andersson, SIL OFL 1.1."),
    },
}


def detect_system_lang() -> str:
    """Return 'fr' or 'en' based on the OS locale, defaulting to English."""
    try:
        name = QLocale.system().name() or ""
    except Exception:
        name = ""
    if name.lower().startswith("fr"):
        return "fr"
    return "en"


def resolve_lang(preference: str) -> str:
    """Given a user preference ('system'|'en'|'fr'), return the effective code."""
    if preference in {"en", "fr"}:
        return preference
    return detect_system_lang()


def t(key: str, lang: str, **kwargs: object) -> str:
    """Translate ``key`` into ``lang`` with optional ``.format`` kwargs."""
    code = lang if lang in STRINGS else "en"
    table = STRINGS[code]
    value = table.get(key) or STRINGS["en"].get(key) or key
    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return value
    return value
