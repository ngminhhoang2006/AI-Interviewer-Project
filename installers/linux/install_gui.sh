#!/usr/bin/env bash
# AI Interviewer graphical installer for Linux (uses zenity, preinstalled on GNOME/Ubuntu).
# Usage: bash install_gui.sh     (keep it in the same folder as install.sh)
# Without zenity it falls back to the terminal installer.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TITLE="AI Interviewer Setup"
DEFAULT_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/ai-interviewer"
LOG="${TMPDIR:-/tmp}/ai-interviewer-setup.log"

[ -f "$HERE/install.sh" ] || { echo "install.sh not found next to this file."; exit 1; }
if ! command -v zenity >/dev/null; then
    echo "zenity not found (sudo apt install zenity). Using the terminal installer instead."
    exec bash "$HERE/install.sh" "$@"
fi

out="$(zenity --question --no-markup --title="$TITLE" --width=480 \
    --text="Install AI Interviewer?

Setup may install missing system packages (you will get a password prompt), then downloads the app and its AI model. This can take a while.

Default location:
$DEFAULT_DIR" \
    --ok-label="Install" --cancel-label="Cancel" --extra-button="Choose folder...")"
rc=$?
if [ $rc -eq 0 ]; then
    FOLDER="$DEFAULT_DIR"
elif [ "$out" = "Choose folder..." ]; then
    FOLDER="$(zenity --file-selection --directory --title="Choose where to install AI Interviewer" \
        --filename="$(dirname "$DEFAULT_DIR")/")" || exit 0
else
    exit 0
fi

# Run the installer; each output line becomes the progress window's label
AI_INTERVIEWER_GUI=1 bash "$HERE/install.sh" --dir "$FOLDER" --yes 2>&1 \
    | tee "$LOG" \
    | tr '\r' '\n' \
    | sed -u -e 's/\x1b\[[0-9;?]*[A-Za-z]//g' -e '/^[[:space:]]*$/d' -e 's/^/# /' \
    | zenity --progress --pulsate --auto-close --no-markup --title="$TITLE" --width=520 \
        --text="Starting..." --cancel-label="Stop"
rc=${PIPESTATUS[0]}

if [ "$rc" -eq 0 ]; then
    if zenity --question --no-markup --title="$TITLE" --text="AI Interviewer is installed.

Open it now?" --ok-label="Open" --cancel-label="Later"; then
        nohup "$HOME/.local/bin/ai-interviewer" >/dev/null 2>&1 &
    fi
else
    if zenity --question --no-markup --title="$TITLE" --width=420 \
        --text="Setup did not finish (it may have been stopped, or something failed)." \
        --ok-label="View log" --cancel-label="Close"; then
        zenity --text-info --title="Setup log" --width=700 --height=450 --filename="$LOG"
    fi
fi
