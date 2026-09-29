#!/usr/bin/env bash
# AI Interviewer graphical installer for macOS: double-click this file.
# Native dialogs ask where to install; the work is done by install_macos.command
# (keep both files in the same folder). Progress is shown in the Terminal window,
# because Homebrew and macOS may need to ask for your password there.
cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"
TITLE="AI Interviewer Setup"
DEFAULT_DIR="$HOME/.local/share/ai-interviewer"

# choose_btn DEFAULT_BUTTON TEXT BUTTON... -> prints the button clicked; fails if the user cancels
choose_btn() {
    local def="$1" text="$2"; shift 2
    osascript - "$TITLE" "$text" "$def" "$@" <<'AS'
on run argv
    set ttl to item 1 of argv
    set txt to item 2 of argv
    set def to item 3 of argv
    set btns to items 4 thru -1 of argv
    return button returned of (display dialog txt with title ttl buttons btns default button def with icon note)
end run
AS
}

[ "$(uname)" = "Darwin" ] || { echo "This installer is for macOS only."; exit 1; }
[ -f "$HERE/install_macos.command" ] || { osascript -e 'display alert "install_macos.command was not found next to this file." message "Keep all the installer files in the same folder."'; exit 1; }

NL=$'\n'
choice="$(choose_btn "Install" "Install AI Interviewer?${NL}${NL}Setup may install Homebrew, Git, Python 3.12, FFmpeg and PortAudio if they are missing. Progress appears in the Terminal window, where you may be asked for your Mac password.${NL}${NL}Default location:${NL}$DEFAULT_DIR" "Cancel" "Choose Folder..." "Install")" || exit 0

FOLDER="$DEFAULT_DIR"
if [ "$choice" = "Choose Folder..." ]; then
    FOLDER="$(osascript -e 'POSIX path of (choose folder with prompt "Choose where to install AI Interviewer:")')" || exit 0
    FOLDER="${FOLDER%/}"
fi

NO_OLLAMA=""
if ! command -v ollama >/dev/null && [ ! -d "/Applications/Ollama.app" ]; then
    r="$(choose_btn "Install Ollama" "Ollama is needed for question generation and grading. Install it too?" "Skip" "Install Ollama")" || exit 0
    [ "$r" = "Skip" ] && NO_OLLAMA="--no-ollama"
fi

echo "Installing AI Interviewer into: $FOLDER"
AI_INTERVIEWER_GUI=1 bash "$HERE/install_macos.command" --dir "$FOLDER" --yes $NO_OLLAMA
rc=$?

if [ $rc -eq 0 ]; then
    r="$(choose_btn "Open AI Interviewer" "AI Interviewer is installed.${NL}${NL}You can open it from ~/Applications, Launchpad or Spotlight." "Close" "Open AI Interviewer")" || exit 0
    [ "$r" = "Open AI Interviewer" ] && open "$HOME/Applications/AI Interviewer.app"
else
    choose_btn "OK" "Setup did not finish.${NL}${NL}Scroll up in the Terminal window to see what went wrong. If macOS asked you to install the developer tools, finish that first and then run this setup again." "OK" >/dev/null
fi
