import sys
import datetime
import requests
import traceback
import tempfile
import os
import threading
from datetime import timezone

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QProgressBar, QListWidget, QPlainTextEdit, QDateTimeEdit
)
from PyQt5.QtCore import (
    QTimer, QUrl, Qt, QDateTime, QObject, pyqtSignal, pyqtSlot
)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

import yt_dlp
import config

# ---- OpenAI v1 ----
try:
    from openai import OpenAI
    _OPENAI_V1 = True
except Exception:
    _OPENAI_V1 = False

# Twilio (optionnel)
try:
    from twilio.rest import Client
    TWILIO_OK = True
except ImportError:
    TWILIO_OK = False

# gTTS (fallback vocal)
try:
    from gtts import gTTS
    GTTS_OK = True
except ImportError:
    GTTS_OK = False

# Google Cloud TTS (premium)
try:
    from google.cloud import texttospeech as gctts
    # active si lib importée ET var d’env renseignée
    GCLOUD_TTS_OK = bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
except Exception:
    gctts = None
    GCLOUD_TTS_OK = False

# === Clés API ===
OPENAI_API_KEY = getattr(config, "OPENAI_API_KEY", None)
YOUTUBE_API_KEY = getattr(config, "YOUTUBE_API_KEY", None)

# ---------- Console thread-safe ----------
class ThreadSafeConsole(QObject):
    append_requested = pyqtSignal(str)
    def __init__(self, widget):
        super().__init__()
        self.widget = widget
        self.append_requested.connect(self._append_on_main)
    @pyqtSlot(str)
    def _append_on_main(self, text):
        self.widget.appendPlainText(text)

class EmittingStream:
    """redirige stdout/stderr vers la console Qt de manière thread-safe"""
    def __init__(self, ts_console: ThreadSafeConsole):
        self.ts_console = ts_console
    def write(self, text):
        if text and text.strip():
            timestamp = datetime.datetime.now().strftime("[%H:%M:%S] ")
            self.ts_console.append_requested.emit(timestamp + text.strip())
    def flush(self):
        pass
# ----------------------------------------

# === HUD principal ===
class TwilightHUD(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Twilight HUD - Multi Tools")
        self.resize(1100, 860)

        layout = QVBoxLayout()

        # --- Affichage temps ---
        self.label_time = QLabel("Heure : --:--:--")
        self.label_civil = QLabel("Crépuscule civil : --:-- - --:--")
        self.label_nautical = QLabel("Crépuscule nautique : --:-- - --:--")
        self.label_countdown = QLabel("Countdown nautique : --:--:--")
        layout.addWidget(self.label_time)
        layout.addWidget(self.label_civil)
        layout.addWidget(self.label_nautical)
        layout.addWidget(self.label_countdown)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        # --- Recherche YouTube ---
        yt_layout = QHBoxLayout()
        self.youtube_search = QLineEdit()
        self.youtube_search.setPlaceholderText("Rechercher sur YouTube...")
        yt_btn = QPushButton("Rechercher")
        yt_btn.clicked.connect(self.search_youtube)
        yt_layout.addWidget(self.youtube_search)
        yt_layout.addWidget(yt_btn)
        layout.addLayout(yt_layout)

        self.youtube_results = QListWidget()
        self.youtube_results.itemClicked.connect(self.play_audio)
        layout.addWidget(self.youtube_results)

        # --- Contrôles audio ---
        audio_ctrl = QHBoxLayout()
        btn_pause = QPushButton("⏸ Pause")
        btn_pause.clicked.connect(lambda: self.player.pause())
        btn_resume = QPushButton("▶ Reprendre")
        btn_resume.clicked.connect(lambda: self.player.play())
        btn_stop = QPushButton("⏹ Stop")
        btn_stop.clicked.connect(lambda: self.player.stop())
        audio_ctrl.addWidget(btn_pause)
        audio_ctrl.addWidget(btn_resume)
        audio_ctrl.addWidget(btn_stop)
        layout.addLayout(audio_ctrl)

        # --- SMS Programmés ---
        sms_layout = QHBoxLayout()
        self.sms_text = QLineEdit()
        self.sms_text.setPlaceholderText("Texte du SMS à envoyer...")

        self.sms_datetime = QDateTimeEdit()
        self.sms_datetime.setDisplayFormat("dd/MM/yyyy HH:mm:ss")
        self.sms_datetime.setCalendarPopup(True)
        self.sms_datetime.setDateTime(QDateTime.currentDateTime().addSecs(60))

        sms_btn = QPushButton("Programmer SMS")
        sms_btn.clicked.connect(self.schedule_sms)

        sms_layout.addWidget(self.sms_text)
        sms_layout.addWidget(self.sms_datetime)
        sms_layout.addWidget(sms_btn)
        layout.addLayout(sms_layout)

        # --- Histoire IA (bouton manuel) ---
        story_layout = QHBoxLayout()
        self.btn_story = QPushButton("Générer histoire IA (voix)")
        self.btn_story.clicked.connect(self.tell_story)
        story_layout.addWidget(self.btn_story)
        layout.addLayout(story_layout)

        # --- Console debug ---
        self.debug_console = QPlainTextEdit()
        self.debug_console.setReadOnly(True)
        self.debug_console.setStyleSheet(
            "background-color: black; color: lime; font-family: monospace;"
        )
        layout.addWidget(self.debug_console, stretch=1)

        # Redirection console -> thread-safe
        self.ts_console = ThreadSafeConsole(self.debug_console)
        sys.stdout = EmittingStream(self.ts_console)
        sys.stderr = EmittingStream(self.ts_console)

        self.setLayout(layout)

        # Player audio
        self.player = QMediaPlayer()
        self.player.stateChanged.connect(self.audio_state_changed)

        # Timers
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_times)
        self.timer.start(1000)  # tick UI/sec, fetch API throttlé ci-dessous

        # Auto histoire toutes 10 min (laisse, ou commente si tu veux manuel only)
        self.story_timer = QTimer()
        self.story_timer.timeout.connect(self.tell_story)
        self.story_timer.start(600000)

        self.alert_timer = QTimer()
        self.alert_timer.timeout.connect(self.check_alerts)
        self.alert_timer.start(60000)

        # Twilight cache + throttle
        self.nautical_time = None
        self._last_twilight = None
        self._last_tw_fetch = None
        self._tw_fetch_interval_sec = 60  # pas plus d’1 fetch/min
        self._tw_fail_count = 0

        # OpenAI client v1
        self._oa_client = None
        if _OPENAI_V1 and OPENAI_API_KEY:
            try:
                self._oa_client = OpenAI(api_key=OPENAI_API_KEY)
            except Exception:
                print("[WARN] Init OpenAI v1 a échoué, TTS/IA désactivé pour cette session.")

    def audio_state_changed(self, state):
        states = {
            QMediaPlayer.StoppedState: "⏹ Lecture arrêtée",
            QMediaPlayer.PlayingState: "▶ Lecture en cours",
            QMediaPlayer.PausedState: "⏸ Lecture en pause"
        }
        print(f"[DEBUG] {states.get(state, 'État inconnu')}")

    # -------- Crépuscule : retries + cache + throttle --------
    def _fetch_twilight_with_retries(self, url, attempts=3, timeout=8, quiet=False):
        last_exc = None
        for i in range(1, attempts + 1):
            try:
                if not quiet:
                    print(f"[DEBUG] Twilight fetch try {i}/{attempts} …")
                resp = requests.get(url, timeout=timeout)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_exc = e
                if not quiet:
                    print(f"[WARN] Twilight fetch failed (try {i}) : {e}")
        if last_exc:
            raise last_exc

    def update_times(self):
        try:
            now = datetime.datetime.now(timezone.utc).astimezone()
            # UI tick
            self.label_time.setText(f"Heure : {now.strftime('%H:%M:%S')}")

            # Throttle: fetch au plus 1 fois / self._tw_fetch_interval_sec
            need_fetch = False
            if self._last_tw_fetch is None:
                need_fetch = True
            else:
                delta = (datetime.datetime.now() - self._last_tw_fetch).total_seconds()
                if delta >= self._tw_fetch_interval_sec:
                    need_fetch = True

            if need_fetch:
                url = (
                    f"https://api.sunrise-sunset.org/json?"
                    f"lat={config.LATITUDE}&lng={config.LONGITUDE}&formatted=0&date=today"
                )
                try:
                    data = self._fetch_twilight_with_retries(
                        url, attempts=3, timeout=8, quiet=False if self._tw_fail_count == 0 else True
                    )
                    results = data["results"]

                    civil_start = datetime.datetime.fromisoformat(results["civil_twilight_begin"]).astimezone()
                    civil_end   = datetime.datetime.fromisoformat(results["civil_twilight_end"]).astimezone()
                    nautical_start = datetime.datetime.fromisoformat(results["nautical_twilight_begin"]).astimezone()
                    nautical_end   = datetime.datetime.fromisoformat(results["nautical_twilight_end"]).astimezone()

                    self._last_twilight = {
                        "civil_start": civil_start, "civil_end": civil_end,
                        "nautical_start": nautical_start, "nautical_end": nautical_end
                    }
                    self._last_tw_fetch = datetime.datetime.now()
                    self._tw_fail_count = 0  # reset ok
                except Exception as e:
                    self._tw_fail_count += 1
                    # backoff léger si ça échoue souvent
                    self._tw_fetch_interval_sec = min(300, 60 + self._tw_fail_count * 30)
                    if self._last_twilight:
                        # On garde le dernier affichage
                        print(f"[WARN] API crépuscule KO, usage du cache (échec #{self._tw_fail_count})")
                    else:
                        print("[ERROR] Erreur récupération horaires :", traceback.format_exc())

            # Affichage (si on a au moins 1 jeu de données)
            if self._last_twilight:
                civil_start   = self._last_twilight["civil_start"]
                civil_end     = self._last_twilight["civil_end"]
                nautical_start= self._last_twilight["nautical_start"]
                nautical_end  = self._last_twilight["nautical_end"]

                self.nautical_time = nautical_end
                self.label_civil.setText(
                    f"Crépuscule civil : {civil_start.strftime('%H:%M')} - {civil_end.strftime('%H:%M')}"
                )
                self.label_nautical.setText(
                    f"Crépuscule nautique : {nautical_start.strftime('%H:%M')} - {nautical_end.strftime('%H:%M')}"
                )

                remaining = nautical_end - now
                if remaining.total_seconds() > 0:
                    h, rem = divmod(int(remaining.total_seconds()), 3600)
                    m, s = divmod(rem, 60)
                    self.label_countdown.setText(
                        f"⏳ Avant crépuscule nautique : {h:02d}:{m:02d}:{s:02d}"
                    )
                else:
                    self.label_countdown.setText("🌌 Crépuscule nautique atteint")

            # Progress bar jour
            seconds_in_day = 86400
            now_seconds = now.hour * 3600 + now.minute * 60 + now.second
            self.progress.setValue(int((now_seconds / seconds_in_day) * 100))

        except Exception:
            print("[ERROR] Erreur update_times() :", traceback.format_exc())
    # ------------------------------------------------------

    def check_alerts(self):
        try:
            if not self.nautical_time:
                return
            remaining = self.nautical_time - datetime.datetime.now(timezone.utc).astimezone()
            mins = int(remaining.total_seconds() / 60)
            if mins in [30, 20, 10]:
                print(f"⚠ Attention : {mins} minutes avant le crépuscule nautique !")
        except Exception:
            print("[ERROR] Erreur check_alerts :", traceback.format_exc())

    def search_youtube(self):
        """Recherche YouTube robuste (skip les items sans videoId)."""
        if not YOUTUBE_API_KEY:
            print("[ERROR] Pas de clé API YouTube dans config.py")
            return

        query = self.youtube_search.text().strip()
        if not query:
            print("⚠ Recherche vide")
            return

        try:
            url = (
                "https://www.googleapis.com/youtube/v3/search"
                f"?part=snippet&q={requests.utils.quote(query)}"
                f"&type=video&videoEmbeddable=true&maxResults=10"
                f"&safeSearch=none&key={YOUTUBE_API_KEY}"
            )
            r = requests.get(url, timeout=8).json()
            items = r.get("items", [])
            self.youtube_results.clear()

            kept = 0
            skipped = 0

            for it in items:
                _id = it.get("id") or {}
                snippet = it.get("snippet") or {}
                kind = _id.get("kind") or it.get("kind")  # par sécurité
                video_id = _id.get("videoId")

                # On garde UNIQUEMENT les vraies vidéos avec videoId
                if kind != "youtube#video" or not video_id:
                    skipped += 1
                    title_dbg = snippet.get("title", "<sans titre>")
                    print(f"[WARN] Item ignoré (kind={kind}, videoId={video_id}) : {title_dbg}")
                    continue

                title = snippet.get("title", video_id)
                self.youtube_results.addItem(f"{title} | {video_id}")
                kept += 1

            if kept == 0:
                print("[WARN] Aucun résultat vidéo exploitable pour cette recherche.")
            else:
                print(f"[DEBUG] Recherche YouTube OK : '{query}' -> {kept} vidéos (ignorés: {skipped})")

        except Exception:
            print("[ERROR] Erreur recherche YouTube :", traceback.format_exc())

    def play_audio(self, item):
        """Lecture audio YouTube blindée (formats 'safe' + fallback)."""
        video_id = item.text().split("|")[-1].strip()
        print(f"[DEBUG] Lecture audio pour ID: {video_id}")
        url_watch = f"https://www.youtube.com/watch?v={video_id}"

        # 1er essai : forcer formats audio HTTPS courants (m4a) + client web
        ydl_opts_primary = {
            "quiet": True,
            "noplaylist": True,
            "format": "bestaudio[ext=m4a]/bestaudio[protocol^=https]/bestaudio/best",
            "extractor_args": {"youtube": {"player_client": ["web"]}},
            "nocheckcertificate": True,
            "ignoreerrors": True,
        }

        # Fallback : laisser yt-dlp choisir le best dispo, tjrs client web
        ydl_opts_fallback = {
            "quiet": True,
            "noplaylist": True,
            "format": "bestaudio/best",
            "extractor_args": {"youtube": {"player_client": ["web"]}},
            "nocheckcertificate": True,
            "ignoreerrors": True,
        }

        def _try_play(opts, label):
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url_watch, download=False)
                    stream_url = None

                    if isinstance(info, dict):
                        stream_url = info.get("url")
                        if not stream_url:
                            for f in (info.get("formats") or []):
                                u = f.get("url")
                                if u:
                                    stream_url = u
                                    break

                    if stream_url:
                        self.player.setMedia(QMediaContent(QUrl(stream_url)))
                        self.player.play()
                        print(f"[DEBUG] Audio lancé ({label})")
                        return True

            except Exception:
                print(f"[WARN] Échec lecture ({label}) :", traceback.format_exc())
            return False

        if _try_play(ydl_opts_primary, "primary"):
            return
        if _try_play(ydl_opts_fallback, "fallback"):
            return

        print("[ERROR] Impossible de récupérer un flux audio exploitable pour cette vidéo.")

    # ====== SMS PROGRAMMÉS ======
    def schedule_sms(self):
        """Programme l'envoi d'un SMS pour la date/heure choisies (thread-safe logging)."""
        if not TWILIO_OK:
            print("[ERROR] Twilio non installé : pip install twilio")
            return
        try:
            if not all([config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN, config.TWILIO_PHONE_NUMBER, config.DEST_PHONE_NUMBER]):
                print("[ERROR] Config Twilio incomplète")
                return

            texte_sms = self.sms_text.text().strip()
            if not texte_sms:
                print("⚠ Message SMS vide")
                return

            target_qt_dt = self.sms_datetime.dateTime()
            target_dt = target_qt_dt.toPyDateTime()  # datetime local naïf
            now = datetime.datetime.now()
            delay = (target_dt - now).total_seconds()

            if delay <= 0:
                print("[ERROR] L'heure programmée doit être dans le futur")
                return

            print(f"[DEBUG] SMS programmé pour {target_dt.strftime('%d/%m/%Y %H:%M:%S')} (dans {int(delay)} s)")
            QTimer.singleShot(
                int(delay * 1000),
                lambda: threading.Thread(target=self.send_sms, args=(texte_sms,), daemon=True).start()
            )
        except Exception:
            print("[ERROR] Erreur programmation SMS :", traceback.format_exc())

    def send_sms(self, texte_sms=None):
        """Envoi immédiat (utilisé par la planification)."""
        if not TWILIO_OK:
            print("[ERROR] Twilio non installé : pip install twilio")
            return
        try:
            if not all([config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN, config.TWILIO_PHONE_NUMBER, config.DEST_PHONE_NUMBER]):
                print("[ERROR] Config Twilio incomplète")
                return

            if texte_sms is None:
                texte_sms = self.sms_text.text().strip()
                if not texte_sms:
                    print("⚠ Texte vide")
                    return

            client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
            message = client.messages.create(
                body=texte_sms,
                from_=config.TWILIO_PHONE_NUMBER,
                to=config.DEST_PHONE_NUMBER
            )
            print(f"[DEBUG] SMS envoyé : {message.sid}")
        except Exception:
            print("[ERROR] Erreur envoi SMS :", traceback.format_exc())

    # ====== IA Histoire + voix (OpenAI v1 + Google Cloud TTS / gTTS) ======
    def _speak_text(self, text: str):
        """Joue `text` en priorité via Google Cloud TTS, sinon gTTS, sinon log."""
        # 1) Google Cloud TTS si dispo
        if GCLOUD_TTS_OK and gctts is not None:
            try:
                client = gctts.TextToSpeechClient()
                synthesis_input = gctts.SynthesisInput(text=text)

                voice_name = getattr(config, "GCP_TTS_VOICE", "fr-FR-Neural2-A")
                voice = gctts.VoiceSelectionParams(
                    language_code="fr-FR",
                    name=voice_name,
                    ssml_gender=gctts.SsmlVoiceGender.NEUTRAL,
                )
                audio_config = gctts.AudioConfig(
                    audio_encoding=gctts.AudioEncoding.MP3,
                    speaking_rate=float(getattr(config, "GCP_TTS_RATE", 1.0)),
                    pitch=float(getattr(config, "GCP_TTS_PITCH", 0.0)),
                )
                response = client.synthesize_speech(
                    input=synthesis_input, voice=voice, audio_config=audio_config
                )
                temp_file = os.path.join(tempfile.gettempdir(), "story_gcloud.mp3")
                with open(temp_file, "wb") as f:
                    f.write(response.audio_content)
                self.player.setMedia(QMediaContent(QUrl.fromLocalFile(temp_file)))
                self.player.play()
                print("[DEBUG] TTS Google Cloud joué")
                return
            except Exception:
                print("[ERROR] Google Cloud TTS a échoué :", traceback.format_exc())

        # 2) gTTS fallback
        if GTTS_OK:
            try:
                tts = gTTS(text, lang="fr")
                temp_file = os.path.join(tempfile.gettempdir(), "story_gtts.mp3")
                tts.save(temp_file)
                self.player.setMedia(QMediaContent(QUrl.fromLocalFile(temp_file)))
                self.player.play()
                print("[DEBUG] TTS gTTS joué")
                return
            except Exception:
                print("[ERROR] gTTS a échoué :", traceback.format_exc())

        print("[WARN] Aucun moteur TTS disponible (installe gTTS ou configure Google Cloud TTS).")

    def tell_story(self):
        if not _OPENAI_V1 or not OPENAI_API_KEY:
            print("[ERROR] OpenAI v1 indisponible ou clé absente (config.OPENAI_API_KEY)")
            return
        if self._oa_client is None:
            try:
                self._oa_client = OpenAI(api_key=OPENAI_API_KEY)
            except Exception:
                print("[ERROR] Impossible d'initialiser OpenAI v1")
                return

        prompt = f"Raconte-moi une courte histoire de style {getattr(config, 'STORY_THEME', 'fantastique')}."
        try:
            resp = self._oa_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8,
                max_tokens=350,
            )
            story = resp.choices[0].message.content
            print("\n📖 Nouvelle histoire générée :\n", story)

            # Parole
            self._speak_text(story)

        except Exception:
            print("[ERROR] Erreur génération histoire :", traceback.format_exc())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    hud = TwilightHUD()
    hud.show()
    sys.exit(app.exec())
