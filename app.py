import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
import imageio_ffmpeg
import yt_dlp

APP_TITLE = "YouTube Downloader"
DEFAULT_OUTPUT = Path.home() / "Downloads" / "YouTube Downloads"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def safe_name(text: str) -> str:
    forbidden = '<>:"/\\|?*'
    return ''.join('_' if c in forbidden else c for c in text).strip()


class YTDLLogger:
    def __init__(self, app):
        self.app = app

    def debug(self, msg):
        if msg.startswith('[download]'):
            self.app.events.put(("log", msg))

    def warning(self, msg):
        self.app.events.put(("log", f"Waarschuwing: {msg}"))

    def error(self, msg):
        self.app.events.put(("log", f"Fout: {msg}"))


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1480x900")
        self.minsize(1120, 720)

        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker = None
        self.playlist_info = None
        self.current_entries = []

        self.url_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(DEFAULT_OUTPUT))
        self.quality_var = tk.StringVar(value="1080p")
        self.status_var = tk.StringVar(value="Plak een YouTube-link om te beginnen")
        self.current_var = tk.StringVar(value="Nog geen download gestart")
        self.counter_var = tk.StringVar(value="0 / 0 voltooid")

        self._build_ui()
        self.after(100, self._poll_events)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        main = ctk.CTkFrame(self, corner_radius=0)
        main.grid(row=0, column=0, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(4, weight=1)

        titlebar = ctk.CTkFrame(main, fg_color="transparent")
        titlebar.grid(row=0, column=0, padx=24, pady=(20, 8), sticky="ew")
        ctk.CTkLabel(titlebar, text="YouTube Downloader", font=ctk.CTkFont(size=26, weight="bold")).pack(side="left")
        ctk.CTkLabel(titlebar, text="Nederlandse gesproken audio", text_color="#55c2ff", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left", padx=16)

        input_card = ctk.CTkFrame(main)
        input_card.grid(row=1, column=0, padx=24, pady=8, sticky="ew")
        input_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(input_card, text="YouTube video of playlist", anchor="w", font=ctk.CTkFont(size=15, weight="bold")).grid(row=0, column=0, columnspan=4, padx=18, pady=(16, 7), sticky="ew")
        self.url_entry = ctk.CTkEntry(input_card, textvariable=self.url_var, height=42, placeholder_text="https://www.youtube.com/watch?v=... of playlist?list=...")
        self.url_entry.grid(row=1, column=0, columnspan=3, padx=(18, 8), pady=(0, 12), sticky="ew")
        ctk.CTkButton(input_card, text="Analyseer", width=120, height=42, command=self.analyse).grid(row=1, column=3, padx=(0, 18), pady=(0, 12))

        settings = ctk.CTkFrame(input_card, fg_color="transparent")
        settings.grid(row=2, column=0, columnspan=4, padx=18, pady=(0, 16), sticky="ew")
        settings.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(settings, text="Uitvoermap").grid(row=0, column=0, padx=(0, 10), sticky="w")
        ctk.CTkEntry(settings, textvariable=self.output_var, height=36).grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(settings, text="Bladeren", width=100, command=self.choose_output).grid(row=0, column=2, padx=8)
        ctk.CTkButton(settings, text="Open map", width=100, command=self.open_output).grid(row=0, column=3)
        ctk.CTkLabel(settings, text="Kwaliteit").grid(row=0, column=4, padx=(20, 8))
        ctk.CTkOptionMenu(settings, values=["720p", "1080p", "Beste"], variable=self.quality_var, width=110).grid(row=0, column=5)

        info = ctk.CTkFrame(main)
        info.grid(row=2, column=0, padx=24, pady=8, sticky="ew")
        info.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(info, textvariable=self.status_var, anchor="w", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, padx=18, pady=(14, 4), sticky="ew")
        ctk.CTkLabel(info, text="De app downloadt géén ondertiteling. Alleen een Nederlandse audiotrack wordt geaccepteerd.", anchor="w", text_color="#aeb7c2").grid(row=1, column=0, padx=18, pady=(0, 14), sticky="ew")

        actions = ctk.CTkFrame(main, fg_color="transparent")
        actions.grid(row=3, column=0, padx=24, pady=8, sticky="ew")
        self.test_btn = ctk.CTkButton(actions, text="▶  Download testvideo", height=44, width=220, command=self.download_test)
        self.test_btn.pack(side="left")
        self.playlist_btn = ctk.CTkButton(actions, text="☰  Download hele playlist", height=44, width=220, fg_color="#2c3b4d", command=self.download_playlist)
        self.playlist_btn.pack(side="left", padx=10)
        self.cancel_btn = ctk.CTkButton(actions, text="Stop", height=44, width=100, fg_color="#7a2b2b", command=self.cancel_download, state="disabled")
        self.cancel_btn.pack(side="left")

        downloads = ctk.CTkFrame(main)
        downloads.grid(row=4, column=0, padx=24, pady=(8, 24), sticky="nsew")
        downloads.grid_columnconfigure(0, weight=1)
        downloads.grid_rowconfigure(3, weight=1)

        top = ctk.CTkFrame(downloads, fg_color="transparent")
        top.grid(row=0, column=0, padx=18, pady=(16, 4), sticky="ew")
        ctk.CTkLabel(top, text="Downloadstatus", font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")
        ctk.CTkLabel(top, textvariable=self.counter_var, text_color="#aeb7c2").pack(side="right")

        ctk.CTkLabel(downloads, textvariable=self.current_var, anchor="w").grid(row=1, column=0, padx=18, pady=(6, 4), sticky="ew")
        self.progress = ctk.CTkProgressBar(downloads, height=12)
        self.progress.grid(row=2, column=0, padx=18, pady=(0, 12), sticky="ew")
        self.progress.set(0)

        table_frame = ctk.CTkFrame(downloads, fg_color="transparent")
        table_frame.grid(row=3, column=0, padx=18, pady=(0, 18), sticky="nsew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        cols = ("nr", "title", "audio", "status", "progress", "size")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=15)
        self.tree.heading("nr", text="#")
        self.tree.heading("title", text="Titel")
        self.tree.heading("audio", text="Audio")
        self.tree.heading("status", text="Status")
        self.tree.heading("progress", text="Voortgang")
        self.tree.heading("size", text="Grootte")
        self.tree.column("nr", width=45, anchor="center")
        self.tree.column("title", width=600)
        self.tree.column("audio", width=150)
        self.tree.column("status", width=120)
        self.tree.column("progress", width=110, anchor="center")
        self.tree.column("size", width=100, anchor="e")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

    def choose_output(self):
        folder = filedialog.askdirectory(initialdir=self.output_var.get())
        if folder:
            self.output_var.set(folder)

    def open_output(self):
        path = Path(self.output_var.get())
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self.test_btn.configure(state=state)
        self.playlist_btn.configure(state=state)
        self.cancel_btn.configure(state="normal" if busy else "disabled")

    def analyse(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Geen URL", "Plak eerst een YouTube-link.")
            return
        self._set_busy(True)
        self.status_var.set("Link analyseren…")
        self.worker = threading.Thread(target=self._analyse_worker, args=(url,), daemon=True)
        self.worker.start()

    def _analyse_worker(self, url):
        try:
            opts = {"quiet": True, "skip_download": True, "extract_flat": "in_playlist"}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            self.events.put(("analysed", info))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _is_playlist(self, info):
        return info.get("_type") == "playlist" or bool(info.get("entries"))

    def _audio_languages(self, info):
        langs = []
        for f in info.get("formats", []) or []:
            if f.get("acodec") and f.get("acodec") != "none":
                lang = (f.get("language") or "").strip()
                if lang and lang not in langs:
                    langs.append(lang)
        return langs

    def _has_dutch_audio(self, info):
        langs = self._audio_languages(info)
        return any(lang.lower().startswith("nl") or "dutch" in lang.lower() for lang in langs)

    def _format_selector(self):
        q = self.quality_var.get()
        height = "720" if q == "720p" else "1080" if q == "1080p" else None
        vh = f"[height<={height}]" if height else ""
        # Prioriteit: expliciete Nederlandse audiotrack. Geen Engelse fallback.
        return f"bv*{vh}+ba[language^=nl]/b{vh}[language^=nl]"

    def _download_opts(self, playlist: bool):
        out = Path(self.output_var.get())
        out.mkdir(parents=True, exist_ok=True)
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        template = str(out / ("%(playlist_index)02d - %(title)s.%(ext)s" if playlist else "%(title)s.%(ext)s"))
        return {
            "format": self._format_selector(),
            "merge_output_format": "mp4",
            "outtmpl": template,
            "ffmpeg_location": ffmpeg,
            "noplaylist": not playlist,
            "ignoreerrors": False,
            "continuedl": True,
            "overwrites": False,
            "writethumbnail": False,
            "writesubtitles": False,
            "writeautomaticsub": False,
            "logger": YTDLLogger(self),
            "progress_hooks": [self._progress_hook],
            "quiet": True,
        }

    def _progress_hook(self, d):
        if self.cancel_event.is_set():
            raise RuntimeError("Download gestopt door gebruiker")
        status = d.get("status")
        info = d.get("info_dict", {})
        title = info.get("title", "Onbekende video")
        index = info.get("playlist_index") or 1
        total = info.get("playlist_count") or len(self.current_entries) or 1
        downloaded = d.get("downloaded_bytes") or 0
        total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        pct = (downloaded / total_bytes * 100) if total_bytes else 0
        size = self._human_size(total_bytes) if total_bytes else ""
        self.events.put(("progress", index, total, title, status, pct, size))

    @staticmethod
    def _human_size(n):
        for unit in ["B", "KB", "MB", "GB"]:
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    def download_test(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Geen URL", "Plak eerst een YouTube-link.")
            return
        self._start_download(url, playlist=False, test_first=True)

    def download_playlist(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Geen URL", "Plak eerst een playlist-link.")
            return
        self._start_download(url, playlist=True, test_first=False)

    def _start_download(self, url, playlist, test_first):
        self.cancel_event.clear()
        self._set_busy(True)
        self.progress.set(0)
        self.current_var.set("Nederlandse gesproken audio controleren…")
        self.worker = threading.Thread(target=self._download_worker, args=(url, playlist, test_first), daemon=True)
        self.worker.start()

    def _download_worker(self, url, playlist, test_first):
        try:
            # Bij een playlist is test = alleen eerste item.
            probe_opts = {"quiet": True, "skip_download": True, "playlist_items": "1" if test_first else None}
            with yt_dlp.YoutubeDL(probe_opts) as ydl:
                probe = ydl.extract_info(url, download=False)

            candidate = probe
            if probe.get("entries"):
                entries = [e for e in probe.get("entries", []) if e]
                if not entries:
                    raise RuntimeError("Geen video's in de playlist gevonden.")
                candidate = entries[0]
                if not candidate.get("formats") and candidate.get("webpage_url"):
                    with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
                        candidate = ydl.extract_info(candidate["webpage_url"], download=False)

            langs = self._audio_languages(candidate)
            if not self._has_dutch_audio(candidate):
                shown = ", ".join(langs) if langs else "geen taalmetadata"
                raise RuntimeError(
                    "Geen expliciete Nederlandse audiotrack gevonden voor de testvideo. "
                    f"Gedetecteerd: {shown}. De app downloadt bewust geen andere taal."
                )

            actual_playlist = playlist and not test_first
            opts = self._download_opts(actual_playlist)
            if test_first:
                opts["playlist_items"] = "1"
                opts["noplaylist"] = False
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            self.events.put(("done", "Testvideo gedownload" if test_first else "Playlist voltooid"))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def cancel_download(self):
        self.cancel_event.set()
        self.current_var.set("Download stoppen…")

    def _upsert_row(self, index, title, status, pct, size):
        iid = str(index)
        values = (f"{int(index):02d}", title, "Nederlands", status, f"{pct:.0f}%", size)
        if self.tree.exists(iid):
            self.tree.item(iid, values=values)
        else:
            self.tree.insert("", "end", iid=iid, values=values)

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "analysed":
                    info = event[1]
                    self.playlist_info = info
                    if self._is_playlist(info):
                        count = len([e for e in info.get("entries", []) if e])
                        self.status_var.set(f"{info.get('title', 'Playlist')}  •  {count} video's")
                    else:
                        self.status_var.set(info.get("title", "Video gevonden"))
                    self._set_busy(False)
                elif kind == "progress":
                    _, idx, total, title, status, pct, size = event
                    label = "Voltooid" if status == "finished" else "Bezig"
                    if status == "finished":
                        pct = 100
                    self._upsert_row(idx, title, label, pct, size)
                    overall = ((idx - 1) + pct / 100) / max(total, 1)
                    self.progress.set(min(max(overall, 0), 1))
                    self.current_var.set(f"{int(idx):02d}. {title}  •  {pct:.0f}%")
                    completed = int(idx) if status == "finished" else max(int(idx) - 1, 0)
                    self.counter_var.set(f"{completed} / {int(total)} voltooid")
                elif kind == "done":
                    self.progress.set(1)
                    self.current_var.set(event[1])
                    self.status_var.set("Klaar ✅  Open de uitvoermap en speel de testvideo af.")
                    self._set_busy(False)
                elif kind == "error":
                    self._set_busy(False)
                    self.status_var.set("Download niet gestart")
                    messagebox.showerror("YouTube Downloader", event[1])
                elif kind == "log":
                    pass
        except queue.Empty:
            pass
        self.after(100, self._poll_events)


if __name__ == "__main__":
    App().mainloop()
