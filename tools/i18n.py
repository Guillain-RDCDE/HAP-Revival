#!/usr/bin/env python3
"""
HAP-Revival i18n — one tiny, dependency-free translation layer shared by every
user-facing surface in the project (the web UI, the CLI client, the tkinter
sync GUI, and the library tools).

Design goals:
    - **Stdlib only.** No gettext .mo compilation, no babel, no jinja. A plain
      nested dict of catalogs and a `t()` function. Readable in five minutes.
    - **One source of truth.** Every translatable string lives here, keyed by a
      dotted path (e.g. "web.sound.dsee"). Python code calls `t("web.sound.dsee")`;
      the web UI embeds `catalog_for(lang)` as a JSON blob and translates in the
      browser so the language switch is instant (no server round-trip).
    - **Graceful fallback.** A missing key in the active language falls back to
      English; a key missing even in English returns the key itself (so a typo
      is visible, never a crash).
    - **Auto-detect, manual override.** Language is chosen from, in order:
      an explicit override (CLI `--lang`, env `HAP_LANG`, web `?lang=` / saved
      choice) → the browser `Accept-Language` header (web) → the OS locale
      (CLI/GUI) → English.

Supported languages: en (source), fr, ja, de, es, it. Adding one is a single
new dict below — the fallback machinery does the rest.

CLI smoke test:
    python tools/i18n.py            # list languages + a sample line in each
    python tools/i18n.py fr web.sound.dsee
"""

from __future__ import annotations

import locale
import os
import sys

# Order matters: the first entry is the canonical source language and the
# universal fallback. Keep "en" first.
LANGUAGES: dict[str, str] = {
    "en": "English",
    "fr": "Français",
    "ja": "日本語",
    "de": "Deutsch",
    "es": "Español",
    "it": "Italiano",
}

DEFAULT_LANG = "en"


# ---------------------------------------------------------------------------
# Catalogs.  Keys are dotted paths grouped by surface:
#   common.*   shared atoms (on/off/auto, yes/no…)
#   cli.*      the hap_client.py command-line output
#   web.*      the browser control surface (webui.py)
#   gui.*      the tkinter sync app (hap_gui.py)
# English is complete and authoritative; every other language is expected to
# mirror it, but any gap silently falls back to English.
# ---------------------------------------------------------------------------

EN: dict[str, str] = {
    # --- shared atoms ---
    "common.app_name": "HAP-Revival",
    "common.on": "on",
    "common.off": "off",
    "common.auto": "auto",
    "common.yes": "yes",
    "common.no": "no",
    "common.language": "Language",
    # --- CLI: now-playing ---
    "cli.np.streaming": "streaming ({src})",
    "cli.np.art": "art: {url}",
    "cli.sent.pause": "pause sent",
    "cli.sent.resume": "resume sent",
    "cli.sent.next": "next sent",
    "cli.sent.previous": "previous sent",
    "cli.sent.seek": "seek to {pos}s sent",
    "cli.sent.play_track": "playing track {id} on {uri}",
    # --- CLI: system block ---
    "cli.sys.model": "model",
    "cli.sys.name": "name",
    "cli.sys.product": "product",
    "cli.sys.version": "version",
    "cli.sys.gen": "gen",
    "cli.sys.mac": "mac",
    "cli.sys.lang": "lang",
    "cli.sys.power": "power",
    # --- CLI: sound block ---
    "cli.snd.dsee": "DSEE",
    "cli.snd.dsd": "DSD remastering",
    "cli.snd.gapless": "Gapless playback",
    "cli.snd.volnorm": "Volume normalization",
    "cli.snd.oversampling": "Oversampling",
    # --- CLI: sleep timer block ---
    "cli.sleep.status": "status",
    "cli.sleep.remain": "remain",
    "cli.sleep.sleep": "sleep",
    "cli.sleep.options": "options",
    # --- CLI: errors ---
    "cli.err.api": "API error: {msg}",
    "cli.err.transport": "Transport error: {msg}",
    # --- Web: header / footer ---
    "web.title": "HAP-Revival — control",
    "web.connecting": "connecting…",
    "web.firmware": "firmware",
    "web.footer.polls": "polls every 3s",
    "web.footer.stdlib": "stdlib only",
    # --- Web: now-playing card ---
    "web.np.streaming": "streaming · {src}",
    "web.state.PLAYING": "playing",
    "web.state.PAUSED": "paused",
    "web.state.PAUSED_PLAYBACK": "paused",
    "web.state.STOPPED": "stopped",
    "web.state.NO_MEDIA_PRESENT": "no media",
    "web.ctrl.previous": "Previous",
    "web.ctrl.play": "Pause / resume",
    "web.ctrl.next": "Next",
    "web.ctrl.standby": "Standby",
    "web.seek_hint": "Click to seek",
    "web.confirm_standby": "Put the HAP in standby?",
    "web.power.active": "on",
    "web.power.standby": "standby",
    # --- Web: settings panel sections ---
    "web.bg.title": "Background",
    "web.bg.ambient": "Ambient cover",
    "web.bg.cover_solid": "Solid (from cover)",
    "web.bg.dark": "Dark",
    "web.bg.custom": "Custom",
    "web.bg.current": "current:",
    "web.lang.title": "Language",
    "web.display.title": "Display",
    "web.display.minimal": "Minimal mode",
    "web.display.minimal_note": "Hides the header (title + device info) and the footer. The now-playing card and the gear stay.",
    "web.sound.title": "Sound",
    "web.sound.dsee": "DSEE",
    "web.sound.dsee_note": "Sony's upscaler. Auto tries to rebuild high frequencies lost in MP3/AAC. Off keeps the signal bit-perfect.",
    "web.sound.dsd": "DSD remastering",
    "web.sound.dsd_note": "Converts PCM (FLAC/WAV) to DSD before the DAC. Some hear it as smoother; off keeps the file's native format.",
    "web.sound.gapless": "Gapless",
    "web.sound.gapless_note": "Removes the silence between consecutive tracks. Auto follows album metadata; off always inserts ~0.1 s.",
    "web.sound.volnorm": "Volume normalize",
    "web.sound.volnorm_note": "Evens out loudness between tracks using ReplayGain tags. Useful for shuffled playback across albums.",
    "web.sound.oversampling": "Oversampling",
    "web.sound.oversampling_note": "DAC reconstruction filter shape. Precision = sharper cutoff (more accurate). Normal = softer (smoother to some).",
    "web.val.precision": "precision",
    "web.val.normal": "normal",
    "web.playback.title": "Playback",
    "web.playback.volume": "Volume",
    "web.playback.volume_note": "HAP-Z1ES has no internal amp — volume is fixed (controlled by your preamp / external amp).",
    "web.playback.sleep": "Sleep timer",
    "web.playback.sleep_note": "Turns the HAP off after the selected duration. Useful for falling asleep to music.",
    "web.minutes": "{n} min",
    "web.current.title": "Current track",
    "web.current.favorite": "Favorite",
    "web.current.favorite_note": "Marks the current track in the HAP library. Buttons disable when playing a non-HDD source (Spotify, radio).",
    "web.fav.title.favorite": "Mark as favorite",
    "web.fav.title.clear": "Clear favorite / dislike",
    "web.fav.title.dislike": "Mark as dislike",
    "web.fav.hdd": "Acts on the current track in the HAP library.",
    "web.fav.nonhdd": "Favorites only work on HDD tracks (current source: {src}).",
    "web.vol.no_amp": "HAP-Z1ES has no internal amp — volume is fixed (use external amp / preamp).",
    "web.vol.amp": "HAP-S1 / amp output. Step: {step}.",
    # --- Web: read-only settings table ---
    "web.tbl.dsee": "DSEE",
    "web.tbl.dsd": "DSD remastering",
    "web.tbl.gapless": "Gapless playback",
    "web.tbl.volnorm": "Volume normalization",
    "web.tbl.oversampling": "Oversampling",
    # --- Web: errors ---
    "web.err.unreachable": "Cannot reach HAP: {msg}",
    "web.err.action": "Action failed: {msg}",
    # --- GUI: window + tabs ---
    "gui.window_title": "HAP Sync — HAP-Revival",
    "gui.tab.transfer": "Transfer",
    "gui.tab.validate": "Validate",
    "gui.tab.compare": "Compare library",
    # --- GUI: connection bar ---
    "gui.conn.ip": "HAP IP",
    "gui.conn.mac": "MAC",
    "gui.conn.autodetect": "Auto-detect",
    "gui.conn.check": "Check",
    "gui.conn.wake": "Wake",
    "gui.conn.save": "Save config",
    "gui.conn.detecting": "Scanning the network for your HAP…",
    "gui.conn.detected": "Found HAP at {ip} ({mac})",
    "gui.conn.not_found": "No HAP found on this subnet.",
    "gui.conn.saved": "Configuration saved.",
    # --- GUI: transfer tab ---
    "gui.xfer.internal": "Internal disk (HAP_Internal)",
    "gui.xfer.external": "USB drive (HAP_External)",
    "gui.xfer.pick_folder": "Choose folder…",
    "gui.xfer.analyze": "Analyze (dry run)",
    "gui.xfer.sync": "Sync",
    "gui.xfer.cancel": "Cancel",
    "gui.xfer.idle": "Ready.",
    "gui.xfer.scanning": "Scanning…",
    "gui.xfer.transferring": "Transferring {done}/{total}…",
    "gui.xfer.done": "Done — {n} files transferred.",
    "gui.xfer.nothing": "Nothing to transfer; everything is up to date.",
    # --- GUI: validate tab ---
    "gui.val.title": "Pre-flight check a folder before sending it to the HAP.",
    "gui.val.run": "Validate folder",
    "gui.val.junk": "Junk files (skipped)",
    "gui.val.unsupported": "Unsupported formats (skipped)",
    "gui.val.over_ceiling": "Above the 192 kHz ceiling",
    "gui.val.missing_cover": "Albums missing cover art",
    "gui.val.ok": "Looks clean — nothing the HAP would choke on.",
    # --- GUI: shared status ---
    "gui.status.ready": "Ready.",
    "gui.status.working": "Working…",
    "gui.status.no_pysmb": "pysmb is not installed — run: pip install pysmb",
    # --- GUI: extra chrome ---
    "gui.menu.language": "Language",
    "gui.conn.fix": "Fix access",
    "gui.lbl.ip": "IP address:",
    "gui.lbl.mac": "MAC:",
    "gui.folders_box": "Folders to sync  (PC → HAP)",
    "gui.add_folder": "+ Add a folder",
    "gui.opt.new_only": "Only add new files (don't overwrite existing)",
    "gui.opt.unsupported": "Include unsupported formats",
    "gui.opt.rescan": "Re-scan the HAP (ignore cache)",
    "gui.btn.analyze": "Analyze",
    "gui.btn.sync": "Sync",
    "gui.btn.stop": "Stop",
    "gui.btn.browse": "Browse…",
    "gui.btn.validate": "Validate",
    "gui.btn.compare": "Compare",
    "gui.lbl.folder": "Folder:",
    "gui.lbl.db": "HAP database (.db):",
    "gui.lbl.local_folder": "Local folder:",
    "gui.warn.enter_ip": "Enter the HAP's IP address (or click Auto-detect).",
    "gui.warn.add_folder": "Add at least one local folder to transfer.",
    "gui.warn.valid_folder": "Choose a valid folder to validate.",
    "gui.warn.choose_db": "Choose the HAP library .db file.",
    "gui.warn.choose_local": "Choose a local folder to compare.",
    "gui.validate_help": (
        "What this does: scans a PC folder before you send it and reports files the HAP "
        "would reject or that would clutter its library — junk (Thumbs.db, .DS_Store, "
        ".ffs_tmp…) the HAP indexes as ghost tracks, unsupported formats, PCM over 192 kHz "
        "(above the HAP's playback limit) and albums with no cover art.\n"
        "When to use it: optional. Sync already skips junk and unsupported files on its own, "
        "so this is just a pre-flight report — most useful to catch >192 kHz files and "
        "missing covers, which Sync won't fix for you."
    ),
    "gui.diff_help": (
        "What this does: compares a local <Artist>/<Album>/ tree against the HAP's own music "
        "database and lists which albums are NEW vs already on the device — matched by "
        "content (artist + album names), not by filename or date.\n"
        "What it needs: the HAP's SQLite catalog (.db), which you only get by reading the "
        "HAP's internal disk — so this is an advanced/occasional tool. For everyday use, just "
        "use Sync: it already compares against the files actually on the share and transfers "
        "only what's missing."
    ),
}

FR: dict[str, str] = {
    "common.on": "activé",
    "common.off": "désactivé",
    "common.auto": "auto",
    "common.yes": "oui",
    "common.no": "non",
    "common.language": "Langue",
    "cli.np.streaming": "diffusion ({src})",
    "cli.np.art": "pochette : {url}",
    "cli.sent.pause": "pause envoyée",
    "cli.sent.resume": "lecture relancée",
    "cli.sent.next": "piste suivante envoyée",
    "cli.sent.previous": "piste précédente envoyée",
    "cli.sent.seek": "saut à {pos}s envoyé",
    "cli.sent.play_track": "lecture de la piste {id} sur {uri}",
    "cli.sys.model": "modèle",
    "cli.sys.name": "nom",
    "cli.sys.product": "produit",
    "cli.sys.version": "version",
    "cli.sys.gen": "génération",
    "cli.sys.mac": "adresse MAC",
    "cli.sys.lang": "langue",
    "cli.sys.power": "alimentation",
    "cli.snd.dsee": "DSEE",
    "cli.snd.dsd": "Remastérisation DSD",
    "cli.snd.gapless": "Lecture sans blanc",
    "cli.snd.volnorm": "Normalisation du volume",
    "cli.snd.oversampling": "Suréchantillonnage",
    "cli.sleep.status": "état",
    "cli.sleep.remain": "restant",
    "cli.sleep.sleep": "minuterie",
    "cli.sleep.options": "options",
    "cli.err.api": "Erreur API : {msg}",
    "cli.err.transport": "Erreur de transport : {msg}",
    "web.title": "HAP-Revival — commande",
    "web.connecting": "connexion…",
    "web.firmware": "micrologiciel",
    "web.footer.polls": "interrogé toutes les 3 s",
    "web.footer.stdlib": "stdlib uniquement",
    "web.np.streaming": "diffusion · {src}",
    "web.state.PLAYING": "lecture",
    "web.state.PAUSED": "en pause",
    "web.state.PAUSED_PLAYBACK": "en pause",
    "web.state.STOPPED": "arrêté",
    "web.state.NO_MEDIA_PRESENT": "aucun média",
    "web.ctrl.previous": "Précédent",
    "web.ctrl.play": "Pause / lecture",
    "web.ctrl.next": "Suivant",
    "web.ctrl.standby": "Veille",
    "web.seek_hint": "Cliquer pour se déplacer",
    "web.confirm_standby": "Mettre le HAP en veille ?",
    "web.power.active": "allumé",
    "web.power.standby": "veille",
    "web.bg.title": "Arrière-plan",
    "web.bg.ambient": "Pochette ambiante",
    "web.bg.cover_solid": "Uni (depuis la pochette)",
    "web.bg.dark": "Sombre",
    "web.bg.custom": "Personnalisé",
    "web.bg.current": "actuel :",
    "web.lang.title": "Langue",
    "web.display.title": "Affichage",
    "web.display.minimal": "Mode minimal",
    "web.display.minimal_note": "Masque l'en-tête (titre + infos appareil) et le pied de page. La carte de lecture et l'engrenage restent.",
    "web.sound.title": "Son",
    "web.sound.dsee": "DSEE",
    "web.sound.dsee_note": "Le rehausseur Sony. Auto tente de reconstruire les hautes fréquences perdues en MP3/AAC. Désactivé garde le signal bit-perfect.",
    "web.sound.dsd": "Remastérisation DSD",
    "web.sound.dsd_note": "Convertit le PCM (FLAC/WAV) en DSD avant le DAC. Certains le trouvent plus doux ; désactivé garde le format natif du fichier.",
    "web.sound.gapless": "Sans blanc",
    "web.sound.gapless_note": "Supprime le silence entre les pistes consécutives. Auto suit les métadonnées d'album ; désactivé insère toujours ~0,1 s.",
    "web.sound.volnorm": "Normaliser le volume",
    "web.sound.volnorm_note": "Égalise le niveau sonore entre les pistes via les tags ReplayGain. Utile en lecture aléatoire entre albums.",
    "web.sound.oversampling": "Suréchantillonnage",
    "web.sound.oversampling_note": "Forme du filtre de reconstruction du DAC. Précision = coupure plus nette (plus fidèle). Normal = plus douce (plus suave pour certains).",
    "web.val.precision": "précision",
    "web.val.normal": "normal",
    "web.playback.title": "Lecture",
    "web.playback.volume": "Volume",
    "web.playback.volume_note": "Le HAP-Z1ES n'a pas d'ampli interne — le volume est fixe (géré par votre préampli / ampli externe).",
    "web.playback.sleep": "Minuterie de veille",
    "web.playback.sleep_note": "Éteint le HAP après la durée choisie. Pratique pour s'endormir en musique.",
    "web.minutes": "{n} min",
    "web.current.title": "Piste en cours",
    "web.current.favorite": "Favori",
    "web.current.favorite_note": "Marque la piste en cours dans la bibliothèque du HAP. Les boutons se désactivent pour une source non-disque (Spotify, radio).",
    "web.fav.title.favorite": "Marquer comme favori",
    "web.fav.title.clear": "Retirer favori / rejet",
    "web.fav.title.dislike": "Marquer comme rejeté",
    "web.fav.hdd": "Agit sur la piste en cours dans la bibliothèque du HAP.",
    "web.fav.nonhdd": "Les favoris ne fonctionnent que sur les pistes du disque (source actuelle : {src}).",
    "web.vol.no_amp": "Le HAP-Z1ES n'a pas d'ampli interne — le volume est fixe (utilisez un ampli / préampli externe).",
    "web.vol.amp": "Sortie HAP-S1 / ampli. Pas : {step}.",
    "web.tbl.dsee": "DSEE",
    "web.tbl.dsd": "Remastérisation DSD",
    "web.tbl.gapless": "Lecture sans blanc",
    "web.tbl.volnorm": "Normalisation du volume",
    "web.tbl.oversampling": "Suréchantillonnage",
    "web.err.unreachable": "HAP injoignable : {msg}",
    "web.err.action": "Échec de l'action : {msg}",
    "gui.window_title": "HAP Sync — HAP-Revival",
    "gui.tab.transfer": "Transfert",
    "gui.tab.validate": "Vérifier",
    "gui.tab.compare": "Comparer la bibliothèque",
    "gui.conn.ip": "IP du HAP",
    "gui.conn.mac": "MAC",
    "gui.conn.autodetect": "Détection auto",
    "gui.conn.check": "Tester",
    "gui.conn.wake": "Réveiller",
    "gui.conn.save": "Enregistrer",
    "gui.conn.detecting": "Recherche du HAP sur le réseau…",
    "gui.conn.detected": "HAP trouvé à {ip} ({mac})",
    "gui.conn.not_found": "Aucun HAP trouvé sur ce sous-réseau.",
    "gui.conn.saved": "Configuration enregistrée.",
    "gui.xfer.internal": "Disque interne (HAP_Internal)",
    "gui.xfer.external": "Clé USB (HAP_External)",
    "gui.xfer.pick_folder": "Choisir un dossier…",
    "gui.xfer.analyze": "Analyser (à blanc)",
    "gui.xfer.sync": "Synchroniser",
    "gui.xfer.cancel": "Annuler",
    "gui.xfer.idle": "Prêt.",
    "gui.xfer.scanning": "Analyse…",
    "gui.xfer.transferring": "Transfert {done}/{total}…",
    "gui.xfer.done": "Terminé — {n} fichiers transférés.",
    "gui.xfer.nothing": "Rien à transférer ; tout est à jour.",
    "gui.val.title": "Vérifiez un dossier avant de l'envoyer au HAP.",
    "gui.val.run": "Vérifier le dossier",
    "gui.val.junk": "Fichiers parasites (ignorés)",
    "gui.val.unsupported": "Formats non pris en charge (ignorés)",
    "gui.val.over_ceiling": "Au-dessus du plafond 192 kHz",
    "gui.val.missing_cover": "Albums sans pochette",
    "gui.val.ok": "Propre — rien qui poserait problème au HAP.",
    "gui.status.ready": "Prêt.",
    "gui.status.working": "Traitement…",
    "gui.status.no_pysmb": "pysmb n'est pas installé — lancez : pip install pysmb",
    "gui.menu.language": "Langue",
    "gui.conn.fix": "Réparer l'accès",
    "gui.lbl.ip": "Adresse IP :",
    "gui.lbl.mac": "MAC :",
    "gui.folders_box": "Dossiers à synchroniser  (PC → HAP)",
    "gui.add_folder": "+ Ajouter un dossier",
    "gui.opt.new_only": "Ajouter seulement les nouveaux fichiers (ne pas écraser)",
    "gui.opt.unsupported": "Inclure les formats non pris en charge",
    "gui.opt.rescan": "Re-scanner le HAP (ignorer le cache)",
    "gui.btn.analyze": "Analyser",
    "gui.btn.sync": "Synchroniser",
    "gui.btn.stop": "Arrêter",
    "gui.btn.browse": "Parcourir…",
    "gui.btn.validate": "Vérifier",
    "gui.btn.compare": "Comparer",
    "gui.lbl.folder": "Dossier :",
    "gui.lbl.db": "Base du HAP (.db) :",
    "gui.lbl.local_folder": "Dossier local :",
    "gui.warn.enter_ip": "Saisissez l'adresse IP du HAP (ou cliquez Détection auto).",
    "gui.warn.add_folder": "Ajoutez au moins un dossier local à transférer.",
    "gui.warn.valid_folder": "Choisissez un dossier valide à vérifier.",
    "gui.warn.choose_db": "Choisissez le fichier .db de la bibliothèque du HAP.",
    "gui.warn.choose_local": "Choisissez un dossier local à comparer.",
    "gui.validate_help": (
        "Ce que ça fait : analyse un dossier PC avant l'envoi et signale les fichiers que le "
        "HAP refuserait ou qui encombreraient sa bibliothèque — parasites (Thumbs.db, "
        ".DS_Store, .ffs_tmp…) que le HAP indexe en pistes fantômes, formats non pris en "
        "charge, PCM au-dessus de 192 kHz (au-delà de la limite du HAP) et albums sans "
        "pochette.\n"
        "Quand l'utiliser : facultatif. La synchro ignore déjà d'elle-même les parasites et "
        "les formats non pris en charge ; c'est donc un simple rapport de contrôle — surtout "
        "utile pour repérer les fichiers >192 kHz et les pochettes manquantes, que la synchro "
        "ne corrige pas."
    ),
    "gui.diff_help": (
        "Ce que ça fait : compare une arborescence locale <Artiste>/<Album>/ à la base "
        "musicale du HAP et liste les albums NOUVEAUX vs déjà présents — par contenu (noms "
        "d'artiste + d'album), pas par nom de fichier ni date.\n"
        "Ce qu'il faut : le catalogue SQLite du HAP (.db), qu'on n'obtient qu'en lisant le "
        "disque interne du HAP — c'est donc un outil avancé/occasionnel. Au quotidien, "
        "utilisez la synchro : elle compare déjà aux fichiers réellement présents sur le "
        "partage et ne transfère que ce qui manque."
    ),
}

JA: dict[str, str] = {
    "common.on": "オン",
    "common.off": "オフ",
    "common.auto": "オート",
    "common.yes": "はい",
    "common.no": "いいえ",
    "common.language": "言語",
    "cli.np.streaming": "ストリーミング（{src}）",
    "cli.np.art": "アートワーク: {url}",
    "cli.sent.pause": "一時停止を送信しました",
    "cli.sent.resume": "再生を再開しました",
    "cli.sent.next": "次の曲を送信しました",
    "cli.sent.previous": "前の曲を送信しました",
    "cli.sent.seek": "{pos}秒へのシークを送信しました",
    "cli.sent.play_track": "トラック {id} を {uri} で再生中",
    "cli.sys.model": "モデル",
    "cli.sys.name": "名称",
    "cli.sys.product": "製品",
    "cli.sys.version": "バージョン",
    "cli.sys.gen": "世代",
    "cli.sys.mac": "MACアドレス",
    "cli.sys.lang": "言語",
    "cli.sys.power": "電源",
    "cli.snd.dsee": "DSEE",
    "cli.snd.dsd": "DSDリマスタリング",
    "cli.snd.gapless": "ギャップレス再生",
    "cli.snd.volnorm": "音量ノーマライズ",
    "cli.snd.oversampling": "オーバーサンプリング",
    "cli.sleep.status": "状態",
    "cli.sleep.remain": "残り",
    "cli.sleep.sleep": "スリープ",
    "cli.sleep.options": "選択肢",
    "cli.err.api": "APIエラー: {msg}",
    "cli.err.transport": "通信エラー: {msg}",
    "web.title": "HAP-Revival — コントロール",
    "web.connecting": "接続中…",
    "web.firmware": "ファームウェア",
    "web.footer.polls": "3秒ごとに更新",
    "web.footer.stdlib": "標準ライブラリのみ",
    "web.np.streaming": "ストリーミング · {src}",
    "web.state.PLAYING": "再生中",
    "web.state.PAUSED": "一時停止",
    "web.state.PAUSED_PLAYBACK": "一時停止",
    "web.state.STOPPED": "停止",
    "web.state.NO_MEDIA_PRESENT": "メディアなし",
    "web.ctrl.previous": "前へ",
    "web.ctrl.play": "一時停止 / 再生",
    "web.ctrl.next": "次へ",
    "web.ctrl.standby": "スタンバイ",
    "web.seek_hint": "クリックでシーク",
    "web.confirm_standby": "HAPをスタンバイにしますか？",
    "web.power.active": "オン",
    "web.power.standby": "スタンバイ",
    "web.bg.title": "背景",
    "web.bg.ambient": "アンビエント（ジャケット）",
    "web.bg.cover_solid": "単色（ジャケットから）",
    "web.bg.dark": "ダーク",
    "web.bg.custom": "カスタム",
    "web.bg.current": "現在:",
    "web.lang.title": "言語",
    "web.display.title": "表示",
    "web.display.minimal": "ミニマルモード",
    "web.display.minimal_note": "ヘッダー（タイトルと機器情報）とフッターを隠します。再生カードと歯車は残ります。",
    "web.sound.title": "サウンド",
    "web.sound.dsee": "DSEE",
    "web.sound.dsee_note": "ソニーのアップスケーラー。オートはMP3/AACで失われた高域を補完しようとします。オフはビットパーフェクトを維持します。",
    "web.sound.dsd": "DSDリマスタリング",
    "web.sound.dsd_note": "DACの前でPCM（FLAC/WAV）をDSDに変換します。より滑らかに感じる人もいます。オフはファイル本来の形式を保ちます。",
    "web.sound.gapless": "ギャップレス",
    "web.sound.gapless_note": "連続する曲間の無音を除きます。オートはアルバム情報に従い、オフは常に約0.1秒挿入します。",
    "web.sound.volnorm": "音量ノーマライズ",
    "web.sound.volnorm_note": "ReplayGainタグで曲間の音量を均します。アルバムをまたぐシャッフル再生に便利です。",
    "web.sound.oversampling": "オーバーサンプリング",
    "web.sound.oversampling_note": "DAC再構成フィルターの形。プレシジョン＝急峻（より正確）。ノーマル＝緩やか（人によっては滑らか）。",
    "web.val.precision": "プレシジョン",
    "web.val.normal": "ノーマル",
    "web.playback.title": "再生",
    "web.playback.volume": "音量",
    "web.playback.volume_note": "HAP-Z1ESに内蔵アンプはありません。音量は固定です（プリ／外部アンプで制御）。",
    "web.playback.sleep": "スリープタイマー",
    "web.playback.sleep_note": "選んだ時間が経つとHAPをオフにします。音楽を聴きながら眠るのに便利です。",
    "web.minutes": "{n}分",
    "web.current.title": "再生中のトラック",
    "web.current.favorite": "お気に入り",
    "web.current.favorite_note": "HAPライブラリの現在の曲に印を付けます。HDD以外（Spotify、ラジオ）の再生中はボタンが無効になります。",
    "web.fav.title.favorite": "お気に入りに登録",
    "web.fav.title.clear": "お気に入り／嫌いを解除",
    "web.fav.title.dislike": "嫌いに登録",
    "web.fav.hdd": "HAPライブラリの現在の曲に作用します。",
    "web.fav.nonhdd": "お気に入りはHDDの曲のみ有効です（現在のソース: {src}）。",
    "web.vol.no_amp": "HAP-Z1ESに内蔵アンプはありません。音量は固定です（外部アンプ／プリアンプを使用）。",
    "web.vol.amp": "HAP-S1／アンプ出力。ステップ: {step}。",
    "web.tbl.dsee": "DSEE",
    "web.tbl.dsd": "DSDリマスタリング",
    "web.tbl.gapless": "ギャップレス再生",
    "web.tbl.volnorm": "音量ノーマライズ",
    "web.tbl.oversampling": "オーバーサンプリング",
    "web.err.unreachable": "HAPに接続できません: {msg}",
    "web.err.action": "操作に失敗しました: {msg}",
    "gui.window_title": "HAP Sync — HAP-Revival",
    "gui.tab.transfer": "転送",
    "gui.tab.validate": "チェック",
    "gui.tab.compare": "ライブラリ比較",
    "gui.conn.ip": "HAPのIP",
    "gui.conn.mac": "MAC",
    "gui.conn.autodetect": "自動検出",
    "gui.conn.check": "テスト",
    "gui.conn.wake": "起動",
    "gui.conn.save": "設定を保存",
    "gui.conn.detecting": "ネットワークでHAPを探索中…",
    "gui.conn.detected": "HAPを {ip}（{mac}）で発見",
    "gui.conn.not_found": "このサブネットにHAPが見つかりません。",
    "gui.conn.saved": "設定を保存しました。",
    "gui.xfer.internal": "内蔵ディスク（HAP_Internal）",
    "gui.xfer.external": "USBドライブ（HAP_External）",
    "gui.xfer.pick_folder": "フォルダーを選択…",
    "gui.xfer.analyze": "解析（ドライラン）",
    "gui.xfer.sync": "同期",
    "gui.xfer.cancel": "キャンセル",
    "gui.xfer.idle": "準備完了。",
    "gui.xfer.scanning": "走査中…",
    "gui.xfer.transferring": "転送中 {done}/{total}…",
    "gui.xfer.done": "完了 — {n} ファイルを転送しました。",
    "gui.xfer.nothing": "転送するものはありません。すべて最新です。",
    "gui.val.title": "HAPへ送る前にフォルダーを事前チェックします。",
    "gui.val.run": "フォルダーをチェック",
    "gui.val.junk": "不要ファイル（スキップ）",
    "gui.val.unsupported": "非対応フォーマット（スキップ）",
    "gui.val.over_ceiling": "192kHz上限超過",
    "gui.val.missing_cover": "ジャケットのないアルバム",
    "gui.val.ok": "クリーンです — HAPが詰まる要素はありません。",
    "gui.status.ready": "準備完了。",
    "gui.status.working": "処理中…",
    "gui.status.no_pysmb": "pysmbがインストールされていません — 実行: pip install pysmb",
    "gui.menu.language": "言語",
    "gui.conn.fix": "アクセスを修復",
    "gui.lbl.ip": "IPアドレス:",
    "gui.lbl.mac": "MAC:",
    "gui.folders_box": "同期するフォルダー  (PC → HAP)",
    "gui.add_folder": "+ フォルダーを追加",
    "gui.opt.new_only": "新しいファイルのみ追加（既存を上書きしない）",
    "gui.opt.unsupported": "非対応フォーマットも含める",
    "gui.opt.rescan": "HAPを再スキャン（キャッシュを無視）",
    "gui.btn.analyze": "解析",
    "gui.btn.sync": "同期",
    "gui.btn.stop": "停止",
    "gui.btn.browse": "参照…",
    "gui.btn.validate": "チェック",
    "gui.btn.compare": "比較",
    "gui.lbl.folder": "フォルダー:",
    "gui.lbl.db": "HAPデータベース (.db):",
    "gui.lbl.local_folder": "ローカルフォルダー:",
    "gui.warn.enter_ip": "HAPのIPアドレスを入力してください（または自動検出をクリック）。",
    "gui.warn.add_folder": "転送するローカルフォルダーを少なくとも1つ追加してください。",
    "gui.warn.valid_folder": "チェックする有効なフォルダーを選んでください。",
    "gui.warn.choose_db": "HAPライブラリの .db ファイルを選んでください。",
    "gui.warn.choose_local": "比較するローカルフォルダーを選んでください。",
}

DE: dict[str, str] = {
    "common.on": "ein",
    "common.off": "aus",
    "common.auto": "auto",
    "common.yes": "ja",
    "common.no": "nein",
    "common.language": "Sprache",
    "cli.np.streaming": "Streaming ({src})",
    "cli.np.art": "Cover: {url}",
    "cli.sent.pause": "Pause gesendet",
    "cli.sent.resume": "Wiedergabe fortgesetzt",
    "cli.sent.next": "Nächster Titel gesendet",
    "cli.sent.previous": "Vorheriger Titel gesendet",
    "cli.sent.seek": "Sprung zu {pos}s gesendet",
    "cli.sent.play_track": "Spiele Titel {id} auf {uri}",
    "cli.sys.model": "Modell",
    "cli.sys.name": "Name",
    "cli.sys.product": "Produkt",
    "cli.sys.version": "Version",
    "cli.sys.gen": "Generation",
    "cli.sys.mac": "MAC-Adresse",
    "cli.sys.lang": "Sprache",
    "cli.sys.power": "Stromzustand",
    "cli.snd.dsee": "DSEE",
    "cli.snd.dsd": "DSD-Remastering",
    "cli.snd.gapless": "Lückenlose Wiedergabe",
    "cli.snd.volnorm": "Lautstärke-Normalisierung",
    "cli.snd.oversampling": "Oversampling",
    "cli.sleep.status": "Status",
    "cli.sleep.remain": "Restzeit",
    "cli.sleep.sleep": "Timer",
    "cli.sleep.options": "Optionen",
    "cli.err.api": "API-Fehler: {msg}",
    "cli.err.transport": "Übertragungsfehler: {msg}",
    "web.title": "HAP-Revival — Steuerung",
    "web.connecting": "Verbinde…",
    "web.firmware": "Firmware",
    "web.footer.polls": "alle 3 s abgefragt",
    "web.footer.stdlib": "nur Standardbibliothek",
    "web.np.streaming": "Streaming · {src}",
    "web.state.PLAYING": "Wiedergabe",
    "web.state.PAUSED": "Pausiert",
    "web.state.PAUSED_PLAYBACK": "Pausiert",
    "web.state.STOPPED": "Gestoppt",
    "web.state.NO_MEDIA_PRESENT": "Kein Medium",
    "web.ctrl.previous": "Zurück",
    "web.ctrl.play": "Pause / Wiedergabe",
    "web.ctrl.next": "Weiter",
    "web.ctrl.standby": "Standby",
    "web.seek_hint": "Zum Spulen klicken",
    "web.confirm_standby": "HAP in Standby versetzen?",
    "web.power.active": "ein",
    "web.power.standby": "Standby",
    "web.bg.title": "Hintergrund",
    "web.bg.ambient": "Ambiente (Cover)",
    "web.bg.cover_solid": "Einfarbig (aus Cover)",
    "web.bg.dark": "Dunkel",
    "web.bg.custom": "Benutzerdefiniert",
    "web.bg.current": "aktuell:",
    "web.lang.title": "Sprache",
    "web.display.title": "Anzeige",
    "web.display.minimal": "Minimalmodus",
    "web.display.minimal_note": "Blendet die Kopfzeile (Titel + Geräteinfo) und die Fußzeile aus. Die Wiedergabekarte und das Zahnrad bleiben.",
    "web.sound.title": "Klang",
    "web.sound.dsee": "DSEE",
    "web.sound.dsee_note": "Sonys Upscaler. Auto versucht, in MP3/AAC verlorene Höhen zu rekonstruieren. Aus hält das Signal bitgenau.",
    "web.sound.dsd": "DSD-Remastering",
    "web.sound.dsd_note": "Wandelt PCM (FLAC/WAV) vor dem DAC in DSD um. Manche empfinden es als weicher; aus behält das native Format.",
    "web.sound.gapless": "Lückenlos",
    "web.sound.gapless_note": "Entfernt die Stille zwischen aufeinanderfolgenden Titeln. Auto folgt den Album-Metadaten; aus fügt immer ~0,1 s ein.",
    "web.sound.volnorm": "Lautstärke angleichen",
    "web.sound.volnorm_note": "Gleicht die Lautstärke zwischen Titeln über ReplayGain-Tags an. Nützlich bei albumübergreifender Zufallswiedergabe.",
    "web.sound.oversampling": "Oversampling",
    "web.sound.oversampling_note": "Form des DAC-Rekonstruktionsfilters. Präzision = steilerer Abfall (genauer). Normal = sanfter (für manche weicher).",
    "web.val.precision": "Präzision",
    "web.val.normal": "Normal",
    "web.playback.title": "Wiedergabe",
    "web.playback.volume": "Lautstärke",
    "web.playback.volume_note": "Der HAP-Z1ES hat keinen internen Verstärker — die Lautstärke ist fest (über Vorverstärker / externen Verstärker geregelt).",
    "web.playback.sleep": "Sleep-Timer",
    "web.playback.sleep_note": "Schaltet den HAP nach der gewählten Dauer aus. Praktisch zum Einschlafen mit Musik.",
    "web.minutes": "{n} Min.",
    "web.current.title": "Aktueller Titel",
    "web.current.favorite": "Favorit",
    "web.current.favorite_note": "Markiert den aktuellen Titel in der HAP-Bibliothek. Bei Nicht-HDD-Quellen (Spotify, Radio) sind die Tasten deaktiviert.",
    "web.fav.title.favorite": "Als Favorit markieren",
    "web.fav.title.clear": "Favorit / Abneigung löschen",
    "web.fav.title.dislike": "Als Abneigung markieren",
    "web.fav.hdd": "Wirkt auf den aktuellen Titel in der HAP-Bibliothek.",
    "web.fav.nonhdd": "Favoriten funktionieren nur bei HDD-Titeln (aktuelle Quelle: {src}).",
    "web.vol.no_amp": "Der HAP-Z1ES hat keinen internen Verstärker — die Lautstärke ist fest (externen Verstärker / Vorverstärker verwenden).",
    "web.vol.amp": "HAP-S1 / Verstärker-Ausgang. Schritt: {step}.",
    "web.tbl.dsee": "DSEE",
    "web.tbl.dsd": "DSD-Remastering",
    "web.tbl.gapless": "Lückenlose Wiedergabe",
    "web.tbl.volnorm": "Lautstärke-Normalisierung",
    "web.tbl.oversampling": "Oversampling",
    "web.err.unreachable": "HAP nicht erreichbar: {msg}",
    "web.err.action": "Aktion fehlgeschlagen: {msg}",
    "gui.window_title": "HAP Sync — HAP-Revival",
    "gui.tab.transfer": "Übertragung",
    "gui.tab.validate": "Prüfen",
    "gui.tab.compare": "Bibliothek vergleichen",
    "gui.conn.ip": "HAP-IP",
    "gui.conn.mac": "MAC",
    "gui.conn.autodetect": "Auto-Erkennung",
    "gui.conn.check": "Testen",
    "gui.conn.wake": "Aufwecken",
    "gui.conn.save": "Speichern",
    "gui.conn.detecting": "Suche den HAP im Netzwerk…",
    "gui.conn.detected": "HAP gefunden unter {ip} ({mac})",
    "gui.conn.not_found": "Kein HAP in diesem Subnetz gefunden.",
    "gui.conn.saved": "Konfiguration gespeichert.",
    "gui.xfer.internal": "Interne Platte (HAP_Internal)",
    "gui.xfer.external": "USB-Laufwerk (HAP_External)",
    "gui.xfer.pick_folder": "Ordner wählen…",
    "gui.xfer.analyze": "Analysieren (Probelauf)",
    "gui.xfer.sync": "Synchronisieren",
    "gui.xfer.cancel": "Abbrechen",
    "gui.xfer.idle": "Bereit.",
    "gui.xfer.scanning": "Durchsuche…",
    "gui.xfer.transferring": "Übertrage {done}/{total}…",
    "gui.xfer.done": "Fertig — {n} Dateien übertragen.",
    "gui.xfer.nothing": "Nichts zu übertragen; alles ist aktuell.",
    "gui.val.title": "Einen Ordner vor dem Senden an den HAP vorab prüfen.",
    "gui.val.run": "Ordner prüfen",
    "gui.val.junk": "Müll-Dateien (übersprungen)",
    "gui.val.unsupported": "Nicht unterstützte Formate (übersprungen)",
    "gui.val.over_ceiling": "Über der 192-kHz-Grenze",
    "gui.val.missing_cover": "Alben ohne Cover",
    "gui.val.ok": "Sauber — nichts, woran der HAP scheitern würde.",
    "gui.status.ready": "Bereit.",
    "gui.status.working": "Arbeite…",
    "gui.status.no_pysmb": "pysmb ist nicht installiert — ausführen: pip install pysmb",
    "gui.menu.language": "Sprache",
    "gui.conn.fix": "Zugriff reparieren",
    "gui.lbl.ip": "IP-Adresse:",
    "gui.lbl.mac": "MAC:",
    "gui.folders_box": "Zu synchronisierende Ordner  (PC → HAP)",
    "gui.add_folder": "+ Ordner hinzufügen",
    "gui.opt.new_only": "Nur neue Dateien hinzufügen (vorhandene nicht überschreiben)",
    "gui.opt.unsupported": "Nicht unterstützte Formate einbeziehen",
    "gui.opt.rescan": "HAP neu scannen (Cache ignorieren)",
    "gui.btn.analyze": "Analysieren",
    "gui.btn.sync": "Synchronisieren",
    "gui.btn.stop": "Stopp",
    "gui.btn.browse": "Durchsuchen…",
    "gui.btn.validate": "Prüfen",
    "gui.btn.compare": "Vergleichen",
    "gui.lbl.folder": "Ordner:",
    "gui.lbl.db": "HAP-Datenbank (.db):",
    "gui.lbl.local_folder": "Lokaler Ordner:",
    "gui.warn.enter_ip": "Geben Sie die IP-Adresse des HAP ein (oder klicken Sie auf Auto-Erkennung).",
    "gui.warn.add_folder": "Fügen Sie mindestens einen lokalen Ordner zum Übertragen hinzu.",
    "gui.warn.valid_folder": "Wählen Sie einen gültigen Ordner zum Prüfen.",
    "gui.warn.choose_db": "Wählen Sie die .db-Datei der HAP-Bibliothek.",
    "gui.warn.choose_local": "Wählen Sie einen lokalen Ordner zum Vergleichen.",
}

ES: dict[str, str] = {
    "common.on": "activado",
    "common.off": "desactivado",
    "common.auto": "auto",
    "common.yes": "sí",
    "common.no": "no",
    "common.language": "Idioma",
    "cli.np.streaming": "transmisión ({src})",
    "cli.np.art": "carátula: {url}",
    "cli.sent.pause": "pausa enviada",
    "cli.sent.resume": "reproducción reanudada",
    "cli.sent.next": "siguiente pista enviada",
    "cli.sent.previous": "pista anterior enviada",
    "cli.sent.seek": "salto a {pos}s enviado",
    "cli.sent.play_track": "reproduciendo la pista {id} en {uri}",
    "cli.sys.model": "modelo",
    "cli.sys.name": "nombre",
    "cli.sys.product": "producto",
    "cli.sys.version": "versión",
    "cli.sys.gen": "generación",
    "cli.sys.mac": "dirección MAC",
    "cli.sys.lang": "idioma",
    "cli.sys.power": "alimentación",
    "cli.snd.dsee": "DSEE",
    "cli.snd.dsd": "Remasterización DSD",
    "cli.snd.gapless": "Reproducción sin pausas",
    "cli.snd.volnorm": "Normalización de volumen",
    "cli.snd.oversampling": "Sobremuestreo",
    "cli.sleep.status": "estado",
    "cli.sleep.remain": "restante",
    "cli.sleep.sleep": "temporizador",
    "cli.sleep.options": "opciones",
    "cli.err.api": "Error de API: {msg}",
    "cli.err.transport": "Error de transporte: {msg}",
    "web.title": "HAP-Revival — control",
    "web.connecting": "conectando…",
    "web.firmware": "firmware",
    "web.footer.polls": "sondea cada 3 s",
    "web.footer.stdlib": "solo biblioteca estándar",
    "web.np.streaming": "transmisión · {src}",
    "web.state.PLAYING": "reproduciendo",
    "web.state.PAUSED": "en pausa",
    "web.state.PAUSED_PLAYBACK": "en pausa",
    "web.state.STOPPED": "detenido",
    "web.state.NO_MEDIA_PRESENT": "sin medio",
    "web.ctrl.previous": "Anterior",
    "web.ctrl.play": "Pausa / reanudar",
    "web.ctrl.next": "Siguiente",
    "web.ctrl.standby": "Reposo",
    "web.seek_hint": "Clic para avanzar",
    "web.confirm_standby": "¿Poner el HAP en reposo?",
    "web.power.active": "encendido",
    "web.power.standby": "reposo",
    "web.bg.title": "Fondo",
    "web.bg.ambient": "Carátula ambiente",
    "web.bg.cover_solid": "Sólido (de la carátula)",
    "web.bg.dark": "Oscuro",
    "web.bg.custom": "Personalizado",
    "web.bg.current": "actual:",
    "web.lang.title": "Idioma",
    "web.display.title": "Pantalla",
    "web.display.minimal": "Modo mínimo",
    "web.display.minimal_note": "Oculta el encabezado (título + info del equipo) y el pie. La tarjeta de reproducción y el engranaje permanecen.",
    "web.sound.title": "Sonido",
    "web.sound.dsee": "DSEE",
    "web.sound.dsee_note": "El escalador de Sony. Auto intenta reconstruir los agudos perdidos en MP3/AAC. Desactivado mantiene la señal bit-perfect.",
    "web.sound.dsd": "Remasterización DSD",
    "web.sound.dsd_note": "Convierte PCM (FLAC/WAV) a DSD antes del DAC. Algunos lo oyen más suave; desactivado conserva el formato nativo.",
    "web.sound.gapless": "Sin pausas",
    "web.sound.gapless_note": "Quita el silencio entre pistas consecutivas. Auto sigue los metadatos del álbum; desactivado inserta siempre ~0,1 s.",
    "web.sound.volnorm": "Normalizar volumen",
    "web.sound.volnorm_note": "Iguala el volumen entre pistas con etiquetas ReplayGain. Útil en reproducción aleatoria entre álbumes.",
    "web.sound.oversampling": "Sobremuestreo",
    "web.sound.oversampling_note": "Forma del filtro de reconstrucción del DAC. Precisión = corte más nítido (más exacto). Normal = más suave (más dulce para algunos).",
    "web.val.precision": "precisión",
    "web.val.normal": "normal",
    "web.playback.title": "Reproducción",
    "web.playback.volume": "Volumen",
    "web.playback.volume_note": "El HAP-Z1ES no tiene amplificador interno — el volumen es fijo (lo controla tu preamplificador / amplificador externo).",
    "web.playback.sleep": "Temporizador de apagado",
    "web.playback.sleep_note": "Apaga el HAP tras la duración elegida. Útil para dormirse con música.",
    "web.minutes": "{n} min",
    "web.current.title": "Pista actual",
    "web.current.favorite": "Favorito",
    "web.current.favorite_note": "Marca la pista actual en la biblioteca del HAP. Los botones se desactivan con fuentes que no son del disco (Spotify, radio).",
    "web.fav.title.favorite": "Marcar como favorito",
    "web.fav.title.clear": "Quitar favorito / no me gusta",
    "web.fav.title.dislike": "Marcar como no me gusta",
    "web.fav.hdd": "Actúa sobre la pista actual en la biblioteca del HAP.",
    "web.fav.nonhdd": "Los favoritos solo funcionan en pistas del disco (fuente actual: {src}).",
    "web.vol.no_amp": "El HAP-Z1ES no tiene amplificador interno — el volumen es fijo (usa amplificador / preamplificador externo).",
    "web.vol.amp": "Salida HAP-S1 / amplificador. Paso: {step}.",
    "web.tbl.dsee": "DSEE",
    "web.tbl.dsd": "Remasterización DSD",
    "web.tbl.gapless": "Reproducción sin pausas",
    "web.tbl.volnorm": "Normalización de volumen",
    "web.tbl.oversampling": "Sobremuestreo",
    "web.err.unreachable": "No se puede contactar con el HAP: {msg}",
    "web.err.action": "Acción fallida: {msg}",
    "gui.window_title": "HAP Sync — HAP-Revival",
    "gui.tab.transfer": "Transferencia",
    "gui.tab.validate": "Validar",
    "gui.tab.compare": "Comparar biblioteca",
    "gui.conn.ip": "IP del HAP",
    "gui.conn.mac": "MAC",
    "gui.conn.autodetect": "Detección automática",
    "gui.conn.check": "Probar",
    "gui.conn.wake": "Despertar",
    "gui.conn.save": "Guardar",
    "gui.conn.detecting": "Buscando el HAP en la red…",
    "gui.conn.detected": "HAP encontrado en {ip} ({mac})",
    "gui.conn.not_found": "No se encontró ningún HAP en esta subred.",
    "gui.conn.saved": "Configuración guardada.",
    "gui.xfer.internal": "Disco interno (HAP_Internal)",
    "gui.xfer.external": "Unidad USB (HAP_External)",
    "gui.xfer.pick_folder": "Elegir carpeta…",
    "gui.xfer.analyze": "Analizar (en seco)",
    "gui.xfer.sync": "Sincronizar",
    "gui.xfer.cancel": "Cancelar",
    "gui.xfer.idle": "Listo.",
    "gui.xfer.scanning": "Analizando…",
    "gui.xfer.transferring": "Transfiriendo {done}/{total}…",
    "gui.xfer.done": "Hecho — {n} archivos transferidos.",
    "gui.xfer.nothing": "Nada que transferir; todo está al día.",
    "gui.val.title": "Comprueba una carpeta antes de enviarla al HAP.",
    "gui.val.run": "Validar carpeta",
    "gui.val.junk": "Archivos basura (omitidos)",
    "gui.val.unsupported": "Formatos no compatibles (omitidos)",
    "gui.val.over_ceiling": "Por encima del límite de 192 kHz",
    "gui.val.missing_cover": "Álbumes sin carátula",
    "gui.val.ok": "Limpio — nada que atasque al HAP.",
    "gui.status.ready": "Listo.",
    "gui.status.working": "Trabajando…",
    "gui.status.no_pysmb": "pysmb no está instalado — ejecuta: pip install pysmb",
    "gui.menu.language": "Idioma",
    "gui.conn.fix": "Reparar acceso",
    "gui.lbl.ip": "Dirección IP:",
    "gui.lbl.mac": "MAC:",
    "gui.folders_box": "Carpetas a sincronizar  (PC → HAP)",
    "gui.add_folder": "+ Añadir una carpeta",
    "gui.opt.new_only": "Añadir solo archivos nuevos (no sobrescribir)",
    "gui.opt.unsupported": "Incluir formatos no compatibles",
    "gui.opt.rescan": "Reescanear el HAP (ignorar caché)",
    "gui.btn.analyze": "Analizar",
    "gui.btn.sync": "Sincronizar",
    "gui.btn.stop": "Detener",
    "gui.btn.browse": "Examinar…",
    "gui.btn.validate": "Validar",
    "gui.btn.compare": "Comparar",
    "gui.lbl.folder": "Carpeta:",
    "gui.lbl.db": "Base de datos del HAP (.db):",
    "gui.lbl.local_folder": "Carpeta local:",
    "gui.warn.enter_ip": "Introduce la dirección IP del HAP (o pulsa Detección automática).",
    "gui.warn.add_folder": "Añade al menos una carpeta local para transferir.",
    "gui.warn.valid_folder": "Elige una carpeta válida para validar.",
    "gui.warn.choose_db": "Elige el archivo .db de la biblioteca del HAP.",
    "gui.warn.choose_local": "Elige una carpeta local para comparar.",
}

IT: dict[str, str] = {
    "common.on": "attivo",
    "common.off": "disattivo",
    "common.auto": "auto",
    "common.yes": "sì",
    "common.no": "no",
    "common.language": "Lingua",
    "cli.np.streaming": "streaming ({src})",
    "cli.np.art": "copertina: {url}",
    "cli.sent.pause": "pausa inviata",
    "cli.sent.resume": "riproduzione ripresa",
    "cli.sent.next": "brano successivo inviato",
    "cli.sent.previous": "brano precedente inviato",
    "cli.sent.seek": "salto a {pos}s inviato",
    "cli.sent.play_track": "riproduco il brano {id} su {uri}",
    "cli.sys.model": "modello",
    "cli.sys.name": "nome",
    "cli.sys.product": "prodotto",
    "cli.sys.version": "versione",
    "cli.sys.gen": "generazione",
    "cli.sys.mac": "indirizzo MAC",
    "cli.sys.lang": "lingua",
    "cli.sys.power": "alimentazione",
    "cli.snd.dsee": "DSEE",
    "cli.snd.dsd": "Rimasterizzazione DSD",
    "cli.snd.gapless": "Riproduzione senza pause",
    "cli.snd.volnorm": "Normalizzazione volume",
    "cli.snd.oversampling": "Sovracampionamento",
    "cli.sleep.status": "stato",
    "cli.sleep.remain": "rimanente",
    "cli.sleep.sleep": "timer",
    "cli.sleep.options": "opzioni",
    "cli.err.api": "Errore API: {msg}",
    "cli.err.transport": "Errore di trasporto: {msg}",
    "web.title": "HAP-Revival — comando",
    "web.connecting": "connessione…",
    "web.firmware": "firmware",
    "web.footer.polls": "interroga ogni 3 s",
    "web.footer.stdlib": "solo libreria standard",
    "web.np.streaming": "streaming · {src}",
    "web.state.PLAYING": "in riproduzione",
    "web.state.PAUSED": "in pausa",
    "web.state.PAUSED_PLAYBACK": "in pausa",
    "web.state.STOPPED": "fermo",
    "web.state.NO_MEDIA_PRESENT": "nessun supporto",
    "web.ctrl.previous": "Precedente",
    "web.ctrl.play": "Pausa / riprendi",
    "web.ctrl.next": "Successivo",
    "web.ctrl.standby": "Standby",
    "web.seek_hint": "Clic per scorrere",
    "web.confirm_standby": "Mettere il HAP in standby?",
    "web.power.active": "acceso",
    "web.power.standby": "standby",
    "web.bg.title": "Sfondo",
    "web.bg.ambient": "Copertina ambientale",
    "web.bg.cover_solid": "Tinta unita (dalla copertina)",
    "web.bg.dark": "Scuro",
    "web.bg.custom": "Personalizzato",
    "web.bg.current": "attuale:",
    "web.lang.title": "Lingua",
    "web.display.title": "Visualizzazione",
    "web.display.minimal": "Modalità minimale",
    "web.display.minimal_note": "Nasconde l'intestazione (titolo + info dispositivo) e il piè di pagina. La scheda di riproduzione e l'ingranaggio restano.",
    "web.sound.title": "Audio",
    "web.sound.dsee": "DSEE",
    "web.sound.dsee_note": "L'upscaler di Sony. Auto prova a ricostruire le alte frequenze perse in MP3/AAC. Off mantiene il segnale bit-perfect.",
    "web.sound.dsd": "Rimasterizzazione DSD",
    "web.sound.dsd_note": "Converte il PCM (FLAC/WAV) in DSD prima del DAC. Alcuni lo trovano più morbido; off mantiene il formato nativo.",
    "web.sound.gapless": "Senza pause",
    "web.sound.gapless_note": "Rimuove il silenzio tra brani consecutivi. Auto segue i metadati dell'album; off inserisce sempre ~0,1 s.",
    "web.sound.volnorm": "Normalizza volume",
    "web.sound.volnorm_note": "Uniforma il volume tra i brani usando i tag ReplayGain. Utile nella riproduzione casuale tra album.",
    "web.sound.oversampling": "Sovracampionamento",
    "web.sound.oversampling_note": "Forma del filtro di ricostruzione del DAC. Precisione = taglio più netto (più accurato). Normale = più morbido (per alcuni più dolce).",
    "web.val.precision": "precisione",
    "web.val.normal": "normale",
    "web.playback.title": "Riproduzione",
    "web.playback.volume": "Volume",
    "web.playback.volume_note": "L'HAP-Z1ES non ha un amplificatore interno — il volume è fisso (controllato dal pre / ampli esterno).",
    "web.playback.sleep": "Timer di spegnimento",
    "web.playback.sleep_note": "Spegne il HAP dopo la durata scelta. Comodo per addormentarsi con la musica.",
    "web.minutes": "{n} min",
    "web.current.title": "Brano corrente",
    "web.current.favorite": "Preferito",
    "web.current.favorite_note": "Segna il brano corrente nella libreria del HAP. I pulsanti si disattivano con sorgenti non su disco (Spotify, radio).",
    "web.fav.title.favorite": "Segna come preferito",
    "web.fav.title.clear": "Rimuovi preferito / non mi piace",
    "web.fav.title.dislike": "Segna come non mi piace",
    "web.fav.hdd": "Agisce sul brano corrente nella libreria del HAP.",
    "web.fav.nonhdd": "I preferiti funzionano solo sui brani su disco (sorgente attuale: {src}).",
    "web.vol.no_amp": "L'HAP-Z1ES non ha un amplificatore interno — il volume è fisso (usa un ampli / pre esterno).",
    "web.vol.amp": "Uscita HAP-S1 / ampli. Passo: {step}.",
    "web.tbl.dsee": "DSEE",
    "web.tbl.dsd": "Rimasterizzazione DSD",
    "web.tbl.gapless": "Riproduzione senza pause",
    "web.tbl.volnorm": "Normalizzazione volume",
    "web.tbl.oversampling": "Sovracampionamento",
    "web.err.unreachable": "HAP non raggiungibile: {msg}",
    "web.err.action": "Azione non riuscita: {msg}",
    "gui.window_title": "HAP Sync — HAP-Revival",
    "gui.tab.transfer": "Trasferimento",
    "gui.tab.validate": "Verifica",
    "gui.tab.compare": "Confronta libreria",
    "gui.conn.ip": "IP del HAP",
    "gui.conn.mac": "MAC",
    "gui.conn.autodetect": "Rilevamento automatico",
    "gui.conn.check": "Prova",
    "gui.conn.wake": "Risveglia",
    "gui.conn.save": "Salva",
    "gui.conn.detecting": "Ricerca del HAP sulla rete…",
    "gui.conn.detected": "HAP trovato su {ip} ({mac})",
    "gui.conn.not_found": "Nessun HAP trovato su questa sottorete.",
    "gui.conn.saved": "Configurazione salvata.",
    "gui.xfer.internal": "Disco interno (HAP_Internal)",
    "gui.xfer.external": "Unità USB (HAP_External)",
    "gui.xfer.pick_folder": "Scegli cartella…",
    "gui.xfer.analyze": "Analizza (simulazione)",
    "gui.xfer.sync": "Sincronizza",
    "gui.xfer.cancel": "Annulla",
    "gui.xfer.idle": "Pronto.",
    "gui.xfer.scanning": "Scansione…",
    "gui.xfer.transferring": "Trasferimento {done}/{total}…",
    "gui.xfer.done": "Fatto — {n} file trasferiti.",
    "gui.xfer.nothing": "Niente da trasferire; tutto aggiornato.",
    "gui.val.title": "Controlla una cartella prima di inviarla al HAP.",
    "gui.val.run": "Verifica cartella",
    "gui.val.junk": "File spazzatura (saltati)",
    "gui.val.unsupported": "Formati non supportati (saltati)",
    "gui.val.over_ceiling": "Oltre il limite di 192 kHz",
    "gui.val.missing_cover": "Album senza copertina",
    "gui.val.ok": "Pulito — niente che possa bloccare il HAP.",
    "gui.status.ready": "Pronto.",
    "gui.status.working": "Elaborazione…",
    "gui.status.no_pysmb": "pysmb non è installato — esegui: pip install pysmb",
    "gui.menu.language": "Lingua",
    "gui.conn.fix": "Ripara accesso",
    "gui.lbl.ip": "Indirizzo IP:",
    "gui.lbl.mac": "MAC:",
    "gui.folders_box": "Cartelle da sincronizzare  (PC → HAP)",
    "gui.add_folder": "+ Aggiungi una cartella",
    "gui.opt.new_only": "Aggiungi solo i file nuovi (non sovrascrivere)",
    "gui.opt.unsupported": "Includi i formati non supportati",
    "gui.opt.rescan": "Riscansiona il HAP (ignora la cache)",
    "gui.btn.analyze": "Analizza",
    "gui.btn.sync": "Sincronizza",
    "gui.btn.stop": "Ferma",
    "gui.btn.browse": "Sfoglia…",
    "gui.btn.validate": "Verifica",
    "gui.btn.compare": "Confronta",
    "gui.lbl.folder": "Cartella:",
    "gui.lbl.db": "Database del HAP (.db):",
    "gui.lbl.local_folder": "Cartella locale:",
    "gui.warn.enter_ip": "Inserisci l'indirizzo IP del HAP (o clicca Rilevamento automatico).",
    "gui.warn.add_folder": "Aggiungi almeno una cartella locale da trasferire.",
    "gui.warn.valid_folder": "Scegli una cartella valida da verificare.",
    "gui.warn.choose_db": "Scegli il file .db della libreria del HAP.",
    "gui.warn.choose_local": "Scegli una cartella locale da confrontare.",
}

CATALOGS: dict[str, dict[str, str]] = {
    "en": EN,
    "fr": FR,
    "ja": JA,
    "de": DE,
    "es": ES,
    "it": IT,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_lang(code: str | None) -> str | None:
    """Map a locale/code string to one of our supported language codes, or None.

    Accepts things like 'fr', 'fr_FR', 'fr-FR.UTF-8', 'JA', 'de_DE' — only the
    leading two-letter primary subtag is considered.
    """
    if not code:
        return None
    primary = code.replace("_", "-").split("-", 1)[0].strip().lower()
    return primary if primary in CATALOGS else None


def parse_accept_language(header: str | None) -> str | None:
    """Pick the best supported language from an HTTP Accept-Language header.

    Honors q-weights ('fr;q=0.9, en;q=0.8'); returns None if nothing matches.
    """
    if not header:
        return None
    best: tuple[float, str] | None = None
    for part in header.split(","):
        token = part.strip()
        if not token:
            continue
        q = 1.0
        if ";" in token:
            token, _, params = token.partition(";")
            for p in params.split(";"):
                p = p.strip()
                if p.startswith("q="):
                    try:
                        q = float(p[2:])
                    except ValueError:
                        q = 0.0
        lang = normalize_lang(token.strip())
        if lang and (best is None or q > best[0]):
            best = (q, lang)
    return best[1] if best else None


def _os_lang() -> str | None:
    """Best-effort OS locale → supported language, or None."""
    # Respect the standard env vars first (set on Linux/macOS, sometimes Windows).
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        lang = normalize_lang(os.environ.get(var, "").split(":", 1)[0])
        if lang:
            return lang
    try:
        loc = locale.getlocale()[0]
    except (ValueError, TypeError):
        loc = None
    if not loc:
        try:  # getdefaultlocale is deprecated (3.11+) but still the only
            # reliable read of the Windows UI language without ctypes.
            loc = locale.getdefaultlocale()[0]  # type: ignore[attr-defined]
        except (ValueError, AttributeError):
            loc = None
    return normalize_lang(loc)


def detect_lang(
    accept_language: str | None = None,
    override: str | None = None,
    use_os: bool = True,
) -> str:
    """Resolve the active language.

    Priority: explicit `override` (CLI flag / saved web choice / ?lang=) →
    `HAP_LANG` env var → HTTP `accept_language` → OS locale → DEFAULT_LANG.
    Always returns a supported code.
    """
    return (
        normalize_lang(override)
        or normalize_lang(os.environ.get("HAP_LANG"))
        or parse_accept_language(accept_language)
        or (_os_lang() if use_os else None)
        or DEFAULT_LANG
    )


def t(key: str, lang: str | None = None, **kwargs: object) -> str:
    """Translate `key` into `lang` (default: detected), formatting with kwargs.

    Lookup order for the string: active language → English → the key itself.
    `str.format` is applied with kwargs; a malformed placeholder degrades to the
    unformatted string rather than raising.
    """
    active = lang or detect_lang()
    catalog = CATALOGS.get(active, EN)
    template = catalog.get(key) or EN.get(key) or key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return template


def catalog_for(lang: str) -> dict[str, str]:
    """Return the *complete* catalog for `lang`, with English filling any gaps.

    This is what the web UI embeds (as JSON) so the browser can translate every
    key client-side and switch languages with zero server round-trips.
    """
    merged = dict(EN)
    merged.update(CATALOGS.get(lang, {}))
    return merged


def all_catalogs() -> dict[str, dict[str, str]]:
    """Every language's complete (English-backfilled) catalog, for embedding the
    whole set so the web language switch is instant and offline."""
    return {code: catalog_for(code) for code in CATALOGS}


def language_options() -> list[dict[str, str]]:
    """[{code, name}] in canonical order — for building a language <select>."""
    return [{"code": code, "name": name} for code, name in LANGUAGES.items()]


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------


def _main(argv: list[str]) -> int:
    if len(argv) >= 2:
        lang = normalize_lang(argv[0]) or DEFAULT_LANG
        key = argv[1]
        print(t(key, lang))
        return 0
    print(f"Detected language: {detect_lang()}")
    print("Supported:")
    for code, name in LANGUAGES.items():
        sample = t("web.sound.dsee_note", code)
        print(f"  {code}  {name:10s}  {sample[:60]}…")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
