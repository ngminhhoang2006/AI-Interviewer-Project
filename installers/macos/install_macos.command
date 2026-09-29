#!/usr/bin/env bash
# AI Interviewer installer for macOS.
#   Double-click, or:  bash install_macos.command [--dir FOLDER] [--yes] [--no-ollama]
# If no folder is given you will be asked (press Enter for the default).
# You can also set AI_INTERVIEWER_DIR instead of passing --dir.
set -euo pipefail
if [ -z "${AI_INTERVIEWER_GUI:-}" ]; then trap 'echo; read -r -p "Press Enter to close..." _' EXIT; fi

APP_NAME="AI Interviewer"
APP_ID="ai-interviewer"
REPO_URL="https://github.com/ngminhhoang2006/AI-Interviewer-Project.git"
PORT=5000
MARKER=".ai-interviewer-install"
ASSUME_YES=0
NO_OLLAMA=0

DEFAULT_INSTALL_DIR="$HOME/.local/share/$APP_ID"
CONFIG_DIR="$HOME/.config/$APP_ID"
ENV_FILE="$CONFIG_DIR/env"
PATH_FILE="$CONFIG_DIR/install_path"
APP_BUNDLE="$HOME/Applications/$APP_NAME.app"

say() { printf '\n==> %s\n' "$*"; }
ask() { [ "$ASSUME_YES" = 1 ] && return 0; read -r -p "$1 [Y/n] " a; [[ "${a:-Y}" =~ ^[Yy]$ ]]; }

[ "$(uname)" = "Darwin" ] || { echo "This installer is for macOS only."; exit 1; }

# ---------------------------------------------------------------- choose install folder
CHOSEN="${AI_INTERVIEWER_DIR:-}"
while [ $# -gt 0 ]; do
    case "$1" in
        -d|--dir)
            [ -n "${2:-}" ] || { echo "--dir needs a folder argument."; exit 1; }
            CHOSEN="$2"; shift 2 ;;
        --dir=*) CHOSEN="${1#--dir=}"; shift ;;
        -y|--yes) ASSUME_YES=1; shift ;;
        --no-ollama) NO_OLLAMA=1; shift ;;
        -h|--help)
            echo "Usage: bash install_macos.command [--dir FOLDER] [--yes] [--no-ollama]"
            echo "Default folder: $DEFAULT_INSTALL_DIR"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [ -z "$CHOSEN" ]; then
    read -r -p "Install location [$DEFAULT_INSTALL_DIR]: " CHOSEN
    CHOSEN="${CHOSEN:-$DEFAULT_INSTALL_DIR}"
fi

# Expand a leading ~ (Terminal drag-and-drop of a folder also works: it pastes the path)
case "$CHOSEN" in
    "~")   CHOSEN="$HOME" ;;
    "~/"*) CHOSEN="$HOME/${CHOSEN#\~/}" ;;
esac

mkdir -p "$CHOSEN" || { echo "Cannot create $CHOSEN"; exit 1; }
CHOSEN="$(cd "$CHOSEN" && pwd)"   # absolute path

if [ "$CHOSEN" = "/" ] || [ "$CHOSEN" = "$HOME" ]; then
    echo "Refusing to install directly into '$CHOSEN'. Pick a dedicated folder."
    exit 1
fi

# The uninstaller deletes this folder, so never adopt a folder that already holds
# someone else's files: nest inside it instead.
INSTALL_DIR="$CHOSEN"
if [ ! -e "$CHOSEN/$MARKER" ] && [ ! -d "$CHOSEN/.git" ] && [ -n "$(ls -A "$CHOSEN")" ]; then
    INSTALL_DIR="$CHOSEN/$APP_ID"
    echo "'$CHOSEN' is not empty, so the app will go in '$INSTALL_DIR' instead."
fi
mkdir -p "$INSTALL_DIR"

say "Installing to $INSTALL_DIR"

# ---------------------------------------------------------------- toolchain
say "Checking Xcode command line tools (needed to build webrtcvad)"
if ! xcode-select -p >/dev/null 2>&1; then
    xcode-select --install || true
    echo "Finish the Xcode Command Line Tools installation in the popup, then run this installer again."
    exit 1
fi

say "Checking Homebrew"
for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$p" ] && eval "$("$p" shellenv)"
done
if ! command -v brew >/dev/null; then
    echo "Homebrew is not installed."
    if ask "Install Homebrew now (official installer from brew.sh)?"; then
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do
            [ -x "$p" ] && eval "$("$p" shellenv)"
        done
    else
        echo "Homebrew is required. Install it from https://brew.sh and re-run."; exit 1
    fi
fi

say "Installing dependencies with Homebrew"
for f in git python@3.12 ffmpeg portaudio; do
    brew list --formula "$f" >/dev/null 2>&1 || brew install "$f"
done
PY="$(brew --prefix python@3.12)/bin/python3.12"

if ! command -v ollama >/dev/null && [ ! -d "/Applications/Ollama.app" ]; then
    echo "Ollama is needed for question generation and grading."
    if [ "$NO_OLLAMA" = 1 ]; then
        echo "Skipping. Install it later from https://ollama.com"
    elif ask "Install Ollama with Homebrew now?"; then
        brew install --cask ollama
    else
        echo "Skipping. Install it later from https://ollama.com"
    fi
fi

# ---------------------------------------------------------------- source code
say "Fetching project into $INSTALL_DIR"
if [ -d "$INSTALL_DIR/.git" ]; then
    git -C "$INSTALL_DIR" pull --ff-only
else
    git clone "$REPO_URL" "$INSTALL_DIR"
fi
touch "$INSTALL_DIR/$MARKER"

# Remember where we installed so uninstall_macos.command can find it
mkdir -p "$CONFIG_DIR"
printf '%s\n' "$INSTALL_DIR" > "$PATH_FILE"

# ---------------------------------------------------------------- python venv
say "Creating virtual environment"
"$PY" -m venv "$INSTALL_DIR/.venv"
PIP="$INSTALL_DIR/.venv/bin/pip"
"$PIP" install --upgrade pip

REQ_SRC="$INSTALL_DIR/requirements.txt"
REQ_CLEAN="$INSTALL_DIR/.requirements.clean.txt"
MODEL_FILE="$INSTALL_DIR/.ollama_models.txt"

if [ -f "$REQ_SRC" ]; then
    # Strip stdlib modules / model notes that pip rejects
    "$PY" - "$REQ_SRC" "$REQ_CLEAN" "$MODEL_FILE" <<'PY'
import re, sys
src, dst, model_file = sys.argv[1:4]
std = set(getattr(sys, "stdlib_module_names", ())) | {
    "re", "unicodedata", "pathlib", "sys", "sqlite3", "os", "random", "time", "base64",
    "json", "shutil", "subprocess", "datetime", "collections", "threading", "io", "wave",
    "argparse",
}
skip = {"werkzeug"}
pkgs, models = [], []
for raw in open(src, encoding="utf-8"):
    line = raw.strip()
    # Model named in a comment, e.g. "# ... with the model: ollama pull qwen3:8b"
    pull = re.search(r"ollama\s+pull\s+([A-Za-z0-9_.:\-/]+)", line)
    if pull and pull.group(1) not in models:
        models.append(pull.group(1))
    if not line or line.startswith("#"):
        continue
    m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(.*)$", line)
    if not m:
        continue
    name, rest = m.groups()
    if name.split(".")[0] in std or name.split(".")[0] in skip:
        continue
    if rest.startswith("("):
        note = rest.strip("() ")
        if name == "ollama" and note:
            models.append(note)
        rest = ""
    spec = (name + rest).strip()
    if spec not in pkgs:
        pkgs.append(spec)
open(dst, "w").write("\n".join(pkgs) + "\n")
open(model_file, "w").write("\n".join(models) + ("\n" if models else ""))
PY
    "$PIP" install -r "$REQ_CLEAN"
else
    echo "No requirements.txt found; installing a minimal fallback set."
    "$PIP" install flask flask-login flask-mail flask-sqlalchemy itsdangerous markdown numpy \
        ollama sherpa-onnx noisereduce webrtcvad sounddevice pymupdf sqlalchemy requests
    echo "qwen3:8b" > "$MODEL_FILE"
fi

# Pull the Ollama model(s) named in requirements.txt
if [ -s "$MODEL_FILE" ] && { command -v ollama >/dev/null || [ -d "/Applications/Ollama.app" ]; }; then
    say "Pulling Ollama model(s)"
    open -a Ollama 2>/dev/null || true
    sleep 6
    OLLAMA_BIN="$(command -v ollama || echo /Applications/Ollama.app/Contents/Resources/ollama)"
    while read -r model; do
        [ -n "$model" ] && { "$OLLAMA_BIN" pull "$model" || echo "Could not pull $model. Make sure Ollama is running, then: ollama pull $model"; }
    done < "$MODEL_FILE"
fi

# ---------------------------------------------------------------- speech models
say "Downloading speech models (about 1.2 GB the first time; already-installed ones are skipped)"
MODEL_SCRIPT="$INSTALL_DIR/system/download_models.py"
if [ -f "$MODEL_SCRIPT" ]; then
    "$INSTALL_DIR/.venv/bin/python" "$MODEL_SCRIPT" || echo "Some speech models could not be downloaded. Re-run later with: $INSTALL_DIR/.venv/bin/python $MODEL_SCRIPT"
else
    echo "NOTE: system/download_models.py was not found in the project, so no speech models were installed."
fi

# ---------------------------------------------------------------- config / secrets
say "Setting up config"
if [ ! -f "$ENV_FILE" ]; then
    SECRET="$("$PY" -c 'import secrets; print(secrets.token_hex(32))')"
    cat > "$ENV_FILE" <<EOF
# Loaded by the launcher. Keep this file private.
SECRET_KEY=$SECRET
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=
MAIL_PASSWORD=
EOF
    chmod 600 "$ENV_FILE"
    echo "Created $ENV_FILE (fill in MAIL_USERNAME / MAIL_PASSWORD for email verification)"
else
    echo "Keeping existing $ENV_FILE"
fi

# ---------------------------------------------------------------- .app bundle
say "Creating $APP_BUNDLE"
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"

cat > "$APP_BUNDLE/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>$APP_NAME</string>
    <key>CFBundleDisplayName</key><string>$APP_NAME</string>
    <key>CFBundleIdentifier</key><string>local.$APP_ID</string>
    <key>CFBundleExecutable</key><string>$APP_ID</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleVersion</key><string>1.0</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>LSMinimumSystemVersion</key><string>11.0</string>
</dict>
</plist>
EOF

LAUNCHER="$APP_BUNDLE/Contents/MacOS/$APP_ID"
cat > "$LAUNCHER" <<'EOF'
#!/bin/bash
INSTALL_DIR="@INSTALL_DIR@"
ENV_FILE="@ENV_FILE@"
PORT=@PORT@
URL="http://127.0.0.1:$PORT"
PIDFILE="$HOME/Library/Caches/@APP_ID@.pid"

# Apps started from Finder get a minimal PATH; add Homebrew so ffmpeg/ollama are found
export PATH="/opt/homebrew/bin:/usr/local/bin:/Applications/Ollama.app/Contents/Resources:$PATH"

[ -f "$ENV_FILE" ] && { set -a; . "$ENV_FILE"; set +a; }

STARTED=0
if ! curl -s -o /dev/null "$URL"; then
    cd "$INSTALL_DIR/apps"
    "$INSTALL_DIR/.venv/bin/python" -c "
import home_app
home_app.app.run(host='127.0.0.1', port=$PORT, debug=False, threaded=True)
" >> "$INSTALL_DIR/server.log" 2>&1 &
    echo $! > "$PIDFILE"
    STARTED=1
    for _ in $(seq 1 120); do
        curl -s -o /dev/null "$URL" && break
        sleep 0.5
    done
fi

stop_server() { [ "$STARTED" = 1 ] && kill "$(cat "$PIDFILE")" 2>/dev/null && rm -f "$PIDFILE"; }

# App-style window with a Chromium browser (separate profile, so we can wait for it to close)
for b in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
    "/Applications/Chromium.app/Contents/MacOS/Chromium"; do
    if [ -x "$b" ]; then
        "$b" --app="$URL" --user-data-dir="$HOME/Library/Caches/@APP_ID@-profile" >/dev/null 2>&1
        stop_server
        exit 0
    fi
done

# Fallback: default browser (e.g. Safari) + a dialog that keeps the server alive until dismissed
open "$URL"
osascript -e 'display dialog "AI Interviewer is running in your browser. Click Stop when you are finished." with title "AI Interviewer" buttons {"Stop"} default button "Stop"' >/dev/null 2>&1
stop_server
EOF
sed -i.bak \
    -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" \
    -e "s|@ENV_FILE@|$ENV_FILE|g" \
    -e "s|@PORT@|$PORT|g" \
    -e "s|@APP_ID@|$APP_ID|g" \
    "$LAUNCHER" && rm -f "$LAUNCHER.bak"
chmod +x "$LAUNCHER"

say "Done!"
echo "Open '$APP_NAME' from ~/Applications, Launchpad or Spotlight."
echo "Installed in: $INSTALL_DIR"
echo "Logs:         $INSTALL_DIR/server.log"
echo "Config:       $ENV_FILE"
echo "First launch: macOS will ask for microphone access for your browser. Allow it."
echo "Remove:       run uninstall_macos.command"
