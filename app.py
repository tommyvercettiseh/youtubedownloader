import json
import os
import queue
import re
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
LEGACY_COOKIE_DIR = Path.home() / "Videos" / "YouTubeDownloads" / "Cookies"
COOKIE_JSON = LEGACY_COOKIE_DIR / "cookies.json"
COOKIE_TXT = LEGACY_COOKIE_DIR / "cookies.txt"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def safe_name(text: str) -> str:
    forbidden = '<>:"/\\|?*'
    clean = ''.join('_' if c in forbidden else c for c in text).strip()
    return clean[:140] or "video"


def convert_json_to_netscape(json_file: Path, output_file: Path) -> bool:
    if not json_file.exists():
        return False
    try:
        with json_file.open("r", encoding="utf-8") as f:
            cookies = json.load(f)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n\n")
            for cookie in cookies:
                domain = cookie.get("domain", "")
                flag = "TRUE" if str(domain).startswith(".") else "FALSE"
                path = cookie.get("path", "/")
                secure = "TRUE" if cookie.get("secure") else "FALSE"
                expiry = int(cookie.get("expirationDate", 0) or 0)
                name = cookie.get("name", "")
                value = cookie.get("value", "")
                f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expiry}\t{name}\t{value}\n")
        return True
    except Exception:
        return False


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1480x900")
        self.minsize(1120, 720)

        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker = None
        self.proc = None
        self.current_entries = []

        self.url_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(DEFAULT_OUTPUT))
        self.quality_var = tk.StringVar(value="1080p")
        self.status_var = tk.StringVar(value="Plak een YouTube-link om te beginnen")
        self.current_var = tk.StringVar(value="Nog geen download gestart")
        self.counter_var = tk.StringVar(value="0 / 0 voltooid")

        if COOKIE_JSON.exists():
            convert_json_to_netscape(COOKIE_JSON, COOKIE_TXT)

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
        ctk.CTkLabel(info, text="Geen ondertiteling. Per video wordt gezocht naar een expliciete [nl] audiostream.", anchor="w", text_color="#aeb7c2").grid(row=1, column=0, padx=18, pady=(0, 14), sticky="ew")

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
        for col, label in [("nr", "#"), ("title", "Titel"), ("audio", "Audio"), ("status", "Status"), ("progress", "Voortgang"), ("size", "Grootte")]:
            self.tree.heading(col, text=label)
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

    def _cookie_args(self):
        if COOKIE_JSON.exists() and not COOKIE_TXT.exists():
            convert_json_to_netscape(COOKIE_JSON, COOKIE_TXT)
        return ["--cookies", str(COOKIE_TXT)] if COOKIE_TXT.exists() else []

    def _base_cmd(self, use_cookies=False):
        cmd = [sys.executable, "-m", "yt_dlp"]
        if use_cookies:
            cmd += self._cookie_args()
            cmd += ["--extractor-args", "youtube:player_client=default,web_embedded"]
        return cmd

    def analyse(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Geen URL", "Plak eerst een YouTube-link.")
            return
        self._set_busy(True)
        self.status_var.set("Link analyseren…")
        self.worker = threading.Thread(target=self._analyse_worker, args=(url,), daemon=True)
        self.worker.start()

    def _extract_info_with_fallback(self, url, flat=True, first_only=False):
        attempts = [False, True] if COOKIE_TXT.exists() or COOKIE_JSON.exists() else [False]
        last_exc = None
        for use_cookies in attempts:
            try:
                opts = {"quiet": True, "skip_download": True, "extract_flat": flat}
                if first_only:
                    opts["playlist_items"] = "1"
                if use_cookies:
                    if COOKIE_JSON.exists() and not COOKIE_TXT.exists():
                        convert_json_to_netscape(COOKIE_JSON, COOKIE_TXT)
                    if COOKIE_TXT.exists():
                        opts["cookiefile"] = str(COOKIE_TXT)
                    opts["extractor_args"] = {"youtube": {"player_client": ["default", "web_embedded"]}}
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(url, download=False)
            except Exception as exc:
                last_exc = exc
        raise last_exc

    def _analyse_worker(self, url):
        try:
            info = self._extract_info_with_fallback(url, flat="in_playlist")
            self.events.put(("analysed", info))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _is_playlist(self, info):
        return info.get("_type") == "playlist" or bool(info.get("entries"))

    def _find_dutch_audio_format(self, video_url):
        attempts = [False, True] if COOKIE_TXT.exists() or COOKIE_JSON.exists() else [False]
        diagnostics = []

        for use_cookies in attempts:
            cmd = [*self._base_cmd(use_cookies), "-F", video_url]
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            diagnostics.append(output)

            candidates = []
            for line in output.splitlines():
                lower = line.lower()
                is_audio = "audio only" in lower
                is_dutch = (
                    bool(re.search(r"\[nl(?:[-_][a-z]+)?\]", line, re.IGNORECASE))
                    or "dutch" in lower
                    or "nederlands" in lower
                )
                if is_audio and is_dutch:
                    match = re.match(r"\s*([^\s]+)", line)
                    if match:
                        candidates.append((match.group(1), line.strip()))

            if candidates:
                return candidates[0][0], candidates[0][1], use_cookies

            # Als de pagina-reload fout optreedt, probeer automatisch de volgende methode.
            if "page needs to be reloaded" in output.lower():
                continue

        return None, "\n\n".join(diagnostics), False

    def _height_filter(self):
        q = self.quality_var.get()
        if q == "720p":
            return "[height<=720]"
        if q == "1080p":
            return "[height<=1080]"
        return ""

    def _get_playlist_entries(self, url, first_only=False):
        info = self._extract_info_with_fallback(url, flat=True, first_only=first_only)
        if info.get("entries"):
            entries = [e for e in info.get("entries", []) if e]
        else:
            entries = [info]
        return info, entries

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
        self.current_var.set("Nederlandse audiostream zoeken…")
        self.worker = threading.Thread(target=self._download_worker, args=(url, playlist, test_first), daemon=True)
        self.worker.start()

    def _download_worker(self, url, playlist, test_first):
        try:
            _, entries = self._get_playlist_entries(url, first_only=test_first)
            if not entries:
                raise RuntimeError("Geen video's gevonden.")
            if test_first:
                entries = entries[:1]

            self.current_entries = entries
            total = len(entries)
            out_dir = Path(self.output_var.get())
            out_dir.mkdir(parents=True, exist_ok=True)

            for pos, entry in enumerate(entries, 1):
                if self.cancel_event.is_set():
                    raise RuntimeError("Download gestopt door gebruiker")

                video_id = entry.get("id")
                if not video_id:
                    continue
                video_url = entry.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"
                title = entry.get("title") or f"Video {pos}"
                filename = f"{pos:02d} - {safe_name(title)}.mp4" if (playlist and not test_first) else f"{safe_name(title)}.mp4"
                output_path = out_dir / filename

                if output_path.exists():
                    self.events.put(("progress", pos, total, title, "finished", 100.0, self._human_size(output_path.stat().st_size), "Nederlands"))
                    continue

                self.events.put(("checking", pos, total, title))
                audio_format, diagnostic, used_cookies = self._find_dutch_audio_format(video_url)
                if not audio_format:
                    audio_lines = [line for line in diagnostic.splitlines() if "audio only" in line.lower()]
                    preview = "\n".join(audio_lines[-12:])
                    raise RuntimeError(
                        f"Geen [nl] audio-only stream gevonden bij {pos:02d}. {title}.\n\n"
                        f"Laatste audioformats:\n{preview or 'Geen audioformatregels gevonden.'}"
                    )

                self.events.put(("audio_found", pos, total, title, audio_format))
                self._download_one(video_url, output_path, audio_format, pos, total, title, used_cookies)

            self.events.put(("done", "Testvideo gedownload" if test_first else "Playlist voltooid"))
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            self.proc = None

    def _download_one(self, video_url, output_path, audio_format, index, total, title, use_cookies=False):
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        selector = f"bv*{self._height_filter()}+{audio_format}"
        cmd = [
            *self._base_cmd(use_cookies),
            "--newline",
            "--no-part",
            "--fragment-retries", "15",
            "--retries", "10",
            "--sleep-interval", "2",
            "--max-sleep-interval", "5",
            "--ffmpeg-location", ffmpeg,
            "--merge-output-format", "mp4",
            "--no-write-subs",
            "--no-write-auto-subs",
            "-f", selector,
            "-o", str(output_path),
            video_url,
        ]

        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        last_pct = 0.0
        size = ""
        tail = []
        for line in self.proc.stdout:
            tail.append(line.rstrip())
            tail = tail[-20:]
            if self.cancel_event.is_set():
                self.proc.terminate()
                raise RuntimeError("Download gestopt door gebruiker")
            pct_match = re.search(r"\[download\]\s+([0-9.]+)%", line)
            if pct_match:
                last_pct = float(pct_match.group(1))
            size_match = re.search(r"of\s+~?\s*([0-9.]+\s*[KMGTP]i?B)", line, re.IGNORECASE)
            if size_match:
                size = size_match.group(1)
            self.events.put(("progress", index, total, title, "downloading", last_pct, size, f"NL · {audio_format}"))

        rc = self.proc.wait()
        if rc != 0:
            raise RuntimeError("yt-dlp stopte met foutcode %s bij %s\n\n%s" % (rc, title, "\n".join(tail[-8:])))

        final_size = self._human_size(output_path.stat().st_size) if output_path.exists() else size
        self.events.put(("progress", index, total, title, "finished", 100.0, final_size, f"NL · {audio_format}"))
        self.proc = None

    @staticmethod
    def _human_size(n):
        n = float(n)
        for unit in ["B", "KB", "MB", "GB"]:
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    def cancel_download(self):
        self.cancel_event.set()
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.current_var.set("Download stoppen…")

    def _upsert_row(self, index, title, audio, status, pct, size):
        iid = str(index)
        values = (f"{int(index):02d}", title, audio, status, f"{pct:.0f}%", size)
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
                    if self._is_playlist(info):
                        count = len([e for e in info.get("entries", []) if e])
                        self.status_var.set(f"{info.get('title', 'Playlist')}  •  {count} video's")
                    else:
                        self.status_var.set(info.get("title", "Video gevonden"))
                    self._set_busy(False)

                elif kind == "checking":
                    _, idx, total, title = event
                    self.current_var.set(f"{idx:02d}. NL audio controleren: {title}")
                    self._upsert_row(idx, title, "Zoeken…", "Controleren", 0, "")
                    self.counter_var.set(f"{idx - 1} / {total} voltooid")

                elif kind == "audio_found":
                    _, idx, total, title, audio_id = event
                    self.current_var.set(f"{idx:02d}. Nederlandse audio gevonden ({audio_id}) · downloaden…")
                    self._upsert_row(idx, title, f"NL · {audio_id}", "Gevonden", 0, "")

                elif kind == "progress":
                    _, idx, total, title, status, pct, size, audio = event
                    label = "Voltooid" if status == "finished" else "Bezig"
                    self._upsert_row(idx, title, audio, label, pct, size)
                    overall = ((idx - 1) + pct / 100) / max(total, 1)
                    self.progress.set(min(max(overall, 0), 1))
                    self.current_var.set(f"{idx:02d}. {title}  •  {pct:.0f}%")
                    completed = idx if status == "finished" else max(idx - 1, 0)
                    self.counter_var.set(f"{completed} / {total} voltooid")

                elif kind == "done":
                    self.progress.set(1)
                    self.current_var.set(event[1])
                    self.status_var.set("Klaar ✅ Open de uitvoermap en controleer de Nederlandse gesproken audio.")
                    self._set_busy(False)

                elif kind == "error":
                    self._set_busy(False)
                    self.status_var.set("Download niet voltooid")
                    messagebox.showerror("YouTube Downloader", event[1])

        except queue.Empty:
            pass
        self.after(100, self._poll_events)


if __name__ == "__main__":
    App().mainloop()
