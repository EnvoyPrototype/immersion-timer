"""
Immersion Timer  -  a native Windows desktop focus/break timer.

Run by double-clicking this file (the .pyw extension launches it with no
console window). Requires only Python 3 with its standard library; nothing
to install.

Features
  - Focus / Break modes (defaults: 20 min focus, 10 min break)
  - Settings to change the defaults, the alarm sound, and auto-start
  - A 5-second alarm when a timer runs out, with a flashing clock and a
    flashing taskbar button (and the window is raised to the front)
  - "Focused today" total that persists across restarts (with a reset),
    plus a per-session total
  - Optional auto-start of the next phase when one ends
  - Clicking "Break" during a focus session ends it early, logs the
    elapsed focus time, and rolls into a break

Preferences and the daily total are saved to:
    %APPDATA%\\ImmersionTimer\\state.json
"""

import os
import sys
import json
import time
import datetime
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox

try:
    import winsound  # Windows only; used for the alarm
    HAVE_WINSOUND = True
except ImportError:  # pragma: no cover - non-Windows fallback
    HAVE_WINSOUND = False

try:
    import ctypes      # Windows only; used to flash the taskbar button
    from ctypes import wintypes
    HAVE_CTYPES = True
except ImportError:  # pragma: no cover
    HAVE_CTYPES = False

# ---- Palette ----
BG       = "#0f1419"
PANEL    = "#1a2029"
PANEL2   = "#232b36"
TEXT     = "#e7ecf3"
MUTED    = "#8b97a7"
LINE     = "#2c3744"
FOCUS    = "#4f9eff"
FOCUSDIM = "#2d5a8f"
BREAK    = "#2ec28a"
BREAKDIM = "#1d6e51"
DANGER   = "#ff6b6b"

# alarm-sound choices -> Windows system alias (None = silent, flash only)
ALARM_CHOICES = ["Soft", "Standard", "Silent"]
ALARM_ALIAS = {
    "Soft": "SystemAsterisk",
    "Standard": "SystemExclamation",
    "Silent": None,
}


def state_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "ImmersionTimer")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        folder = os.path.expanduser("~")
    return os.path.join(folder, "state.json")


def resource_path(rel):
    """Path to a bundled resource, working both as .pyw and as a PyInstaller exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def today_str():
    return datetime.date.today().isoformat()


class ImmersionTimer:
    def __init__(self, root):
        self.root = root

        # ---- Defaults, then load saved preferences ----
        self.focus_min = 20
        self.break_min = 10
        self.auto_start = False
        self.alarm = "Standard"
        self.daily_date = today_str()
        self.daily_seconds = 0.0       # persistent focus total for today
        self._load_state()

        # ---- Session state ----
        self.mode = "focus"
        self.remaining = self.focus_min * 60.0
        self.running = False
        self.end_at = 0.0
        self.focus_elapsed = 0.0       # focus seconds in current run, not yet logged
        self.session_focus = 0.0       # focus logged since this launch
        self.sessions = 0              # focus sessions completed this launch

        self._tick_job = None
        self._alarm_job = None
        self._flash_job = None
        self._sound_job = None
        self._flash_on = False
        self._flashing_taskbar = False

        self._build_ui()
        self.render()

    # --------------------------------------------------- persistence
    def _load_state(self):
        try:
            with open(state_path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        self.focus_min = self._clamp_int(data.get("focus_min"), self.focus_min)
        self.break_min = self._clamp_int(data.get("break_min"), self.break_min)
        self.auto_start = bool(data.get("auto_start", self.auto_start))
        if data.get("alarm") in ALARM_CHOICES:
            self.alarm = data["alarm"]
        # daily total only counts if it's still the same calendar day
        if data.get("daily_date") == today_str():
            try:
                self.daily_seconds = float(data.get("daily_seconds", 0) or 0)
            except (TypeError, ValueError):
                self.daily_seconds = 0.0
            self.daily_date = data["daily_date"]

    @staticmethod
    def _clamp_int(value, fallback):
        try:
            v = int(value)
            if 1 <= v <= 180:
                return v
        except (TypeError, ValueError):
            pass
        return fallback

    def _save_state(self):
        data = {
            "focus_min": self.focus_min,
            "break_min": self.break_min,
            "auto_start": self.auto_start,
            "alarm": self.alarm,
            "daily_date": self.daily_date,
            "daily_seconds": round(self.daily_seconds, 2),
        }
        try:
            with open(state_path(), "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError:
            pass

    def _roll_day_if_needed(self):
        """Reset the persistent daily total when the calendar day changes."""
        t = today_str()
        if t != self.daily_date:
            self.daily_date = t
            self.daily_seconds = 0.0

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        self.root.title("Immersion Timer")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.geometry("420x612")
        try:
            self.root.iconbitmap(resource_path("icon.ico"))
        except Exception:
            pass

        f_title = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        f_mode  = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        f_clock = tkfont.Font(family="Consolas", size=58, weight="bold")
        f_btn   = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        f_small = tkfont.Font(family="Segoe UI", size=9)
        f_total = tkfont.Font(family="Consolas", size=20, weight="bold")
        f_link  = tkfont.Font(family="Segoe UI", size=9, underline=True)

        card = tk.Frame(self.root, bg=PANEL, padx=26, pady=22)
        card.place(relx=0.5, rely=0.5, anchor="center", width=388, height=580)

        # Top bar
        top = tk.Frame(card, bg=PANEL)
        top.pack(fill="x")
        self.dot = tk.Canvas(top, width=12, height=16, bg=PANEL,
                             highlightthickness=0)
        self.dot.pack(side="left")
        self._dot_id = self.dot.create_oval(2, 4, 11, 13, fill=MUTED, outline="")
        tk.Label(top, text="  Immersion Timer", bg=PANEL, fg=MUTED,
                 font=f_title).pack(side="left")
        self.settings_btn = tk.Button(
            top, text="⚙", font=tkfont.Font(family="Segoe UI", size=14),
            bg=PANEL, fg=MUTED, activebackground=PANEL2, activeforeground=TEXT,
            relief="flat", bd=0, cursor="hand2", command=self.open_settings,
            takefocus=0, width=2)
        self.settings_btn.pack(side="right")

        # Mode label
        self.mode_label = tk.Label(card, text="FOCUS", bg=PANEL, fg=FOCUS,
                                   font=f_mode)
        self.mode_label.pack(pady=(16, 2))

        # Clock
        self.clock_label = tk.Label(card, text="20:00", bg=PANEL, fg=TEXT,
                                    font=f_clock)
        self.clock_label.pack(pady=(0, 10))

        # Progress bar
        self.bar_canvas = tk.Canvas(card, height=6, bg=PANEL2,
                                    highlightthickness=0)
        self.bar_canvas.pack(fill="x", pady=(0, 16))
        self._bar_fill = self.bar_canvas.create_rectangle(0, 0, 0, 6,
                                                          fill=FOCUS, outline="")

        # Mode buttons
        modes = tk.Frame(card, bg=PANEL)
        modes.pack(fill="x")
        modes.columnconfigure(0, weight=1, uniform="m")
        modes.columnconfigure(1, weight=1, uniform="m")
        self.focus_btn = tk.Button(
            modes, text="Focus", font=f_btn, bg=PANEL2, fg=TEXT,
            activebackground=FOCUSDIM, activeforeground=TEXT, relief="flat",
            bd=0, cursor="hand2", pady=10, takefocus=0,
            command=self.on_focus_click)
        self.focus_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.break_btn = tk.Button(
            modes, text="Break", font=f_btn, bg=PANEL2, fg=TEXT,
            activebackground=BREAKDIM, activeforeground=TEXT, relief="flat",
            bd=0, cursor="hand2", pady=10, takefocus=0,
            command=self.on_break_click)
        self.break_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        subs = tk.Frame(card, bg=PANEL)
        subs.pack(fill="x", pady=(4, 14))
        subs.columnconfigure(0, weight=1, uniform="s")
        subs.columnconfigure(1, weight=1, uniform="s")
        self.focus_sub = tk.Label(subs, text="20 min default", bg=PANEL,
                                  fg=MUTED, font=f_small)
        self.focus_sub.grid(row=0, column=0)
        self.break_sub = tk.Label(subs, text="10 min default", bg=PANEL,
                                  fg=MUTED, font=f_small)
        self.break_sub.grid(row=0, column=1)

        # Controls
        ctrls = tk.Frame(card, bg=PANEL)
        ctrls.pack(fill="x")
        ctrls.columnconfigure(0, weight=1, uniform="c")
        ctrls.columnconfigure(1, weight=1, uniform="c")
        self.start_btn = tk.Button(
            ctrls, text="Start", font=f_btn, bg=TEXT, fg=BG,
            activebackground="#cdd5e0", activeforeground=BG, relief="flat",
            bd=0, cursor="hand2", pady=9, takefocus=0, command=self.toggle_start)
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.reset_btn = tk.Button(
            ctrls, text="Reset", font=f_btn, bg=PANEL2, fg=TEXT,
            activebackground=LINE, activeforeground=TEXT, relief="flat",
            bd=0, cursor="hand2", pady=9, takefocus=0, command=self.reset)
        self.reset_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        # Totals
        sep = tk.Frame(card, bg=LINE, height=1)
        sep.pack(fill="x", pady=(20, 12))

        head = tk.Frame(card, bg=PANEL)
        head.pack(fill="x")
        tk.Label(head, text="FOCUSED TODAY", bg=PANEL, fg=MUTED,
                 font=f_small).pack(side="left")
        self.reset_today = tk.Button(
            head, text="reset", font=f_link, bg=PANEL, fg=MUTED,
            activebackground=PANEL, activeforeground=TEXT, relief="flat",
            bd=0, cursor="hand2", takefocus=0, command=self.reset_daily)
        self.reset_today.pack(side="right")

        self.total_label = tk.Label(card, text="0m 00s", bg=PANEL, fg=FOCUS,
                                    font=f_total)
        self.total_label.pack(anchor="w", pady=(2, 0))
        self.session_label = tk.Label(card, text="This session: 0m 00s",
                                      bg=PANEL, fg=MUTED, font=f_small)
        self.session_label.pack(anchor="w")

        # Keyboard: space toggles start/pause
        self.root.bind("<space>", lambda e: self.toggle_start())

    # ------------------------------------------------------------ helpers
    def duration_for(self, mode):
        return (self.focus_min if mode == "focus" else self.break_min) * 60.0

    @staticmethod
    def fmt_clock(secs):
        secs = max(0, int(round(secs)))
        return f"{secs // 60:02d}:{secs % 60:02d}"

    @staticmethod
    def fmt_total(secs):
        secs = int(secs)
        h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
        if h > 0:
            return f"{h}h {m}m {s:02d}s"
        return f"{m}m {s:02d}s"

    # ------------------------------------------------------------- render
    def render(self):
        accent = FOCUS if self.mode == "focus" else BREAK
        self.dot.itemconfig(self._dot_id, fill=accent)
        self.mode_label.configure(text=self.mode.upper(), fg=accent)
        self.clock_label.configure(text=self.fmt_clock(self.remaining))

        total = self.duration_for(self.mode)
        pct = 0.0 if total <= 0 else max(0.0, min(1.0, 1 - self.remaining / total))
        w = self.bar_canvas.winfo_width() or 336
        self.bar_canvas.coords(self._bar_fill, 0, 0, w * pct, 6)
        self.bar_canvas.itemconfig(self._bar_fill, fill=accent)

        if self.running:
            self.start_btn.configure(text="Pause")
        elif self.remaining < self.duration_for(self.mode) - 0.01:
            self.start_btn.configure(text="Resume")
        else:
            self.start_btn.configure(text="Start")

        self.focus_btn.configure(bg=FOCUSDIM if self.mode == "focus" else PANEL2)
        self.break_btn.configure(bg=BREAKDIM if self.mode == "break" else PANEL2)

        self.focus_sub.configure(text=f"{self.focus_min} min default")
        self.break_sub.configure(text=f"{self.break_min} min default")

        self.total_label.configure(text=self.fmt_total(self.daily_seconds))
        self.session_label.configure(
            text=f"This session: {self.fmt_total(self.session_focus)}  ·  "
                 f"{self.sessions} session{'' if self.sessions == 1 else 's'}")

    # ----------------------------------------------------------- engine
    def tick(self):
        if not self.running:
            return
        now = time.monotonic()
        prev = self.remaining
        self.remaining = self.end_at - now
        if self.mode == "focus":
            delta = prev - self.remaining
            if delta > 0:
                self.focus_elapsed += delta
        if self.remaining <= 0:
            self.remaining = 0
            self.complete_timer()
            return
        self.render()
        self._tick_job = self.root.after(200, self.tick)

    def start(self):
        if self.running or self.remaining <= 0:
            return
        self.running = True
        self.end_at = time.monotonic() + self.remaining
        self._tick_job = self.root.after(200, self.tick)
        self.render()

    def pause(self):
        if not self.running:
            return
        self.running = False
        if self._tick_job:
            self.root.after_cancel(self._tick_job)
            self._tick_job = None
        self.remaining = max(0.0, self.end_at - time.monotonic())
        self.render()

    def toggle_start(self):
        self.pause() if self.running else self.start()

    def complete_timer(self):
        """A timer reached zero on its own."""
        if self._tick_job:
            self.root.after_cancel(self._tick_job)
            self._tick_job = None
        self.running = False
        self.play_alarm()
        if self.mode == "focus":
            self.log_focus(self.focus_elapsed if self.focus_elapsed > 0
                           else self.duration_for("focus"))
            self.switch_mode("break")
        else:
            self.switch_mode("focus")
        if self.auto_start:
            self.start()

    def log_focus(self, seconds):
        self._roll_day_if_needed()
        self.session_focus += seconds
        self.daily_seconds += seconds
        self.sessions += 1
        self.focus_elapsed = 0.0
        self._save_state()

    def switch_mode(self, nxt):
        if self.running:
            self.pause()
        self.mode = nxt
        self.remaining = self.duration_for(nxt)
        self.focus_elapsed = 0.0
        self.render()

    def end_focus_early_to_break(self):
        """Break clicked mid-focus: log elapsed focus, roll into a break."""
        was_running = self.running
        if self.running:
            self.pause()
        if self.focus_elapsed > 0.5:
            self.log_focus(self.focus_elapsed)
        else:
            self.focus_elapsed = 0.0
        self.mode = "break"
        self.remaining = self.duration_for("break")
        self.render()
        if was_running:
            self.start()

    def reset(self):
        self.pause()
        self.stop_alarm()
        self.remaining = self.duration_for(self.mode)
        self.focus_elapsed = 0.0
        self.render()

    def reset_daily(self):
        if messagebox.askyesno(
                "Reset today's total",
                "Reset the “Focused today” total back to zero?\n"
                "(This does not affect the current timer.)",
                parent=self.root):
            self.daily_seconds = 0.0
            self.daily_date = today_str()
            self._save_state()
            self.render()

    # --------------------------------------------------- mode buttons
    def on_focus_click(self):
        self.stop_alarm()
        if self.mode == "focus":
            self.reset()
        else:
            self.switch_mode("focus")

    def on_break_click(self):
        self.stop_alarm()
        if self.mode == "focus":
            self.end_focus_early_to_break()
        else:
            self.reset()

    # --------------------------------------------------------- alarm
    def play_alarm(self):
        self.stop_alarm()
        # Re-trigger the sound on a timer for the alarm window. SND_LOOP is not
        # supported with SND_ALIAS (system sounds), so looping has to be done
        # by replaying the sound ourselves.
        self._sound_loop()

        # raise the window so it's visible, and flash the taskbar button
        try:
            self.root.deiconify()
            self.root.lift()
        except tk.TclError:
            pass
        self._flash_taskbar(True)

        self._flash_on = True
        self._flash()
        self._alarm_job = self.root.after(5000, self.stop_alarm)

    def _play_sound_once(self):
        alias = ALARM_ALIAS.get(self.alarm)
        if alias and HAVE_WINSOUND:
            try:
                winsound.PlaySound(
                    alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
            except RuntimeError:
                self.root.bell()
        elif alias is None:
            pass  # silent (flash only)
        else:
            self.root.bell()

    def _sound_loop(self):
        self._play_sound_once()
        # system alarm sounds are ~1s; replay until stop_alarm cancels this
        self._sound_job = self.root.after(1200, self._sound_loop)

    def _flash(self):
        self._flash_on = not self._flash_on
        self.clock_label.configure(fg=DANGER if self._flash_on else TEXT)
        self._flash_job = self.root.after(400, self._flash)

    def stop_alarm(self):
        if self._alarm_job:
            self.root.after_cancel(self._alarm_job)
            self._alarm_job = None
        if self._flash_job:
            self.root.after_cancel(self._flash_job)
            self._flash_job = None
        if self._sound_job:
            self.root.after_cancel(self._sound_job)
            self._sound_job = None
        if HAVE_WINSOUND:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except RuntimeError:
                pass
        self._flash_taskbar(False)
        self.clock_label.configure(fg=TEXT)

    def _flash_taskbar(self, on):
        """Flash (or stop flashing) this window's taskbar button on Windows."""
        if not HAVE_CTYPES:
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            if not hwnd:
                hwnd = self.root.winfo_id()

            class FLASHWINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT),
                            ("hwnd", wintypes.HWND),
                            ("dwFlags", wintypes.DWORD),
                            ("uCount", wintypes.UINT),
                            ("dwTimeout", wintypes.DWORD)]

            FLASHW_STOP = 0
            FLASHW_ALL = 0x3
            FLASHW_TIMERNOFG = 0xC
            flags = FLASHW_STOP if not on else (FLASHW_ALL | FLASHW_TIMERNOFG)
            info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, flags,
                              0 if on else 0, 0)
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
            self._flashing_taskbar = on
        except Exception:
            pass

    # ------------------------------------------------------- settings
    def open_settings(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Settings")
        dlg.configure(bg=PANEL)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        try:
            dlg.iconbitmap(resource_path("icon.ico"))
        except Exception:
            pass
        dlg.grab_set()

        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 320) // 2
        y = self.root.winfo_y() + 90
        dlg.geometry(f"320x352+{max(0, x)}+{max(0, y)}")

        f_h = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        f_l = tkfont.Font(family="Segoe UI", size=9)
        f_b = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        f_e = tkfont.Font(family="Consolas", size=12, weight="bold")

        wrap = tk.Frame(dlg, bg=PANEL, padx=22, pady=18)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text="Settings", bg=PANEL, fg=TEXT, font=f_h).pack(
            anchor="w", pady=(0, 12))

        # two minute fields side by side
        grid = tk.Frame(wrap, bg=PANEL)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1, uniform="g")
        grid.columnconfigure(1, weight=1, uniform="g")

        tk.Label(grid, text="Focus (min)", bg=PANEL, fg=MUTED,
                 font=f_l).grid(row=0, column=0, sticky="w")
        tk.Label(grid, text="Break (min)", bg=PANEL, fg=MUTED,
                 font=f_l).grid(row=0, column=1, sticky="w", padx=(10, 0))
        focus_var = tk.StringVar(value=str(self.focus_min))
        break_var = tk.StringVar(value=str(self.break_min))
        e1 = tk.Entry(grid, textvariable=focus_var, bg=BG, fg=TEXT,
                      insertbackground=TEXT, relief="flat", font=f_e,
                      justify="center")
        e1.grid(row=1, column=0, sticky="ew", pady=(4, 0), ipady=5)
        e2 = tk.Entry(grid, textvariable=break_var, bg=BG, fg=TEXT,
                      insertbackground=TEXT, relief="flat", font=f_e,
                      justify="center")
        e2.grid(row=1, column=1, sticky="ew", pady=(4, 0), padx=(10, 0), ipady=5)

        # alarm sound
        tk.Label(wrap, text="Alarm sound", bg=PANEL, fg=MUTED,
                 font=f_l).pack(anchor="w", pady=(16, 4))
        alarm_var = tk.StringVar(value=self.alarm)
        om = tk.OptionMenu(wrap, alarm_var, *ALARM_CHOICES)
        om.configure(bg=BG, fg=TEXT, activebackground=PANEL2,
                     activeforeground=TEXT, relief="flat", bd=0,
                     highlightthickness=0, font=f_b, anchor="w",
                     cursor="hand2")
        om["menu"].configure(bg=PANEL2, fg=TEXT, activebackground=FOCUSDIM,
                             activeforeground=TEXT, relief="flat", bd=0)
        om.pack(fill="x", ipady=2)

        # auto-start
        auto_var = tk.BooleanVar(value=self.auto_start)
        cb = tk.Checkbutton(
            wrap, text="  Auto-start the next phase when one ends",
            variable=auto_var, bg=PANEL, fg=TEXT, font=f_l,
            activebackground=PANEL, activeforeground=TEXT, selectcolor=BG,
            highlightthickness=0, bd=0, cursor="hand2",
            anchor="w")
        cb.pack(fill="x", pady=(16, 16))

        btns = tk.Frame(wrap, bg=PANEL)
        btns.pack(fill="x")

        def save():
            self.focus_min = self._clamp_int(focus_var.get(), self.focus_min)
            self.break_min = self._clamp_int(break_var.get(), self.break_min)
            if alarm_var.get() in ALARM_CHOICES:
                self.alarm = alarm_var.get()
            self.auto_start = bool(auto_var.get())
            if not self.running:
                self.remaining = self.duration_for(self.mode)
                self.focus_elapsed = 0.0
            self._save_state()
            dlg.destroy()
            self.render()

        tk.Button(btns, text="Cancel", font=f_b, bg=PANEL2, fg=TEXT,
                  activebackground=LINE, activeforeground=TEXT, relief="flat",
                  bd=0, cursor="hand2", padx=18, pady=8, takefocus=0,
                  command=dlg.destroy).pack(side="right", padx=(10, 0))
        tk.Button(btns, text="Save", font=f_b, bg=TEXT, fg=BG,
                  activebackground="#cdd5e0", activeforeground=BG, relief="flat",
                  bd=0, cursor="hand2", padx=22, pady=8, takefocus=0,
                  command=save).pack(side="right")

        e1.focus_set()
        dlg.bind("<Return>", lambda e: save())
        dlg.bind("<Escape>", lambda e: dlg.destroy())


def main():
    root = tk.Tk()
    app = ImmersionTimer(root)
    root.after(60, app.render)  # redraw the progress bar at real width
    root.mainloop()


if __name__ == "__main__":
    main()
