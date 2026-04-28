/* TextSpeak Pro - i18n string table
 * (C) 2026 JojoLapin Inc. All rights reserved.
 */
(function () {
  'use strict';

  const STRINGS = {
    en: {
      // App chrome
      'app.name': 'TextSpeak Pro',
      'app.tagline': 'Offline neural text-to-speech',
      'app.engine.tag': 'Piper TTS · Offline',
      'app.tm': 'TextSpeak Pro\u2122 by JojoLapin Inc.',
      'app.copyright': '\u00a9 2026 JojoLapin Inc.',

      // Title bar
      'tb.minimize': 'Minimize',
      'tb.maximize': 'Maximize',
      'tb.restore': 'Restore',
      'tb.close': 'Close',

      // Header actions
      'hdr.import': 'Import',
      'hdr.bookmarks': 'Bookmarks',
      'hdr.debug': 'Debug',
      'hdr.voices': 'Voices',
      'hdr.settings': 'Settings',
      'hdr.md': 'MD',
      'hdr.md.title.on': 'Markdown-aware reading is ON. Click to turn off.',
      'hdr.md.title.off': 'Markdown-aware reading is OFF. Click to turn on.',
      'hdr.md.title.auto': 'Markdown-aware reading is AUTO (detected: {state}). Click to switch.',

      // Status banner states
      'status.ready': 'Ready \u2014 paste or type text, then press Play.',
      'status.playing': 'Playing',
      'status.paused': 'Paused',
      'status.loading': 'Synthesizing\u2026',
      'status.done': 'Finished',
      'status.idle': 'Ready',
      'status.error': 'Error',

      // Missing voices banner
      'nv.title': 'No voices installed',
      'nv.body': 'Open the Voices panel to download a free neural voice.',
      'nv.cta': 'Open Voice Catalog',

      // Editor
      'editor.placeholder':
        'Paste or type your text here...\n\nTips:\n\u2022 Double-click any word to start reading from there\n\u2022 Drop a .txt, .md or .pdf file onto the window\n\u2022 Press Space to pause / resume while reading',

      // Stats
      'stats.words': 'words',
      'stats.chars': 'chars',
      'stats.readtime': 'min read',
      'stats.chunks': 'chunks',

      // Controls
      'btn.play': 'Play',
      'btn.fromCursor': 'From Cursor',
      'btn.pause': 'Pause',
      'btn.resume': 'Resume',
      'btn.stop': 'Stop',
      'btn.restart': 'Restart',
      'btn.skipBack': '-10s',
      'btn.skipForward': '+10s',
      'btn.find': 'Find',
      'title.fromCursor': 'Start reading from the cursor position',
      'title.restart': 'Stop and restart from the very beginning',
      'title.skipBack': 'Skip back 10 seconds',
      'title.skipForward': 'Skip forward 10 seconds',

      // Export row
      'exp.download': 'Export audio',
      'exp.batch': 'Batch export',
      'exp.format': 'Format',
      'exp.bitrate': 'Bitrate',
      'exp.hint': 'Saves the entire text as an audio file.',
      'exp.batchHint': 'One file per paragraph (blank line = new paragraph).',

      // Settings grid
      'set.voice': 'Voice',
      'set.speed': 'Speed',
      'set.volume': 'Volume',
      'set.voice.loading': 'Loading voices...',
      'set.voice.none': 'No voices installed',
      'set.cb.highlight': 'Show progress highlighting',
      'set.cb.autoscroll': 'Auto-scroll while reading',
      'set.cb.remember': 'Remember text & position',

      // Shortcuts
      'kb.play': 'Play',
      'kb.fromCursor': 'From cursor',
      'kb.pauseResume': 'Pause / Resume',
      'kb.stop': 'Stop',
      'kb.skip': 'Skip \u00b110s',
      'kb.find': 'Find',

      // Import panel
      'imp.title': 'Import text',
      'imp.drop': 'Drop a file here or click to browse',
      'imp.drop.types': '.txt, .md, .html, .pdf, .json',
      'imp.url.placeholder': 'Paste URL to fetch text\u2026',
      'imp.fetch': 'Fetch from URL',
      'imp.paste': 'Paste from clipboard',
      'imp.clear': 'Clear all',
      'imp.recent': 'Recent files',
      'imp.recent.empty': 'No recent files yet.',

      // Bookmarks panel
      'bm.title': 'Bookmarks',
      'bm.add': 'Add bookmark',
      'bm.empty': 'No bookmarks yet. Start reading and add one to save your position.',

      // Debug panel
      'dbg.title': 'Engine log',
      'dbg.clear': 'Clear',
      'dbg.copy': 'Copy',

      // Voice catalog
      'vc.title': 'Voice catalog',
      'vc.subtitle': 'Download free neural voices for any language.',
      'vc.refresh': 'Refresh catalog',
      'vc.installed': 'Installed',
      'vc.download': 'Download',
      'vc.cancel': 'Cancel',
      'vc.delete': 'Delete',
      'vc.sample': 'Sample',
      'vc.filter.all': 'All languages',
      'vc.filter.quality': 'Any quality',
      'vc.filter.gender': 'Any voice',
      'vc.filter.gender.f': 'Female',
      'vc.filter.gender.m': 'Male',
      'vc.search.placeholder': 'Search voice, language, country\u2026',
      'vc.quality.x_low': 'X-Low',
      'vc.quality.low': 'Low',
      'vc.quality.medium': 'Medium',
      'vc.quality.high': 'High',
      'vc.size': '{size} MB',
      'vc.confirmDelete': 'Delete voice "{voice}"?',
      'vc.empty': 'No voices match your filter.',

      // Settings panel
      'settings.title': 'Settings',
      'settings.theme': 'Theme',
      'settings.language': 'Language',
      'settings.theme.system': 'Follow system',
      'settings.theme.light': 'Light',
      'settings.theme.dark': 'Dark',
      'settings.lang.system': 'Follow system',
      'settings.lang.en': 'English',
      'settings.lang.fr': 'Fran\u00e7ais',
      'settings.export': 'Export defaults',
      'settings.export.format': 'Format',
      'settings.export.bitrate': 'MP3 bitrate',
      'settings.export.author': 'Author (ID3 tag)',
      'settings.export.authorPlaceholder': 'Your name',
      'settings.portable': 'Portable mode',
      'settings.portable.hint':
        'Store settings and voices next to the .exe (USB-friendly). Takes effect after restart.',
      'settings.locations': 'Locations',
      'settings.openVoices': 'Open voices folder',
      'settings.openLogs': 'Open logs folder',
      'settings.openData': 'Open data folder',
      'settings.presets': 'Presets',
      'settings.preset.save': 'Save current as preset',
      'settings.preset.savePrompt': 'Name for this preset',
      'settings.preset.delete': 'Delete preset',
      'settings.preset.empty': 'No presets saved yet.',
      'settings.about': 'About',
      'settings.about.btn': 'About TextSpeak Pro',
      'settings.version': 'Version {version}',

      // Markdown reading (settings section)
      'settings.md': 'Markdown reading',
      'settings.md.hint':
        'Keeps Piper from pronouncing asterisks, hashes, link syntax and table pipes in .md files.',
      'settings.md.mode': 'Markdown handling',
      'settings.md.mode.auto': 'Auto (detect .md files)',
      'settings.md.mode.on': 'Always on',
      'settings.md.mode.off': 'Off (read raw markdown)',
      'settings.md.readCode': 'Read code block contents aloud',
      'settings.md.readUrls': 'Read URLs inside links',
      'settings.md.readTables': 'Read table rows',
      'toast.md.on': 'Markdown-aware reading ON',
      'toast.md.off': 'Markdown-aware reading OFF',
      'toast.md.auto': 'Markdown-aware reading AUTO',

      // About
      'about.title': 'About TextSpeak Pro',
      'about.desc':
        '100% offline neural text-to-speech. No cloud, no API keys, no telemetry.',
      'about.credits':
        'Powered by <a href="https://github.com/OHF-Voice/piper1-gpl" target="_blank">Piper TTS</a> (GPL-3.0). ' +
        'Voice models published by the Piper community.',
      'about.close': 'Close',

      // Export overlay
      'export.title': 'Generating audio\u2026',
      'export.synth': 'Synthesizing {chars} characters with Piper',
      'export.elapsed': 'elapsed',
      'export.eta': 'estimated total',
      'export.cancel': 'Cancel',
      'export.saved': 'Saved {name}',
      'export.failed': 'Export failed: {error}',

      // Find
      'find.placeholder': 'Find in text\u2026',
      'find.count': '{current} / {total}',

      // First-run wizard
      'wiz.welcome': 'Welcome to TextSpeak Pro',
      'wiz.welcome.body':
        "Let's get you set up with one or two voices so you can start reading right away.",
      'wiz.next': 'Next',
      'wiz.back': 'Back',
      'wiz.skip': 'Skip',
      'wiz.done': 'Start reading',
      'wiz.step.lang': 'Language',
      'wiz.step.theme': 'Theme',
      'wiz.step.voices': 'Voices',
      'wiz.voices.body':
        'Pick the voices you want to download now. You can always add more later.',
      'wiz.voices.downloading': 'Downloading {name}\u2026',
      'wiz.voices.total': 'Total download: {size} MB',

      // Toasts
      'toast.bookmarkAdded': 'Bookmark added',
      'toast.bookmarkRemoved': 'Bookmark removed',
      'toast.textCleared': 'Text cleared',
      'toast.pastedClipboard': 'Pasted from clipboard',
      'toast.noText': 'Please enter some text first.',
      'toast.noVoice': 'No voice available. Open the Voice Catalog to download one.',
      'toast.readingComplete': 'Reading complete',
      'toast.copied': 'Copied',
      'toast.presetSaved': 'Preset saved',
      'toast.presetDeleted': 'Preset deleted',
      'toast.voiceInstalled': 'Voice installed: {voice}',
      'toast.voiceDeleted': 'Voice deleted: {voice}',
      'toast.sampleUnavailable': 'Sample unavailable for this voice.',
      'toast.portableOn': 'Portable mode enabled. Restart to apply.',
      'toast.portableOff': 'Portable mode disabled. Restart to apply.',
      'toast.fileLoaded': 'Loaded: {name}',
      'toast.fileReadError': 'Could not read file: {error}',
      'toast.urlFetchError': 'Could not fetch URL (CORS or network).',
      'toast.clipboardError': 'Could not access clipboard.',
      'toast.pdfUnavailable': 'PDF import failed: {error}',
    },
    fr: {
      'app.name': 'TextSpeak Pro',
      'app.tagline': 'Synth\u00e8se vocale neuronale hors ligne',
      'app.engine.tag': 'Piper TTS \u00b7 Hors ligne',
      'app.tm': 'TextSpeak Pro\u2122 par JojoLapin Inc.',
      'app.copyright': '\u00a9 2026 JojoLapin Inc.',

      'tb.minimize': 'R\u00e9duire',
      'tb.maximize': 'Agrandir',
      'tb.restore': 'Restaurer',
      'tb.close': 'Fermer',

      'hdr.import': 'Importer',
      'hdr.bookmarks': 'Signets',
      'hdr.debug': 'Journal',
      'hdr.voices': 'Voix',
      'hdr.settings': 'Param\u00e8tres',
      'hdr.md': 'MD',
      'hdr.md.title.on': 'Lecture markdown activ\u00e9e. Cliquer pour d\u00e9sactiver.',
      'hdr.md.title.off': 'Lecture markdown d\u00e9sactiv\u00e9e. Cliquer pour activer.',
      'hdr.md.title.auto': 'Lecture markdown AUTO (d\u00e9tect\u00e9 : {state}). Cliquer pour changer.',

      'status.ready': 'Pr\u00eat \u2014 collez ou tapez votre texte, puis appuyez sur Lire.',
      'status.playing': 'Lecture',
      'status.paused': 'En pause',
      'status.loading': 'Synth\u00e8se\u2026',
      'status.done': 'Termin\u00e9',
      'status.idle': 'Pr\u00eat',
      'status.error': 'Erreur',

      'nv.title': 'Aucune voix install\u00e9e',
      'nv.body': 'Ouvrez le panneau Voix pour t\u00e9l\u00e9charger une voix neuronale gratuite.',
      'nv.cta': 'Ouvrir le catalogue de voix',

      'editor.placeholder':
        'Collez ou tapez votre texte ici\u2026\n\nAstuces :\n\u2022 Double-cliquez sur un mot pour commencer la lecture \u00e0 partir de l\u00e0\n\u2022 Glissez un fichier .txt, .md ou .pdf dans la fen\u00eatre\n\u2022 Appuyez sur Espace pour mettre en pause / reprendre',

      'stats.words': 'mots',
      'stats.chars': 'car.',
      'stats.readtime': 'min de lecture',
      'stats.chunks': 'segments',

      'btn.play': 'Lire',
      'btn.fromCursor': 'Depuis le curseur',
      'btn.pause': 'Pause',
      'btn.resume': 'Reprendre',
      'btn.stop': 'Arr\u00eater',
      'btn.restart': 'Recommencer',
      'btn.skipBack': '-10s',
      'btn.skipForward': '+10s',
      'btn.find': 'Rechercher',
      'title.fromCursor': 'D\u00e9marrer la lecture \u00e0 la position du curseur',
      'title.restart': 'Arr\u00eater et relire depuis le d\u00e9but',
      'title.skipBack': 'Reculer de 10 secondes',
      'title.skipForward': 'Avancer de 10 secondes',

      'exp.download': 'Exporter l\'audio',
      'exp.batch': 'Export par lot',
      'exp.format': 'Format',
      'exp.bitrate': 'D\u00e9bit',
      'exp.hint': 'Enregistre tout le texte dans un fichier audio.',
      'exp.batchHint': 'Un fichier par paragraphe (ligne vide = nouveau paragraphe).',

      'set.voice': 'Voix',
      'set.speed': 'Vitesse',
      'set.volume': 'Volume',
      'set.voice.loading': 'Chargement des voix\u2026',
      'set.voice.none': 'Aucune voix install\u00e9e',
      'set.cb.highlight': 'Surligner la progression',
      'set.cb.autoscroll': 'D\u00e9filement automatique',
      'set.cb.remember': 'M\u00e9moriser le texte et la position',

      'kb.play': 'Lire',
      'kb.fromCursor': 'Depuis le curseur',
      'kb.pauseResume': 'Pause / Reprise',
      'kb.stop': 'Arr\u00eater',
      'kb.skip': 'Saut \u00b110s',
      'kb.find': 'Rechercher',

      'imp.title': 'Importer du texte',
      'imp.drop': 'Glissez un fichier ici ou cliquez pour parcourir',
      'imp.drop.types': '.txt, .md, .html, .pdf, .json',
      'imp.url.placeholder': 'Collez une URL \u00e0 r\u00e9cup\u00e9rer\u2026',
      'imp.fetch': 'R\u00e9cup\u00e9rer l\'URL',
      'imp.paste': 'Coller depuis le presse-papiers',
      'imp.clear': 'Tout effacer',
      'imp.recent': 'Fichiers r\u00e9cents',
      'imp.recent.empty': 'Aucun fichier r\u00e9cent.',

      'bm.title': 'Signets',
      'bm.add': 'Ajouter un signet',
      'bm.empty': 'Aucun signet. Commencez une lecture et enregistrez votre position.',

      'dbg.title': 'Journal du moteur',
      'dbg.clear': 'Effacer',
      'dbg.copy': 'Copier',

      'vc.title': 'Catalogue de voix',
      'vc.subtitle': 'T\u00e9l\u00e9chargez gratuitement des voix neuronales dans plus de 30 langues.',
      'vc.refresh': 'Actualiser le catalogue',
      'vc.installed': 'Install\u00e9e',
      'vc.download': 'T\u00e9l\u00e9charger',
      'vc.cancel': 'Annuler',
      'vc.delete': 'Supprimer',
      'vc.sample': 'Aper\u00e7u',
      'vc.filter.all': 'Toutes les langues',
      'vc.filter.quality': 'Toute qualit\u00e9',
      'vc.filter.gender': 'Tout genre',
      'vc.filter.gender.f': 'F\u00e9minine',
      'vc.filter.gender.m': 'Masculine',
      'vc.search.placeholder': 'Rechercher voix, langue, pays\u2026',
      'vc.quality.x_low': 'Tr\u00e8s basse',
      'vc.quality.low': 'Basse',
      'vc.quality.medium': 'Moyenne',
      'vc.quality.high': '\u00c9lev\u00e9e',
      'vc.size': '{size} Mo',
      'vc.confirmDelete': 'Supprimer la voix \u00ab {voice} \u00bb ?',
      'vc.empty': 'Aucune voix ne correspond \u00e0 votre filtre.',

      'settings.title': 'Param\u00e8tres',
      'settings.theme': 'Th\u00e8me',
      'settings.language': 'Langue',
      'settings.theme.system': 'Suivre le syst\u00e8me',
      'settings.theme.light': 'Clair',
      'settings.theme.dark': 'Sombre',
      'settings.lang.system': 'Suivre le syst\u00e8me',
      'settings.lang.en': 'English',
      'settings.lang.fr': 'Fran\u00e7ais',
      'settings.export': 'Valeurs par d\u00e9faut d\'export',
      'settings.export.format': 'Format',
      'settings.export.bitrate': 'D\u00e9bit MP3',
      'settings.export.author': 'Auteur (tag ID3)',
      'settings.export.authorPlaceholder': 'Votre nom',
      'settings.portable': 'Mode portable',
      'settings.portable.hint':
        'Stocker les param\u00e8tres et les voix \u00e0 c\u00f4t\u00e9 du .exe (id\u00e9al USB). Prend effet apr\u00e8s red\u00e9marrage.',
      'settings.locations': 'Emplacements',
      'settings.openVoices': 'Ouvrir le dossier des voix',
      'settings.openLogs': 'Ouvrir le dossier des journaux',
      'settings.openData': 'Ouvrir le dossier de donn\u00e9es',
      'settings.presets': 'Pr\u00e9r\u00e9glages',
      'settings.preset.save': 'Enregistrer l\'actuel',
      'settings.preset.savePrompt': 'Nom du pr\u00e9r\u00e9glage',
      'settings.preset.delete': 'Supprimer le pr\u00e9r\u00e9glage',
      'settings.preset.empty': 'Aucun pr\u00e9r\u00e9glage.',
      'settings.about': '\u00c0 propos',
      'settings.about.btn': '\u00c0 propos de TextSpeak Pro',
      'settings.version': 'Version {version}',

      'settings.md': 'Lecture markdown',
      'settings.md.hint':
        'Emp\u00eache Piper de prononcer les ast\u00e9risques, di\u00e8ses, crochets et barres de tableau des fichiers .md.',
      'settings.md.mode': 'Traitement markdown',
      'settings.md.mode.auto': 'Auto (d\u00e9tecter les .md)',
      'settings.md.mode.on': 'Toujours activ\u00e9',
      'settings.md.mode.off': 'D\u00e9sactiv\u00e9 (lire le markdown brut)',
      'settings.md.readCode': 'Lire le contenu des blocs de code',
      'settings.md.readUrls': 'Lire les URL dans les liens',
      'settings.md.readTables': 'Lire les lignes des tableaux',
      'toast.md.on': 'Lecture markdown ACTIV\u00c9E',
      'toast.md.off': 'Lecture markdown D\u00c9SACTIV\u00c9E',
      'toast.md.auto': 'Lecture markdown AUTO',

      'about.title': '\u00c0 propos de TextSpeak Pro',
      'about.desc':
        'Synth\u00e8se vocale 100 % hors ligne. Pas de cloud, pas de cl\u00e9 API, pas de t\u00e9l\u00e9m\u00e9trie.',
      'about.credits':
        'Propuls\u00e9 par <a href="https://github.com/OHF-Voice/piper1-gpl" target="_blank">Piper TTS</a> (GPL-3.0). ' +
        'Mod\u00e8les de voix publi\u00e9s par la communaut\u00e9 Piper.',
      'about.close': 'Fermer',

      'export.title': 'G\u00e9n\u00e9ration de l\'audio\u2026',
      'export.synth': 'Synth\u00e8se de {chars} caract\u00e8res avec Piper',
      'export.elapsed': '\u00e9coul\u00e9',
      'export.eta': 'estimation totale',
      'export.cancel': 'Annuler',
      'export.saved': 'Enregistr\u00e9 : {name}',
      'export.failed': '\u00c9chec de l\'export : {error}',

      'find.placeholder': 'Rechercher dans le texte\u2026',
      'find.count': '{current} / {total}',

      'wiz.welcome': 'Bienvenue dans TextSpeak Pro',
      'wiz.welcome.body':
        'Configurons une ou deux voix pour que vous puissiez commencer la lecture imm\u00e9diatement.',
      'wiz.next': 'Suivant',
      'wiz.back': 'Retour',
      'wiz.skip': 'Passer',
      'wiz.done': 'Commencer la lecture',
      'wiz.step.lang': 'Langue',
      'wiz.step.theme': 'Th\u00e8me',
      'wiz.step.voices': 'Voix',
      'wiz.voices.body':
        'Choisissez les voix \u00e0 t\u00e9l\u00e9charger maintenant. Vous pourrez en ajouter plus tard.',
      'wiz.voices.downloading': 'T\u00e9l\u00e9chargement de {name}\u2026',
      'wiz.voices.total': 'T\u00e9l\u00e9chargement total : {size} Mo',

      'toast.bookmarkAdded': 'Signet ajout\u00e9',
      'toast.bookmarkRemoved': 'Signet supprim\u00e9',
      'toast.textCleared': 'Texte effac\u00e9',
      'toast.pastedClipboard': 'Coll\u00e9 depuis le presse-papiers',
      'toast.noText': 'Veuillez saisir du texte.',
      'toast.noVoice': 'Aucune voix disponible. Ouvrez le catalogue pour en t\u00e9l\u00e9charger une.',
      'toast.readingComplete': 'Lecture termin\u00e9e',
      'toast.copied': 'Copi\u00e9',
      'toast.presetSaved': 'Pr\u00e9r\u00e9glage enregistr\u00e9',
      'toast.presetDeleted': 'Pr\u00e9r\u00e9glage supprim\u00e9',
      'toast.voiceInstalled': 'Voix install\u00e9e : {voice}',
      'toast.voiceDeleted': 'Voix supprim\u00e9e : {voice}',
      'toast.sampleUnavailable': 'Aper\u00e7u indisponible pour cette voix.',
      'toast.portableOn': 'Mode portable activ\u00e9. Red\u00e9marrez pour appliquer.',
      'toast.portableOff': 'Mode portable d\u00e9sactiv\u00e9. Red\u00e9marrez pour appliquer.',
      'toast.fileLoaded': 'Charg\u00e9 : {name}',
      'toast.fileReadError': 'Lecture du fichier impossible : {error}',
      'toast.urlFetchError': 'R\u00e9cup\u00e9ration de l\'URL impossible (CORS ou r\u00e9seau).',
      'toast.clipboardError': 'Acc\u00e8s au presse-papiers impossible.',
      'toast.pdfUnavailable': 'Import PDF \u00e9chou\u00e9 : {error}',
    },
  };

  let currentLang = 'en';

  function setLang(lang) {
    currentLang = STRINGS[lang] ? lang : 'en';
    document.documentElement.lang = currentLang;
  }

  function t(key, params) {
    const table = STRINGS[currentLang] || STRINGS.en;
    let s = table[key] || STRINGS.en[key] || key;
    if (params) {
      Object.keys(params).forEach((k) => {
        s = s.split('{' + k + '}').join(String(params[k]));
      });
    }
    return s;
  }

  function applyAll() {
    document.querySelectorAll('[data-i18n]').forEach((el) => {
      const key = el.getAttribute('data-i18n');
      if (!key) return;
      const mode = el.getAttribute('data-i18n-attr');
      const val = t(key);
      if (mode === 'placeholder') el.placeholder = val;
      else if (mode === 'title') el.title = val;
      else if (mode === 'html') el.innerHTML = val;
      else el.textContent = val;
    });
    document.querySelectorAll('[data-i18n-title]').forEach((el) => {
      el.title = t(el.getAttribute('data-i18n-title'));
    });
  }

  window.I18N = { t: t, setLang: setLang, applyAll: applyAll, get lang() { return currentLang; } };
})();
