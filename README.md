# Immersion Timer

A small native Windows focus/break timer. No browser, no install beyond
Python's standard library — just a single window.

![A blue clock app icon](icon.ico)

## Features

- **Focus / Break** modes (defaults: 20 min focus, 10 min break)
- **Settings** to change the defaults, the alarm sound, and auto-start
- **5-second alarm** when a timer ends — the clock flashes, the taskbar
  button flashes, and the window is raised to the front
- **"Focused today"** running total that **persists across restarts**
  (auto-resets at midnight, plus a manual reset), alongside a per-session total
- **Auto-start** option to roll straight into the next phase
- Clicking **Break** during a focus session ends it early, logs the elapsed
  focus time, and starts the break
- Spacebar toggles start/pause

## Run it

**From source** (Python 3 with Tk, included in standard Windows installs):

```
pythonw immersion_timer.pyw
```

or just double-click `immersion_timer.pyw`.

**As a standalone .exe** (no Python needed on the target machine) — build with
[PyInstaller](https://pyinstaller.org/):

```
pip install pyinstaller
pyinstaller --onefile --windowed --name ImmersionTimer ^
    --icon icon.ico --add-data "icon.ico;." immersion_timer.pyw
```

The result lands in `dist\ImmersionTimer.exe`. (Build outputs are
git-ignored.)

## Where settings are stored

Preferences and the daily total are saved to:

```
%APPDATA%\ImmersionTimer\state.json
```

This is shared whether you run the `.pyw` or the `.exe`.

## Files

| File | Purpose |
| --- | --- |
| `immersion_timer.pyw` | The application source |
| `icon.ico` | App icon (keep alongside the source for builds) |
| `.gitignore` | Excludes build artifacts and per-user state |
