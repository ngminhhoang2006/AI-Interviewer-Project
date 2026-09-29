#!/usr/bin/env bash
# AI Interviewer graphical uninstaller for macOS: double-click this file.
# Native dialogs ask the questions; the work is done by uninstall_macos.command
# (keep both files in the same folder).
cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"
TITLE="AI Interviewer Uninstall"

choose_btn() {
    local def="$1" text="$2"; shift 2
    osascript - "$TITLE" "$text" "$def" "$@" <<'AS'
on run argv
    set ttl to item 1 of argv
    set txt to item 2 of argv
    set def to item 3 of argv
    set btns to items 4 thru -1 of argv
    return button returned of (display dialog txt with title ttl buttons btns default button def with icon caution)
end run
AS
}

[ "$(uname)" = "Darwin" ] || { echo "This uninstaller is for macOS only."; exit 1; }
[ -f "$HERE/uninstall_macos.command" ] || { osascript -e 'display alert "uninstall_macos.command was not found next to this file." message "Keep all the installer files in the same folder."'; exit 1; }

choose_btn "Uninstall" "Remove AI Interviewer from this Mac?" "Cancel" "Uninstall" >/dev/null || exit 0

r="$(choose_btn "Back up" "Save a backup of candidate data (uploads and database) to your home folder before deleting?" "No backup" "Back up")" || exit 0
[ "$r" = "Back up" ] && BACKUP="--backup" || BACKUP="--no-backup"

r="$(choose_btn "Keep" "Also delete settings (secret key and email settings)?" "Keep" "Delete")" || exit 0
[ "$r" = "Delete" ] && CONFIG="--delete-config" || CONFIG="--keep-config"

AI_INTERVIEWER_GUI=1 bash "$HERE/uninstall_macos.command" --yes $BACKUP $CONFIG
rc=$?

if [ $rc -eq 0 ]; then
    choose_btn "OK" "AI Interviewer has been removed." "OK" >/dev/null
else
    choose_btn "OK" "Uninstall did not finish. Scroll up in the Terminal window to see what went wrong." "OK" >/dev/null
fi
