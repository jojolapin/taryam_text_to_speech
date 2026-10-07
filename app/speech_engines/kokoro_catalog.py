"""Curated Kokoro preset voices.

Names follow the Kokoro-82M voice ids. Presentation labels describe the
published voice, not a real person. Language codes are the ones Kokoro
passes to its phonemizer.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

# id, short name, kokoro lang, catalog language code, gender, English language, French language
_VOICES = (
    ("af_heart", "Heart", "en-us", "en-US", "female", "English (US)", "Anglais (É.-U.)"),
    ("af_bella", "Bella", "en-us", "en-US", "female", "English (US)", "Anglais (É.-U.)"),
    ("af_sarah", "Sarah", "en-us", "en-US", "female", "English (US)", "Anglais (É.-U.)"),
    ("af_nicole", "Nicole", "en-us", "en-US", "female", "English (US)", "Anglais (É.-U.)"),
    ("am_michael", "Michael", "en-us", "en-US", "male", "English (US)", "Anglais (É.-U.)"),
    ("am_adam", "Adam", "en-us", "en-US", "male", "English (US)", "Anglais (É.-U.)"),
    ("am_fenrir", "Fenrir", "en-us", "en-US", "male", "English (US)", "Anglais (É.-U.)"),
    ("bf_emma", "Emma", "en-gb", "en-GB", "female", "English (UK)", "Anglais (R.-U.)"),
    ("bf_isabella", "Isabella", "en-gb", "en-GB", "female", "English (UK)", "Anglais (R.-U.)"),
    ("bm_george", "George", "en-gb", "en-GB", "male", "English (UK)", "Anglais (R.-U.)"),
    ("bm_daniel", "Daniel", "en-gb", "en-GB", "male", "English (UK)", "Anglais (R.-U.)"),
    ("ff_siwis", "Siwis", "fr-fr", "fr-FR", "female", "French", "Français"),
    ("ef_dora", "Dora", "es", "es", "female", "Spanish", "Espagnol"),
    ("em_alex", "Alex", "es", "es", "male", "Spanish", "Espagnol"),
    ("if_sara", "Sara", "it", "it", "female", "Italian", "Italien"),
    ("im_nicola", "Nicola", "it", "it", "male", "Italian", "Italien"),
    ("pf_dora", "Dora", "pt-br", "pt-BR", "female", "Portuguese (BR)", "Portugais (BR)"),
    ("pm_alex", "Alex", "pt-br", "pt-BR", "male", "Portuguese (BR)", "Portugais (BR)"),
    ("hf_alpha", "Alpha", "hi", "hi", "female", "Hindi", "Hindi"),
    ("hm_omega", "Omega", "hi", "hi", "male", "Hindi", "Hindi"),
    ("jf_alpha", "Alpha", "ja", "ja", "female", "Japanese", "Japonais"),
    ("jm_kumo", "Kumo", "ja", "ja", "male", "Japanese", "Japonais"),
    ("zf_xiaoxiao", "Xiaoxiao", "zh", "zh", "female", "Chinese", "Chinois"),
    ("zm_yunxi", "Yunxi", "zh", "zh", "male", "Chinese", "Chinois"),
)


def voices() -> list[dict]:
    rows = []
    for voice_id, name, kokoro_lang, language, gender, lang_en, lang_fr in _VOICES:
        rows.append({
            "id": voice_id,
            "storage_id": f"kokoro:{voice_id}",
            "name": name,
            "kokoro_lang": kokoro_lang,
            "language": language,
            "gender": gender,
            "lang_en": lang_en,
            "lang_fr": lang_fr,
            "engine": "kokoro",
            "local": True,
            "cloning": False,
        })
    return rows


def voice_by_storage_id(storage_id: str) -> dict | None:
    key = (storage_id or "").split(":", 1)[-1]
    for row in voices():
        if row["id"] == key or row["storage_id"] == storage_id:
            return row
    return None


def choice_label(row: dict, lang: str) -> str:
    language = row["lang_fr"] if lang == "fr" else row["lang_en"]
    if lang == "fr":
        presentation = "Féminine" if row["gender"] == "female" else "Masculine"
    else:
        presentation = "Female" if row["gender"] == "female" else "Male"
    return f"{row['name']} · {language} · {presentation}"
