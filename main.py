"""
main.py — Fetch (Android + desktop)
Build: buildozer android debug  →  bin/fetch-1.0-debug.apk

High-quality unlock:
  - Import a cookies.txt (Netscape format) exported from a logged-in browser.
  - Cookies let yt-dlp access age-restricted, members-only, and 1440p/2160p/4K streams
    that YouTube hides from unauthenticated requests.
  - On desktop, FFmpeg must be installed and on PATH for stream merging.
"""

import io
import json
import os
import sys
import threading
import re

def ensure_streams():
    for name in ("stdout", "stderr"):
        s = getattr(sys, name, None)
        if s is None or isinstance(s, str) or not hasattr(s, "write"):
            setattr(sys, name, io.StringIO())


ensure_streams()

import yt_dlp  # noqa: E402

from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import NumericProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.image import AsyncImage
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import platform

# ── Palette ──────────────────────────────────────────────────────────────────
BG       = (0.039, 0.043, 0.063, 1)
SURFACE  = (0.082, 0.090, 0.125, 1)
SURFACE2 = (0.125, 0.137, 0.188, 1)
ACCENT   = (0.424, 0.388, 1.0, 1)
PINK     = (1.0, 0.42, 0.616, 1)
WHITE    = (1, 1, 1, 1)
TEXT     = (0.93, 0.93, 0.96, 1)
MUTED    = (0.52, 0.54, 0.64, 1)
OK       = (0.243, 0.812, 0.557, 1)
ERR      = (1.0, 0.373, 0.341, 1)
GOLD     = (1.0, 0.80, 0.20, 1)

Window.clearcolor = BG
if platform == "android":
    Window.softinput_mode = "below_target"

ANDROID = platform == "android"

# ── YouTube client list ───────────────────────────────────────────────────────
# FIX: removed android_vr — it reports formats that 403 on actual download.
# web surfaces VP9/AV1 high-bitrate streams.
# tv_embedded bypasses some age gates without cookies.
# ios is a reliable fallback.
YT_CLIENTS = ["default", "-web", "-web_safari"]

# ── Anti-throttle chunk size ──────────────────────────────────────────────────
# YouTube's adaptive throttling hammers large unbounded requests.
# Fixed 10 MB chunks defeat it by looking like normal buffered playback.
HTTP_CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB


# ── Storage helpers ──────────────────────────────────────────────────────────
def _writable(path):
    try:
        os.makedirs(path, exist_ok=True)
        test = os.path.join(path, ".w")
        with open(test, "w") as f:
            f.write("x")
        os.remove(test)
        return True
    except Exception:
        return False


def get_download_dir():
    if not ANDROID:
        from pathlib import Path
        p = str(Path.home() / "Downloads")
        os.makedirs(p, exist_ok=True)
        return p
    candidates = []
    try:
        from android.storage import primary_external_storage_path
        candidates.append(os.path.join(primary_external_storage_path(), "Download", "Fetch"))
    except Exception:
        candidates.append("/sdcard/Download/Fetch")
    try:
        from jnius import autoclass
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        candidates.append(os.path.join(act.getExternalFilesDir(None).getAbsolutePath(), "Fetch"))
    except Exception:
        pass
    for c in candidates:
        if _writable(c):
            return c
    return os.getcwd()


def ensure_all_files_access():
    try:
        from jnius import autoclass
        Env = autoclass("android.os.Environment")
        if autoclass("android.os.Build$VERSION").SDK_INT >= 30 and not Env.isExternalStorageManager():
            Intent   = autoclass("android.content.Intent")
            Settings = autoclass("android.provider.Settings")
            Uri      = autoclass("android.net.Uri")
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            act.startActivity(Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                                     Uri.parse("package:" + act.getPackageName())))
    except Exception:
        pass


# ── Formatting helpers ───────────────────────────────────────────────────────
def fmt_size(n):
    if not n:
        return ""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def fmt_time(sec):
    if not sec:
        return ""
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def merge_av(video_path, audio_path, out_path):
    """Mux H.264 video + AAC audio into one mp4 using Android MediaMuxer."""
    from jnius import autoclass
    MediaExtractor = autoclass("android.media.MediaExtractor")
    MediaMuxer = autoclass("android.media.MediaMuxer")
    BufferInfo = autoclass("android.media.MediaCodec$BufferInfo")
    ByteBuffer = autoclass("java.nio.ByteBuffer")

    def open_track(path, prefix):
        ex = MediaExtractor()
        ex.setDataSource(path)
        for i in range(ex.getTrackCount()):
            fmt = ex.getTrackFormat(i)
            if (fmt.getString("mime") or "").startswith(prefix):
                ex.selectTrack(i)
                return ex, fmt
        ex.release()
        raise RuntimeError(f"No {prefix} track in {path}")

    v_ex, v_fmt = open_track(video_path, "video/")
    a_ex, a_fmt = open_track(audio_path, "audio/")
    muxer = MediaMuxer(out_path, 0)  # 0 = MPEG_4
    try:
        v_idx = muxer.addTrack(v_fmt)
        a_idx = muxer.addTrack(a_fmt)
        muxer.start()
        buf = ByteBuffer.allocateDirect(8 * 1024 * 1024)
        info = BufferInfo()
        for ex, idx in ((v_ex, v_idx), (a_ex, a_idx)):
            while True:
                size = ex.readSampleData(buf, 0)
                if size < 0:
                    break
                info.set(0, size, ex.getSampleTime(), ex.getSampleFlags())
                muxer.writeSampleData(idx, buf, info)
                ex.advance()
        muxer.stop()
    finally:
        muxer.release()
        v_ex.release()
        a_ex.release()

def scan_media(path):
    """Tell Android's media scanner about a new file so Gallery shows it."""
    if not ANDROID:
        return
    try:
        from jnius import autoclass
        MSC = autoclass("android.media.MediaScannerConnection")
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        MSC.scanFile(act, [path], None, None)
    except Exception:
        pass

URL_RE = re.compile(r"https?://\S+")

def extract_url(intent):
    """Pull the first URL out of a share intent."""
    try:
        if intent is None or intent.getAction() != "android.intent.action.SEND":
            return None
        text = intent.getStringExtra("android.intent.extra.TEXT") or ""
        m = URL_RE.search(text)
        return m.group(0) if m else None
    except Exception:
        return None

class QuietLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def build_entries(info):
    """
    One entry per resolution.
    Stores video_id, audio_id, mux_id independently.
    Scores video by tbr then codec (AV1 > VP9 > AVC).
    """
    best_video = {}
    best_muxed = {}
    best_audio = None

    for f in info.get("formats") or []:
        vcodec = (f.get("vcodec") or "none").lower()
        acodec = (f.get("acodec") or "none").lower()
        h   = f.get("height")
        tbr = f.get("tbr") or 0
        abr = f.get("abr") or tbr

        is_video_only = vcodec != "none" and acodec == "none"
        is_audio_only = vcodec == "none" and acodec != "none"
        is_muxed      = vcodec != "none" and acodec != "none"

        if ANDROID and is_video_only and "avc1" not in vcodec:
            continue
        if ANDROID and is_audio_only and f.get("ext") != "m4a":
            continue

        if is_audio_only:
            score = (abr, f.get("ext") == "m4a")
            if best_audio is None or score > best_audio["score"]:
                best_audio = {"id": f["format_id"], "score": score}

        if not h:
            continue

        if is_video_only:
            codec_pref = 2 if "av01" in vcodec else (1 if "vp9" in vcodec else 0)
            score = (tbr, codec_pref, f.get("filesize") or 0)
            cur = best_video.get(h)
            if cur is None or score > cur["score"]:
                best_video[h] = {"id": f["format_id"], "score": score,
                                 "size": f.get("filesize") or f.get("filesize_approx")}

        if is_muxed:
            score = (tbr, f.get("ext") == "mp4", f.get("filesize") or 0)
            cur = best_muxed.get(h)
            if cur is None or score > cur["score"]:
                best_muxed[h] = {"id": f["format_id"], "score": score,
                                 "size": f.get("filesize") or f.get("filesize_approx")}

    all_heights = sorted(set(best_video) | set(best_muxed), reverse=True)
    audio_id    = best_audio["id"] if best_audio else None

    entries = [{"h": None, "video_id": None, "audio_id": audio_id,
                "mux_id": None, "has_audio": True, "size": None}]
    for h in all_heights:
        vf = best_video.get(h)
        mf = best_muxed.get(h)
        entries.append({
            "h":        h,
            "video_id": vf["id"] if vf else None,
            "audio_id": audio_id,
            "mux_id":   mf["id"] if mf else None,
            "has_audio": mf is not None,
            "size":     (vf or mf or {}).get("size"),
        })
    return entries


# ── Widgets ──────────────────────────────────────────────────────────────────
class AutoLabel(Label):
    def __init__(self, text="", size=14, color=TEXT, bold=False, halign="left", min_h=0, **kw):
        super().__init__(text=text, font_size=f"{size}sp", color=color, bold=bold,
                         halign=halign, valign="middle", size_hint_y=None, **kw)
        self._min_h = dp(min_h)
        self.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                  texture_size=lambda w, ts: setattr(w, "height", max(ts[1] + dp(2), w._min_h)))


class RBtn(ButtonBehavior, Label):
    def __init__(self, text="", bg=SURFACE2, fg=TEXT, radius=14, height=48, size=14, bold=False, **kw):
        super().__init__(text=text, color=fg, font_size=f"{size}sp", bold=bold,
                         halign="center", valign="middle", size_hint_y=None, height=dp(height), **kw)
        self.bg = bg
        with self.canvas.before:
            self._col  = Color(*bg)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(radius)])
        self.bind(pos=self._upd, size=self._upd, state=self._state, disabled=self._dis,
                  width=lambda w, v: setattr(w, "text_size", (v - dp(8), None)))

    def _upd(self, *a):   self._rect.pos, self._rect.size = self.pos, self.size
    def _state(self, *a):
        c = self.bg
        self._col.rgba = (c[0]*.75, c[1]*.75, c[2]*.75, 1) if self.state == "down" else c
    def _dis(self, *a):   self.opacity = .45 if self.disabled else 1
    def set_look(self, bg, fg):
        self.bg = bg; self._col.rgba = bg; self.color = fg


class Card(BoxLayout):
    def __init__(self, bg=SURFACE, radius=18, pad=14, **kw):
        kw.setdefault("orientation", "vertical")
        kw.setdefault("spacing", dp(10))
        super().__init__(padding=dp(pad), size_hint_y=None, **kw)
        with self.canvas.before:
            Color(*bg)
            self._r = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(radius)])
        self.bind(pos=self._u, size=self._u, minimum_height=self.setter("height"))

    def _u(self, *a): self._r.pos, self._r.size = self.pos, self.size


class Bar(Widget):
    value = NumericProperty(0)

    def __init__(self, **kw):
        super().__init__(size_hint_y=None, height=dp(8), **kw)
        with self.canvas:
            Color(*SURFACE2); self._bg = RoundedRectangle(radius=[dp(4)])
            self._c = Color(*ACCENT); self._fg = RoundedRectangle(radius=[dp(4)])
        self.bind(pos=self._u, size=self._u, value=self._u)

    def set_color(self, c): self._c.rgba = c
    def _u(self, *a):
        self._bg.pos, self._bg.size = self.pos, self.size
        self._fg.pos  = self.pos
        self._fg.size = (max(self.width * self.value / 100.0, 0), self.height)


class Slot(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", size_hint_y=None, **kw)
        self.bind(minimum_height=self.setter("height"))


# ── App ──────────────────────────────────────────────────────────────────────
class FetchApp(App):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.mode    = "video"
        self.entries = [{"h": None, "video_id": None, "audio_id": None,
                         "mux_id": None, "has_audio": True, "size": None}]
        self.sel                = 0
        self.chips              = []
        self.dirs               = {"video": None, "audio": None}
        self._out_dir           = None
        self._stage, self._stages = 0, 1
        self._cookies_path      = None   # path to cookies.txt, None = not set

    # ── build ─────────────────────────────────────────────────────────────────
    def build(self):
        self.title = "Fetch"
        self._load_cfg()
        scroll     = ScrollView(do_scroll_x=False, bar_width=0)
        self.main  = BoxLayout(orientation="vertical", padding=dp(16),
                               spacing=dp(14), size_hint_y=None)
        self.main.bind(minimum_height=self.main.setter("height"))
        scroll.add_widget(self.main)
        self._build_ui()
        return scroll

    def on_start(self):
        if ANDROID:
            try:
                from android.permissions import request_permissions, Permission
                request_permissions([Permission.INTERNET,
                                     Permission.WRITE_EXTERNAL_STORAGE,
                                     Permission.READ_EXTERNAL_STORAGE])
            except Exception:
                pass
            ensure_all_files_access()
            try:
                from android import activity
                activity.bind(on_new_intent=self._on_new_intent)
                from jnius import autoclass
                act = autoclass("org.kivy.android.PythonActivity").mActivity
                self._handle_intent(act.getIntent())
            except Exception:
                pass

    def _handle_intent(self, intent):
        url = extract_url(intent)
        if url:
            Clock.schedule_once(lambda dt: self._load_shared(url))

    def _on_new_intent(self, intent):
        self._handle_intent(intent)

    def _load_shared(self, url):
        self.url_input.text = url
        self._fetch_info()

    def _build_ui(self):
        add = self.main.add_widget

        # header
        add(AutoLabel("Fetch", size=30, bold=True, color=WHITE, min_h=40))
        add(AutoLabel("YouTube · TikTok · Instagram · X", size=12, color=MUTED, min_h=16))

        # url card
        url_card = Card()
        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        self.url_input = TextInput(
            hint_text="Paste a video link…", multiline=False, font_size="14sp",
            background_normal="", background_active="", background_color=SURFACE2,
            foreground_color=TEXT, hint_text_color=MUTED, cursor_color=ACCENT,
            padding=(dp(12), dp(14)))
        paste = RBtn("Paste", bg=SURFACE2, fg=ACCENT, height=48, size=13, bold=True,
                     size_hint_x=None, width=dp(72))
        paste.bind(on_release=lambda *_: setattr(self.url_input, "text",
                                                  (Clipboard.paste() or "").strip()))
        row.add_widget(self.url_input)
        row.add_widget(paste)
        url_card.add_widget(row)
        self.fetch_btn = RBtn("Fetch Info", bg=ACCENT, fg=WHITE, height=48, bold=True)
        self.fetch_btn.bind(on_release=lambda *_: self._fetch_info())
        url_card.add_widget(self.fetch_btn)
        add(url_card)

        # ── cookies card ──────────────────────────────────────────────────────
        ck_card = Card(bg=SURFACE)
        ck_title_row = BoxLayout(size_hint_y=None, height=dp(20))
        ck_title_row.add_widget(AutoLabel("COOKIES  (unlocks 4K + age-restricted)", size=11,
                                          color=GOLD, bold=True, min_h=16))
        ck_card.add_widget(ck_title_row)

        ck_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        self.ck_lbl = AutoLabel("Not set — public streams only", size=11, color=MUTED, min_h=14)
        ck_row.add_widget(self.ck_lbl)
        ck_import = RBtn("Import", bg=SURFACE2, fg=GOLD, height=36, size=12, bold=True,
                         radius=10, size_hint_x=None, width=dp(78))
        ck_clear  = RBtn("Clear",  bg=SURFACE2, fg=MUTED, height=36, size=12,
                         radius=10, size_hint_x=None, width=dp(60))
        ck_import.bind(on_release=lambda *_: self._pick_cookies())
        ck_clear.bind(on_release=lambda *_: self._clear_cookies())
        ck_row.add_widget(ck_import)
        ck_row.add_widget(ck_clear)
        ck_card.add_widget(ck_row)

        ck_hint = AutoLabel(
            "Export cookies.txt from Chrome/Firefox while logged into YouTube.\n"
            "Extensions: 'Get cookies.txt LOCALLY' (Chrome) or 'cookies.txt' (Firefox).",
            size=10, color=MUTED, min_h=0)
        ck_card.add_widget(ck_hint)
        add(ck_card)
        self._refresh_ck_lbl()

        # preview slot
        self.preview_slot = Slot()
        add(self.preview_slot)

        # mode toggle
        mode_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        self.btn_video = RBtn("Video", bg=ACCENT, fg=WHITE, bold=True)
        self.btn_audio = RBtn("Audio only", bg=SURFACE, fg=MUTED, bold=True)
        self.btn_video.bind(on_release=lambda *_: self._set_mode("video"))
        self.btn_audio.bind(on_release=lambda *_: self._set_mode("audio"))
        mode_row.add_widget(self.btn_video)
        mode_row.add_widget(self.btn_audio)
        add(mode_row)

        # quality
        self.q_slot = Slot()
        q_card = Card()
        q_card.add_widget(AutoLabel("QUALITY", size=11, color=MUTED, bold=True, min_h=16))
        self.q_scroll = ScrollView(do_scroll_y=False, size_hint_y=None, height=dp(76), bar_width=0)
        self.q_row    = BoxLayout(size_hint_x=None, spacing=dp(8))
        self.q_row.bind(minimum_width=self.q_row.setter("width"))
        self.q_scroll.add_widget(self.q_row)
        q_card.add_widget(self.q_scroll)
        self.q_note = AutoLabel("", size=11, color=MUTED, min_h=0)
        q_card.add_widget(self.q_note)
        self.q_card = q_card
        self.q_slot.add_widget(q_card)
        add(self.q_slot)
        self._rebuild_q()

        # progress + folder card
        p_card = Card()
        self.status_lbl = AutoLabel("Paste a link → Fetch Info → Download",
                                    size=12, color=MUTED, min_h=18)
        p_card.add_widget(self.status_lbl)
        self.prog = Bar()
        p_card.add_widget(self.prog)

        dir_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        self.dir_lbl = AutoLabel("", size=10, color=MUTED, min_h=14)
        dir_row.add_widget(self.dir_lbl)
        change = RBtn("Change", bg=SURFACE2, fg=ACCENT, height=36, size=12, bold=True,
                      radius=10, size_hint_x=None, width=dp(78))
        change.size_hint_y = None
        change.bind(on_release=lambda *_: self._pick_folder())
        dir_row.add_widget(change)
        p_card.add_widget(dir_row)
        self._refresh_dir_lbl()
        add(p_card)

        # download
        self.dl_btn = RBtn("Download", bg=ACCENT, fg=WHITE, height=58, size=17, bold=True, radius=18)
        self.dl_btn.bind(on_release=lambda *_: self._start_download())
        add(self.dl_btn)

    # ── cookies handling ──────────────────────────────────────────────────────
    def _refresh_ck_lbl(self):
        if self._cookies_path and os.path.isfile(self._cookies_path):
            name = os.path.basename(self._cookies_path)
            self.ck_lbl.text  = f"Active: {name}"
            self.ck_lbl.color = GOLD
        else:
            self.ck_lbl.text  = "Not set — public streams only"
            self.ck_lbl.color = MUTED

    def _pick_cookies(self):
        start = os.path.expanduser("~") if not ANDROID else "/sdcard"
        box   = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        fc    = FileChooserListView(path=start, dirselect=False,
                                    filters=["*.txt", "*.TXT"])
        box.add_widget(fc)
        row    = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        cancel = RBtn("Cancel", bg=SURFACE2, fg=TEXT)
        ok     = RBtn("Use this file", bg=GOLD, fg=(0, 0, 0, 1), bold=True)
        row.add_widget(cancel); row.add_widget(ok)
        box.add_widget(row)
        pop = Popup(title="Pick cookies.txt", content=box, size_hint=(.96, .88),
                    separator_color=GOLD, background="",
                    background_color=(0.06, 0.07, 0.1, 1))
        cancel.bind(on_release=lambda *_: pop.dismiss())

        def choose(*_):
            sel = fc.selection[0] if fc.selection else None
            pop.dismiss()
            if sel and os.path.isfile(sel):
                self._cookies_path = sel
                self._save_cfg()
                self._refresh_ck_lbl()
                self._set_status("Cookies loaded — high-quality streams unlocked", OK)
            else:
                self._set_status("No file selected", MUTED)

        ok.bind(on_release=choose)
        pop.open()

    def _clear_cookies(self):
        self._cookies_path = None
        self._save_cfg()
        self._refresh_ck_lbl()
        self._set_status("Cookies cleared", MUTED)

    # ── save-folder handling ──────────────────────────────────────────────────
    def _cfg_path(self):
        return os.path.join(self.user_data_dir, "config.json")

    def _load_cfg(self):
        try:
            with open(self._cfg_path()) as f:
                saved = json.load(f)
            for m in ("video", "audio"):
                d = saved.get(m)
                if d and _writable(d):
                    self.dirs[m] = d
            ck = saved.get("cookies")
            if ck and os.path.isfile(ck):
                self._cookies_path = ck
        except Exception:
            pass

    def _save_cfg(self):
        try:
            data = dict(self.dirs)
            if self._cookies_path:
                data["cookies"] = self._cookies_path
            with open(self._cfg_path(), "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def cur_dir(self):
        return self.dirs[self.mode] or get_download_dir()

    def _refresh_dir_lbl(self):
        what = "Video" if self.mode == "video" else "Audio"
        self.dir_lbl.text = f"{what} saves to: {self.cur_dir()}"

    def _pick_folder(self):
        mode   = self.mode
        accent = ACCENT if mode == "video" else PINK
        start  = self.cur_dir()
        if not os.path.isdir(start):
            start = "/sdcard" if ANDROID else os.path.expanduser("~")
        base = "/sdcard" if ANDROID else os.path.expanduser("~")

        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        fc  = FileChooserListView(
            path=start, dirselect=True,
            filters=[lambda folder, fn: os.path.isdir(os.path.join(folder, fn))])

        sc = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        for label, sub in (("Downloads", "Download"), ("Movies", "Movies"),
                           ("Music", "Music"), ("DCIM", "DCIM")):
            b = RBtn(label, bg=SURFACE2, fg=accent, height=40, size=12, radius=10)
            target = os.path.join(base, sub)
            b.bind(on_release=lambda _b, t=target: setattr(
                fc, "path", t if os.path.isdir(t) else base))
            sc.add_widget(b)
        box.add_widget(sc)
        box.add_widget(fc)

        row    = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        cancel = RBtn("Cancel", bg=SURFACE2, fg=TEXT)
        ok     = RBtn("Use this folder", bg=accent, fg=WHITE, bold=True)
        row.add_widget(cancel); row.add_widget(ok)
        box.add_widget(row)

        pop = Popup(title=f"Save {mode} to…", content=box, size_hint=(.96, .92),
                    separator_color=accent, background="",
                    background_color=(0.06, 0.07, 0.1, 1))
        cancel.bind(on_release=lambda *_: pop.dismiss())

        def choose(*_):
            sel = fc.selection[0] if fc.selection and os.path.isdir(fc.selection[0]) else fc.path
            pop.dismiss()
            if _writable(sel):
                self.dirs[mode] = sel
                self._save_cfg()
                self._refresh_dir_lbl()
                self._set_status(f"{mode.capitalize()} folder set", OK)
            else:
                self._set_status("Can't write there — pick another folder", ERR)

        ok.bind(on_release=choose)
        pop.open()

    # ── quality chips ─────────────────────────────────────────────────────────
    def _rebuild_q(self):
        self.q_row.clear_widgets()
        self.chips = []
        for i, e in enumerate(self.entries):
            if e["h"] is None:
                text = "Best\nauto"
            else:
                lines = [f"{e['h']}p"]
                sz = fmt_size(e["size"])
                if sz:
                    lines.append(sz)
                if ANDROID and e["video_id"] and not e["has_audio"]:
                    lines.append("2 files")
                text = "\n".join(lines)
            b = RBtn(text, bg=SURFACE2, fg=MUTED, height=64, size=12, radius=12,
                     size_hint_x=None, width=dp(84))
            b.bind(on_release=lambda _b, idx=i: self._set_q(idx))
            self.q_row.add_widget(b)
            self.chips.append(b)
        self._set_q(0)
        note = ""
        # FIX: was using double-quotes inside a double-quoted string — syntax error
        if ANDROID and any(e["video_id"] and not e["has_audio"] for e in self.entries[1:]):
                        note = 'Qualities marked "2 files" are downloaded separately, then merged automatically.'
        self.q_note.text = note

    def _set_q(self, idx):
        self.sel   = idx
        accent = ACCENT if self.mode == "video" else PINK
        for i, b in enumerate(self.chips):
            b.set_look(accent if i == idx else SURFACE2, WHITE if i == idx else MUTED)

    # ── mode ──────────────────────────────────────────────────────────────────
    def _set_mode(self, m):
        self.mode = m
        if m == "video":
            self.btn_video.set_look(ACCENT, WHITE)
            self.btn_audio.set_look(SURFACE, MUTED)
            self.dl_btn.set_look(ACCENT, WHITE)
            self.dl_btn.text = "Download"
            self.prog.set_color(ACCENT)
            if self.q_card.parent is None:
                self.q_slot.add_widget(self.q_card)
        else:
            self.btn_audio.set_look(PINK, WHITE)
            self.btn_video.set_look(SURFACE, MUTED)
            self.dl_btn.set_look(PINK, WHITE)
            self.dl_btn.text = "Save Audio (.m4a)" if ANDROID else "Save Audio (.mp3)"
            self.prog.set_color(PINK)
            if self.q_card.parent is not None:
                self.q_slot.remove_widget(self.q_card)
        self._set_q(self.sel)
        self._refresh_dir_lbl()

    # ── base yt-dlp options ───────────────────────────────────────────────────
    def _base_opts(self):
        opts = {
            "quiet":            True,
            "no_warnings":      True,
            "noprogress":       True,
            "no_color":         True,
            "logger":           QuietLogger(),
            "noplaylist":       True,
            "cachedir":         False,
            "restrictfilenames": True,
            # FIX: added extractor_retries + fragment_retries to survive transient 403s
            "retries":          10,
            "fragment_retries": 10,
            "extractor_retries": 5,
            "socket_timeout":   30,
            # ── anti-throttle: fixed chunk size defeats adaptive bandwidth shaping ──
            "http_chunk_size":  HTTP_CHUNK_SIZE,
            # ── geo-bypass: fake X-Forwarded-For to sidestep region blocks ──────────
            "geo_bypass":       True,
            # ── client list: web first for high-res VP9/AV1; tv_embedded bypasses
            #    some age gates without requiring cookies ──────────────────────────
            "extractor_args":   {"youtube": {"player_client": YT_CLIENTS}},
        }
        # ── cookies: inject if the user has set a cookies.txt ────────────────
        if self._cookies_path and os.path.isfile(self._cookies_path):
            opts["cookiefile"] = self._cookies_path
        return opts

    # ── fetch info ────────────────────────────────────────────────────────────
    def _fetch_info(self):
        url = self.url_input.text.strip()
        if not url:
            self._set_status("Paste a link first", ERR)
            return
        self.fetch_btn.disabled = True
        self._set_status("Fetching info…")
        threading.Thread(target=self._info_worker, args=(url,), daemon=True).start()

    def _info_worker(self, url):
        ensure_streams()
        try:
            opts = self._base_opts()
            opts["skip_download"] = True
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if info.get("entries"):
                info = next(iter(info["entries"]), info)
            entries = build_entries(info)
            meta = {
                "title":    (info.get("title") or "")[:90],
                "uploader": info.get("uploader") or "",
                "duration": info.get("duration"),
                "thumb":    info.get("thumbnail"),
            }
            Clock.schedule_once(lambda dt: self._on_info(meta, entries))
        except Exception as e:
            msg = str(e).replace("ERROR: ", "")[:160]
            Clock.schedule_once(lambda dt: self._info_fail(msg))

    def _info_fail(self, msg):
        hint = ""
        low  = msg.lower()
        if any(k in low for k in ("sign in", "age", "members", "private", "login")):
            hint = " — try importing cookies.txt from a logged-in browser"
        self._set_status(f"Error: {msg}{hint}", ERR)
        self.fetch_btn.disabled = False

    def _on_info(self, meta, entries):
        self.preview_slot.clear_widgets()
        card = Card(pad=0, radius=18, spacing=0)
        if meta["thumb"]:
            img = AsyncImage(source=meta["thumb"], size_hint_y=None,
                             height=dp(190), fit_mode="cover")
            card.add_widget(img)
        body = BoxLayout(orientation="vertical", padding=dp(14),
                         spacing=dp(4), size_hint_y=None)
        body.bind(minimum_height=body.setter("height"))
        body.add_widget(AutoLabel(meta["title"], size=15, bold=True, color=WHITE))
        sub = "  •  ".join(x for x in (meta["uploader"], fmt_time(meta["duration"])) if x)
        if sub:
            body.add_widget(AutoLabel(sub, size=12, color=MUTED))
        card.add_widget(body)
        self.preview_slot.add_widget(card)
        self.entries = entries
        self._rebuild_q()
        self.fetch_btn.disabled = False
        self._set_status("Ready — pick a quality and tap Download", OK)

    # ── download ──────────────────────────────────────────────────────────────
    def _start_download(self):
        url = self.url_input.text.strip()
        if not url:
            self._set_status("Paste a link first", ERR)
            return
        # FIX: block download if info hasn't been fetched yet
        if all(e["video_id"] is None and e["mux_id"] is None and e["audio_id"] is None
            for e in self.entries):
            self._set_status("Tap Fetch Info first before downloading", ERR)
            return
        self._out_dir = self.cur_dir()
        if not _writable(self._out_dir):
            self._set_status("Can't write to this folder — tap Change and pick another", ERR)
            return
        self._refresh_dir_lbl()
        self.dl_btn.disabled = True
        self.prog.value      = 0
        self._set_status("Starting…")
        threading.Thread(target=self._dl_worker, args=(url,), daemon=True).start()

    def _plan_jobs(self):
        if self.mode == "audio":
            if ANDROID:
                return [("bestaudio[ext=m4a]/bestaudio/best", "", {})]
            return [("bestaudio/best", "", {"postprocessors": [
                {"key": "FFmpegExtractAudio",
                "preferredcodec": "mp3", "preferredquality": "192"}]})]

        e = self.entries[self.sel] if self.sel < len(self.entries) else self.entries[0]
        h = e["h"]

        if not ANDROID:
            if h is None:
                fmt = "bv*+ba/b"
            else:
                fmt = (
                    f"bv*[height={h}]+ba"
                    f"/bv*[height<={h}]+ba"
                    f"/b[height<={h}]"
                    f"/b"
                )
            return [(fmt, "", {"merge_output_format": "mp4"})]

        # Android — no ffmpeg
        if h is None:
            # "Best auto" = highest available quality, using the same
            # 2-file + MediaMuxer path as the numbered qualities.
            real = [x for x in self.entries[1:] if x["video_id"] or x["mux_id"]]
            if real:
                e = real[0]
                h = e["h"]
            else:
                return [("best[ext=mp4]/best", "", {})]

        if e["mux_id"]:
            fmt = (
                f"{e['mux_id']}"
                f"/best[height<={h}][ext=mp4]"
                f"/best[height<={h}]"
                f"/best[ext=mp4]"
                f"/best"
            )
            return [(fmt, f"_{h}p", {})]

        if e["video_id"]:
            vid_fmt = (
                f"{e['video_id']}"
                f"/bestvideo[height<={h}][ext=mp4]"
                f"/bestvideo[height<={h}]"
                f"/bestvideo"
            )
            return [
                (vid_fmt,                        f"_{h}p_video", {}),
                ("bestaudio[ext=m4a]/bestaudio", "_audio",       {}),
            ]

        # last resort
        return [(
            f"best[height<={h}][ext=mp4]"
            f"/best[height<={h}]"
            f"/best[ext=mp4]"
            f"/best",
            f"_{h}p", {}
        )]
    def _dl_worker(self, url):
        ensure_streams()
        jobs          = self._plan_jobs()
        self._stages  = len(jobs)
        out_dir       = self._out_dir
        files         = {}

        def hook(d):
            if d.get("status") == "finished":
                files[self._stage] = d.get("filename")
            if d.get("status") == "downloading":
                total   = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done    = d.get("downloaded_bytes") or 0
                pct     = (done / total * 100) if total else 0
                overall = (self._stage * 100 + pct) / self._stages
                speed, eta = d.get("speed"), d.get("eta")
                txt = f"Downloading… {int(overall)}%"
                if speed: txt += f"  •  {fmt_size(speed)}/s"
                if eta:   txt += f"  •  {fmt_time(eta)} left"
                Clock.schedule_once(lambda dt: self._upd_prog(overall, txt))

        try:
            for i, (fmt, tag, extra) in enumerate(jobs):
                self._stage = i
                opts = self._base_opts()
                opts.update({
                    "format":         fmt,
                    "outtmpl":        os.path.join(out_dir, f"%(title).80s{tag}.%(ext)s"),
                    "progress_hooks": [hook],
                })
                opts.update(extra)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])

            final = list(files.values())
            if ANDROID and len(jobs) == 2 and 0 in files and 1 in files:
                Clock.schedule_once(lambda dt: self._set_status("Merging video + audio…"))
                v, a = files[0], files[1]
                out = v.replace("_video.", ".")
                try:
                    merge_av(v, a, out)
                    os.remove(v)
                    os.remove(a)
                    final = [out]
                except Exception as e:
                    msg = f"Merge failed, kept 2 files: {str(e)[:100]}"
                    Clock.schedule_once(lambda dt: self._on_error(msg))
                    return
            for p in final:
                scan_media(p)
            Clock.schedule_once(lambda dt: self._on_done())
        except Exception as e:
            msg = str(e).replace("ERROR: ", "")[:160]
            Clock.schedule_once(lambda dt: self._on_error(msg))
            
    def _upd_prog(self, pct, txt):
        self.prog.value = pct
        self._set_status(txt)

    def _on_done(self):
        self.prog.value      = 100
        self.dl_btn.disabled = False
        self._set_status(f"Saved → {self._out_dir}", OK)

    def _on_error(self, err):
        hint = ""
        low  = err.lower()
        if any(k in low for k in ("sign in", "age", "members", "private", "login", "403")):
            hint = " — import cookies.txt from a logged-in YouTube browser session"
        self._set_status(f"Error: {err}{hint}", ERR)
        self.dl_btn.disabled = False

    def _set_status(self, text, color=None):
        self.status_lbl.text  = text
        self.status_lbl.color = color or MUTED


if __name__ == "__main__":
    FetchApp().run()