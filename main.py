"""
PSX Sample Forge: one-click PlayStation 1 .VAG sample converter.

GUI:  python main.py            (or drop files onto the .exe)
CLI:  python main.py kick.wav pads/ --loop --xfade 20 -r 22050 --wav
"""
import argparse
import json
import os
import queue
import sys
import tempfile
import threading

import core

APP_NAME = "PSX Sample Forge"
VERSION = "2.0"

BG = "#1e1e1e"
PANEL = "#252526"
FIELD = "#2d2d30"
ACCENT = "#007acc"
TEXT = "#ffffff"
MUTED = "#888888"
OK = "#4caf50"
WARN = "#ffb74d"
ERR = "#f44336"

SETTINGS_PATH = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "PSXSampleForge", "settings.json")
DEFAULT_SETTINGS = {
    "rate": core.DEFAULT_RATE,
    "loop": False,
    "loop_start_ms": 0.0,
    "crossfade_ms": 0.0,
    "normalize": False,
    "export_wav": False,
    "out_dir": "",
}


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            settings.update({k: v for k, v in json.load(f).items() if k in DEFAULT_SETTINGS})
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings):
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass


def enable_file_drop(widget, on_drop):
    """Native Windows drag & drop of files onto a Tk window, no extra dependencies."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        WM_DROPFILES = 0x0233
        GWLP_WNDPROC = -4
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        user32.CallWindowProcW.restype = LRESULT
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        shell32.DragFinish.argtypes = [ctypes.c_void_p]
        shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]

        hwnd = widget.winfo_id()
        old_proc = None

        def wnd_proc(h, msg, wparam, lparam):
            if msg == WM_DROPFILES:
                count = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                files = []
                for i in range(count):
                    length = shell32.DragQueryFileW(wparam, i, None, 0)
                    buf = ctypes.create_unicode_buffer(length + 1)
                    shell32.DragQueryFileW(wparam, i, buf, length + 1)
                    files.append(buf.value)
                shell32.DragFinish(wparam)
                widget.after(0, on_drop, files)
                return 0
            return user32.CallWindowProcW(old_proc, h, msg, wparam, lparam)

        callback = WNDPROC(wnd_proc)
        old_proc = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(callback, ctypes.c_void_p))
        shell32.DragAcceptFiles(hwnd, True)
        widget._drop_callback = callback  # keep the ctypes callback alive
        return True
    except Exception:
        return False


class PSXConverterApp:
    def __init__(self, root, initial_files=()):
        import tkinter as tk
        self.tk = tk
        self.root = root
        self.root.title(f"{APP_NAME} {VERSION}")
        # Window size in 96-DPI units, scaled for HiDPI screens
        scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        self.root.geometry(f"{int(560 * scale)}x{int(640 * scale)}")
        self.root.minsize(int(520 * scale), int(600 * scale))
        self.root.configure(bg=BG)

        self.encoder = core.find_encoder()
        self.settings = load_settings()
        self.files = []
        self.events = queue.Queue()
        self.worker = None
        self.preview_path = os.path.join(tempfile.gettempdir(), "psxforge_preview.wav")

        self._setup_styles()
        self._build_ui()
        self.add_paths(initial_files)

        enable_file_drop(self.root, self.add_paths)
        if not self.encoder:
            self.set_status("psxavenc not found: put it into bin/", ERR)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(50, self._poll_events)

    # ---------- UI ----------

    def _setup_styles(self):
        from tkinter import ttk
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("TButton", background="#3e3e42", foreground=TEXT, borderwidth=0, padding=(10, 4))
        style.map("TButton", background=[("active", ACCENT), ("disabled", "#2a2a2a")],
                  foreground=[("disabled", "#666666")])
        style.configure("TCheckbutton", background=BG, foreground=TEXT)
        style.map("TCheckbutton", background=[("active", BG)], indicatorcolor=[("selected", ACCENT)])
        style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT, borderwidth=0)
        style.map("TEntry", fieldbackground=[("disabled", "#262626")], foreground=[("disabled", "#666666")])
        style.configure("TCombobox", fieldbackground=FIELD, background="#3e3e42", foreground=TEXT,
                        arrowcolor=TEXT, borderwidth=0)
        style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)])
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=FIELD, borderwidth=0)

    def _build_ui(self):
        tk = self.tk
        from tkinter import ttk
        s = self.settings

        header = tk.Frame(self.root, bg=BG)
        header.pack(pady=(16, 8))
        tk.Label(header, text="PSX SAMPLE FORGE", bg=BG, fg=ACCENT, font=("Impact", 24)).pack()
        tk.Label(header, text="Any audio  →  PlayStation 1 .VAG", bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack()

        # File list
        list_frame = tk.Frame(self.root, bg=BG)
        list_frame.pack(fill="both", expand=True, padx=20, pady=(8, 4))
        self.listbox = tk.Listbox(list_frame, bg=FIELD, fg=TEXT, bd=0, highlightthickness=0,
                                  selectbackground=ACCENT, activestyle="none", selectmode="extended",
                                  font=("Segoe UI", 9))
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        hint = "Drop audio files or folders here" if os.name == "nt" else "Add audio files or folders"
        self.placeholder = tk.Label(self.listbox, text=hint, bg=FIELD, fg="#5a5a5a", font=("Segoe UI", 10))
        self.listbox.bind("<Delete>", lambda e: self.remove_selected())
        self.listbox.bind("<Double-Button-1>", lambda e: self.preview())

        btns = tk.Frame(self.root, bg=BG)
        btns.pack(fill="x", padx=20, pady=(0, 8))
        self.btn_add = ttk.Button(btns, text="Add files", command=self.select_files)
        self.btn_add.pack(side="left")
        self.btn_folder = ttk.Button(btns, text="Add folder", command=self.select_folder)
        self.btn_folder.pack(side="left", padx=6)
        self.btn_clear = ttk.Button(btns, text="Clear", command=self.clear_files)
        self.btn_clear.pack(side="left")
        self.count_label = ttk.Label(btns, text="", style="Muted.TLabel")
        self.count_label.pack(side="right")

        # Options
        opts = tk.Frame(self.root, bg=BG)
        opts.pack(fill="x", padx=20, pady=4)
        opts.columnconfigure(1, weight=1)
        opts.columnconfigure(3, weight=1)

        ttk.Label(opts, text="Sample rate").grid(row=0, column=0, sticky="w", pady=3)
        self.rate_var = tk.StringVar(value=str(s["rate"]))
        rate_cell = self._unit_cell(opts, "Hz")
        rate_cell.grid(row=0, column=1, sticky="w", padx=8)
        ttk.Combobox(rate_cell, textvariable=self.rate_var, width=8,
                     values=[str(r) for r in core.RATE_PRESETS]).pack(side="left")

        self.normalize_var = tk.BooleanVar(value=s["normalize"])
        ttk.Checkbutton(opts, text="Normalize", variable=self.normalize_var).grid(row=0, column=2, columnspan=2, sticky="w")

        self.loop_var = tk.BooleanVar(value=s["loop"])
        ttk.Checkbutton(opts, text="Loop mode (pads, leads, breaks)", variable=self.loop_var,
                        command=self.update_loop_state).grid(row=1, column=0, columnspan=2, sticky="w", pady=3)
        self.wav_var = tk.BooleanVar(value=s["export_wav"])
        ttk.Checkbutton(opts, text="Also save PSX .wav", variable=self.wav_var).grid(row=1, column=2, columnspan=2, sticky="w")

        ttk.Label(opts, text="Loop start").grid(row=2, column=0, sticky="w", pady=3)
        self.loop_start_var = tk.StringVar(value=_fmt_num(s["loop_start_ms"]))
        cell = self._unit_cell(opts, "ms")
        cell.grid(row=2, column=1, sticky="w", padx=8)
        self.loop_start_entry = ttk.Entry(cell, textvariable=self.loop_start_var, width=8)
        self.loop_start_entry.pack(side="left")

        ttk.Label(opts, text="Crossfade").grid(row=2, column=2, sticky="w")
        self.xfade_var = tk.StringVar(value=_fmt_num(s["crossfade_ms"]))
        cell = self._unit_cell(opts, "ms")
        cell.grid(row=2, column=3, sticky="w", padx=8)
        self.xfade_entry = ttk.Entry(cell, textvariable=self.xfade_var, width=8)
        self.xfade_entry.pack(side="left")

        self.info_label = ttk.Label(opts, text="", style="Muted.TLabel", justify="left")
        self.info_label.grid(row=3, column=0, columnspan=4, sticky="w", pady=(2, 4))

        # Output folder
        out = tk.Frame(self.root, bg=BG)
        out.pack(fill="x", padx=20, pady=4)
        ttk.Label(out, text="Output").pack(side="left")
        self.out_var = tk.StringVar(value=s["out_dir"])
        self.out_label = ttk.Label(out, text="", style="Muted.TLabel")
        self.out_label.pack(side="left", padx=8, fill="x", expand=True)
        ttk.Button(out, text="Reset", command=lambda: self.set_out_dir("")).pack(side="right")
        ttk.Button(out, text="Choose...", command=self.select_out_dir).pack(side="right", padx=6)
        self.set_out_dir(s["out_dir"])

        # Actions
        actions = tk.Frame(self.root, bg=BG)
        actions.pack(pady=(10, 6))
        self.btn_convert = tk.Button(actions, text="CONVERT", command=self.convert,
                                     bg=ACCENT, fg="white", font=("Segoe UI", 12, "bold"), bd=0,
                                     activebackground="#005a9e", activeforeground="white", cursor="hand2",
                                     disabledforeground="#9fc9e6")
        self.btn_convert.pack(side="left", ipadx=36, ipady=6)
        self.btn_preview = ttk.Button(actions, text="▶ Preview", command=self.preview)
        self.btn_preview.pack(side="left", padx=(10, 0), ipady=5)
        if os.name != "nt":
            self.btn_preview.state(["disabled"])

        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.pack(fill="x", padx=20, pady=(6, 2))
        self.status_label = tk.Label(self.root, text="Ready", bg=BG, fg=OK, font=("Segoe UI", 9))
        self.status_label.pack(pady=(2, 12))

        self.update_loop_state()

    # ---------- helpers ----------

    def _unit_cell(self, parent, unit):
        """Frame holding an input (packed later on the left) and a unit label on the right."""
        from tkinter import ttk
        cell = self.tk.Frame(parent, bg=BG)
        ttk.Label(cell, text=unit, style="Muted.TLabel").pack(side="right", padx=(6, 0))
        return cell

    def set_status(self, text, color=OK):
        self.status_label.config(text=text, fg=color)

    def update_loop_state(self):
        state = ["!disabled"] if self.loop_var.get() else ["disabled"]
        self.loop_start_entry.state(state)
        self.xfade_entry.state(state)
        if self.loop_var.get():
            self.info_label.config(text="Loop is aligned to 28-sample SPU blocks, so it repeats seamlessly on hardware.\n"
                                        "Crossfade smooths clicks at the loop point (try 10-50 ms).")
        else:
            self.info_label.config(text="One-shot: for kicks, snares, hats and SFX.\n ")

    def refresh_list(self):
        self.listbox.delete(0, "end")
        for path in self.files:
            self.listbox.insert("end", os.path.basename(path))
        n = len(self.files)
        if n:
            self.placeholder.place_forget()
        else:
            self.placeholder.place(relx=0.5, rely=0.5, anchor="center")
        self.count_label.config(text=f"{n} file{'s' if n != 1 else ''}" if n else "")

    def add_paths(self, paths):
        new = [p for p in core.collect_audio_files(paths) if p not in self.files]
        self.files.extend(new)
        self.refresh_list()
        if new:
            self.set_status(f"Added {len(new)} file{'s' if len(new) != 1 else ''}", OK)
        elif paths:
            self.set_status("No supported audio files found", WARN)

    def remove_selected(self):
        for i in reversed(self.listbox.curselection()):
            del self.files[i]
        self.refresh_list()

    def clear_files(self):
        self.files.clear()
        self.refresh_list()

    def select_files(self):
        from tkinter import filedialog
        patterns = " ".join("*" + ext for ext in core.AUDIO_EXTENSIONS)
        paths = filedialog.askopenfilenames(filetypes=[("Audio files", patterns), ("All files", "*.*")])
        self.add_paths(paths)

    def select_folder(self):
        from tkinter import filedialog
        folder = filedialog.askdirectory()
        if folder:
            self.add_paths([folder])

    def select_out_dir(self):
        from tkinter import filedialog
        folder = filedialog.askdirectory()
        if folder:
            self.set_out_dir(folder)

    def set_out_dir(self, folder):
        self.out_var.set(folder)
        self.out_label.config(text=folder if folder else "next to source files")

    def read_options(self):
        """Validate the form, returns kwargs for core.convert_file or None."""
        from tkinter import messagebox
        try:
            rate = int(float(self.rate_var.get()))
            loop_start = float(self.loop_start_var.get() or 0)
            xfade = float(self.xfade_var.get() or 0)
        except ValueError:
            messagebox.showerror("Invalid value", "Sample rate, loop start and crossfade must be numbers.")
            return None
        if not 1000 <= rate <= core.MAX_RATE:
            messagebox.showerror("Invalid value", f"Sample rate must be between 1000 and {core.MAX_RATE} Hz.")
            return None
        if loop_start < 0 or xfade < 0:
            messagebox.showerror("Invalid value", "Loop start and crossfade can't be negative.")
            return None
        options = {
            "rate": rate,
            "normalize": self.normalize_var.get(),
            "loop": self.loop_var.get(),
            "loop_start_ms": loop_start,
            "crossfade_ms": xfade,
            "export_wav": self.wav_var.get(),
            "out_dir": self.out_var.get() or None,
        }
        self.settings.update(options, out_dir=self.out_var.get())
        save_settings(self.settings)
        return options

    def set_busy(self, busy):
        state = ["disabled"] if busy else ["!disabled"]
        for b in (self.btn_add, self.btn_folder, self.btn_clear):
            b.state(state)
        if os.name == "nt":
            self.btn_preview.state(state)
        self.btn_convert.config(state="disabled" if busy else "normal")

    # ---------- actions ----------

    def convert(self):
        from tkinter import messagebox
        if not self.files:
            messagebox.showinfo(APP_NAME, "Add some audio files first (or drop them onto the window).")
            return
        if not self.encoder:
            messagebox.showerror("Encoder missing", "psxavenc not found.\nPut psxavenc.exe into the bin/ folder.")
            return
        options = self.read_options()
        if options is None:
            return
        self.stop_preview()
        self.set_busy(True)
        self.progress.config(maximum=len(self.files), value=0)
        files = list(self.files)
        self.worker = threading.Thread(target=self._convert_worker, args=(files, options), daemon=True)
        self.worker.start()

    def _convert_worker(self, files, options):
        errors = []
        for i, path in enumerate(files):
            self.events.put(("status", f"Converting {os.path.basename(path)}  ({i + 1}/{len(files)})", WARN))
            try:
                core.convert_file(path, self.encoder, **options)
            except Exception as e:
                errors.append((path, str(e)))
            self.events.put(("progress", i + 1))
        self.events.put(("done", len(files), errors, options["out_dir"] or os.path.dirname(files[0])))

    def preview(self):
        """Encode the selected file with current settings, decode it back and play it."""
        from tkinter import messagebox
        if os.name != "nt" or (self.worker and self.worker.is_alive()):
            return
        if not self.files:
            return
        if not self.encoder:
            messagebox.showerror("Encoder missing", "psxavenc not found.")
            return
        sel = self.listbox.curselection()
        path = self.files[sel[0] if sel else 0]
        options = self.read_options()
        if options is None:
            return
        self.stop_preview()
        self.set_busy(True)
        self.set_status(f"Rendering preview: {os.path.basename(path)}", WARN)
        self.worker = threading.Thread(target=self._preview_worker, args=(path, options), daemon=True)
        self.worker.start()

    def _preview_worker(self, path, options):
        import soundfile as sf
        vag = self.preview_path[:-4] + ".vag"
        try:
            data, sr = sf.read(path, dtype="float32", always_2d=True)
            samples, loop_start = core.prepare_audio(data, sr, options["rate"], options["normalize"], options["loop"],
                                                     options["loop_start_ms"], options["crossfade_ms"])
            core.encode_vag(samples, options["rate"], vag, self.encoder, options["loop"], loop_start)
            decoded, rate, vag_loop = core.decode_vag(vag)
            core.write_wav(self.preview_path, core.render_preview(decoded, vag_loop, rate), rate)
            self.events.put(("play", os.path.basename(path)))
        except Exception as e:
            self.events.put(("error", str(e)))

    def stop_preview(self):
        if os.name == "nt":
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)

    def _poll_events(self):
        from tkinter import messagebox
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "status":
                    self.set_status(event[1], event[2])
                elif kind == "progress":
                    self.progress.config(value=event[1])
                elif kind == "play":
                    import winsound
                    self.set_busy(False)
                    self.set_status(f"Playing PSX preview: {event[1]}", OK)
                    winsound.PlaySound(self.preview_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                elif kind == "error":
                    self.set_busy(False)
                    self.set_status("Preview failed", ERR)
                    messagebox.showerror("Error", event[1])
                elif kind == "done":
                    _, total, errors, folder = event
                    self.set_busy(False)
                    if errors:
                        self.set_status(f"Done with errors: {total - len(errors)}/{total} converted", ERR)
                        details = "\n\n".join(f"{os.path.basename(p)}:\n{msg}" for p, msg in errors[:10])
                        messagebox.showerror("Some files failed", details)
                    else:
                        self.set_status(f"Done: {total} file{'s' if total != 1 else ''} → {folder}", OK)
        except queue.Empty:
            pass
        self.root.after(50, self._poll_events)

    def on_close(self):
        self.stop_preview()
        for path in (self.preview_path, self.preview_path[:-4] + ".vag"):
            try:
                os.remove(path)
            except OSError:
                pass
        self.root.destroy()


def _fmt_num(value):
    return str(int(value)) if float(value).is_integer() else str(value)


def run_gui(files=()):
    import tkinter as tk
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on HiDPI screens
        except Exception:
            pass
    root = tk.Tk()
    PSXConverterApp(root, files)
    root.mainloop()


def run_cli(args):
    files = core.collect_audio_files(args.inputs)
    if not files:
        print("No supported audio files found.", file=sys.stderr)
        return 1
    encoder = core.find_encoder()
    if not encoder:
        print("psxavenc not found. Put it into bin/ or on PATH.", file=sys.stderr)
        return 1
    failed = 0
    for path in files:
        try:
            info = core.convert_file(path, encoder, rate=args.rate, normalize=args.normalize, loop=args.loop,
                                     loop_start_ms=args.loop_start, crossfade_ms=args.xfade,
                                     export_wav=args.wav, out_dir=args.output)
            loop = f", loop @ {info['loop_start']} smp" if info["loop_start"] is not None else ""
            print(f"OK   {path} -> {info['vag']} ({info['bytes']} bytes{loop})")
        except Exception as e:
            failed += 1
            print(f"FAIL {path}: {e}", file=sys.stderr)
    print(f"{len(files) - failed}/{len(files)} converted.")
    return 1 if failed else 0


def parse_args(argv):
    p = argparse.ArgumentParser(prog="psx-forge", description=f"{APP_NAME} {VERSION}: convert audio to PlayStation 1 .VAG")
    p.add_argument("inputs", nargs="*", help="audio files or folders")
    p.add_argument("-r", "--rate", type=int, default=core.DEFAULT_RATE, help="sample rate in Hz (default 22050)")
    p.add_argument("-l", "--loop", action="store_true", help="loop mode: block-aligned seamless loop")
    p.add_argument("--loop-start", type=float, default=0.0, metavar="MS", help="loop start in ms (default 0)")
    p.add_argument("--xfade", type=float, default=0.0, metavar="MS", help="loop crossfade in ms (default 0)")
    p.add_argument("-n", "--normalize", action="store_true", help="peak normalize to -0.3 dBFS")
    p.add_argument("-w", "--wav", action="store_true", help="also save the decoded PSX sound as .psx.wav")
    p.add_argument("-o", "--output", metavar="DIR", help="output folder (default: next to source)")
    p.add_argument("--gui", action="store_true", help="open the GUI with these files")
    p.add_argument("-V", "--version", action="version", version=f"{APP_NAME} {VERSION}")
    return p.parse_args(argv)


def main():
    args = parse_args(sys.argv[1:])
    # Windowed exe (or pythonw) has no stdout: files dropped onto it open in the GUI
    if not args.inputs or args.gui or sys.stdout is None:
        run_gui(args.inputs)
        return 0
    return run_cli(args)


if __name__ == "__main__":
    sys.exit(main())
