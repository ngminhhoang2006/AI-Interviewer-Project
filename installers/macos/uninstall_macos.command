#!/usr/bin/env bash
# AI Interviewer uninstaller for macOS.
#   Double-click, or:  bash uninstall_macos.command [--dir FOLDER] [--yes] [--backup|--no-backup] [--delete-config|--keep-config]
# --dir is only needed if the install location can't be detected automatically.
set -uo pipefail
if [ -z "${AI_INTERVIEWER_GUI:-}" ]; then trap 'echo; read -r -p "Press Enter to close..." _' EXIT; fi

APP_NAME="AI Interviewer"
APP_ID="ai-interviewer"
MARKER=".ai-interviewer-install"
DEFAULT_INSTALL_DIR="$HOME/.local/share/$APP_ID"
CONFIG_DIR="$HOME/.config/$APP_ID"
PATH_FILE="$CONFIG_DIR/install_path"
APP_BUNDLE="$HOME/Applications/$APP_NAME.app"
BUNDLE_LAUNCHER="$APP_BUNDLE/Contents/MacOS/$APP_ID"
PIDFILE="$HOME/Library/Caches/$APP_ID.pid"
PROFILE_DIR="$HOME/Library/Caches/$APP_ID-profile"

say() { printf '\n==> %s\n' "$*"; }
ask() { read -r -p "$1 [y/N] " a; [[ "${a:-N}" =~ ^[Yy]$ ]]; }
# mode_ask MODE QUESTION: MODE is yes/no (pre-answered) or anything else to ask
mode_ask() { case "$1" in yes) return 0 ;; no) return 1 ;; *) ask "$2" ;; esac; }
ASSUME_YES=0; BACKUP_MODE=ask; CONFIG_MODE=ask

# ---------------------------------------------------------------- locate install folder
INSTALL_DIR=""
while [ $# -gt 0 ]; do
    case "$1" in
        -d|--dir) INSTALL_DIR="${2:-}"; shift 2 ;;
        --dir=*)  INSTALL_DIR="${1#--dir=}"; shift ;;
        -y|--yes) ASSUME_YES=1; shift ;;
        --backup) BACKUP_MODE=yes; shift ;;
        --no-backup) BACKUP_MODE=no; shift ;;
        --delete-config) CONFIG_MODE=yes; shift ;;
        --keep-config) CONFIG_MODE=no; shift ;;
        -h|--help) echo "Usage: bash uninstall_macos.command [--dir FOLDER] [--yes] [--backup|--no-backup] [--delete-config|--keep-config]"; exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# 1) recorded by the installer  2) read from the app bundle  3) default location
if [ -z "$INSTALL_DIR" ] && [ -f "$PATH_FILE" ]; then
    INSTALL_DIR="$(head -n1 "$PATH_FILE")"
fi
if [ -z "$INSTALL_DIR" ] && [ -f "$BUNDLE_LAUNCHER" ]; then
    INSTALL_DIR="$(sed -n 's/^INSTALL_DIR="\(.*\)"$/\1/p' "$BUNDLE_LAUNCHER" | head -n1)"
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
[ -n "$INSTALL_DIR" ] && [ -d "$INSTALL_DIR" ] && INSTALL_DIR="$(cd "$INSTALL_DIR" && pwd)"

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

echo "This will remove $APP_NAME from your Mac."
[ "$REMOVE_DIR" = 1 ] && echo "Install folder: $INSTALL_DIR"
[ "$ASSUME_YES" = 1 ] || ask "Continue?" || { echo "Cancelled."; exit 0; }

say "Stopping server"
[ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null
rm -f "$PIDFILE"
[ "$REMOVE_DIR" = 1 ] && pkill -f "$INSTALL_DIR/.venv/bin/python" 2>/dev/null || true

if [ "$REMOVE_DIR" = 1 ] && { [ -d "$INSTALL_DIR/uploads" ] || [ -d "$INSTALL_DIR/database" ]; }; then
    echo
    echo "Found user data (candidate uploads/reports and the accounts database)."
    if mode_ask "$BACKUP_MODE" "Save a backup copy to your home folder before deleting?"; then
        BACKUP="$HOME/${APP_ID}-backup-$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$BACKUP"
        [ -d "$INSTALL_DIR/uploads" ]  && cp -a "$INSTALL_DIR/uploads"  "$BACKUP/"
        [ -d "$INSTALL_DIR/database" ] && cp -a "$INSTALL_DIR/database" "$BACKUP/"
        echo "Backup saved to $BACKUP"
    fi
fi

say "Removing files"
rm -rf "$APP_BUNDLE"
[ "$REMOVE_DIR" = 1 ] && rm -rf "$INSTALL_DIR"
rm -rf "$PROFILE_DIR"

if [ -d "$CONFIG_DIR" ]; then
    if mode_ask "$CONFIG_MODE" "Also delete config ($CONFIG_DIR, contains SECRET_KEY and email settings)?"; then
        rm -rf "$CONFIG_DIR"
    else
        rm -f "$PATH_FILE"   # stale once the install folder is gone
        echo "Kept $CONFIG_DIR"
    fi
fi

say "Uninstalled."
echo "Not removed (shared system tools): Homebrew packages (git, python@3.12, ffmpeg, portaudio), Ollama and its models."
echo "To remove Ollama models: ollama list && ollama rm <model>"
