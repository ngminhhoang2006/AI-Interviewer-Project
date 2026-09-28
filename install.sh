#!/usr/bin/env bash
# AI Interviewer installer: clones the repo, builds a venv, adds an app-menu launcher.
# Usage: bash install.sh
set -euo pipefail

APP_NAME="AI Interviewer"
APP_ID="ai-interviewer"
REPO_URL="https://github.com/ngminhhoang2006/AI-Interviewer-Project.git"
PORT=5000

INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_ID"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/$APP_ID"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ENV_FILE="$CONFIG_DIR/env"
LAUNCHER="$BIN_DIR/$APP_ID"

say() { printf '\n==> %s\n' "$*"; }

# ---------------------------------------------------------------- system deps
say "Checking system dependencies"
missing=()
command -v git     >/dev/null || missing+=(git)
command -v python3 >/dev/null || missing+=(python3)
python3 -c "import venv, ensurepip" 2>/dev/null || missing+=(python3-venv)
command -v ffmpeg  >/dev/null || missing+=(ffmpeg)
command -v curl    >/dev/null || missing+=(curl)

if [ ${#missing[@]} -gt 0 ]; then
    echo "Missing packages: ${missing[*]}"
    if command -v apt-get >/dev/null; then
        read -r -p "Install them with apt now (needs sudo)? [Y/n] " ans
        if [[ "${ans:-Y}" =~ ^[Yy]$ ]]; then
            sudo apt-get update && sudo apt-get install -y "${missing[@]}"
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

# ---------------------------------------------------------------- python venv
say "Creating virtual environment"
python3 -m venv "$INSTALL_DIR/.venv"
PIP="$INSTALL_DIR/.venv/bin/pip"
"$PIP" install --upgrade pip

if [ -f "$INSTALL_DIR/requirements.txt" ]; then
    "$PIP" install -r "$INSTALL_DIR/requirements.txt"
else
    echo "No requirements.txt in the repo; installing the web-app packages I can see."
    "$PIP" install flask flask-login flask-mail flask-sqlalchemy itsdangerous markdown numpy
    echo
    echo "WARNING: the modules in system/ (cv_reader, chatbot, grade_interview, ...) need more"
    echo "         packages (sherpa-onnx, a PDF reader, the ollama client, etc.). Add them with:"
    echo "           $PIP install <package>"
    echo "         and consider committing a requirements.txt to your repo so this is automatic."
fi

# ---------------------------------------------------------------- config / secrets
say "Setting up config"
mkdir -p "$CONFIG_DIR" "$BIN_DIR" "$DESKTOP_DIR"
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
echo "Logs:   $INSTALL_DIR/server.log"
echo "Config: $ENV_FILE"
echo "Remove: bash uninstall.sh"
