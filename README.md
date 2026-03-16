# PULSE — Speed Test

A beautiful, minimalist Linux desktop speed test app built with Python + PyQt6.

---

## Features
- **Real speed test** via `speedtest-cli` (Ookla)
- Animated arc gauge with smooth live updates
- Ping / Download / Upload stat cards
- Frameless, draggable dark UI
- Proprietary — do not redistribute

---

## Requirements
- Linux (tested on Ubuntu 22.04+, Fedora, Arch)
- Python 3.10+
- Internet connection

---

## Quick Start

```bash
# 1. Make the run script executable
chmod +x run.sh

# 2. Install deps and launch
./run.sh
```

Or manually:

```bash
pip install PyQt6 speedtest-cli
python3 speedtest_gui.py
```

---

## Optional: Add to app launcher

Edit `pulse-speedtest.desktop` and set the correct `Exec=` path, then:

```bash
cp pulse-speedtest.desktop ~/.local/share/applications/
```

---

