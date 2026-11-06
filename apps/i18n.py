"""Interface translations for the whole site.

Catalogs live in locales/<code>.json (one flat key -> text file per language). English is the
fallback for any missing key. The language comes from the `ui_lang` cookie, then the browser's
Accept-Language header, then English.

    t("f.login_ok")                       plain text (Jinja escapes it)
    th("verify.sent", email=user_input)   catalog text that contains HTML; the parameters are escaped
"""
import json
from pathlib import Path

from flask import redirect, request
from markupsafe import Markup, escape

LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
COOKIE = "ui_lang"
DEFAULT = "en"

# code, name written in its own language
LANGUAGES = [
    ("en", "English"), ("vi", "Tiếng Việt"), ("es", "Español"), ("fr", "Français"),
    ("de", "Deutsch"), ("it", "Italiano"), ("pt", "Português"), ("ru", "Русский"),
    ("uk", "Українська"), ("pl", "Polski"), ("tr", "Türkçe"), ("id", "Bahasa Indonesia"),
    ("hi", "हिन्दी"), ("ar", "العربية"), ("zh", "中文"), ("ja", "日本語"),
    ("ko", "한국어"), ("th", "ไทย"),
]
RTL = {"ar"}
# strings outside the js.* group that the browser scripts also use
JS_EXTRA = {"setup.drop", "int.submit", "int.start_rec", "mic.record", "chk.report_h"}

_catalogs = {}
for _code, _ in LANGUAGES:
    _file = LOCALES_DIR / f"{_code}.json"
    if _file.exists():
        _catalogs[_code] = json.loads(_file.read_text(encoding="utf-8"))
CODES = [c for c, _ in LANGUAGES if c in _catalogs]


class _Keep(dict):
    """format_map helper: a placeholder with no value stays as written."""
    def __missing__(self, key):
        return "{" + key + "}"


def get_lang():
    """Language of the current request."""
    try:
        chosen = request.cookies.get(COOKIE)
        if chosen in _catalogs:
            return chosen
        for tag, _quality in request.accept_languages:
            primary = tag.replace("_", "-").split("-")[0].lower()
            if primary in _catalogs:
                return primary
    except RuntimeError:  # no request (scripts, tests)
        pass
    return DEFAULT


def _text(key, lang=None):
    lang = lang or get_lang()
    return _catalogs.get(lang, {}).get(key) or _catalogs[DEFAULT].get(key) or key


def t(key, lang=None, **params):
    """Translated plain text."""
    return _text(key, lang).format_map(_Keep(params)) if params else _text(key, lang)


def th(key, lang=None, **params):
    """Translated text that contains HTML. The catalog is trusted; the parameters are escaped."""
    safe = _Keep({k: escape(v) for k, v in params.items()})
    return Markup(_text(key, lang).format_map(safe))


def js_catalog(lang=None):
    """The strings the browser scripts need."""
    lang = lang or get_lang()
    return {k: t(k, lang) for k in _catalogs[DEFAULT] if k.startswith("js.") or k in JS_EXTRA}


def _safe_next(value):
    """Only same-site relative paths, so the language switch cannot redirect elsewhere."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return "/"


def init_i18n(app):
    @app.context_processor
    def inject_i18n():
        lang = get_lang()
        return {
            "t": t, "th": th, "ui_lang": lang, "ui_dir": "rtl" if lang in RTL else "ltr",
            "ui_languages": [(c, n) for c, n in LANGUAGES if c in _catalogs],
            "js_strings": js_catalog(lang),
        }

    @app.route("/set_language", methods=["POST"])
    def set_language():
        response = redirect(_safe_next(request.form.get("next", "")))
        chosen = request.form.get("lang", "")
        if chosen in _catalogs:
            response.set_cookie(COOKIE, chosen, max_age=365 * 24 * 3600, samesite="Lax",
                                secure=request.is_secure, path="/")
        return response

    return app
