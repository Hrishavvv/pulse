#!/usr/bin/env bash
# ─────────────────────────────────────────────
#  PULSE — Speed Test  |  Made with ❤️ by Hrishav
#  Install dependencies and launch the app
# ─────────────────────────────────────────────
set -e

echo ""
echo "  ██████  ██    ██ ██      ███████ ███████ "
echo "  ██   ██ ██    ██ ██      ██      ██      "
echo "  ██████  ██    ██ ██      ███████ █████   "
echo "  ██      ██    ██ ██           ██ ██      "
echo "  ██       ██████  ███████ ███████ ███████ "
echo ""
echo "  Speed Test  ·  Made with ❤️  by Hrishav"
echo "──────────────────────────────────────────"
echo ""

# Check Python 3
if ! command -v python3 &>/dev/null; then
    echo "  ✗ python3 not found. Install Python 3.10+ first."
    exit 1
fi

echo "  → Installing Python dependencies..."
pip3 install --quiet --upgrade PyQt6 speedtest-cli

echo "  → Launching PULSE..."
echo ""
python3 "$(dirname "$0")/speedtest_gui.py"
