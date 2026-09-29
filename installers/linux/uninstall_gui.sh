#!/usr/bin/env bash
# AI Interviewer graphical uninstaller for Linux (uses zenity).
# Usage: bash uninstall_gui.sh     (keep it in the same folder as uninstall.sh)
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TITLE="AI Interviewer Uninstall"
LOG="${TMPDIR:-/tmp}/ai-interviewer-uninstall.log"

[ -f "$HERE/uninstall.sh" ] || { echo "uninstall.sh not found next to this file."; exit 1; }
if ! command -v zenity >/dev/null; then
    echo "zenity not found (sudo apt install zenity). Using the terminal uninstaller instead."
    exec bash "$HERE/uninstall.sh" "$@"
fi

zenity --question --no-markup --title="$TITLE" --text="Remove AI Interviewer from this computer?" \
    --ok-label="Uninstall" --cancel-label="Cancel" || exit 0

if zenity --question --no-markup --title="$TITLE" --width=420 \
    --text="Save a backup of candidate data (uploads and database) to your home folder before deleting?" \
    --ok-label="Back up" --cancel-label="No backup"; then BACKUP="--backup"; else BACKUP="--no-backup"; fi

if zenity --question --no-markup --title="$TITLE" --width=420 \
    --text="Also delete settings (secret key and email settings)?" \
    --ok-label="Delete" --cancel-label="Keep"; then CONFIG="--delete-config"; else CONFIG="--keep-config"; fi

bash "$HERE/uninstall.sh" --yes $BACKUP $CONFIG > "$LOG" 2>&1
rc=$?

if [ "$rc" -eq 0 ]; then
    zenity --info --no-markup --title="$TITLE" --text="AI Interviewer has been removed."
else
    zenity --text-info --title="Uninstall did not finish" --width=700 --height=450 --filename="$LOG"
fi
