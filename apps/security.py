"""
Web-security hardening for the Flask app (XSS + CSRF defences).

Call `init_security(app, project_root)` once, right after the Flask app is created and
BEFORE any request is served. It sets up:

  * a real SECRET_KEY (from the SECRET_KEY env var, else a random key kept in database/.secret_key)
  * CSRF protection on every POST/PUT/PATCH/DELETE request (Flask-WTF)
  * hardened session cookies (HttpOnly, SameSite=Lax, Secure when served over HTTPS)
  * security headers, including a Content-Security-Policy that blocks inline scripts
  * a friendly error response when a CSRF check fails

Environment variables
  SECRET_KEY      signing key for sessions / CSRF tokens / reset links (set this in production)
  COOKIE_SECURE   set to 1 when the site is served over HTTPS (adds the Secure cookie flag + HSTS)
"""
import os
import secrets
from pathlib import Path

from flask import flash, jsonify, redirect, request, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect

csrf = CSRFProtect()

# Everything the pages load comes from this site (scripts, CSS, fetch calls). The one
# exception is the style attribute used throughout the templates, hence 'unsafe-inline'
# for styles ONLY. Scripts are 'self' only: injected <script> tags and inline on*= handlers
# will not run, which is the main safety net if an escaping bug ever slips through.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "media-src 'self' data: blob:",     # TTS audio comes back as a data: URL, mic test uses blob:
    "connect-src 'self'",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def _load_secret_key(project_root: Path) -> str:
    key = os.environ.get("SECRET_KEY")
    if key:
        return key

    # No env var: create a random key once and keep it, so sessions and password-reset
    # links survive restarts. (For production, or several workers, set SECRET_KEY instead.)
    key_file = project_root / "database" / ".secret_key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if key_file.exists():
        stored = key_file.read_text().strip()
        if stored:
            return stored
    key = secrets.token_hex(32)
    key_file.write_text(key)
    try:
        key_file.chmod(0o600)
    except OSError:
        pass  # e.g. Windows
    print("[security] SECRET_KEY not set - generated a random one in database/.secret_key")
    return key


def init_security(app, project_root: Path):
    # --- secret key (never fall back to a hard-coded value) ---------------------------
    app.config["SECRET_KEY"] = _load_secret_key(project_root)

    # --- cookies ----------------------------------------------------------------------
    secure_cookies = os.environ.get("COOKIE_SECURE", "0").lower() in ("1", "true", "yes")
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,      # JavaScript (so also any injected script) can't read it
        SESSION_COOKIE_SAMESITE="Lax",     # not sent on cross-site POSTs: first CSRF barrier
        SESSION_COOKIE_SECURE=secure_cookies,
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE="Lax",
        REMEMBER_COOKIE_SECURE=secure_cookies,
    )

    # --- CSRF tokens ------------------------------------------------------------------
    # None = the token lives as long as the session. A one-hour limit would break an
    # interview that runs longer than that when it saves the answers at the end.
    app.config["WTF_CSRF_TIME_LIMIT"] = None
    csrf.init_app(app)

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        message = "Your session expired or the request could not be verified. Please reload the page and try again."
        if request.is_json or request.path.startswith("/api/") or request.path in ("/upload_cv", "/generate_questions"):
            return jsonify({"error": message}), 400
        flash(message, "danger")
        if request.endpoint in (None, "logout"):
            return redirect(url_for("index"))
        return redirect(request.path)

    # --- security headers -------------------------------------------------------------
    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "microphone=(self), camera=(), geolocation=()")
        if secure_cookies:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    return app
