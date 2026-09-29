#!/usr/bin/env bash
# AI Interviewer installer: clones the repo, builds a venv, adds an app-menu launcher.
#
# Usage:
#   bash install.sh                    # asks where to install (Enter = default)
#   bash install.sh --dir ~/apps/ai    # choose the folder on the command line
#   AI_INTERVIEWER_DIR=/opt/ai bash install.sh
set -euo pipefail

APP_NAME="AI Interviewer"
APP_ID="ai-interviewer"
REPO_URL="https://github.com/ngminhhoang2006/AI-Interviewer-Project.git"
PORT=5000
MARKER=".ai-interviewer-install"
ASSUME_YES=0

DEFAULT_INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_ID"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/$APP_ID"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ENV_FILE="$CONFIG_DIR/env"
PATH_FILE="$CONFIG_DIR/install_path"
LAUNCHER="$BIN_DIR/$APP_ID"

say() { printf '\n==> %s\n' "$*"; }

usage() {
    cat <<EOF
Usage: bash install.sh [--dir FOLDER]

  -d, --dir FOLDER   Install the app into FOLDER (created if missing).
  -y, --yes          Don't ask questions (auto-answer yes to installing missing packages).
  -h, --help         Show this help.

If no folder is given you will be asked. Default: $DEFAULT_INSTALL_DIR
You can also set AI_INTERVIEWER_DIR instead of passing --dir.
EOF
}

# ---------------------------------------------------------------- choose install folder
CHOSEN="${AI_INTERVIEWER_DIR:-}"
while [ $# -gt 0 ]; do
    case "$1" in
        -d|--dir)
            [ -n "${2:-}" ] || { echo "--dir needs a folder argument."; exit 1; }
            CHOSEN="$2"; shift 2 ;;
        --dir=*) CHOSEN="${1#--dir=}"; shift ;;
        -y|--yes) ASSUME_YES=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1"; usage; exit 1 ;;
    esac
done

if [ -z "$CHOSEN" ]; then
    if [ -t 0 ]; then
        read -r -p "Install location [$DEFAULT_INSTALL_DIR]: " CHOSEN
    fi
    CHOSEN="${CHOSEN:-$DEFAULT_INSTALL_DIR}"
fi

# Expand a leading ~
case "$CHOSEN" in
    "~")   CHOSEN="$HOME" ;;
    "~/"*) CHOSEN="$HOME/${CHOSEN#\~/}" ;;
esac

mkdir -p "$CHOSEN" || { echo "Cannot create $CHOSEN"; exit 1; }
CHOSEN="$(cd "$CHOSEN" && pwd)"   # absolute, symlinks resolved

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

# ---------------------------------------------------------------- system deps
say "Checking system dependencies"
missing=()
command -v git     >/dev/null || missing+=(git)
command -v python3 >/dev/null || missing+=(python3)
python3 -c "import venv, ensurepip" 2>/dev/null || missing+=(python3-venv)
command -v ffmpeg  >/dev/null || missing+=(ffmpeg)
command -v curl    >/dev/null || missing+=(curl)
if command -v dpkg >/dev/null; then
    # libportaudio2 -> sounddevice; build-essential/python3-dev -> webrtcvad compiles from source
    for p in libportaudio2 build-essential python3-dev; do
        dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p")
    done
fi

if [ ${#missing[@]} -gt 0 ]; then
    echo "Missing packages: ${missing[*]}"
    if command -v apt-get >/dev/null; then
        ans=Y
        [ "$ASSUME_YES" = 1 ] || read -r -p "Install them with apt now (needs sudo)? [Y/n] " ans
        if [[ "${ans:-Y}" =~ ^[Yy]$ ]]; then
            SUDO=(sudo)
            if [ -n "${AI_INTERVIEWER_GUI:-}" ]; then      # no terminal for a sudo prompt: use a graphical one
                command -v pkexec >/dev/null || { echo "pkexec not found. Install these packages manually and re-run: ${missing[*]}"; exit 1; }
                SUDO=(pkexec)
            fi
            "${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive sh -c 'apt-get update && apt-get install -y "$@"' _ "${missing[@]}"
        else
            echo "Please install them manually and re-run."; exit 1
        fi
    else
        echo "Install these with your package manager and re-run."; exit 1
    fi
fi

command -v ollama >/dev/null || {
    echo "NOTE: Ollama is not installed. The app needs it for question generation and grading."
    echo "      Install from https://ollama.com and pull the model your system/ code uses."
}

# ---------------------------------------------------------------- source code
say "Fetching project into $INSTALL_DIR"
if [ -d "$INSTALL_DIR/.git" ]; then
    git -C "$INSTALL_DIR" pull --ff-only
else
    git clone "$REPO_URL" "$INSTALL_DIR"
fi
touch "$INSTALL_DIR/$MARKER"

# Remember where we installed so uninstall.sh can find it
mkdir -p "$CONFIG_DIR" "$BIN_DIR" "$DESKTOP_DIR"
printf '%s\n' "$INSTALL_DIR" > "$PATH_FILE"

# ---------------------------------------------------------------- python venv
say "Creating virtual environment"
python3 -m venv "$INSTALL_DIR/.venv"
PIP="$INSTALL_DIR/.venv/bin/pip"
"$PIP" install --upgrade pip

REQ_SRC="$INSTALL_DIR/requirements.txt"
REQ_CLEAN="$INSTALL_DIR/.requirements.clean.txt"
MODEL_FILE="$INSTALL_DIR/.ollama_models.txt"

if [ -f "$REQ_SRC" ]; then
    # The repo's requirements.txt lists standard-library modules and notes like
    # "ollama (qwen3:8b)", which pip rejects. Clean it up before installing.
    python3 - "$REQ_SRC" "$REQ_CLEAN" "$MODEL_FILE" <<'PY'
import re, sys
src, dst, model_file = sys.argv[1:4]
std = set(getattr(sys, "stdlib_module_names", ())) | {
    "re", "unicodedata", "pathlib", "sys", "sqlite3", "os", "random", "time", "base64",
    "json", "shutil", "subprocess", "datetime", "collections", "threading", "io", "wave",
    "argparse",
}
skip = {"werkzeug"}  # installed automatically with Flask
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
    if rest.startswith("("):                      # e.g. "ollama (qwen3:8b)" -> a model note
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

# Pull the Ollama model(s) named in requirements.txt (e.g. qwen3:8b)
if command -v ollama >/dev/null && [ -s "$MODEL_FILE" ]; then
    say "Pulling Ollama model(s)"
    while read -r model; do
        [ -n "$model" ] && { ollama pull "$model" || echo "Could not pull $model. Start Ollama, then run: ollama pull $model"; }
    done < "$MODEL_FILE"
fi

# ---------------------------------------------------------------- config / secrets
say "Setting up config"
if [ ! -f "$ENV_FILE" ]; then
    SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    cat > "$ENV_FILE" <<EOF
# Loaded by the launcher. Keep this file private (chmod 600).
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

# ---------------------------------------------------------------- launcher
say "Writing launcher"
cat > "$LAUNCHER" <<'EOF'
#!/usr/bin/env bash
INSTALL_DIR="@INSTALL_DIR@"
ENV_FILE="@ENV_FILE@"
PORT=@PORT@
URL="http://127.0.0.1:$PORT"
PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/@APP_ID@.pid"

if [ "${1:-}" = "stop" ]; then
    [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null && rm -f "$PIDFILE" && echo "Stopped."
    exit 0
fi

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

# App-style window if a Chromium-based browser exists; the server stops when it closes.
for b in google-chrome google-chrome-stable chromium chromium-browser brave-browser microsoft-edge; do
    if command -v "$b" >/dev/null; then
        "$b" --app="$URL" --user-data-dir="$HOME/.cache/@APP_ID@-profile" >/dev/null 2>&1
        [ "$STARTED" = 1 ] && kill "$(cat "$PIDFILE")" 2>/dev/null && rm -f "$PIDFILE"
        exit 0
    fi
done

# Otherwise use the default browser; stop later with: @APP_ID@ stop
xdg-open "$URL" >/dev/null 2>&1
exit 0
EOF
sed -i \
    -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" \
    -e "s|@ENV_FILE@|$ENV_FILE|g" \
    -e "s|@PORT@|$PORT|g" \
    -e "s|@APP_ID@|$APP_ID|g" \
    "$LAUNCHER"
chmod +x "$LAUNCHER"

# ---------------------------------------------------------------- desktop entry
say "Creating app-menu entry"
ICON="applications-office"
[ -f "$INSTALL_DIR/static/icon.png" ] && ICON="$INSTALL_DIR/static/icon.png"

cat > "$DESKTOP_DIR/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=AI-powered technical interview portal
Exec=$LAUNCHER
Icon=$ICON
Terminal=false
Categories=Office;Education;
EOF
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "Note: add $BIN_DIR to your PATH to run '$APP_ID' from a terminal." ;; esac

say "Done!"
echo "Launch '$APP_NAME' from your app menu, or run: $APP_ID"
echo "Installed in: $INSTALL_DIR"
echo "Logs:         $INSTALL_DIR/server.log"
echo "Config:       $ENV_FILE"
echo "Remove:       bash uninstall.sh"
