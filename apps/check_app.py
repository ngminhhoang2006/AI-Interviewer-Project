#!/usr/bin/env python3
import functools
import html
import os
import re
import unicodedata
from pathlib import Path
from flask import Flask, render_template, request, jsonify
import sys
import sqlite3

from i18n import init_i18n, t

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "system"))

try:
    import markdown
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False

try:
    import nh3  # HTML sanitizer
    HAS_SANITIZER = True
except ImportError:
    HAS_SANITIZER = False

app = Flask(
    __name__,
    template_folder=str(PROJECT_ROOT / "templates"),
    static_folder=str(PROJECT_ROOT / "static")
)
init_i18n(app)

UPLOAD_FOLDER = PROJECT_ROOT / "uploads"
DB_PATH = PROJECT_ROOT / "database.db"


@functools.lru_cache(maxsize=50000)
def flatten_text(text: str) -> str:
    """Normalizes text matching candidate folder names."""
    text = text.replace("\u00a0", " ").replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", stripped.casefold())


MAX_NAME_LEN = 100
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def validate_name(raw) -> str:
    """Validates a user-supplied candidate name. Raises ValueError with a safe message.

    This is input hygiene, not the SQL injection defence: quotes are allowed on purpose
    (names like O'Brien are legitimate). Injection is prevented by always passing user
    input to SQLite as bound parameters, never by building SQL strings.
    """
    if not isinstance(raw, str):
        raise ValueError(t("v.not_text"))
    name = raw.strip()
    if not name:
        raise ValueError(t("v.empty"))
    if len(name) > MAX_NAME_LEN:
        raise ValueError(t("v.too_long", max=MAX_NAME_LEN))
    if _CONTROL_CHARS.search(name):
        raise ValueError(t("v.invalid_chars"))
    return name


def _open_readonly_db() -> sqlite3.Connection:
    """The checker only ever reads, so open the database read-only (least privilege)."""
    return sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True, timeout=10)


def find_candidate_folders(name: str) -> list[Path]:
    """Finds candidate folders (directly inside the uploads folder) matching the search query."""
    target_flat = flatten_text(name)
    if not target_flat or not UPLOAD_FOLDER.exists():
        return []

    matches = []
    with os.scandir(UPLOAD_FOLDER) as entries:
        for entry in entries:
            if entry.is_dir():
                folder_flat = flatten_text(entry.name)
                if folder_flat and target_flat in folder_flat:
                    matches.append(Path(entry.path))

    return sorted(matches, key=lambda x: str(x))


def find_report_files(folder: Path) -> list[Path]:
    """Finds grading report files within a candidate's folder."""
    return sorted(folder.rglob("*_answers_report.md"))


@app.route("/", methods=["GET"])
def index():
    return render_template("checker.html")

def _read_score_rows():
    """Every stored result as (flattened name, row), oldest first. Read once per search request."""
    if not DB_PATH.exists():
        return []
    conn = _open_readonly_db()
    try:
        rows = conn.execute(
            "SELECT candidate_name, cv_score, interview_score, feedback_reason, created_at "
            "FROM interview_results ORDER BY id"
        ).fetchall()
    except sqlite3.Error as e:
        print(f"Database error while reading scores: {e}")
        return []
    finally:
        conn.close()
    flat_rows = [(flatten_text(r[0]) if isinstance(r[0], str) else "", r) for r in rows]
    return [(flat, r) for flat, r in flat_rows if flat]


def get_candidate_scores(candidate_name: str, rows=None):
    """Scores of the first stored result whose name contains the candidate's name or the reverse.

    Pass `rows` (from _read_score_rows) when looking up several names, so the table is read only once.
    """
    empty = {"cv_score": "N/A", "interview_score": "N/A", "feedback": "", "date": ""}
    target_flat = flatten_text(candidate_name)
    if not target_flat:
        return empty
    if rows is None:
        rows = _read_score_rows()
    for flat, row in rows:
        if target_flat in flat or flat in target_flat:
            # The keys are crossed on purpose: search_candidate swaps them back.
            return {
                "cv_score": str(row[2]) if row[2] is not None else "N/A",
                "interview_score": str(row[1]) if row[1] is not None else "N/A",
                "feedback": row[3] or "",
                "date": str(row[4]) if row[4] else "",
            }
    return empty


def extract_scores_from_md(report_path: Path):
    if not report_path.exists():
        return "N/A", "N/A"
    
    try:
        content = report_path.read_text(encoding="utf-8")
        
        # Matches numbers before optional /10 even inside markdown bolding (**Overall score: 7/10**)
        overall_match = re.search(r"Overall\s+score:\s*\*?\*?\s*([\d.]+)", content, re.IGNORECASE)
        avg_match = re.search(r"Average\s+per-question\s+score:\s*\*?\*?\s*([\d.]+)", content, re.IGNORECASE)
        
        cv_score = overall_match.group(1) if overall_match else "N/A"
        interview_score = avg_match.group(1) if avg_match else "N/A"
        
        return cv_score, interview_score
    except Exception as e:
        print(f"Error reading report {report_path}: {e}")
        return "N/A", "N/A"


@app.route("/api/search", methods=["POST"])
def search_candidate():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": t("e.invalid_request")}), 400
    try:
        query = validate_name(data.get("name", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    folders = find_candidate_folders(query)
    if not folders:
        return jsonify({"candidates": [], "message": t("e.no_match", query=query)})

    results = []
    upload_rel = UPLOAD_FOLDER.relative_to(PROJECT_ROOT)
    score_rows = None        # the database is read once, and only if some folder has no report on disk
    query_scores = None
    for f in folders:
        reports = find_report_files(f)
        
        cv_score = "N/A"
        interview_score = "N/A"
        
        # Prefer the Markdown report on disk; fall back to the database.
        if reports:
            cv_score, interview_score = extract_scores_from_md(reports[0])
            
        if cv_score == "N/A" or interview_score == "N/A":
            if score_rows is None:
                score_rows = _read_score_rows()
                query_scores = get_candidate_scores(query, score_rows)
            db_scores = query_scores
            if db_scores["cv_score"] == "N/A" and db_scores["interview_score"] == "N/A":
                db_scores = get_candidate_scores(f.name, score_rows)
            
            if cv_score == "N/A":
                # Swap back: get_candidate_scores returns the two columns crossed.
                cv_score = db_scores["interview_score"]
            if interview_score == "N/A":
                interview_score = db_scores["cv_score"]

        results.append({
            "folder_name": f.name,
            "folder_path": str(upload_rel / f.name),
            "reports": [r.name for r in reports],
            "cv_score": cv_score,
            "interview_score": interview_score
        })

    return jsonify({"candidates": results})


@app.route("/api/get_report", methods=["POST"])
def get_report():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": t("e.invalid_request")}), 400
    relative_folder = str(data.get("folder_path", ""))
    report_filename = str(data.get("report_filename", ""))

    folder_path = (PROJECT_ROOT / relative_folder).resolve()
    report_path = (folder_path / report_filename).resolve()

    # Only report files inside the uploads folder can be opened (also blocks "../" tricks)
    if (UPLOAD_FOLDER.resolve() not in report_path.parents
            or not report_path.name.endswith("_answers_report.md")):
        return jsonify({"error": "Access denied"}), 403

    if not report_path.exists():
        return jsonify({"error": t("e.report_missing")}), 404

    md_content = report_path.read_text(encoding="utf-8")

    # The report is LLM-written from candidate input, so it is untrusted and markdown passes raw HTML through.
    # Sanitize before rendering; without both packages, fall back to escaped plain text.
    if HAS_MARKDOWN and HAS_SANITIZER:
        html_content = nh3.clean(
            markdown.markdown(md_content, extensions=['tables', 'fenced_code'])
        )
    else:
        html_content = f"<pre>{html.escape(md_content)}</pre>"

    return jsonify({
        "candidate": folder_path.name,
        "filename": report_filename,
        "content_html": html_content,
        "content_raw": md_content
    })


if __name__ == "__main__":
    import os
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", host=os.environ.get("HOST", "127.0.0.1"), port=5001)