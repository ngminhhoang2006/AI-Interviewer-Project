#!/usr/bin/env bash
# AI Interviewer uninstaller for macOS (double-click, or: bash uninstall_macos.command)
set -uo pipefail
trap 'echo; read -r -p "Press Enter to close..." _' EXIT

APP_NAME="AI Interviewer"
APP_ID="ai-interviewer"
INSTALL_DIR="$HOME/.local/share/$APP_ID"
CONFIG_DIR="$HOME/.config/$APP_ID"
APP_BUNDLE="$HOME/Applications/$APP_NAME.app"
PIDFILE="$HOME/Library/Caches/$APP_ID.pid"
PROFILE_DIR="$HOME/Library/Caches/$APP_ID-profile"

say() { printf '\n==> %s\n' "$*"; }
ask() { read -r -p "$1 [y/N] " a; [[ "${a:-N}" =~ ^[Yy]$ ]]; }

echo "This will remove $APP_NAME from your Mac."
ask "Continue?" || { echo "Cancelled."; exit 0; }

say "Stopping server"
[ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null
rm -f "$PIDFILE"
pkill -f "$INSTALL_DIR/.venv/bin/python" 2>/dev/null || true

if [ -d "$INSTALL_DIR/uploads" ] || [ -d "$INSTALL_DIR/database" ]; then
    echo
    echo "Found user data (candidate uploads/reports and the accounts database)."
    if ask "Save a backup copy to your home folder before deleting?"; then
        BACKUP="$HOME/${APP_ID}-backup-$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$BACKUP"
        [ -d "$INSTALL_DIR/uploads" ]  && cp -a "$INSTALL_DIR/uploads"  "$BACKUP/"
        [ -d "$INSTALL_DIR/database" ] && cp -a "$INSTALL_DIR/database" "$BACKUP/"
        echo "Backup saved to $BACKUP"
    fi
fi

say "Removing files"
rm -rf "$APP_BUNDLE"
rm -rf "$INSTALL_DIR"
rm -rf "$PROFILE_DIR"

if [ -d "$CONFIG_DIR" ]; then
    if ask "Also delete config ($CONFIG_DIR, contains SECRET_KEY and email settings)?"; then
        rm -rf "$CONFIG_DIR"
    else
        echo "Kept $CONFIG_DIR"
    fi
fi

say "Uninstalled."
echo "Not removed (shared system tools): Homebrew packages (git, python@3.12, ffmpeg, portaudio), Ollama and its models."
echo "To remove Ollama models: ollama list && ollama rm <model>"
