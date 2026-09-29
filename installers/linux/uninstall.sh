#!/usr/bin/env bash
# AI Interviewer uninstaller.
# Usage: bash uninstall.sh [--dir FOLDER]
#   --dir is only needed if the install location can't be detected automatically.
set -uo pipefail

APP_ID="ai-interviewer"
MARKER=".ai-interviewer-install"
DEFAULT_INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_ID"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/$APP_ID"
PATH_FILE="$CONFIG_DIR/install_path"
BIN_DIR="$HOME/.local/bin"
DESKTOP_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/applications/$APP_ID.desktop"
LAUNCHER="$BIN_DIR/$APP_ID"
BROWSER_PROFILE="$HOME/.cache/$APP_ID-profile"

say() { printf '\n==> %s\n' "$*"; }
ask() { read -r -p "$1 [y/N] " a; [[ "${a:-N}" =~ ^[Yy]$ ]]; }

# ---------------------------------------------------------------- locate install folder
INSTALL_DIR=""
while [ $# -gt 0 ]; do
    case "$1" in
        -d|--dir) INSTALL_DIR="${2:-}"; shift 2 ;;
        --dir=*)  INSTALL_DIR="${1#--dir=}"; shift ;;
        -h|--help) echo "Usage: bash uninstall.sh [--dir FOLDER]"; exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# 1) recorded by install.sh  2) read from the launcher  3) default location
if [ -z "$INSTALL_DIR" ] && [ -f "$PATH_FILE" ]; then
    INSTALL_DIR="$(head -n1 "$PATH_FILE")"
fi
if [ -z "$INSTALL_DIR" ] && [ -f "$LAUNCHER" ]; then
    INSTALL_DIR="$(sed -n 's/^INSTALL_DIR="\(.*\)"$/\1/p' "$LAUNCHER" | head -n1)"
fi
if [ -z "$INSTALL_DIR" ] && [ -d "$DEFAULT_INSTALL_DIR" ]; then
    INSTALL_DIR="$DEFAULT_INSTALL_DIR"
fi
if [ -z "$INSTALL_DIR" ] || [ ! -d "$INSTALL_DIR" ]; then
    read -r -p "Could not find the install folder. Enter it (blank to skip): " INSTALL_DIR
fi
case "$INSTALL_DIR" in
    "~")   INSTALL_DIR="$HOME" ;;
    "~/"*) INSTALL_DIR="$HOME/${INSTALL_DIR#\~/}" ;;
esac
[ -d "$INSTALL_DIR" ] && INSTALL_DIR="$(cd "$INSTALL_DIR" && pwd)"

# Safety: only ever rm -rf a folder that clearly belongs to this app
REMOVE_DIR=0
if [ -n "$INSTALL_DIR" ] && [ -d "$INSTALL_DIR" ]; then
    if [ "$INSTALL_DIR" = "/" ] || [ "$INSTALL_DIR" = "$HOME" ]; then
        echo "Refusing to delete '$INSTALL_DIR'."
    elif [ -e "$INSTALL_DIR/$MARKER" ] || [ -d "$INSTALL_DIR/.git" ]; then
        REMOVE_DIR=1
    else
        echo "'$INSTALL_DIR' doesn't look like an $APP_ID install (no marker file). Not deleting it."
    fi
fi

echo "This will remove $APP_ID from your system."
[ "$REMOVE_DIR" = 1 ] && echo "Install folder: $INSTALL_DIR"
ask "Continue?" || { echo "Cancelled."; exit 0; }

# Stop the server if it's running
say "Stopping server"
[ -x "$LAUNCHER" ] && "$LAUNCHER" stop 2>/dev/null || true

# Offer to keep candidate data (uploads, reports, user database)
if [ "$REMOVE_DIR" = 1 ] && { [ -d "$INSTALL_DIR/uploads" ] || [ -d "$INSTALL_DIR/database" ]; }; then
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
[ "$REMOVE_DIR" = 1 ] && rm -rf "$INSTALL_DIR"
rm -rf "$BROWSER_PROFILE"
update-desktop-database "$(dirname "$DESKTOP_FILE")" 2>/dev/null || true

if [ -d "$CONFIG_DIR" ]; then
    if ask "Also delete config ($CONFIG_DIR, contains SECRET_KEY and email settings)?"; then
        rm -rf "$CONFIG_DIR"
    else
        rm -f "$PATH_FILE"   # stale once the install folder is gone
        echo "Kept $CONFIG_DIR"
    fi
fi

say "Uninstalled."
echo "Not removed (installed system-wide): ffmpeg, Ollama and its downloaded models."
echo "To remove Ollama models: ollama list && ollama rm <model>"
