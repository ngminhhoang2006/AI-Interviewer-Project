#!/usr/bin/env bash
# AI Interviewer uninstaller. Usage: bash uninstall.sh
set -uo pipefail

APP_ID="ai-interviewer"
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_ID"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/$APP_ID"
BIN_DIR="$HOME/.local/bin"
DESKTOP_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/applications/$APP_ID.desktop"
LAUNCHER="$BIN_DIR/$APP_ID"
BROWSER_PROFILE="$HOME/.cache/$APP_ID-profile"

say() { printf '\n==> %s\n' "$*"; }
ask() { read -r -p "$1 [y/N] " a; [[ "${a:-N}" =~ ^[Yy]$ ]]; }

echo "This will remove $APP_ID from your system."
ask "Continue?" || { echo "Cancelled."; exit 0; }

# Stop the server if it's running
say "Stopping server"
[ -x "$LAUNCHER" ] && "$LAUNCHER" stop 2>/dev/null || true

# Offer to keep candidate data (uploads, reports, user database)
if [ -d "$INSTALL_DIR/uploads" ] || [ -d "$INSTALL_DIR/database" ]; then
    echo
    echo "Found user data (candidate uploads/reports and the accounts database)."
    if ask "Save a backup copy to ~/${APP_ID}-backup before deleting?"; then
        BACKUP="$HOME/${APP_ID}-backup-$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$BACKUP"
        [ -d "$INSTALL_DIR/uploads" ]  && cp -a "$INSTALL_DIR/uploads"  "$BACKUP/"
        [ -d "$INSTALL_DIR/database" ] && cp -a "$INSTALL_DIR/database" "$BACKUP/"
        echo "Backup saved to $BACKUP"
    fi
fi

say "Removing files"
rm -f  "$LAUNCHER"
rm -f  "$DESKTOP_FILE"
rm -rf "$INSTALL_DIR"
rm -rf "$BROWSER_PROFILE"
update-desktop-database "$(dirname "$DESKTOP_FILE")" 2>/dev/null || true

if [ -d "$CONFIG_DIR" ]; then
    if ask "Also delete config ($CONFIG_DIR, contains SECRET_KEY and email settings)?"; then
        rm -rf "$CONFIG_DIR"
    else
        echo "Kept $CONFIG_DIR"
    fi
fi

say "Uninstalled."
echo "Not removed (installed system-wide): ffmpeg, Ollama and its downloaded models."
echo "To remove Ollama models: ollama list && ollama rm <model>"
